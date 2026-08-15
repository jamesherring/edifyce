#!/usr/bin/env python
"""Blank a real proof's justifications and drive the loop to restore them.

    uv run python scripts/restore_proofs.py set.mm --limit 300 --proofs 25

The roadmap's §7–§9c built a structured authoring loop — ``holes`` to say what is
open, ``/cite`` to justify a line, ``/lines`` to state one — and exercised it with
three-line synthetic proofs. This drives the same loop against a **corpus**, where
the original proof is the answer key: blank a step's citation and the right answer
is already known, so success is exact and needs no search.

Five rounds, each reaching a different part of the write path:

**cite** — park every step as a hole (``[?]``), then justify them back. Blanked
bottom-up and restored top-down, so the open goals are a *suffix* of the proof
throughout and ``only_holes`` is checkable at every step in between, not only at
the ends. The proof must come out byte-identical to the one that was imported, and
valid. Each call is a source edit with everything a source edit entails.

**insert** — dry-run a new line *before* an existing one, which renumbers every
citation below it. A mis-shifted citation still resolves, so nothing but "no
previously-valid line became invalid" catches it — and a corpus proof, where a
single step may cite a dozen lines, is where that bites.

**state** — restate a step's own formula as a **constructor tree** rebuilt from
its stored rows, and require the line that comes back to be spelled exactly as the
corpus spelled it. The term round trip is the endpoint's own check; what this adds
is real grammar to run it against, and an answer key for the *spelling*, which the
endpoint has none for.

**probe** — offer deliberately wrong citations and require the refusal to land in
the closed vocabulary rather than in a generic sentence (§7). Two of the six
mutations are measurements rather than assertions: whether a *swapped* citation is
refused says whether antecedent order carries information, and whether one with no
antecedents at all is says how far the checker will infer.

**apply** — actually insert a line mid-proof, read the stored structure back, and
take it out again with `/lines/remove`. Two things the dry runs cannot reach: a
renumbered proof persisted and then re-checked from its rows, and insert-and-remove
as a genuine round trip, since the proof has to come back byte-identical.

Everything is throwaway: the import lands in a SQLite file (or ``--database-url``)
and the corpus proofs are given an owner so the owner-only apply path is reachable.
Nothing here touches a deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/restore_proofs.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, func, inspect, make_url, select  # noqa: E402
from sqlalchemy import update as sa_update  # noqa: E402
from sqlalchemy.exc import ArgumentError  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from app.db import (  # noqa: E402
    Base,
    FormalSystem,
    Proof,
    ProofLineAntecedentRow,
    ProofLineRow,
)
from app.db.metamath_store import import_corpus  # noqa: E402
from app.db.models import Theorem, User  # noqa: E402
from app.db.session import asyncpg_url, psycopg_url  # noqa: E402
from app.db.terms import TERM_KIND_NODE  # noqa: E402
from app.db.terms_mapping import StoredTerm, prefetch_terms, walk_subgraph  # noqa: E402
from app.routers.proofs import (  # noqa: E402
    propose_citation,
    propose_line,
    remove_line,
    update_proof,
    verify_stored_proof,
)
from app.schemas import (  # noqa: E402
    CitationOutcome,
    CitationProposal,
    LineOutcome,
    LineProposal,
    LineRemoval,
    LineRemovalOutcome,
    ProofDetail,
    ProofUpdate,
    TermProposalIn,
    VerifyProofResponse,
)
from website.logical.formal_system.proof import (  # noqa: E402
    CITATION_SEPARATOR,
    HOLE_KEY,
    citation_text,
)
from website.logical.metamath import parse  # noqa: E402
from website.logical.metamath.setmm import (  # noqa: E402
    DISPLAY_OVERRIDES,
    DISPLAY_RULES,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

ROUNDS = ("cite", "insert", "state", "probe", "apply")

# What one of these endpoints answers with. Named because `Call` carries whichever
# of them the route it wrapped returns, and `object` would say nothing.
Outcome = (
    CitationOutcome
    | LineOutcome
    | LineRemovalOutcome
    | ProofDetail
    | VerifyProofResponse
)


# ---------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One numbered line of a corpus proof, as the checker decomposed it.

    The rule is the name the checker **resolved**, off the row rather than out of
    the text. The antecedents are the lines the *citation* names, in the order it
    names them, and that split is deliberate: an edge's position is the rule's
    **slot**, and the assignment search fills slots by matching, so `[MP, 2, 1]`
    and `[MP, 1, 2]` store exactly the same edges. Only the citation records which
    of the two the author wrote, and the `cite` round has to put back the one that
    was there.

    So the order is read off the citation and the identity is checked against the
    edges (`Key.discrepancies`), rather than either being trusted alone.
    """

    number: int
    position: int
    rule: str
    antecedents: tuple[int, ...]
    term_id: uuid.UUID
    display: str


@dataclass(frozen=True)
class Key:
    """A corpus proof and everything a round needs to check itself against."""

    proof_id: uuid.UUID
    label: str
    source: str
    steps: tuple[Step, ...]
    # Every citation number the proof has, including any line `steps` left out.
    numbered: tuple[int, ...]
    # Steps whose citation and whose justification edges name different lines.
    # Not a reason to skip: the two are meant to describe one thing, so a
    # disagreement is a finding about the store rather than about this proof.
    discrepancies: tuple[str, ...] = ()

    @property
    def widest(self) -> int:
        return max((len(s.antecedents) for s in self.steps), default=0)

    @property
    def drivable(self) -> bool:
        """Whether the rounds' arithmetic holds for this proof.

        They index steps by number and predict a renumbering from the count, both
        of which assume the citation numbers run 1..N with a rule behind each. A
        Metamath proof is flat and always does; a hand-written one with a scope
        opener or an unjustified line does not, and would be *silently*
        mis-asserted rather than caught — so it is skipped instead.
        """
        wanted = tuple(range(1, len(self.numbered) + 1))
        return bool(self.steps) and self.numbered == wanted and tuple(
            step.number for step in self.steps
        ) == wanted


@dataclass
class Result:
    """One round's verdict for one proof."""

    label: str
    round: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class Tally:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    calls: int = 0
    seconds: float = 0.0
    results: list[Result] = field(default_factory=list)

    def record(self, result: Result) -> None:
        self.results.append(result)
        if result.skipped:
            self.skipped += 1
        elif result.ok:
            self.passed += 1
        else:
            self.failed += 1


# ---------------------------------------------------------------------------
# Calling the endpoints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    """What an endpoint returned, or the ``HTTPException`` it raised instead.

    The routes are awaited directly rather than driven over HTTP: their arguments
    are already resolved dependencies (a session and a user), and the request
    models are still constructed, so what is skipped is transport rather than
    validation. What is *not* skipped is the raise — a route reports half its
    refusals as an exception, and a harness that let those escape would count a
    409 as a crash instead of as a finding.
    """

    outcome: Outcome | None = None
    status: int | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is not None


async def _call(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    work: Callable[[AsyncSession, User], Awaitable[Outcome]],
) -> Call:
    # A session per call, as a request would get: the routes commit, and sharing
    # one session across the loop would let a later call see an earlier one's
    # identity map rather than the row it wrote.
    async with sessions() as session:
        user = await session.get(User, owner)
        try:
            return Call(outcome=await work(session, user))
        except HTTPException as exc:
            return Call(status=exc.status_code, detail=str(exc.detail))


async def _cite(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    proof_id: uuid.UUID,
    line: int,
    rule: str,
    antecedents: Sequence[int] = (),
    apply: bool = True,
) -> Call:
    payload = CitationProposal(
        line=line, rule=rule, antecedents=list(antecedents), apply=apply
    )
    return await _call(
        sessions,
        owner,
        lambda session, user: propose_citation(
            proof_id, payload, user=user, session=session
        ),
    )


async def _line(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    proof_id: uuid.UUID,
    statement: TermProposalIn,
    rule: str = HOLE_KEY,
    before: int | None = None,
    apply: bool = False,
) -> Call:
    payload = LineProposal(statement=statement, rule=rule, before=before, apply=apply)
    return await _call(
        sessions,
        owner,
        lambda session, user: propose_line(
            proof_id, payload, user=user, session=session
        ),
    )


async def _remove(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    proof_id: uuid.UUID,
    line: int,
    apply: bool = True,
) -> Call:
    payload = LineRemoval(line=line, apply=apply)
    return await _call(
        sessions,
        owner,
        lambda session, user: remove_line(proof_id, payload, user=user, session=session),
    )


async def _rewrite(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    proof_id: uuid.UUID,
    source: str,
) -> Call:
    """Put a source back through the ordinary edit route, and re-check it.

    Two calls because they are two operations: `update_proof` discards the stored
    structure and the cached verdict rather than recomputing them, so a proof
    edited and not verified sits at ``valid = None`` — which the selection reads
    as "not a verified proof" just as firmly as False.
    """
    payload = ProofUpdate(source=source)
    edited = await _call(
        sessions,
        owner,
        lambda session, user: update_proof(proof_id, payload, user=user, session=session),
    )
    return edited if not edited.ok else await _verify(sessions, owner, proof_id)


async def _verify(
    sessions: async_sessionmaker[AsyncSession], owner: uuid.UUID, proof_id: uuid.UUID
) -> Call:
    return await _call(
        sessions,
        owner,
        lambda session, user: verify_stored_proof(
            proof_id, user=user, session=session
        ),
    )


# ---------------------------------------------------------------------------
# The rounds
# ---------------------------------------------------------------------------


async def round_cite(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    counter: list[int],
) -> Result:
    """Park every step as a hole, then justify them all back.

    Blanked **bottom-up** and restored top-down, so the open goals are a suffix of
    the proof at every point in between. That is what makes ``only_holes``
    checkable at each step rather than only at the ends: a proof whose unfinished
    part is exactly its tail has nothing wrong with it, and the loop saying
    otherwise mid-flight would be the difference between "keep going" and "back
    up", which is the signal the whole thing runs on.
    """
    numbers = [step.number for step in key.steps]
    for index in range(len(key.steps) - 1, -1, -1):
        step = key.steps[index]
        counter[0] += 1
        blanked = await _cite(sessions, owner, key.proof_id, step.number, HOLE_KEY)
        if not blanked.ok:
            return Result(
                key.label,
                "cite",
                False,
                f"line {step.number} would not take a hole: "
                f"{blanked.status} {blanked.detail}",
            )
        if blanked.outcome.accepted:
            return Result(
                key.label, "cite", False, f"line {step.number} accepted a hole as proved"
            )
        code = blanked.outcome.failure.code if blanked.outcome.failure else None
        if code != "hole":
            return Result(
                key.label,
                "cite",
                False,
                f"line {step.number} parked as a hole reports {code!r}, not 'hole'",
            )
        wrong = _open_goals(blanked.outcome, numbers[index:])
        if wrong is not None:
            return Result(
                key.label, "cite", False, f"after blanking line {step.number}, {wrong}"
            )

    counter[0] += 1
    opened = await _verify(sessions, owner, key.proof_id)
    if not opened.ok:
        return Result(key.label, "cite", False, f"verify raised: {opened.detail}")
    if opened.outcome.holes != numbers:
        return Result(
            key.label,
            "cite",
            False,
            f"holes are {opened.outcome.holes}, expected {numbers}",
        )
    if not opened.outcome.only_holes:
        return Result(
            key.label,
            "cite",
            False,
            f"a fully blanked proof reports errors beside its holes: "
            f"{opened.outcome.errors[:3]}",
        )

    for index, step in enumerate(key.steps):
        counter[0] += 1
        restored = await _cite(
            sessions, owner, key.proof_id, step.number, step.rule, step.antecedents
        )
        if not restored.ok:
            return Result(
                key.label,
                "cite",
                False,
                f"line {step.number} refused its own citation "
                f"[{step.rule}{''.join(f', {n}' for n in step.antecedents)}]: "
                f"{restored.status} {restored.detail}",
            )
        if not restored.outcome.accepted:
            failure = restored.outcome.failure
            return Result(
                key.label,
                "cite",
                False,
                f"line {step.number} rejected its own citation "
                f"{restored.outcome.citation!r}: "
                f"{failure.code if failure else 'no reason given'} — "
                f"{failure.message if failure else ''}",
            )
        wrong = _open_goals(restored.outcome, numbers[index + 1 :])
        if wrong is not None:
            return Result(
                key.label, "cite", False, f"after restoring line {step.number}, {wrong}"
            )

    return await _settled(sessions, owner, key, "cite")


def _open_goals(
    outcome: CitationOutcome | LineOutcome, expected: Sequence[int]
) -> str | None:
    """What an applied proposal got wrong about where the proof now stands."""
    if outcome.holes != list(expected):
        return f"the open goals are {outcome.holes}, expected {list(expected)}"
    if expected and not outcome.only_holes:
        return "an unfinished proof reports something wrong beside its holes"
    if expected and outcome.valid:
        return "a proof with open goals reports itself proved"
    if not expected and not outcome.valid:
        return "a proof with no open goals left does not verify"
    return None


async def _settled(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    round_name: str,
) -> Result:
    # The proof must be back to the text that was imported, not merely to
    # something that verifies: an equivalent-but-different source would mean the
    # loop silently rewrote a step, which is the thing an answer key is for.
    async with sessions() as session:
        proof = await session.get(Proof, key.proof_id)
        source, valid = proof.source, proof.valid
    if source != key.source:
        return Result(
            key.label,
            round_name,
            False,
            f"restored source differs from the corpus's:\n"
            f"    want {key.source!r}\n     got {source!r}",
        )
    if not valid:
        return Result(key.label, round_name, False, "restored proof does not verify")
    return Result(key.label, round_name, True)


async def round_insert(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    counter: list[int],
    positions: int,
) -> Result:
    """Dry-run an inserted line above existing steps, renumbering what follows."""
    total = len(key.steps)
    for number in _spread(range(1, total + 1), positions):
        step = key.steps[number - 1]
        counter[0] += 1
        # A hole restating a line that already stands: the statement is certainly
        # grammatical, so what is under test is the renumbering rather than the
        # term. `ref` is the cheapest way to say it and the one an elaboration
        # loop would use.
        added = await _line(
            sessions,
            owner,
            key.proof_id,
            TermProposalIn(ref=step.term_id),
            before=number,
        )
        if not added.ok:
            return Result(
                key.label,
                "insert",
                False,
                f"inserting before line {number} of {total}: "
                f"{added.status} {added.detail}",
            )
        outcome = added.outcome
        if outcome.accepted:
            return Result(
                key.label, "insert", False, f"the hole inserted at {number} was accepted"
            )
        moved = list(range(number + 1, total + 2))
        if outcome.renumbered != moved:
            return Result(
                key.label,
                "insert",
                False,
                f"inserting before {number} renumbered {outcome.renumbered}, "
                f"expected {moved}",
            )
    return Result(key.label, "insert", True)


async def round_apply(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    counter: list[int],
) -> Result:
    """Actually insert a line mid-proof, and read the stored structure back.

    What the dry runs above cannot reach: a renumbered proof **stored** and then
    re-checked from its rows, which is the path a verify takes ever after (P2). A
    citation shifted in the text but not in the edges — or the reverse — verifies
    fine on the way in and is wrong on the way out, and only reading the rows back
    against the answer key says so.

    The proof is put back afterwards through ``/lines/remove``, which makes the
    restore a *test* rather than a cleanup: insert and remove are inverse
    renumberings and `_settled` demands the corpus's own bytes back. Whether that
    works or not the proof **is** put back — by the edit route if the removal
    would not — because a `--keep` re-run must find the corpus as it was, and a
    proof left carrying a hole is not merely different but *invalid*, which the
    selection reads as "not a proof to drive" and drops silently.
    """
    total = len(key.steps)
    if total < 2:
        return Result(key.label, "apply", True, "too short to insert into", skipped=True)
    at = max(2, total // 2)
    counter[0] += 1
    added = await _line(
        sessions,
        owner,
        key.proof_id,
        TermProposalIn(ref=key.steps[at - 1].term_id),
        before=at,
        apply=True,
    )
    if not added.ok:
        return Result(
            key.label, "apply", False, f"inserting before {at}: {added.status} {added.detail}"
        )
    if added.outcome.holes != [at]:
        return Result(
            key.label,
            "apply",
            False,
            f"after inserting a hole at {at} the open goals are {added.outcome.holes}",
        )
    if not added.outcome.only_holes:
        return Result(
            key.label,
            "apply",
            False,
            f"inserting a hole at {at} broke something else in the proof",
        )

    # Re-verified rather than trusted: the outcome above came from the check that
    # *wrote* the rows, and this one reads them.
    counter[0] += 1
    again = await _verify(sessions, owner, key.proof_id)
    if not again.ok:
        return Result(key.label, "apply", False, f"re-verify raised: {again.detail}")
    if again.outcome.holes != [at] or not again.outcome.only_holes:
        return Result(
            key.label,
            "apply",
            False,
            f"re-read from its rows the proof reports holes {again.outcome.holes}, "
            f"only_holes={again.outcome.only_holes}",
        )

    async with sessions() as session:
        stored = await session.run_sync(
            lambda sync: _key(sync, sync.get(Proof, key.proof_id))
        )
    verdict = _shifted(key, stored, at)

    # Taken back out through the loop's own operation rather than by rewriting the
    # source, which makes the restore a *test* instead of a cleanup: insert and
    # remove are inverse renumberings, and `_settled` below requires the corpus's
    # own bytes back, so anything either of them gets wrong shows up here.
    counter[0] += 1
    removed = await _remove(sessions, owner, key.proof_id, at)
    if not removed.ok:
        # Reported *and* undone. Returning here would leave the proof holed and so
        # invalid, and the selection would drop it from every later `--keep` run —
        # a failure quietly shrinking the next run's coverage.
        counter[0] += 1
        await _rewrite(sessions, owner, key.proof_id, key.source)
        return Result(
            key.label,
            "apply",
            False,
            f"the inserted line would not come back out: "
            f"{removed.status} {removed.detail}",
        )
    moved = [step.number for step in key.steps if step.number >= at]
    if removed.outcome.renumbered != moved:
        return Result(
            key.label,
            "apply",
            False,
            f"removing line {at} renumbered {removed.outcome.renumbered}, "
            f"expected {moved}",
        )
    return verdict if not verdict.ok else await _settled(sessions, owner, key, "apply")


def _shifted(key: Key, stored: Key, at: int) -> Result:
    """Every original step, still saying what it said, at its new number.

    The inserted line itself is not among ``stored.steps``: it is a hole, so no
    rule resolved for it, and `_key` keeps only the steps a rule justified.
    """
    by_number = {step.number: step for step in stored.steps}
    for step in key.steps:
        moved = step.number + 1 if step.number >= at else step.number
        now = by_number.get(moved)
        if now is None:
            return Result(key.label, "apply", False, f"line {step.number} vanished")
        if now.term_id != step.term_id:
            return Result(
                key.label,
                "apply",
                False,
                f"line {step.number} states something else at its new number {moved}",
            )
        if now.rule != step.rule:
            return Result(
                key.label,
                "apply",
                False,
                f"line {moved} is justified by {now.rule!r}, was {step.rule!r}",
            )
        want = tuple(n + 1 if n >= at else n for n in step.antecedents)
        if now.antecedents != want:
            return Result(
                key.label,
                "apply",
                False,
                f"line {moved} now cites {now.antecedents}, expected {want}",
            )
    return Result(key.label, "apply", True)


async def round_state(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    counter: list[int],
    rows: dict[uuid.UUID, StoredTerm],
    children: dict[uuid.UUID, tuple[tuple[str, uuid.UUID], ...]],
    budget: int,
    lines: int,
) -> Result:
    """Restate a step's formula as structure and check it comes back spelled right."""
    skipped: list[str] = []
    checked = 0
    for number in _spread([step.number for step in key.steps], lines):
        step = key.steps[number - 1]
        try:
            statement = _expand(step.term_id, rows, children, budget)
        except _Unproposable as exc:
            skipped.append(f"line {number} {exc}")
            continue

        counter[0] += 1
        # Inserted *before* the line it restates, so the template the new line
        # takes its shape from is that line itself and the expected spelling is
        # exact. A dry run, so the proof is unchanged either way.
        added = await _line(
            sessions, owner, key.proof_id, statement, before=number
        )
        if not added.ok:
            return Result(
                key.label,
                "state",
                False,
                f"restating line {number}: {added.status} {added.detail}",
            )
        # The endpoint already refused anything whose *term* did not survive the
        # round trip; what is checked here is the **spelling**, which it has no
        # answer key for. A corpus line and its restatement differ only in the
        # citation, so the hole is put back to compare.
        want = _holed(step.display)
        if added.outcome.display != want:
            return Result(
                key.label,
                "state",
                False,
                f"restated line {number} reads {added.outcome.display!r}, "
                f"corpus spells it {want!r}",
            )
        checked += 1
    if not checked:
        return Result(key.label, "state", True, "; ".join(skipped), skipped=True)
    return Result(key.label, "state", True, "; ".join(skipped))


# The citation mutations the `probe` round tries. Four have a verdict they must
# be refused with; two are *measurements* — `swapped` and `none-cited` are both
# things the checker may legitimately accept, and what they are here for is to say
# how often it does (see `_expected_code`).
_MUTATIONS = (
    "unknown-rule",
    "one-short",
    "one-long",
    "self-citing",
    "swapped",
    "none-cited",
)


async def round_probe(
    sessions: async_sessionmaker[AsyncSession],
    owner: uuid.UUID,
    key: Key,
    counter: list[int],
    steps: int,
    codes: dict[str, int],
) -> Result:
    """Offer wrong citations and require the refusal to say something usable.

    §7's claim is that a rejection names the next goal rather than only saying no.
    Synthetic fixtures can only show that the codes exist; what this asks is
    whether a *corpus* rule — one with a dozen antecedents, a schema that binds
    across nested statements — still lands in the closed vocabulary rather than in
    the generic sentence. Every probe is a dry run.
    """
    for number in _spread([step.number for step in key.steps], steps):
        step = key.steps[number - 1]
        for mutation in _MUTATIONS:
            proposed = _mutate(mutation, step)
            if proposed is None:
                continue
            rule, antecedents = proposed
            counter[0] += 1
            tried = await _cite(
                sessions,
                owner,
                key.proof_id,
                number,
                rule,
                antecedents,
                apply=False,
            )
            if not tried.ok:
                return Result(
                    key.label,
                    "probe",
                    False,
                    f"line {number} {mutation}: {tried.status} {tried.detail}",
                )
            outcome = tried.outcome
            wanted = _expected_code(mutation)
            if outcome.accepted:
                if wanted is not None:
                    # A mutation with a verdict of its own must be refused. An
                    # accepted one is the *worst* result this round can produce —
                    # the checker took a citation that is wrong — so it fails
                    # rather than being counted alongside the measurements.
                    return Result(
                        key.label,
                        "probe",
                        False,
                        f"line {number} accepted a {mutation} citation, which "
                        f"should have been refused with {wanted!r}",
                    )
                # `swapped` and `none-cited` may legitimately go through; counted
                # so the run says how often they do.
                codes[f"{mutation}:accepted"] = codes.get(f"{mutation}:accepted", 0) + 1
                continue
            failure = outcome.failure
            if failure is None or not failure.message:
                return Result(
                    key.label,
                    "probe",
                    False,
                    f"line {number} {mutation} was refused with no reason attached",
                )
            codes[f"{mutation}:{failure.code}"] = (
                codes.get(f"{mutation}:{failure.code}", 0) + 1
            )
            if wanted is not None and failure.code != wanted:
                return Result(
                    key.label,
                    "probe",
                    False,
                    f"line {number} {mutation} reports {failure.code!r}, "
                    f"expected {wanted!r} — {failure.message}",
                )
    return Result(key.label, "probe", True)


def _expected_code(mutation: str) -> str | None:
    if mutation == "unknown-rule":
        return "bad-reference"
    if mutation == "self-citing":
        return "ordering"
    if mutation in ("one-short", "one-long"):
        return "antecedent-count"
    # `swapped` and `none-cited` have no expected verdict: the assignment search
    # is a bipartite matching, so antecedent *order* carries no information, and
    # citing none at all is not an error but a request to infer them.
    return None


def _mutate(mutation: str, step: Step) -> tuple[str, tuple[int, ...]] | None:
    """A wrong citation of the given shape, or None where the step has no such."""
    if mutation == "unknown-rule":
        return ("no-such-rule-" + step.rule, step.antecedents)
    if mutation == "one-short":
        # Two or more, because dropping the *only* antecedent is not a short
        # citation at all — an empty list asks the checker to infer them
        # (`Proof.justify`), which is what `none-cited` measures.
        return (step.rule, step.antecedents[:-1]) if len(step.antecedents) > 1 else None
    if mutation == "none-cited":
        return (step.rule, ()) if step.antecedents else None
    if mutation == "one-long":
        return (step.rule, (*step.antecedents, step.antecedents[-1]
                            if step.antecedents else 1))
    if mutation == "self-citing":
        # A line among its own antecedents: it cannot stand before itself, and
        # the checker has an ordering verdict for exactly that. One antecedent is
        # *replaced* rather than appended, so the count stays right and ordering
        # is the only thing left wrong — appending would (correctly) be reported
        # as `antecedent-count` first, which tests nothing new.
        return (
            (step.rule, (*step.antecedents[:-1], step.number))
            if step.antecedents
            else None
        )
    if mutation == "swapped":
        reversed_ = tuple(reversed(step.antecedents))
        return (
            (step.rule, reversed_)
            if len(step.antecedents) > 1 and reversed_ != step.antecedents
            else None
        )
    raise ValueError(f"unknown mutation {mutation!r}")


def _holed(display: str) -> str:
    # A corpus line ends in its citation, so the expected restatement is the same
    # line with a hole in its place. Rebuilt by cutting at the last bracket rather
    # than by re-deriving the line type, because this is a comparison string and
    # not something the checker will read.
    opened = display.rfind("[")
    return f"{display[:opened]}[{HOLE_KEY}]" if opened >= 0 else display


class _Unproposable(Exception):
    """A term this round cannot offer as a structured proposal."""


class _TooBig(_Unproposable):
    """A term whose fully-expanded tree exceeds the node budget.

    Not a defect: a term is an interned DAG, so a statement sharing one subterm
    twenty ways expands to a tree far larger than the graph. ``ref`` is the
    endpoint's answer to exactly that, and this round is the one that declines to
    use it.
    """


def _expand(
    term_id: uuid.UUID,
    rows: dict[uuid.UUID, StoredTerm],
    children: dict[uuid.UUID, tuple[tuple[str, uuid.UUID], ...]],
    budget: int,
) -> TermProposalIn:
    """A stored term as a proposal naming productions all the way down.

    Deliberately *not* using ``ref`` for a shared subterm, though that is what the
    endpoint is for: the point of this round is to run the render/reparse round
    trip over as much real grammar as possible, and a ``ref`` is exactly the part
    that skips it. A term is an interned DAG, so full expansion can blow up —
    hence the budget, and hence the skip rather than a crash.
    """
    spent = [0]

    def walk(node_id: uuid.UUID) -> TermProposalIn:
        spent[0] += 1
        if spent[0] > budget:
            raise _TooBig(f"expands past {budget} nodes")
        row = rows[node_id]
        if row.kind != TERM_KIND_NODE:
            # A `var` or a `bound` names a schematic or bound variable, and
            # `TermProposalIn` deliberately offers neither: a proof line states a
            # ground formula. Reported rather than failed — the skip list is the
            # measurement.
            raise _Unproposable(f"carries a {row.kind!r} term, which has no proposal")
        if row.constructor is None:
            raise _Unproposable("carries a node with no constructor")
        return TermProposalIn(
            constructor=row.constructor,
            # A constant atom's token comes off the production, and passing a
            # different one is refused — but these rows record what was parsed, so
            # passing the stored literal is right for both kinds of leaf.
            literal=row.literal,
            sort=row.sort,
            slots={slot: walk(child) for slot, child in children.get(node_id, ())},
        )

    return walk(term_id)


def _spread(items: Iterable[int], count: int) -> list[int]:
    """At most ``count`` of ``items``, evenly spaced, ends included."""
    values = list(items)
    if count >= len(values):
        return values
    if count <= 1:
        return values[-1:]
    step = (len(values) - 1) / (count - 1)
    return sorted({values[round(index * step)] for index in range(count)})


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _provision(url: str, recreate: bool) -> None:
    """An empty schema for the run.

    Every table but the pgvector ``theorems``, which needs an extension and which
    nothing here reads. A SQLite file is deleted rather than dropped table by
    table: ``proofs`` and ``promoted_theorems`` reference each other, so a sorted
    DROP is impossible without ``ALTER``, which SQLite has not got.

    **Refuses a target that already holds systems** unless ``recreate``. This is a
    harness that drops every table and then reassigns the owner of every proof it
    finds, and the natural thing to reach for when handing it a
    ``--database-url`` is the one already in the shell's ``DATABASE_URL``. Making
    that take an explicit flag costs a retry; not making it costs a database.
    """
    if _holds_data(url):
        if not recreate:
            raise SystemExit(
                f"{url} already holds formal systems. This run would drop every "
                "table and take ownership of every proof — pass --recreate if that "
                "is what you meant, or --keep to reuse what is there."
            )
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).unlink(missing_ok=True)
    engine = create_engine(url)
    try:
        tables = [
            table
            for table in Base.metadata.tables.values()
            if table.name != Theorem.__tablename__
        ]
        if not url.startswith("sqlite:///"):
            Base.metadata.drop_all(engine, tables=tables)
        Base.metadata.create_all(engine, tables=tables)
    finally:
        engine.dispose()


def _holds_data(url: str) -> bool:
    """Whether this target already carries an Edifyce system.

    A missing table means an unprovisioned database, which is the case this whole
    guard is here to let through.
    """
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table(FormalSystem.__tablename__):
                return False
            return bool(
                connection.execute(select(func.count()).select_from(FormalSystem)).scalar()
            )
    finally:
        engine.dispose()


def _own(url: str, email: str) -> uuid.UUID:
    """Give the corpus an owner and take it back to drafts, so the apply path is
    reachable.

    An import is deliberately ownerless (`app.db.metamath_store`), which is right
    for a library and wrong for a harness: ``/cite`` and ``/lines`` refuse to
    apply for anyone but the owner. Taking ownership of the imported proofs is
    preferable to copying them, because a proof's own ``$e`` hypotheses are
    citable from the proof that establishes its library entry and nowhere else —
    a copy could not cite them, and a corpus proof's first steps usually do.

    Unpublished for a second reason with the same shape. An import publishes what
    verified, and a *published* proof may not be edited into a state that does not
    verify (`_require_publishable`, re-run on every applied edit) — which is
    exactly what this harness does on purpose, since punching a hole in a proof is
    the first half of every round. Right for a library, wrong here. The systems
    stay published: they are read, not edited, and a draft system would refuse the
    proofs' own publication anyway.
    """
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            user = User(
                email=email,
                # Never authenticated against: the routes are called with the
                # user object directly, so nothing hashes or compares this.
                hashed_password="unused",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            session.add(user)
            session.flush()
            session.execute(
                sa_update(Proof).values(owner_id=user.id, published_at=None)
            )
            session.commit()
            return user.id
    finally:
        engine.dispose()


def _keys(url: str, wanted: Sequence[str] | None, count: int, longest: bool) -> list[Key]:
    """The answer keys for the proofs this run will drive."""
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            query = select(Proof).where(Proof.valid.is_(True))
            if wanted:
                query = query.where(Proof.name.in_(wanted))
            elif longest:
                lines = (
                    select(
                        ProofLineRow.proof_id.label("pid"),
                        func.count().label("n"),
                    )
                    .group_by(ProofLineRow.proof_id)
                    .subquery()
                )
                query = (
                    query.join(lines, lines.c.pid == Proof.id)
                    .order_by(lines.c.n.desc())
                    .limit(count)
                )
            else:
                query = query.order_by(Proof.position)
            proofs = list(session.scalars(query).all())
            if not wanted and not longest:
                proofs = [proofs[i] for i in _spread(range(len(proofs)), count)]
            return [_key(session, proof) for proof in proofs]
    finally:
        engine.dispose()


def _key(session: Session, proof: Proof) -> Key:
    rows = session.scalars(
        select(ProofLineRow)
        .where(ProofLineRow.proof_id == proof.id, ProofLineRow.number.is_not(None))
        .order_by(ProofLineRow.number)
        .options(
            selectinload(ProofLineRow.antecedents).selectinload(
                ProofLineAntecedentRow.antecedent_line
            )
        )
    ).all()
    steps: list[Step] = []
    discrepancies: list[str] = []
    for row in rows:
        if row.rule is None or row.opens_scope is not None or row.behaviour != "logical":
            continue
        cited = _cited(row)
        if cited is None:
            # A reference `/cite` could not write back — a dotted lemma citation,
            # a definitional step, anything whose text is not `rule, ints`. Left
            # out of the steps, which makes the proof undrivable rather than
            # driving it against an answer key that cannot restore it.
            continue
        edges = {
            edge.antecedent_line.number
            if edge.antecedent_line is not None
            else edge.antecedent_number
            for edge in row.antecedents
        }
        if edges != set(cited):
            discrepancies.append(
                f"{proof.name} line {row.number}: cites {sorted(cited)} but its "
                f"edges point at {sorted(edges)}"
            )
        steps.append(
            Step(
                number=row.number,
                position=row.position,
                rule=row.rule,
                antecedents=cited,
                term_id=row.term_id,
                display=row.display,
            )
        )
    return Key(
        proof_id=proof.id,
        label=proof.name,
        source=proof.source,
        steps=tuple(steps),
        numbered=tuple(row.number for row in rows),
        discrepancies=tuple(discrepancies),
    )


def _cited(row: ProofLineRow) -> tuple[int, ...] | None:
    """The lines this row's citation names, in order — or None if `/cite` cannot
    write that citation back.

    The condition is exactly the one the `cite` round needs and is checked as
    such: the reference must be *reproduced* by `citation_text(row.rule, ...)`.
    That covers the rule resolving to something the citation does not spell (a
    `[Def, 3]` step, a rule found by search) and any antecedent that is not a bare
    number (a dotted `[MP, A.2]`, which names a line of another proof), without
    having to enumerate those cases.
    """
    if row.reference is None:
        return None
    tokens = row.reference.split(CITATION_SEPARATOR)
    numbers: list[int] = []
    for token in tokens[1:]:
        if not token.isdigit():
            return None
        numbers.append(int(token))
    ordered = tuple(numbers)
    return ordered if citation_text(row.rule, ordered) == row.reference else None


def _term_rows(
    url: str, keys: Sequence[Key]
) -> tuple[dict[uuid.UUID, StoredTerm], dict[uuid.UUID, tuple[tuple[str, uuid.UUID], ...]]]:
    """Every stored row under the statements the ``state`` round will rebuild.

    Read through `walk_subgraph` rather than by rebuilding terms: that needs a
    built system, and this round wants the **rows** — it is going to hand them
    back as a proposal and let the endpoint do the building.
    """
    rows: dict[uuid.UUID, StoredTerm] = {}
    children: dict[uuid.UUID, tuple[tuple[str, uuid.UUID], ...]] = {}
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            roots = [step.term_id for key in keys for step in key.steps]
            graph = prefetch_terms(session, roots)
            for root in roots:
                for node in walk_subgraph(graph, root):
                    rows[node.id] = node.row
                    children[node.id] = node.children
    finally:
        engine.dispose()
    return rows, children


# ---------------------------------------------------------------------------
# Driving
# ---------------------------------------------------------------------------


async def drive(
    url: str,
    owner: uuid.UUID,
    keys: Sequence[Key],
    rounds: Sequence[str],
    arguments: argparse.Namespace,
    rows: dict[uuid.UUID, StoredTerm],
    children: dict[uuid.UUID, tuple[tuple[str, uuid.UUID], ...]],
    codes: dict[str, int],
) -> dict[str, Tally]:
    engine = create_async_engine(_async_url(url))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tallies = {name: Tally() for name in rounds}
    try:
        for index, key in enumerate(keys, start=1):
            for name in rounds:
                counter = [0]
                started = time.monotonic()
                if name == "cite":
                    result = await round_cite(sessions, owner, key, counter)
                elif name == "insert":
                    result = await round_insert(
                        sessions, owner, key, counter, arguments.insert_positions
                    )
                elif name == "state":
                    result = await round_state(
                        sessions,
                        owner,
                        key,
                        counter,
                        rows,
                        children,
                        arguments.max_nodes,
                        arguments.state_lines,
                    )
                elif name == "probe":
                    result = await round_probe(
                        sessions, owner, key, counter, arguments.probe_lines, codes
                    )
                else:
                    result = await round_apply(sessions, owner, key, counter)
                tally = tallies[name]
                tally.calls += counter[0]
                tally.seconds += time.monotonic() - started
                tally.record(result)
                if not result.ok:
                    print(f"  ! {key.label} [{name}] {result.detail}", flush=True)
                elif not arguments.quiet:
                    mark = "skipped" if result.skipped else "ok"
                    print(
                        f"  [{index}/{len(keys)}] {key.label} {name} {mark}"
                        f"{' — ' + result.detail if result.detail else ''}",
                        flush=True,
                    )
    finally:
        await engine.dispose()
    return tallies


def _sync_url(url: str) -> str:
    """A URL an operator gave us, on a driver that is actually installed.

    SQLite passes through — it names its own driver and has no platform dialect
    to correct. Everything else goes through `app.db.session.psycopg_url`, which
    is where the two rules about platform URLs live (see `_async_url` below for
    the other half).
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return url
    return psycopg_url(parsed).render_as_string(hide_password=False)


def _async_url(url: str) -> str:
    """The async driver URL matching a synchronous one.

    Postgres goes through the app's own normalisation rather than a second copy
    of it: asyncpg is not libpq, so a platform URL's ``sslmode`` has to be
    translated and its ``channel_binding`` dropped, and those two rules should
    have one home (`app.db.session.asyncpg_url`).
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return parsed.set(drivername="sqlite+aiosqlite").render_as_string(
            hide_password=False
        )
    return asyncpg_url(parsed).render_as_string(hide_password=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {number}")
    return number


def _ordered_rounds(text: str) -> list[str]:
    """The rounds ``text`` names, in `ROUNDS` order whatever order it names them.

    The rounds are not independent — `apply` edits the proof the others read from,
    which is why it runs last — so the sequence is the harness's to decide rather
    than a knob. Taking the operator's order would let ``--rounds apply,cite``
    drive `cite` against an answer key one line out of date and report a failure
    that is the flag's fault.
    """
    asked = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in asked if name not in ROUNDS]
    if unknown:
        raise ValueError(f"unknown round(s): {', '.join(unknown)}")
    return [name for name in ROUNDS if name in asked]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit", type=_positive, default=300, help="import only the first N theorems"
    )
    parser.add_argument(
        "--proofs", type=_positive, default=25, help="drive N of the imported proofs"
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="drive this Metamath label (repeatable); overrides --proofs",
    )
    parser.add_argument(
        "--longest",
        action="store_true",
        help="take the proofs with the most lines rather than a spread of them",
    )
    parser.add_argument(
        "--rounds",
        default=",".join(ROUNDS),
        help=f"comma-separated subset of {','.join(ROUNDS)}",
    )
    parser.add_argument(
        "--insert-positions",
        type=_positive,
        default=3,
        help="how many insertion points to try per proof (default 3)",
    )
    parser.add_argument(
        "--max-nodes",
        type=_positive,
        default=400,
        help="skip a `state` restatement expanding past this many nodes",
    )
    parser.add_argument(
        "--state-lines",
        type=_positive,
        default=3,
        help="how many lines to restate per proof (default 3)",
    )
    parser.add_argument(
        "--probe-lines",
        type=_positive,
        default=3,
        help="how many lines to offer wrong citations for per proof (default 3)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="where to import (default: a SQLite file beside the .mm)",
    )
    parser.add_argument(
        "--keep", action="store_true", help="reuse an existing database rather than recreating it"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="drop and rebuild a --database-url that already holds systems",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the progress line")
    return parser.parse_args()


async def main() -> int:
    arguments = _arguments()
    try:
        rounds = _ordered_rounds(arguments.rounds)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Normalised once, here, so every `create_engine` below gets a driver that
    # exists — and so a URL naming an unusable one fails on the first line
    # rather than after an import has been paid for.
    try:
        url = _sync_url(
            arguments.database_url
            or f"sqlite:///{arguments.source.with_suffix('.restore.db')}"
        )
    except ArgumentError as exc:
        print(f"unusable --database-url: {exc}", file=sys.stderr)
        return 2

    if not arguments.keep:
        _provision(url, arguments.recreate)
        started = time.monotonic()
        print(f"Reading {arguments.source}…", flush=True)
        # `.mm` is UTF-8; reading it under the platform locale fails wherever
        # that is not.
        database = parse(arguments.source.read_text(encoding="utf-8"))
        print(
            f"  {len(database.assertions)} assertions in "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )
        started = time.monotonic()
        engine = create_engine(url)
        try:
            with Session(engine) as session:
                report = import_corpus(
                    session,
                    database,
                    limit=arguments.limit,
                    name="corpus",
                    batch=50,
                    overrides=DISPLAY_OVERRIDES,
                    rules=DISPLAY_RULES,
                    source=arguments.source.name,
                )
                session.commit()
        finally:
            engine.dispose()
        print(
            f"  imported {report.checked} theorems in "
            f"{time.monotonic() - started:.1f}s — {report.verified} verified, "
            f"{report.rejected} rejected, {report.failed} failed",
            flush=True,
        )
        _own(url, "harness@example.invalid")

    owner = _owner_of(url)
    found = _keys(url, arguments.label or None, arguments.proofs, arguments.longest)
    keys = [key for key in found if key.drivable]
    if not keys:
        print("no verified proofs to drive", file=sys.stderr)
        return 1
    rows, children = (
        _term_rows(url, keys) if "state" in rounds else ({}, {})
    )
    dropped = len(found) - len(keys)
    # Before anything is driven: a step whose citation and whose edges name
    # different lines means the store contradicts itself, which is worth more than
    # any round's verdict and is not something a round would report.
    discrepancies = [line for key in keys for line in key.discrepancies]
    if discrepancies:
        print("\nthe stored structure disagrees with the citation:", file=sys.stderr)
        for line in discrepancies:
            print(f"  ! {line}", file=sys.stderr)
        return 1
    print(
        f"\nDriving {len(keys)} proofs — "
        f"{sum(len(k.steps) for k in keys)} steps, "
        f"longest {max(len(k.steps) for k in keys)}, "
        f"widest citation {max(k.widest for k in keys)}"
        + (f" ({dropped} not numbered 1..N, skipped)" if dropped else ""),
        flush=True,
    )

    codes: dict[str, int] = {}
    tallies = await drive(url, owner, keys, rounds, arguments, rows, children, codes)

    print()
    failed = 0
    for name in rounds:
        tally = tallies[name]
        per = tally.seconds / tally.calls if tally.calls else 0.0
        print(
            f"  {name:<7} {tally.passed} passed, {tally.failed} failed, "
            f"{tally.skipped} skipped — {tally.calls} calls in "
            f"{tally.seconds:.1f}s ({per * 1000:.0f}ms each)"
        )
        failed += tally.failed
    skipped = [r for t in tallies.values() for r in t.results if r.skipped]
    if skipped:
        print(f"\n  skipped ({len(skipped)}):")
        for result in skipped[:10]:
            print(f"    {result.label} [{result.round}] {result.detail}")
    if codes:
        # What a wrong citation was told, by mutation. The point of §7 is that
        # this table has no "generic" row in it.
        print("\n  what a wrong citation was told:")
        for name, count in sorted(codes.items()):
            print(f"    {count:>5}  {name}")
    return 1 if failed else 0


def _owner_of(url: str) -> uuid.UUID:
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            owner = session.scalar(select(Proof.owner_id).where(Proof.owner_id.is_not(None)))
            if owner is None:
                raise SystemExit("no owned proofs — run without --keep to import first")
            return owner
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
