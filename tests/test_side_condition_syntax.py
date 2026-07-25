"""Tests for the rule `side_conditions:` source grammar (parse -> SideCondition)."""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import LineSpec, SystemSpec, build_spec, build_system
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import (
    DisjointLeaves,
    Equal,
    IsAtom,
    IsMember,
    Not,
    Occurs,
    Or,
    constructor_for,
)
from tests.spec_helpers import regex_prod, rule


def sorts_spec() -> SystemSpec:
    # Two leaf sorts and a statement line — just enough grammar to hand the
    # proviso parser a context with `setvar` and `formula` in it. Each leaf's
    # member name differs from its sort name, or step 4 of build_system appends
    # the sort union to itself.
    return SystemSpec(
        name="Sorts",
        productions=[
            regex_prod("setvar", "var", "[a-z]"),
            regex_prod("formula", "atom", "[A-Z]"),
        ],
        lines=[LineSpec(name="statement", shape="<formula>", logical_sort="formula")],
    )


@pytest.fixture(scope="module")
def context():
    system = build_system(sorts_spec())
    ctx = copy(system.context)
    ctx.variables.update(system.build_context.variables)
    # Declare the metavariables these tests use, as a real rule's `with ... as`
    # clause would: an argument is a metavariable iff it is in `string_variables`,
    # otherwise the parser tries to read it as a literal term.
    setvar = ctx.variables["setvar"]
    ctx.string_variables = dict(ctx.string_variables)
    ctx.string_variables.update({name: setvar for name in ("x", "y", "p", "q", "phi")})
    return ctx


def test_occurs(context):
    assert parse_side_condition("occurs(x, phi)", context) == Occurs("x", "phi")


def test_equal(context):
    assert parse_side_condition("equal(p, q)", context) == Equal("p", "q")


def test_not_negates(context):
    assert parse_side_condition("not occurs(x, phi)", context) == Not(Occurs("x", "phi"))
    assert parse_side_condition("not equal(p, q)", context) == Not(Equal("p", "q"))


def test_disjoint_without_and_with_sort(context):
    setvar = constructor_for(context.variables["setvar"])
    assert parse_side_condition("disjoint(x, y)", context) == DisjointLeaves("x", "y", None)
    assert parse_side_condition("disjoint(x, phi, setvar)", context) == DisjointLeaves(
        "x", "phi", setvar
    )


def test_atom_without_and_with_sort(context):
    setvar = constructor_for(context.variables["setvar"])
    assert parse_side_condition("atom(x)", context) == IsAtom("x", None)
    assert parse_side_condition("atom(x, setvar)", context) == IsAtom("x", setvar)


def test_member_requires_a_sort(context):
    setvar = constructor_for(context.variables["setvar"])
    assert parse_side_condition("member(x, setvar)", context) == IsMember("x", setvar)


@pytest.mark.parametrize("text", ["member(x)", "member(x, y, z)", "member()"])
def test_member_wrong_arity_raises(context, text):
    # `member` needs exactly a name and a sort — no 1-arg form (the sort is the
    # whole point) and no 3-arg form.
    with pytest.raises(ValueError):
        parse_side_condition(text, context)


def test_member_unknown_sort_raises(context):
    with pytest.raises(ValueError, match="not a pattern"):
        parse_side_condition("member(x, nope)", context)


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


# A rule system whose single proviso is substituted per test, to check that a
# malformed one fails the build rather than silently leaving the rule
# unconstrained.
def rule_spec(proviso: str) -> SystemSpec:
    return SystemSpec(
        name="R",
        productions=[regex_prod("atom", "a", "[a-z]")],
        lines=[LineSpec(name="statement", shape="<atom>", logical_sort="atom")],
        rules=[rule("R", "r", (), "p", [("p", "atom"), ("q", "atom")], [proviso])],
    )


def _built_rule(proviso: str):
    (built,) = [
        r for r in build_system(rule_spec(proviso)).inference_rules if r.label == "R"
    ]
    return built


@pytest.mark.parametrize(
    "proviso",
    ["equal(p)", "equal(p, q, r)", "disjoint(p, q, nope)", "bogus(p, q)"],
)
def test_malformed_side_condition_fails_the_build(proviso):
    # A soundness guard: a bad proviso must surface as a build error (which
    # yields no system), never quietly leave the rule with empty side_conditions.
    result = build_spec(rule_spec(proviso))
    assert "errors" in result, result
    assert "system" not in result


def test_valid_side_condition_builds():
    assert _built_rule("equal(p, q)").side_conditions == [Equal("p", "q")]


def test_or_side_condition_builds():
    assert _built_rule("atom(p) or equal(p, q)").side_conditions == [
        Or((IsAtom("p", None), Equal("p", "q")))
    ]
