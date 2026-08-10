"""Citable statements nobody has proved, and the index of what rests on them.

The first half of docs/informal-source-ingestion-roadmap.md §4.1/§4.2. A
translation from an informal source cites results it has not proved — "by Lemma
2.1 of [7]" — and until now the only two moves were both wrong: promote something
unproved (refused, correctly) or leave a hole, which blocks every step beneath it
so nothing downstream can be attempted at all.

An **assumption** is the third move: take the debt on, in the open. It is stored
as an ordinary library entry the checker asserts without a warrant
(`app/db/assumptions.py` explains why that is not a new kind of thing), plus the
editorial record the checker has no opinion about — why it is believed, where it
came from, who took it on.

**Public, and ranked.** A theorem everyone knows is true and Edifyce cannot yet
justify is not an embarrassment to bury; it is the most useful thing this
database can say about where its own gaps are. So published systems' assumptions
are world-readable and ordered by how much rests on them, and the ranking is the
roadmap: the assumption a hundred entries depend on is where proving effort buys
the most.

**Owned, not open.** Creating one is the system owner's, because an assumption
changes what the library says for every proof that inherits it. That an imported
corpus is ownerless is the right outcome rather than a gap: an assumption is a
claim about *your* development, and the place for it is a system of your own that
builds on the corpus.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.auth import current_active_user, current_active_user_optional
from app.db import (
    AssumptionRow,
    FormalSystem,
    PromotedTheoremRow,
    TheoremAssumptionRow,
    dependent_counts,
    dependent_entries,
    record_closure,
    store_theorem,
    theorem_digest,
)
from app.db.models import User
from app.db.session import get_session
from app.routers._common import PageParams, lock_system, page_params
from app.routers._invalidation import invalidate_citations
from app.routers.proofs import build_system, require_a_built_system
from app.routers.systems import (
    owned_system_id_or_404,
    readable_system_id_or_404,
)
from app.schemas import (
    AssumptionCreate,
    AssumptionDetail,
    AssumptionOut,
    Page,
)
from website.logical.promotion import TheoremSpec, promote_spec

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["assumptions"])


def _out(
    row: PromotedTheoremRow,
    assumption: AssumptionRow,
    system_name: str,
    dependents: int,
) -> AssumptionOut:
    return AssumptionOut(
        id=row.id,
        label=row.label,
        statement=row.statement,
        reason=assumption.reason,
        source=assumption.source,
        formal_system_id=row.system_id,
        formal_system_name=system_name,
        dependents=dependents,
        created_at=assumption.created_at,
    )


@router.post(
    "/formal-systems/{system_id}/assumptions",
    response_model=AssumptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_assumption(
    system_id: uuid.UUID,
    payload: AssumptionCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> AssumptionOut:
    """Register a statement as citable, on the record that nobody proved it.

    The statement is composed against the system's grammar exactly as an imported
    theorem's is, so a **ground** statement the grammar cannot read is refused
    here rather than stored. A *schematic* one is not, and that is the engine's
    settled position rather than an oversight: a schema that parses nothing
    yields a theorem that never applies, exactly as an authored rule's does
    (`website.logical.promotion.promote_from_source`). The author finds out at
    the first citation, and the alternative would be this route deciding
    something the engine deliberately leaves open.

    Adding one **changes what a label resolves to** for this system and everything
    below it, which is the same event as promoting a theorem — so it takes the
    system lock and clears the verdicts that were reached without it.
    """
    await owned_system_id_or_404(session, system_id, user.id)
    # Before the build, because the grammar an assumption is composed against must
    # be the grammar a citation of it will be checked against (`/cite`'s lesson).
    await lock_system(session, system_id)
    built = await build_system(session, system_id)
    require_a_built_system(built)
    system, effective, compiled = built.system, built.effective, built.compiled

    label = payload.label
    taken = await session.scalar(
        select(PromotedTheoremRow.id).where(
            PromotedTheoremRow.system_id == system_id,
            PromotedTheoremRow.label == label,
        )
    )
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label!r} already names a theorem in this system's library.",
        )
    # A citation resolves a rule before the library, so an entry under a rule's
    # label is one nothing could ever reach. The same guard promotion makes.
    if any(rule.label == label for rule in compiled.inference_rules):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label!r} is already an inference rule of this system, and a "
            "citation resolves a rule before a theorem, so the entry would be "
            "unreachable. Assume it under another label.",
        )

    spec = TheoremSpec(
        label=label,
        statement=payload.statement,
        metavariables=dict(payload.metavariables),
        premises=tuple(payload.premises),
        distinct=tuple(payload.distinct),
    )
    try:
        promoted = promote_spec(compiled, spec)
    except ValueError as exc:
        # The engine's own guards: a sort that is not a declared pattern, or a
        # ground statement that parses at none of the system's logical sorts.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    digest = theorem_digest(effective.library.digest(system_id), spec)
    symbols = {symbol.name: symbol for symbol in system.symbols}
    position = await session.scalar(
        select(func.count())
        .select_from(PromotedTheoremRow)
        .where(PromotedTheoremRow.system_id == system_id)
    )
    try:
        row = await session.run_sync(
            lambda sync: store_theorem(
                sync,
                system,
                spec,
                symbols,
                position=position or 0,
                # Asserted without a warrant of its own, which is what `primitive`
                # records and what a citation of this needs to know. That it is a
                # *debt* rather than a foundation is the assumption row's business.
                primitive=True,
                digest=digest,
                promoted=promoted,
                proved_by_id=None,
            )
        )
    except LookupError as exc:
        # A metavariable naming a sort the system declares no symbol for.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    await session.flush()
    assumption = AssumptionRow(
        theorem_id=row.id,
        reason=payload.reason,
        source=payload.source,
        asserted_by_id=user.id,
    )
    session.add(assumption)
    # Its own closure is itself. That self-edge is what lets a reader union the
    # closures of the entries a proof cites without a special case for citing an
    # assumption directly.
    await session.run_sync(lambda sync: record_closure(sync, row.id, [row.id]))

    await invalidate_citations(session, system_id, label)
    await session.commit()
    await session.refresh(assumption)
    return _out(row, assumption, system.name, dependents=0)


@router.get(
    "/formal-systems/{system_id}/assumptions", response_model=list[AssumptionOut]
)
async def list_assumptions(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> list[AssumptionOut]:
    """What this system asserts without proof, most depended-on first."""
    name = await _readable_system_name_or_404(session, system_id, user)
    rows = (
        await session.execute(
            select(PromotedTheoremRow, AssumptionRow)
            .join(AssumptionRow, AssumptionRow.theorem_id == PromotedTheoremRow.id)
            .where(PromotedTheoremRow.system_id == system_id)
        )
    ).all()
    counts = await session.run_sync(
        lambda sync: dependent_counts(sync, [row[0].id for row in rows])
    )
    found = [
        _out(theorem, assumption, name, counts.get(theorem.id, 0))
        for theorem, assumption in rows
    ]
    found.sort(key=lambda item: (-item.dependents, item.label))
    return found


# Declared before the `{label}` route so "public" is not read as a label.
@router.get("/assumptions/public", response_model=Page[AssumptionOut])
async def list_public_assumptions(
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[AssumptionOut]:
    """Every assumption in a published system, most depended-on first.

    The gap register. Each row is something believed true that this database
    cannot yet justify, and ``dependents`` says how much has been built on it —
    which is the order in which closing them pays.

    Ordered in the database rather than in Python, because the ranking has to
    hold across the whole set for a page of it to mean anything: sorting one page
    by dependents would rank twenty arbitrary rows.
    """
    # Self-edge excluded, or every assumption would start at one dependent.
    dependents = (
        select(
            TheoremAssumptionRow.assumption_id.label("assumption_id"),
            func.count(TheoremAssumptionRow.theorem_id).label("dependents"),
        )
        .where(TheoremAssumptionRow.theorem_id != TheoremAssumptionRow.assumption_id)
        .group_by(TheoremAssumptionRow.assumption_id)
        .subquery()
    )
    where = (FormalSystem.published_at.is_not(None),)
    stmt = (
        select(
            PromotedTheoremRow,
            AssumptionRow,
            FormalSystem.name,
            func.coalesce(dependents.c.dependents, 0).label("dependents"),
        )
        .join(AssumptionRow, AssumptionRow.theorem_id == PromotedTheoremRow.id)
        .join(FormalSystem, FormalSystem.id == PromotedTheoremRow.system_id)
        .outerjoin(dependents, dependents.c.assumption_id == PromotedTheoremRow.id)
        .where(*where)
        # `label` then `id` break the tie: dependents is zero for most of them, and
        # a page boundary that shuffles between requests loses rows silently. `id`
        # is what makes the order *total* — a label is unique within one system and
        # this spans every published one, so two systems assuming `ax-choice` with
        # the same dependent count would otherwise be free to swap places between
        # the two requests that straddle them, dropping one and repeating the other.
        .order_by(
            func.coalesce(dependents.c.dependents, 0).desc(),
            PromotedTheoremRow.label,
            PromotedTheoremRow.id,
        )
    )
    rows = (
        await session.execute(stmt.limit(params.limit).offset(params.offset))
    ).all()
    total = await session.scalar(
        select(func.count())
        .select_from(AssumptionRow)
        .join(PromotedTheoremRow, PromotedTheoremRow.id == AssumptionRow.theorem_id)
        .join(FormalSystem, FormalSystem.id == PromotedTheoremRow.system_id)
        .where(*where)
    )
    return Page(
        items=[
            _out(theorem, assumption, system_name, count)
            for theorem, assumption, system_name, count in rows
        ],
        total=total or 0,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/formal-systems/{system_id}/assumptions/{label}", response_model=AssumptionDetail
)
async def read_assumption(
    system_id: uuid.UUID,
    label: str,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> AssumptionDetail:
    """One assumption, with the library entries that rest on it named."""
    name = await _readable_system_name_or_404(session, system_id, user)
    theorem, assumption = await _get_assumption_or_404(session, system_id, label)
    resting = await session.run_sync(lambda sync: dependent_entries(sync, theorem.id))
    return AssumptionDetail(
        **_out(theorem, assumption, name, len(resting)).model_dump(),
        dependent_labels=[entry.label for entry in resting],
    )


@router.delete(
    "/formal-systems/{system_id}/assumptions/{label}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def withdraw_assumption(
    system_id: uuid.UUID,
    label: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Withdraw an assumption, so the label stops resolving.

    Only an assumption: a proved entry is retired through the proof that warrants
    it, and letting this route delete one would withdraw a theorem without
    touching the proof that established it.

    **Refused while anything rests on it**, and this is the one guard that is not
    shared with retiring an ordinary entry. Retiring a theorem invalidates the
    proofs that cite *its* label, which is exactly the set whose verdicts rested
    on it. An assumption's dependents are not that set: an entry promoted from a
    proof that cited this is citable under a **different** label, so the walk
    never reaches the proofs resting on it at one remove — while the row cascade
    empties that entry's closure, leaving it standing and reporting itself
    unconditional. Silently understating a debt is the single thing this feature
    exists to prevent, so the answer is to refuse and name them (found in
    review).

    Retire the dependents first, or *discharge* the assumption by promoting a
    proof under the same label (`POST /proofs/{id}/promote`), which pays the debt
    off rather than dropping it: the entries resting on it inherit what the
    warrant rests on instead of losing the record.

    With nothing resting on it, withdrawal clears every verdict reached through
    the label exactly as a retirement does. What it still does not do is retire
    the promotions of the proofs that cited it — those proofs are unchecked
    rather than disproved, and re-verifying is what settles whether they stand.
    That much *is* the shape retiring any other entry already has.
    """
    await owned_system_id_or_404(session, system_id, user.id)
    await lock_system(session, system_id)
    theorem, _ = await _get_assumption_or_404(session, system_id, label)

    resting = await session.run_sync(lambda sync: dependent_entries(sync, theorem.id))
    if resting:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label!r} cannot be withdrawn while "
            + ", ".join(repr(entry.label) for entry in resting)
            + " rest on it: withdrawing it would leave them citable and reporting "
            "no assumptions. Retire them first, or prove this and promote it "
            "under the same label.",
        )

    await session.delete(theorem)
    await session.flush()
    await invalidate_citations(session, system_id, label)
    await session.commit()


async def _readable_system_name_or_404(
    session: AsyncSession, system_id: uuid.UUID, user: User | None
) -> str:
    # The readability policy is `readable_system_id_or_404`'s, unduplicated; the
    # name is a second one-column read rather than the whole-grammar hydrate
    # `_get_readable_or_404` does, which these routes need no part of.
    await readable_system_id_or_404(session, system_id, user)
    return await session.scalar(
        select(FormalSystem.name).where(FormalSystem.id == system_id)
    )


async def _get_assumption_or_404(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> tuple[PromotedTheoremRow, AssumptionRow]:
    row = (
        await session.execute(
            select(PromotedTheoremRow, AssumptionRow)
            .join(AssumptionRow, AssumptionRow.theorem_id == PromotedTheoremRow.id)
            .where(
                PromotedTheoremRow.system_id == system_id,
                PromotedTheoremRow.label == label,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"This system asserts no assumption labelled {label!r}.",
        )
    return row[0], row[1]
