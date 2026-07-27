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


# The productions that mean definitional equivalence in these fragments, as
# set.mm's do: `wb` is `( ph <-> ps )` and `wceq` is `A = B`. Declared, because
# nothing structural tells an equivalence from an implication.
EQUIVALENCES = frozenset({"wb", "wceq"})


def classify_all(source: str, equivalences=EQUIVALENCES) -> dict[str, object]:
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
        out[assertion.label] = classify(
            assertion, term, in_use, database, system, equivalences
        )
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
    assert "not a declared definitional equivalence" in classified.reason


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
    assert "not a declared definitional equivalence" in classified.reason


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


# A definition whose defining side uses the very form it defines. `in_use` cannot
# see this — it holds what *earlier* assertions used — and neither can the kernel,
# which leaves non-circularity untreated.
CIRCULAR = r"""
$c |- wff ( ) -> <-> NEW $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
wnew $a wff NEW ph $.
df-new $a |- ( NEW ph <-> ( NEW ph -> ph ) ) $.
"""


def test_a_recursive_alias_is_not_a_definition():
    classified = classify_all(CIRCULAR)["df-new"]

    assert not classified.is_definition
    assert "built from the form being defined" in classified.reason


# `df-sb` and `df-mo` are set.mm's two definition-shaped `$a` under hypotheses.
# Here the hypothesis is stated by nothing, so there is nothing to cite.
CONDITIONAL = r"""
$c |- wff ( ) -> <-> NEW $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
wnew $a wff NEW ph $.
${
  df-cond.1 $e |- ph $.
  df-cond $a |- ( NEW ph <-> ( ph -> ph ) ) $.
$}
"""


def test_an_assertion_under_a_hypothesis_nothing_proves_is_not_a_definition():
    # A definition holds unconditionally, so an undischarged premise would licence
    # unfolds the `$a` forbids.
    classified = classify_all(CONDITIONAL)["df-cond"]

    assert not classified.is_definition
    assert "which nothing proved before it states" in classified.reason


# `df-sb`'s shape: a hypothesis stated verbatim by a theorem proved earlier in the
# file, which is how `set.mm` discharges the obligation itself (`sbjust`).
JUSTIFIED = r"""
$c |- wff ( ) -> <-> NEW $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
ax-id $a |- ( ph -> ph ) $.
newjust $p |- ( ph -> ph ) $= ( wi ax-id ) B $.
wnew $a wff NEW ph $.
${
  newjust.1 $e |- ( ph -> ph ) $.
  df-new $a |- ( NEW ph <-> ( ph -> ph ) ) $.
$}
"""


def test_a_hypothesis_a_proved_theorem_states_becomes_a_justification():
    classified = classify_all(JUSTIFIED)["df-new"]

    assert classified.is_definition
    justification = classified.definition.justification
    assert justification is not None
    assert justification.label == "newjust"
    assert justification.statement == "( ph -> ph )"


def test_only_a_proof_ahead_of_the_definition_discharges_its_hypothesis():
    # A theorem stated *after* the definition is not available to it: the import
    # checks every assertion against only what precedes it, and a justification
    # that reached forwards would be the one place that ordering leaked.
    later = JUSTIFIED.replace(
        "newjust $p |- ( ph -> ph ) $= ( wi ax-id ) B $.\n", ""
    ).replace("$}", "$}\nnewjust $p |- ( ph -> ph ) $= ( wi ax-id ) B $.")
    classified = classify_all(later)["df-new"]

    assert not classified.is_definition
    assert "which nothing proved before it states" in classified.reason


def test_an_assertion_under_several_hypotheses_is_not_a_definition():
    # A `Definition` carries one obligation. Two would have to be guessed at, and
    # `set.mm` never needs it — `df-sb` and `df-mo` have a single `$e` each.
    several = JUSTIFIED.replace(
        "  newjust.1 $e |- ( ph -> ph ) $.",
        "  newjust.1 $e |- ( ph -> ph ) $.\n  newjust.2 $e |- ( ps -> ps ) $.",
    )
    classified = classify_all(several)["df-new"]

    assert not classified.is_definition
    assert "several hypotheses" in classified.reason


# A `$d` restricts which substitutions the definition admits, so it has to travel
# with it — 1,033 of set.mm's definition-shaped statements carry one.
WITH_PROVISO = r"""
$c |- wff class setvar ( ) <-> A. e. NEW $.
$v x ph ps A B $.
vx $f setvar x $.
wph $f wff ph $.
wps $f wff ps $.
cA $f class A $.
cB $f class B $.
cv $a class x $.
wcel $a wff A e. B $.
wb $a wff ( ph <-> ps ) $.
wal $a wff A. x ph $.
wnew $a wff NEW x A $.
${
  $d x A $.
  df-new $a |- ( NEW x A <-> A. x x e. A ) $.
$}
"""


def test_a_distinct_variable_constraint_travels_with_the_definition():
    classified = classify_all(WITH_PROVISO)["df-new"]

    assert classified.is_definition
    condition = classified.definition.condition
    assert condition is not None and "disjoint(" in condition



# A one-way implication whose antecedent is a *fresh compound* — so the
# bare-metavariable test does not fire, and only naming the equivalence refuses
# it. Reading this as `NEW ph ps := ph` would licence the reverse rewrite.
ONE_WAY = r"""
$c |- wff ( ) -> <-> NEW $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
wnew $a wff NEW ph ps $.
ax-new $a |- ( NEW ph ps -> ph ) $.
"""


def test_a_one_way_implication_is_not_a_definition():
    classified = classify_all(ONE_WAY)["ax-new"]

    assert not classified.is_definition
    assert "not a declared definitional equivalence" in classified.reason


def test_nothing_is_a_definition_when_no_equivalence_is_declared():
    # The default: a caller that names no equivalence gets every logical `$a` as
    # an axiom, which is the import's behaviour before any of this.
    classified = classify_all(PROPOSITIONAL, equivalences=frozenset())

    assert not any(c.is_definition for c in classified.values())
