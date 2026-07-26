"""Binding slots on productions, and the ``fresh`` clause they let the engine
infer.

A production declares which of its slots *bind* and over what
(``Production.scopes_over``). One thing reads it today: a definition's ``fresh``
clause — "which leaves of the defining form sit in a binder slot" — which is now
derivable from the parsed defining form rather than written by hand. See
``docs/binding-slots-design.md`` for the two uses this leaves open.

The load-bearing property throughout is that the declaration is *optional*: a
grammar that declares nothing infers nothing and behaves exactly as it did
before the field existed, which is what makes this safe for every stored system.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import DeclarativeError, SystemSpec, build_system
from website.logical.formal_system.definitions import DefinitionError, parse_definition
from website.logical.kernel import constructor_for, from_match, introduced_leaves, unfold
from tests.spec_helpers import brackets, regex_prod, statement_line, template_prod


# Set theory, as in test_definitions, but with `∀x.phi` free to declare that `x`
# binds over `phi`. `df-subset` is stated over it in both directions: with the
# declaration (so `fresh` can be inferred) and without (so it must be written).
def set_theory(scopes_over=None, extra_productions=()):
    return SystemSpec(
        name="SetTheory",
        brackets=brackets(),
        productions=[
            regex_prod("setvar", "letter", "[a-z]"),
            *extra_productions,
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod(
                "formula", "forall", "∀x.phi",
                [("x", "setvar"), ("phi", "formula")],
                scopes_over=scopes_over,
            ),
            template_prod("formula", "subset", "(x ⊆ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[statement_line()],
    )


def build(spec):
    system = build_system(spec)
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


@pytest.fixture(scope="module")
def binding_theory():
    return build(set_theory({"x": ["phi"]}))


@pytest.fixture(scope="module")
def plain_theory():
    return build(set_theory())


def df_subset(built, fresh=None):
    # (x ⊆ y)  :=  ∀z.((z ∈ x) → (z ∈ y)) — `z` is the binder, declared or not.
    system, context = built
    variables = system.build_context.variables
    return parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "∀z.((z ∈ x) → (z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
        fresh=fresh,
    )


def sorts(definition):
    return [(binder.name, binder.sort.name) for binder in definition.fresh]


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_a_production_projects_its_binding_slots(binding_theory):
    system, _context = binding_theory
    forall = constructor_for(system.build_context.variables["forall"])
    setvar = constructor_for(system.build_context.variables["setvar"])

    assert forall.scopes_over == {"x": ("phi",)}
    # The binder's sort comes off the slot, so a reader needs no second lookup.
    assert forall.slot_sorts["x"] is setvar


def test_an_undeclared_production_binds_nothing(plain_theory):
    system, _context = plain_theory
    forall = constructor_for(system.build_context.variables["forall"])

    assert forall.scopes_over == {}


@pytest.mark.parametrize(
    "scopes_over, message",
    [
        ({"nope": ["phi"]}, "has no such slot"),
        ({"x": ["nope"]}, "has no such slot"),
        ({"x": ["x"]}, "scopes over itself"),
    ],
)
def test_a_binding_slot_may_only_name_this_productions_slots(scopes_over, message):
    # Everything a binding slot can get wrong is decidable from the template, so
    # it is decided at build — the later stages read the declaration as fact.
    with pytest.raises(DeclarativeError, match=message):
        build_system(set_theory(scopes_over))


def test_a_declared_variable_that_occupies_no_slot_cannot_bind():
    # `psi` is declared but never appears in `∀x.phi`, so it holds no position a
    # binder could occupy.
    spec = set_theory()
    forall = next(p for p in spec.productions if p.name == "forall")
    forall.bindings.append(("psi", "formula"))
    forall.scopes_over = {"psi": ["phi"]}

    with pytest.raises(DeclarativeError, match="has no such slot"):
        build_system(spec)


def test_a_slot_that_scopes_over_nothing_is_not_a_binder():
    # Presence in the mapping is what marks a slot as binding, so an empty entry
    # must not create one — and it is not what storage would give back either,
    # since it records the scopes rather than the keys.
    system = build_system(set_theory({"x": []}))
    forall = constructor_for(system.build_context.variables["forall"])

    assert forall.scopes_over == {}


def test_an_atomic_production_cannot_declare_binding_slots():
    spec = set_theory()
    letter = next(p for p in spec.productions if p.name == "letter")
    letter.scopes_over = {"x": ["phi"]}

    with pytest.raises(DeclarativeError, match="atomic and has no template"):
        build_system(spec)


# ---------------------------------------------------------------------------
# What it buys: `fresh` read off the grammar
# ---------------------------------------------------------------------------


def test_fresh_is_inferred_from_the_binding_slot(binding_theory):
    # The whole point: no `fresh` clause, and `z` is still a binder — because the
    # grammar says the slot it sits in binds.
    assert sorts(df_subset(binding_theory)) == [("z", "setvar")]


def test_an_inferred_clause_is_the_declared_one(binding_theory):
    # Inference is not an approximation of the hand-written clause; it produces
    # the same definition, down to the interned term the two schemas share.
    inferred = df_subset(binding_theory)
    declared = df_subset(
        binding_theory, fresh={"z": binding_theory[0].build_context.variables["setvar"]}
    )

    assert inferred.fresh == declared.fresh
    assert inferred.lower is declared.lower
    assert inferred.higher is declared.higher


def test_an_inferred_binder_unfolds_capture_avoidingly(binding_theory):
    system, context = binding_theory
    formula = system.build_context.variables["formula"]
    matched = formula.match("(a ⊆ b)", context)
    assert matched is not None

    result = unfold(df_subset(binding_theory), from_match(matched), context)

    assert result is not None
    assert result.to_string() == "∀z.((z ∈ a) → (z ∈ b))"


def test_nothing_is_inferred_without_the_declaration(plain_theory):
    # The safe half of the contract: silence in the grammar is silence here, so a
    # system that declares no binding slots reads exactly as it did before they
    # existed — and `z` stays a name the defining form conjures.
    assert sorts(df_subset(plain_theory)) == []


def test_a_declared_binder_survives_an_undeclared_grammar(plain_theory):
    setvar = plain_theory[0].build_context.variables["setvar"]

    assert sorts(df_subset(plain_theory, fresh={"z": setvar})) == [("z", "setvar")]


def test_a_parameter_in_a_binder_slot_is_not_a_binder(binding_theory):
    # `x` sits in the binder slot, but the *defined* form supplies it, so an
    # unfold substitutes it rather than conjuring it. Only a leaf the defining
    # form names itself needs capture-avoidance.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "∀x.(x ∈ y)",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert definition.fresh == ()


def test_inference_adds_to_a_partial_declaration(binding_theory):
    # Two binders, one declared. Inference only ever adds, so the declared one
    # keeps its position (and hence its Bound index) and `w` joins it.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "∀z.(∀w.((w ∈ z) → (z ∈ x)) → (z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
        fresh={"z": variables["setvar"]},
    )

    assert sorts(definition) == [("z", "setvar"), ("w", "setvar")]


def test_an_occurrence_outside_the_scope_withholds_the_inference(binding_theory):
    # `z` is bound in the left branch and *free* in the right one. Abstracting it
    # would rename both together, so an unfold would capture a genuinely free
    # variable — the very thing a defining form may not do. Inference declines,
    # and the name goes back to being one the form conjures.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → (z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert definition.fresh == ()
    assert sorted(leaf.literal for leaf in introduced_leaves(definition)) == ["z"]


def test_a_declared_clause_still_reaches_outside_the_scope(binding_theory):
    # The author's own claim is honoured as it always was: a `fresh` clause is a
    # positive act, and only inference is held to the declared scope.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → (z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
        fresh={"z": variables["setvar"]},
    )

    assert sorts(definition) == [("z", "setvar")]


def test_a_second_binder_over_the_same_name_still_infers(binding_theory):
    # Every occurrence is in *some* binder's scope, which is what is asked — not
    # that one binder covers them all.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → ∀z.(z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "setvar")]


def two_binder_sorts():
    # `classvar` is strictly wider than `setvar`, and each has its own binder. A
    # name admitted by both can therefore reach a binder slot of either sort.
    return build(
        set_theory(
            {"x": ["phi"]},
            extra_productions=[
                regex_prod("classvar", "cletter", "[a-zA-Z]"),
                template_prod(
                    "formula", "cmembership", "(x ⋴ y)",
                    [("x", "classvar"), ("y", "setvar")],
                ),
                template_prod(
                    "formula", "exists", "∃x.phi",
                    [("x", "classvar"), ("phi", "formula")],
                    scopes_over={"x": ["phi"]},
                ),
            ],
        )
    )


def test_one_name_binding_at_two_sorts_is_refused():
    # A binder is one indexed node carrying one sort, and `bind` keys on the
    # surface string — so keeping the first and dropping the second would put a
    # `classvar` binder in `∀`'s `setvar` slot. Renaming it to `Q` then yields
    # `∀Q.(Q ∈ a)`, which this grammar cannot parse. Refused at build instead.
    built = two_binder_sorts()
    system, context = built
    variables = system.build_context.variables

    with pytest.raises(DefinitionError, match="two different sorts"):
        parse_definition(
            variables["formula"],
            "(x ⊆ y)",
            "(∃z.(z ⋴ y) → ∀z.(z ∈ x))",
            {"x": variables["setvar"], "y": variables["setvar"]},
            context,
        )


def test_a_repeated_binder_at_one_sort_is_still_one_binder(binding_theory):
    # The ordinary case the conflict check must not disturb: the same name bound
    # twice at the same sort is one binder, not a conflict.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → ∀z.(z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "setvar")]


def test_a_declared_sort_the_grammar_contradicts_is_refused():
    # `classvar` spells the same tokens as `setvar`, so `z` parses as one — but
    # the slot `∀` binds is a `setvar`, and both cannot be true.
    built = build(
        set_theory({"x": ["phi"]}, extra_productions=[regex_prod("classvar", "cletter", "[a-z]")])
    )
    system, _context = built

    with pytest.raises(DefinitionError, match="binder slot of sort 'setvar'"):
        df_subset(built, fresh={"z": system.build_context.variables["classvar"]})
