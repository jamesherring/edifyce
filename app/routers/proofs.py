"""CRUD for proofs, owner-scoped.

Mirrors the formal-system CRUD (`app/routers/systems.py`): a proof is an
owner-scoped object stored as a single row (`app.db.models.Proof`) whose `source`
is `.edi` proof text written against a formal system. This router is the thin
HTTP layer over that row — reads serialize it, `verify` rebuilds the parent
system from its stored rows and hands the proof to the engine (no proof-checking
logic lives here).

Like systems, writes persist freely (a draft proof need not verify) and
`POST /{id}/verify` reports validity on demand, caching the result. Publishing
makes a proof world-readable, so it is gated: the proof must verify **and** its
formal system must itself be published (a published proof exposes its
`formal_system_id`, and `GET` of a draft system 404s for anonymous viewers).

A proof may only be created against a system the caller **owns** (mirroring the
owned-only `inherits_from_id` reference), which keeps a proof and its system in
one ownership domain — so an owner-scoped system delete never cascades into
another user's proof.

Editing a proof's folder placement and its proof-to-proof references is a later
phase — the read models expose `folder_id` so that layer can address it, exactly
as the system read models expose each part's `id`.

Two cross-object invariants against the *parent system* are deferred (they are
same-owner, self-inflicted now that proofs are owned-only, so no user can affect
another's proof): a published proof's cached `valid` can go stale if its owner
edits the system's grammar/rules afterwards (the system-part routes keep the
system compiling via `revalidate_if_published` but don't re-check dependent
proofs), and unpublishing a system does not unpublish proofs that were published
against it. Wiring the system routes to revalidate/unpublish dependent proofs is
a follow-up.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user, current_active_user_optional
from app.db import FormalSystem, Proof, get_session, system_to_spec
from app.db.models import User
from app.routers._common import unique_slug
from app.routers.systems import load_system
from app.schemas import (
    ProofCreate,
    ProofDetail,
    ProofSummary,
    ProofUpdate,
    SystemOwner,
    VerifyProofResponse,
)
from website.logical.declarative import build_spec

router = APIRouter(prefix="/proofs", tags=["proofs"])


async def _unique_slug(
    session: AsyncSession,
    owner_id: uuid.UUID,
    system_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    # Slugs disambiguate a user's proofs within one system; numeric suffix on
    # collision. (Not DB-unique — proofs carry no slug constraint — but kept
    # addressable so a client can route to a proof by slug.)
    async def _taken(slug: str) -> bool:
        stmt = select(Proof.id).where(
            Proof.owner_id == owner_id,
            Proof.formal_system_id == system_id,
            Proof.slug == slug,
        )
        if exclude_id is not None:
            stmt = stmt.where(Proof.id != exclude_id)
        return await session.scalar(stmt) is not None

    return await unique_slug(name, _taken, fallback="proof")


async def _load_owned(
    session: AsyncSession, proof_id: uuid.UUID, owner_id: uuid.UUID
) -> Proof | None:
    stmt = (
        select(Proof)
        .where(Proof.id == proof_id, Proof.owner_id == owner_id)
        .options(selectinload(Proof.owner))
    )
    return await session.scalar(stmt)


async def _get_owned_or_404(
    session: AsyncSession, proof_id: uuid.UUID, owner_id: uuid.UUID
) -> Proof:
    proof = await _load_owned(session, proof_id, owner_id)
    if proof is None:
        # 404 (not 403) for another owner's id, so ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    return proof


def _is_readable(proof: Proof, user: User | None) -> bool:
    # Published proofs are public; drafts are visible only to their owner.
    if proof.published_at is not None:
        return True
    return user is not None and proof.owner_id == user.id


async def _get_readable_or_404(
    session: AsyncSession, proof_id: uuid.UUID, user: User | None
) -> Proof:
    stmt = select(Proof).where(Proof.id == proof_id).options(selectinload(Proof.owner))
    proof = await session.scalar(stmt)
    if proof is None or not _is_readable(proof, user):
        # 404 (not 403) for a draft you don't own, so unpublished ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    return proof


async def _require_owned_system(
    session: AsyncSession, system_id: uuid.UUID, user: User
) -> None:
    """The system a proof is written against must be owned by the caller.

    Owned-only (not merely readable), mirroring how `inherits_from_id` requires
    an owned reference on the system side. This keeps a proof's system in the
    same ownership domain as the proof: a system delete is owner-scoped and
    cascades to proofs via `proofs.formal_system_id`, so allowing a proof against
    someone else's system would let that owner's delete destroy another user's
    proof. 400 (not 404) because it's a bad reference in the request body.
    """
    owned = await session.scalar(
        select(FormalSystem.id).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == user.id
        )
    )
    if owned is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"formal_system_id {system_id} is not one of your systems.",
        )


def _verify(system: FormalSystem, source: str) -> tuple[VerifyProofResponse, bool | None]:
    """Build the parent system and check `source` against it.

    Returns the response payload plus the proof's validity (None when the proof
    couldn't be checked at all — a system that doesn't build, or source the
    engine can't parse). No proof-checking lives here: it defers to the same
    `build_spec` + `FormalSystem.parse` path as the stateless `/proofs/verify`.
    """
    result = build_spec(system_to_spec(system))
    if "errors" in result:
        return VerifyProofResponse(success=False, errors=result["errors"]), None

    compiled = result["system"]
    # The proof checker raises on malformed proofs against otherwise valid
    # systems; return a structured error instead of a 500 (mirrors main.py).
    try:
        proof = compiled.parse(source)
    except Exception as exc:  # noqa: BLE001 — reshaped into a client error
        return VerifyProofResponse(success=False, errors=[str(exc)]), None

    return VerifyProofResponse(success=proof.valid, proof=proof.data()), proof.valid


async def _require_publishable(session: AsyncSession, proof: Proof) -> None:
    """Reject a publish that would expose an unverified or dangling public proof.

    Two things a published proof must not do, since it becomes world-readable: it
    must verify against its system, and that system must itself be public — a
    published proof exposes `formal_system_id`, and `GET /formal-systems/{id}`
    404s for anonymous viewers when the system is a private draft.

    On success the fresh verdict is cached on the row, so a published proof always
    renders as checked. Also used to keep a *published* proof valid across source
    edits (mirror of `systems.revalidate_if_published`): re-running it after an
    edit rejects a change that would leave a world-readable proof unverifying.
    """
    system = await load_system(session, proof.formal_system_id)
    if system is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The proof's system no longer exists.")

    response, valid = _verify(system, proof.source)
    if not response.success:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.errors or ["Proof does not verify against its system."],
        )

    if system.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot publish a proof whose system is an unpublished draft; "
            "publish the system first.",
        )

    # All gates passed. The proof was just verified as part of gating, so cache
    # that verdict — otherwise a published proof that was never hit by /verify
    # would render as "unchecked" despite publishing having proved it valid.
    proof.valid = valid
    proof.result = response.proof


def _owner_out(proof: Proof) -> SystemOwner | None:
    if proof.owner is None:
        return None
    return SystemOwner(id=proof.owner.id, display_name=proof.owner.display_name)


def _summary(proof: Proof) -> ProofSummary:
    return ProofSummary(
        id=proof.id,
        name=proof.name,
        slug=proof.slug,
        description=proof.description,
        formal_system_id=proof.formal_system_id,
        folder_id=proof.folder_id,
        valid=proof.valid,
        published_at=proof.published_at,
        created_at=proof.created_at,
        updated_at=proof.updated_at,
        owner=_owner_out(proof),
    )


def _detail(proof: Proof) -> ProofDetail:
    return ProofDetail(
        **_summary(proof).model_dump(),
        source=proof.source,
        result=proof.result,
    )


@router.get("", response_model=list[ProofSummary])
async def list_proofs(
    formal_system_id: uuid.UUID | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProofSummary]:
    stmt = (
        select(Proof)
        .where(Proof.owner_id == user.id)
        .options(selectinload(Proof.owner))
        .order_by(Proof.created_at)
    )
    # Optional scope to one system, so an editor can list just that system's proofs.
    if formal_system_id is not None:
        stmt = stmt.where(Proof.formal_system_id == formal_system_id)
    proofs = await session.scalars(stmt)
    return [_summary(proof) for proof in proofs]


# Declared before `/{proof_id}` so "public" isn't parsed as a proof id.
@router.get("/public", response_model=list[ProofSummary])
async def list_public_proofs(
    session: AsyncSession = Depends(get_session),
) -> list[ProofSummary]:
    """The shared master list: every published proof, any owner, no auth.

    Drafts (``published_at IS NULL``) are excluded; unpublishing removes a proof
    from this list. Newest publications first.
    """
    proofs = await session.scalars(
        select(Proof)
        .where(Proof.published_at.is_not(None))
        .options(selectinload(Proof.owner))
        .order_by(Proof.published_at.desc(), Proof.created_at.desc())
    )
    return [_summary(proof) for proof in proofs]


@router.post("", response_model=ProofDetail, status_code=status.HTTP_201_CREATED)
async def create_proof(
    payload: ProofCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    await _require_owned_system(session, payload.formal_system_id, user)

    proof = Proof(
        owner_id=user.id,
        formal_system_id=payload.formal_system_id,
        name=payload.name,
        slug=await _unique_slug(session, user.id, payload.formal_system_id, payload.name),
        description=payload.description,
        source=payload.source,
    )
    session.add(proof)
    await session.commit()

    # Reload so server-default timestamps and the owner are eagerly present.
    return _detail(await _get_owned_or_404(session, proof.id, user.id))


@router.get("/{proof_id}", response_model=ProofDetail)
async def get_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    # Published proofs are readable by anyone; drafts only by their owner.
    return _detail(await _get_readable_or_404(session, proof_id, user))


@router.patch("/{proof_id}", response_model=ProofDetail)
async def update_proof(
    proof_id: uuid.UUID,
    payload: ProofUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    proof = await _get_owned_or_404(session, proof_id, user.id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("name") is not None:
        proof.name = changes["name"]
        proof.slug = await _unique_slug(
            session, user.id, proof.formal_system_id, changes["name"], exclude_id=proof.id
        )
    if "description" in changes:
        proof.description = changes["description"]
    source_changed = "source" in changes and changes["source"] is not None
    if source_changed:
        proof.source = changes["source"]
        # The stored source changed, so the cached verdict is stale.
        proof.valid = None
        proof.result = None

    # Publishing is the write that makes a proof world-readable, so gate it —
    # after the field changes above so the checks see this request's final state.
    # A source edit on an already-published proof is re-gated too, so a
    # world-readable proof can't be edited into a non-verifying state (mirror of
    # systems.revalidate_if_published). Both paths re-cache the verdict.
    if "published" in changes:
        if changes["published"]:
            await _require_publishable(session, proof)
        proof.published_at = datetime.now(timezone.utc) if changes["published"] else None
    elif source_changed and proof.published_at is not None:
        await _require_publishable(session, proof)

    await session.commit()
    return _detail(await _get_owned_or_404(session, proof_id, user.id))


@router.delete("/{proof_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proof(
    proof_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # One owner-scoped Core DELETE; references and theorems follow their FK
    # ON DELETE rules, so nothing is loaded here.
    result = await session.execute(
        sa_delete(Proof).where(Proof.id == proof_id, Proof.owner_id == user.id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    await session.commit()


@router.post("/{proof_id}/verify", response_model=VerifyProofResponse)
async def verify_stored_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> VerifyProofResponse:
    proof = await _get_readable_or_404(session, proof_id, user)

    system = await load_system(session, proof.formal_system_id)
    if system is None:
        return VerifyProofResponse(success=False, errors=["The proof's system no longer exists."])

    response, valid = _verify(system, proof.source)

    # Cache the verdict on the row so a client can render it without re-checking.
    # Only the owner may write it back (an anonymous viewer of a published proof
    # gets the result but leaves the stored snapshot untouched).
    if user is not None and proof.owner_id == user.id:
        proof.valid = valid
        proof.result = response.proof
        await session.commit()

    return response
