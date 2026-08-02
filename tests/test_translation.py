"""What a rename between two systems has to earn.

R4b of docs/system-relationships-roadmap.md, engine half. An `extension` edge and
the inheritance spine both transfer a theorem under its own names; an
`interpretation` edge between two independently-built systems may **rename**, and
`website.logical.translation` is where that claim is tested before anything is
transferred on the strength of it.

The claim is §3.2's, and the discipline is §8.0's: every refusal below is paired
with the accepted case it differs from by one thing, because a check that refuses
everything passes a suite of refusals.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_spec, layered_spec
from website.logical.translation import IDENTITY, Translation, translation_errors

from tests.layered_systems import (
    FOL_RENAME,
    PC_RENAME,
    first_order_logic_spec,
    narrowed_propositional_calculus_spec,
    propositional_calculus_spec,
    renamed_first_order_spec,
    renamed_propositional_calculus_spec,
    statement_line,
    with_defined_disjunction,
)
from tests.spec_helpers import (
    atom_const_prod,
    atom_family_prod,
    brackets,
    defn,
    regex_prod,
    template_prod,
)
from website.logical.declarative import SystemSpec


def built(spec):
    result = build_spec(spec)
    assert "errors" not in result, result["errors"]
    return result["system"]


def pc():
    return built(propositional_calculus_spec())


def renamed():
    return built(renamed_propositional_calculus_spec())


PC_MAP = Translation(**PC_RENAME)


# ---------------------------------------------------------------------------
# The map that checks out
# ---------------------------------------------------------------------------


def test_the_identity_translates_anything():
    # The common edge — two systems that agree on their vocabulary — carries no
    # rows and is checked against nothing, which is what keeps it free.
    assert IDENTITY.identity
    assert translation_errors(pc(), renamed(), IDENTITY) == []
    assert IDENTITY.key == ""


def test_a_pure_rename_is_accepted():
    # The same system under other names: identical notation, every production
    # renamed. Nothing here should be refused, and this is the case every
    # refusal below differs from by exactly one thing.
    assert translation_errors(pc(), renamed(), PC_MAP) == []


def test_an_unmapped_name_passes_through():
    # A partial map is the identity on what it does not mention, which is what
    # lets an edge state only the names that actually differ.
    assert PC_MAP.name("implication") == "imp"
    assert PC_MAP.name("something-neither-system-has") == "something-neither-system-has"


def test_a_defined_form_is_renamed_by_its_sort():
    # A definition declares no symbol, so neither table can name its notation —
    # but its constructor is called `<sort>:<template>` and reaches every stored
    # term built through it. The sort half is translated and the template is not,
    # which is what makes a definition the two systems state alike resolve
    # through a sort rename.
    assert PC_MAP.name("formula:(P ∨ Q)") == "wff:(P ∨ Q)"
    # Not a defined form, and not something to take apart on a stray colon.
    assert PC_MAP.name("nothing:like:it") == "nothing:like:it"


def test_a_definition_the_target_does_not_state_is_refused():
    # And the case the renaming cannot reach: a target that spells the *defined
    # form* differently. Nothing in the two tables can say the two correspond, so
    # the edge is refused here rather than left to fail when a theorem happens to
    # mention it — which is where it failed before, mid-verify and unreadably.
    source = built(with_defined_disjunction(propositional_calculus_spec()))
    stated = built(with_defined_disjunction(
        renamed_propositional_calculus_spec(), "wff"
    ))
    assert translation_errors(source, stated, PC_MAP) == []

    otherwise = renamed_propositional_calculus_spec("Otherwise")
    otherwise.definitions = list(otherwise.definitions) + [
        defn("wff", "disj", "(P | Q)", "(¬P → Q)", [("P", "wff"), ("Q", "wff")],
             label="df-or")
    ]
    errors = translation_errors(source, built(otherwise), PC_MAP)

    assert len(errors) == 1
    assert "'formula:(P ∨ Q)'" in errors[0] and "'wff:(P ∨ Q)'" in errors[0]


def test_an_unmapped_production_must_be_the_same_production():
    # The gap a map's own entries cannot show: `Translation.name` is applied to
    # every name a stored term carries, so a name the map says nothing about is
    # still *translated* — to itself. If the two systems spell that name
    # differently, a theorem proved about one connective is read as being about
    # another, and the author never said so.
    #
    # Paired with the accepted case, which is the same two grammars and one more
    # map entry: saying it explicitly is how an author declares exactly this.
    diverging = renamed_propositional_calculus_spec("Diverging")
    diverging.productions = [
        template_prod("wff", "implication", "(p ∨ q)", [("p", "wff"), ("q", "wff")])
        if prod.name == "imp"
        else prod
        for prod in diverging.productions
    ]
    diverging.rules = []
    diverging.definitions = []
    target = built(diverging)
    partial = {name: image for name, image in PC_MAP.symbols.items()
               if name != "implication"}

    errors = translation_errors(pc(), target, Translation(PC_MAP.sorts, partial))
    assert any("different productions that share a name" in error for error in errors)

    declared = Translation(PC_MAP.sorts, {**partial, "implication": "implication"})
    assert translation_errors(pc(), target, declared) == []


def test_two_source_names_may_not_become_one():
    # The map's unique index is on the source side only, so nothing below this
    # stops two of the source's productions collapsing onto one of the target's —
    # under which a theorem about `→` justifies a statement about `∧`.
    collapsed = Translation(PC_MAP.sorts, {**PC_MAP.symbols, "implication": "conj"})
    errors = translation_errors(pc(), renamed(), collapsed)

    assert any("cannot become one" in error for error in errors)
    assert any("'conjunction'" in error and "'implication'" in error
               for error in errors)


def test_a_rename_over_a_binder_is_accepted():
    # The complex accepted case §8.0 asks for. Two sorts, nine productions, a
    # binder among them — and the binder is the one an over-eager guard would
    # refuse, since `scopes_over` is compared and a quantifier is the only
    # production that has any.
    source = built(layered_spec([propositional_calculus_spec(), first_order_logic_spec()]))
    assert translation_errors(source, built(renamed_first_order_spec()), Translation(**FOL_RENAME)) == []


# ---------------------------------------------------------------------------
# The sort map: narrowing, over `admits` rather than over names
# ---------------------------------------------------------------------------


def test_a_narrowing_sort_map_is_refused():
    # §3.2. The target's `wff` must admit a superset of what the source's
    # `formula` does, and this one does not: `conj` is declared, and in another
    # sort. The message names both the branch and the sort, since the whole
    # difficulty of a rename is that two names denote the same thing or fail to.
    narrowed = built(narrowed_propositional_calculus_spec())
    errors = translation_errors(pc(), narrowed, PC_MAP)

    assert len(errors) == 1
    assert "'conjunction'" in errors[0] and "'conj'" in errors[0] and "'wff'" in errors[0]


def test_the_narrowing_refusal_is_not_a_name_comparison():
    # The control that says which check did the refusing. Every name the map
    # mentions is declared on both sides — a comparison of names, or a lookup
    # asking "does the target have a `conj`?", passes this system — so what
    # refuses it can only be `Constructor.admits`.
    narrowed = built(narrowed_propositional_calculus_spec())
    grammar = {
        name
        for candidate in narrowed.build_context.variables.values()
        if hasattr(candidate, "patterns")
        for name in [member.name for member in candidate.patterns]
    }
    assert {"conj", "imp", "neg", "wff_var"} <= grammar

    assert translation_errors(pc(), narrowed, PC_MAP)


def test_a_map_naming_something_neither_system_declares_is_refused():
    # Not a narrowing but a mis-stated edge, and the diagnosis says which side is
    # missing — both halves, since either alone reads as the other's fault.
    absent_source = Translation(symbols={"disjunction": "imp"})
    assert "source system's grammar" in translation_errors(pc(), renamed(), absent_source)[0]

    absent_target = Translation(symbols={"implication": "disjunction"})
    assert "target system's grammar" in translation_errors(pc(), renamed(), absent_target)[0]


# ---------------------------------------------------------------------------
# The symbol map: what a rename may not move
# ---------------------------------------------------------------------------


def _odd_target(production) -> SystemSpec:
    """`renamed_propositional_calculus_spec`'s grammar with one production replaced."""
    spec = renamed_propositional_calculus_spec("Odd")
    spec.productions = [
        production if prod.name == production.name else prod
        for prod in spec.productions
    ]
    return spec


def test_a_rename_across_differing_slots_is_refused():
    # A stored term keys its children by slot name and an edge carries no slot
    # map, so two related productions have to spell their slots alike — the one
    # restriction here that is about the tables rather than about soundness.
    odd = built(_odd_target(
        template_prod("wff", "imp", "(a → b)", [("a", "wff"), ("b", "wff")])
    ))
    errors = translation_errors(pc(), odd, PC_MAP)

    assert len(errors) == 1
    assert "slots" in errors[0] and "['p', 'q']" in errors[0]


def test_a_rename_across_differing_kinds_is_refused():
    # A leaf read as a compound and back again is not the same term.
    odd = built(_odd_target(regex_prod("wff", "imp", "impossible[0-9]*")))
    errors = translation_errors(pc(), odd, PC_MAP)

    assert any("regex" in error and "string" in error for error in errors)


def test_a_constant_may_be_relabelled_but_not_turned_into_a_family():
    # From review (Codex). An atom's *value* is free to differ: sending `⊥` to a
    # constant this system spells `bot` is what an interpretation does, and the
    # rebuild honours it by taking the spelling from the target's production
    # (`terms_mapping._literal`).
    #
    # Which *kind* of atom it is, is not free. A family (`p_#`) is a supply of
    # variables whose literals are its base plus a suffix — the term's own names,
    # which no rename touches — so a family read as another base would put tokens
    # into the target that its own grammar cannot mint. Nothing in the two tables
    # describes that rewriting, so it is refused rather than guessed at.
    def with_bottom(spec, sort, production):
        spec.productions = list(spec.productions) + [production]
        return spec

    source = built(with_bottom(
        propositional_calculus_spec(), "formula",
        atom_const_prod("formula", "falsum", "⊥", denotes_constant=True),
    ))
    relabelled = Translation(PC_MAP.sorts, {**PC_MAP.symbols, "falsum": "falsum"})

    spelled = built(with_bottom(
        renamed_propositional_calculus_spec(), "wff",
        atom_const_prod("wff", "falsum", "bot", denotes_constant=True),
    ))
    assert translation_errors(source, spelled, relabelled) == []

    supplied = built(with_bottom(
        renamed_propositional_calculus_spec(), "wff",
        atom_family_prod("wff", "falsum", "f"),
    ))
    errors = translation_errors(source, supplied, relabelled)

    assert any("atoms of different kinds" in error for error in errors)


def test_a_rename_that_loses_a_binder_is_refused():
    # The sharp one, and the reason `scopes_over` is compared at all: the target
    # spells `∀x p` the same way and does not declare that `x` binds. A statement
    # transferred through the map would then have a free occurrence where the
    # system that proved it had a bound one — and freshness, capture and every
    # definitional unfold are decided on exactly that.
    source = built(layered_spec([propositional_calculus_spec(), first_order_logic_spec()]))
    unbound = renamed_first_order_spec("Unbound")
    unbound.productions = [
        template_prod("wff", "all", "∀x p", [("x", "ind"), ("p", "wff")])
        if prod.name == "all"
        else prod
        for prod in unbound.productions
    ]
    errors = translation_errors(source, built(unbound), Translation(**FOL_RENAME))

    assert len(errors) == 1
    assert "binds" in errors[0] and "'universal'" in errors[0]


def test_a_sort_of_the_source_may_be_a_wider_sort_of_the_target():
    # The other direction is *not* refused, and should not be: a target sort that
    # admits more than the source's is §1.1's widening, which is what makes a
    # propositional theorem citable about first-order formulas in the first
    # place. Only narrowing is a claim the target cannot honour.
    source = SystemSpec(
        name="Two connectives",
        brackets=brackets(),
        productions=[
            regex_prod("formula", "prop_var", "[A-Z][A-Z0-9]*"),
            template_prod("formula", "negation", "¬p", [("p", "formula")]),
            template_prod(
                "formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]
            ),
        ],
        lines=[statement_line()],
    )
    # The map names only what this source has — a map is refused for naming a
    # production its source does not declare, which is the test above.
    narrower = Translation(
        sorts=PC_MAP.sorts,
        symbols={k: v for k, v in PC_MAP.symbols.items() if k != "conjunction"},
    )

    assert translation_errors(built(source), renamed(), narrower) == []
