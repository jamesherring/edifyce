"""Round trip between a declarative :class:`SystemSpec` and the flat ORM rows.

``spec_to_system`` explodes a ``SystemSpec`` into an ORM object graph ready to
persist; ``system_to_spec`` rebuilds an equal ``SystemSpec`` from a loaded row.
Because ``SystemSpec`` lowers to ``.edi`` and compiles, this closes the loop
    rows -> SystemSpec -> (lower) -> FormalSystem
so the relational tables, not a text blob, become the source of truth.
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

from .models import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    FormalSystemRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    ProductionRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SortRow,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "system"


def spec_to_system(spec: SystemSpec) -> FormalSystemRow:
    """Build the ORM graph for ``spec`` (unsaved; add it to a session to persist)."""

    system = FormalSystemRow(name=spec.name, slug=_slug(spec.name))

    for i, (opening, closing) in enumerate(spec.brackets):
        system.brackets.append(BracketRow(position=i, opening=opening, closing=closing))

    # Sorts are first class and ordered by first appearance.
    sort_rows: dict[str, SortRow] = {}
    for i, name in enumerate(spec.sort_names()):
        row = SortRow(position=i, name=name)
        sort_rows[name] = row
        system.sorts.append(row)

    for i, prod in enumerate(spec.productions):
        row = ProductionRow(
            position=i,
            name=prod.name,
            kind="regex" if prod.regex is not None else "composite",
            template=prod.template,
            regex=prod.regex,
            sort=sort_rows[prod.sort],
        )
        for j, (var, sort) in enumerate(prod.bindings):
            row.bindings.append(ProductionBindingRow(position=j, var=var, sort=sort))
        system.productions.append(row)

    if spec.line is not None:
        line = LineRow(position=0, name=spec.line.name, shape=spec.line.shape,
                       logical_sort=spec.line.logical_sort)
        for j, part in enumerate(spec.line.parts):
            line.parts.append(LinePartRow(position=j, name=part.name, regex=part.regex))
        system.lines.append(line)

    for i, defn in enumerate(spec.definitions):
        row = DefinitionRow(position=i, sort=defn.sort, name=defn.name, higher=defn.higher,
                            lower=defn.lower, condition=defn.condition)
        for j, (var, sort) in enumerate(defn.bindings):
            row.bindings.append(DefinitionBindingRow(position=j, var=var, sort=sort))
        system.definitions.append(row)

    for i, axiom in enumerate(spec.axioms):
        row = AxiomRow(position=i, label=axiom.label, name=axiom.name, formula=axiom.deduction)
        for j, (var, sort) in enumerate(axiom.bindings):
            row.bindings.append(AxiomBindingRow(position=j, var=var, sort=sort))
        system.axioms.append(row)

    for i, rule in enumerate(spec.rules):
        row = RuleRow(position=i, label=rule.label, name=rule.name, deduction=rule.deduction)
        for j, antecedent in enumerate(rule.antecedents):
            row.antecedents.append(RuleAntecedentRow(position=j, pattern=antecedent))
        for j, (var, sort) in enumerate(rule.bindings):
            row.bindings.append(RuleBindingRow(position=j, var=var, sort=sort))
        system.rules.append(row)

    return system


def system_to_spec(system: FormalSystemRow) -> SystemSpec:
    """Rebuild a :class:`SystemSpec` from a loaded :class:`FormalSystemRow`."""

    spec = SystemSpec(name=system.name)
    spec.brackets = [(b.opening, b.closing) for b in system.brackets]

    spec.productions = [
        Production(
            sort=prod.sort.name,
            name=prod.name,
            template=prod.template,
            regex=prod.regex,
            bindings=[(b.var, b.sort) for b in prod.bindings],
        )
        for prod in system.productions
    ]

    if system.lines:
        line = system.lines[0]
        spec.line = LineSpec(
            name=line.name,
            shape=line.shape,
            parts=[LinePart(name=part.name, regex=part.regex) for part in line.parts],
            logical_sort=line.logical_sort,
        )

    spec.definitions = [
        Definition(
            sort=defn.sort,
            name=defn.name,
            higher=defn.higher,
            lower=defn.lower,
            bindings=[(b.var, b.sort) for b in defn.bindings],
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
            bindings=[(b.var, b.sort) for b in axiom.bindings],
        )
        for axiom in system.axioms
    ]

    spec.rules = [
        Rule(
            label=rule.label,
            name=rule.name,
            antecedents=[a.pattern for a in rule.antecedents],
            deduction=rule.deduction,
            bindings=[(b.var, b.sort) for b in rule.bindings],
        )
        for rule in system.rules
    ]

    return spec
