"""Tests for the rule `side_conditions:` source grammar (parse -> SideCondition)."""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import DisjointLeaves, Equal, IsAtom, Not, Occurs

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
