"""Declared binding slots on an imported Metamath grammar.

A ``.mm`` file says nothing about which slots bind — `A. x ph` and a two-argument
connective are the same shape, and Metamath's verifier never needs to tell them
apart, since `$d` provisos carry the weight instead. Edifyce needs the answer,
because a definition whose defining form binds a dummy must declare that dummy
`fresh` or the unfold would conjure a name. So it is *declared* per database
(:mod:`website.logical.metamath.setmm`), and this is what the declaration buys.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import build_spec, parse
from website.logical.metamath.corpus import walk
from website.logical.metamath.definitions import Classified
from website.logical.metamath.parser import MetamathError
from website.logical.metamath.setmm import BINDERS, EQUIVALENCES

# `df-tru`'s shape, which is the shape of 1,123 of set.mm's refusals: the defining
# form quantifies over an `x` the defined form has no room for. Sound in Metamath,
# and sound here — but only once something says `A. x ph` binds `x` in `ph`.
FRAGMENT = r"""
$c |- wff setvar ( ) -> <-> = A. T. $.
$v x ph ps $.
vx $f setvar x $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
weq $a wff x = x $.
wal $a wff A. x ph $.
wtru $a wff T. $.
df-tru $a |- ( T. <-> ( A. x x = x -> A. x x = x ) ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( A walk classifies what it passes, so the fragment needs something to walk. $)
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""

FORALL_BINDS = {"wal": {"x": ["ph"]}}


def classify_all(binders: dict | None) -> dict[str, Classified]:
    verdicts: list[Classified] = []
    list(
        walk(
            parse(FRAGMENT),
            equivalences=EQUIVALENCES,
            classified=verdicts.append,
            binders=binders,
        )
    )
    return {verdict.label: verdict for verdict in verdicts}


def test_without_a_declaration_a_bound_dummy_reads_as_introduced() -> None:
    # The behaviour every import had before the declaration existed, and still has
    # when none is given: `x` is quantified in the defining form and absent from
    # `T.`, and nothing says the quantifier binds it, so it reads as a name the
    # unfold would conjure.
    classified = classify_all(None)["df-tru"]

    assert not classified.is_definition
    assert "defining side introduces 'x'" in classified.reason


def test_declaring_the_binder_makes_it_a_definition() -> None:
    classified = classify_all(FORALL_BINDS)["df-tru"]

    assert classified.is_definition, classified.reason
    assert classified.definition.higher == "T."


def test_the_declaration_reaches_the_production() -> None:
    spec = build_spec(parse(FRAGMENT), name="t", binders=FORALL_BINDS)
    forall = next(p for p in spec.productions if p.name == "wal")

    assert forall.scopes_over == {"x": ["ph"]}
    # And a production nobody declared says nothing, which is what keeps this safe
    # for every grammar written before binding slots existed.
    equality = next(p for p in spec.productions if p.name == "weq")
    assert equality.scopes_over == {}


def test_a_declaration_naming_a_variable_the_axiom_lacks_is_refused() -> None:
    # Silently dropping it would leave a binder undeclared, which is the very thing
    # the declaration exists to fix — so a typo is an error, not a no-op.
    with pytest.raises(MetamathError) as excinfo:
        build_spec(parse(FRAGMENT), name="t", binders={"wal": {"nope": ["ph"]}})

    assert "'wal'" in str(excinfo.value) and "'nope'" in str(excinfo.value)


def test_a_declaration_scoping_over_a_variable_the_axiom_lacks_is_refused() -> None:
    with pytest.raises(MetamathError) as excinfo:
        build_spec(parse(FRAGMENT), name="t", binders={"wal": {"x": ["nope"]}})

    assert "scopes over 'nope'" in str(excinfo.value)


def test_a_renamed_slot_still_matches_its_declaration() -> None:
    # `_uncollide` renames a slot whose name occurs inside one of the template's
    # constants — set.mm's `wral` is `A. x e. A ph`, where the class `A` is found
    # inside the quantifier `A.`. A declaration is written against the `$f` names
    # an author reads in the file, so the rename has to be applied to it too, or
    # the commonest binder in the corpus would silently go undeclared.
    source = FRAGMENT.replace(
        "wal $a wff A. x ph $.",
        "$c e. $.\n$v A $.\ncA $f setvar A $.\nwral $a wff A. x e. A ph $.",
    )
    spec = build_spec(parse(source), name="t", binders={"wral": {"x": ["ph"]}})
    restricted = next(p for p in spec.productions if p.name == "wral")

    # The class slot was renamed; the binder and its target were not, and the
    # declaration still lands on the slots the production actually has.
    slots = {var for var, _sort in restricted.bindings}
    assert set(restricted.scopes_over) <= slots
    assert restricted.scopes_over == {"x": ["ph"]}


def test_the_set_mm_table_names_only_real_binders() -> None:
    # The table is data about one library, so what it claims is checkable against
    # that library. Here only its shape is checked (a corpus test would need the
    # 51 MB file); every entry is verified against set.mm's own syntax axioms in
    # the roadmap's A4 measurement.
    assert EQUIVALENCES == frozenset({"wb", "wceq"})
    assert len(BINDERS) == 28
    for label, scopes in BINDERS.items():
        assert scopes, f"{label} declares no binder"
        for binder, scoped in scopes.items():
            assert scoped, f"{label}'s {binder} scopes over nothing"
            assert binder not in scoped, f"{label}'s {binder} scopes over itself"
