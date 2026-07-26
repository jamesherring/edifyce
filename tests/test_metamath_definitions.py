"""Which of a Metamath database's logical ``$a`` are definitions (roadmap A4).

Metamath does not distinguish a definition from an axiom — both are ``$a``, and
`df-` is a naming convention its verifier never reads. The classifier decides
structurally, and the tests below are the cases that shaped it: each fragment is
the *reason* one of the three tests exists, and three of them are quoted from
`set.mm` because reasoning alone got them wrong.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_system
from website.logical.metamath import build_spec, parse
from website.logical.metamath.definitions import classify, constructors_used


def classify_all(source: str) -> dict[str, object]:
    """Classify every logical `$a` in `source`, in file order."""
    database = parse(source)
    system = build_system(build_spec(database, name="t"))

    in_use: set[str] = set()
    out = {}
    for assertion in database.iter_assertions():
        if not assertion.is_logical or assertion.proof:
            continue
        line = system.parse(" ".join(assertion.tokens) + " [x]").proof_lines[0]
        term = line.formula_term
        out[assertion.label] = classify(assertion, database, system, term, in_use)
        if term is not None:
            in_use |= constructors_used(term)
    return out


# `wa` is defined from `wn`/`wi`, exactly as set.mm's `df-an` does it; `ax-1` is
# set.mm's verbatim first axiom, and is the reason the bare-metavariable test
# exists — an implication has a biconditional's shape.
PROPOSITIONAL = r"""
$c |- wff ( ) -> -. <-> /\ $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wn $a wff -. ph $.
wb $a wff ( ph <-> ps ) $.
wa $a wff ( ph /\ ps ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
df-an $a |- ( ( ph /\ ps ) <-> -. ( ph -> -. ps ) ) $.
"""


def test_a_biconditional_introducing_notation_is_a_definition():
    classified = classify_all(PROPOSITIONAL)["df-an"]

    assert classified.is_definition
    definition = classified.definition
    assert definition.sort == "wff"
    assert definition.higher == "( ph /\\ ps )"
    assert definition.lower == "-. ( ph -> -. ps )"
    assert definition.label == "df-an"


def test_an_implication_is_not_a_definition_of_its_own_antecedent():
    # `ax-1` is `|- ( ph -> ( ps -> ph ) )`. Its root takes two `wff` slots, just
    # as a biconditional does, and `ph` is notation not yet in use the first time
    # it appears — so the first and third tests both pass and it reads as
    # `ph := ( ps -> ph )`. Only "the defined side is not a bare metavariable"
    # refuses it. Found by running the classifier over set.mm, not by reasoning.
    classified = classify_all(PROPOSITIONAL)["ax-1"]

    assert not classified.is_definition
    assert "bare metavariable" in classified.reason


# `df-bi` must define `<->` without using it, so set.mm states it as a nest of
# negated implications. Quoted verbatim.
DEFINES_ITS_OWN_CONNECTIVE = r"""
$c |- wff ( ) -> -. <-> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wn $a wff -. ph $.
wb $a wff ( ph <-> ps ) $.
df-bi $a |- -. ( ( ( ph <-> ps ) -> -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) ) ->
  -. ( -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) -> ( ph <-> ps ) ) ) $.
"""


def test_a_definition_that_cannot_use_its_own_connective_stays_an_axiom():
    # Definitional in intent, but not fold/unfold-shaped: its root is `-.`, not a
    # relation between two wffs. The roadmap's rule is that anything which does
    # not reduce to fold/unfold defaults to axiom, never to a silent `Define`.
    classified = classify_all(DEFINES_ITS_OWN_CONNECTIVE)["df-bi"]

    assert not classified.is_definition
    assert "not a relation between two things of one sort" in classified.reason


# `df-cleq` in miniature: an equivalence whose *defined* side is ordinary `=`,
# put in use by the reflexivity axiom before it. set.mm names it `df-`, but it is
# an axiom connecting class notation to set theory, not an eliminable definition.
REUSED_NOTATION = r"""
$c |- wff class setvar ( ) <-> A. e. = $.
$v x ph ps A B $.
vx $f setvar x $.
wph $f wff ph $.
wps $f wff ps $.
cA $f class A $.
cB $f class B $.
cv $a class x $.
wceq $a wff A = B $.
wcel $a wff A e. B $.
wb $a wff ( ph <-> ps ) $.
wal $a wff A. x ph $.
ax-eqid $a |- A = A $.
df-cleq $a |- ( A = B <-> A. x ( x e. A <-> x e. B ) ) $.
"""


def test_an_equivalence_over_notation_already_in_use_stays_an_axiom():
    classified = classify_all(REUSED_NOTATION)["df-cleq"]

    assert not classified.is_definition
    assert "already in use" in classified.reason


def test_the_classifier_reads_shape_not_the_label():
    # Nothing consults the `df-` prefix: a definition-shaped statement named
    # `ax-` is a definition, and that is the point — Metamath's verifier never
    # reads the convention either.
    renamed = PROPOSITIONAL.replace("df-an $a", "ax-conj $a")
    classified = classify_all(renamed)["ax-conj"]

    assert classified.is_definition
    assert classified.definition.higher == "( ph /\\ ps )"
