"""Per-object CRUD for the parts of a formal system.

Sits under the same `/formal-systems/{system_id}` prefix as the system router and
edits the normalised child rows directly — sorts, productions, definitions,
axioms, rules, line types, brackets — so a system can be built up object by
object. Nested value lists (a production's bindings, a rule's antecedents, a line
type's parts) are supplied on the parent write and replaced wholesale.

Every route is owner-scoped: it first asserts the parent system is owned
(`owned_system_id_or_404`), then operates on children scoped by `system_id`, so
another owner's ids are never reachable.

Compilability is not enforced here (draft-tolerant, per the design): writes
persist structurally-valid rows and `POST /formal-systems/{id}/validate` reports
whether the assembled system compiles.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import FormalSystem, get_session
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _owned(session: AsyncSession, system_id: uuid.UUID, user: User) -> None:
    await owned_system_id_or_404(session, system_id, user.id)


async def _next_position(session: AsyncSession, row_cls, system_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(row_cls.position)).where(row_cls.system_id == system_id)
    )
    return 0 if current is None else current + 1


async def _get_child_or_404(session, row_cls, system_id, child_id, *options):
    stmt = select(row_cls).where(row_cls.id == child_id, row_cls.system_id == system_id)
    if options:
        stmt = stmt.options(*options)
    child = await session.scalar(stmt)
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return child


async def _delete_child(session, row_cls, system_id, child_id) -> None:
    result = await session.execute(
        sa_delete(row_cls).where(row_cls.id == child_id, row_cls.system_id == system_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    await session.commit()


async def _reorder(session, row_cls, system_id, ids: list[uuid.UUID]) -> list:
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
    return [by_id[child_id] for child_id in ids]


def _binding_rows(row_cls, bindings):
    return [row_cls(position=i, var=b.var, sort=b.sort) for i, b in enumerate(bindings)]


async def _resolve_sort(session, system_id, sort_name: str) -> SortRow:
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


async def _require_sort_name_free(session, system_id, name, exclude_id=None) -> None:
    stmt = select(SortRow.id).where(SortRow.system_id == system_id, SortRow.name == name)
    if exclude_id is not None:
        stmt = stmt.where(SortRow.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A sort named '{name}' already exists.")


# ---------------------------------------------------------------------------
# Brackets
# ---------------------------------------------------------------------------


@router.post("/brackets", response_model=BracketPair, status_code=status.HTTP_201_CREATED)
async def create_bracket(
    system_id: uuid.UUID,
    payload: BracketCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> BracketPair:
    await _owned(session, system_id, user)
    row = BracketRow(
        system_id=system_id,
        position=await _next_position(session, BracketRow, system_id),
        opening=payload.opening,
        closing=payload.closing,
    )
    session.add(row)
    await session.commit()
    return bracket_out(row)


@router.patch("/brackets/{bracket_id}", response_model=BracketPair)
async def update_bracket(
    system_id: uuid.UUID,
    bracket_id: uuid.UUID,
    payload: BracketUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> BracketPair:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, BracketRow, system_id, bracket_id)
    fields = payload.model_fields_set
    if "opening" in fields and payload.opening is not None:
        row.opening = payload.opening
    if "closing" in fields and payload.closing is not None:
        row.closing = payload.closing
    await session.commit()
    return bracket_out(row)


@router.delete("/brackets/{bracket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bracket(
    system_id: uuid.UUID,
    bracket_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, BracketRow, system_id, bracket_id)


@router.put("/brackets/order", response_model=list[BracketPair])
async def reorder_brackets(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[BracketPair]:
    await _owned(session, system_id, user)
    return [bracket_out(r) for r in await _reorder(session, BracketRow, system_id, payload.ids)]


# ---------------------------------------------------------------------------
# Sorts
# ---------------------------------------------------------------------------


@router.post("/sorts", response_model=Sort, status_code=status.HTTP_201_CREATED)
async def create_sort(
    system_id: uuid.UUID,
    payload: SortCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Sort:
    await _owned(session, system_id, user)
    await _require_sort_name_free(session, system_id, payload.name)
    row = SortRow(
        system_id=system_id,
        position=await _next_position(session, SortRow, system_id),
        name=payload.name,
    )
    session.add(row)
    await session.commit()
    return sort_out(row)


@router.patch("/sorts/{sort_id}", response_model=Sort)
async def update_sort(
    system_id: uuid.UUID,
    sort_id: uuid.UUID,
    payload: SortUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Sort:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, SortRow, system_id, sort_id)
    if "name" in payload.model_fields_set and payload.name is not None:
        await _require_sort_name_free(session, system_id, payload.name, exclude_id=sort_id)
        row.name = payload.name
    await session.commit()
    return sort_out(row)


@router.delete("/sorts/{sort_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sort(
    system_id: uuid.UUID,
    sort_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Productions reference a sort by FK ON DELETE CASCADE, so removing a sort
    # also removes productions of that sort.
    await _owned(session, system_id, user)
    await _delete_child(session, SortRow, system_id, sort_id)


@router.put("/sorts/order", response_model=list[Sort])
async def reorder_sorts(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Sort]:
    await _owned(session, system_id, user)
    return [sort_out(r) for r in await _reorder(session, SortRow, system_id, payload.ids)]


# ---------------------------------------------------------------------------
# Productions
# ---------------------------------------------------------------------------

_PRODUCTION_LOADS = (selectinload(ProductionRow.sort), selectinload(ProductionRow.bindings))


@router.post("/productions", response_model=Production, status_code=status.HTTP_201_CREATED)
async def create_production(
    system_id: uuid.UUID,
    payload: ProductionCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Production:
    await _owned(session, system_id, user)
    sort = await _resolve_sort(session, system_id, payload.sort)
    row = ProductionRow(
        system_id=system_id,
        sort=sort,
        position=await _next_position(session, ProductionRow, system_id),
        name=payload.name,
        kind=_production_kind(payload.template, payload.regex),
        template=payload.template,
        regex=payload.regex,
    )
    row.bindings = _binding_rows(ProductionBindingRow, payload.bindings)
    session.add(row)
    await session.commit()
    return production_out(row)


@router.patch("/productions/{production_id}", response_model=Production)
async def update_production(
    system_id: uuid.UUID,
    production_id: uuid.UUID,
    payload: ProductionUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Production:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, ProductionRow, system_id, production_id, *_PRODUCTION_LOADS)
    fields = payload.model_fields_set
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
    await session.commit()
    return production_out(row)


@router.delete("/productions/{production_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_production(
    system_id: uuid.UUID,
    production_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, ProductionRow, system_id, production_id)


@router.put("/productions/order", response_model=list[Production])
async def reorder_productions(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Production]:
    await _owned(session, system_id, user)
    rows = await _reorder(session, ProductionRow, system_id, payload.ids)
    # Reorder loads bare rows; production_out needs sort + bindings.
    ordered = [
        await _get_child_or_404(session, ProductionRow, system_id, r.id, *_PRODUCTION_LOADS)
        for r in rows
    ]
    return [production_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Line types
# ---------------------------------------------------------------------------


@router.post("/line-types", response_model=LineType, status_code=status.HTTP_201_CREATED)
async def create_line_type(
    system_id: uuid.UUID,
    payload: LineTypeCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> LineType:
    await _owned(session, system_id, user)
    row = LineRow(
        system_id=system_id,
        position=await _next_position(session, LineRow, system_id),
        name=payload.name,
        shape=payload.shape,
        logical_sort=payload.logical_sort,
    )
    row.parts = [LinePartRow(position=i, name=p.name, regex=p.regex) for i, p in enumerate(payload.parts)]
    session.add(row)
    await session.commit()
    return line_out(row)


@router.patch("/line-types/{line_id}", response_model=LineType)
async def update_line_type(
    system_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: LineTypeUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> LineType:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, LineRow, system_id, line_id, selectinload(LineRow.parts))
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "shape" in fields and payload.shape is not None:
        row.shape = payload.shape
    if "logical_sort" in fields:
        row.logical_sort = payload.logical_sort
    if "parts" in fields and payload.parts is not None:
        row.parts = [LinePartRow(position=i, name=p.name, regex=p.regex) for i, p in enumerate(payload.parts)]
    await session.commit()
    return line_out(row)


@router.delete("/line-types/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_line_type(
    system_id: uuid.UUID,
    line_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, LineRow, system_id, line_id)


@router.put("/line-types/order", response_model=list[LineType])
async def reorder_line_types(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[LineType]:
    await _owned(session, system_id, user)
    rows = await _reorder(session, LineRow, system_id, payload.ids)
    ordered = [
        await _get_child_or_404(session, LineRow, system_id, r.id, selectinload(LineRow.parts))
        for r in rows
    ]
    return [line_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


@router.post("/definitions", response_model=Definition, status_code=status.HTTP_201_CREATED)
async def create_definition(
    system_id: uuid.UUID,
    payload: DefinitionCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Definition:
    await _owned(session, system_id, user)
    row = DefinitionRow(
        system_id=system_id,
        position=await _next_position(session, DefinitionRow, system_id),
        sort=payload.sort,
        name=payload.name,
        higher=payload.higher,
        lower=payload.lower,
        condition=payload.condition,
    )
    row.bindings = _binding_rows(DefinitionBindingRow, payload.bindings)
    session.add(row)
    await session.commit()
    return definition_out(row)


@router.patch("/definitions/{definition_id}", response_model=Definition)
async def update_definition(
    system_id: uuid.UUID,
    definition_id: uuid.UUID,
    payload: DefinitionUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Definition:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, DefinitionRow, system_id, definition_id, selectinload(DefinitionRow.bindings))
    fields = payload.model_fields_set
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
    await session.commit()
    return definition_out(row)


@router.delete("/definitions/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_definition(
    system_id: uuid.UUID,
    definition_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, DefinitionRow, system_id, definition_id)


@router.put("/definitions/order", response_model=list[Definition])
async def reorder_definitions(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Definition]:
    await _owned(session, system_id, user)
    rows = await _reorder(session, DefinitionRow, system_id, payload.ids)
    ordered = [
        await _get_child_or_404(session, DefinitionRow, system_id, r.id, selectinload(DefinitionRow.bindings))
        for r in rows
    ]
    return [definition_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Axioms
# ---------------------------------------------------------------------------


@router.post("/axioms", response_model=Axiom, status_code=status.HTTP_201_CREATED)
async def create_axiom(
    system_id: uuid.UUID,
    payload: AxiomCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Axiom:
    await _owned(session, system_id, user)
    row = AxiomRow(
        system_id=system_id,
        position=await _next_position(session, AxiomRow, system_id),
        label=payload.label,
        name=payload.name,
        formula=payload.formula,
    )
    row.bindings = _binding_rows(AxiomBindingRow, payload.bindings)
    session.add(row)
    await session.commit()
    return axiom_out(row)


@router.patch("/axioms/{axiom_id}", response_model=Axiom)
async def update_axiom(
    system_id: uuid.UUID,
    axiom_id: uuid.UUID,
    payload: AxiomUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Axiom:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, AxiomRow, system_id, axiom_id, selectinload(AxiomRow.bindings))
    fields = payload.model_fields_set
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "formula" in fields and payload.formula is not None:
        row.formula = payload.formula
    if "bindings" in fields and payload.bindings is not None:
        row.bindings = _binding_rows(AxiomBindingRow, payload.bindings)
    await session.commit()
    return axiom_out(row)


@router.delete("/axioms/{axiom_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_axiom(
    system_id: uuid.UUID,
    axiom_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, AxiomRow, system_id, axiom_id)


@router.put("/axioms/order", response_model=list[Axiom])
async def reorder_axioms(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Axiom]:
    await _owned(session, system_id, user)
    rows = await _reorder(session, AxiomRow, system_id, payload.ids)
    ordered = [
        await _get_child_or_404(session, AxiomRow, system_id, r.id, selectinload(AxiomRow.bindings))
        for r in rows
    ]
    return [axiom_out(r) for r in ordered]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

_RULE_LOADS = (selectinload(RuleRow.antecedents), selectinload(RuleRow.bindings))


@router.post("/rules", response_model=Rule, status_code=status.HTTP_201_CREATED)
async def create_rule(
    system_id: uuid.UUID,
    payload: RuleCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Rule:
    await _owned(session, system_id, user)
    row = RuleRow(
        system_id=system_id,
        position=await _next_position(session, RuleRow, system_id),
        label=payload.label,
        name=payload.name,
        deduction=payload.deduction,
    )
    row.antecedents = [
        RuleAntecedentRow(position=i, pattern=pattern) for i, pattern in enumerate(payload.antecedents)
    ]
    row.bindings = _binding_rows(RuleBindingRow, payload.bindings)
    session.add(row)
    await session.commit()
    return rule_out(row)


@router.patch("/rules/{rule_id}", response_model=Rule)
async def update_rule(
    system_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: RuleUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Rule:
    await _owned(session, system_id, user)
    row = await _get_child_or_404(session, RuleRow, system_id, rule_id, *_RULE_LOADS)
    fields = payload.model_fields_set
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
    await session.commit()
    return rule_out(row)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    system_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned(session, system_id, user)
    await _delete_child(session, RuleRow, system_id, rule_id)


@router.put("/rules/order", response_model=list[Rule])
async def reorder_rules(
    system_id: uuid.UUID,
    payload: ReorderRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Rule]:
    await _owned(session, system_id, user)
    rows = await _reorder(session, RuleRow, system_id, payload.ids)
    ordered = [
        await _get_child_or_404(session, RuleRow, system_id, r.id, *_RULE_LOADS) for r in rows
    ]
    return [rule_out(r) for r in ordered]
