"""Turning a display name into a URL-safe slug.

Here rather than in ``app/routers/_common.py``, where it began, because both
layers need it and the persistence layer must not depend on a router: an import
names folders after a `.mm` file's section headers and slugs them without an HTTP
request anywhere in sight. The routers import it from here.
"""

from __future__ import annotations

import re

_UNSAFE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, fallback: str) -> str:
    """A URL-safe slug from a display name, falling back when it empties out."""
    return _UNSAFE.sub("-", name.lower()).strip("-") or fallback


def unique_slug(name: str, taken: set[str], fallback: str) -> str:
    """:func:`slugify`, disambiguated against slugs already used, and reserving it.

    The synchronous counterpart of ``routers._common.unique_slug``, whose
    ``exists`` callback asks the database one slug at a time. A bulk writer knows
    its whole namespace up front — an import creates 1,903 folders in one pass —
    and a query per candidate would be 1,903 round trips for a question a set
    answers. ``taken`` is mutated, so the caller keeps one set per scope.
    """
    base = slugify(name, fallback)
    slug = base
    n = 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug
