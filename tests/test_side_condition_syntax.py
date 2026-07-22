"""Tests for the rule `side_conditions:` source grammar (parse -> SideCondition)."""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import DisjointLeaves, Equal, IsAtom, Not, Occurs, Or

SYSTEM = """FormalSystem Sorts:

    Regex setvar:
        ^[a-z]$

    Regex formula:
        ^[A-Z]$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: formula
        behaviour: none
"""


@pytest.fixture(scope="module")
def context():
    result = compile_formal_system(SYSTEM)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    ctx = copy(system.context)
    ctx.variables.update(system.build_context.variables)
    return ctx


def test_occurs(context):
    assert parse_side_condition("occurs(x, phi)", context) == Occurs("x", "phi")


def test_equal(context):
    assert parse_side_condition("equal(p, q)", context) == Equal("p", "q")


def test_not_negates(context):
    assert parse_side_condition("not occurs(x, phi)", context) == Not(Occurs("x", "phi"))
    assert parse_side_condition("not equal(p, q)", context) == Not(Equal("p", "q"))


def test_disjoint_without_and_with_sort(context):
    setvar = context.variables["setvar"]
    assert parse_side_condition("disjoint(x, y)", context) == DisjointLeaves("x", "y", None)
    assert parse_side_condition("disjoint(x, phi, setvar)", context) == DisjointLeaves(
        "x", "phi", setvar
    )


def test_atom_without_and_with_sort(context):
    setvar = context.variables["setvar"]
    assert parse_side_condition("atom(x)", context) == IsAtom("x", None)
    assert parse_side_condition("atom(x, setvar)", context) == IsAtom("x", setvar)


def test_whitespace_is_tolerated(context):
    assert parse_side_condition("  occurs( x , phi )  ", context) == Occurs("x", "phi")


def test_or_forms_a_disjunction(context):
    assert parse_side_condition("atom(x) or equal(p, q)", context) == Or(
        (IsAtom("x", None), Equal("p", "q"))
    )


def test_or_chains_more_than_two(context):
    assert parse_side_condition("atom(x) or equal(p, q) or occurs(x, phi)", context) == Or(
        (IsAtom("x", None), Equal("p", "q"), Occurs("x", "phi"))
    )


def test_not_binds_tighter_than_or(context):
    # `not A or B` is `(not A) or B`, not `not (A or B)`.
    assert parse_side_condition("not occurs(x, phi) or equal(p, q)", context) == Or(
        (Not(Occurs("x", "phi")), Equal("p", "q"))
    )


def test_a_single_predicate_is_not_wrapped_in_or(context):
    # No `or` present ⇒ the bare condition, so existing provisos are unchanged.
    assert parse_side_condition("occurs(x, phi)", context) == Occurs("x", "phi")


@pytest.mark.parametrize("text", ["occurs(x, phi) or", "or occurs(x, phi)", "atom(x) or or atom(y)"])
def test_malformed_or_raises(context, text):
    with pytest.raises(ValueError):
        parse_side_condition(text, context)


@pytest.mark.parametrize(
    "text",
    [
        "occurs(x)",            # wrong arity
        "occurs(x, y, z)",      # wrong arity
        "equal(x)",             # wrong arity
        "atom()",               # no argument
        "bogus(x, y)",          # unknown predicate
        "occurs x, y",          # no parentheses
        "occurs(x, y",          # unbalanced
        "occurs(x,)",           # empty argument
    ],
)
def test_malformed_raises(context, text):
    with pytest.raises(ValueError):
        parse_side_condition(text, context)


def test_unknown_sort_raises(context):
    # `nope` is not a pattern in context.
    with pytest.raises(ValueError, match="not a pattern"):
        parse_side_condition("disjoint(x, y, nope)", context)


# A rule system whose single side-condition line is substituted per test, to
# check that a malformed proviso fails compilation rather than silently building
# an unconstrained rule.
RULE_SYSTEM = """FormalSystem R:

    Regex atom:
        ^[a-z]$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: atom
        behaviour: logical

    with p as atom, q as atom:
        InferenceRule r:
            label:
                R
            deduction:
                p
            side_conditions:
                {LINE}
"""


@pytest.mark.parametrize(
    "line",
    ["equal(p)", "equal(p, q, r)", "disjoint(p, q, nope)", "bogus(p, q)"],
)
def test_malformed_side_condition_fails_compilation(line):
    # A soundness guard: a bad proviso must surface as a compile error (which
    # yields no system), never quietly leave the rule with empty side_conditions.
    result = compile_formal_system(RULE_SYSTEM.replace("{LINE}", line))
    assert "errors" in result, result
    assert "system" not in result


def test_valid_side_condition_compiles():
    result = compile_formal_system(RULE_SYSTEM.replace("{LINE}", "equal(p, q)"))
    assert "errors" not in result, result.get("errors")
    (rule,) = [r for r in result["system"].inference_rules if r.label == "R"]
    assert rule.side_conditions == [Equal("p", "q")]


def test_or_side_condition_compiles():
    result = compile_formal_system(RULE_SYSTEM.replace("{LINE}", "atom(p) or equal(p, q)"))
    assert "errors" not in result, result.get("errors")
    (rule,) = [r for r in result["system"].inference_rules if r.label == "R"]
    assert rule.side_conditions == [Or((IsAtom("p", None), Equal("p", "q")))]
