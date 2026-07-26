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

from website.logical.declarative import (
    Definition,
    LinePart,
    LineSpec,
    Production,
    Rule,
    Subproof,
    SystemSpec,
)

from app.db.models import FormalSystem
from app.db.side_conditions_mapping import (
    build_rule_side_conditions,
    build_side_condition_rows,
    definition_condition_string,
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


def spec_to_system(spec: SystemSpec) -> FormalSystem:
    """Build the ORM graph for ``spec`` (unsaved; add it to a session to persist)."""

    system = FormalSystem(name=spec.name, slug=_slug(spec.name))

    for i, (opening, closing) in enumerate(spec.brackets):
        system.brackets.append(BracketRow(position=i, opening=opening, closing=closing))

    # Symbols share one namespace: union symbols (sorts) first, then productions.
    # `symbols` resolves any binding/definition/logical reference by name.
    symbols: dict[str, SymbolRow] = {}
    position = 0
    for name in spec.sort_names():
        symbol = SymbolRow(position=position, name=name, kind="union")
        symbols[name] = symbol
        system.symbols.append(symbol)
        position += 1

    production_symbols: list[tuple[Production, SymbolRow]] = []
    for prod in spec.productions:
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
        row = DefinitionRow(position=i, symbol=symbols[defn.sort], name=defn.name,
                            higher=defn.higher, lower=defn.lower, label=defn.label)
        for j, (var, sort) in enumerate(defn.bindings):
            row.bindings.append(DefinitionBindingRow(position=j, var=var, symbol=symbols[sort]))
        for j, (var, sort) in enumerate(defn.fresh):
            row.fresh.append(DefinitionFreshRow(position=j, var=var, symbol=symbols[sort]))
        build_side_condition_rows(row, defn.condition, symbols, {var for var, _ in defn.bindings})
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

    # Productions are the non-union symbols, in declaration (position) order;
    # each names its sort by the union it belongs to.
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
            condition=definition_condition_string(defn),
            fresh=[(f.var, f.symbol.name) for f in defn.fresh],
            label=defn.label,
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
