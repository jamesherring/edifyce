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
    Subproof,
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


def atom_const_prod(sort: str, name: str, value: str) -> Production:
    """An atom *constant* production: a sort member matching one literal token."""
    return Production(sort=sort, name=name, atom_value=value)


def atom_family_prod(sort: str, name: str, base: str) -> Production:
    """An atom *family* production: the infinite ``base_#`` (``p`` -> p, p_0, p_1, …)."""
    return Production(sort=sort, name=name, atom_base=base)


def defn(
    sort: str,
    name: str,
    higher: str,
    lower: str,
    bindings: Iterable[Binding],
    condition: str | None = None,
    fresh: Iterable[Binding] = (),
) -> Definition:
    return Definition(
        sort=sort,
        name=name,
        higher=higher,
        lower=lower,
        bindings=list(bindings),
        condition=condition,
        fresh=list(fresh),
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
    """The ``<formula> [<reference>]`` logical line used by every test system.

    The reference field allows ``.`` so a proof can cite a lemma imported from
    another proof with the engine's dotted navigation syntax (``[alias.line]``,
    or ``[RULE, alias.line, ...]``); without it such a citation won't even parse.
    """
    return LineSpec(
        name="statement",
        shape="<formula> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
        logical_sort="formula",
    )


def assumption_line() -> LineSpec:
    """An ``assume <formula>`` line that opens a hypothesis subproof (for →I).

    Both a formula-bearing logical line *and* a scope opener — the two concerns
    the engine keeps orthogonal. It carries no reference field: a scope opener is
    granted by fiat, so it cites nothing.
    """
    return LineSpec(
        name="assume",
        shape="assume <formula>",
        logical_sort="formula",
        scope="assumption",
    )


def reiteration_rule() -> Rule:
    """Reiteration (R): restate an in-scope formula. Exercises scope checking."""
    return rule("R", "reiteration", ["p"], "p", [("p", "formula")])


def cp_rule() -> Rule:
    """Conditional proof (→I): discharge a hypothesis subproof to an implication.

    Cites no lines — it consumes the whole subproof opened by ``assume p`` and
    concluded by ``q``, yielding ``(p → q)``.
    """
    return Rule(
        label="CP",
        name="conditional proof",
        antecedents=[],
        deduction="(p → q)",
        bindings=[("p", "formula"), ("q", "formula")],
        subproof=Subproof(assume="p", derive="q"),
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
