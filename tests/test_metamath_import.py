"""Importing Metamath into Edifyce: the ``sqrt2re`` vertical slice.

Covers ``website.logical.metamath`` end to end — read ``.mm`` source, build the
grammar from its syntax axioms, promote its logical assertions to citable
theorems, decode a compressed proof, and have Edifyce's own kernel check the
result.

The specimen is set.mm's ``sqrt2re`` ("the square root of 2 is a real number"),
whose stored proof is short enough to reason about in full::

    sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
      ( c2 2re 2pos sqrtpclii ) ABCD $.

Executing ``ABCD`` against that label table: ``c2`` builds the class ``2``
(*syntax* — no logical content), ``2re`` and ``2pos`` supply ``|- 2 e. RR`` and
``|- 0 < 2``, and ``sqrtpclii`` consumes all three to conclude. So four stored
steps import as **three** proof lines: Edifyce parses well-formedness instead of
proving it, and the syntax step simply disappears.

``2re``/``2pos``/``sqrtpclii`` appear here as ``$a``, standing in for the part of
the library an import would already have processed; ``sqrt2re``'s proof is the
verbatim set.mm string, which is what the decoder is actually tested against.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import (
    MetamathError,
    build_spec,
    decode,
    import_database,
    import_proof,
    parse,
    split_proof,
)
from website.logical.metamath.parser import Hypothesis


# A self-contained fragment of set.mm: every statement below is quoted from it.
SQRT2RE_FRAGMENT = r"""
$c |- wff class ( ) ` e. RR sqrt 2 0 < $.
$v A B F R $.
cA $f class A $.
cB $f class B $.
cF $f class F $.
cR $f class R $.

$( Syntax axioms — in Metamath these *are* the grammar. $)
wcel $a wff A e. B $.
wbr $a wff A R B $.
cfv $a class ( F ` A ) $.
c2 $a class 2 $.
cr $a class RR $.
csqrt $a class sqrt $.
cc0 $a class 0 $.
clt $a class < $.

$( The library this slice builds on. $)
2re $a |- 2 e. RR $.
2pos $a |- 0 < 2 $.
${
  sqrtthi.1 $e |- A e. RR $.
  ${
    sqrpclii.2 $e |- 0 < A $.
    sqrtpclii $a |- ( sqrt ` A ) e. RR $.
  $}
$}

$( The theorem, with its proof exactly as set.mm stores it. $)
sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
  ( c2 2re 2pos sqrtpclii ) ABCD $.
"""


EXPECTED_PROOF = (
    "2 e. RR [2re]\n"
    "0 < 2 [2pos]\n"
    "( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]"
)


@pytest.fixture(scope="module")
def database():
    return parse(SQRT2RE_FRAGMENT)


# ---------------------------------------------------------------------------
# Reading .mm source
# ---------------------------------------------------------------------------
def test_syntax_and_logic_are_separated(database):
    # The `|-` typecode marks an assertion of truth; every other typecode
    # declares notation. Keeping them apart is what lets syntax steps vanish.
    assert [a.label for a in database.syntax_assertions()] == [
        "wcel", "wbr", "cfv", "c2", "cr", "csqrt", "cc0", "clt",
    ]
    assert [a.label for a in database.logical_assertions()] == [
        "2re", "2pos", "sqrtpclii", "sqrt2re",
    ]


def test_mandatory_hypotheses_are_scoped_and_ordered(database):
    # `sqrtpclii` sits inside two nested scopes, so it takes both essentials —
    # plus the floating hypothesis for the `A` they mention, which is declared
    # far earlier. Order is declaration order, and it is what the proof's stack
    # machine pops by, so getting it wrong silently misaligns every application.
    assert [h.label for h in database.assertions["sqrtpclii"].mandatory] == [
        "cA", "sqrtthi.1", "sqrpclii.2",
    ]

    # `sqrt2re` mentions no variables and sits in no scope: nothing is mandatory,
    # which is why its proof indexes the label table directly.
    assert database.assertions["sqrt2re"].mandatory == ()


def test_floating_hypotheses_of_unmentioned_variables_are_not_mandatory(database):
    # `cB`/`cF`/`cR` are active everywhere but mentioned by neither `sqrtpclii`'s
    # statement nor its essentials, so they are not popped when it is applied.
    mandatory = {h.label for h in database.assertions["sqrtpclii"].mandatory}
    assert {"cB", "cF", "cR"}.isdisjoint(mandatory)


def test_comments_and_scope_errors(database):
    assert parse("$c a $. $( a comment $) $v x $.").constants == {"a"}

    with pytest.raises(MetamathError, match="Unterminated comment"):
        parse("$c a $. $( never closed")

    with pytest.raises(MetamathError, match="Unbalanced"):
        parse("${ $c a $.")


# ---------------------------------------------------------------------------
# The compressed proof format
# ---------------------------------------------------------------------------
def test_split_proof_separates_the_label_table(database):
    labels, letters = split_proof(database.assertions["sqrt2re"].proof)
    assert labels == ["c2", "2re", "2pos", "sqrtpclii"]
    assert letters == "ABCD"


def test_uncompressed_proofs_are_refused():
    with pytest.raises(MetamathError, match="Only compressed proofs"):
        split_proof(("2re", "ax-mp"))


def test_letters_number_steps_in_base_twenty():
    # A-T are 1-20; each leading U-Y adds a further 20 in base five, so the
    # sequence runs A..T, UA..UT, VA.., .., YA..YT, then UUA.
    labels = [f"L{n}" for n in range(1, 130)]

    def selected(letters):
        return [step.label for step in decode(letters, labels, ())]

    assert selected("A") == ["L1"]
    assert selected("T") == ["L20"]
    assert selected("UA") == ["L21"]
    assert selected("UT") == ["L40"]
    assert selected("VA") == ["L41"]
    assert selected("YA") == ["L101"]
    assert selected("UUA") == ["L121"]
    assert selected("ABC") == ["L1", "L2", "L3"]


def test_step_numbers_select_across_the_three_bands():
    # Band 1 is the theorem's own mandatory hypotheses, band 2 the label table,
    # band 3 the steps saved by `Z`.
    hypothesis = Hypothesis(
        label="h1", typecode="|-", tokens=("A",), floating=False, position=0
    )
    steps = decode("ABZC", ["only"], (hypothesis,))

    assert steps[0].hypothesis is hypothesis         # 1 -> the mandatory hyp
    assert steps[1].label == "only"                  # 2 -> the one table entry
    assert steps[1].saved is True                    # ...tagged by the Z
    assert steps[2].backreference == 0               # 3 -> the first saved step


def test_malformed_letter_streams_are_rejected():
    with pytest.raises(MetamathError, match="'Z' does not follow"):
        decode("Z", ["a"], ())

    with pytest.raises(MetamathError, match="ends mid-number"):
        decode("AU", ["a"], ())

    with pytest.raises(MetamathError, match="unexpected character"):
        decode("A?", ["a"], ())


# ---------------------------------------------------------------------------
# The import itself
# ---------------------------------------------------------------------------
def test_syntax_axioms_become_the_grammar(database):
    spec = build_spec(database)
    productions = {p.name: p for p in spec.productions}

    # A syntax axiom with variables is a template over its floating hypotheses,
    # which are listed in *declaration* order (`cA` precedes `cF` in the file),
    # not in order of appearance in the template.
    assert productions["cfv"].sort == "class"
    assert productions["cfv"].template == "( F ` A )"
    assert productions["cfv"].bindings == [("A", "class"), ("F", "class")]

    # ...and one without is a constant of its sort.
    assert productions["c2"].atom_value == "2"
    assert productions["c2"].template is None


def test_logical_assertions_are_promoted_not_made_rules(database):
    system = import_database(database)

    assert set(system.promoted_theorems) == {"2re", "2pos", "sqrtpclii", "sqrt2re"}
    # They are derived results, so they stay out of the system's primitive rules.
    assert system.inference_rules == []

    # `sqrtpclii` keeps its premises and its metavariable, so it re-instantiates.
    promoted = system.promoted_theorems["sqrtpclii"]
    assert len(promoted.antecedents) == 2
    assert set(promoted.variables) == {"A"}

    # `2re` is closed: nothing to instantiate.
    assert system.promoted_theorems["2re"].antecedents == ()
    assert system.promoted_theorems["2re"].variables == {}


def test_sqrt2re_imports_to_the_expected_proof(database):
    assert import_proof(database, "sqrt2re") == EXPECTED_PROOF


def test_syntax_steps_emit_no_proof_line(database):
    # Four stored steps (`ABCD`), three imported lines: `c2` built the class `2`,
    # which Edifyce gets by parsing rather than by proof.
    _labels, letters = split_proof(database.assertions["sqrt2re"].proof)
    assert len(letters) == 4
    assert len(import_proof(database, "sqrt2re").splitlines()) == 3


def test_the_imported_proof_is_checked_by_the_kernel(database):
    # The payoff: a real Metamath proof, translated, and verified by Edifyce's
    # own checker. Nothing in the importer re-verifies anything.
    system = import_database(database)
    proof = system.parse(import_proof(database, "sqrt2re"))

    assert proof.valid is True
    assert all(line.valid for line in proof.proof_lines)


def test_a_tampered_import_is_rejected(database):
    # The check is real: swap the conclusion for one that does not follow and the
    # kernel refuses it, so a green import is evidence rather than assumption.
    system = import_database(database)
    tampered = import_proof(database, "sqrt2re").replace(
        "( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]", "0 < 2 [sqrtpclii, 1, 2]"
    )

    assert system.parse(tampered).proof_lines[-1].valid is False


def test_import_errors_are_reported(database):
    with pytest.raises(MetamathError, match="No assertion labelled"):
        import_proof(database, "nosuchlabel")

    with pytest.raises(MetamathError, match="has no proof"):
        import_proof(database, "2re")
