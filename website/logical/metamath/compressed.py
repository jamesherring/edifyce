"""Decoding Metamath's compressed proof format.

A ``$p`` proof is stored as a parenthesised *label table* followed by a run of
capital letters encoding a reverse-Polish program::

    sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
      ( c2 2re 2pos sqrtpclii ) ABCD $.

The letters are a base-20/5 numbering: ``A``-``T`` are the digits 1-20, and each
leading ``U``-``Y`` contributes a further 20, 40, 60, 80, 100 - so a number is a
run of ``U``-``Y`` terminated by one ``A``-``T``. ``Z`` is not a digit: it tags
the step just completed as *saved*, to be cited again later rather than reproved.

Each number selects a step, in three bands:

1. ``1 .. len(mandatory)`` - a mandatory hypothesis of the theorem being proved;
2. the next ``len(labels)`` - an entry of the parenthesised table;
3. beyond that - a previously ``Z``-saved step.

:func:`decode` turns the letters into that sequence of :class:`Step` selections.
It does not execute them; running the stack machine is the importer's job, since
what a step *means* depends on the target representation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .parser import Assertion, Hypothesis, MetamathError

# A-T are digits 1-20; U-Y are the 20s carriers; Z marks a save.
_LOW = "ABCDEFGHIJKLMNOPQRST"
_HIGH = "UVWXY"
_SAVE = "Z"


@dataclass(frozen=True)
class Step:
    """One selection from a decoded proof.

    Exactly one of the three fields is set: ``hypothesis`` (a mandatory
    hypothesis of the theorem), ``label`` (an entry of the label table), or
    ``backreference`` (the index of an earlier saved step).
    """

    hypothesis: Hypothesis | None = None
    label: str | None = None
    backreference: int | None = None
    # Whether the step this selection completes is saved for later citation.
    saved: bool = False


def split_proof(proof: tuple[str, ...]) -> tuple[list[str], str]:
    """Split raw ``$=`` tokens into the label table and the letter stream.

    Raises :class:`MetamathError` for an uncompressed proof (one with no
    parenthesised table), which this importer does not handle.
    """
    if not proof or proof[0] != "(":
        raise MetamathError(
            "Only compressed proofs are supported (expected a '(' label table)."
        )
    if ")" not in proof:
        raise MetamathError("Compressed proof has no closing ')' for its label table.")

    close = proof.index(")")
    return list(proof[1:close]), "".join(proof[close + 1:])


def decode(
    letters: str, labels: list[str], mandatory: tuple[Hypothesis, ...]
) -> list[Step]:
    """Decode a compressed letter stream into the steps it selects."""
    steps: list[Step] = []
    value = 0
    started = False

    for char in letters:
        if char in _HIGH:
            # A carrier digit: 20 per U-Y, offset by which letter it is.
            value = value * 5 + (_HIGH.index(char) + 1)
            started = True
            continue

        if char in _LOW:
            number = value * 20 + (_LOW.index(char) + 1)
            steps.append(_select(number, labels, mandatory))
            value = 0
            started = False
            continue

        if char == _SAVE:
            if not steps or started:
                raise MetamathError("Compressed proof: 'Z' does not follow a complete step.")
            # Mark the step just completed as saved. Steps are frozen, so replace.
            steps[-1] = _saved(steps[-1])
            continue

        raise MetamathError(f"Compressed proof: unexpected character {char!r}.")

    if started:
        raise MetamathError("Compressed proof ends mid-number (trailing U-Y run).")

    return steps


def _saved(step: Step) -> Step:
    return Step(
        hypothesis=step.hypothesis,
        label=step.label,
        backreference=step.backreference,
        saved=True,
    )


def _select(number: int, labels: list[str], mandatory: tuple[Hypothesis, ...]) -> Step:
    # Map a decoded number onto its band: mandatory hypothesis, label table, or
    # an earlier saved step (0-based within the saved sequence).
    if number < 1:
        raise MetamathError(f"Compressed proof: step number {number} is out of range.")

    if number <= len(mandatory):
        return Step(hypothesis=mandatory[number - 1])

    number -= len(mandatory)
    if number <= len(labels):
        return Step(label=labels[number - 1])

    return Step(backreference=number - len(labels) - 1)


def mandatory_of(assertion: Assertion) -> tuple[Hypothesis, ...]:
    """The hypothesis list a proof of ``assertion`` indexes its first band by."""
    return assertion.mandatory
