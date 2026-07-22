"""Small helpers shared across the CRUD routers.

Kept model-agnostic: nothing here imports a specific ORM model, so both the
formal-system and proof routers can reuse it without a circular import. Anything
that needs to query a table passes a predicate in (see :func:`unique_slug`).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable


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
