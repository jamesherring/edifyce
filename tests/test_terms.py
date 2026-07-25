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
from website.logical.declarative import SystemSpec, build_system
from website.logical.kernel import Bound, Node, Var, abstract, bind, constructor_for, from_match, from_pattern
from website.logical.matching import Context, RegexPattern, StringPattern, UnionPattern
from tests.spec_helpers import (
    brackets,
    defn,
    regex_prod,
    rule,
    statement_line,
    template_prod,
)


def build(spec):
    system = build_system(spec)

    # A proof-parsing context that can see the system's productions.
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


# First-order logic: atoms and a named `implication` production, plus modus
# ponens whose antecedents are written as a bare variable and an inline schema.
# `atom` is a leaf member of `formula` (so `formula.patterns[0]` is the atom
# sort and `[-1]` the implication production — several tests index by position).
FOPL = SystemSpec(
    name="FOPL",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        template_prod("formula", "implication", "(p -> q)", [("p", "formula"), ("q", "formula")]),
    ],
    lines=[statement_line()],
    rules=[rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", [("p", "formula"), ("q", "formula")])],
)

# A near-English set theory: membership and subset written the way a
# mathematician would say them, plus a definition of "subset".
SET_THEORY = SystemSpec(
    name="SetTheory",
    productions=[
        # A leaf sort `setvar` (its regex member must be named distinctly from the
        # sort, else the sort union would list itself and recurse).
        regex_prod("setvar", "letter", "[a-z]"),
        template_prod(
            "formula", "membership", "x is an element of y", [("x", "setvar"), ("y", "setvar")]
        ),
    ],
    lines=[statement_line()],
    definitions=[
        defn(
            "formula",
            "subset",
            "x is a subset of y",
            "x is an element of y",
            [("x", "setvar"), ("y", "setvar")],
        )
    ],
)


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

    term = from_match(match)
    assert term.to_string() == match.string == formula_string


@pytest.mark.parametrize(
    "formula_string",
    ["a is an element of b", "a is a subset of b"],
)
def test_near_english_roundtrips(set_theory, formula_string):
    _system, context, formula = set_theory

    match = formula.match(formula_string, context)
    assert match is not None

    term = from_match(match)
    # Arbitrary near-English surface syntax reconstructs exactly.
    assert term.to_string() == match.string == formula_string


def test_union_coercion_is_collapsed(fopl):
    # `formula` is a UnionPattern; the term for an atom is the atom itself,
    # not a chain of union wrappers.
    _system, context, formula = fopl

    term = from_match(formula.match("a", context))
    assert isinstance(term, Node)
    assert term.constructor.name == "atom"
    assert term.literal == "a"


# ---------------------------------------------------------------------------
# Structural equality and free variables
# ---------------------------------------------------------------------------


def test_structural_equality_ground(fopl):
    _system, context, formula = fopl

    a = from_match(formula.match("(a -> (b -> a))", context))
    b = from_match(formula.match("(a -> (b -> a))", context))
    c = from_match(formula.match("(a -> (b -> b))", context))

    assert a.equal(b, context)
    assert not a.equal(c, context)


def test_ground_term_has_no_free_vars(fopl):
    _system, context, formula = fopl
    term = from_match(formula.match("(a -> b)", context))
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
        "p": from_match(formula.match("a", context)),
        "q": from_match(formula.match("(b -> a)", context)),
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
        "p": from_match(formula.match("a", context)),
        "q": from_match(formula.match("b", context)),
    }

    line1 = from_match(formula.match("a", context))
    line2 = from_match(formula.match("(a -> b)", context))
    line3 = from_match(formula.match("b", context))

    assert antecedent1.substitute(binding, context).equal(line1, context)
    assert antecedent2.substitute(binding, context).equal(line2, context)
    assert deduction.substitute(binding, context).equal(line3, context)

    # Negative control: the wrong conclusion does not check out.
    wrong = from_match(formula.match("c", context))
    assert not deduction.substitute(binding, context).equal(wrong, context)


# A system whose `implication` production names its variables lhs/rhs, while
# the modus ponens rule names them p/q - so schema and production are the same
# constructor under alpha-renaming but spell their slots differently.
ALPHA_RENAMED = SystemSpec(
    name="AlphaRenamed",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        template_prod(
            "formula", "implication", "(lhs -> rhs)", [("lhs", "formula"), ("rhs", "formula")]
        ),
    ],
    lines=[statement_line()],
    rules=[rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", [("p", "formula"), ("q", "formula")])],
)


def test_equality_aligns_slots_by_position_not_label():
    # Codex P2: a rule schema (p -> q) must equal a production instance built
    # from (lhs -> rhs) once substituted, even though the slot labels differ.
    system, context = build(ALPHA_RENAMED)
    formula = system.build_context.variables["formula"]
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # children keyed p, q
    ground = from_match(formula.match("(a -> b)", context))  # keyed lhs, rhs
    assert set(schema.free_vars()) == {"p", "q"}

    binding = {
        "p": from_match(formula.match("a", context)),
        "q": from_match(formula.match("b", context)),
    }
    assert schema.substitute(binding, context).equal(ground, context)

    # And a genuinely different instance still compares unequal.
    other = from_match(formula.match("(a -> c)", context))
    assert not schema.substitute(binding, context).equal(other, context)


def test_definition_backed_union_match_keeps_structure():
    # A formula parsed only through a definition attached to a union sort must
    # stay structured (built via the definition's higher form), not collapse to
    # an opaque literal. The term keeps no reference to the definition itself -
    # relating higher and lower forms is a cited step (see kernel.definitions).
    context = Context()
    setvar = RegexPattern("setvar", "^[a-z]$")
    membership = StringPattern("membership", "x in y", variables={"x": setvar, "y": setvar})
    formula = UnionPattern("formula", [membership])

    context.string_variables = {"x": setvar, "y": setvar}
    formula.add_notation("x is a member of y", context)

    match = formula.match("a is a member of b", context)
    assert match.sort is not None  # matched via defined notation

    term = from_match(match)
    # Structure preserved and it still round-trips, with no stored definition.
    assert isinstance(term, Node)
    assert not hasattr(term, "definition")
    assert term.to_string() == match.string == "a is a member of b"
    assert {v.to_string() for v in term.children.values()} == {"a", "b"}


# ---------------------------------------------------------------------------
# The payoff: term operations do not re-parse
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stress tests: richer systems, deep nesting, alpha-renaming, substitution
# ---------------------------------------------------------------------------


# A propositional system with several connectives (negation, conjunction,
# implication) sharing one `formula` union, plus a rule whose antecedent is a
# bare sort. Uses Unicode operators to also exercise multi-codepoint templates.
RICH = SystemSpec(
    name="Rich",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        template_prod("formula", "negation", "¬p", [("p", "formula")]),
        template_prod("formula", "conjunction", "(p ∧ q)", [("p", "formula"), ("q", "formula")]),
        template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
    ],
    lines=[statement_line()],
    # The antecedent is the bare sort `formula` — "any formula".
    rules=[rule("ANY", "any_formula", ["formula"], "p", [("p", "formula")])],
)


@pytest.fixture(scope="module")
def rich():
    system, context = build(RICH)
    return system, context, system.build_context.variables["formula"]


@pytest.mark.parametrize(
    "formula_string",
    [
        "¬a",
        "(a ∧ b)",
        "(a → b)",
        "¬(a → b)",
        "((a ∧ b) → (¬c → d))",
        "¬(a → (b ∧ ¬c))",
        "(((a → b) ∧ (b → c)) → (a → c))",
    ],
)
def test_rich_system_roundtrips(rich, formula_string):
    _system, context, formula = rich
    match = formula.match(formula_string, context)
    assert match is not None, formula_string

    term = from_match(match)
    assert term.to_string() == match.string == formula_string


def test_equality_distinguishes_constructors(rich):
    _system, context, formula = rich

    conjunction = from_match(formula.match("(a ∧ b)", context))
    implication = from_match(formula.match("(a → b)", context))
    negation = from_match(formula.match("¬a", context))
    atom = from_match(formula.match("a", context))

    # Same children, different constructor -> not equal.
    assert not conjunction.equal(implication, context)
    # Different arity / shape -> not equal.
    assert not negation.equal(atom, context)


def test_equality_is_deep(rich):
    _system, context, formula = rich

    a = from_match(formula.match("¬(a → (b ∧ ¬c))", context))
    b = from_match(formula.match("¬(a → (b ∧ ¬c))", context))
    # Differs only at the deepest leaf (c -> d).
    c = from_match(formula.match("¬(a → (b ∧ ¬d))", context))

    assert a.equal(b, context)
    assert not a.equal(c, context)


def test_repeated_subterm_is_not_confused_with_distinct(rich):
    _system, context, formula = rich
    same = from_match(formula.match("(a → a)", context))
    different = from_match(formula.match("(a → b)", context))
    assert not same.equal(different, context)


def test_from_pattern_bare_sort_antecedent_is_var(rich):
    system, context, _formula = rich
    (rule,) = [r for r in system.inference_rules if r.label == "ANY"]

    # The antecedent is written as the bare sort `formula` - i.e. "any formula".
    antecedent = from_pattern(rule.antecedents[0], context)
    assert isinstance(antecedent, Var)
    assert antecedent.sort.name == "formula"


@pytest.mark.parametrize(
    "formula_string",
    ["a", "¬a", "(a → b)", "¬(a → (b ∧ ¬c))", "(((a → b) ∧ (b → c)) → (a → c))"],
)
def test_parse_term_string_parse_is_idempotent(rich, formula_string):
    # Parse -> Term -> string -> parse -> Term yields an equal term. This
    # exercises from_match, to_string, and equal together on deep trees.
    _system, context, formula = rich

    first = from_match(formula.match(formula_string, context))
    second = from_match(formula.match(first.to_string(), context))
    assert first.equal(second, context)


def test_nested_substitution_and_free_var_dedup(fopl):
    # Build the schema (p -> (q -> p)) by reusing the implication production, and
    # check that a repeated variable is deduplicated in free_vars and that a
    # deep substitution rebuilds the expected term.
    _system, context, formula = fopl
    implication = formula.patterns[-1]  # the `implication` production

    inner = Node(constructor_for(implication), {"p": Var("q", formula), "q": Var("p", formula)})
    schema = Node(constructor_for(implication), {"p": Var("p", formula), "q": inner})

    assert set(schema.free_vars()) == {"p", "q"}

    binding = {
        "p": from_match(formula.match("a", context)),
        "q": from_match(formula.match("b", context)),
    }
    result = schema.substitute(binding, context)
    assert result.to_string() == "(a -> (b -> a))"
    assert result.free_vars() == {}


def test_partial_substitution_leaves_unbound_variables(fopl):
    system, context, formula = fopl
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # (p -> q)
    partial = schema.substitute(
        {"p": from_match(formula.match("a", context))}, context
    )

    assert partial.to_string() == "(a -> q)"
    assert set(partial.free_vars()) == {"q"}


def test_alpha_renaming_holds_at_depth():
    # A production names its slots lhs/rhs; a rule schema names them p/q. Nested
    # occurrences must still compare equal position-by-position.
    system, context = build(ALPHA_RENAMED)
    formula = system.build_context.variables["formula"]
    (mp,) = [r for r in system.inference_rules if r.label == "MP"]

    schema = from_pattern(mp.antecedents[1], context)  # (p -> q), keyed p/q
    binding = {
        "p": from_match(formula.match("a", context)),
        "q": from_match(formula.match("(a -> b)", context)),  # nested, keyed lhs/rhs
    }
    substituted = schema.substitute(binding, context)  # -> (a -> (a -> b))

    ground = from_match(formula.match("(a -> (a -> b))", context))  # keyed lhs/rhs throughout
    assert substituted.equal(ground, context)

    other = from_match(formula.match("(a -> (a -> c))", context))
    assert not substituted.equal(other, context)


def test_from_match_maps_variable_leaf_to_var():
    # A formula string that is itself a declared schematic variable (as happens
    # when a rule is checked against a formula) becomes a Var, not a literal.
    context = Context()
    atom = RegexPattern("atom", "^[a-z][a-z0-9]*$")
    formula = UnionPattern("formula", [atom])
    context.string_variables = {"phi": formula}

    match = formula.match("phi", context)
    assert match is not None and match.is_variable

    term = from_match(match)
    assert isinstance(term, Var)
    assert term.name == "phi"
    assert term.sort.name == "formula"


def test_deeply_nested_terms_do_not_reparse(rich, monkeypatch):
    # The no-reparse guarantee holds for a deep tree, not just a shallow one.
    _system, context, formula = rich
    term = from_match(
        formula.match("(((a → b) ∧ (b → c)) → (a → c))", context))

    calls = {"n": 0}
    for cls in (patterns.StringPattern, patterns.UnionPattern, patterns.RegexPattern):
        original = cls.match

        def counting_match(self, *args, _original=original, **kwargs):
            calls["n"] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "match", counting_match)

    for _ in range(200):
        term.to_string()
        term.equal(term, context)
        term.substitute({"a": term}, context)
        term.free_vars()

    assert calls["n"] == 0


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
    term = from_match(formula.match("a is an element of b", context))
    assert calls["n"] > 0

    # Every subsequent term operation walks the tree - zero re-parses.
    calls["n"] = 0
    for _ in range(500):
        term.to_string()
        term.equal(term, context)
        term.substitute({}, context)
        term.free_vars()

    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# abstract: parse a ground term, then lift parameter leaves into variables
# ---------------------------------------------------------------------------


def test_abstract_lifts_parameter_leaves_to_vars(fopl):
    # `(a -> b)` parsed ground, then abstract `a` into a variable p (leaving b).
    _system, context, formula = fopl
    ground = from_match(formula.match("(a -> b)", context))
    assert ground.free_vars() == {}

    atom = formula.patterns[0]  # the `atom` regex sort
    schema = abstract(ground, {"a": atom})

    assert set(schema.free_vars()) == {"a"}
    # Structure and rendering are preserved; only the leaf changed kind.
    assert schema.to_string() == "(a -> b)"
    # And it now behaves as a schema: matching binds the lifted variable.
    from website.logical.kernel import match

    binding = match(schema, from_match(formula.match("(c -> b)", context)), context)
    assert binding is not None and binding["a"].to_string() == "c"


def test_abstract_preserves_nested_structure(fopl):
    # Unlike from_pattern (one production level), abstract keeps a nested tree.
    _system, context, formula = fopl
    atom = formula.patterns[0]
    schema = abstract(
        from_match(formula.match("(a -> (b -> a))", context)),
        {"a": atom, "b": atom},
    )
    assert set(schema.free_vars()) == {"a", "b"}
    # Substituting the variables back reproduces a concrete nested formula.
    reified = schema.substitute(
        {
            "a": from_match(formula.match("x", context)),
            "b": from_match(formula.match("y", context)),
        },
        context,
    )
    assert reified.to_string() == "(x -> (y -> x))"


def test_bind_lifts_named_leaves_to_abstract_bound_nodes(fopl):
    # `bind` turns each ground leaf naming a bound variable into a shared,
    # indexed Bound node - and a Bound is bound, not free.
    _system, context, formula = fopl
    atom = formula.patterns[0]
    b0 = Bound(0, atom)

    schema = bind(from_match(formula.match("(a -> a)", context)), {"a": b0})

    # Both occurrences of `a` collapse to the *same* abstract node.
    children = list(schema.children.values())
    assert all(isinstance(child, Bound) for child in children)
    assert children[0] is children[1] is b0
    # A bound variable is not reported as a free parameter.
    assert schema.free_vars() == {}


def test_bound_instantiates_via_substitution(fopl):
    # A Bound behaves as a schematic leaf: matching recovers the concrete name
    # it takes, and substituting that binding instantiates it - the mechanics
    # the definition unfolder relies on.
    from website.logical.kernel import match

    _system, context, formula = fopl
    atom = formula.patterns[0]
    b0 = Bound(0, atom)
    schema = bind(from_match(formula.match("(a -> a)", context)), {"a": b0})

    # Recover the binder's concrete name by matching against a ground formula...
    binding = match(schema, from_match(formula.match("(c -> c)", context)), context)
    assert binding is not None
    # ...then substituting that binding instantiates every occurrence uniformly.
    assert schema.substitute(binding, context).to_string() == "(c -> c)"
