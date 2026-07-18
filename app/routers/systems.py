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

import re
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import Base, FormalSystem, get_session, system_to_spec
from app.db.models import User
from app.db.systems import (
    AxiomRow,
    BracketRow,
    DefinitionRow,
    LineRow,
    ProductionRow,
    RuleRow,
    SortRow,
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
    Rule,
    Sort,
    SystemSource,
    SystemValidation,
)
from website.logical.declarative import build_spec, lower

router = APIRouter(prefix="/formal-systems", tags=["formal-systems"])


# The child collections `system_to_spec` and the detail serializer touch. Async
# has no lazy load, so every one must be eagerly fetched.
_CHILD_LOADS = (
    selectinload(FormalSystem.brackets),
    selectinload(FormalSystem.sorts),
    selectinload(FormalSystem.productions).selectinload(ProductionRow.sort),
    selectinload(FormalSystem.productions).selectinload(ProductionRow.bindings),
    selectinload(FormalSystem.lines).selectinload(LineRow.parts),
    selectinload(FormalSystem.definitions).selectinload(DefinitionRow.bindings),
    selectinload(FormalSystem.axioms).selectinload(AxiomRow.bindings),
    selectinload(FormalSystem.rules).selectinload(RuleRow.antecedents),
    selectinload(FormalSystem.rules).selectinload(RuleRow.bindings),
)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "system"


async def _unique_slug(
    session: AsyncSession, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> str:
    # Slugs are unique per owner; disambiguate collisions with a numeric suffix.
    base = _slugify(name)
    slug = base
    n = 2
    while True:
        stmt = select(FormalSystem.id).where(
            FormalSystem.owner_id == owner_id, FormalSystem.slug == slug
        )
        if exclude_id is not None:
            stmt = stmt.where(FormalSystem.id != exclude_id)
        if await session.scalar(stmt) is None:
            return slug
        slug = f"{base}-{n}"
        n += 1


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
    )


# Per-child serializers (row -> read schema). Shared with the child-CRUD router
# (app/routers/system_parts.py), which returns individual objects.


def _bindings_out(rows: Sequence[Base]) -> list[Binding]:
    return [Binding(var=b.var, sort=b.sort) for b in rows]


def bracket_out(b: BracketRow) -> BracketPair:
    return BracketPair(id=b.id, opening=b.opening, closing=b.closing)


def sort_out(s: SortRow) -> Sort:
    return Sort(id=s.id, name=s.name)


def production_out(p: ProductionRow) -> Production:
    return Production(
        id=p.id,
        name=p.name,
        sort=p.sort.name,
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
        logical_sort=line.logical_sort,
        parts=[LinePart(id=pt.id, name=pt.name, regex=pt.regex) for pt in line.parts],
    )


def definition_out(d: DefinitionRow) -> Definition:
    return Definition(
        id=d.id,
        sort=d.sort,
        name=d.name,
        higher=d.higher,
        lower=d.lower,
        condition=d.condition,
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
    )


def _detail(system: FormalSystem) -> FormalSystemDetail:
    return FormalSystemDetail(
        **_summary(system).model_dump(),
        brackets=[bracket_out(b) for b in system.brackets],
        sorts=[sort_out(s) for s in system.sorts],
        productions=[production_out(p) for p in system.productions],
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
        .order_by(FormalSystem.created_at)
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
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    return _detail(await _get_owned_or_404(session, system_id, user.id))


@router.patch("/{system_id}", response_model=FormalSystemDetail)
async def update_system(
    system_id: uuid.UUID,
    payload: FormalSystemUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    system = await _get_owned_or_404(session, system_id, user.id)
    changes = payload.model_dump(exclude_unset=True)

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
    if "published" in changes:
        system.published_at = datetime.now(timezone.utc) if changes["published"] else None

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
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SystemValidation:
    system = await _get_owned_or_404(session, system_id, user.id)

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


@router.get("/{system_id}/source", response_model=SystemSource)
async def system_source(
    system_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SystemSource:
    system = await _get_owned_or_404(session, system_id, user.id)
    # Describes this system alone; inheritance is not lowered yet (see the note
    # on validate_system).
    return SystemSource(source=lower(system_to_spec(system)))
