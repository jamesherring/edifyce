"""Tests for term interning - the shared-DAG representation (graph-rep step).

Terms are hash-consed: identical subterms are stored once, so structurally equal
terms built through the kernel are the *same* object and ``equal`` short-circuits
on identity. This is a pure optimisation - ``equal`` stays authoritative - so the
tests check both that sharing happens and that equality is unchanged, including
for hand-built (un-interned) terms.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_spec, build_system
from website.logical.kernel import Node, Var, from_match, intern, match
from website.logical.kernel.terms import _node
from website.logical.matching import StringPattern
from tests.spec_helpers import brackets, regex_prod, statement_line, template_prod
from tests.test_definition_step_bridge import alias_spec


def build(spec):
    system = build_system(spec)
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


# First-order logic with a single ASCII-arrow `implication` production over
# single-letter atoms — the grammar these interning tests build terms through.
FOPL = SystemSpec(
    name="FOPL",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z]"),
        template_prod("formula", "implication", "(p -> q)", [("p", "formula"), ("q", "formula")]),
    ],
    lines=[statement_line()],
)


@pytest.fixture(scope="module")
def fopl():
    system, context = build(FOPL)
    return system, context, system.build_context.variables["formula"]


def term(fopl, string):
    _system, context, formula = fopl
    matched = formula.match(string, context)
    assert matched is not None, string
    return from_match(matched, context)


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


def test_repeated_subterm_is_shared(fopl):
    # Both `a` leaves of (a -> a) are the same object.
    children = list(term(fopl, "(a -> a)").children.values())
    assert children[0] is children[1]


def test_equal_terms_intern_to_the_same_object(fopl):
    assert term(fopl, "(a -> b)") is term(fopl, "(a -> b)")
    assert term(fopl, "(a -> (b -> a))") is term(fopl, "(a -> (b -> a))")


def test_distinct_terms_are_distinct_objects(fopl):
    assert term(fopl, "(a -> b)") is not term(fopl, "(a -> c)")


def test_subterms_are_shared_across_formulas(fopl):
    big1 = term(fopl, "((a -> b) -> c)")
    big2 = term(fopl, "((a -> b) -> d)")
    ab1 = next(t for t in big1.children.values() if t.to_string() == "(a -> b)")
    ab2 = next(t for t in big2.children.values() if t.to_string() == "(a -> b)")
    assert ab1 is ab2


# ---------------------------------------------------------------------------
# intern() bridges hand-built terms into the shared DAG
# ---------------------------------------------------------------------------


def test_intern_bridges_a_hand_built_term(fopl):
    system, _context, formula = fopl
    implication = system.build_context.variables["implication"]
    atom = system.build_context.variables["atom"]

    # A term assembled by hand (not through a kernel producer) is not shared...
    hand = Node(implication, {"p": Node(atom, literal="a"), "q": Node(atom, literal="b")})
    assert hand is not term(fopl, "(a -> b)")

    # ...until interned, when it becomes the canonical shared instance.
    assert intern(hand) is term(fopl, "(a -> b)")


# ---------------------------------------------------------------------------
# Equality is unchanged - interning is only a fast path
# ---------------------------------------------------------------------------


def test_equal_still_holds_for_uninterned_terms(fopl):
    _system, context, formula = fopl
    system = _system
    atom = system.build_context.variables["atom"]
    implication = system.build_context.variables["implication"]

    hand = Node(implication, {"p": Node(atom, literal="a"), "q": Node(atom, literal="b")})
    canonical = term(fopl, "(a -> b)")

    # Different objects (hand is un-interned)...
    assert hand is not canonical
    # ...but structurally equal, via the fallback comparison, both directions.
    assert hand.equal(canonical, context)
    assert canonical.equal(hand, context)


def test_substitution_result_is_interned(fopl):
    system, context, formula = fopl
    implication = system.build_context.variables["implication"]
    schema = Node(implication, {"p": Var("p", formula), "q": Var("q", formula)})

    reified = schema.substitute(
        {"p": term(fopl, "a"), "q": term(fopl, "b")}, context
    )
    # The substituted term shares identity with the directly-parsed equal term.
    assert reified is term(fopl, "(a -> b)")


# ---------------------------------------------------------------------------
# The `sort` typing attribute is part of identity (equal ignores it, but
# interning must not merge two terms that differ in sort)
# ---------------------------------------------------------------------------


def test_nodes_differing_only_in_sort_are_not_merged(fopl):
    system, context, formula = fopl
    atom = system.build_context.variables["atom"]

    plain = intern(Node(atom, literal="a"))
    with_sort = intern(Node(atom, literal="a", sort=formula))

    # Interning keeps them distinct (sort is part of the key)...
    assert plain is not with_sort
    # ...even though `equal` ignores sort and calls them equal.
    assert plain.equal(with_sort, context)


def test_different_constructors_are_not_merged(fopl):
    # A substituted rule schema `(p -> q)` (an inline `antecedent` pattern) and a
    # parsed production `(a -> b)` (`implication`) share a signature and children,
    # but must not be interned to one object: they carry different sorts, and a
    # parsed formula must keep its production so sort admission still works -
    # regardless of which was built first.
    system, context, formula = fopl
    implication = system.build_context.variables["implication"]
    a, b = term(fopl, "a"), term(fopl, "b")

    schema_pattern = StringPattern(
        "antecedent", "(p -> q)", variables={"p": formula, "q": formula}
    )
    # Build the schema-substituted node FIRST, then the parsed production node.
    node_schema = _node(pattern=schema_pattern, children={"p": a, "q": b})
    node_production = _node(pattern=implication, children={"p": a, "q": b})

    assert node_schema is not node_production
    assert node_production.pattern is implication  # kept its production
    # ...and equal ignores the constructor identity, still calling them equal.
    assert node_schema.equal(node_production, context)
    # A formula variable therefore still binds to the parsed production node.
    assert match(Var("phi", formula), node_production, context) is not None


def test_defined_notation_interns_like_a_production():
    # A match made through a *definition* re-parents the sub-matches of its
    # defined form. Those must be shared, not copied: a copy used to carry a
    # copied `Pattern`, and since a node's interning key is its constructor's
    # identity, every definition-backed subterm then missed the table — so two
    # parses of `a sub b` built disjoint DAGs while `(a ∈ b)` shared one.
    system = build_spec(alias_spec())["system"]
    lines = system.parse("a sub b [HYP]\na sub b [HYP]").proof_lines
    first, second = (line.formula_term for line in lines)

    assert first is second
    assert all(first.children[label] is second.children[label] for label in first.children)
