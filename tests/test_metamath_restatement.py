"""The one definition that cannot state itself.

A definition is recognised by an equivalence at the root of its statement, which
works for every definition in `set.mm` except the one that *defines* the
equivalence. `df-bi` gives `<->` its meaning, so it cannot be written with `<->`:
it is a nest of negated implications, root `-.`, and the first shape test refuses
it — correctly, since nothing about `-.` says which of its descendants is being
defined.

Its two forms are perfectly ordinary and merely elsewhere. `set.mm` states them
the usual way round in `dfbi1`, a theorem proved from `df-bi`, and says so in the
file: `$j definition 'dfbi1' for 'wb';`. So the remedy is a declaration naming
that theorem, and this module pins both what it buys and what it is checked
against — the checks being the whole difference between a declaration and a blank
cheque.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.corpus import walk
from website.logical.metamath.definitions import Classified
from website.logical.metamath.setmm import EQUIVALENCES, RESTATEMENTS

# `df-bi`'s shape in miniature, with `set.mm`'s own arrangement preserved: the
# defining `$a` is written without the connective it defines, and a later theorem
# restates it with the connective at the root, **proved from** the `$a`.
#
# `ax-restate` stands in for the propositional derivation `dfbi1` actually uses
# (`impbi`, `con3rr3`, `mt3`), which is several hundred theorems of scaffolding no
# fixture needs — but it takes the `$a`'s statement as a hypothesis, so `newbi1`
# has to cite `df-new` to discharge it and the derivation is a real one. That
# matters: a fixture whose restatement did not actually follow from the assertion
# would exercise the label check while quietly misrepresenting the arrangement it
# is supposed to model. `ax-alt` gives the same conclusion by another route, for
# the test that the citation is what is being checked.
BOOTSTRAP = r"""
$c |- wff ( ) -> -. <-> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wn $a wff -. ph $.
wb $a wff ( ph <-> ps ) $.
df-new $a |- -. ( ( ph <-> ps ) -> -. ( ph -> ps ) ) $.
${
  restate.1 $e |- -. ( ( ph <-> ps ) -> -. ( ph -> ps ) ) $.
  ax-restate $a |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $.
$}
ax-alt $a |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $.
newbi1 $p |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $= ( df-new ax-restate ) ABABCD $.
"""

RESTATED = {"df-new": "newbi1"}


def classify_all(source: str, restatements: dict | None) -> dict[str, Classified]:
    verdicts: list[Classified] = []
    checked = list(
        walk(
            parse(source),
            equivalences=EQUIVALENCES,
            classified=verdicts.append,
            restatements=restatements,
        )
    )
    # The restatement must really be derivable from the assertion, or the fixture
    # models an arrangement `set.mm` does not have.
    assert all(c.verified for c in checked), [c.error for c in checked]
    return {verdict.label: verdict for verdict in verdicts}


def test_without_the_declaration_it_stays_an_axiom() -> None:
    # The behaviour every import had before the declaration existed, and still has
    # when none is given: the root is `-.`, so nothing says it defines.
    classified = classify_all(BOOTSTRAP, None)["df-new"]

    assert not classified.is_definition
    assert "root is not a declared definitional equivalence (wn)" in classified.reason


def test_the_declaration_recovers_the_two_forms() -> None:
    classified = classify_all(BOOTSTRAP, RESTATED)["df-new"]

    assert classified.is_definition, classified.reason
    # Read off the *restatement*, which is where they are the usual way round.
    assert classified.definition.higher == "( ph <-> ps )"
    assert classified.definition.lower == "( ph -> ps )"


def test_the_definition_is_named_for_the_assertion_not_the_restatement() -> None:
    # The restatement supplies the shape and nothing else. What stops being an
    # axiom is `df-new`, and a definitional step cites that — naming the
    # definition after a *derived* theorem would make the primitive basis look
    # smaller while leaving the axiom in it.
    definition = classify_all(BOOTSTRAP, RESTATED)["df-new"].definition

    assert definition.name == "df-new"
    assert definition.label == "df-new"
    # And the restatement is not itself classified: a `$p` is derived, so
    # abbreviating it defines nothing.
    assert "newbi1" not in classify_all(BOOTSTRAP, RESTATED)


def test_a_restatement_that_is_asserted_rather_than_proved_is_refused() -> None:
    # An asserted restatement is a second axiom about the same notation with
    # nothing tying it to the first, so it could say anything at all.
    asserted = BOOTSTRAP.replace(
        "newbi1 $p |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $= ( df-new ax-restate ) ABABCD $.",
        "newbi1 $a |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $.\n"
        "walked $p |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $= ( ax-alt ) ABC $.",
    )
    classified = classify_all(asserted, RESTATED)["df-new"]

    assert not classified.is_definition
    assert "asserted rather than proved" in classified.reason


def test_a_restatement_whose_proof_does_not_cite_the_assertion_is_refused() -> None:
    # The check that carries the weight. No structural test can confirm that a
    # negation nest *is* the biconditional of its parts — deciding that is the
    # semantic reading this approach exists to avoid. What is checkable is that
    # the restatement was derived *from* the assertion, which is what makes it a
    # consequence of the axiom being reclassified rather than an unrelated
    # equivalence pointed at it. Here the same conclusion is reached from `ax-alt`
    # instead, so nothing ties it to `df-new` and the declaration no longer holds.
    uncited = BOOTSTRAP.replace(
        "$= ( df-new ax-restate ) ABABCD $.", "$= ( ax-alt ) ABC $."
    )
    classified = classify_all(uncited, RESTATED)["df-new"]

    assert not classified.is_definition
    assert "whose proof does not cite it" in classified.reason


def test_a_label_the_proof_lists_but_never_uses_does_not_count_as_a_citation() -> None:
    # A compressed proof's label *table* lists what it may cite; the letter stream
    # says what it does cite. Reading the table admits a restatement derived from
    # something else entirely with the assertion's label sitting unused beside it —
    # which defeats the one check standing between this declaration and a blank
    # cheque. Here `df-new` is in the table and the letters select `ax-alt`, and
    # the proof verifies, so nothing else would notice.
    listed = BOOTSTRAP.replace(
        "$= ( df-new ax-restate ) ABABCD $.", "$= ( df-new ax-alt ) ABD $."
    )
    classified = classify_all(listed, RESTATED)["df-new"]

    assert not classified.is_definition
    assert "whose proof does not cite it" in classified.reason


def test_a_d_the_restatement_does_not_carry_is_refused() -> None:
    # The two forms come from the restatement, so its `$d` travels with them. One
    # on the *assertion* that the restatement lacks would simply be dropped,
    # turning a conditionally-asserted statement into an unconditional rewrite.
    # Scoped to `df-new` alone, since a file-level `$d` is active for both.
    scoped = BOOTSTRAP.replace(
        "df-new $a |- -. ( ( ph <-> ps ) -> -. ( ph -> ps ) ) $.",
        "${\n  $d ph ps $.\n"
        "  df-new $a |- -. ( ( ph <-> ps ) -> -. ( ph -> ps ) ) $.\n$}",
    )
    classified = classify_all(scoped, RESTATED)["df-new"]

    assert not classified.is_definition
    assert "does not carry its $d (ph/ps)" in classified.reason


def test_a_restatement_whose_proof_does_not_derive_it_is_refused() -> None:
    # Citing the assertion is not enough: the derivation has to actually reach the
    # statement being read off. Without this a `$p` that decodes and cites, but
    # derives something else, is taken at its declared word — and the definition is
    # registered at the *assertion's* position, while the walk only rejects the
    # restatement later, or never, if `limit` stops first. Nothing retracts a
    # definition, so the check belongs before it is used.
    #
    # `import_proof` settles this against the database alone, which is what makes
    # it possible at all: `dfbi1` cites `impbi`, `con3rr3` and `mt3`, every one
    # proved *after* `df-bi`, so a check needing them to be in the library would
    # refuse the very case this mechanism exists for.
    bogus = BOOTSTRAP.replace(
        "$= ( df-new ax-restate ) ABABCD $.", "$= ( df-new ax-restate ) ABABCDC $."
    )
    verdicts: list[Classified] = []
    checked = list(
        walk(
            parse(bogus),
            equivalences=EQUIVALENCES,
            classified=verdicts.append,
            restatements=RESTATED,
        )
    )
    classified = {v.label: v for v in verdicts}["df-new"]

    # The fixture's point is that the walk *would* have caught it — later.
    assert not any(c.verified for c in checked)
    assert not classified.is_definition
    assert "whose proof does not derive it" in classified.reason


def test_a_syntax_proof_restates_nothing() -> None:
    # A `$p` under a syntax typecode asserts well-formedness, not truth.
    syntax = BOOTSTRAP.replace(
        "newbi1 $p |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $= ( df-new ax-restate ) ABABCD $.",
        "wsyn $p wff ( ph <-> ps ) $= ( wb ) ABC $.\n"
        "walked $p |- ( ( ph <-> ps ) <-> ( ph -> ps ) ) $= ( ax-alt ) ABC $.",
    )
    classified = classify_all(syntax, {"df-new": "wsyn"})["df-new"]

    assert not classified.is_definition
    assert "is not a logical statement" in classified.reason


def test_a_declaration_naming_something_absent_is_refused() -> None:
    classified = classify_all(BOOTSTRAP, {"df-new": "nope"})["df-new"]

    assert not classified.is_definition
    assert "which the database does not have" in classified.reason


def test_the_set_mm_table_names_only_the_bootstrap() -> None:
    # A database bootstraps its equivalence connective once, so a second entry
    # would be a surprise rather than a pattern. Pinned so that adding one has to
    # be deliberate.
    assert RESTATEMENTS == {"df-bi": "dfbi1"}
