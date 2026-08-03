"""A sequent calculus built *on* a Hilbert tower rather than beside one.

The third arrangement, after S1's standalone system and S2's edge, and the one an
imported corpus forces. `tests/sequent_tower.py` carries the design; what is
asserted here is that it works and that the two arrangements are not
interchangeable.

The claim the whole module is about: **for a sequent calculus over a system that
already exists, the spine does what S2's edge did and asks for none of what the
edge asks for.** No rename, because the child's `formula` *is* the parent's rows.
No template, because the child can state a parent line itself. No obligations,
because the parent's rules are the child's. What replaces all three is one
declared rule, `lift`, taking `P` to `∅ ⊢ P`.

That matters because of `set.mm`: 1,441 productions, which a sibling system would
have to redeclare or map one by one. `test_a_sequent_layer_sits_on_an_imported_
grammar` is the same layer, unmodified except for the name of its parent's
logical sort, on a grammar the Metamath importer built.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import DeclarativeError, build_spec, layered_spec
from website.logical.metamath import importer
from website.logical.metamath.parser import parse
from website.logical.promotion import TheoremSpec, promote_spec

from tests.layered_systems import (
    first_order_logic_spec,
    propositional_calculus_spec,
)
from tests.sequent_tower import (
    CITATION,
    propositional_sequent_rules,
    sequent_core,
    sequent_layer_spec,
    sequent_tower_specs,
)
from tests.test_metamath_import import SQRT2RE_FRAGMENT


@pytest.fixture(scope="module")
def tower():
    built = build_spec(layered_spec(sequent_tower_specs()))
    assert "errors" not in built, built["errors"]
    return built["system"]


def stands(system, source: str) -> bool:
    return bool(system.parse(source).valid)


def why(system, source: str) -> str:
    proof = system.parse(source)
    return " | ".join(
        f"{line.number}: {line.invalid_message}"
        for line in proof.proof_lines
        if not line.empty and not line.valid and line.invalid_message
    )


def test_the_tower_is_the_one_these_tests_assume(tower):
    # A guard on the fixture, as S1's is: every refusal below would pass just as
    # well against a system that had none of this. Both line types are present —
    # which is the arrangement, not an accident — and the rules are the union of
    # three layers.
    assert [line.name for line in tower.line_types] == [
        "statement", "sequent-statement"
    ]
    assert {rule.label for rule in tower.inference_rules} == {
        # Propositional calculus
        "ax-1", "ax-2", "ax-3", "MP",
        # First-order logic
        "ax-4", "ax-5", "GEN",
        # The sequent layer
        "id", "WL", "XL", "CL", "cut", "lift", "→R", "→L", "∀R", "∀L",
    }


# ---------------------------------------------------------------------------
# Both calculi, in one system
# ---------------------------------------------------------------------------


def test_the_parent_s_own_lines_still_check_here(tower):
    # The child did not take anything away. A Hilbert proof written against PC
    # and FOL checks in the sequent layer unchanged, because a line type is
    # inherited like everything else — which is what makes this arrangement
    # additive rather than a fork.
    assert stands(tower, "(P → (Q → P)) [ax-1]")
    assert stands(
        tower,
        "(A → (B → A)) [ax-1]\n"
        "((A → (B → A)) → (C → (A → (B → A)))) [ax-1]\n"
        "(C → (A → (B → A))) [MP, 1, 2]",
    )


def test_a_sequent_proof_checks_over_the_inherited_grammar(tower):
    # And the child's own lines. `(A → A)` is spelled by *PC's* `implication`
    # production, and the context sort admits it because the layer declared
    # `context ::= … | formula`, naming a sort it inherited rather than one it
    # owns.
    assert stands(tower, "∅ , A ⊢ A [id]\n∅ ⊢ (A → A) [→R, 1]")


def test_lifting_is_what_the_edge_s_template_was_doing(tower):
    # **The headline.** A Hilbert theorem proved by the parent's rules, lifted
    # into a sequent, then used as a sequent. Three lines, and the middle one is
    # the whole of what S2 needed a statement template, an extras table and four
    # obligations to achieve.
    #
    # Nothing is wrapped here: line 1 *is* a formula line, and `lift` is an
    # ordinary rule whose antecedent is read at `formula` and whose conclusion is
    # read at `sequent`.
    assert stands(
        tower,
        "(P → (Q → P)) [ax-1]\n"
        "∅ ⊢ (P → (Q → P)) [lift, 1]\n"
        "∅ , B ⊢ (P → (Q → P)) [WL, 2]",
    )


def test_a_library_theorem_of_the_parent_lifts_too(tower):
    # The same path for a *promoted* theorem rather than a primitive, which is
    # what an imported corpus contributes: `set.mm`'s 49,000 entries are library,
    # not rules. A child's library is its ancestors' (§5.2), so the entry is
    # citable on a formula line here and `lift` carries it across.
    #
    # Promoted onto a copy, so the module fixture is not mutated by a test.
    system = build_spec(layered_spec(sequent_tower_specs()))["system"]
    system.promote(promote_spec(system, TheoremSpec(
        label="id-law", statement="(P → P)", metavariables={"P": "formula"}
    )))

    assert stands(
        system,
        "(A → A) [id-law]\n"
        "∅ ⊢ (A → A) [lift, 1]\n"
        "∅ , B ⊢ (A → A) [WL, 2]",
    )


def test_lift_reaches_the_empty_context_and_no_other(tower):
    # `lift` concludes `∅ ⊢ P`, never `Γ ⊢ P`, and the difference is §9.24's
    # finding restated as a rule rather than as a template: a schema is read for
    # *all* instances of its metavariables, so a lift onto an arbitrary context
    # would claim uniformity that only weakening earns.
    #
    # The pair: the empty context stands, a non-empty one does not, and the
    # weakening that bridges them is written out.
    assert stands(tower, "(P → (Q → P)) [ax-1]\n∅ ⊢ (P → (Q → P)) [lift, 1]")

    source = "(P → (Q → P)) [ax-1]\nB ⊢ (P → (Q → P)) [lift, 1]"
    assert not stands(tower, source)
    assert "lift does not apply" in why(tower, source)


def test_a_hilbert_axiom_does_not_justify_a_sequent_line(tower):
    # The two calculi do not leak into each other. `ax-5` concludes a *formula*,
    # so it justifies a formula line and not a sequent one — the lift is not
    # optional, and a system where it were would be one where `⊢` meant nothing.
    assert stands(tower, "(P → ∀x P) [ax-5]")

    source = "∅ ⊢ (P → ∀x P) [ax-5]"
    assert not stands(tower, source)
    assert "ax-5 does not apply" in why(tower, source)


# ---------------------------------------------------------------------------
# The eigenvariable condition, asked about an inherited sort
# ---------------------------------------------------------------------------


def test_generalisation_over_a_context_that_mentions_the_variable(tower):
    # S1's central case, one layer up. What is new is that the proviso is asked
    # about notation the sequent layer never declared: `x` is FOL's `term`, the
    # formula is FOL's `equality`, and the context is this layer's — so `occurs`
    # descends across a layer boundary, which is exactly what it should do, since
    # `layered_spec` produces one flat grammar and the kernel learns nothing
    # about layers (§5.1).
    #
    # And it answers S1's third finding, which was that `id` alone cannot supply
    # a **non-vacuous** ∀R premise: `id` puts its formula into the context by
    # construction, so every sequent it proves mentions in Γ whatever it proves,
    # and the proviso then holds vacuously or fails trivially. S1 had to declare
    # an axiom of the object theory to get round it. Here the *parent* supplies
    # it — `lift` brings in a Hilbert theorem about `x` that the context does not
    # contain, which is the bridge doing real work rather than ornament.
    #
    # The pair differs in one character: the context is about `y` or about `x`.
    lifted = (
        "(x = x → (Q → x = x)) [ax-1]\n"
        "∅ ⊢ (x = x → (Q → x = x)) [lift, 1]\n"
    )
    assert stands(
        tower,
        lifted
        + "∅ , y = y ⊢ (x = x → (Q → x = x)) [WL, 2]\n"
        + "∅ , y = y ⊢ ∀x (x = x → (Q → x = x)) [∀R, 3]",
    )

    source = (
        lifted
        + "∅ , x = x ⊢ (x = x → (Q → x = x)) [WL, 2]\n"
        + "∅ , x = x ⊢ ∀x (x = x → (Q → x = x)) [∀R, 3]"
    )
    assert not stands(tower, source)
    assert "∀R does not apply" in why(tower, source)


# ---------------------------------------------------------------------------
# The arrangement `set.mm` forces
# ---------------------------------------------------------------------------


def test_a_sequent_layer_sits_on_an_imported_grammar():
    # **The architecture check.** The same `sequent_core`, unmodified except for
    # the name of its parent's logical sort, on a grammar the Metamath importer
    # built from a `.mm` file. That is the arrangement `set.mm` forces and the
    # one an edge cannot reach: a sibling system would have to redeclare 1,441
    # productions, or carry a rename with an entry for each — and
    # `translation_errors` holds a rename to totality, so a partial one is not an
    # option either.
    #
    # Everything asserted here is about the *inherited* notation: `0 < 2` is the
    # importer's `wbr`, and the context sort admits it because the layer names
    # `wff`, a sort it did not declare.
    database = parse(SQRT2RE_FRAGMENT)
    imported = importer.build_spec(database, name="Imported")
    assert imported.lines[0].logical_sort == "wff"

    built = build_spec(layered_spec([
        imported,
        sequent_core(name="Sequent over the import", formula="wff"),
    ]))
    assert "errors" not in built, built["errors"]
    system = built["system"]

    assert [line.name for line in system.line_types] == [
        "statement", "sequent-statement"
    ]
    assert stands(system, "∅ , 0 < 2 ⊢ 0 < 2 [id]")
    assert stands(system, "∅ , 2 e. RR ⊢ 2 e. RR [id]")
    assert stands(
        system,
        "∅ , 0 < 2 ⊢ 0 < 2 [id]\n∅ , 0 < 2 , 2 e. RR ⊢ 0 < 2 [WL, 1]",
    )


def test_an_imported_theorem_lifts_into_a_sequent():
    # And the bridge, over imported notation. The importer's assertions land in
    # the *library* rather than among the rules, so this promotes one the way a
    # walk does and cites it on a `wff` line — then lifts it.
    #
    # This is the whole of what S2's edge bought, obtained from the spine at the
    # cost of one declared rule and no obligations at all.
    database = parse(SQRT2RE_FRAGMENT)
    system = build_spec(layered_spec([
        importer.build_spec(database, name="Imported"),
        sequent_core(name="Sequent over the import", formula="wff"),
    ]))["system"]
    system.promote(promote_spec(
        system, TheoremSpec(label="2re", statement="2 e. RR")
    ))

    assert stands(
        system,
        "2 e. RR [2re]\n"
        "∅ ⊢ 2 e. RR [lift, 1]\n"
        "∅ , 0 < 2 ⊢ 2 e. RR [WL, 2]",
    )


def test_the_core_names_nothing_of_its_parent_but_the_logical_sort():
    # Why the layer above could be reused verbatim, asserted rather than
    # asserted-by-anecdote: `sequent_core`'s productions and rules mention the
    # parent's *sort* and no production of it. That is what makes the split in
    # `sequent_tower` real — the logical rules (→R, →L, ∀R) do spell connectives
    # and are therefore written per parent.
    core = sequent_core(formula="wff")
    mentioned = {
        sort
        for production in core.productions
        for _slot, sort in (production.bindings or [])
    }
    mentioned |= {production.sort for production in core.productions}
    assert mentioned == {"context", "sequent", "wff"}

    # And the contrast: a logical rule names a connective, so it cannot be.
    assert any("→" in rule.deduction for rule in propositional_sequent_rules())


# ---------------------------------------------------------------------------
# What a layer may not reuse
# ---------------------------------------------------------------------------


def test_a_layer_may_not_reuse_its_parent_s_line_part_name(tower):
    # **The wart this arrangement has to work around**, pinned so that the
    # workaround is not mistaken for a preference. `layered_spec` claims a line
    # *part*'s name once across a chain, so a child adding a line type cannot
    # call its citation field `reference` — which is what both the Hilbert layers
    # and the Metamath importer call theirs.
    #
    # Within a *single* spec two line types may share a part name freely, and the
    # accepted half here is that same arrangement flattened: it is the
    # inconsistency that makes this a wart rather than a rule (§9.25).
    from copy import deepcopy

    clashing = sequent_layer_spec()
    clashing.lines[0].shape = "<sequent> [<reference>]"
    clashing.lines[0].parts[0].name = "reference"

    with pytest.raises(DeclarativeError) as refused:
        layered_spec([
            propositional_calculus_spec(), first_order_logic_spec(), clashing
        ])
    assert "Line part 'reference'" in str(refused.value)

    # The same two line types in one spec, which builds — so nothing about the
    # *grammar* requires the names to differ.
    flat = deepcopy(propositional_calculus_spec())
    flat.productions.extend(deepcopy(sequent_core().productions))
    flat.lines.extend(deepcopy(clashing.lines))
    flat.rules.extend(r for r in sequent_core().rules if r.label == "id")
    assert "errors" not in build_spec(flat)

    # And the name this repository's layer uses instead.
    assert CITATION == "citation"
