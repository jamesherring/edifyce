"""Per-object CRUD for the parts of a formal system.

Sits under the ``/formal-systems/{system_id}`` prefix and edits the normalised
child rows directly, so a system can be built up object by object.

Sorts and productions are two views of one **symbol** table (a sort is a
``union`` symbol, a production a ``composite``/``regex`` symbol that belongs to a
union), so they have bespoke handlers here; the other parts (brackets, line
types, definitions, axioms, rules) share one table-driven CRUD shape. Every
grammar reference — a binding's type, a definition's attach-point, a line type's
logical sort — is resolved from a name to a **symbol FK**, which is what makes
rename safe and delete-when-referenced detectable.

Every route is owner-scoped. Compilability is draft-tolerant: writes persist
structurally-valid rows and ``POST /{id}/validate`` reports whether it compiles.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement
from sqlalchemy import delete as sa_delete
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import Base, get_session
from app.db.models import User
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import (
    build_rule_side_conditions,
    build_side_condition_rows,
    validate_side_condition_metavars,
)
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
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

Payload = BaseModel

# Every column that references a symbol; a symbol referenced by any of these
# can't be deleted (it would orphan a live reference).
_SYMBOL_REFERENCES = (
    ProductionBindingRow.symbol_id,
    DefinitionBindingRow.symbol_id,
    AxiomBindingRow.symbol_id,
    RuleBindingRow.symbol_id,
    DefinitionRow.symbol_id,
    LineRow.logical_symbol_id,
    # A sort named by a `disjoint`/`atom` proviso (definition or rule). Its
    # ON DELETE CASCADE would otherwise silently drop the predicate node and
    # weaken a soundness condition, so a referenced sort must be undeletable too.
    SideConditionRow.sort_symbol_id,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _owned(session: AsyncSession, system_id: uuid.UUID, user: User) -> None:
    await owned_system_id_or_404(session, system_id, user.id)


async def _commit(session: AsyncSession) -> None:
    # Pre-checks give friendly 409s, but they're check-then-insert; a raced DB
    # constraint becomes a 409 too rather than a 500.
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That change conflicts with an existing item.")


async def _next_position(session: AsyncSession, row_cls: type[Base], system_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(row_cls.position)).where(row_cls.system_id == system_id)
    )
    return 0 if current is None else current + 1


async def _get_child_or_404(
    session: AsyncSession, row_cls: type[Base], system_id: uuid.UUID, child_id: uuid.UUID, *options: Any
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
    session: AsyncSession, row_cls: type[Base], system_id: uuid.UUID, ids: list[uuid.UUID],
    loads: tuple[Any, ...],
) -> list[Base]:
    rows = (await session.scalars(select(row_cls).where(row_cls.system_id == system_id))).all()
    return await _apply_order(session, rows, ids, row_cls, loads)


async def _apply_order(
    session: AsyncSession, rows: Sequence[Base], ids: list[uuid.UUID], row_cls: type[Base],
    loads: tuple[Any, ...],
) -> list[Base]:
    by_id = {row.id: row for row in rows}
    if set(ids) != set(by_id) or len(ids) != len(by_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ids must be exactly the collection's members, each once."
        )
    for position, child_id in enumerate(ids):
        by_id[child_id].position = position
    await session.commit()
    if not loads:
        return [by_id[child_id] for child_id in ids]
    reloaded = (
        await session.scalars(select(row_cls).where(row_cls.id.in_(ids)).options(*loads))
    ).all()
    reloaded_by_id = {row.id: row for row in reloaded}
    return [reloaded_by_id[child_id] for child_id in ids]


# ---------------------------------------------------------------------------
# Symbol helpers (sorts + productions live in one table)
# ---------------------------------------------------------------------------

_PRODUCTION_LOADS = (selectinload(SymbolRow.union), selectinload(SymbolRow.bindings).selectinload(ProductionBindingRow.symbol))


async def _resolve_symbol(session: AsyncSession, system_id: uuid.UUID, name: str) -> SymbolRow:
    symbol = await session.scalar(
        select(SymbolRow).where(SymbolRow.system_id == system_id, SymbolRow.name == name)
    )
    if symbol is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown sort or production '{name}'.")
    return symbol


async def _resolve_sort(session: AsyncSession, system_id: uuid.UUID, name: str) -> SymbolRow:
    symbol = await _resolve_symbol(session, system_id, name)
    if symbol.kind != "union":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{name}' is a production, not a sort.")
    return symbol


async def _system_symbols(session: AsyncSession, system_id: uuid.UUID) -> dict[str, SymbolRow]:
    """The system's symbol namespace by name — for resolving a proviso's sorts."""
    symbols = await session.scalars(
        select(SymbolRow).where(SymbolRow.system_id == system_id)
    )
    return {symbol.name: symbol for symbol in symbols}


async def _binding_rows(
    session: AsyncSession, system_id: uuid.UUID, row_cls: type[Base], bindings: Sequence[Binding]
) -> list[Base]:
    rows: list[Base] = []
    for i, b in enumerate(bindings):
        symbol = await _resolve_symbol(session, system_id, b.sort)
        rows.append(row_cls(position=i, var=b.var, symbol=symbol))
    return rows


async def _require_symbol_name_free(
    session: AsyncSession, system_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(SymbolRow.id).where(SymbolRow.system_id == system_id, SymbolRow.name == name)
    if exclude_id is not None:
        stmt = stmt.where(SymbolRow.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A sort or production named '{name}' already exists.")


async def _symbol_referenced(session: AsyncSession, symbol_id: uuid.UUID) -> bool:
    # One round-trip instead of one SELECT per referencing column: OR together an
    # EXISTS per column and let the database short-circuit.
    any_reference = or_(*(exists().where(column == symbol_id) for column in _SYMBOL_REFERENCES))
    return bool(await session.scalar(select(any_reference)))


def _kind_predicate(union: bool) -> ColumnElement[bool]:
    # A sort is the sole ``union`` symbol; everything else is a production.
    return SymbolRow.kind == "union" if union else SymbolRow.kind != "union"


async def _next_symbol_position(session: AsyncSession, system_id: uuid.UUID, union: bool) -> int:
    current = await session.scalar(
        select(func.max(SymbolRow.position)).where(
            SymbolRow.system_id == system_id, _kind_predicate(union)
        )
    )
    return 0 if current is None else current + 1


async def _get_symbol_or_404(
    session: AsyncSession, system_id: uuid.UUID, symbol_id: uuid.UUID, union: bool, *options: Any
) -> SymbolRow:
    stmt = select(SymbolRow).where(
        SymbolRow.id == symbol_id, SymbolRow.system_id == system_id, _kind_predicate(union)
    )
    if options:
        stmt = stmt.options(*options)
    symbol = await session.scalar(stmt)
    if symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return symbol


def _production_kind(template: str | None, regex: str | None) -> str:
    if (template is None) == (regex is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A production needs exactly one of 'template' or 'regex'."
        )
    return "regex" if regex is not None else "composite"


async def _delete_symbol(
    session: AsyncSession, system_id: uuid.UUID, symbol_id: uuid.UUID, *, union: bool
) -> None:
    # Sorts and productions delete the same way — reference-checked so a live FK
    # is never orphaned — except that a sort must also be empty of productions.
    await _get_symbol_or_404(session, system_id, symbol_id, union=union)
    noun = "sort" if union else "production"
    if await _symbol_referenced(session, symbol_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This {noun} is referenced by a binding, definition, line type, or proviso; remove those first.",
        )
    if union and await session.scalar(
        select(SymbolRow.id).where(SymbolRow.member_of_union_id == symbol_id).limit(1)
    ) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This sort still has productions; delete them first."
        )
    await session.execute(sa_delete(SymbolRow).where(SymbolRow.id == symbol_id))
    await session.commit()


async def _reorder_symbols(
    session: AsyncSession, system_id: uuid.UUID, *, union: bool, ids: list[uuid.UUID],
    loads: tuple[Any, ...],
) -> list[SymbolRow]:
    rows = (
        await session.scalars(
            select(SymbolRow).where(SymbolRow.system_id == system_id, _kind_predicate(union))
        )
    ).all()
    return await _apply_order(session, rows, ids, SymbolRow, loads)


# ---------------------------------------------------------------------------
# Sorts (union symbols)
# ---------------------------------------------------------------------------


@router.post("/sorts", response_model=Sort, status_code=status.HTTP_201_CREATED)
async def create_sort(
    system_id: uuid.UUID, payload: SortCreate,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> Sort:
    await _owned(session, system_id, user)
    await _require_symbol_name_free(session, system_id, payload.name)
    row = SymbolRow(
        system_id=system_id, name=payload.name, kind="union",
        position=await _next_symbol_position(session, system_id, union=True),
    )
    session.add(row)
    await _commit(session)
    return sort_out(row)


@router.patch("/sorts/{sort_id}", response_model=Sort)
async def update_sort(
    system_id: uuid.UUID, sort_id: uuid.UUID, payload: SortUpdate,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> Sort:
    await _owned(session, system_id, user)
    row = await _get_symbol_or_404(session, system_id, sort_id, union=True)
    if "name" in payload.model_fields_set and payload.name is not None:
        # Rename is safe: references are FKs, so they follow automatically.
        await _require_symbol_name_free(session, system_id, payload.name, exclude_id=sort_id)
        row.name = payload.name
    await _commit(session)
    return sort_out(row)


@router.delete("/sorts/{sort_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sort(
    system_id: uuid.UUID, sort_id: uuid.UUID,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_symbol(session, system_id, sort_id, union=True)


@router.put("/sorts/order", response_model=list[Sort])
async def reorder_sorts(
    system_id: uuid.UUID, payload: ReorderRequest,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> list[Sort]:
    await _owned(session, system_id, user)
    ordered = await _reorder_symbols(session, system_id, union=True, ids=payload.ids, loads=())
    return [sort_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Productions (composite/regex symbols)
# ---------------------------------------------------------------------------


@router.post("/productions", response_model=Production, status_code=status.HTTP_201_CREATED)
async def create_production(
    system_id: uuid.UUID, payload: ProductionCreate,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> Production:
    await _owned(session, system_id, user)
    await _require_symbol_name_free(session, system_id, payload.name)
    union = await _resolve_sort(session, system_id, payload.sort)
    row = SymbolRow(
        system_id=system_id, name=payload.name,
        kind=_production_kind(payload.template, payload.regex),
        template=payload.template, regex=payload.regex, union=union,
        position=await _next_symbol_position(session, system_id, union=False),
    )
    row.bindings = await _binding_rows(session, system_id, ProductionBindingRow, payload.bindings)
    session.add(row)
    await _commit(session)
    return production_out(await _get_symbol_or_404(session, system_id, row.id, False, *_PRODUCTION_LOADS))


@router.patch("/productions/{production_id}", response_model=Production)
async def update_production(
    system_id: uuid.UUID, production_id: uuid.UUID, payload: ProductionUpdate,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> Production:
    await _owned(session, system_id, user)
    row = await _get_symbol_or_404(session, system_id, production_id, False, *_PRODUCTION_LOADS)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        await _require_symbol_name_free(session, system_id, payload.name, exclude_id=production_id)
        row.name = payload.name
    if "sort" in fields and payload.sort is not None:
        row.union = await _resolve_sort(session, system_id, payload.sort)
    if "template" in fields:
        row.template = payload.template
    if "regex" in fields:
        row.regex = payload.regex
    if "template" in fields or "regex" in fields:
        row.kind = _production_kind(row.template, row.regex)
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = await _binding_rows(session, system_id, ProductionBindingRow, payload.bindings)
    await _commit(session)
    return production_out(await _get_symbol_or_404(session, system_id, production_id, False, *_PRODUCTION_LOADS))


@router.delete("/productions/{production_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_production(
    system_id: uuid.UUID, production_id: uuid.UUID,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_symbol(session, system_id, production_id, union=False)


@router.put("/productions/order", response_model=list[Production])
async def reorder_productions(
    system_id: uuid.UUID, payload: ReorderRequest,
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_session),
) -> list[Production]:
    await _owned(session, system_id, user)
    ordered = await _reorder_symbols(
        session, system_id, union=False, ids=payload.ids, loads=_PRODUCTION_LOADS
    )
    return [production_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Per-type payload -> row mapping for the table-driven parts
# ---------------------------------------------------------------------------


async def _assign_bracket(session: AsyncSession, system_id: uuid.UUID, row: BracketRow, payload: Payload, fields: set[str], creating: bool) -> None:
    if "opening" in fields and payload.opening is not None:
        row.opening = payload.opening
    if "closing" in fields and payload.closing is not None:
        row.closing = payload.closing


async def _assign_line(session: AsyncSession, system_id: uuid.UUID, row: LineRow, payload: Payload, fields: set[str], creating: bool) -> None:
    if creating and await session.scalar(
        select(LineRow.id).where(LineRow.system_id == system_id)
    ) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A system has at most one line type.")
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "shape" in fields and payload.shape is not None:
        row.shape = payload.shape
    if "logical_sort" in fields:
        row.logical_symbol = (
            await _resolve_sort(session, system_id, payload.logical_sort)
            if payload.logical_sort is not None else None
        )
    if "parts" in fields and payload.parts is not None:
        row.parts = [LinePartRow(position=i, name=p.name, regex=p.regex) for i, p in enumerate(payload.parts)]


async def _assign_definition(session: AsyncSession, system_id: uuid.UUID, row: DefinitionRow, payload: Payload, fields: set[str], creating: bool) -> None:
    if "sort" in fields and payload.sort is not None:
        row.symbol = await _resolve_symbol(session, system_id, payload.sort)
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "higher" in fields and payload.higher is not None:
        row.higher = payload.higher
    if "lower" in fields and payload.lower is not None:
        row.lower = payload.lower
    # Bindings first: a proviso's metavariables are validated against them, so a
    # same-request binding change must land before the condition is rebuilt.
    bindings_changed = "bindings" in fields and payload.bindings is not None
    if bindings_changed:
        row.bindings = await _binding_rows(session, system_id, DefinitionBindingRow, payload.bindings)
    rebuilt = "condition" in fields
    if rebuilt:
        # Rebuild the proviso as structured side-condition rows. `side_conditions`
        # is eager-loaded (see the definitions resource), so clearing it here is
        # safe on the async path; delete-orphan removes the previous tree.
        row.side_conditions = []
        if payload.condition:
            symbols = await _system_symbols(session, system_id)
            try:
                build_side_condition_rows(
                    row, payload.condition, symbols, {b.var for b in row.bindings}
                )
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    elif bindings_changed and row.side_conditions:
        # Bindings changed but the proviso wasn't rewritten: re-check the stored
        # tree so a dropped binding can't orphan a metavariable it still names.
        try:
            validate_side_condition_metavars(row.side_conditions, {b.var for b in row.bindings})
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


async def _assign_axiom(session: AsyncSession, system_id: uuid.UUID, row: AxiomRow, payload: Payload, fields: set[str], creating: bool) -> None:
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "formula" in fields and payload.formula is not None:
        row.formula = payload.formula
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = await _binding_rows(session, system_id, AxiomBindingRow, payload.bindings)


async def _assign_rule(session: AsyncSession, system_id: uuid.UUID, row: RuleRow, payload: Payload, fields: set[str], creating: bool) -> None:
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "deduction" in fields and payload.deduction is not None:
        row.deduction = payload.deduction
    if "antecedents" in fields and payload.antecedents is not None:
        row.antecedents = [
            RuleAntecedentRow(position=i, pattern=pattern) for i, pattern in enumerate(payload.antecedents)
        ]
    bindings_changed = "bindings" in fields and payload.bindings is not None
    if bindings_changed:
        row.bindings = await _binding_rows(session, system_id, RuleBindingRow, payload.bindings)
    rebuilt = "side_conditions" in fields and payload.side_conditions is not None
    if rebuilt:
        # Rebuild the provisos as structured side-condition rows. `side_conditions`
        # is eager-loaded (see the rules resource), so clearing it here is safe on
        # the async path; delete-orphan removes the previous tree.
        row.side_conditions = []
        if payload.side_conditions:
            symbols = await _system_symbols(session, system_id)
            try:
                build_rule_side_conditions(
                    row, payload.side_conditions, symbols, {b.var for b in row.bindings}
                )
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    elif bindings_changed and row.side_conditions:
        # Bindings changed but the provisos weren't rewritten: re-check the stored
        # tree so a dropped binding can't orphan a metavariable it still names.
        try:
            validate_side_condition_metavars(row.side_conditions, {b.var for b in row.bindings})
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


# ---------------------------------------------------------------------------
# Table-driven CRUD for brackets, line types, definitions, axioms, rules
# ---------------------------------------------------------------------------

AssignFn = Callable[[AsyncSession, uuid.UUID, Base, Payload, set[str], bool], Awaitable[None]]


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
    resource: ChildResource, system_id: uuid.UUID, payload: BaseModel, user: User,
    session: AsyncSession,
) -> BaseModel:
    await _owned(session, system_id, user)
    row = resource.row_cls(system_id=system_id, position=await _next_position(session, resource.row_cls, system_id))
    await resource.assign(session, system_id, row, payload, set(type(payload).model_fields), True)
    session.add(row)
    await _commit(session)
    return resource.serialize(await _get_child_or_404(session, resource.row_cls, system_id, row.id, *resource.loads))


async def _update_child(
    resource: ChildResource, system_id: uuid.UUID, child_id: uuid.UUID, payload: BaseModel,
    user: User, session: AsyncSession,
) -> BaseModel:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, resource.row_cls, system_id, child_id, *resource.loads)
    await resource.assign(session, system_id, row, payload, payload.model_fields_set, False)
    # Re-add the (persistent) row so any freshly built child subtree an assign
    # created cascades into the session. A side-condition node sits in both its
    # owner collection and its parent's `children` (delete-orphan) collection;
    # on an update that double membership otherwise leaves new nodes unflushed.
    # This mirrors the `session.add` the create path already does.
    session.add(row)
    await _commit(session)
    return resource.serialize(await _get_child_or_404(session, resource.row_cls, system_id, child_id, *resource.loads))


async def _delete_child_route(
    resource: ChildResource, system_id: uuid.UUID, child_id: uuid.UUID, user: User,
    session: AsyncSession,
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, resource.row_cls, system_id, child_id)


async def _reorder_route(
    resource: ChildResource, system_id: uuid.UUID, ids: list[uuid.UUID], user: User,
    session: AsyncSession,
) -> list[BaseModel]:
    await _owned(session, system_id, user)
    rows = await _reorder_rows(session, resource.row_cls, system_id, ids, resource.loads)
    return [resource.serialize(row) for row in rows]


def _register(resource: ChildResource) -> None:
    seg = resource.segment
    tag = seg.replace("-", "_")

    async def create(system_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _create_child(resource, system_id, payload, user, session)

    create.__name__ = f"create_{tag}"
    create.__annotations__ = {"system_id": uuid.UUID, "payload": resource.create_model, "return": resource.out_model}
    router.add_api_route(f"/{seg}", create, methods=["POST"], response_model=resource.out_model, status_code=status.HTTP_201_CREATED)

    async def update(system_id, child_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _update_child(resource, system_id, child_id, payload, user, session)

    update.__name__ = f"update_{tag}"
    update.__annotations__ = {"system_id": uuid.UUID, "child_id": uuid.UUID, "payload": resource.update_model, "return": resource.out_model}
    router.add_api_route(f"/{seg}/{{child_id}}", update, methods=["PATCH"], response_model=resource.out_model)

    async def remove(system_id, child_id, user=Depends(current_active_user), session=Depends(get_session)):
        await _delete_child_route(resource, system_id, child_id, user, session)

    remove.__name__ = f"delete_{tag}"
    remove.__annotations__ = {"system_id": uuid.UUID, "child_id": uuid.UUID, "return": None}
    router.add_api_route(f"/{seg}/{{child_id}}", remove, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT)

    async def reorder(system_id, payload, user=Depends(current_active_user), session=Depends(get_session)):
        return await _reorder_route(resource, system_id, payload.ids, user, session)

    reorder.__name__ = f"reorder_{tag}"
    reorder.__annotations__ = {"system_id": uuid.UUID, "payload": ReorderRequest, "return": list[resource.out_model]}
    router.add_api_route(f"/{seg}/order", reorder, methods=["PUT"], response_model=list[resource.out_model])


RESOURCES: tuple[ChildResource, ...] = (
    ChildResource("brackets", BracketRow, BracketCreate, BracketUpdate, BracketPair, bracket_out, (), _assign_bracket),
    ChildResource(
        "line-types", LineRow, LineTypeCreate, LineTypeUpdate, LineType, line_out,
        (selectinload(LineRow.parts), selectinload(LineRow.logical_symbol)), _assign_line,
    ),
    ChildResource(
        "definitions", DefinitionRow, DefinitionCreate, DefinitionUpdate, Definition, definition_out,
        (selectinload(DefinitionRow.symbol),
         selectinload(DefinitionRow.bindings).selectinload(DefinitionBindingRow.symbol),
         selectinload(DefinitionRow.side_conditions).selectinload(SideConditionRow.sort_symbol)),
        _assign_definition,
    ),
    ChildResource(
        "axioms", AxiomRow, AxiomCreate, AxiomUpdate, Axiom, axiom_out,
        (selectinload(AxiomRow.bindings).selectinload(AxiomBindingRow.symbol),), _assign_axiom,
    ),
    ChildResource(
        "rules", RuleRow, RuleCreate, RuleUpdate, Rule, rule_out,
        (selectinload(RuleRow.antecedents),
         selectinload(RuleRow.bindings).selectinload(RuleBindingRow.symbol),
         selectinload(RuleRow.side_conditions).selectinload(SideConditionRow.sort_symbol)),
        _assign_rule,
    ),
)

for _resource in RESOURCES:
    _register(_resource)
