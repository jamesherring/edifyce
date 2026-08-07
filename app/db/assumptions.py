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
closures, so each promotion does *one hop* of work and reading a proof's closure
is one hop as well — no walk, at any depth, in either direction. Stable: an entry
that stops standing is retired, and retirement already cascades
(`app/routers/_invalidation.py`), so nothing maintains this that is not already
maintained.

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
from app.db.proof_lines import ProofLineRow
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

    ``unresolved`` is the honest half. A cited label that names no library entry,
    no inference rule of the chain, and no hypothesis of the theorem being proved
    is a label this report could not account for, and a report that dropped it
    would read as "rests on nothing" when the truth is "rests on something I
    could not follow". Same reasoning as `app/db/retrieval.py`'s ``unindexed``:
    a short list must not read as a complete one.
    """

    assumptions: tuple[Assumed, ...]
    unresolved: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unresolved


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
    session: Session, systems: Sequence[uuid.UUID], theorem_id: uuid.UUID | None
) -> set[str]:
    """The labels a proof's own context accounts for without any library entry.

    An **inference rule** the chain declares, by either of its two spellings, and
    the **hypotheses** of the theorem this proof establishes — a Metamath ``$e``,
    citable only from inside the block that declares it. Neither is a dependency
    on anything unproved, so both drop out rather than being reported as labels
    the walk could not follow. Exactly `app/db/provenance.py`'s ``explained``,
    read for one proof instead of for a corpus.
    """
    labels: set[str] = set()
    if systems:
        for label, name in session.execute(
            select(RuleRow.label, RuleRow.name).where(RuleRow.system_id.in_(list(systems)))
        ):
            labels.update({label, name})
    if theorem_id is not None:
        labels.update(
            session.scalars(
                select(PromotedTheoremPremiseRow.label).where(
                    PromotedTheoremPremiseRow.theorem_id == theorem_id,
                    PromotedTheoremPremiseRow.label.is_not(None),
                )
            )
        )
    return labels


def cited_entries(
    session: Session,
    proof_id: uuid.UUID,
    systems: Sequence[uuid.UUID],
    theorem_id: uuid.UUID | None,
) -> tuple[dict[str, uuid.UUID], tuple[str, ...]]:
    """The library entries one proof's checked lines cite, and what went unread.

    ``proof_lines.rule`` and not the reference the author typed: the resolved
    label is what the *checker* used, and reporting a label the resolver never
    reached would invent a dependency the proof does not have. The same choice
    `app/db/provenance.py` makes, and for the same reason.
    """
    labels = [
        label
        for label in session.scalars(
            select(ProofLineRow.rule)
            .where(ProofLineRow.proof_id == proof_id, ProofLineRow.rule.is_not(None))
            .distinct()
        )
    ]
    entries = resolve_labels(session, systems, labels)
    explained = explained_labels(session, systems, theorem_id)
    unresolved = tuple(
        sorted(label for label in labels if label not in entries and label not in explained)
    )
    return entries, unresolved


def rests_on(
    session: Session,
    proof_id: uuid.UUID,
    systems: Sequence[uuid.UUID],
    theorem_id: uuid.UUID | None,
) -> RestsOn:
    """What one proof transitively assumes, from rows alone.

    Nothing here parses, and nothing re-checks: the citations are the resolved
    labels the last verification recorded, and each cited entry's own closure was
    settled when *it* was promoted. A proof with no stored lines has never been
    checked, and reports nothing — which its caller should turn into "verify it
    first" rather than into "it assumes nothing".
    """
    entries, unresolved = cited_entries(session, proof_id, systems, theorem_id)
    return RestsOn(
        assumptions=hydrate(session, closure_of(session, list(entries.values()))),
        unresolved=unresolved,
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
