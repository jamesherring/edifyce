"""Tests for definitions as cited axioms (kernel step 4).

A definition is verified as a single unfold: ``check_definitional_step`` accepts
exactly a one-position rewrite between a defined form and its defining form (in
either direction), and rejects wrong expansions, no-ops, and two-at-once. The
defining form is multi-level (``∀z.(…→…)``), so these also exercise that a
definition schema keeps its grammatical structure (built via parse + abstract).
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.kernel import (
    Definition,
    DisjointLeaves,
    Var,
    check_definitional_step,
    from_match,
    match,
    unfold,
)
from website.logical.matching import Context, RegexPattern, StringPattern, UnionPattern


def build(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


# Set theory: membership, implication, a universal quantifier, and subset -
# enough to state df-subset as a genuinely multi-level definition.
SET_THEORY = """FormalSystem SetTheory:

    Regex setvar:
        ^[a-z]$

    Pattern membership:
        with x as setvar, y as setvar:
            (x ∈ y)

    UnionPattern formula:
        membership

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    formula:
        implication

    Pattern forall:
        with x as setvar, phi as formula:
            ∀x.phi

    formula:
        forall

    Pattern subset:
        with x as setvar, y as setvar:
            (x ⊆ y)

    formula:
        subset
"""


@pytest.fixture(scope="module")
def theory():
    system, context = build(SET_THEORY)
    return system, context


@pytest.fixture(scope="module")
def formula(theory):
    system, _context = theory
    return system.build_context.variables["formula"]


@pytest.fixture(scope="module")
def setvar(theory):
    system, _context = theory
    return system.build_context.variables["setvar"]


def term(theory, formula, string):
    _system, context = theory
    matched = formula.match(string, context)
    assert matched is not None, string
    return from_match(matched, context)


def df_subset(theory, setvar, condition=None):
    # (x ⊆ y)  :=  ∀z.((z ∈ x) → (z ∈ y))
    _system, context = theory
    formula = _system.build_context.variables["formula"]
    return Definition.parse(
        formula,
        "(x ⊆ y)",
        "∀z.((z ∈ x) → (z ∈ y))",
        {"x": setvar, "y": setvar},
        context,
        condition=condition,
    )


# ---------------------------------------------------------------------------
# unfold
# ---------------------------------------------------------------------------


def test_unfold_expands_the_defined_form(theory, formula, setvar):
    _system, context = theory
    result = unfold(df_subset(theory, setvar), term(theory, formula, "(a ⊆ b)"), context)
    assert result is not None
    assert result.to_string() == "∀z.((z ∈ a) → (z ∈ b))"


def test_unfold_returns_none_for_a_non_redex(theory, formula, setvar):
    _system, context = theory
    # A membership is not an instance of the definition's higher form.
    assert unfold(df_subset(theory, setvar), term(theory, formula, "(a ∈ b)"), context) is None


# ---------------------------------------------------------------------------
# check_definitional_step
# ---------------------------------------------------------------------------


def test_accepts_a_root_unfold(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    assert check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        d,
        context,
    )


def test_accepts_the_fold_direction(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Same step stated the other way round (contracting to the defined form).
    assert check_definitional_step(
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        term(theory, formula, "(a ⊆ b)"),
        d,
        context,
    )


def test_rejects_a_wrong_expansion(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    assert not check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ c))"),  # b became c
        d,
        context,
    )


def test_rejects_a_no_op(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    line = term(theory, formula, "(a ⊆ b)")
    # Identical terms: no rewrite happened, so it is not a definitional step.
    assert not check_definitional_step(line, line, d, context)


def test_unfolds_a_subterm(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Unfold the left conjunct of an implication, leaving the right untouched.
    assert check_definitional_step(
        term(theory, formula, "((a ⊆ b) → (c ⊆ d))"),
        term(theory, formula, "(∀z.((z ∈ a) → (z ∈ b)) → (c ⊆ d))"),
        d,
        context,
    )


def test_rejects_two_unfolds_at_once(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Both subset occurrences expanded: more than one position changed.
    assert not check_definitional_step(
        term(theory, formula, "((a ⊆ b) → (c ⊆ d))"),
        term(theory, formula, "(∀z.((z ∈ a) → (z ∈ b)) → ∀z.((z ∈ c) → (z ∈ d)))"),
        d,
        context,
    )


# ---------------------------------------------------------------------------
# A definition's side-condition gates the unfold
# ---------------------------------------------------------------------------


def test_side_condition_gates_the_unfold(theory, formula, setvar):
    # A definition may carry a step-3 proviso; here (illustrating the mechanism)
    # the two arguments must be distinct variables. The unfold only fires when
    # the proviso holds. (Genuine capture-avoidance over a bound variable needs
    # the binder-aware extension noted in side_conditions; this shows gating.)
    _system, context = theory
    d = df_subset(theory, setvar, condition=DisjointLeaves("x", "y", sort=setvar))

    # Distinct arguments: proviso holds, unfold applies.
    assert check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        d,
        context,
    )
    # Equal arguments: proviso fails, so there is no valid definitional step.
    assert unfold(d, term(theory, formula, "(a ⊆ a)"), context) is None
    assert not check_definitional_step(
        term(theory, formula, "(a ⊆ a)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ a))"),
        d,
        context,
    )


# ---------------------------------------------------------------------------
# A definition-only surface form still matches a variable of its sort
# ---------------------------------------------------------------------------


def test_definition_backed_subject_admits_its_sort():
    # A form reachable only through a definition on a union sort has an ad-hoc
    # `higher` constructor, but it still *inhabits* the union (e.g. `formula`).
    # A schematic variable of that sort must therefore bind to it.
    context = Context()
    setvar = RegexPattern("setvar", "^[a-z]$")
    membership = StringPattern("membership", "x in y", variables={"x": setvar, "y": setvar})
    formula = UnionPattern("formula", [membership])

    context.string_variables = {"x": setvar, "y": setvar}
    formula.add_definition(
        "x in y", "x is a member of y", context, require_lower_match=False
    )

    subject = from_match(formula.match("a is a member of b", context), context)
    # Its recorded sort is the union it belongs to, not its higher constructor.
    assert subject.sort is formula

    binding = match(Var("phi", formula), subject, context)
    assert binding is not None
    assert binding["phi"].to_string() == "a is a member of b"


# ---------------------------------------------------------------------------
# A definition is usable in both directions within a proof
# ---------------------------------------------------------------------------


def test_definition_used_in_both_directions(theory, formula, setvar):
    # A single definition supports both unfolding (defined -> defining) and
    # folding (defining -> defined), at the root and inside a larger formula -
    # the two directions a proof may cite df-subset.
    _system, context = theory
    d = df_subset(theory, setvar)

    subset = "(a ⊆ b)"
    expanded = "∀z.((z ∈ a) → (z ∈ b))"
    subset_in_context = "((a ⊆ b) → (c ⊆ d))"
    expanded_in_context = "(∀z.((z ∈ a) → (z ∈ b)) → (c ⊆ d))"

    steps = [
        (subset, expanded),                        # unfold, at the root
        (expanded, subset),                        # fold, at the root
        (subset_in_context, expanded_in_context),  # unfold, inside a larger formula
        (expanded_in_context, subset_in_context),  # fold, inside a larger formula
    ]

    for before, after in steps:
        b, a = term(theory, formula, before), term(theory, formula, after)
        # The two forms genuinely differ (so a direction was really applied)...
        assert not b.equal(a, context)
        # ...and the same definition `d` justifies the step either way.
        assert check_definitional_step(b, a, d, context), f"{before} -> {after}"
