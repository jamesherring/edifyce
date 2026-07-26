"""Binding slots on productions, and the ``fresh`` clause they let the engine
infer.

A production declares which of its slots *bind* and over what
(``Production.scopes_over``). Two things read it. A definition's ``fresh``
clause — "which leaves of the defining form sit in a binder slot" — is derivable
from the parsed defining form rather than written by hand; and a
``denotes_constant`` declaration on a production the binder can *bind* is
refused, since a bindable token is a variable of the object language whatever
the author ticked. See ``docs/binding-slots-design.md`` for the use this leaves
open.

The load-bearing property throughout is that the declaration is *optional*: a
grammar that declares nothing infers nothing and behaves exactly as it did
before the field existed, which is what makes this safe for every stored system.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Definition as Definition_
from website.logical.declarative import (
    DeclarativeError,
    Production,
    SystemSpec,
    build_spec,
    build_system,
)
from website.logical.formal_system.definitions import DefinitionError, parse_definition
from website.logical.kernel import (
    check_definitional_step,
    constructor_for,
    from_match,
    introduced_leaves,
    unfold,
)
from tests.spec_helpers import (
    atom_const_prod,
    atom_family_prod,
    brackets,
    regex_prod,
    statement_line,
    template_prod,
)


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


def test_an_inferred_clause_builds_the_same_defining_form(binding_theory):
    # Inference and a hand-written clause agree on the *term*: for a form whose
    # binder scopes over the whole body, binding by scope and binding by name
    # place exactly the same nodes, down to the interned object.
    inferred = df_subset(binding_theory)
    declared = df_subset(
        binding_theory, fresh={"z": binding_theory[0].build_context.variables["setvar"]}
    )

    assert inferred.lower is declared.lower
    assert inferred.higher is declared.higher
    assert sorts(inferred) == sorts(declared) == [("z", "setvar")]
    # They differ in how the binder was *placed*, which is what decides its scope
    # and so which other binders it must differ from.
    assert [b.scoped for b in inferred.fresh] == [True]
    assert [b.scoped for b in declared.fresh] == [False]


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


def test_an_occurrence_outside_the_scope_stays_free(binding_theory):
    # `z` is bound in the left branch and *free* in the right one. Binding by
    # scope reaches only the first: the free occurrence stays a ground leaf, and
    # `introduced_leaves` reports it as the name the form conjures — so the
    # definition is still refused, now for the reason that is actually true of it.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → (z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "setvar")]
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


def test_two_binders_over_one_name_are_two_binders(binding_theory):
    # Sharing a spelling does not make them one binder. Each binding occurrence
    # gets its own indexed node, which is what lets a step spell them differently.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∀z.(z ∈ x) → ∀z.(z ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "setvar"), ("z", "setvar")]
    # Siblings, so neither encloses the other — and neither need differ from the
    # other when a step names them.
    assert [b.enclosing for b in definition.fresh] == [(), ()]


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


def test_one_name_at_two_sorts_is_two_binders():
    # The payoff, and what the name-keyed representation could not express. Each
    # binding occurrence carries its slot's own sort, so `∃`'s `classvar` binder
    # and `∀`'s `setvar` binder are distinct — where before, one was stored and
    # the other silently received it, giving a term the grammar cannot parse once
    # the binder is renamed.
    system, context = two_binder_sorts()
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∃z.(z ⋴ y) → ∀z.(z ∈ x))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "classvar"), ("z", "setvar")]


def test_two_binders_of_different_sorts_may_be_named_apart():
    # And the consequence a step can see: the two are independently nameable, so
    # a target that spells them differently checks. `Q` is a `classvar` and not a
    # `setvar`, which is exactly the naming the shared binder made impossible.
    system, context = two_binder_sorts()
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "(∃z.(z ⋴ y) → ∀z.(z ∈ x))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    def term(text):
        matched = variables["formula"].match(text, context)
        assert matched is not None, text
        return from_match(matched)

    assert check_definitional_step(
        term("(a ⊆ b)"), term("(∃Q.(Q ⋴ b) → ∀w.(w ∈ a))"), definition, context
    )

def test_a_nested_binder_records_the_one_it_sits_inside(binding_theory):
    # Nesting is what the freshness proviso needs: an inner binder spelled like
    # the one it sits inside would shadow it, so those two must differ while
    # siblings need not.
    system, context = binding_theory
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "∀z.∀w.((z ∈ x) → (w ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert sorts(definition) == [("z", "setvar"), ("w", "setvar")]
    assert [b.enclosing for b in definition.fresh] == [(), (0,)]


def test_a_declared_sort_the_grammar_contradicts_is_refused():
    # `classvar` spells the same tokens as `setvar`, so `z` parses as one — but
    # the slot `∀` binds is a `setvar`, and both cannot be true.
    built = build(
        set_theory({"x": ["phi"]}, extra_productions=[regex_prod("classvar", "cletter", "[a-z]")])
    )
    system, _context = built

    with pytest.raises(DefinitionError, match="binder slot of sort 'setvar'"):
        df_subset(built, fresh={"z": system.build_context.variables["classvar"]})


# ---------------------------------------------------------------------------
# What it buys: a `denotes_constant` declaration the grammar contradicts
# ---------------------------------------------------------------------------


def atom_variable(scopes_over=None, denotes_constant=False):
    """`setvar ::= [A-Z] | c`, with `c` an atom the author may declare constant.

    The grammar from ``test_definitions.ATOM_VARIABLE`` — `c` is a *variable* of
    the object language spelled as a one-token atom, and nothing about its shape
    says so. `T ≝ (c ∈ c)` is admitted only if `c` is excused as a constant, and
    `∀c.T ⟶ ∀c.(c ∈ c)` then captures.
    """
    return SystemSpec(
        name="AtomVariable",
        brackets=brackets(),
        productions=[
            regex_prod("setvar", "setvar_atom", "[A-Z]"),
            atom_const_prod("setvar", "cee", "c", denotes_constant=denotes_constant),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod(
                "formula", "forall", "∀x.phi",
                [("x", "setvar"), ("phi", "formula")],
                scopes_over=scopes_over,
            ),
            template_prod("formula", "tee", "T", []),
        ],
        lines=[statement_line()],
        definitions=[
            Definition_(sort="formula", name="d", higher="T", lower="(c ∈ c)", bindings=[])
        ],
    )


def test_a_constant_in_a_sort_a_binder_ranges_over_is_refused():
    # The documented hole, now closed for a grammar that says what binds. `∀`
    # ranges over `setvar`, `c` is one, so `c` is a variable of the object
    # language however it was declared — and the declaration is what would let
    # `T ≝ (c ∈ c)` through.
    with pytest.raises(DeclarativeError, match="binds 'setvar' through its slot 'x'"):
        build_system(atom_variable({"x": ["phi"]}, denotes_constant=True))


def test_the_declaration_stays_trusted_where_nothing_binds():
    # The boundary this narrows rather than removes: a sort no binder mentions is
    # still the author's call, so the same spec without the binding declaration
    # builds exactly as it did before. This is the pinned hole in
    # `test_definitions.test_declaring_a_bindable_atom_constant_is_the_author_s_to_get_wrong`.
    assert "errors" not in build_spec(atom_variable(denotes_constant=True))


def test_an_undeclared_atom_is_refused_for_the_ordinary_reason():
    # Without the declaration the leaf is variable-like, so the definition is
    # refused as introducing a name from nowhere — the pre-existing path, which
    # the new check must not shadow.
    result = build_spec(atom_variable({"x": ["phi"]}))

    assert "errors" in result
    (message,) = result["errors"]
    assert "introduces 'c'" in message


def test_a_constant_outside_every_binder_sort_is_untouched():
    # `⊥` is a `formula`, and no binder ranges over `formula` — only over
    # `setvar`. The check must reach the bindable sorts and no further.
    spec = atom_variable({"x": ["phi"]})
    spec.productions.append(atom_const_prod("formula", "falsum", "⊥", denotes_constant=True))
    spec.definitions = [
        Definition_(sort="formula", name="d", higher="T", lower="(⊥ → ⊥)", bindings=[])
    ]
    spec.productions.append(
        template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")])
    )

    assert "errors" not in build_spec(spec)


def test_the_check_reaches_through_a_nested_sort_union():
    # A sort admits its branches *transitively*, so a constant two levels down is
    # as bindable as one declared directly in the sort the binder names. A member
    # production with no regex/template/atom of its own leaves the forward-declared
    # union of that name in place, which is how a sort comes to nest.
    spec = SystemSpec(
        name="Nested",
        brackets=brackets(),
        productions=[
            Production(sort="setvar", name="inner"),
            regex_prod("inner", "inner_atom", "[A-Z]"),
            atom_const_prod("inner", "cee", "c", denotes_constant=True),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod(
                "formula", "forall", "∀x.phi",
                [("x", "setvar"), ("phi", "formula")],
                scopes_over={"x": ["phi"]},
            ),
        ],
        lines=[statement_line()],
    )

    # `setvar` admits `inner`, which admits `cee` — and the message says so.
    with pytest.raises(DeclarativeError, match="'setvar' admits 'inner'"):
        build_system(spec)


def test_an_atom_family_is_still_refused_before_any_binder_is_declared():
    # An indexed family is refused outright wherever it sits, declaration or no
    # binder — a supply of interchangeable tokens can never name one fixed thing.
    # Kept distinct from the new check, which needs a binder to say anything.
    spec = atom_variable()
    spec.productions.append(atom_family_prod("formula", "prop", "p"))
    spec.productions[-1].denotes_constant = True

    with pytest.raises(DeclarativeError, match="indexed atom family"):
        build_system(spec)


def test_a_notation_cannot_reach_a_binder_sort_as_a_constant():
    # A nullary defined form is marked constant by the *engine*, not the author
    # (`denotes_a_constant`), so it bypasses the check above. It cannot reach a
    # binder sort anyway: a definition into that sort needs a defining form of
    # that sort, everything there is bindable and so refused as conjured, and the
    # only way to prime the chain is a declared constant the check now catches.
    spec = SystemSpec(
        name="NotationInBinderSort",
        brackets=brackets(),
        productions=[
            regex_prod("setvar", "letter", "[a-z]"),
            atom_const_prod("setvar", "seed", "§"),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod(
                "formula", "forall", "∀x.phi",
                [("x", "setvar"), ("phi", "formula")],
                scopes_over={"x": ["phi"]},
            ),
            template_prod("formula", "tee", "T", []),
        ],
        lines=[statement_line()],
        definitions=[
            Definition_(sort="setvar", name="d1", higher="S", lower="§", bindings=[]),
            Definition_(sort="formula", name="d2", higher="T", lower="(S ∈ S)", bindings=[]),
        ],
    )

    # Undeclared, the seed is conjured and the chain never starts.
    (message,) = build_spec(spec)["errors"]
    assert "introduces '§'" in message

    # Declared, the seed is exactly what the new check refuses.
    spec.productions[1].denotes_constant = True
    (message,) = build_spec(spec)["errors"]
    assert "Production 'seed' (sort 'setvar') is declared" in message


def test_two_binders_on_one_production_must_differ():
    # `⟪u,v⟫.phi` scopes *both* binders over the same body, and neither is inside
    # the other — so nesting alone would call them disjoint and let a step spell
    # both the same, merging two binders into one. Binders opened at one node
    # constrain each other for exactly this reason.
    spec = SystemSpec(
        name="Pair",
        brackets=brackets(),
        productions=[
            regex_prod("setvar", "letter", "[a-z]"),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod(
                "formula", "pair", "⟪u,v⟫.phi",
                [("u", "setvar"), ("v", "setvar"), ("phi", "formula")],
                scopes_over={"u": ["phi"], "v": ["phi"]},
            ),
            template_prod("formula", "subset", "(x ⊆ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[statement_line()],
    )
    system, context = build(spec)
    variables = system.build_context.variables
    definition = parse_definition(
        variables["formula"],
        "(x ⊆ y)",
        "⟪s,t⟫.((s ∈ x) → (t ∈ y))",
        {"x": variables["setvar"], "y": variables["setvar"]},
        context,
    )

    assert [b.enclosing for b in definition.fresh] == [(1,), (0,)]

    def term(text):
        matched = variables["formula"].match(text, context)
        assert matched is not None, text
        return from_match(matched)

    assert check_definitional_step(
        term("(a ⊆ b)"), term("⟪s,t⟫.((s ∈ a) → (t ∈ b))"), definition, context
    )
    assert not check_definitional_step(
        term("(a ⊆ b)"), term("⟪q,q⟫.((q ∈ a) → (q ∈ b))"), definition, context
    )
