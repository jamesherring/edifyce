"""Small helpers shared across the CRUD routers.

Kept model-agnostic: nothing here imports a specific ORM model, so both the
formal-system and proof routers can reuse it without a circular import. Anything
that needs to query a table passes a predicate in (see :func:`unique_slug`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import selectinload

from app.db.slugs import slugify
from app.schemas import Page

if TYPE_CHECKING:
    import uuid

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

S = TypeVar("S")


# The `.list()` / `.list()/public` endpoints all page over a summary row that
# carries the same sortable surface (name, description, owner display name,
# timestamps) and an `owner` relationship. `paginate_summaries` keeps that whole
# paging/search/sort recipe in one place; it stays model-agnostic by taking the
# ORM classes as arguments (mirroring `unique_slug`), so `_common` never imports
# a concrete model.

# Cap the page size so a client can't ask the DB for an unbounded slice.
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class PageParams:
    """The pagination/search/sort query params every list endpoint accepts."""

    limit: int
    offset: int
    search: str | None
    sort: str | None
    descending: bool


def page_params(
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    sort: str | None = Query(None),
    desc: bool = Query(False),
) -> PageParams:
    """FastAPI dependency: parse the shared list query params once."""
    return PageParams(limit=limit, offset=offset, search=search, sort=sort, descending=desc)


def _search_conditions(model: Any, search: str | None) -> list[ColumnElement[bool]]:
    """A case-insensitive ``name``/``description`` filter, or nothing when blank."""
    if not search or not search.strip():
        return []
    like = f"%{search.strip()}%"
    return [or_(model.name.ilike(like), model.description.ilike(like))]


def _order_by(
    model: Any,
    user_model: Any,
    sort: str | None,
    descending: bool,
    default: Sequence[ColumnElement[Any]],
) -> tuple[list[ColumnElement[Any]], bool]:
    """Resolve a client column id into a stable ORDER BY.

    Returns the ordering plus whether it references the owner (so the caller
    joins ``user_model`` for the ``author`` sort). Unknown/blank sort keys fall
    back to ``default`` untouched. For an explicit sort, ``model.id`` is appended
    so pages don't shuffle rows that share the sorted value.

    A default that can tie has to carry its own last key rather than take one
    here, because the right one depends on what the tie means. Ties are a
    *bulk-write* phenomenon: ``created_at`` defaults to ``now()``, which under
    Postgres is the transaction's timestamp, so rows written together share it —
    which is one row per request for the interactive lists (where creation order
    is therefore already total) and a whole batch for an import. See
    ``proofs.list_public_proofs``, the listing an import feeds.
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


async def paginate_summaries(
    session: AsyncSession,
    model: Any,
    user_model: Any,
    *,
    base_conditions: Sequence[ColumnElement[bool]],
    default_order: Sequence[ColumnElement[Any]],
    params: PageParams,
    summarize: Callable[[Any], S],
) -> Page[S]:
    """Assemble, run, and serialize one page of an owner-bearing summary list.

    Folds the whole recipe the four list endpoints share: apply the search
    filter over ``base_conditions``, resolve the sort (joining ``user_model``
    only when sorting by author), fetch the slice, and count the full match set
    for the page controls. Owner is eager-loaded via ``selectinload`` so the
    summarizer can name the author without a lazy load.
    """
    conditions = [*base_conditions, *_search_conditions(model, params.search)]
    order_by, by_author = _order_by(model, user_model, params.sort, params.descending, default_order)

    stmt = select(model).where(*conditions).options(selectinload(model.owner))
    if by_author:
        stmt = stmt.outerjoin(user_model, model.owner_id == user_model.id)
    stmt = stmt.order_by(*order_by)

    rows = (await session.scalars(stmt.limit(params.limit).offset(params.offset))).all()
    # A first page that isn't full already holds every match, so the count query
    # is pure waste — skip it. (The common "my systems"/"my proofs" load.)
    if params.offset == 0 and len(rows) < params.limit:
        total = len(rows)
    else:
        total = await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

    return Page(
        items=[summarize(row) for row in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


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


async def lock_system(session: AsyncSession, system_id: uuid.UUID) -> None:
    """Serialize this transaction against every other one touching ``system_id``.

    Several writes across these routers are read-then-write and race:

    * the reference-graph cycle check — two concurrent PUTs of A→B and B→A each
      pass against the committed graph and together commit a cycle;
    * term interning when a proof is checked — two proofs in one system both miss
      the same new subterm and both insert it;
    * **verification against invalidation** — a verify reads a lemma's stored
      lines, a concurrent source edit invalidates them and commits, and the
      verify then writes a valid snapshot back over that invalidation. Since a
      verify now *trusts* those rows rather than re-checking the lemma
      (``docs/verification-from-rows.md``), a later proof would rest on a
      theorem no longer in the lemma's source.

    The third is why this is taken at the **start** of a verify rather than just
    before its write, and why every invalidation takes it too: the read and the
    write have to be inside one critical section, or the invalidation can land
    between them. One key per system, always acquired first — and a proof may
    only reference proofs in its own system, so one key covers a whole reference
    closure.

    One caller needs **several** keys: changing what a label resolves to
    invalidates the proofs that cited it, and a citation crosses systems
    (`proofs`' ``_invalidate_citations``). It acquires in **(depth, id)** order —
    ancestor first — and not simply sorted by id, because it is reached with its
    subtree's root already locked here, so a sorted order can put a descendant's
    key ahead of one already held and two operations at different levels of one
    tower deadlock. Any future caller taking more than one key has to fit the
    same order, counting the key it already holds.

    Postgres only; a no-op on SQLite (the test database, where requests do not
    run concurrently anyway), which is why the routes are covered by asserting
    that they *take* the lock and the exclusion itself is tested against a real
    Postgres.
    """
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(system_id)},
        )
