"""Why a line did not check, as data — and the open goal that is not a failure.

A checker that answers only "no" is usable by a person reading one line and by
nothing else. These pin the two things that change that: a `Failure` carrying what
the assignment search worked out and threw away, and a `[?]` line that is
*unfinished* rather than wrong.

The load-bearing tests are the last two: a hole must not make a proof valid, and
the diagnosis must not cost the checking path anything.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import (
    Definition,
    LinePart,
    LineSpec,
    Production,
    Rule,
    SystemSpec,
    build_system,
)
from website.logical.formal_system import FormalSystem
from website.logical.formal_system.proof import HOLE_KEY, Proof, citation_text

# A reference part that admits `?`, which is what a hole needs of a grammar. The
# Metamath importer's own regex is widened for the same reason.
_REFERENCE = r"[A-Za-z0-9 ,.?-]+"


def propositional() -> FormalSystem:
    return build_system(
        SystemSpec(
            name="pc",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
                Production(
                    sort="formula",
                    name="negation",
                    template="-A",
                    bindings=[("A", "formula")],
                ),
            ],
            rules=[
                Rule(
                    label="MP",
                    name="modus ponens",
                    antecedents=["p", "(p -> q)"],
                    deduction="q",
                    bindings=[("p", "formula"), ("q", "formula")],
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                )
            ],
        )
    )


def quantified() -> FormalSystem:
    """A system with a proviso, so a *side-condition* failure has something to be.

    Generalisation is unsound without the eigenvariable condition, and "GEN does
    not apply" is exactly the message that leaves an author guessing which of the
    rule's several requirements they missed.
    """
    return build_system(
        SystemSpec(
            name="q",
            productions=[
                Production(sort="ind", name="ivar", regex="[x-z]"),
                Production(
                    sort="formula",
                    name="pred",
                    template="P(t)",
                    bindings=[("t", "ind")],
                ),
                Production(
                    sort="formula",
                    name="forall",
                    template="@v.A",
                    bindings=[("v", "ind"), ("A", "formula")],
                    scopes_over={"v": ["A"]},
                ),
            ],
            rules=[
                Rule(
                    label="GEN",
                    name="generalisation",
                    antecedents=["p"],
                    deduction="@x.p",
                    bindings=[("p", "formula"), ("x", "ind")],
                    side_conditions=["not occurs(x, p)"],
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                )
            ],
        )
    )


def checked(system: FormalSystem, text: str) -> Proof:
    return system.parse(text)


def last(proof: Proof) -> object:
    """The last non-blank line — the one every case here is about."""
    return [line for line in proof.proof_lines if not line.empty][-1]


# --- the diagnosis ---------------------------------------------------------


def test_a_slot_no_cited_line_can_fill_is_named() -> None:
    # The most useful thing a failed citation can say, and the reason for all of
    # this: the slot's schema is a premise the proof does not have, which is
    # exactly the next goal for anyone working backwards.
    proof = checked(propositional(), "p [?]\n-p [?]\nq [MP, 1, 2]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "slot-unsatisfied"
    assert failure.rule == "MP"
    assert [slot.schema for slot in failure.slots] == ["(p -> q)"]
    assert failure.slots[0].index == 1
    assert failure.slots[0].candidates == ()
    # The sentence is untouched, so nothing reading it changes behaviour.
    assert failure.message == "MP does not apply."


def test_a_proviso_that_blocked_is_named() -> None:
    # `GEN does not apply` is true of a capture and of a mis-stated conclusion
    # alike. Which of the rule's requirements failed is the difference between a
    # fixable step and a guess.
    proof = checked(quantified(), "P(x) [?]\n@x.P(x) [GEN, 1]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "side-condition"
    # In the author's own words, not the repr of a frozen dataclass.
    assert failure.proviso == "not occurs(x, p)"
    assert failure.lines == (1,)


def test_the_sound_instance_of_the_same_rule_still_checks() -> None:
    # The other half of the previous test: the proviso is what refused it, and it
    # refuses only what it should.
    proof = checked(quantified(), "P(y) [?]\n@x.P(y) [GEN, 1]\n")

    assert last(proof).valid is True
    assert last(proof).failure is None


def test_the_wrong_number_of_antecedents_reports_both_numbers() -> None:
    proof = checked(propositional(), "p [?]\nq [MP, 1]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "antecedent-count"
    assert (failure.expected, failure.given) == (2, 1)


def test_a_citation_that_resolves_to_nothing_keeps_what_was_written() -> None:
    # So a caller can tell a typo from a rule that exists and did not apply.
    proof = checked(propositional(), "q [NOPE, 1]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "bad-reference"
    assert failure.reference == "NOPE, 1"


def test_a_failure_is_json_shaped_and_omits_what_it_does_not_carry() -> None:
    # A `no-formula` carrying nine nulls reads as though nine things were unknown.
    proof = checked(propositional(), "p [?]\n-p [?]\nq [MP, 1, 2]\n")
    record = last(proof).failure.as_dict()

    assert record["code"] == "slot-unsatisfied"
    assert record["rule"] == "MP"
    assert "proviso" not in record
    assert "expected" not in record
    assert record["slots"][0]["schema"] == "(p -> q)"


def test_the_first_diagnosis_wins() -> None:
    # A sharper reason must not be buried by a later, vaguer pass. An out-of-scope
    # citation is decided before the assignment search runs at all.
    system = build_system(
        SystemSpec(
            name="nd",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
            ],
            rules=[
                Rule(
                    label="MP",
                    name="modus ponens",
                    antecedents=["p", "(p -> q)"],
                    deduction="q",
                    bindings=[("p", "formula"), ("q", "formula")],
                )
            ],
            lines=[
                LineSpec(
                    name="assume",
                    shape="assume <formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                    scope="assumption",
                ),
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                ),
            ],
        )
    )
    proof = checked(
        system, "assume p [?]\n    (p -> q) [?]\nq [MP, 1, 2]\n"
    )
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "out-of-scope"


# --- holes -----------------------------------------------------------------


def test_a_hole_is_an_open_goal_and_not_a_mistake() -> None:
    proof = checked(propositional(), "q [?]\n")
    line = last(proof)

    assert line.failure is not None
    assert line.failure.code == "hole"
    assert [hole.number for hole in proof.holes] == [1]
    assert proof.only_holes is True


def test_a_hole_does_not_make_the_proof_valid() -> None:
    """The load-bearing one.

    `proof.valid` is `all(line.valid)`, and promotion is gated on it. A hole that
    reported valid would let a proof with an unproved step be published as proved,
    which is the whole reason a hole is a *failure* carrying a code rather than a
    third verdict.
    """
    proof = checked(propositional(), "q [?]\n")

    assert last(proof).valid is False
    assert proof.valid is False


def test_a_later_line_may_cite_a_hole_and_check() -> None:
    # What makes a proof writable top-down: the goal is assumed while the argument
    # above it is built. Sound because the proof as a whole stays invalid.
    proof = checked(propositional(), "p [?]\n(p -> q) [?]\nq [MP, 1, 2]\n")
    lines = [line for line in proof.proof_lines if not line.empty]

    assert lines[2].valid is True
    assert proof.valid is False
    assert [hole.number for hole in proof.holes] == [1, 2]
    assert proof.only_holes is True


def test_a_broken_step_beside_a_hole_is_not_only_holes() -> None:
    # The distinction a top-down author works against: filling a goal beneath a
    # broken step proves nothing, so the errors come first.
    proof = checked(propositional(), "p [?]\nq [NOPE, 1]\n")

    assert [hole.number for hole in proof.holes] == [1]
    assert proof.only_holes is False


def test_a_finished_proof_has_no_holes_and_is_not_only_holes() -> None:
    # `only_holes` is about work *remaining*, so a proof with none is False rather
    # than vacuously True — a caller looping "while only_holes" must terminate.
    system = propositional()
    proof = checked(system, "p [?]\n")
    assert proof.only_holes is True

    done = system.parse("")
    assert done.holes == []
    assert done.only_holes is False


def test_a_rule_named_like_the_hole_keyword_still_wins() -> None:
    # The precedence `Def` already has: rules resolve first, so a system may
    # repurpose the keyword and nothing here overrides its grammar.
    assert HOLE_KEY == "?"
    system = build_system(
        SystemSpec(
            name="pc",
            productions=[Production(sort="formula", name="var", regex="[p-r]")],
            rules=[
                Rule(
                    label=HOLE_KEY,
                    name="anything",
                    antecedents=[],
                    deduction="p",
                    bindings=[("p", "formula")],
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                )
            ],
        )
    )
    proof = checked(system, "p [?]\n")

    assert last(proof).valid is True
    assert proof.holes == []


# --- the checking path is untouched ----------------------------------------


def test_a_line_that_checks_carries_no_failure() -> None:
    # Diagnosis runs on the failure path only, which is what keeps a corpus whose
    # proofs all check from paying for it.
    proof = checked(quantified(), "P(y) [?]\n@x.P(y) [GEN, 1]\n")

    assert [line.failure is None for line in proof.proof_lines if not line.empty] == [
        False,  # the hole
        True,
    ]


def test_a_line_that_matches_no_line_type_is_diagnosed() -> None:
    # The most common authoring error of all. It is decided in `check_proof`
    # rather than in the citation path, which is why it needs saying separately:
    # a caller branching on `failure` should not have to fall back to reading the
    # sentence for the ordinary case.
    proof = checked(propositional(), "this is not a formula at all\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "unparsed-line"


def test_a_definitional_step_citing_a_later_line_is_diagnosed() -> None:
    # The definitional path had its own early exits, and the same mistake on a
    # rule citation was already diagnosed — so it must be here too.
    system = build_system(
        SystemSpec(
            name="d",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
                Production(
                    sort="formula",
                    name="falsum",
                    atom_value="F",
                    denotes_constant=True,
                ),
            ],
            definitions=[
                Definition(
                    sort="formula",
                    name="d",
                    higher="S",
                    lower="(F -> F)",
                    bindings=[],
                    label="dfS",
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                )
            ],
        )
    )
    # Cites itself, which is neither earlier nor a different line.
    proof = checked(system, "S [dfS, 1]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "ordering"
    assert failure.rule == "dfS"


def test_a_definitional_step_that_relates_to_nothing_names_what_was_tried() -> None:
    system = build_system(
        SystemSpec(
            name="d",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
                Production(
                    sort="formula",
                    name="falsum",
                    atom_value="F",
                    denotes_constant=True,
                ),
            ],
            definitions=[
                Definition(
                    sort="formula",
                    name="d",
                    higher="S",
                    lower="(F -> F)",
                    bindings=[],
                    label="dfS",
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex=_REFERENCE)],
                    logical_sort="formula",
                )
            ],
        )
    )
    proof = checked(system, "p [?]\nq [Def, 1]\n")
    failure = last(proof).failure

    assert failure is not None
    assert failure.code == "definition-mismatch"
    assert failure.lines == (1,)
    assert failure.definitions == ("dfS",)


# --- composing and replacing a citation ------------------------------------


def test_a_citation_is_composed_from_a_label_and_line_numbers() -> None:
    # So a caller proposing a justification structurally never has to know a
    # system's citation syntax — which is where a projection would creep back in.
    assert citation_text("MP", [1, 2]) == "MP, 1, 2"
    assert citation_text(HOLE_KEY) == "?"


def test_replacing_a_citation_keeps_the_rest_of_the_line() -> None:
    system = propositional()

    assert system.recite("q [?]", "MP, 1, 2") == "q [MP, 1, 2]"
    assert system.recite("q [MP, 1, 2]", HOLE_KEY) == "q [?]"


def test_a_line_with_no_citation_to_replace_is_refused() -> None:
    system = propositional()

    assert system.recite("not a line at all", "MP, 1") is None
    assert system.recite("q", "MP, 1") is None


def test_a_replacement_that_would_not_read_back_is_refused() -> None:
    """The reason the substitution is self-checking rather than trusted.

    A `Match` records no positions, so replacing a citation is textual. Making
    the result *read back* as the citation asked for is what turns a fragile
    splice into a safe one: a line that would come out meaning something else is
    refused rather than mangled.
    """
    system = propositional()

    # A citation the grammar's reference part cannot spell — `[` is excluded — so
    # the spliced line either fails to parse or parses as something else. Either
    # way it must not be returned.
    assert system.recite("q [?]", "MP, [1]") is None
