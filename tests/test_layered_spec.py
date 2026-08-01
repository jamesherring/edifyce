"""Inheritance at the spec level: :func:`layered_spec` and what it refuses.

A child's effective system is its ancestors' parts followed by its own, and that
concatenation is the *whole* of inheritance — `build_system` sees one flat spec
and neither it nor the kernel learns a new concept
(docs/system-relationships-roadmap.md §5.1).

The tower under test is `tests/layered_systems.py`: propositional calculus,
first-order logic, ZFC. Everything here is written as an accepted/rejected pair
where one exists, because every guard in this area errs *safe* — a bug shows up
as a valid system being refused, which a suite of refusals cannot see.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("regex")

from website.logical.declarative import (
    DeclarativeError,
    SystemSpec,
    build_spec,
    layered_spec,
)
from website.logical.kernel.constructors import constructor_for

from tests.spec_helpers import template_prod
from tests.layered_systems import (
    bound_constant_spec,
    extra_line_spec,
    first_order_logic_spec,
    propositional_calculus_spec,
    propositional_grammar_spec,
    redeclared_implication_spec,
    redefining_implication_spec,
    tower,
    zfc_spec,
)


def built(*specs: SystemSpec):
    """Build the chain, failing the test with the engine's own message."""
    result = build_spec(layered_spec(list(specs)))
    assert "errors" not in result, result["errors"]
    return result["system"]


def refusal(*specs: SystemSpec) -> str:
    """The message the chain is refused with, at either stage."""
    try:
        result = build_spec(layered_spec(list(specs)))
    except DeclarativeError as exc:
        return str(exc)
    assert "errors" in result, "expected a refusal, got a system"
    return " ".join(result["errors"])


# --- the concatenation itself ----------------------------------------------


def test_one_layer_is_the_spec_it_was_given():
    # The identity that keeps every existing system's behaviour untouched: a
    # system with no ancestors is layered with itself and comes out equal — same
    # parts, same order, and an empty `definition_scope`, which *is* the flat
    # reading rather than a special case of it.
    spec = propositional_calculus_spec()
    assert layered_spec([spec]) == spec
    assert layered_spec([spec]).definition_scope == []


def test_layering_is_associative():
    # Grouping the chain differently must not change the system it describes.
    # Only the *messages* differ: a nested group is one layer as far as collision
    # reporting is concerned.
    pc, fol, zfc = tower()
    stepwise = layered_spec([layered_spec([pc, fol]), zfc])
    assert stepwise == layered_spec(tower())


def test_sorts_merge_and_notation_accumulates():
    spec = layered_spec(tower())
    # `formula` is declared by the propositional layer and *grown* by the first-
    # order one; `term` arrives with the latter. Two sorts, not four.
    assert spec.sort_names() == ["formula", "term"]
    names = [prod.name for prod in spec.productions]
    assert names.index("implication") < names.index("universal")
    assert {"prop_var", "implication", "universal", "membership"} <= set(names)


def test_the_child_line_type_is_the_ancestors():
    # A child declaring no lines uses its ancestors', and one that declares an
    # extra gets both — in ancestor-first order, which is the order the parser
    # tries them in.
    spec = layered_spec([propositional_calculus_spec(), extra_line_spec()])
    assert [line.name for line in spec.lines] == ["statement", "claim"]


def test_token_separation_is_the_disjunction_over_the_chain():
    # The promise is about the whole notation, so an ancestor's claim reaches the
    # child. What a layer that then writes glued templates gets is
    # `_check_token_separation`'s complaint, which is where that belongs.
    separated = replace(propositional_calculus_spec(), token_separated=True)
    assert layered_spec([separated, zfc_spec()]).token_separated is True
    assert layered_spec(tower()).token_separated is False


def test_the_name_is_the_most_derived_layers():
    assert layered_spec(tower()).name == zfc_spec().name


# --- the sort widening, read off the kernel --------------------------------


def test_the_childs_sort_admits_everything_the_ancestors_did():
    # The claim §2 of the roadmap rests on, asserted where it is decided — the
    # kernel's sort admission — rather than by comparing sort *names*, which
    # would pass for a child that reused `formula` for something else entirely.
    alone = built(propositional_calculus_spec())
    layered = built(*tower())

    def admitted(system):
        union = system.build_context.variables["formula"]
        return {member.name for member in constructor_for(union).admits}

    assert admitted(alone) < admitted(layered)
    assert "universal" in admitted(layered) - admitted(alone)


# --- what a layered system can prove ---------------------------------------


def test_a_zfc_proof_may_be_written_entirely_in_propositional_notation():
    system = built(*tower())
    proof = system.parse(
        "(A → (B → A)) [ax-1]\n"
        "((A → (B → A)) → (C → (A → (B → A)))) [ax-1]\n"
        "(C → (A → (B → A))) [MP, 1, 2]"
    )
    assert proof.valid, [line.invalid_message for line in proof.proof_lines]


def test_a_zfc_proof_mixes_every_layers_primitives():
    system = built(*tower())
    proof = system.parse(
        "(A → (B → A)) [ax-1]\n"
        "∀x (A → (B → A)) [GEN, 1]\n"
        "(∀x (A → (B → A)) → (∀x A → ∀x (B → A))) [ax-4]\n"
        "(∀x A → ∀x (B → A)) [MP, 2, 3]"
    )
    assert proof.valid, [line.invalid_message for line in proof.proof_lines]


def test_an_ancestors_definition_unfolds_in_a_descendants_proof():
    # `df-an` belongs to the propositional layer; the step is taken three layers
    # up, over a formula the propositional layer could not even spell.
    system = built(*tower())
    proof = system.parse("(x ∈ y ∧ B) [ax-1]\n¬(x ∈ y → ¬B) [df-an, 1]")
    assert proof.proof_lines[1].valid, proof.proof_lines[1].invalid_message


def test_a_definition_over_the_ancestors_notation_unfolds():
    # `df-ss` is ZFC's, and every symbol it is written with is inherited.
    system = built(*tower())
    proof = system.parse("x ⊆ y [ax-1]\n∀z (z ∈ x → z ∈ y) [df-ss, 1]")
    assert proof.proof_lines[1].valid, proof.proof_lines[1].invalid_message


def test_an_ancestors_proviso_still_binds_in_a_descendant():
    # The accepted/rejected pair. `ax-5` may quantify over an `x` its formula
    # does not mention, and may not otherwise — enforced by the kernel's
    # `occurs`, over the term, in a layer that did not declare the rule.
    system = built(*tower())
    assert system.parse("(A → ∀x A) [ax-5]").valid
    assert not system.parse("(x ∈ y → ∀x x ∈ y) [ax-5]").valid


def test_a_fiat_axiom_of_the_top_layer_is_schematic_over_the_whole_grammar():
    system = built(*tower())
    assert system.parse(
        "(∀z ((z ∈ x → z ∈ y) ∧ (z ∈ y → z ∈ x)) → x = y)"
    ).valid
    # The negative control: a near-miss of the same shape must not be asserted.
    assert not system.parse(
        "(∀z ((z ∈ x → z ∈ y) ∧ (z ∈ y → z ∈ x)) → x = z)"
    ).valid


# --- collisions ------------------------------------------------------------


def test_a_child_may_not_redeclare_an_ancestors_production():
    message = refusal(propositional_calculus_spec(), redeclared_implication_spec())
    assert "'implication'" in message
    # The message has to name both layers: a collision is a fact about a pair,
    # and the author is looking at only one of them.
    assert "Propositional calculus" in message and "Redeclared" in message


def test_a_collision_within_one_layer_is_still_that_layers_business():
    # `layered_spec` refuses *cross*-layer collisions only. A spec that declares
    # the same name twice is exactly as (in)valid as it was before inheritance
    # existed — which is what keeps `layered_spec([spec]) == spec` meaningful.
    doubled = propositional_calculus_spec()
    doubled.productions.append(redeclared_implication_spec().productions[0])
    layered_spec([doubled])  # no refusal from here


def test_two_layers_may_not_give_one_bracket_two_readings():
    other = SystemSpec(name="Other brackets", brackets=[("(", "]")])
    assert "cannot both hold" in refusal(propositional_calculus_spec(), other)


def test_a_bracket_pair_repeated_down_the_chain_is_declared_once():
    same = SystemSpec(name="Same brackets", brackets=[("(", ")")])
    assert layered_spec([propositional_calculus_spec(), same]).brackets == [("(", ")")]


def test_a_label_may_not_be_taken_twice_down_the_chain():
    shadow = SystemSpec(
        name="Shadow", rules=list(propositional_calculus_spec().rules[:1])
    )
    message = refusal(propositional_calculus_spec(), shadow)
    assert "'ax-1'" in message and "Shadow" in message


# --- checks that only fire because of a layer above or below ---------------


def test_a_binder_in_a_child_refuses_an_ancestors_constant_declaration():
    # `∅` is declared a constant of the object language, which is true of the
    # layer that declares it and false once a quantifier ranges over its sort.
    # The pair: harmless alone, refused under the layer that introduces `∀`.
    built(propositional_calculus_spec(), bound_constant_spec())
    message = refusal(
        propositional_calculus_spec(), bound_constant_spec(), first_order_logic_spec()
    )
    assert "'zero'" in message and "universal" in message


def test_a_child_may_not_define_a_symbol_its_ancestors_reason_over():
    # Freshness, reading the *ancestors'* primitives. The control is the same
    # definition over the same notation with no rules beneath it: accepted, so
    # the refusal is about what the ancestors prove and not about what they
    # spell.
    built(propositional_grammar_spec(), redefining_implication_spec())
    message = refusal(propositional_calculus_spec(), redefining_implication_spec())
    assert "already stated over that form" in message


def test_an_ancestors_definition_is_not_held_to_a_descendants_axiom():
    # The other direction, and the one that would have made the tower
    # unbuildable. `df-an` gives `∧` a meaning it did not have *in the layer that
    # declares it*; ZFC's extensionality axiom, added later, then reasons with
    # that meaning. Reading the chain flat makes the definition look like it is
    # redefining a symbol the theory already constrains, which is what
    # `definition_scope` exists to prevent.
    spec = layered_spec(tower())
    assert spec.definition_scope[0] < spec.definition_scope[-1]
    built(*tower())

    flattened = replace(spec, definition_scope=[])
    assert "already stated over that form" in " ".join(build_spec(flattened)["errors"])


def test_an_empty_chain_is_refused():
    with pytest.raises(DeclarativeError):
        layered_spec([])


def test_layers_are_told_apart_by_position_not_by_name():
    # A layer's name is free text and two layers of a chain may well share one.
    # Identifying a layer by it would make every check above skip exactly the
    # pair it exists to catch — and the collision is silent, because the child's
    # production simply replaces the ancestor's in the build namespace.
    pc = propositional_calculus_spec()
    clash = replace(redeclared_implication_spec(), name=pc.name)
    message = refusal(pc, clash)
    assert "'implication'" in message


def test_a_production_may_not_take_an_ancestors_sort_name():
    # A sort is shared, but its name is still one entry in `ctx.variables`: a
    # production spelled like an ancestor's sort would take the union's place,
    # and the sort would then admit nothing. Refused with the sort named, rather
    # than surfacing later as an attribute error out of the builder.
    shadow = SystemSpec(
        name="Shadow",
        productions=[
            template_prod("formula", "formula", "[P]", [("P", "formula")])
        ],
    )
    message = refusal(propositional_calculus_spec(), shadow)
    assert "'formula'" in message and "sort of that name" in message
