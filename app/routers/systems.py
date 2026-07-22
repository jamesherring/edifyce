"""CRUD for formal systems, owner-scoped.

Systems are stored as normalised rows (`app/db/systems.py`); this router is the
thin HTTP layer over them. Reads assemble the full aggregate; `validate` and
`source` rebuild a `SystemSpec` (`app.db.system_to_spec`) and hand it to the
engine (`declarative.build_spec` / `lower`) — no compile logic lives here.

This phase covers **system-level** writes (create / update / delete) plus read,
validate and source. Editing the component parts (productions, definitions,
rules, …) is a later phase; the read models already expose each part's `id` so
that layer can address them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user, current_active_user_optional
from app.db import Base, FormalSystem, get_session, system_to_spec
from app.routers._common import unique_slug
from app.db.models import User
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import (
    definition_condition_string,
    rule_side_conditions_list,
)
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    DefinitionBindingRow,
    DefinitionRow,
    LineRow,
    ProductionBindingRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.schemas import (
    Axiom,
    Binding,
    BracketPair,
    Definition,
    FormalSystemCreate,
    FormalSystemDetail,
    FormalSystemSummary,
    FormalSystemUpdate,
    LinePart,
    LineType,
    Production,
    ProofVerifyRequest,
    Rule,
    Sort,
    SystemOwner,
    SystemSource,
    SystemValidation,
    VerifyProofResponse,
)
from website.logical.declarative import DeclarativeError, build_spec, lower

router = APIRouter(prefix="/formal-systems", tags=["formal-systems"])


# The child collections `system_to_spec` and the detail serializer touch. Async
# has no lazy load, so every one must be eagerly fetched. `owner` is here too so
# the summary/detail serializers can name the author without a lazy load.
_CHILD_LOADS = (
    selectinload(FormalSystem.owner),
    selectinload(FormalSystem.brackets),
    selectinload(FormalSystem.symbols).selectinload(SymbolRow.union),
    selectinload(FormalSystem.symbols)
    .selectinload(SymbolRow.bindings)
    .selectinload(ProductionBindingRow.symbol),
    selectinload(FormalSystem.lines).selectinload(LineRow.parts),
    selectinload(FormalSystem.lines).selectinload(LineRow.logical_symbol),
    selectinload(FormalSystem.definitions).selectinload(DefinitionRow.symbol),
    selectinload(FormalSystem.definitions)
    .selectinload(DefinitionRow.bindings)
    .selectinload(DefinitionBindingRow.symbol),
    # The proviso tree (flat) + each node's sort reference, for
    # definition_condition_string on the async read path.
    selectinload(FormalSystem.definitions)
    .selectinload(DefinitionRow.side_conditions)
    .selectinload(SideConditionRow.sort_symbol),
    selectinload(FormalSystem.axioms)
    .selectinload(AxiomRow.bindings)
    .selectinload(AxiomBindingRow.symbol),
    selectinload(FormalSystem.rules).selectinload(RuleRow.antecedents),
    selectinload(FormalSystem.rules)
    .selectinload(RuleRow.bindings)
    .selectinload(RuleBindingRow.symbol),
    # The rule's proviso tree (flat) + each node's sort reference, for
    # rule_side_conditions_list on the async read path.
    selectinload(FormalSystem.rules)
    .selectinload(RuleRow.side_conditions)
    .selectinload(SideConditionRow.sort_symbol),
)


async def _unique_slug(
    session: AsyncSession, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> str:
    # Slugs are unique per owner; disambiguate collisions with a numeric suffix.
    async def _taken(slug: str) -> bool:
        stmt = select(FormalSystem.id).where(
            FormalSystem.owner_id == owner_id, FormalSystem.slug == slug
        )
        if exclude_id is not None:
            stmt = stmt.where(FormalSystem.id != exclude_id)
        return await session.scalar(stmt) is not None

    return await unique_slug(name, _taken, fallback="system")


async def _load_owned(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> FormalSystem | None:
    stmt = (
        select(FormalSystem)
        .where(FormalSystem.id == system_id, FormalSystem.owner_id == owner_id)
        .options(*_CHILD_LOADS)
    )
    return await session.scalar(stmt)


async def _get_owned_or_404(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> FormalSystem:
    system = await _load_owned(session, system_id, owner_id)
    if system is None:
        # 404 (not 403) for another owner's id, so ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return system


async def load_system(session: AsyncSession, system_id: uuid.UUID) -> FormalSystem | None:
    stmt = select(FormalSystem).where(FormalSystem.id == system_id).options(*_CHILD_LOADS)
    return await session.scalar(stmt)


def _is_readable(system: FormalSystem, user: User | None) -> bool:
    # Published systems are public; drafts are visible only to their owner.
    if system.published_at is not None:
        return True
    return user is not None and system.owner_id == user.id


async def _get_readable_or_404(
    session: AsyncSession, system_id: uuid.UUID, user: User | None
) -> FormalSystem:
    system = await load_system(session, system_id)
    if system is None or not _is_readable(system, user):
        # 404 (not 403) for a draft you don't own, so unpublished ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return system


async def owned_system_id_or_404(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> uuid.UUID:
    """Assert the system exists and is owned, without loading it. 404 otherwise.

    Shared with the child-CRUD router so a child write can scope to an owned
    parent with a single cheap query.
    """
    owned = await session.scalar(
        select(FormalSystem.id).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == owner_id
        )
    )
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return owned


async def _require_owned_reference(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(FormalSystem.id).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == owner_id
        )
    )
    if exists is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"inherits_from_id {system_id} is not one of your systems.",
        )


async def _require_publishable(session: AsyncSession, system: FormalSystem) -> None:
    """Reject a publish that would expose a broken or dangling public system.

    Two things a published system must not do, since it becomes world-readable:
    it must compile (otherwise `/source` and future public consumers break on
    it), and if it inherits from another system that parent must itself be
    public — a published child exposes `inherits_from_id`, and `GET /{parent}`
    404s for anonymous viewers when the parent is a private draft.
    """
    result = build_spec(system_to_spec(system))
    if "errors" in result:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["errors"])

    if system.inherits_from_id is not None:
        parent_published_at = await session.scalar(
            select(FormalSystem.published_at).where(FormalSystem.id == system.inherits_from_id)
        )
        if parent_published_at is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot publish a system that inherits from an unpublished draft; "
                "publish the parent system first.",
            )


async def require_editable_system(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    """Assert the system is owned *and* still a draft; the guard for every edit.

    A published system is **frozen**: its compiled behaviour is exactly what its
    published proofs were verified against, so any part edit (child-CRUD router)
    or system-level edit could silently invalidate them. Publishing is therefore
    a one-way door — unpublishing is refused too (see `update_system`) — and
    editing a published system is a 409. 404 (not 409) when it isn't owned, so
    ids don't leak. Shared with the child-CRUD router.

    NOTE: this closes the *sequential* hole (an edit after a system is published
    is rejected), not a *concurrent* one. An owner who publishes and edits a part
    in overlapping transactions can read ``published_at`` as still-NULL here,
    admit the edit, and commit it after the publish commits — landing a change on
    a now-published system. Closing that means serializing publication against
    part writes (a ``SELECT ... FOR UPDATE`` lock on the parent row in both this
    guard and the publish path). It's deferred: the window needs one owner racing
    a publish and an edit on the same system, and the lock is Postgres-only
    behaviour the SQLite test suite can't exercise — so it belongs with
    deliberate concurrency hardening, tested against Postgres.
    """
    row = (
        await session.execute(
            select(FormalSystem.published_at).where(
                FormalSystem.id == system_id, FormalSystem.owner_id == owner_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    if row.published_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This system is published and can no longer be edited. Publishing is "
            "final so that proofs verified against the system stay valid.",
        )


def _owner_out(system: FormalSystem) -> SystemOwner | None:
    if system.owner is None:
        return None
    return SystemOwner(id=system.owner.id, display_name=system.owner.display_name)


def _summary(system: FormalSystem) -> FormalSystemSummary:
    return FormalSystemSummary(
        id=system.id,
        name=system.name,
        slug=system.slug,
        description=system.description,
        inherits_from_id=system.inherits_from_id,
        published_at=system.published_at,
        created_at=system.created_at,
        updated_at=system.updated_at,
        owner=_owner_out(system),
    )


# Per-child serializers (row -> read schema). Shared with the child-CRUD router
# (app/routers/system_parts.py), which returns individual objects.


def _bindings_out(rows: Sequence[Base]) -> list[Binding]:
    # A binding references a symbol by FK; its `sort` in the API is that symbol's
    # name (a sort or a production).
    return [Binding(var=b.var, sort=b.symbol.name) for b in rows]


def bracket_out(b: BracketRow) -> BracketPair:
    return BracketPair(id=b.id, opening=b.opening, closing=b.closing)


def sort_out(s: SymbolRow) -> Sort:
    return Sort(id=s.id, name=s.name)


def production_out(p: SymbolRow) -> Production:
    return Production(
        id=p.id,
        name=p.name,
        sort=p.union.name,
        kind=p.kind,
        template=p.template,
        regex=p.regex,
        bindings=_bindings_out(p.bindings),
    )


def line_out(line: LineRow) -> LineType:
    return LineType(
        id=line.id,
        name=line.name,
        shape=line.shape,
        logical_sort=line.logical_symbol.name if line.logical_symbol is not None else None,
        parts=[LinePart(id=pt.id, name=pt.name, regex=pt.regex) for pt in line.parts],
    )


def definition_out(d: DefinitionRow) -> Definition:
    return Definition(
        id=d.id,
        sort=d.symbol.name,
        name=d.name,
        higher=d.higher,
        lower=d.lower,
        condition=definition_condition_string(d),
        bindings=_bindings_out(d.bindings),
    )


def axiom_out(a: AxiomRow) -> Axiom:
    return Axiom(id=a.id, label=a.label, name=a.name, formula=a.formula, bindings=_bindings_out(a.bindings))


def rule_out(r: RuleRow) -> Rule:
    return Rule(
        id=r.id,
        label=r.label,
        name=r.name,
        deduction=r.deduction,
        antecedents=[ant.pattern for ant in r.antecedents],
        bindings=_bindings_out(r.bindings),
        side_conditions=rule_side_conditions_list(r),
    )


def _detail(system: FormalSystem) -> FormalSystemDetail:
    return FormalSystemDetail(
        **_summary(system).model_dump(),
        brackets=[bracket_out(b) for b in system.brackets],
        sorts=[sort_out(s) for s in system.symbols if s.kind == "union"],
        productions=[production_out(s) for s in system.symbols if s.kind != "union"],
        lines=[line_out(line) for line in system.lines],
        definitions=[definition_out(d) for d in system.definitions],
        axioms=[axiom_out(a) for a in system.axioms],
        rules=[rule_out(r) for r in system.rules],
    )


@router.get("", response_model=list[FormalSystemSummary])
async def list_systems(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[FormalSystemSummary]:
    systems = await session.scalars(
        select(FormalSystem)
        .where(FormalSystem.owner_id == user.id)
        .options(selectinload(FormalSystem.owner))
        .order_by(FormalSystem.created_at)
    )
    return [_summary(system) for system in systems]


# Declared before `/{system_id}` so "public" isn't parsed as a system id.
@router.get("/public", response_model=list[FormalSystemSummary])
async def list_public_systems(
    session: AsyncSession = Depends(get_session),
) -> list[FormalSystemSummary]:
    """The shared master list: every published system, any owner, no auth.

    Drafts (``published_at IS NULL``) are excluded; unpublishing removes a system
    from this list. Newest publications first.
    """
    systems = await session.scalars(
        select(FormalSystem)
        .where(FormalSystem.published_at.is_not(None))
        .options(selectinload(FormalSystem.owner))
        .order_by(FormalSystem.published_at.desc(), FormalSystem.created_at.desc())
    )
    return [_summary(system) for system in systems]


@router.post("", response_model=FormalSystemDetail, status_code=status.HTTP_201_CREATED)
async def create_system(
    payload: FormalSystemCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    if payload.inherits_from_id is not None:
        await _require_owned_reference(session, payload.inherits_from_id, user.id)

    system = FormalSystem(
        owner_id=user.id,
        name=payload.name,
        slug=await _unique_slug(session, user.id, payload.name),
        description=payload.description,
        inherits_from_id=payload.inherits_from_id,
    )
    session.add(system)
    await session.commit()

    # Reload so the (empty) child collections are eagerly present for the
    # detail serializer, and server-default timestamps are populated.
    return _detail(await _get_owned_or_404(session, system.id, user.id))


@router.get("/{system_id}", response_model=FormalSystemDetail)
async def get_system(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    # Published systems are readable by anyone; drafts only by their owner.
    return _detail(await _get_readable_or_404(session, system_id, user))


@router.patch("/{system_id}", response_model=FormalSystemDetail)
async def update_system(
    system_id: uuid.UUID,
    payload: FormalSystemUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    system = await _get_owned_or_404(session, system_id, user.id)
    changes = payload.model_dump(exclude_unset=True)

    # A published system is frozen: no field edits and no unpublishing, so proofs
    # verified against it stay valid (child-part edits are blocked the same way in
    # the system-parts router). Reject any change; an empty PATCH is a harmless
    # no-op. Publishing a *draft* is still allowed (handled below).
    if system.published_at is not None and changes:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This system is published and can no longer be edited or unpublished. "
            "Publishing is final so that proofs verified against it stay valid.",
        )

    if "inherits_from_id" in changes and changes["inherits_from_id"] is not None:
        if changes["inherits_from_id"] == system_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A system cannot inherit from itself.")
        await _require_owned_reference(session, changes["inherits_from_id"], user.id)

    if changes.get("name") is not None:
        system.name = changes["name"]
        system.slug = await _unique_slug(session, user.id, changes["name"], exclude_id=system.id)
    if "description" in changes:
        system.description = changes["description"]
    if "inherits_from_id" in changes:
        system.inherits_from_id = changes["inherits_from_id"]

    # Publishing makes a system world-readable and is a one-way door — once set,
    # the freeze above rejects any later edit or unpublish. `published: false`
    # only reaches here for a draft (already unpublished), so it's a no-op.
    if changes.get("published"):
        await _require_publishable(session, system)
        system.published_at = datetime.now(timezone.utc)

    await session.commit()
    return _detail(await _get_owned_or_404(session, system_id, user.id))


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # One owner-scoped Core DELETE; the children (and proofs/folders/theorems)
    # go via their ON DELETE CASCADE foreign keys, so nothing is loaded here.
    result = await session.execute(
        sa_delete(FormalSystem).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == user.id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    await session.commit()


@router.post("/{system_id}/validate", response_model=SystemValidation)
async def validate_system(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> SystemValidation:
    system = await _get_readable_or_404(session, system_id, user)

    # NOTE: inheritance is not resolved yet. `inherits_from_id` is stored (and
    # its reference validated on write), but the declarative pipeline has no
    # `inherit` concept — `system_to_spec`/`lower` describe this system alone and
    # no parent `system_dict` is supplied — so a child that relies on a parent's
    # grammar/rules would validate in isolation. Wiring the parent chain through
    # here (and `/source`) is deferred to the inheritance phase; see
    # docs/object-crud-design.md.
    result = build_spec(system_to_spec(system))

    if "errors" in result:
        return SystemValidation(success=False, errors=result["errors"])

    compiled = result["system"]
    return SystemValidation(
        success=True,
        system_name=compiled.name or None,
        line_type_count=len(compiled.line_types),
        inference_rule_count=len(compiled.inference_rules),
    )


@router.post("/{system_id}/verify", response_model=VerifyProofResponse)
async def verify_proof(
    system_id: uuid.UUID,
    payload: ProofVerifyRequest,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> VerifyProofResponse:
    """Check a proof against a stored system, assembled server-side from rows.

    Replaces the raw-source verify: the client sends only the proof text and the
    system id, never the system's `.edi`. Readable systems are published ones
    (any viewer) or the owner's own drafts. Inheritance is not resolved yet (see
    the note on `validate_system`).
    """
    system = await _get_readable_or_404(session, system_id, user)

    result = build_spec(system_to_spec(system))
    if "errors" in result:
        # The stored system no longer compiles; surface the compile errors as a
        # 400 the client renders verbatim, as the old raw-source verify did.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["errors"])

    compiled = result["system"]
    # The proof checker raises on malformed proofs against otherwise-valid
    # systems (e.g. a line type whose context edit targets a missing key);
    # return a structured error rather than letting it escape as a 500.
    try:
        proof = compiled.parse(payload.proof_text)
    except Exception as e:
        return VerifyProofResponse(success=False, errors=[str(e)])

    return VerifyProofResponse(success=proof.valid, proof=proof.data())


@router.get("/{system_id}/source", response_model=SystemSource)
async def system_source(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> SystemSource:
    system = await _get_readable_or_404(session, system_id, user)
    # Describes this system alone; inheritance is not lowered yet (see the note
    # on validate_system).
    #
    # `lower` raises `DeclarativeError` on a structurally-invalid spec (e.g. a
    # line shape with no grammar-sort placeholder). Published systems are
    # world-readable, so a broken one would otherwise be an unauthenticated 500;
    # surface it as a 422 with the error text, mirroring how `validate` reports
    # `build_spec` failures.
    try:
        source = lower(system_to_spec(system))
    except DeclarativeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[str(exc)]) from exc
    return SystemSource(source=source)
