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

A published proof's parent system can never change under it: publishing a system
is a one-way door — once published a system rejects every part edit, field edit,
and unpublish (see `systems.require_editable_system`) — so a proof verified
against a published system stays valid. A proof's *own* source is still editable
by its owner; a published proof re-verifies on a source edit (below), and an edit
that would break it is rejected.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from graphlib import CycleError, TopologicalSorter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user, current_active_user_optional
from app.db import FormalSystem, Proof, ProofReference, get_session, system_to_spec
from app.db.models import User
from app.routers._common import PageParams, page_params, paginate_summaries, unique_slug
from app.routers.systems import load_system
from website.logical.formal_system.proof import Proof as EngineProof
from app.schemas import (
    Page,
    ProofCreate,
    ProofDetail,
    ProofReferenceOut,
    ProofReferencesUpdate,
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


# Loads for a detail view: the owner, plus outgoing reference edges and each
# referenced proof (for its public identity in ProofReferenceOut).
_DETAIL_LOADS = (
    selectinload(Proof.owner),
    selectinload(Proof.reference_links).selectinload(ProofReference.referenced),
)


async def _load_owned(
    session: AsyncSession, proof_id: uuid.UUID, owner_id: uuid.UUID
) -> Proof | None:
    stmt = (
        select(Proof)
        .where(Proof.id == proof_id, Proof.owner_id == owner_id)
        .options(*_DETAIL_LOADS)
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
    stmt = select(Proof).where(Proof.id == proof_id).options(*_DETAIL_LOADS)
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


# One reference edge as loaded for the closure: (alias, target proof id, position).
_Edge = tuple[str, uuid.UUID, int]


async def _reference_closure(
    session: AsyncSession, root_id: uuid.UUID
) -> tuple[dict[uuid.UUID, Proof], dict[uuid.UUID, list[_Edge]]]:
    """Load ``root_id`` and every proof it transitively references.

    Returns the proofs keyed by id and each proof's outgoing edges. References are
    same-system-only and the stored graph is acyclic (enforced on write), so this
    BFS terminates within the root's system.
    """
    proofs: dict[uuid.UUID, Proof] = {}
    edges: dict[uuid.UUID, list[_Edge]] = {}
    frontier = [root_id]
    while frontier:
        to_load = [pid for pid in frontier if pid not in proofs]
        frontier = []
        if not to_load:
            break
        rows = (
            await session.scalars(
                select(Proof)
                .where(Proof.id.in_(to_load))
                .options(selectinload(Proof.reference_links))
            )
        ).all()
        for proof in rows:
            proofs[proof.id] = proof
            edges[proof.id] = [
                (link.alias, link.references_id, link.position) for link in proof.reference_links
            ]
            frontier.extend(
                link.references_id
                for link in proof.reference_links
                if link.references_id not in proofs
            )
    return proofs, edges


def _dependency_order(
    node_ids: list[uuid.UUID], edges: dict[uuid.UUID, list[_Edge]]
) -> list[uuid.UUID]:
    # Proofs ordered so a lemma is compiled before the proofs that cite it.
    # Raises graphlib.CycleError if the graph is cyclic.
    sorter: TopologicalSorter[uuid.UUID] = TopologicalSorter()
    for pid in node_ids:
        sorter.add(pid, *(target for _alias, target, _pos in edges.get(pid, ())))
    return list(sorter.static_order())


def _is_usable_lemma(engine_proof: EngineProof) -> bool:
    # Match the engine's own import rule (proof.py `import_path`): only a fully
    # valid, warning-free proof is a usable lemma. A warning-carrying proof is
    # not seeded, so this path and the engine's native import agree on what a
    # usable lemma is.
    return bool(engine_proof.valid) and not engine_proof.has_warnings


async def _verify_with_references(
    session: AsyncSession, proof: Proof, system: FormalSystem | None = None
) -> tuple[VerifyProofResponse, bool | None]:
    """Verify a stored proof, resolving the lemmas it cites from other proofs.

    Compiles the system once and parses the whole transitive reference closure in
    dependency order (a lemma before its dependents), pre-seeding each proof's
    ``reference_context`` with the already-compiled proofs it references — keyed by
    the stored citation alias — so a `[alias.line]` citation resolves to that
    lemma's line. Only *usable* lemmas (fully valid, warning-free) are seeded, so
    a proof leaning on an unproven lemma fails rather than borrowing an unsound
    line. Pass ``system`` to reuse an already-loaded system (a publish gate has
    one in hand); otherwise it is loaded here.

    Returns the response payload plus validity (None when the proof couldn't be
    checked at all — the system doesn't build, or its source doesn't parse).
    """
    if system is None:
        system = await load_system(session, proof.formal_system_id)
    if system is None:
        return VerifyProofResponse(success=False, errors=["The proof's system no longer exists."]), None

    build = build_spec(system_to_spec(system))
    if "errors" in build:
        return VerifyProofResponse(success=False, errors=build["errors"]), None
    compiled_system = build["system"]

    closure, edges = await _reference_closure(session, proof.id)
    try:
        order = _dependency_order(list(closure), edges)
    except CycleError:
        # The stored graph is kept acyclic (enforced on write); a defensive guard.
        return VerifyProofResponse(success=False, errors=["Circular proof reference."]), None

    compiled: dict[uuid.UUID, EngineProof] = {}
    for pid in order:
        reference_context = {
            alias: compiled[target]
            for alias, target, _pos in edges.get(pid, ())
            if target in compiled and _is_usable_lemma(compiled[target])
        }
        engine_proof = EngineProof(formal_system=compiled_system)
        engine_proof.reference_context = reference_context
        # The checker raises on malformed proofs against otherwise-valid systems;
        # reshape into a structured error for the target, and just don't seed a
        # broken lemma downstream.
        try:
            compiled_system.parse(closure[pid].source, proof=engine_proof)
        except Exception as exc:  # noqa: BLE001
            if pid == proof.id:
                return VerifyProofResponse(success=False, errors=[str(exc)]), None
            engine_proof.valid = False
        compiled[pid] = engine_proof

    # The root can be absent if the proof was deleted concurrently between the
    # caller's load and the closure query — a structured failure, not a 500.
    root = compiled.get(proof.id)
    if root is None:
        return VerifyProofResponse(success=False, errors=["Proof not found."]), None
    return VerifyProofResponse(success=root.valid, proof=root.data()), root.valid


async def _invalidate_dependents(session: AsyncSession, proof_id: uuid.UUID) -> None:
    """Clear the cached verdict of every proof that transitively references
    ``proof_id``, so a stale ``valid`` can't survive a change to a lemma it leans
    on (a source edit, or the proof's deletion). Those proofs re-verify on demand.
    """
    dependents: set[uuid.UUID] = set()
    frontier = [proof_id]
    while frontier:
        rows = (
            await session.scalars(
                select(ProofReference.proof_id).where(
                    ProofReference.references_id.in_(frontier)
                )
            )
        ).all()
        frontier = [pid for pid in rows if pid not in dependents]
        dependents.update(frontier)
    if dependents:
        await session.execute(
            sa_update(Proof).where(Proof.id.in_(dependents)).values(valid=None, result=None)
        )


async def _has_published_dependents(session: AsyncSession, proof_id: uuid.UUID) -> bool:
    """Whether any *published* proof references ``proof_id``.

    Only direct dependents are checked: the publish invariant already forces
    every ancestor of a published proof to be published, so a published proof
    that transitively depends on this one has a published proof directly citing
    it somewhere in the chain. Used to block unpublishing or deleting a lemma
    that a public theorem rests on (which would silently break that theorem).
    """
    dependent = await session.scalar(
        select(ProofReference.proof_id)
        .join(Proof, Proof.id == ProofReference.proof_id)
        .where(ProofReference.references_id == proof_id, Proof.published_at.is_not(None))
        .limit(1)
    )
    return dependent is not None


async def _require_publishable(session: AsyncSession, proof: Proof) -> None:
    """Reject a publish that would expose an unverified or dangling public proof.

    Two things a published proof must not do, since it becomes world-readable: it
    must verify against its system, and that system must itself be public — a
    published proof exposes `formal_system_id`, and `GET /formal-systems/{id}`
    404s for anonymous viewers when the system is a private draft.

    A third: every lemma it references must itself be published — a published
    proof's references are part of the theorem it exposes, and a public reader
    must be able to follow them.

    On success the fresh verdict is cached on the row, so a published proof always
    renders as checked. Also used to keep a *published* proof valid across source
    edits: re-running it after a source edit rejects a change that would leave a
    world-readable proof unverifying.
    """
    system = await load_system(session, proof.formal_system_id)
    if system is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The proof's system no longer exists.")

    if system.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot publish a proof whose system is an unpublished draft; "
            "publish the system first.",
        )

    unpublished = [link for link in proof.reference_links if link.referenced.published_at is None]
    if unpublished:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every referenced proof must be published before this proof can be.",
        )

    # Verify with references resolved, so a proof that leans on a lemma is gated
    # on the lemma actually proving it. Reuse the system already loaded above.
    response, valid = await _verify_with_references(session, proof, system=system)
    if not response.success:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.errors or ["Proof does not verify against its system."],
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


def _references_out(proof: Proof, viewer: User | None) -> list[ProofReferenceOut]:
    # Only surface references the viewer may themselves read. Otherwise a
    # published proof that cites the owner's own draft would leak that draft's
    # existence, name, and slug to any anonymous reader.
    return [
        ProofReferenceOut(
            referenced_proof_id=link.references_id,
            alias=link.alias,
            name=link.referenced.name,
            slug=link.referenced.slug,
            published=link.referenced.published_at is not None,
        )
        for link in proof.reference_links
        if _is_readable(link.referenced, viewer)
    ]


def _detail(proof: Proof, viewer: User | None) -> ProofDetail:
    return ProofDetail(
        **_summary(proof).model_dump(),
        source=proof.source,
        result=proof.result,
        references=_references_out(proof, viewer),
    )


@router.get("", response_model=Page[ProofSummary])
async def list_proofs(
    formal_system_id: uuid.UUID | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[ProofSummary]:
    base = [Proof.owner_id == user.id]
    # Optional scope to one system, so an editor can list just that system's proofs.
    if formal_system_id is not None:
        base.append(Proof.formal_system_id == formal_system_id)
    return await paginate_summaries(
        session,
        Proof,
        User,
        base_conditions=base,
        default_order=[Proof.created_at],
        params=params,
        summarize=_summary,
    )


# Declared before `/{proof_id}` so "public" isn't parsed as a proof id.
@router.get("/public", response_model=Page[ProofSummary])
async def list_public_proofs(
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[ProofSummary]:
    """The shared master list: every published proof, any owner, no auth.

    Drafts (``published_at IS NULL``) are excluded; unpublishing removes a proof
    from this list. Newest publications first, unless the client asks to sort.
    """
    return await paginate_summaries(
        session,
        Proof,
        User,
        base_conditions=[Proof.published_at.is_not(None)],
        default_order=[Proof.published_at.desc(), Proof.created_at.desc()],
        params=params,
        summarize=_summary,
    )


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
    return _detail(await _get_owned_or_404(session, proof.id, user.id), user)


@router.get("/{proof_id}", response_model=ProofDetail)
async def get_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    # Published proofs are readable by anyone; drafts only by their owner.
    return _detail(await _get_readable_or_404(session, proof_id, user), user)


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
        # The stored source changed, so this proof's verdict — and the cached
        # verdict of anything that cites it as a lemma — is stale.
        proof.valid = None
        proof.result = None
        await _invalidate_dependents(session, proof.id)

    # Publishing is the write that makes a proof world-readable, so gate it —
    # after the field changes above so the checks see this request's final state.
    # A source edit on an already-published proof is re-gated too, so a
    # world-readable proof can't be edited into a non-verifying state. Both paths
    # re-cache the verdict.
    if "published" in changes:
        if changes["published"]:
            await _require_publishable(session, proof)
        elif await _has_published_dependents(session, proof.id):
            # Unpublishing a lemma a published proof rests on would leave that
            # public theorem depending on a private draft; block it (the
            # dependents must be unpublished first).
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cannot unpublish a proof that a published proof references.",
            )
        proof.published_at = datetime.now(timezone.utc) if changes["published"] else None
    elif source_changed and proof.published_at is not None:
        await _require_publishable(session, proof)

    await session.commit()
    return _detail(await _get_owned_or_404(session, proof_id, user.id), user)


async def _lock_reference_graph(session: AsyncSession, system_id: uuid.UUID) -> None:
    """Serialize concurrent reference-graph edits within one system.

    The cycle check is read-then-write, so two concurrent PUTs (A→B and B→A)
    could each pass against the committed graph and commit a cycle. A
    transaction-scoped advisory lock keyed by the system makes those edits
    serialize, so each sees the other's edge. Postgres only; a no-op on SQLite
    (the test DB, where requests don't run concurrently anyway). Verification
    re-checks for cycles as a defensive backstop (``_dependency_order``).
    """
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(system_id)},
        )


async def _reference_would_cycle(
    session: AsyncSession,
    proof_id: uuid.UUID,
    target_ids: list[uuid.UUID],
    system_id: uuid.UUID,
) -> bool:
    """Whether pointing ``proof_id`` at every id in ``target_ids`` closes a cycle.

    The stored reference graph is kept acyclic, so a new cycle must run through
    ``proof_id`` (proof → target → … → proof). Load every edge in this system
    except this proof's own (they are being replaced) and ask whether any target
    already reaches ``proof_id``. References are same-system-only, so scoping the
    load to the system captures the whole reachable closure without scanning the
    global table. The persistence-layer analogue of the engine's transitive
    ``Proof.circular_dependency``.
    """
    rows = (
        await session.execute(
            select(ProofReference.proof_id, ProofReference.references_id)
            .join(Proof, Proof.id == ProofReference.proof_id)
            .where(Proof.formal_system_id == system_id, ProofReference.proof_id != proof_id)
        )
    ).all()
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for src, dst in rows:
        adjacency[src].append(dst)

    seen: set[uuid.UUID] = set()
    stack = list(target_ids)
    while stack:
        node = stack.pop()
        if node == proof_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


@router.put("/{proof_id}/references", response_model=ProofDetail)
async def set_proof_references(
    proof_id: uuid.UUID,
    payload: ProofReferencesUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    """Replace a proof's outgoing references (the lemmas it cites) wholesale.

    A proof may reference another proof **in the same system** that is either the
    caller's own or published (a public lemma). Self-references, duplicate targets
    or aliases, and any edge that would make the reference graph cyclic are
    rejected (422). A published proof may only reference published proofs (its
    references are part of the public theorem). Changing the set invalidates the
    cached verdict of this proof and of anything that cites it, since references
    now feed verification.
    """
    proof = await _get_owned_or_404(session, proof_id, user.id)

    # Serialize concurrent reference edits in this system so the cycle check
    # below can't be raced into committing a cycle.
    await _lock_reference_graph(session, proof.formal_system_id)

    target_ids = [r.referenced_proof_id for r in payload.references]
    aliases = [r.alias for r in payload.references]

    if proof.id in target_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A proof cannot reference itself.")
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A proof may reference another proof at most once."
        )
    if len(set(aliases)) != len(aliases):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Reference aliases must be unique within a proof."
        )

    if target_ids:
        targets = (await session.scalars(select(Proof).where(Proof.id.in_(target_ids)))).all()
        by_id = {t.id: t for t in targets}
        for tid in target_ids:
            target = by_id.get(tid)
            if target is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"Referenced proof {tid} does not exist."
                )
            if target.formal_system_id != proof.formal_system_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "A proof may only reference proofs in the same system.",
                )
            # Own proofs (draft or published) or anyone's published proof.
            if target.owner_id != user.id and target.published_at is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Referenced proof {tid} must be your own or a published proof.",
                )
            # A published proof's references are exposed publicly and must verify
            # for a public reader, so they must be published too.
            if proof.published_at is not None and target.published_at is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "A published proof may only reference published proofs.",
                )

        if await _reference_would_cycle(session, proof.id, target_ids, proof.formal_system_id):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That set of references would create a circular dependency.",
            )

    # Replace the edge set. Clear-then-flush before inserting so the unique
    # (proof_id, alias) index can't trip on an alias reused from the old set.
    proof.reference_links.clear()
    await session.flush()
    proof.reference_links = [
        ProofReference(references_id=tid, alias=alias, position=i)
        for i, (tid, alias) in enumerate(zip(target_ids, aliases))
    ]
    # References feed verification now, so this proof's verdict and every
    # dependent's are stale.
    proof.valid = None
    proof.result = None
    await _invalidate_dependents(session, proof.id)
    await session.commit()
    return _detail(await _get_owned_or_404(session, proof_id, user.id), user)


@router.delete("/{proof_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proof(
    proof_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Establish ownership first (404 for a stranger's id, so nothing leaks) before
    # any dependency checks reveal the proof exists.
    owned = await session.scalar(
        select(Proof.id).where(Proof.id == proof_id, Proof.owner_id == user.id)
    )
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")

    # Deleting a proof drops its reference edges (FK cascade), so a dependent's
    # `[alias.line]` citation would dangle. If a *published* proof rests on it,
    # that would silently break a public theorem — block it. Otherwise just clear
    # the (draft) dependents' stale verdicts.
    if await _has_published_dependents(session, proof_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete a proof that a published proof references.",
        )
    await _invalidate_dependents(session, proof_id)

    await session.execute(sa_delete(Proof).where(Proof.id == proof_id))
    await session.commit()


@router.post("/{proof_id}/verify", response_model=VerifyProofResponse)
async def verify_stored_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> VerifyProofResponse:
    proof = await _get_readable_or_404(session, proof_id, user)

    response, valid = await _verify_with_references(session, proof)

    # Cache the verdict on the row so a client can render it without re-checking.
    # Only the owner may write it back (an anonymous viewer of a published proof
    # gets the result but leaves the stored snapshot untouched).
    if user is not None and proof.owner_id == user.id:
        proof.valid = valid
        proof.result = response.proof
        await session.commit()

    return response
