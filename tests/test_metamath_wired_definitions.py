"""Importing a Metamath ``$a`` as a definition as well as an axiom.

`metamath.definitions` decides which logical ``$a`` are definitions (roadmap A4);
this is the walk actually registering them. What it fixes is the ordering and the
default: a definition may only give meaning to a symbol the system does not yet
reason with, and this assertion's own rule is stated over the very symbol it
defines — so the definition has to land first, or every one refuses itself.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.kernel import unfold
from website.logical.metamath import parse
from website.logical.metamath.corpus import walk
from website.logical.metamath.definitions import statement_of

# `set.mm`'s shape in miniature: syntax axioms declare the notation, `df-an`
# defines `/\` from primitives, and two theorems are proved over it. `wb` is the
# definitional equivalence, as in `set.mm`.
FRAGMENT = r"""
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
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""

EQUIVALENCES = frozenset({"wb", "wceq"})


def walked(source: str = FRAGMENT, **kwargs):
    database = parse(source)
    verdicts: list = []
    checked = list(walk(database, classified=verdicts.append, **kwargs))
    return checked, verdicts


def test_naming_no_equivalence_registers_no_definitions():
    # The default, and the whole safety of it: a caller that names no definitional
    # equivalence gets the all-axioms import it got before any of this existed,
    # and pays nothing to classify.
    checked, verdicts = walked()

    assert verdicts == []
    assert all(c.verified for c in checked), [c.error for c in checked]


def test_a_definitional_assertion_is_registered_as_a_definition():
    checked, verdicts = walked(equivalences=EQUIVALENCES)

    definitions = [v.label for v in verdicts if v.is_definition]
    assert definitions == ["df-an"]
    assert all(c.verified for c in checked), [c.error for c in checked]


def test_the_definition_lands_before_its_own_rule():
    # The ordering with teeth. A definition may only give meaning to a symbol the
    # system does not already reason with, and `df-an`'s own rule is stated over
    # `/\` — so registering the rule first makes the definition refuse itself on
    # freshness. Nothing in the verdict says which order ran; that it *is* a
    # definition is the evidence.
    _checked, verdicts = walked(equivalences=EQUIVALENCES)
    (df_an,) = [v for v in verdicts if v.label == "df-an"]

    assert df_an.is_definition, df_an.reason
    assert "already reasons with" not in df_an.reason


def test_an_axiom_stays_an_axiom():
    _checked, verdicts = walked(equivalences=EQUIVALENCES)
    (ax_1,) = [v for v in verdicts if v.label == "ax-1"]

    assert not ax_1.is_definition
    assert "not a declared definitional equivalence" in ax_1.reason


def test_only_asserted_statements_are_classified():
    # A `$p` is derived, so whatever it says is already a consequence and
    # abbreviating it defines nothing. Skipping them also skips a statement parse
    # per theorem, which over a corpus is the difference between free and not.
    _checked, verdicts = walked(equivalences=EQUIVALENCES)

    assert "id" not in {v.label for v in verdicts}


def test_a_registered_definition_unfolds_on_the_system_it_joined():
    # Registered means usable, not merely counted: the kernel definition is on the
    # system and applies to a term of the defined form.
    database = parse(FRAGMENT)
    verdicts: list = []
    systems: list = []

    # The walk owns the system, so reach it through a checked theorem's proof.
    for checked in walk(database, equivalences=EQUIVALENCES, classified=verdicts.append):
        if checked.proof is not None:
            systems.append(checked.proof.formal_system)

    system = systems[-1]
    (definition,) = system.definitions
    redex = system.parse("( ph /\\ ps ) [x]").proof_lines[0].formula_term
    unfolded = unfold(definition, redex, system.context)

    assert unfolded is not None
    assert unfolded.to_string() == "-. ( ph -> -. ps )"


def test_a_definition_the_grammar_already_spells_registers_no_notation():
    # The cost half. An imported definition's defined form is grammatical from its
    # own syntax axiom, so a notation for it could never be reached by a parse —
    # and registering one switches off the first-character leaf index for every
    # later parse (`UnionPattern.leaf_candidates`). Over 5,000 set.mm theorems
    # that cost 2.4x; here it is pinned as a property.
    database = parse(FRAGMENT)
    systems = [
        checked.proof.formal_system
        for checked in walk(database, equivalences=EQUIVALENCES)
        if checked.proof is not None
    ]

    system = systems[-1]
    assert len(system.definitions) == 1
    assert list(system.context.definitions) == []


def test_a_statement_reads_the_same_whether_promoted_or_parsed_as_a_line():
    # `statement_of` composes the term at the system's logical sorts rather than
    # through a proof line, so the classifier does not depend on how a line
    # happens to be shaped. The two readings must agree, or the shape tests are
    # being applied to something other than what a proof sees.
    database = parse(FRAGMENT)
    system = next(
        checked.proof.formal_system
        for checked in walk(database, equivalences=EQUIVALENCES)
        if checked.proof is not None
    )
    assertion = database.assertions["df-an"]

    promoted = statement_of(assertion, system)
    line = system.parse(" ".join(assertion.tokens) + " [x]").proof_lines[0].formula_term

    assert promoted is not None
    assert promoted.equal(line, system.context)
