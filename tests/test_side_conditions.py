"""Tests for the fixed side-condition vocabulary (kernel step 3).

These cover each proviso in the closed algebra - occurrence, leaf-disjointness,
atomicity, and the boolean combinators - as structural checks over terms, plus
two end-to-end rule checks (vacuous quantification gated by freshness, and a
disjoint-variables proviso) built on ``unify.match_all``.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_system
from website.logical.kernel import (
    And,
    constructor_for,
    DisjointLeaves,
    Equal,
    IsAtom,
    Not,
    Occurs,
    Or,
    from_match,
    from_pattern,
    match_all,
)
from tests.spec_helpers import brackets, regex_prod, rule as rule_spec, statement_line, template_prod


def build(spec):
    system = build_system(spec)
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


def rule(system, label):
    (found,) = [r for r in system.inference_rules if r.label == label]
    return found


# First-order logic: unary predicates, a binary relation, and a quantifier,
# with a vacuous-quantification rule and an identity rule over a relation.
# `setvar` and `predicate` are leaf sorts whose regex members are named
# distinctly from the sort. (The original also listed a bare predicate letter as
# a formula; nothing exercises that, and the declarative model reaches a leaf
# sort only through a wrapping production, so it is omitted.)
_RULE_BINDINGS = [("x", "setvar"), ("y", "setvar"), ("R", "predicate"), ("phi", "formula")]
FOL = SystemSpec(
    name="FOL",
    brackets=brackets(),
    productions=[
        regex_prod("setvar", "letter", "[a-z]"),
        regex_prod("predicate", "predicate_letter", "[A-Z]"),
        template_prod("formula", "application", "P(x)", [("P", "predicate"), ("x", "setvar")]),
        template_prod(
            "formula", "relation", "R(x, y)",
            [("R", "predicate"), ("x", "setvar"), ("y", "setvar")],
        ),
        template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
    ],
    lines=[statement_line()],
    rules=[
        rule_spec("VAC", "vacuous", ["phi"], "∀x.phi", _RULE_BINDINGS),
        rule_spec("DIST", "distinct_pair", ["R(x, y)"], "R(x, y)", _RULE_BINDINGS),
    ],
)


@pytest.fixture(scope="module")
def fol():
    system, context = build(FOL)
    return system, context


def formula_term(fol, string):
    system, context = fol
    formula = system.build_context.variables["formula"]
    matched = formula.match(string, context)
    assert matched is not None, string
    return from_match(matched)


def setvar_term(fol, string):
    system, context = fol
    setvar = system.build_context.variables["setvar"]
    return from_match(setvar.match(string, context))


# ---------------------------------------------------------------------------
# Occurrence / freshness
# ---------------------------------------------------------------------------


def test_occurs_finds_a_subterm(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(x)")}
    assert Occurs("x", "phi").check(binding, context)


def test_occurs_is_false_when_absent(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(y)")}
    assert not Occurs("x", "phi").check(binding, context)


def test_occurs_is_deep(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "z"), "phi": formula_term(fol, "∀y.R(z, y)")}
    assert Occurs("x", "phi").check(binding, context)


def test_freshness_is_negated_occurrence(fol):
    _system, context = fol
    absent = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(y)")}
    present = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(x)")}
    assert Not(Occurs("x", "phi")).check(absent, context)
    assert not Not(Occurs("x", "phi")).check(present, context)


# ---------------------------------------------------------------------------
# Distinctness ($d)
# ---------------------------------------------------------------------------


def test_distinct_variables(fol):
    _system, context = fol
    different = {"x": setvar_term(fol, "a"), "y": setvar_term(fol, "b")}
    same = {"x": setvar_term(fol, "a"), "y": setvar_term(fol, "a")}
    assert DisjointLeaves("x", "y").check(different, context)
    assert not DisjointLeaves("x", "y").check(same, context)


def test_distinct_is_symmetric(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "a"), "y": setvar_term(fol, "b")}
    assert DisjointLeaves("x", "y").check(binding, context) == DisjointLeaves("y", "x").check(binding, context)


def test_distinct_variable_sort_ignores_non_variable_symbols(fol):
    # P(x) and P(z) share the predicate symbol "P" but no *variable*. Restricting
    # to `setvar` makes DisjointLeaves a variable-occurrence check, so they count as
    # distinct; unrestricted, the shared "P" leaf makes them non-distinct.
    system, context = fol
    setvar = constructor_for(system.build_context.variables["setvar"])
    binding = {"a": formula_term(fol, "P(x)"), "b": formula_term(fol, "P(z)")}

    assert DisjointLeaves("a", "b", sort=setvar).check(binding, context)
    assert not DisjointLeaves("a", "b").check(binding, context)


def test_distinct_variable_and_formula_is_freshness(fol):
    # For a variable and a formula, DisjointLeaves(setvar) is the $d-style "x not in φ".
    system, context = fol
    setvar = constructor_for(system.build_context.variables["setvar"])
    fresh = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(y)")}
    captured = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(x)")}

    assert DisjointLeaves("x", "phi", sort=setvar).check(fresh, context)
    assert not DisjointLeaves("x", "phi", sort=setvar).check(captured, context)


# ---------------------------------------------------------------------------
# IsAtom and combinators
# ---------------------------------------------------------------------------


def test_is_atom(fol):
    # In FOL, IsAtom(x, setvar) asserts x stands for a variable, not a compound.
    system, context = fol
    setvar = constructor_for(system.build_context.variables["setvar"])
    binding = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(y)")}

    assert IsAtom("x").check(binding, context)
    assert IsAtom("x", sort=setvar).check(binding, context)
    assert not IsAtom("phi").check(binding, context)  # P(y) is compound


def test_boolean_combinators(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "x"), "phi": formula_term(fol, "P(y)")}
    fresh = Not(Occurs("x", "phi"))

    assert And((fresh, IsAtom("x"))).check(binding, context)
    assert not And((fresh, IsAtom("phi"))).check(binding, context)
    assert Or((Occurs("x", "phi"), fresh)).check(binding, context)
    assert not Or((Occurs("x", "phi"),)).check(binding, context)

    # Empty conjunction is vacuously true; empty disjunction vacuously false.
    assert And(()).check(binding, context)
    assert not Or(()).check(binding, context)


def test_equal_compares_terms_structurally(fol):
    _system, context = fol
    same = {"p": formula_term(fol, "P(x)"), "q": formula_term(fol, "P(x)")}
    different = {"p": formula_term(fol, "P(x)"), "q": formula_term(fol, "P(y)")}

    assert Equal("p", "q").check(same, context)
    assert not Equal("p", "q").check(different, context)
    # Distinctness is its negation.
    assert not Not(Equal("p", "q")).check(same, context)
    assert Not(Equal("p", "q")).check(different, context)


def test_equal_missing_binding_raises(fol):
    _system, context = fol
    with pytest.raises(ValueError, match="did not bind"):
        Equal("p", "missing").check({"p": setvar_term(fol, "x")}, context)


def test_malformed_condition_raises(fol):
    _system, context = fol
    binding = {"x": setvar_term(fol, "x")}
    with pytest.raises(ValueError, match="did not bind"):
        Occurs("x", "missing").check(binding, context)


def test_malformed_branch_raises_even_when_short_circuited(fol):
    # A malformed proviso must raise regardless of composition/order - a typo in
    # a later branch cannot be hidden by an earlier branch deciding the result.
    _system, context = fol
    binding = {"x": setvar_term(fol, "x")}  # 'phi' intentionally unbound
    malformed = Occurs("x", "phi")

    # Or: first branch true would short-circuit a generator; must still raise.
    with pytest.raises(ValueError, match="did not bind"):
        Or((IsAtom("x"), malformed)).check(binding, context)

    # And: first branch false would short-circuit a generator; must still raise.
    with pytest.raises(ValueError, match="did not bind"):
        And((Not(IsAtom("x")), malformed)).check(binding, context)

    # Nested/negated composition is no escape hatch either.
    with pytest.raises(ValueError, match="did not bind"):
        Not(Or((IsAtom("x"), malformed))).check(binding, context)


# ---------------------------------------------------------------------------
# End-to-end: side-conditions gating a rule over terms
# ---------------------------------------------------------------------------


def check_step(fol, label, premises_conclusion, condition):
    """Match a whole step, then apply the proviso - the shape a checker uses."""
    system, context = fol
    r = rule(system, label)
    schemas = [from_pattern(a) for a in r.antecedents] + [
        from_pattern(r.deduction)
    ]
    subjects = [formula_term(fol, s) for s in premises_conclusion]
    binding = match_all(list(zip(schemas, subjects)), context)
    return binding is not None and condition.check(binding, context)


def test_vacuous_quantification_gated_by_freshness(fol):
    fresh = Not(Occurs("x", "phi"))
    # φ = P(y): x not in φ, so ∀x.P(y) is a valid vacuous quantification.
    assert check_step(fol, "VAC", ["P(y)", "∀x.P(y)"], fresh)
    # φ = P(x): x occurs in φ, so the vacuous rule must not fire.
    assert not check_step(fol, "VAC", ["P(x)", "∀x.P(x)"], fresh)


def test_distinct_pair_proviso(fol):
    system, _context = fol
    setvar = constructor_for(system.build_context.variables["setvar"])
    distinct = DisjointLeaves("x", "y", sort=setvar)

    assert check_step(fol, "DIST", ["R(a, b)", "R(a, b)"], distinct)
    assert not check_step(fol, "DIST", ["R(a, a)", "R(a, a)"], distinct)
