"""A definition that holds only under a proof obligation.

Most definitions hold outright. A few hold only because something is *provable*:
Metamath's `df-sb` defines proper substitution through a dummy variable and is
sound just because the choice of dummy is immaterial, which its hypothesis
`sbjust.1` asserts. That is a derivability claim, so it is not a proviso — every
predicate in the kernel's closed algebra is a total structural check on shape —
and it is discharged instead by citing something the system has already settled.

These tests fix what the citation has to establish, and what the definition
inherits from it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import (
    DeclarativeError,
    Justification,
    SystemSpec,
    build_system,
    register_definition,
    registered_definition_layering,
)
from website.logical.kernel import unfold
from website.logical.promotion import promote_from_source

from tests.spec_helpers import (
    assumption_line,
    axiom,
    biconditional_prod,
    brackets,
    cp_rule,
    defn,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    reiteration_rule,
    rule,
    statement_line,
    universal_prod,
    variable_prod,
)

# `x ⊆ y ≝ ∀z (z ∈ x → z ∈ y)`, but stated as holding only if the choice of the
# dummy `z` is immaterial — the shape of `df-sb`'s hypothesis, in miniature. The
# obligation is written in primitive notation, as it must be: it has to parse
# before the definition it justifies extends the grammar.
OBLIGATION = "(∀z (z ∈ x → z ∈ y) ↔ ∀w (w ∈ x → w ∈ y))"

METAVARIABLES = [
    ("x", "variable"), ("y", "variable"), ("z", "variable"), ("w", "variable"),
]


def subset_defn(
    justification: Justification | None,
    condition: str | None = None,
    label: str | None = None,
):
    return defn(
        "formula",
        "subset",
        "x ⊆ y",
        "∀z (z ∈ x → z ∈ y)",
        METAVARIABLES,
        condition=condition,
        fresh=[("z", "variable")],
        label=label,
        justification=justification,
    )


def _spec(definitions, extra_rules=()) -> SystemSpec:
    return SystemSpec(
        name="Sets",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(),
            implication_prod(), biconditional_prod(), universal_prod(),
        ],
        lines=[statement_line()],
        axioms=[axiom("EXT", "extensionality", "∀x x = x")],
        rules=[hyp_rule(), mp_rule(), *extra_rules],
        definitions=list(definitions),
    )


def _dummy_rule(deduction: str = OBLIGATION, antecedents=(), side_conditions=()):
    # The system's own statement that the dummy is immaterial. An asserted rule
    # rather than a proved theorem only because a spec declares no proofs; both
    # are settled statements, which is all a discharge needs.
    return rule(
        "dummy-immaterial",
        "the dummy is immaterial",
        list(antecedents),
        deduction,
        METAVARIABLES,
        side_conditions=side_conditions,
    )


def test_a_definition_whose_obligation_is_settled_is_registered():
    system = build_system(
        _spec([subset_defn(Justification("dummy-immaterial", OBLIGATION))], [_dummy_rule()])
    )

    assert system.definition_layering == [True]
    assert len(system.definitions) == 1


def test_a_definition_with_no_justification_is_unaffected():
    system = build_system(_spec([subset_defn(None)]))

    assert system.definition_layering == [True]
    assert system.definitions[0].condition is None


def test_a_definition_citing_nothing_the_system_declares_is_refused():
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(_spec([subset_defn(Justification("no-such-theorem", OBLIGATION))]))

    assert "no-such-theorem" in str(excinfo.value)


def test_a_definition_citing_something_with_premises_of_its_own_is_refused():
    # A rule with an antecedent has not settled its conclusion — it settles it
    # *given* something else, which is the obligation over again one step back.
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(
            _spec(
                [subset_defn(Justification("dummy-immaterial", OBLIGATION))],
                [_dummy_rule(antecedents=["∀x x = x"])],
            )
        )

    assert "premises of its own" in str(excinfo.value)


def test_an_obligation_the_cited_statement_does_not_cover_is_refused():
    # The cited rule is about `∈`; the obligation stated is about `=`. Nothing
    # structural relates them, so the citation establishes nothing.
    unrelated = "(∀z (z = x → z = y) ↔ ∀w (w = x → w = y))"
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(
            _spec(
                [subset_defn(Justification("dummy-immaterial", OBLIGATION))],
                [_dummy_rule(deduction=unrelated)],
            )
        )

    assert "not an instance of what" in str(excinfo.value)


def test_a_more_general_statement_still_discharges_the_obligation():
    # The citation asks that the obligation be an *instance* of what was settled,
    # not that the two coincide: a theorem may be more general than the definition
    # needs. Here the rule is schematic in whole formulae where the obligation has
    # memberships.
    general = rule(
        "dummy-immaterial",
        "the dummy is immaterial",
        [],
        "(∀z p ↔ ∀w q)",
        [("p", "formula"), ("q", "formula"), ("z", "variable"), ("w", "variable")],
    )
    system = build_system(
        _spec([subset_defn(Justification("dummy-immaterial", OBLIGATION))], [general])
    )

    assert system.definition_layering == [True]


def test_an_obligation_more_general_than_what_was_settled_is_refused():
    # The other direction: what was settled is about `x` specifically, while the
    # obligation is schematic in it. Matching is one-directional for a reason —
    # a narrower statement does not discharge a broader claim.
    narrow = rule(
        "dummy-immaterial",
        "the dummy is immaterial for x",
        [],
        "(∀z (z ∈ x → z ∈ x) ↔ ∀w (w ∈ x → w ∈ x))",
        METAVARIABLES,
    )
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(
            _spec([subset_defn(Justification("dummy-immaterial", OBLIGATION))], [narrow])
        )

    assert "not an instance of what" in str(excinfo.value)


def test_a_discharge_rule_settles_nothing_and_cannot_be_cited():
    # Conditional proof has no `antecedents` — it cites no lines — but it consumes
    # a whole subproof, which is a premise by another name. Without refusing it,
    # `CP` would settle every `(A → B)` there is.
    spec = SystemSpec(
        name="Sets",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(),
            implication_prod(), biconditional_prod(), universal_prod(),
        ],
        lines=[statement_line(), assumption_line()],
        axioms=[axiom("EXT", "extensionality", "∀x x = x")],
        rules=[hyp_rule(), mp_rule(), cp_rule(), reiteration_rule()],
        definitions=[subset_defn(Justification("CP", "(x ∈ y → x ∈ y)"))],
    )
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(spec)

    assert "premises of its own" in str(excinfo.value)


def test_a_rule_whose_provisos_are_not_yet_parsed_cannot_be_cited():
    # A rule's provisos are parsed after definitions resolve, so that one may use
    # defined notation. Inheriting them here would read an empty list and silently
    # drop what the rule holds under, so the citation is refused instead.
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(
            _spec(
                [subset_defn(Justification("dummy-immaterial", OBLIGATION))],
                [_dummy_rule(side_conditions=["disjoint(z, y)"])],
            )
        )

    assert "parsed after definitions resolve" in str(excinfo.value)


# --- the corpus case: a theorem promoted after the system was built ----------


def _built_system():
    return build_system(_spec([]))


def _promote(system, statement=OBLIGATION, distinct=()):
    system.promote(
        promote_from_source(
            system,
            label="dummy-immaterial",
            statement=statement,
            metavariables=dict(METAVARIABLES),
            distinct=distinct,
        )
    )
    return system


def test_a_definition_added_after_the_build_cites_a_promoted_theorem():
    # The corpus case. A walk builds one system and promotes each theorem as it
    # reaches it, so the theorem a definition cites is not there at build time —
    # which is what `register_definition` is for.
    system = _promote(_built_system())

    registered = register_definition(
        subset_defn(Justification("dummy-immaterial", OBLIGATION)), system
    )

    assert registered is True
    assert len(system.definitions) == 1


def test_the_definition_inherits_the_provisos_of_the_theorem_it_cites():
    # The citation licences only what the cited theorem licences: a theorem proved
    # under a `$d` hands that proviso to the definition, restated in the
    # definition's own metavariables. Stricter than Metamath, which re-proves the
    # hypothesis per use — and stricter is the safe direction.
    system = _promote(_built_system(), distinct=["disjoint(x, y, variable)"])

    register_definition(subset_defn(Justification("dummy-immaterial", OBLIGATION)), system)

    condition = system.definitions[0].condition
    assert condition is not None
    assert "DisjointLeaves" in repr(condition)


def test_an_inherited_proviso_is_enforced_at_every_unfold():
    # Present is not enough — it has to *decide* unfolds. `a ⊆ b` satisfies the
    # inherited disjointness and unfolds; `a ⊆ a` does not, and is refused.
    system = _promote(_built_system(), distinct=["disjoint(x, y, variable)"])
    register_definition(subset_defn(Justification("dummy-immaterial", OBLIGATION)), system)
    definition = system.definitions[0]

    def redex(text: str):
        return system.parse(f"{text} [HYP]").proof_lines[0].formula_term

    assert unfold(definition, redex("a ⊆ b"), system.context) is not None
    assert unfold(definition, redex("a ⊆ a"), system.context) is None


def test_an_inherited_proviso_joins_the_definition_s_own():
    system = _promote(_built_system(), distinct=["disjoint(x, y, variable)"])

    register_definition(
        subset_defn(Justification("dummy-immaterial", OBLIGATION), condition="disjoint(x, y)"),
        system,
    )

    assert repr(system.definitions[0].condition).count("DisjointLeaves") == 2


def test_an_inherited_proviso_the_defined_form_cannot_supply_is_refused():
    # `w` is the obligation's *other* dummy: a metavariable of the definition, but
    # neither one its defined form `x ⊆ y` supplies nor one its `fresh` clause
    # declares. An unfold resolves only the parameters and the binders, so this
    # proviso has nothing to resolve against — and `unfold` does not fail closed on
    # that, it raises into the proof parse. Refused where the author can act on it.
    system = _promote(_built_system(), distinct=["disjoint(w, y)"])

    with pytest.raises(DeclarativeError) as excinfo:
        register_definition(
            subset_defn(Justification("dummy-immaterial", OBLIGATION)), system
        )

    assert "does not supply" in str(excinfo.value)
    assert "'w'" in str(excinfo.value)


def test_a_late_refusal_withdraws_the_notation_it_registered():
    # A refusal past `add_notation` leaves the defined form parsing as defined
    # notation with no kernel definition behind it. On a whole build that is
    # discarded with everything else, but `register_definition` mutates a *live*
    # system — and a corpus import catches this exact error to keep the assertion
    # as an axiom, so it must find the grammar as it left it.
    system = _promote(_built_system(), distinct=["disjoint(w, y)"])
    before = set(system.context.definitions)

    with pytest.raises(DeclarativeError):
        register_definition(
            subset_defn(Justification("dummy-immaterial", OBLIGATION)), system
        )

    assert set(system.context.definitions) == before
    assert system.definitions == []
    # And the form is no longer readable as the notation the refusal registered.
    assert system.parse("a ⊆ b [HYP]").proof_lines[0].formula_term is None


def test_a_late_refusal_leaves_an_earlier_definition_s_notation_alone():
    # Two definitions may share one defined form, and `add_notation` hands the
    # second the production the first registered. Withdrawing it on the second's
    # refusal would confiscate the first one's grammar.
    system = _promote(_built_system(), distinct=["disjoint(w, y)"])
    register_definition(subset_defn(None), system)
    before = set(system.context.definitions)

    with pytest.raises(DeclarativeError):
        register_definition(
            subset_defn(Justification("dummy-immaterial", OBLIGATION)), system
        )

    assert set(system.context.definitions) == before
    assert system.parse("a ⊆ b [HYP]").proof_lines[0].formula_term is not None


# A proviso that constrains the *binder* and nothing else. Disjointness from the
# parameters is already the auto-generated `$d` the kernel derives from `fresh`,
# so it could never isolate this; "the binder may not be called `c`" can. It is a
# contrived rule, and deliberately so — what it pins is which binding the proviso
# is resolved against, not a proposition anyone would want.
NOT_C = "not equal(z, c)"


def test_a_proviso_may_constrain_a_binder_by_its_declared_name():
    # A binder is stored abstractly and takes whatever name an unfold chooses, so
    # `z` in a proviso means "this binder, whatever it ends up called" rather than
    # the literal token `z`. Before, the condition was checked before the binders
    # were resolved and could only mean the token.
    system = _built_system()
    register_definition(subset_defn(None, condition=NOT_C), system)
    definition = system.definitions[0]
    redex = system.parse("a ⊆ b [HYP]").proof_lines[0].formula_term

    def leaf(name: str):
        # A `variable` leaf, taken out of a formula: a bare variable is not a
        # formula, so it has no proof line of its own to parse.
        membership = system.parse(f"{name} ∈ {name} [HYP]").proof_lines[0].formula_term
        return membership.children["s"]

    # The default name, and another the proviso permits.
    assert unfold(definition, redex, system.context) is not None
    assert unfold(definition, redex, system.context, {"z": leaf("d")}) is not None
    # `c` is fresh for the parameters, so only the definition's own proviso refuses.
    assert unfold(definition, redex, system.context, {"z": leaf("c")}) is None


def test_a_binder_proviso_reaches_the_proof_checker_too():
    # `check_definitional_step` recovers the binder's name from the target rather
    # than being handed it, and carries its own copy of the unfold logic — so the
    # proviso has to be checked there after recovery too, or the rule holds for
    # `kernel.unfold` and not for any actual proof.
    system = _built_system()
    register_definition(subset_defn(None, condition=NOT_C, label="sub"), system)

    ok = system.parse("a ⊆ b [HYP]\n∀d (d ∈ a → d ∈ b) [sub, 1]")
    assert ok.proof_lines[1].valid is True

    refused = system.parse("a ⊆ b [HYP]\n∀c (c ∈ a → c ∈ b) [sub, 1]")
    assert refused.proof_lines[1].valid is not True


def test_a_definition_s_own_proviso_is_held_to_the_same_rule():
    # Not a justification-only rule: a hand-written `where` clause naming a
    # non-parameter has always had the same defect, and is refused the same way.
    with pytest.raises(DeclarativeError) as excinfo:
        build_system(_spec([subset_defn(None, condition="disjoint(w, y)")]))

    assert "does not supply" in str(excinfo.value)


def test_registering_a_duplicate_definition_label_is_refused():
    # `build_system` refuses a duplicate within its own spec because a cited name
    # must resolve to one definition; a definition added later needs the same
    # refusal against what the system already carries.
    system = _built_system()
    register_definition(subset_defn(None, label="sub"), system)

    with pytest.raises(DeclarativeError) as excinfo:
        register_definition(
            defn("formula", "sub2", "x ⊂ y", "∀z (z ∈ x → z ∈ y)",
                 METAVARIABLES, fresh=[("z", "variable")], label="sub"),
            system,
        )

    assert "Duplicate definition label 'sub'" in str(excinfo.value)


def test_registering_keeps_the_layering_list_positional():
    system = _built_system()

    register_definition(subset_defn(None), system)

    assert system.definition_layering == [True]
    assert len(system.definitions) == len(system.definition_layering)


def test_registering_against_a_system_with_no_build_context_is_refused():
    from website.logical.formal_system import FormalSystem

    with pytest.raises(DeclarativeError) as excinfo:
        register_definition(subset_defn(None), FormalSystem("bare"))

    assert "no build context" in str(excinfo.value)


def test_layering_is_reported_for_a_justified_definition():
    # The reorder guard builds a spec reduced to grammar plus definitions, so a
    # justification's citation is not there to resolve. Dropping the justification
    # for that build is what keeps the answer about *layering* — otherwise every
    # definition reads as dropped and the guard silently stops guarding.
    spec = _spec(
        [subset_defn(Justification("dummy-immaterial", OBLIGATION))], [_dummy_rule()]
    )

    assert build_system(spec).definition_layering == [True]
    assert registered_definition_layering(spec) == [True]
