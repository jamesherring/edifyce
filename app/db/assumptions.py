"""A library entry nobody has proved, and what rests on it.

An informal source cites results it does not prove — "by Lemma 2.1 of [7]", "by
compactness" — and a translation that must prove every one of them before it can
state the next line cannot get started. An **assumption** is the way to take that
debt on explicitly: a citable entry with a statement, a reason, and no proof.

**Not a new kind of thing to the checker.** An assumption is stored as a promoted
theorem with ``primitive`` set and ``proved_by_id`` NULL, because that is exactly
what it is to a citation: an assertion this system offers without a warrant of
its own. A proof citing one is a perfectly good proof — *of a conditional* — and
nothing in the kernel, in unification, or in `promoted_theorems_mapping` needs to
learn a third case. What the rows here add is the editorial half the checker has
no opinion about: why it is believed, where it came from, and who took it on.

That split is deliberate and is the reason this is a side table rather than a
column. ``primitive`` answers "does this system assert this without proving it",
which is a question about checking; "is this a foundation or a debt" is a
question about the *development*, and only the second one is ever paid down.

What rests on what
------------------
The point of tracking a debt is knowing what would fall with it, and that is a
transitive question: a proof citing a theorem citing an assumption rests on the
assumption. :class:`TheoremAssumptionRow` is that closure, stored **per library
entry** and written when the entry is promoted.

Per entry rather than per proof, because an entry is where the answer is both
cheap and stable. Cheap: an entry's closure is the union of its citations'
closures, so each promotion does *one hop* of work, and reading it back is one
query however deep the **library** citation graph runs — which on a corpus is
thousands of theorems. Stable: an entry that stops standing is retired, and
retirement already cascades (`app/routers/_invalidation.py`), so nothing
maintains this that is not already maintained.

The one walk left is over **proofs**, not entries: a proof may cite a lemma
proof's lines directly (``[alias.line]``), which names no label, so
:func:`reference_closure` follows those edges before any label is read. That
graph is per-development and acyclic by construction, not corpus-scale.

An entry promoted before this table existed has no rows, which reads as an empty
closure — and that is the right answer rather than a missing one, since nothing
can rest on an assumption that did not exist when it was promoted.

An assumption carries a **self-edge**, so "the closure of the entries this proof
cites" needs no special case for citing one directly.

Ids and not labels, throughout. A relation edge may rename a label across systems
(`website/logical/translation.py`), so the label a citation spells is not a key;
the entry it resolves to is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models import Proof
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.promoted_theorems import PromotedTheoremPremiseRow, PromotedTheoremRow
from app.db.systems import RuleRow

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.orm import Session


class AssumptionRow(TimestampMixin, Base):
    """The editorial record of a library entry that is asserted, not proved."""

    __tablename__ = "assumptions"

    # The entry *is* the assumption, so its id is this row's key: one entry has
    # at most one debt record, and the record cannot outlive the entry.
    theorem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="CASCADE"), primary_key=True
    )
    # Why it is believed true, and why it is not proved here. Required, and
    # unbounded: this is the only thing standing between a tracked debt and an
    # axiom nobody remembers adopting.
    reason: Mapped[str] = mapped_column(Text)
    # Where the claim comes from — an arXiv id, a DOI, a textbook, a URL. Free
    # text on purpose: structuring a citation is the formalization record's job
    # (docs/informal-source-ingestion-roadmap.md §4.3), and guessing at that
    # shape now would be a migration later.
    source: Mapped[str | None] = mapped_column(Text)
    # Who took the debt on. SET NULL rather than CASCADE — losing the account
    # must not silently discharge the assumption.
    asserted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    theorem: Mapped[PromotedTheoremRow] = relationship()


class TheoremAssumptionRow(Base):
    """One library entry transitively rests on one assumption.

    Both columns name `promoted_theorems`: the entry that rests, and the assumed
    entry it rests on. An assumption's own row (both columns equal) is what lets
    a reader union closures without special-casing a direct citation.
    """

    __tablename__ = "theorem_assumptions"
    __table_args__ = (
        # "What rests on this assumption?" — the whole reason to store the
        # closure rather than walk it, and the ranking the public index uses.
        Index("ix_theorem_assumptions_assumption", "assumption_id"),
    )

    theorem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="CASCADE"), primary_key=True
    )
    assumption_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="CASCADE"), primary_key=True
    )


@dataclass(frozen=True)
class Assumed:
    """One assumption, as a reader of a dependency report needs it."""

    theorem_id: uuid.UUID
    system_id: uuid.UUID
    label: str
    statement: str
    reason: str
    source: str | None


@dataclass(frozen=True)
class RestsOn:
    """What a proof depends on that nobody has proved — and what went unread.

    ``unresolved`` and ``unread`` are the honest half, one per door into the
    library. A cited **label** that names no entry, no inference rule of the
    chain and no hypothesis of a theorem being proved is one the report could not
    account for; a cited **lemma proof** holding no line rows is one whose own
    debts could not be read. Either dropped silently would make this read "rests
    on nothing" when the truth is "rests on something I could not follow". Same
    reasoning as `app/db/retrieval.py`'s ``unindexed``: a short list must not read
    as a complete one.
    """

    assumptions: tuple[Assumed, ...]
    unresolved: tuple[str, ...]
    # Reached lemma proofs with no stored structure, by name.
    unread: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.unresolved and not self.unread


def record_closure(
    session: Session, theorem_id: uuid.UUID, assumption_ids: Iterable[uuid.UUID]
) -> None:
    """Replace the assumptions ``theorem_id`` transitively rests on.

    Replace rather than add: a re-promotion after an edit is a new claim about
    what the entry depends on, and accumulating would leave the debts of a proof
    that no longer exists attached to the entry that replaced it.
    """
    session.execute(
        delete(TheoremAssumptionRow).where(
            TheoremAssumptionRow.theorem_id == theorem_id
        )
    )
    for assumption_id in sorted(set(assumption_ids), key=str):
        session.add(
            TheoremAssumptionRow(
                theorem_id=theorem_id, assumption_id=assumption_id
            )
        )


def closure_of(
    session: Session, theorem_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Every assumption the given entries transitively rest on.

    One query, because each entry's own closure is already stored — this is the
    single hop that makes a proof's report cost the same at any citation depth.
    """
    if not theorem_ids:
        return set()
    return set(
        session.scalars(
            select(TheoremAssumptionRow.assumption_id).where(
                TheoremAssumptionRow.theorem_id.in_(list(theorem_ids))
            )
        )
    )


def dependent_counts(
    session: Session, assumption_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """How many library entries rest on each assumption.

    The blast radius, and the ranking that says which gap is worth closing first.
    Counts *entries*, not proofs: an entry is what another proof can cite, so it
    is what the debt has actually spread to. A proof that rests on an assumption
    and has been promoted is counted through its entry; one that has not been
    promoted is nobody's dependency yet.

    An assumption's self-edge is excluded, or every assumption would report one
    dependent before anything cited it.
    """
    if not assumption_ids:
        return {}
    rows = session.execute(
        select(
            TheoremAssumptionRow.assumption_id, func.count(TheoremAssumptionRow.theorem_id)
        )
        .where(
            TheoremAssumptionRow.assumption_id.in_(list(assumption_ids)),
            TheoremAssumptionRow.theorem_id != TheoremAssumptionRow.assumption_id,
        )
        .group_by(TheoremAssumptionRow.assumption_id)
    )
    counts = {assumption_id: count for assumption_id, count in rows}
    return {assumption_id: counts.get(assumption_id, 0) for assumption_id in assumption_ids}


def assumption_labels(
    session: Session, theorem_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """The assumptions each entry rests on, by label, for reading an entry back.

    Labels rather than the whole record, because a reader of a *library entry*
    wants to know it is conditional and on what; the record itself is the
    assumption's own route. One query for however many entries are asked about,
    so a listing pays once.
    """
    if not theorem_ids:
        return {}
    found: dict[uuid.UUID, list[str]] = {}
    for theorem_id, label in session.execute(
        select(TheoremAssumptionRow.theorem_id, PromotedTheoremRow.label)
        .join(
            PromotedTheoremRow,
            PromotedTheoremRow.id == TheoremAssumptionRow.assumption_id,
        )
        .where(TheoremAssumptionRow.theorem_id.in_(list(theorem_ids)))
        .order_by(PromotedTheoremRow.label)
    ):
        found.setdefault(theorem_id, []).append(label)
    return found


def dependent_entries(
    session: Session, assumption_id: uuid.UUID
) -> list[PromotedTheoremRow]:
    """The library entries that rest on one assumption, self excluded."""
    return list(
        session.scalars(
            select(PromotedTheoremRow)
            .join(
                TheoremAssumptionRow,
                TheoremAssumptionRow.theorem_id == PromotedTheoremRow.id,
            )
            .where(
                TheoremAssumptionRow.assumption_id == assumption_id,
                PromotedTheoremRow.id != assumption_id,
            )
            .order_by(PromotedTheoremRow.position, PromotedTheoremRow.id)
        )
    )


def resolve_labels(
    session: Session, systems: Sequence[uuid.UUID], labels: Sequence[str]
) -> dict[str, uuid.UUID]:
    """Which entry each label names, resolving **nearest first**.

    ``systems`` is the citing proof's library order — `LibraryChain.system_ids`,
    which is the chain followed by whatever relation edges reach further. That is
    the resolver's own order, so a label declared twice resolves here to the
    entry a citation would actually have reached rather than to whichever row a
    query happened to return.
    """
    if not systems or not labels:
        return {}
    rank = {system_id: index for index, system_id in enumerate(systems)}
    found: dict[str, tuple[int, uuid.UUID]] = {}
    for row in session.execute(
        select(
            PromotedTheoremRow.id,
            PromotedTheoremRow.label,
            PromotedTheoremRow.system_id,
        ).where(
            PromotedTheoremRow.system_id.in_(list(systems)),
            PromotedTheoremRow.label.in_(sorted(set(labels))),
        )
    ):
        held = found.get(row.label)
        near = rank[row.system_id]
        if held is None or near < held[0]:
            found[row.label] = (near, row.id)
    return {label: entry for label, (_, entry) in found.items()}


def explained_labels(
    session: Session, systems: Sequence[uuid.UUID], theorem_ids: Sequence[uuid.UUID]
) -> set[str]:
    """The labels a proof's own context accounts for without any library entry.

    An **inference rule** the chain declares, by either of its two spellings, and
    the **hypotheses** of the theorems these proofs establish — a Metamath ``$e``,
    citable only from inside the block that declares it. Neither is a dependency
    on anything unproved, so both drop out rather than being reported as labels
    the walk could not follow. Exactly `app/db/provenance.py`'s ``explained``,
    read for a proof and the lemmas it cites instead of for a corpus.
    """
    labels: set[str] = set()
    if systems:
        for label, name in session.execute(
            select(RuleRow.label, RuleRow.name).where(RuleRow.system_id.in_(list(systems)))
        ):
            labels.update({label, name})
    if theorem_ids:
        labels.update(
            session.scalars(
                select(PromotedTheoremPremiseRow.label).where(
                    PromotedTheoremPremiseRow.theorem_id.in_(list(theorem_ids)),
                    PromotedTheoremPremiseRow.label.is_not(None),
                )
            )
        )
    return labels


def reference_closure(
    session: Session, proof_id: uuid.UUID
) -> tuple[list[uuid.UUID], tuple[str, ...]]:
    """Every proof whose lines this one's citations reach, itself included.

    **The second door into the library, and the one with no label on it.** A
    proof reaches a theorem two ways: a rule label its lines resolve
    (`proof_lines.rule`), and a *lemma proof* whose lines it cites as
    ``[alias.line]``. The second leaves no label behind — the rule recorded is
    whatever justified the step, and the lemma's own citations are rows on the
    lemma — so a report reading only the first calls a proof unconditional when
    every debt it has came through a lemma.

    Followed by **antecedent edge** rather than by `proof_references`, which is
    the declared set: a reference no line cites is not a dependency, and
    `app/db/provenance.py` makes the same choice one level down for the same
    reason. A breadth-first walk rather than one hop, because a lemma may cite a
    lemma; the reference graph is acyclic by construction (the cycle check on
    write) and the walk carries its own ``seen`` set regardless.

    The second return is the **unread**: reached proofs holding no line rows, by
    name. That should be unreachable — invalidating a lemma clears its
    dependents' verdicts and structure together (`_invalidation.dependent_closure`),
    so a proof with stored lines implies its lemmas have them — but a closure
    that quietly skipped one would under-report a debt, which is the one failure
    this module exists to prevent. Reported rather than trusted.
    """
    reached = [proof_id]
    seen = {proof_id}
    frontier = [proof_id]
    while frontier:
        # Joined through the line: an edge is keyed by the *line* that cites, so
        # "which proofs does this one reach" is a question about its lines.
        rows = session.scalars(
            select(ProofLineAntecedentRow.antecedent_proof_id)
            .join(ProofLineRow, ProofLineRow.id == ProofLineAntecedentRow.line_id)
            .where(
                ProofLineRow.proof_id.in_(frontier),
                ProofLineAntecedentRow.antecedent_proof_id.is_not(None),
            )
            .distinct()
        )
        frontier = [found for found in rows if found not in seen]
        seen.update(frontier)
        reached.extend(frontier)

    # Which of them actually hold structure. The seed is the caller's business —
    # a route 409s on it — so only the lemmas can surprise us here.
    checked = set(
        session.scalars(
            select(ProofLineRow.proof_id).where(ProofLineRow.proof_id.in_(reached)).distinct()
        )
    )
    unread = tuple(
        sorted(
            name
            for name, in session.execute(
                select(Proof.name).where(Proof.id.in_([p for p in reached if p not in checked]))
            )
        )
    )
    return reached, unread


def cited_entries(
    session: Session, proofs: Sequence[uuid.UUID], systems: Sequence[uuid.UUID]
) -> tuple[dict[str, uuid.UUID], tuple[str, ...]]:
    """The library entries these proofs' checked lines cite, and what went unread.

    ``proof_lines.rule`` and not the reference the author typed: the resolved
    label is what the *checker* used, and reporting a label the resolver never
    reached would invent a dependency the proof does not have. The same choice
    `app/db/provenance.py` makes, and for the same reason.
    """
    labels = list(
        session.scalars(
            select(ProofLineRow.rule)
            .where(ProofLineRow.proof_id.in_(list(proofs)), ProofLineRow.rule.is_not(None))
            .distinct()
        )
    )
    theorem_ids = [
        theorem_id
        for theorem_id in session.scalars(
            select(Proof.theorem_id).where(
                Proof.id.in_(list(proofs)), Proof.theorem_id.is_not(None)
            )
        )
    ]
    entries = resolve_labels(session, systems, labels)
    explained = explained_labels(session, systems, theorem_ids)
    unresolved = tuple(
        sorted(label for label in labels if label not in entries and label not in explained)
    )
    return entries, unresolved


def rests_on(
    session: Session, proof_id: uuid.UUID, systems: Sequence[uuid.UUID]
) -> RestsOn:
    """What one proof transitively assumes, from rows alone.

    Nothing here parses, and nothing re-checks: the citations are the resolved
    labels the last verification recorded, and each cited entry's own closure was
    settled when *it* was promoted. A proof with no stored lines has never been
    checked, and reports nothing — which its caller should turn into "verify it
    first" rather than into "it assumes nothing".

    ``systems`` covers every proof reached, not only the seed: a proof may
    reference only proofs in its own system (which is what lets one lock cover a
    whole reference closure, `_common.lock_system`), so they share a chain.
    """
    proofs, unread = reference_closure(session, proof_id)
    entries, unresolved = cited_entries(session, proofs, systems)
    return RestsOn(
        assumptions=hydrate(session, closure_of(session, list(entries.values()))),
        unresolved=unresolved,
        unread=unread,
    )


def hydrate(
    session: Session, assumption_ids: Iterable[uuid.UUID]
) -> tuple[Assumed, ...]:
    """The assumptions those ids name, statement and reason included."""
    ids = list(assumption_ids)
    if not ids:
        return ()
    rows = session.execute(
        select(
            PromotedTheoremRow.id,
            PromotedTheoremRow.system_id,
            PromotedTheoremRow.label,
            PromotedTheoremRow.statement,
            AssumptionRow.reason,
            AssumptionRow.source,
        )
        .join(AssumptionRow, AssumptionRow.theorem_id == PromotedTheoremRow.id)
        .where(PromotedTheoremRow.id.in_(ids))
        .order_by(PromotedTheoremRow.label)
    )
    return tuple(
        Assumed(
            theorem_id=row.id,
            system_id=row.system_id,
            label=row.label,
            statement=row.statement,
            reason=row.reason,
            source=row.source,
        )
        for row in rows
    )
