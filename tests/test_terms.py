"""Tests for the parse-once term representation (kernel step 1).

These cover three things:

1. Faithfulness - a term reconstructs exactly the string it was parsed from,
   across first-order-logic and near-English (set-theory) surface syntax, so
   the representation imposes no restriction on what a system may express.
2. The operations that make the representation usable - structural equality,
   free variables, substitution - and a rule (modus ponens) applied entirely
   over terms.
3. The actual payoff - term operations never re-invoke the string matcher.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

import website.logical.matching.patterns as patterns
from website.logical.compiler import compile as compile_formal_system
from website.logical.kernel import Node, Var, from_match, from_pattern
from website.logical.matching import Context, RegexPattern, StringPattern, UnionPattern


def build(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    system = result["system"]

    # A proof-parsing context that can see the system's productions.
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


# First-order logic: atoms and a named `implication` production, plus modus
# ponens whose antecedents are written as a bare variable and an inline schema.
FOPL = """FormalSystem FOPL:

    Regex atom:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    formula:
        implication

    with p as formula, q as formula:
        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p -> q)
            deduction:
                q
"""

# A near-English set theory: membership and subset written the way a
# mathematician would say them, plus a definition of "subset".
SET_THEORY = """FormalSystem SetTheory:

    Regex setvar:
        ^[a-z]$

    Pattern membership:
        with x as setvar, y as setvar:
            x is an element of y

    UnionPattern formula:
        membership

    Pattern subset:
        with x as setvar, y as setvar:
            x is a subset of y
        Define x is a subset of y as x is an element of y

    formula:
        subset
"""


@pytest.fixture(scope="module")
def fopl():
    system, context = build(FOPL)
    return system, context, system.build_context.variables["formula"]


@pytest.fixture(scope="module")
def set_theory():
    system, context = build(SET_THEORY)
    return system, context, system.build_context.variables["formula"]


# ---------------------------------------------------------------------------
# Faithfulness: a term rebuilds exactly the string it came from
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "formula_string",
    ["a", "(a -> b)", "(a -> (b -> a))", "((a -> b) -> (b -> c))"],
)
def test_fopl_roundtrips(fopl, formula_string):
    _system, context, formula = fopl

    match = formula.match(formula_string, context)
    assert match is not None

    term = from_match(match, context)
    assert term.to_string() == match.formatted_string() == formula_string


@pytest.mark.parametrize(
    "formula_string",
    ["a is an element of b", "a is a subset of b"],
)
def test_near_english_roundtrips(set_theory, formula_string):
    _system, context, formula = set_theory

    match = formula.match(formula_string, context)
    assert match is not None

    term = from_match(match, context)
    # Arbitrary near-English surface syntax reconstructs exactly.
    assert term.to_string() == match.formatted_string() == formula_string


def test_union_coercion_is_collapsed(fopl):
    # `formula` is a UnionPattern; the term for an atom is the atom itself,
    # not a chain of union wrappers.
    _system, context, formula = fopl

    term = from_match(formula.match("a", context), context)
    assert isinstance(term, Node)
    assert term.pattern.name == "atom"
    assert term.literal == "a"


# ---------------------------------------------------------------------------
# Structural equality and free variables
# ---------------------------------------------------------------------------


def test_structural_equality_ground(fopl):
    _system, context, formula = fopl

    a = from_match(formula.match("(a -> (b -> a))", context), context)
    b = from_match(formula.match("(a -> (b -> a))", context), context)
    c = from_match(formula.match("(a -> (b -> b))", context), context)

    assert a.equal(b, context)
    assert not a.equal(c, context)


def test_ground_term_has_no_free_vars(fopl):
    _system, context, formula = fopl
    term = from_match(formula.match("(a -> b)", context), context)
    assert term.free_vars() == {}


def test_schema_exposes_free_vars(fopl):
    system, context, _formula = fopl
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # (p -> q)
    assert set(schema.free_vars()) == {"p", "q"}


# ---------------------------------------------------------------------------
# Substitution and a rule applied over terms
# ---------------------------------------------------------------------------


def test_substitution_applies_binding(fopl):
    system, context, formula = fopl
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # (p -> q)
    binding = {
        "p": from_match(formula.match("a", context), context),
        "q": from_match(formula.match("(b -> a)", context), context),
    }

    result = schema.substitute(binding, context)
    assert result.to_string() == "(a -> (b -> a))"
    assert result.free_vars() == {}


def test_modus_ponens_checks_over_terms(fopl):
    # Given the binding p := a, q := b, all three schema positions of MP
    # reconstruct the concrete proof lines - the rule "fires" without any
    # strings. (Deriving the binding by unification is kernel step 2.)
    system, context, formula = fopl
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    antecedent1 = from_pattern(mp.antecedents[0], context)  # p
    antecedent2 = from_pattern(mp.antecedents[1], context)  # (p -> q)
    deduction = from_pattern(mp.deduction, context)         # q

    binding = {
        "p": from_match(formula.match("a", context), context),
        "q": from_match(formula.match("b", context), context),
    }

    line1 = from_match(formula.match("a", context), context)
    line2 = from_match(formula.match("(a -> b)", context), context)
    line3 = from_match(formula.match("b", context), context)

    assert antecedent1.substitute(binding, context).equal(line1, context)
    assert antecedent2.substitute(binding, context).equal(line2, context)
    assert deduction.substitute(binding, context).equal(line3, context)

    # Negative control: the wrong conclusion does not check out.
    wrong = from_match(formula.match("c", context), context)
    assert not deduction.substitute(binding, context).equal(wrong, context)


def test_definition_slot_is_carried_through_substitution(fopl):
    # A node's `definition` is metadata for the future definitions-as-axioms
    # work; substitution must preserve it untouched.
    _system, context, formula = fopl

    sentinel = object()
    node = Node(
        pattern=formula.patterns[-1],  # the `implication` production
        children={
            "p": Var("p", formula),
            "q": Var("q", formula),
        },
        definition=sentinel,
    )

    substituted = node.substitute(
        {"p": from_match(formula.match("a", context), context)}, context
    )
    assert substituted.definition is sentinel


# A system whose `implication` production names its variables lhs/rhs, while
# the modus ponens rule names them p/q - so schema and production are the same
# constructor under alpha-renaming but spell their slots differently.
ALPHA_RENAMED = """FormalSystem AlphaRenamed:

    Regex atom:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        atom

    Pattern implication:
        with lhs as formula, rhs as formula:
            (lhs -> rhs)

    formula:
        implication

    with p as formula, q as formula:
        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p -> q)
            deduction:
                q
"""


def test_equality_aligns_slots_by_position_not_label():
    # Codex P2: a rule schema (p -> q) must equal a production instance built
    # from (lhs -> rhs) once substituted, even though the slot labels differ.
    system, context = build(ALPHA_RENAMED)
    formula = system.build_context.variables["formula"]
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # children keyed p, q
    ground = from_match(formula.match("(a -> b)", context), context)  # keyed lhs, rhs
    assert set(schema.free_vars()) == {"p", "q"}

    binding = {
        "p": from_match(formula.match("a", context), context),
        "q": from_match(formula.match("b", context), context),
    }
    assert schema.substitute(binding, context).equal(ground, context)

    # And a genuinely different instance still compares unequal.
    other = from_match(formula.match("(a -> c)", context), context)
    assert not schema.substitute(binding, context).equal(other, context)


def test_definition_backed_union_match_keeps_structure():
    # Codex P2: a formula parsed only through a definition attached to a union
    # sort must stay structured (children + definition), not collapse to an
    # opaque literal.
    context = Context()
    setvar = RegexPattern("setvar", "^[a-z]$")
    membership = StringPattern("membership", "x in y", variables={"x": setvar, "y": setvar})
    formula = UnionPattern("formula", [membership])

    context.string_variables = {"x": setvar, "y": setvar}
    definition = formula.add_definition(
        "x in y", "x is a member of y", context, require_lower_match=False
    )

    match = formula.match("a is a member of b", context)
    assert match.definition is not None  # matched via the definition

    term = from_match(match, context)
    # Structure preserved, definition carried, and it still round-trips.
    assert isinstance(term, Node)
    assert term.definition is definition
    assert term.to_string() == match.formatted_string() == "a is a member of b"
    assert {v.to_string() for v in term.children.values()} == {"a", "b"}


# ---------------------------------------------------------------------------
# The payoff: term operations do not re-parse
# ---------------------------------------------------------------------------


def test_term_operations_never_reinvoke_the_matcher(set_theory, monkeypatch):
    _system, context, formula = set_theory

    calls = {"n": 0}
    for cls in (patterns.StringPattern, patterns.UnionPattern, patterns.RegexPattern):
        original = cls.match

        def counting_match(self, *args, _original=original, **kwargs):
            calls["n"] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "match", counting_match)

    # Parsing once naturally calls match().
    term = from_match(formula.match("a is an element of b", context), context)
    assert calls["n"] > 0

    # Every subsequent term operation walks the tree - zero re-parses.
    calls["n"] = 0
    for _ in range(500):
        term.to_string()
        term.equal(term, context)
        term.substitute({}, context)
        term.free_vars()

    assert calls["n"] == 0
