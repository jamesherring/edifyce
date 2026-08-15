"""Why a proof line did not check, as data rather than as a sentence.

A checker that answers only "no" is usable by a person reading one line and by
nothing else. `syl does not apply` is what the assignment search reduces to after
it has already worked out which antecedent slot could not be filled, which
unification failed, and which proviso blocked — and every one of those is what a
caller trying to *repair* the step needs.

So a failed line carries a :class:`Failure` beside its message: a ``code`` from a
closed vocabulary, and whatever structured detail that code implies. The code is
what a machine branches on and the message is what a person reads, and neither is
derived from the other — a sentence rewritten for clarity must not change a
consumer's behaviour.

Computed on the failure path only
---------------------------------
Nothing here runs while a proof is checking. `InferenceRule.check` keeps its
signature and its fast path; diagnosis is a second pass over a line that has
*already* failed, so a corpus whose 47,589 proofs all check pays nothing for it.
That is also what licenses the diagnosis to be thorough: it only ever runs on the
lines someone is looking at.

Display, not soundness
----------------------
Like `rendering`, none of this is consulted by the checker. A wrong `Failure`
misleads a reader; it cannot make a false proof check, because the verdict was
settled before any of it was built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .proof import ProofLine

# The closed vocabulary. Closed because a consumer branches on it: an open set of
# strings invented at each call site is a second message field wearing a hat.
#
# `hole` is the one that is not a failure in the ordinary sense — see
# `proof.HOLE_KEY`. It rides here because a hole *is* an unproved line and every
# consumer that asks "why is this line not established?" wants one answer, not two
# places to look.
FailureCode = Literal[
    "no-formula",
    "unparsed-line",
    "bad-reference",
    "out-of-scope",
    "antecedent-count",
    "too-many-antecedents",
    "slot-unsatisfied",
    "inconsistent-binding",
    "side-condition",
    "ordering",
    "no-subproof",
    "subproof-out-of-scope",
    "discharge-mismatch",
    "definition-mismatch",
    "hole",
]


@dataclass(frozen=True)
class SlotReport:
    """One antecedent slot of a rule, and how the citation fared against it.

    ``schema`` is the slot's pattern as the rule states it — what a line would
    have to look like to fill it. ``candidates`` are the cited line numbers that
    were tried, so a caller can tell "you cited nothing that could fill this" from
    "you cited three things and none fit".
    """

    index: int
    schema: str
    candidates: tuple[int, ...] = ()


@dataclass(frozen=True)
class Failure:
    """Why one proof line is not established.

    ``message`` is the sentence `ProofLine.invalid_message` already carried, kept
    identical so nothing reading it changes behaviour. Everything else is what the
    checker knew and used to throw away.

    Every structured field is optional because the codes carry different detail:
    an `antecedent-count` failure has expected and given, a `side-condition` one
    has the proviso, and `no-formula` has nothing to add. A field left None means
    this code does not carry it, never that it was unavailable.
    """

    code: FailureCode
    message: str
    # The rule or definition the line cited, by label, where one was resolved.
    rule: str | None = None
    # The citation exactly as the author wrote it, where the failure is about the
    # citation rather than about what it resolved to.
    reference: str | None = None
    # Line numbers this failure implicates — the antecedents cited, the opener of
    # a subproof, the source of a definitional step.
    lines: tuple[int, ...] = ()
    # For `antecedent-count` and `too-many-antecedents`.
    expected: int | None = None
    given: int | None = None
    # For `slot-unsatisfied` and `inconsistent-binding`: which of the rule's
    # antecedent slots could not be filled, and what each wanted.
    slots: tuple[SlotReport, ...] = ()
    # For `side-condition`: the proviso that blocked, restated over the binding
    # where the rule could state it.
    proviso: str | None = None
    # For `definition-mismatch`: the definitions tried.
    definitions: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        """A JSON-shaped record, omitting what this code does not carry.

        The API's shape, and the stored one. Omission rather than nulls because a
        failure's detail is sparse by nature — a `no-formula` carrying nine null
        fields reads as though nine things were unknown.
        """
        out: dict[str, object] = {"code": self.code, "message": self.message}
        if self.rule is not None:
            out["rule"] = self.rule
        if self.reference is not None:
            out["reference"] = self.reference
        if self.lines:
            out["lines"] = list(self.lines)
        if self.expected is not None:
            out["expected"] = self.expected
        if self.given is not None:
            out["given"] = self.given
        if self.slots:
            out["slots"] = [
                {
                    "index": slot.index,
                    "schema": slot.schema,
                    "candidates": list(slot.candidates),
                }
                for slot in self.slots
            ]
        if self.proviso is not None:
            out["proviso"] = self.proviso
        if self.definitions:
            out["definitions"] = list(self.definitions)
        return out


def numbers(lines: Sequence[ProofLine]) -> tuple[int, ...]:
    """The citation numbers of these lines, skipping any that have none.

    A line is numbered when it is *placed*, and a diagnosis may hold one that
    never was — a citation resolving to a blank or a comment, or a line the parse
    rejected before numbering reached it. Diagnosing a failure must not fail in
    turn, so an unnumbered line is left out rather than reported as None among
    integers.
    """
    return tuple(line.number for line in lines if line.number is not None)
