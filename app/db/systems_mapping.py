"""Round trip between a declarative :class:`SystemSpec` and the ORM rows.

``spec_to_system`` explodes a ``SystemSpec`` into an ORM object graph ready to
persist; ``system_to_spec`` rebuilds an equal ``SystemSpec`` from a loaded row.
Because ``SystemSpec`` builds directly into a ``FormalSystem``
(``declarative.build_system``), this closes the loop
    rows -> SystemSpec -> FormalSystem
so the relational tables, not a text blob, are the source of truth.

The spec speaks in *names* (a production's sort, a binding's type). Storage
speaks in *symbols* (one namespace of sorts and productions, referenced by FK):
this module is where names are resolved to symbols on the way in and read back
from symbols on the way out, so the ``SystemSpec`` shape — and the engine
round-trip — is unchanged by the unified storage.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from website.logical.declarative import (
    Definition,
    Justification,
    LinePart,
    LineSpec,
    Production,
    Rule,
    Subproof,
    SystemSpec,
    layered_spec,
    library_digest,
)

from app.db.models import FormalSystem
from app.db.promoted_theorems_mapping import LibraryChain
from app.db.side_conditions_mapping import (
    build_definition_provisos,
    build_rule_side_conditions,
    definition_provisos_list,
    proviso_sorts,
    rule_side_conditions_list,
)
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    ProductionBindingScopeRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "system"


def _named_sorts(spec: SystemSpec) -> list[str]:
    """Every sort name ``spec`` needs a symbol for, in first-mention order.

    ``SystemSpec.sort_names`` reads the *productions*, which is what a system
    declaring its own grammar needs. A layer in an inheritance chain also
    **refers** to sorts it does not declare: ZFC's ``⊆`` is a ``formula`` over
    ``term``, and both of those are the layers below it. Storage resolves a
    name to a symbol by FK, so such a name still needs a row of its own —
    self-contained, rather than an FK into another system's namespace, which a
    parent's delete would take with it.

    What it leaves behind is a union row with no members, which is exactly what
    a *declared* sort of a layer looks like too, and which ``system_to_spec``
    emits nothing for either way. The sort itself comes back from the chain
    (`effective_spec`), where the layer that declares it is in front.
    """
    names = list(spec.sort_names())
    # A binding may name a *production* rather than a sort (`x : variable`), and
    # a production of this spec gets its own row below. Only a name nothing here
    # declares needs holding.
    declared = {prod.name for prod in spec.productions}

    def note(name: str | None) -> None:
        if name and name not in names and name not in declared:
            names.append(name)

    for prod in spec.productions:
        for _var, sort in prod.bindings:
            note(sort)
    for line in spec.lines:
        note(line.logical_sort)
    for defn in spec.definitions:
        note(defn.sort)
        for _var, sort in [*defn.bindings, *defn.fresh]:
            note(sort)
        # A proviso's sort argument is resolved to a symbol too — `disjoint(x, y,
        # setvar)` names a sort as surely as a binding does.
        for sort in proviso_sorts(defn.provisos):
            note(sort)
    for rule in [*spec.axioms, *spec.rules]:
        for _var, sort in rule.bindings:
            note(sort)
        for sort in proviso_sorts(rule.side_conditions):
            note(sort)
    return names


def spec_to_system(spec: SystemSpec) -> FormalSystem:
    """Build the ORM graph for ``spec`` (unsaved; add it to a session to persist)."""

    system = FormalSystem(
        name=spec.name, slug=_slug(spec.name), token_separated=spec.token_separated
    )

    for i, (opening, closing) in enumerate(spec.brackets):
        system.brackets.append(BracketRow(position=i, opening=opening, closing=closing))

    # Symbols share one namespace: union symbols (sorts) first, then productions.
    # `symbols` resolves any binding/definition/logical reference by name.
    symbols: dict[str, SymbolRow] = {}
    position = 0
    for name in _named_sorts(spec):
        symbol = SymbolRow(position=position, name=name, kind="union")
        symbols[name] = symbol
        system.symbols.append(symbol)
        position += 1

    production_symbols: list[tuple[Production, SymbolRow]] = []
    for prod in spec.productions:
        # A shapeless production naming a sort *includes* that sort into another —
        # `setvar_var` into `setvar`, so a Metamath `$v` reads as its typecode as
        # well as as a variable. That is membership, which this schema already has
        # an edge for, so record it on the sub-sort rather than inventing a second
        # symbol: symbols share one namespace, and a row named for a sort that
        # already exists violates `uq_symbols_system_name`.
        if prod.name in symbols and symbols[prod.name].kind == "union":
            symbols[prod.name].union = symbols[prod.sort]
            continue

        is_atom = prod.atom_value is not None or prod.atom_base is not None
        symbol = SymbolRow(
            position=position,
            name=prod.name,
            kind="regex" if prod.regex is not None else "atom" if is_atom else "composite",
            template=prod.template,
            regex=prod.regex,
            atom_value=prod.atom_value,
            atom_base=prod.atom_base,
            denotes_constant=prod.denotes_constant,
            union=symbols[prod.sort],
        )
        symbols[prod.name] = symbol
        system.symbols.append(symbol)
        production_symbols.append((prod, symbol))
        position += 1

    # Bindings are resolved after every symbol exists (a binding may reference a
    # production, e.g. `x : variable`, not only a sort).
    for prod, symbol in production_symbols:
        rows: dict[str, ProductionBindingRow] = {}
        for j, (var, sort) in enumerate(prod.bindings):
            rows[var] = ProductionBindingRow(position=j, var=var, symbol=symbols[sort])
            symbol.bindings.append(rows[var])
        # A binding slot points at *sibling slots of the same production*, so its
        # targets are the rows just built. Indexed rather than probed, on the same
        # assumption as the `symbols[sort]` lookups above: a spec reaching storage
        # names things that exist. A scope naming a slot the *template* lacks is a
        # different matter — it stores fine and fails at build
        # (`declarative._binding_scopes`), which is the draft-tolerant behaviour
        # every other part of a system already has.
        for var, scoped in prod.scopes_over.items():
            rows[var].scopes = [
                ProductionBindingScopeRow(position=j, scoped=rows[target])
                for j, target in enumerate(scoped)
            ]

    for i, line_spec in enumerate(spec.lines):
        logical = symbols[line_spec.logical_sort] if line_spec.logical_sort else None
        line = LineRow(position=i, name=line_spec.name, shape=line_spec.shape,
                       scope=line_spec.scope, behaviour=line_spec.behaviour,
                       logical_symbol=logical)
        for j, part in enumerate(line_spec.parts):
            line.parts.append(LinePartRow(position=j, name=part.name, regex=part.regex))
        system.lines.append(line)

    for i, defn in enumerate(spec.definitions):
        justification = defn.justification
        row = DefinitionRow(
            position=i, symbol=symbols[defn.sort], name=defn.name,
            higher=defn.higher, lower=defn.lower, label=defn.label,
            justification_label=justification.label if justification else None,
            justification_statement=justification.statement if justification else None,
        )
        for j, (var, sort) in enumerate(defn.bindings):
            row.bindings.append(DefinitionBindingRow(position=j, var=var, symbol=symbols[sort]))
        for j, (var, sort) in enumerate(defn.fresh):
            row.fresh.append(DefinitionFreshRow(position=j, var=var, symbol=symbols[sort]))
        build_definition_provisos(row, defn.provisos, symbols, {var for var, _ in defn.bindings})
        system.definitions.append(row)

    for i, axiom in enumerate(spec.axioms):
        row = AxiomRow(position=i, label=axiom.label, name=axiom.name, formula=axiom.deduction)
        for j, (var, sort) in enumerate(axiom.bindings):
            row.bindings.append(AxiomBindingRow(position=j, var=var, symbol=symbols[sort]))
        system.axioms.append(row)

    for i, rule in enumerate(spec.rules):
        subproof = rule.subproof
        row = RuleRow(
            position=i, label=rule.label, name=rule.name,
            deduction=rule.deduction, matching=rule.matching,
            subproof_derive=subproof.derive if subproof is not None else None,
            subproof_assume=subproof.assume if subproof is not None else None,
            subproof_fresh=subproof.fresh if subproof is not None else None,
            allow_extra_antecedents=rule.allow_extra_antecedents,
        )
        for j, antecedent in enumerate(rule.antecedents):
            row.antecedents.append(RuleAntecedentRow(position=j, pattern=antecedent))
        for j, (var, sort) in enumerate(rule.bindings):
            row.bindings.append(RuleBindingRow(position=j, var=var, symbol=symbols[sort]))
        build_rule_side_conditions(row, rule.side_conditions, symbols, {var for var, _ in rule.bindings})
        system.rules.append(row)

    return system


def system_to_spec(system: FormalSystem) -> SystemSpec:
    """Rebuild a :class:`SystemSpec` from a loaded :class:`FormalSystem`."""

    spec = SystemSpec(name=system.name)
    spec.brackets = [(b.opening, b.closing) for b in system.brackets]
    spec.token_separated = system.token_separated

    # Productions are the non-union symbols, in declaration (position) order;
    # each names its sort by the union it belongs to. A *union* that belongs to
    # one is a sub-sort included into it, which the spec spells as a shapeless
    # production (see spec_to_system); emit those last, so a sub-sort's own
    # members are declared before it joins its parent.
    spec.productions = [
        Production(
            sort=symbol.union.name,
            name=symbol.name,
            template=symbol.template,
            regex=symbol.regex,
            atom_value=symbol.atom_value,
            atom_base=symbol.atom_base,
            denotes_constant=symbol.denotes_constant,
            bindings=[(b.var, b.symbol.name) for b in symbol.bindings],
            scopes_over={
                b.var: [s.scoped.var for s in b.scopes]
                for b in symbol.bindings
                if b.scopes
            },
        )
        for symbol in system.symbols
        if symbol.kind != "union"
    ] + [
        Production(sort=symbol.union.name, name=symbol.name)
        for symbol in system.symbols
        if symbol.kind == "union" and symbol.union is not None
    ]

    spec.lines = [
        LineSpec(
            name=line.name,
            shape=line.shape,
            parts=[LinePart(name=part.name, regex=part.regex) for part in line.parts],
            logical_sort=line.logical_symbol.name if line.logical_symbol is not None else None,
            scope=line.scope,
            behaviour=line.behaviour,
        )
        for line in system.lines
    ]

    spec.definitions = [
        Definition(
            sort=defn.symbol.name,
            name=defn.name,
            higher=defn.higher,
            lower=defn.lower,
            bindings=[(b.var, b.symbol.name) for b in defn.bindings],
            provisos=definition_provisos_list(defn),
            fresh=[(f.var, f.symbol.name) for f in defn.fresh],
            label=defn.label,
            # Both columns are written together, so the label alone decides
            # whether there is an obligation; a statement without one is a row
            # nothing here could have produced.
            justification=(
                Justification(
                    label=defn.justification_label,
                    statement=defn.justification_statement or "",
                )
                if defn.justification_label is not None
                else None
            ),
        )
        for defn in system.definitions
    ]

    spec.axioms = [
        Rule(
            label=axiom.label,
            name=axiom.name,
            antecedents=[],
            deduction=axiom.formula,
            bindings=[(b.var, b.symbol.name) for b in axiom.bindings],
        )
        for axiom in system.axioms
    ]

    spec.rules = [
        Rule(
            label=rule.label,
            name=rule.name,
            antecedents=[a.pattern for a in rule.antecedents],
            deduction=rule.deduction,
            bindings=[(b.var, b.symbol.name) for b in rule.bindings],
            side_conditions=rule_side_conditions_list(rule),
            matching=rule.matching,
            subproof=_subproof_from_row(rule),
            allow_extra_antecedents=rule.allow_extra_antecedents,
        )
        for rule in system.rules
    ]

    return spec


def _subproof_from_row(rule: RuleRow) -> Subproof | None:
    # A discharge rule is exactly the one carrying a `subproof_derive`; rebuild
    # its Subproof from the three stored schema lines.
    if rule.subproof_derive is None:
        return None
    return Subproof(
        derive=rule.subproof_derive,
        assume=rule.subproof_assume,
        fresh=rule.subproof_fresh,
    )


def effective_spec(chain: Sequence[FormalSystem]) -> SystemSpec:
    """The spec a system is actually built from: its ancestors' parts, then its own.

    ``chain`` is the inheritance chain **root first**, ending in the system being
    built — what ``formal_systems.inherits_from_id`` describes, resolved. Each
    system contributes only its *own* rows (:func:`system_to_spec` is unchanged,
    because that is what the parts CRUD edits and what the API renders), and
    :func:`~website.logical.declarative.layered_spec` concatenates them.

    Raises :class:`~website.logical.declarative.DeclarativeError` when two layers
    collide on a name — see that function for why a name may be declared only
    once down a chain.
    """
    return layered_spec([system_to_spec(system) for system in chain])


def effective_library(chain: Sequence[FormalSystem]) -> tuple[SystemSpec, LibraryChain]:
    """What a system is built from, and where its citations resolve — in one pass.

    Both answers come from the same per-layer specs, and a verify needs both, so
    they are read together: reading the rows twice measured at five times the
    cost of reading them once, for a system with no ancestors at all.

    The spec is :func:`effective_spec`. The chain is **nearest first** — the rule
    that a label declared twice resolves to the closer system — and each layer
    carries the digest guarding *its own* stored terms, which for an ancestor is
    the digest of the ancestor's chain rather than the citing system's (see
    :class:`~app.db.promoted_theorems_mapping.LibraryChain`). Hence the running
    prefix: layer *i*'s digest covers layers 0..i.
    """
    specs = [system_to_spec(system) for system in chain]
    libraries = [
        (system.id, library_digest(layered_spec(specs[: index + 1])))
        for index, system in enumerate(chain)
    ]
    return layered_spec(specs), LibraryChain(tuple(reversed(libraries)))


def inherited_rule_count(chain: Sequence[FormalSystem]) -> int:
    """How many of :func:`effective_spec`'s rules belong to systems before the last.

    The ``offset`` :mod:`app.db.schema_terms` pairs one system's rule *rows* with
    the whole chain's spec by.
    """
    return sum(len(system.rules) for system in chain[:-1])


def inherited_definition_count(chain: Sequence[FormalSystem]) -> int:
    """The same, for definitions — :mod:`app.db.definition_terms`' ``offset``.

    A separate count rather than a shared one: :func:`effective_spec` concatenates
    each part list independently, so a chain's definitions and its rules are
    offset by different amounts.
    """
    return sum(len(system.definitions) for system in chain[:-1])
