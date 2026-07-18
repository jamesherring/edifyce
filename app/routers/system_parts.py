"""Per-object CRUD for the parts of a formal system.

Sits under the same `/formal-systems/{system_id}` prefix as the system router and
edits the normalised child rows directly — sorts, productions, definitions,
axioms, rules, line types, brackets — so a system can be built up object by
object. Nested value lists (a production's bindings, a rule's antecedents, a line
type's parts) are supplied on the parent write and replaced wholesale.

The seven child types share one CRUD shape (create / update / delete / reorder),
so they're described once by a :class:`ChildResource` and their routes are
generated in a loop. Only the type-specific bit — mapping a payload onto a row —
lives per type, in an ``assign`` function.

Every route is owner-scoped: it first asserts the parent system is owned
(`owned_system_id_or_404`), then operates on children scoped by `system_id`, so
another owner's ids are never reachable.

Compilability is not enforced here (draft-tolerant, per the design): writes
persist structurally-valid rows and `POST /formal-systems/{id}/validate` reports
whether the assembled system compiles.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import Base, FormalSystem, get_session
from app.db.models import User
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    ProductionRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SortRow,
)
from app.routers.systems import (
    axiom_out,
    bracket_out,
    definition_out,
    line_out,
    owned_system_id_or_404,
    production_out,
    rule_out,
    sort_out,
)
from app.schemas import (
    Axiom,
    AxiomCreate,
    AxiomUpdate,
    Binding,
    BracketCreate,
    BracketPair,
    BracketUpdate,
    Definition,
    DefinitionCreate,
    DefinitionUpdate,
    LinePartInput,
    LineType,
    LineTypeCreate,
    LineTypeUpdate,
    Production,
    ProductionCreate,
    ProductionUpdate,
    ReorderRequest,
    Rule,
    RuleCreate,
    RuleUpdate,
    Sort,
    SortCreate,
    SortUpdate,
)

router = APIRouter(prefix="/formal-systems/{system_id}", tags=["formal-systems"])

# A payload is one of a resource's create/update models; `assign` reads whichever
# it is given, applying only the fields named in `fields`.
Payload = BaseModel
AssignFn = Callable[[AsyncSession, uuid.UUID, Base, Payload, set[str], bool], Awaitable[None]]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _owned(session: AsyncSession, system_id: uuid.UUID, user: User) -> None:
    await owned_system_id_or_404(session, system_id, user.id)


async def _commit(session: AsyncSession) -> None:
    # The pre-checks (e.g. sort-name uniqueness) give a friendly 409 in the
    # common case, but they're check-then-insert: a concurrent write can still
    # race a DB constraint. Translate that violation into a 409 rather than
    # letting it surface as a 500.
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That change conflicts with an existing item."
        )


async def _next_position(session: AsyncSession, row_cls: type[Base], system_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(row_cls.position)).where(row_cls.system_id == system_id)
    )
    return 0 if current is None else current + 1


async def _get_child_or_404(
    session: AsyncSession,
    row_cls: type[Base],
    system_id: uuid.UUID,
    child_id: uuid.UUID,
    *options: Any,
) -> Base:
    stmt = select(row_cls).where(row_cls.id == child_id, row_cls.system_id == system_id)
    if options:
        stmt = stmt.options(*options)
    child = await session.scalar(stmt)
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return child


async def _delete_child(
    session: AsyncSession, row_cls: type[Base], system_id: uuid.UUID, child_id: uuid.UUID
) -> None:
    result = await session.execute(
        sa_delete(row_cls).where(row_cls.id == child_id, row_cls.system_id == system_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    await session.commit()


async def _reorder_rows(
    session: AsyncSession,
    row_cls: type[Base],
    system_id: uuid.UUID,
    ids: list[uuid.UUID],
    loads: tuple[Any, ...],
) -> list[Base]:
    rows = (
        await session.scalars(select(row_cls).where(row_cls.system_id == system_id))
    ).all()
    by_id = {row.id: row for row in rows}
    if set(ids) != set(by_id) or len(ids) != len(by_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ids must be exactly the collection's members, each once.",
        )
    for position, child_id in enumerate(ids):
        by_id[child_id].position = position
    await session.commit()

    if not loads:
        return [by_id[child_id] for child_id in ids]

    # Reload the relationship-bearing rows in a single query (not one per row),
    # then return them in the requested order.
    reloaded = (
        await session.scalars(
            select(row_cls).where(row_cls.id.in_(ids)).options(*loads)
        )
    ).all()
    reloaded_by_id = {row.id: row for row in reloaded}
    return [reloaded_by_id[child_id] for child_id in ids]


def _binding_rows(row_cls: type[Base], bindings: Sequence[Binding]) -> list[Base]:
    return [row_cls(position=i, var=b.var, sort=b.sort) for i, b in enumerate(bindings)]


def _part_rows(parts: Sequence[LinePartInput]) -> list[LinePartRow]:
    return [LinePartRow(position=i, name=p.name, regex=p.regex) for i, p in enumerate(parts)]


async def _resolve_sort(session: AsyncSession, system_id: uuid.UUID, sort_name: str) -> SortRow:
    sort = await session.scalar(
        select(SortRow).where(SortRow.system_id == system_id, SortRow.name == sort_name)
    )
    if sort is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown sort '{sort_name}'.")
    return sort


def _production_kind(template: str | None, regex: str | None) -> str:
    if (template is None) == (regex is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A production needs exactly one of 'template' or 'regex'.",
        )
    return "regex" if regex is not None else "composite"


async def _require_sort_name_free(
    session: AsyncSession, system_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(SortRow.id).where(SortRow.system_id == system_id, SortRow.name == name)
    if exclude_id is not None:
        stmt = stmt.where(SortRow.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A sort named '{name}' already exists.")


# ---------------------------------------------------------------------------
# Per-type payload -> row mapping. Shared by create (all fields) and update
# (only the fields the client sent). `creating` distinguishes the two where it
# matters (uniqueness excludes the row itself only on update).
# ---------------------------------------------------------------------------


async def _assign_bracket(
    session: AsyncSession, system_id: uuid.UUID, row: BracketRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "opening" in fields and payload.opening is not None:
        row.opening = payload.opening
    if "closing" in fields and payload.closing is not None:
        row.closing = payload.closing


async def _assign_sort(
    session: AsyncSession, system_id: uuid.UUID, row: SortRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "name" in fields and payload.name is not None:
        await _require_sort_name_free(
            session, system_id, payload.name, exclude_id=None if creating else row.id
        )
        row.name = payload.name


async def _assign_production(
    session: AsyncSession, system_id: uuid.UUID, row: ProductionRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "sort" in fields and payload.sort is not None:
        row.sort = await _resolve_sort(session, system_id, payload.sort)
    if "template" in fields:
        row.template = payload.template
    if "regex" in fields:
        row.regex = payload.regex
    if "template" in fields or "regex" in fields:
        row.kind = _production_kind(row.template, row.regex)
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = _binding_rows(ProductionBindingRow, payload.bindings)


async def _assign_line(
    session: AsyncSession, system_id: uuid.UUID, row: LineRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "shape" in fields and payload.shape is not None:
        row.shape = payload.shape
    if "logical_sort" in fields:
        row.logical_sort = payload.logical_sort
    if "parts" in fields and payload.parts is not None:
        row.parts = _part_rows(payload.parts)


async def _assign_definition(
    session: AsyncSession, system_id: uuid.UUID, row: DefinitionRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "sort" in fields and payload.sort is not None:
        row.sort = payload.sort
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "higher" in fields and payload.higher is not None:
        row.higher = payload.higher
    if "lower" in fields and payload.lower is not None:
        row.lower = payload.lower
    if "condition" in fields:
        row.condition = payload.condition
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = _binding_rows(DefinitionBindingRow, payload.bindings)


async def _assign_axiom(
    session: AsyncSession, system_id: uuid.UUID, row: AxiomRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "formula" in fields and payload.formula is not None:
        row.formula = payload.formula
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = _binding_rows(AxiomBindingRow, payload.bindings)


async def _assign_rule(
    session: AsyncSession, system_id: uuid.UUID, row: RuleRow, payload: Payload,
    fields: set[str], creating: bool,
) -> None:
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "deduction" in fields and payload.deduction is not None:
        row.deduction = payload.deduction
    if "antecedents" in fields and payload.antecedents is not None:
        row.antecedents = [
            RuleAntecedentRow(position=i, pattern=pattern)
            for i, pattern in enumerate(payload.antecedents)
        ]
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = _binding_rows(RuleBindingRow, payload.bindings)


# ---------------------------------------------------------------------------
# Resource descriptors + generic CRUD
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChildResource:
    segment: str
    row_cls: type[Base]
    create_model: type[BaseModel]
    update_model: type[BaseModel]
    out_model: type[BaseModel]
    serialize: Callable[[Base], BaseModel]
    loads: tuple[Any, ...]
    assign: AssignFn


async def _create_child(
    resource: ChildResource, system_id: uuid.UUID, payload: Payload, user: User, session: AsyncSession
) -> BaseModel:
    await _owned(session, system_id, user)
    row = resource.row_cls(
        system_id=system_id,
        position=await _next_position(session, resource.row_cls, system_id),
    )
    await resource.assign(session, system_id, row, payload, set(type(payload).model_fields), True)
    session.add(row)
    await _commit(session)
    reloaded = await _get_child_or_404(session, resource.row_cls, system_id, row.id, *resource.loads)
    return resource.serialize(reloaded)


async def _update_child(
    resource: ChildResource, system_id: uuid.UUID, child_id: uuid.UUID, payload: Payload,
    user: User, session: AsyncSession,
) -> BaseModel:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, resource.row_cls, system_id, child_id, *resource.loads)
    await resource.assign(session, system_id, row, payload, payload.model_fields_set, False)
    await _commit(session)
    reloaded = await _get_child_or_404(session, resource.row_cls, system_id, child_id, *resource.loads)
    return resource.serialize(reloaded)


async def _delete_child_route(
    resource: ChildResource, system_id: uuid.UUID, child_id: uuid.UUID, user: User, session: AsyncSession
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, resource.row_cls, system_id, child_id)


async def _reorder_route(
    resource: ChildResource, system_id: uuid.UUID, ids: list[uuid.UUID], user: User, session: AsyncSession
) -> list[BaseModel]:
    await _owned(session, system_id, user)
    rows = await _reorder_rows(session, resource.row_cls, system_id, ids, resource.loads)
    return [resource.serialize(row) for row in rows]


def _register(resource: ChildResource) -> None:
    """Generate the four CRUD routes for one child resource.

    The endpoint closures carry no annotations of their own; FastAPI reads the
    per-resource request/response types from the ``__annotations__`` set below,
    which is how one generic body serves every typed child model.
    """
    seg = resource.segment
    tag = seg.replace("-", "_")

    async def create(system_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _create_child(resource, system_id, payload, user, session)

    create.__name__ = f"create_{tag}"
    create.__annotations__ = {
        "system_id": uuid.UUID, "payload": resource.create_model, "return": resource.out_model,
    }
    router.add_api_route(
        f"/{seg}", create, methods=["POST"],
        response_model=resource.out_model, status_code=status.HTTP_201_CREATED,
    )

    async def update(system_id, child_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _update_child(resource, system_id, child_id, payload, user, session)

    update.__name__ = f"update_{tag}"
    update.__annotations__ = {
        "system_id": uuid.UUID, "child_id": uuid.UUID,
        "payload": resource.update_model, "return": resource.out_model,
    }
    router.add_api_route(
        f"/{seg}/{{child_id}}", update, methods=["PATCH"], response_model=resource.out_model
    )

    async def remove(system_id, child_id, user=Depends(current_active_user), session=Depends(get_session)):
        await _delete_child_route(resource, system_id, child_id, user, session)

    remove.__name__ = f"delete_{tag}"
    remove.__annotations__ = {"system_id": uuid.UUID, "child_id": uuid.UUID, "return": None}
    router.add_api_route(
        f"/{seg}/{{child_id}}", remove, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT
    )

    async def reorder(system_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _reorder_route(resource, system_id, payload.ids, user, session)

    reorder.__name__ = f"reorder_{tag}"
    reorder.__annotations__ = {
        "system_id": uuid.UUID, "payload": ReorderRequest, "return": list[resource.out_model],
    }
    router.add_api_route(
        f"/{seg}/order", reorder, methods=["PUT"], response_model=list[resource.out_model]
    )


RESOURCES: tuple[ChildResource, ...] = (
    ChildResource("brackets", BracketRow, BracketCreate, BracketUpdate, BracketPair, bracket_out, (), _assign_bracket),
    ChildResource("sorts", SortRow, SortCreate, SortUpdate, Sort, sort_out, (), _assign_sort),
    ChildResource(
        "productions", ProductionRow, ProductionCreate, ProductionUpdate, Production, production_out,
        (selectinload(ProductionRow.sort), selectinload(ProductionRow.bindings)), _assign_production,
    ),
    ChildResource(
        "line-types", LineRow, LineTypeCreate, LineTypeUpdate, LineType, line_out,
        (selectinload(LineRow.parts),), _assign_line,
    ),
    ChildResource(
        "definitions", DefinitionRow, DefinitionCreate, DefinitionUpdate, Definition, definition_out,
        (selectinload(DefinitionRow.bindings),), _assign_definition,
    ),
    ChildResource(
        "axioms", AxiomRow, AxiomCreate, AxiomUpdate, Axiom, axiom_out,
        (selectinload(AxiomRow.bindings),), _assign_axiom,
    ),
    ChildResource(
        "rules", RuleRow, RuleCreate, RuleUpdate, Rule, rule_out,
        (selectinload(RuleRow.antecedents), selectinload(RuleRow.bindings)), _assign_rule,
    ),
)

for _resource in RESOURCES:
    _register(_resource)
