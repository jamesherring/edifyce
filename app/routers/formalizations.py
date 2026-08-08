"""What a formal statement claims to be a formalization *of*.

§4.3 of docs/informal-source-ingestion-roadmap.md, and the third of the claims an
informal source adds that nothing here can check. The kernel certifies that a
proof establishes a term in a system; whether that term is Theorem 3.2 of the
paper someone was reading is not a question it can be asked.

So this does not check it — it records it, attributes it, and makes its absence
visible. `app/db/formalizations.py` carries the reasoning for the shape,
including why this is a leaf annotation rather than the closure `assumptions`
needed: a proof citing a term inherits the term, not anyone's claim about what
the term corresponds to.

**Nothing here reaches the engine.** A formalization is prose and foreign keys.
The one thing it borrows from the formal side is a `terms.id`, which is what
§4.4's statements route exists to hand out — and the reason that came first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import (
    FormalizationRow,
    GlossaryEntryRow,
    Proof,
    SourceDocumentRow,
)
from app.db.models import User
from app.db.session import get_session
from app.db.terms import TermRow
from app.routers.systems import readable_system_id_or_404
from app.schemas import (
    Formalization,
    FormalizationCreate,
    FormalizationReview,
    GlossaryEntry,
    GlossaryEntryInput,
    SourceDocument,
    SourceDocumentCreate,
    SystemOwner,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["formalizations"])


def _owner_out(account: SystemOwner | None) -> SystemOwner | None:
    # Already the public face — id and display name, never the address or the
    # password hash. See `_accounts` for why it is read as columns.
    return account


def _document_out(row: SourceDocumentRow, formalizations: int = 0) -> SourceDocument:
    return SourceDocument(
        id=row.id,
        kind=row.kind,
        identifier=row.identifier,
        version=row.version,
        title=row.title,
        url=row.url,
        content_hash=row.content_hash,
        licence=row.licence,
        retrieved_at=row.retrieved_at,
        created_at=row.created_at,
        formalizations=formalizations,
    )


# ---------------------------------------------------------------------------
# Source documents
# ---------------------------------------------------------------------------


@router.post(
    "/sources", response_model=SourceDocument, status_code=status.HTTP_201_CREATED
)
async def register_source(
    payload: SourceDocumentCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SourceDocument:
    """Register an external work, or return the one already registered.

    **Idempotent on identity**, which is (kind, identifier, version). Two people
    formalizing the same paper share the row rather than racing to own it, and a
    caller that retries gets the same id — the property every write on this
    surface will eventually need and this one gets for free from the index.

    A **version is part of the identity**, not a note about the document. A
    paper's v2 may restate the theorem, so it is a different row, and a claim
    made against v1 keeps pointing at the v1 its author read. That is what makes
    "pinned to a version" structural rather than a rule someone has to remember.
    """
    held = await _document_like(session, payload)
    if held is not None:
        # Returned rather than merged: the first registration's metadata stands,
        # since a second caller's title or licence is no more authoritative and
        # silently overwriting one with the other would make the row's contents
        # depend on who asked last.
        return _document_out(held, await _claim_count(session, held.id))

    row = SourceDocumentRow(
        kind=payload.kind,
        identifier=payload.identifier,
        version=payload.version,
        title=payload.title,
        url=payload.url,
        content_hash=payload.content_hash,
        licence=payload.licence,
        retrieved_at=payload.retrieved_at,
        registered_by_id=user.id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        # Two callers read "no such row" and both inserted. The unique index is
        # what actually decides, and the loser's answer is the winner's row —
        # which is the whole idempotency guarantee, and would otherwise fail
        # precisely for the concurrent agents it exists for (found in review).
        await session.rollback()
        winner = await _document_like(session, payload)
        if winner is None:
            raise
        return _document_out(winner, await _claim_count(session, winner.id))
    await session.refresh(row)
    return _document_out(row)


async def _document_like(
    session: AsyncSession, payload: SourceDocumentCreate
) -> SourceDocumentRow | None:
    return await session.scalar(
        select(SourceDocumentRow).where(
            SourceDocumentRow.kind == payload.kind,
            SourceDocumentRow.identifier == payload.identifier,
            SourceDocumentRow.version == payload.version,
        )
    )


@router.get("/sources", response_model=list[SourceDocument])
async def list_sources(
    kind: str | None = None,
    identifier: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SourceDocument]:
    """Every registered work, newest first. Public: a claim about a paper is only
    reviewable by someone who can see which paper it was."""
    conditions = []
    if kind is not None:
        conditions.append(SourceDocumentRow.kind == kind)
    if identifier is not None:
        conditions.append(SourceDocumentRow.identifier == identifier)
    rows = (
        await session.scalars(
            select(SourceDocumentRow)
            .where(*conditions)
            .order_by(SourceDocumentRow.created_at.desc(), SourceDocumentRow.id)
        )
    ).all()
    counts = await _claim_counts(session, [row.id for row in rows])
    return [_document_out(row, counts.get(row.id, 0)) for row in rows]


async def _claim_count(session: AsyncSession, document_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(FormalizationRow)
            .where(FormalizationRow.document_id == document_id)
        )
    ) or 0


async def _claim_counts(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(FormalizationRow.document_id, func.count(FormalizationRow.id))
        .where(FormalizationRow.document_id.in_(document_ids))
        .group_by(FormalizationRow.document_id)
    )
    return {document_id: count for document_id, count in rows}


# ---------------------------------------------------------------------------
# Formalizations
# ---------------------------------------------------------------------------


@router.post(
    "/formalizations",
    response_model=Formalization,
    status_code=status.HTTP_201_CREATED,
)
async def claim_formalization(
    payload: FormalizationCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Formalization:
    """Claim that a term is a formalization of a result in a document.

    Three things are checked, and none of them is the claim itself — that is the
    unverifiable part, and pretending otherwise is what this whole layer exists
    to avoid. What *is* checked is that the claim is about things that exist and
    that hang together: the document is registered, the term belongs to the
    system named, and a proof cited is a proof of that system.

    The informal statement is stored **verbatim on this row** rather than read
    from the document later, so that nothing — an edit, a revision — can rewrite
    what the attestation was about.

    Not deduplicated. Two people may formalize one theorem differently, in
    different systems or on different readings, and that disagreement is exactly
    what a reader of the document should see rather than a race to be the row.
    """
    document = await session.get(SourceDocumentRow, payload.document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source document not found.")

    await readable_system_id_or_404(session, payload.formal_system_id, user)
    term = await session.get(TermRow, payload.statement_term_id)
    if term is None or term.formal_system_id != payload.formal_system_id:
        # Also the not-found case, deliberately: interning is per system, so a
        # term of another system names a statement this one cannot mean, and
        # which system it came from is not this caller's business.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That system has no term with that id. Compose the statement with "
            "`POST /formal-systems/{id}/statements` and store it first.",
        )

    if payload.proof_id is not None:
        proof = await session.get(Proof, payload.proof_id)
        if proof is None or proof.formal_system_id != payload.formal_system_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That proof is not a proof of the system this claim is about.",
            )

    await _require_terms_of(session, payload.formal_system_id, payload.glossary)

    row = FormalizationRow(
        document_id=document.id,
        claim=payload.claim,
        informal_statement=payload.informal_statement,
        formal_system_id=payload.formal_system_id,
        statement_term_id=payload.statement_term_id,
        proof_id=payload.proof_id,
        attested_by_id=user.id,
        attested_as=payload.attested_as,
        reasoning=payload.reasoning,
    )
    _set_glossary(row, payload.glossary)
    session.add(row)
    await session.commit()
    return await _detail(session, row.id)


@router.get("/formalizations", response_model=list[Formalization])
async def list_formalizations(
    document_id: uuid.UUID | None = None,
    formal_system_id: uuid.UUID | None = None,
    proof_id: uuid.UUID | None = None,
    unreviewed: bool = Query(
        False, description="Only claims nobody has passed a verdict on."
    ),
    session: AsyncSession = Depends(get_session),
) -> list[Formalization]:
    """Claims, filtered the four ways anyone reads them.

    ``unreviewed`` is the one that matters most: an unreviewed claim is the
    ordinary state, and being able to list them is what makes "its absence is
    visible" more than a phrase.
    """
    conditions = []
    if document_id is not None:
        conditions.append(FormalizationRow.document_id == document_id)
    if formal_system_id is not None:
        conditions.append(FormalizationRow.formal_system_id == formal_system_id)
    if proof_id is not None:
        conditions.append(FormalizationRow.proof_id == proof_id)
    if unreviewed:
        conditions.append(FormalizationRow.review_verdict.is_(None))

    rows = (
        await session.scalars(
            _loaded(select(FormalizationRow))
            .where(*conditions)
            .order_by(FormalizationRow.created_at.desc(), FormalizationRow.id)
        )
    ).all()
    # The accounts named across the whole page in one query, so a listing is a
    # fixed number of round trips rather than two per claim.
    return await _page(session, list(rows))


@router.get("/formalizations/{formalization_id}", response_model=Formalization)
async def read_formalization(
    formalization_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Formalization:
    return await _detail(session, formalization_id)


@router.post(
    "/formalizations/{formalization_id}/review", response_model=Formalization
)
async def review_formalization(
    formalization_id: uuid.UUID,
    payload: FormalizationReview,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Formalization:
    """Pass a verdict on somebody else's claim.

    **Not your own.** The entire value of the word "reviewed" is independence,
    and a self-review that reads as reviewed is the same silent overstatement
    this layer exists to refuse — so the attestor is turned away rather than
    quietly recorded as their own reviewer.

    One verdict at a time, replaceable: a later reviewer's finding stands, since
    a stale confirmation surviving a subsequent dispute is the wrong way round.
    """
    row = await session.scalar(
        _loaded(select(FormalizationRow)).where(FormalizationRow.id == formalization_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formalization not found.")
    if row.attested_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You attested this claim, so you cannot also review it. A review "
            "means somebody else read the paper and agreed.",
        )

    row.review_verdict = payload.verdict
    row.review_note = payload.note
    row.reviewed_by_id = user.id
    row.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    return await _detail(session, row.id)


@router.put(
    "/formalizations/{formalization_id}/glossary",
    response_model=Formalization,
)
async def set_glossary(
    formalization_id: uuid.UUID,
    entries: list[GlossaryEntryInput],
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Formalization:
    """Replace this claim's glossary wholesale, as the nested value lists on a
    system's parts are replaced.

    Editing the alignment **clears any review**: a reviewer agreed with a reading
    of the paper's words, and changing those words means nobody has agreed with
    the reading that now stands.
    """
    row = await _owned_or_404(session, formalization_id, user)
    await _require_terms_of(session, row.formal_system_id, entries)
    row.glossary.clear()
    await session.flush()
    _set_glossary(row, entries)
    _withdraw_review(row)
    await session.commit()
    return await _detail(session, row.id)


@router.delete(
    "/formalizations/{formalization_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def withdraw_formalization(
    formalization_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Withdraw a claim. Nothing formal depends on it — a proof establishes its
    term whether or not anyone still says the term is Theorem 3.2 — so this is a
    plain delete rather than the gated withdrawal an assumption needs."""
    row = await _owned_or_404(session, formalization_id, user)
    await session.delete(row)
    await session.commit()


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------


def _loaded(stmt):  # noqa: ANN001, ANN202 - a Select of FormalizationRow
    # The three relationships every read of a claim renders, eager-loaded so a
    # listing is a fixed number of queries rather than one per row.
    return stmt.options(
        selectinload(FormalizationRow.document),
        selectinload(FormalizationRow.glossary),
    )


async def _require_terms_of(
    session: AsyncSession,
    system_id: uuid.UUID,
    entries: list[GlossaryEntryInput],
) -> None:
    """Every term a glossary points at must belong to the claimed system.

    The same check `statement_term_id` gets, and it was missing here: a term of
    another system would have committed happily and left the glossary pointing
    outside the system the claim is about, while a nonexistent one would have
    reached the foreign key and answered 500 where this answers 422 (found in
    review).
    """
    wanted = [entry.term_id for entry in entries if entry.term_id is not None]
    if not wanted:
        return
    owners = dict(
        (
            await session.execute(
                select(TermRow.id, TermRow.formal_system_id).where(
                    TermRow.id.in_(wanted)
                )
            )
        ).all()
    )
    stray = [term_id for term_id in wanted if owners.get(term_id) != system_id]
    if stray:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"That system has no term with id {stray[0]}, so the glossary would "
            "point outside the system this claim is about.",
        )


def _set_glossary(
    row: FormalizationRow, entries: list[GlossaryEntryInput]
) -> None:
    for position, entry in enumerate(entries):
        row.glossary.append(
            GlossaryEntryRow(
                position=position,
                notion=entry.notion,
                label=entry.label,
                term_id=entry.term_id,
                reasoning=entry.reasoning,
            )
        )


def _withdraw_review(row: FormalizationRow) -> None:
    row.review_verdict = None
    row.review_note = None
    row.reviewed_by_id = None
    row.reviewed_at = None


async def _owned_or_404(
    session: AsyncSession, formalization_id: uuid.UUID, user: User
) -> FormalizationRow:
    row = await session.scalar(
        _loaded(select(FormalizationRow)).where(FormalizationRow.id == formalization_id)
    )
    if row is None or row.attested_by_id != user.id:
        # 404 rather than 403 for somebody else's, so ids do not leak — the same
        # answer every other owner-scoped route gives.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formalization not found.")
    return row


async def _detail(session: AsyncSession, formalization_id: uuid.UUID) -> Formalization:
    row = await session.scalar(
        _loaded(select(FormalizationRow)).where(FormalizationRow.id == formalization_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formalization not found.")
    return (await _page(session, [row]))[0]


async def _page(
    session: AsyncSession, rows: list[FormalizationRow]
) -> list[Formalization]:
    """Serialize claims, with the account lookup done once for the lot."""
    if not rows:
        return []
    accounts = await _accounts(
        session,
        {row.attested_by_id for row in rows} | {row.reviewed_by_id for row in rows},
    )
    return [_out(row, accounts) for row in rows]


async def _accounts(
    session: AsyncSession, ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, SystemOwner]:
    """The public face of each account named, in one query.

    Two columns rather than whole rows, for the reason `scripts/import_metamath`
    records: `User` eagerly joins its OAuth accounts, so selecting the entity
    drags in tokens and a password hash to render a display name — and a
    collection-bearing entity needs `.unique()` besides.
    """
    wanted = [account for account in ids if account is not None]
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name).where(User.id.in_(wanted))
    )
    return {
        account_id: SystemOwner(id=account_id, display_name=display_name)
        for account_id, display_name in rows
    }


def _out(
    row: FormalizationRow, accounts: dict[uuid.UUID, SystemOwner]
) -> Formalization:
    attested_by = accounts.get(row.attested_by_id)
    reviewed_by = accounts.get(row.reviewed_by_id)
    return Formalization(
        id=row.id,
        document=_document_out(row.document),
        claim=row.claim,
        informal_statement=row.informal_statement,
        formal_system_id=row.formal_system_id,
        statement_term_id=row.statement_term_id,
        proof_id=row.proof_id,
        reasoning=row.reasoning,
        attested_by=_owner_out(attested_by),
        attested_as=row.attested_as,
        attested_at=row.created_at,
        review_verdict=row.review_verdict,
        review_note=row.review_note,
        reviewed_by=_owner_out(reviewed_by),
        reviewed_at=row.reviewed_at,
        glossary=[
            GlossaryEntry(
                id=entry.id,
                notion=entry.notion,
                label=entry.label,
                term_id=entry.term_id,
                reasoning=entry.reasoning,
            )
            for entry in row.glossary
        ],
    )
