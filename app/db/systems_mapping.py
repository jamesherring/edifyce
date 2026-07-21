"""Round trip between a declarative :class:`SystemSpec` and the ORM rows.

``spec_to_system`` explodes a ``SystemSpec`` into an ORM object graph ready to
persist; ``system_to_spec`` rebuilds an equal ``SystemSpec`` from a loaded row.
Because ``SystemSpec`` lowers to ``.edi`` and compiles, this closes the loop
    rows -> SystemSpec -> (lower) -> FormalSystem
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
    SystemSpec,
)

from app.db.models import FormalSystem
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
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
        symbol = SymbolRow(
            position=position,
            name=prod.name,
            kind="regex" if prod.regex is not None else "composite",
            template=prod.template,
            regex=prod.regex,
            union=symbols[prod.sort],
        )
        symbols[prod.name] = symbol
        system.symbols.append(symbol)
        production_symbols.append((prod, symbol))
        position += 1

    # Bindings are resolved after every symbol exists (a binding may reference a
    # production, e.g. `x : variable`, not only a sort).
    for prod, symbol in production_symbols:
        for j, (var, sort) in enumerate(prod.bindings):
            symbol.bindings.append(ProductionBindingRow(position=j, var=var, symbol=symbols[sort]))

    if spec.line is not None:
        logical = symbols[spec.line.logical_sort] if spec.line.logical_sort else None
        line = LineRow(position=0, name=spec.line.name, shape=spec.line.shape, logical_symbol=logical)
        for j, part in enumerate(spec.line.parts):
            line.parts.append(LinePartRow(position=j, name=part.name, regex=part.regex))
        system.lines.append(line)

    for i, defn in enumerate(spec.definitions):
        row = DefinitionRow(position=i, symbol=symbols[defn.sort], name=defn.name,
                            higher=defn.higher, lower=defn.lower, condition=defn.condition)
        for j, (var, sort) in enumerate(defn.bindings):
            row.bindings.append(DefinitionBindingRow(position=j, var=var, symbol=symbols[sort]))
        system.definitions.append(row)

    for i, axiom in enumerate(spec.axioms):
        row = AxiomRow(position=i, label=axiom.label, name=axiom.name, formula=axiom.deduction)
        for j, (var, sort) in enumerate(axiom.bindings):
            row.bindings.append(AxiomBindingRow(position=j, var=var, symbol=symbols[sort]))
        system.axioms.append(row)

    for i, rule in enumerate(spec.rules):
        row = RuleRow(position=i, label=rule.label, name=rule.name, deduction=rule.deduction)
        for j, antecedent in enumerate(rule.antecedents):
            row.antecedents.append(RuleAntecedentRow(position=j, pattern=antecedent))
        for j, (var, sort) in enumerate(rule.bindings):
            row.bindings.append(RuleBindingRow(position=j, var=var, symbol=symbols[sort]))
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
            bindings=[(b.var, b.symbol.name) for b in symbol.bindings],
        )
        for symbol in system.symbols
        if symbol.kind != "union"
    ]

    if system.lines:
        line = system.lines[0]
        spec.line = LineSpec(
            name=line.name,
            shape=line.shape,
            parts=[LinePart(name=part.name, regex=part.regex) for part in line.parts],
            logical_sort=line.logical_symbol.name if line.logical_symbol is not None else None,
        )

    spec.definitions = [
        Definition(
            sort=defn.symbol.name,
            name=defn.name,
            higher=defn.higher,
            lower=defn.lower,
            bindings=[(b.var, b.symbol.name) for b in defn.bindings],
            condition=defn.condition,
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
        )
        for rule in system.rules
    ]

    return spec
