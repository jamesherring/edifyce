"""Tests for first-order matching over terms (kernel step 2).

These cover:

1. ``match`` as the variable-binding counterpart of structural equality - it
   reduces to ``Term.equal`` when the schema has no variables, binds variables
   otherwise, enforces consistency and sorts.
2. ``match_all`` checking whole inference steps (modus ponens, conjunction
   introduction) over terms, deriving the binding a proof checker needs.
3. Invariants: the ``match`` -> ``substitute`` round-trip, alpha-renaming,
   deep nesting, near-English syntax, input immutability, and no re-parsing.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

import website.logical.matching.patterns as patterns
from website.logical.compiler import compile as compile_formal_system
from website.logical.kernel import Node, Var, from_match, from_pattern, match, match_all


def build(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


def rule(system, label):
    (found,) = [r for r in system.inference_rules if r.label == label]
    return found


# Implication + conjunction, with modus ponens and conjunction introduction.
RICH = """FormalSystem Rich:

    Regex atom:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    Pattern conjunction:
        with p as formula, q as formula:
            (p ∧ q)

    formula:
        implication
        conjunction

    with p as formula, q as formula:
        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p -> q)
            deduction:
                q

        InferenceRule conjunction_intro:
            label:
                CONJ
            antecedents:
                p
                q
            deduction:
                (p ∧ q)
"""

# A production names its slots lhs/rhs; the rule names them p/q.
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

# Near-English set membership.
SET_THEORY = """FormalSystem SetTheory:

    Regex setvar:
        ^[a-z]$

    Pattern membership:
        with x as setvar, y as setvar:
            x is an element of y

    UnionPattern formula:
        membership
"""


@pytest.fixture(scope="module")
def rich():
    system, context = build(RICH)
    return system, context, system.build_context.variables["formula"]


def term(formula, context, string):
    """Parse a formula string into a ground term."""
    matched = formula.match(string, context)
    assert matched is not None, string
    return from_match(matched, context)


# ---------------------------------------------------------------------------
# match as the variable-binding counterpart of equality
# ---------------------------------------------------------------------------


def test_match_binds_a_variable(rich):
    system, context, formula = rich
    schema = from_pattern(rule(system, "MP").antecedents[1], context)  # (p -> q)

    binding = match(schema, term(formula, context, "(a -> b)"), context)
    assert binding is not None
    assert {name: t.to_string() for name, t in binding.items()} == {"p": "a", "q": "b"}


@pytest.mark.parametrize(
    "left,right,equal",
    [
        ("(a -> b)", "(a -> b)", True),
        ("(a -> b)", "(a -> c)", False),
        ("(a ∧ b)", "(a ∧ b)", True),
        ("(a ∧ b)", "(a -> b)", False),  # different constructor
    ],
)
def test_match_reduces_to_equality_without_variables(rich, left, right, equal):
    _system, context, formula = rich
    a = term(formula, context, left)
    b = term(formula, context, right)

    # With no schema variables, match succeeds exactly when the terms are equal.
    assert (match(a, b, context) is not None) is equal
    assert a.equal(b, context) is equal


def test_match_enforces_consistent_repeated_variable(rich):
    system, context, formula = rich
    implication = system.build_context.variables["implication"]
    schema = Node(implication, {"p": Var("p", formula), "q": Var("p", formula)})  # (p -> p)

    assert match(schema, term(formula, context, "(a -> a)"), context) is not None
    assert match(schema, term(formula, context, "(a -> b)"), context) is None


def test_match_respects_sorts(rich):
    system, context, formula = rich
    atom = system.build_context.variables["atom"]

    atom_var = Var("z", atom)
    # An atom-sorted variable must not capture a compound implication.
    assert match(atom_var, term(formula, context, "(a -> b)"), context) is None
    # But it happily binds to an atom.
    assert match(atom_var, term(formula, context, "a"), context) is not None


def test_concrete_schema_does_not_match_opaque_variable(rich):
    _system, context, formula = rich
    implication = formula.patterns[0]
    schema = Node(implication, {"p": Var("p", formula), "q": Var("q", formula)})

    # Subject is a bare variable (opaque): a concrete production cannot match it.
    subject = Var("phi", formula)
    assert match(schema, subject, context) is None


def test_variable_binds_to_variable(rich):
    _system, context, formula = rich
    binding = match(Var("p", formula), Var("phi", formula), context)
    assert binding is not None and binding["p"].to_string() == "phi"


# ---------------------------------------------------------------------------
# match_all: checking whole inference steps
# ---------------------------------------------------------------------------


def test_modus_ponens_step_checks(rich):
    system, context, formula = rich
    mp = rule(system, "MP")
    antecedent1 = from_pattern(mp.antecedents[0], context)  # p
    antecedent2 = from_pattern(mp.antecedents[1], context)  # (p -> q)
    deduction = from_pattern(mp.deduction, context)         # q

    binding = match_all(
        [
            (antecedent1, term(formula, context, "a")),
            (antecedent2, term(formula, context, "(a -> b)")),
            (deduction, term(formula, context, "b")),
        ],
        context,
    )
    assert binding is not None
    assert {n: t.to_string() for n, t in binding.items()} == {"p": "a", "q": "b"}


def test_modus_ponens_rejects_wrong_conclusion(rich):
    system, context, formula = rich
    mp = rule(system, "MP")
    pairs = [
        (from_pattern(mp.antecedents[0], context), term(formula, context, "a")),
        (from_pattern(mp.antecedents[1], context), term(formula, context, "(a -> b)")),
        (from_pattern(mp.deduction, context), term(formula, context, "c")),  # not b
    ]
    assert match_all(pairs, context) is None


def test_modus_ponens_rejects_inconsistent_premises(rich):
    system, context, formula = rich
    mp = rule(system, "MP")
    # First premise says p = a; the implication says p = x. No consistent binding.
    pairs = [
        (from_pattern(mp.antecedents[0], context), term(formula, context, "a")),
        (from_pattern(mp.antecedents[1], context), term(formula, context, "(x -> b)")),
    ]
    assert match_all(pairs, context) is None


def test_two_antecedent_rule_checks(rich):
    system, context, formula = rich
    conj = rule(system, "CONJ")  # p, q |- (p ∧ q)
    pairs = [
        (from_pattern(conj.antecedents[0], context), term(formula, context, "a")),
        (from_pattern(conj.antecedents[1], context), term(formula, context, "b")),
        (from_pattern(conj.deduction, context), term(formula, context, "(a ∧ b)")),
    ]
    binding = match_all(pairs, context)
    assert binding is not None
    assert {n: t.to_string() for n, t in binding.items()} == {"p": "a", "q": "b"}

    # A conclusion that swaps the conjuncts is rejected.
    swapped = [
        (from_pattern(conj.antecedents[0], context), term(formula, context, "a")),
        (from_pattern(conj.antecedents[1], context), term(formula, context, "b")),
        (from_pattern(conj.deduction, context), term(formula, context, "(b ∧ a)")),
    ]
    assert match_all(swapped, context) is None


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_string,subject_string",
    [
        ("(p -> q)", "(a -> b)"),
        ("(p -> q)", "(a -> (b -> a))"),
        ("(p ∧ q)", "((a -> b) ∧ c)"),
        ("(p -> p)", "(a -> a)"),
    ],
)
def test_match_then_substitute_round_trips(rich, schema_string, subject_string):
    # If match(schema, subject) = σ then schema.substitute(σ) == subject.
    system, context, formula = rich
    implication = system.build_context.variables["implication"]
    conjunction = system.build_context.variables["conjunction"]
    p, q = Var("p", formula), Var("q", formula)

    if schema_string == "(p -> p)":
        schema = Node(implication, {"p": p, "q": p})
    elif schema_string == "(p ∧ q)":
        schema = Node(conjunction, {"p": p, "q": q})
    else:  # "(p -> q)"
        schema = Node(implication, {"p": p, "q": q})

    subject = term(formula, context, subject_string)
    binding = match(schema, subject, context)
    assert binding is not None
    assert schema.substitute(binding, context).equal(subject, context)


def test_alpha_renamed_schema_matches_production_instance():
    system, context = build(ALPHA_RENAMED)
    formula = system.build_context.variables["formula"]
    mp = rule(system, "MP")

    schema = from_pattern(mp.antecedents[1], context)  # (p -> q), keyed p/q
    subject = term(formula, context, "(a -> b)")       # keyed lhs/rhs
    binding = match(schema, subject, context)

    assert binding is not None
    assert {n: t.to_string() for n, t in binding.items()} == {"p": "a", "q": "b"}
    assert schema.substitute(binding, context).equal(subject, context)


def test_deeply_nested_match(rich):
    system, context, formula = rich
    schema = from_pattern(rule(system, "MP").antecedents[1], context)  # (p -> q)

    subject = term(formula, context, "(((a -> b) ∧ c) -> (d -> e))")
    binding = match(schema, subject, context)
    assert binding is not None
    assert binding["p"].to_string() == "((a -> b) ∧ c)"
    assert binding["q"].to_string() == "(d -> e)"


def test_near_english_matching():
    system, context = build(SET_THEORY)
    formula = system.build_context.variables["formula"]
    membership = system.build_context.variables["membership"]

    schema = from_pattern(membership, context)  # "x is an element of y"
    subject = term(formula, context, "a is an element of b")
    binding = match(schema, subject, context)

    assert binding is not None
    assert {n: t.to_string() for n, t in binding.items()} == {"x": "a", "y": "b"}


def test_match_does_not_mutate_input_binding(rich):
    system, context, formula = rich
    schema = from_pattern(rule(system, "MP").antecedents[1], context)

    original = {}
    result = match(schema, term(formula, context, "(a -> b)"), context, original)
    assert result is not None
    assert original == {}  # untouched
    assert result is not original


def test_match_never_reinvokes_the_matcher(rich, monkeypatch):
    system, context, formula = rich
    schema = from_pattern(rule(system, "MP").antecedents[1], context)
    subject = term(formula, context, "(a -> (b -> c))")

    calls = {"n": 0}
    for cls in (patterns.StringPattern, patterns.UnionPattern, patterns.RegexPattern):
        original = cls.match

        def counting_match(self, *args, _original=original, **kwargs):
            calls["n"] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "match", counting_match)

    for _ in range(300):
        assert match(schema, subject, context) is not None

    assert calls["n"] == 0
