"""Programmatic ``SystemSpec`` builders for tests.

Formal systems in the test suite are assembled directly as
:class:`~website.logical.declarative.SystemSpec` objects — the "scripted
assembly" path — rather than parsed from a bespoke text syntax. These are the
shared building blocks; each test module composes the pieces its scenarios need
and, where it exercises a whole system, defines a small local factory.

Every helper returns a *fresh* object graph so specs never alias shared lists
across tests (some tests compare specs with ``==`` or round-trip them through
storage).
"""

from __future__ import annotations

from collections.abc import Iterable

from website.logical.declarative import (
    Definition,
    LinePart,
    LineSpec,
    Production,
    Rule,
    SystemSpec,
)

Binding = tuple[str, str]


# --- atomic constructors ---------------------------------------------------


def template_prod(
    sort: str, name: str, template: str, bindings: Iterable[Binding] = ()
) -> Production:
    """A composite (notation) production, e.g. ``formula | membership | s ∈ t``."""
    return Production(sort=sort, name=name, template=template, bindings=list(bindings))


def regex_prod(sort: str, name: str, regex: str) -> Production:
    """An atomic (leaf) production matched by a raw regex."""
    return Production(sort=sort, name=name, regex=regex)


def defn(
    sort: str,
    name: str,
    higher: str,
    lower: str,
    bindings: Iterable[Binding],
    condition: str | None = None,
) -> Definition:
    return Definition(
        sort=sort,
        name=name,
        higher=higher,
        lower=lower,
        bindings=list(bindings),
        condition=condition,
    )


def rule(
    label: str,
    name: str,
    antecedents: Iterable[str],
    deduction: str,
    bindings: Iterable[Binding],
    side_conditions: Iterable[str] = (),
) -> Rule:
    return Rule(
        label=label,
        name=name,
        antecedents=list(antecedents),
        deduction=deduction,
        bindings=list(bindings),
        side_conditions=list(side_conditions),
    )


def axiom(label: str, name: str, formula: str, bindings: Iterable[Binding] = ()) -> Rule:
    """An asserted axiom — a rule with no antecedents whose deduction is the formula."""
    return Rule(
        label=label,
        name=name,
        antecedents=[],
        deduction=formula,
        bindings=list(bindings),
    )


# --- common building blocks shared across systems --------------------------


def statement_line() -> LineSpec:
    """The ``<formula> [<reference>]`` logical line used by every test system."""
    return LineSpec(
        name="statement",
        shape="<formula> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,]+")],
        logical_sort="formula",
    )


def variable_prod() -> Production:
    return regex_prod("term", "variable", "[a-z][a-z0-9]*")


def membership_prod() -> Production:
    return template_prod("formula", "membership", "s ∈ t", [("s", "term"), ("t", "term")])


def equality_prod() -> Production:
    return template_prod("formula", "equality", "s = t", [("s", "term"), ("t", "term")])


def negation_prod() -> Production:
    return template_prod("formula", "negation", "¬p", [("p", "formula")])


def conjunction_prod() -> Production:
    return template_prod(
        "formula", "conjunction", "(p ∧ q)", [("p", "formula"), ("q", "formula")]
    )


def disjunction_prod() -> Production:
    return template_prod(
        "formula", "disjunction", "(p ∨ q)", [("p", "formula"), ("q", "formula")]
    )


def implication_prod() -> Production:
    return template_prod(
        "formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]
    )


def biconditional_prod() -> Production:
    return template_prod(
        "formula", "biconditional", "(p ↔ q)", [("p", "formula"), ("q", "formula")]
    )


def universal_prod() -> Production:
    return template_prod(
        "formula", "universal", "∀x p", [("x", "variable"), ("p", "formula")]
    )


def existential_prod() -> Production:
    return template_prod(
        "formula", "existential", "∃x p", [("x", "variable"), ("p", "formula")]
    )


def hyp_rule() -> Rule:
    """The hypothesis rule: assert any formula from no antecedents."""
    return rule("HYP", "hypothesis", [], "p", [("p", "formula")])


def mp_rule() -> Rule:
    """Modus ponens: from ``p`` and ``(p → q)`` infer ``q``."""
    return rule(
        "MP",
        "modus ponens",
        ["p", "(p → q)"],
        "q",
        [("p", "formula"), ("q", "formula")],
    )


def subset_def() -> Definition:
    """``x ⊆ y`` ≝ ``∀z (z ∈ x → z ∈ y)`` — the canonical layered definition."""
    return defn(
        "formula",
        "subset",
        "x ⊆ y",
        "∀z (z ∈ x → z ∈ y)",
        [("x", "variable"), ("y", "variable"), ("z", "variable")],
    )


def brackets() -> list[Binding]:
    """The single ``( )`` grouping pair every bracketed system declares."""
    return [("(", ")")]
