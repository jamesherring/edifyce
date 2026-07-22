"""Small helpers shared across the CRUD routers.

Kept model-agnostic: nothing here imports a specific ORM model, so both the
formal-system and proof routers can reuse it without a circular import. Anything
that needs to query a table passes a predicate in (see :func:`unique_slug`).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, Select
    from sqlalchemy.ext.asyncio import AsyncSession


# The `.list()` / `.list()/public` endpoints all page over a summary row that
# carries the same sortable surface (name, description, owner display name,
# timestamps). These helpers keep that paging/search/sort logic in one place;
# each stays model-agnostic by taking the ORM classes as arguments (mirroring
# `unique_slug`), so `_common` never imports a concrete model.

# Cap the page size so a client can't ask the DB for an unbounded slice.
MAX_PAGE_SIZE = 100


def search_conditions(model: Any, search: str | None) -> list[ColumnElement[bool]]:
    """A case-insensitive ``name``/``description`` filter, or nothing when blank."""
    if not search or not search.strip():
        return []
    like = f"%{search.strip()}%"
    return [or_(model.name.ilike(like), model.description.ilike(like))]


def order_by_clause(
    model: Any,
    user_model: Any,
    sort: str | None,
    descending: bool,
    default: Sequence[ColumnElement[Any]],
) -> tuple[list[ColumnElement[Any]], bool]:
    """Resolve a column id from the client into a stable ORDER BY.

    Returns the ordering plus whether it references the owner (so the caller
    knows to join ``user_model`` for the ``author`` sort). Unknown/blank sort
    keys fall back to ``default`` untouched (its own creation-order tiebreak is
    already deterministic). For an explicit sort, ``model.id`` is appended so
    pages don't shuffle rows that share the sorted value.
    """
    columns: dict[str, ColumnElement[Any]] = {
        "name": model.name,
        "description": model.description,
        "author": user_model.display_name,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }
    column = columns.get(sort or "")
    if column is None:
        return list(default), False
    ordered = column.desc() if descending else column.asc()
    return [ordered, model.id], sort == "author"


async def fetch_page(
    session: AsyncSession,
    items_stmt: Select[Any],
    count_stmt: Select[Any],
    *,
    limit: int,
    offset: int,
) -> tuple[Sequence[Any], int]:
    """Run the count and the (limited) item query, returning ``(rows, total)``.

    ``count_stmt`` must carry the same WHERE as ``items_stmt`` but no ORDER
    BY/LIMIT — it answers "how many match" for the page controls.
    """
    total = await session.scalar(count_stmt) or 0
    rows = (await session.scalars(items_stmt.limit(limit).offset(offset))).all()
    return rows, total


def count_stmt_for(model: Any, conditions: Sequence[ColumnElement[bool]]) -> Select[Any]:
    """A ``SELECT count(*)`` over ``model`` filtered by ``conditions``."""
    return select(func.count()).select_from(model).where(*conditions)


def slugify(name: str, fallback: str) -> str:
    """A URL-safe slug from a display name, falling back when it empties out."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or fallback


async def unique_slug(
    name: str, exists: Callable[[str], Awaitable[bool]], *, fallback: str
) -> str:
    """Slugify ``name`` and disambiguate collisions with a numeric suffix.

    ``exists`` answers "is this slug already taken?" for the caller's own
    uniqueness scope (per owner, per system, …), so the collision policy lives
    here once while each router keeps its own query.
    """
    base = slugify(name, fallback)
    slug = base
    n = 2
    while await exists(slug):
        slug = f"{base}-{n}"
        n += 1
    return slug
