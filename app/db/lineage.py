"""Which systems a question about one system should really be asked of.

A corpus imported with ``--setmm-layers`` is a **spine**: propositional calculus,
then first-order logic, then ZF set theory, each inheriting the one before. Every
row a read path reaches by system id is partitioned by that split — a proof is
filed against the layer its own section falls in, and so is its documentation.

Which means a question scoped to one system id is, on a layered corpus, scoped to
one *third* of it — and both directions of a cross-reference cross the split. A ZF
comment points at a propositional theorem, and that theorem's "what points at me"
lives on a layer it has never heard of.

**Both directions want the whole spine**, which is worth stating because the
tempting answer is that they want opposite halves. A reference *up* is obvious: a
ZF proof cites `ax-mp` from the root. A reference *down* is just as real, because
a comment may point anywhere in the file and the file has been cut into layers —
`set.mm`'s early prose says "see ~ sqrt2irr" all the time, and `sqrt2irr` is a
leaf. So :func:`spine_ids` is what a read scopes to, and the two walks it is built
from are exported because each is meaningful alone.

Ids only, and walked rather than joined. ``load_chain`` in the systems router
already walks the same edge, but it hydrates each system's whole grammar — the
symbols, lines, definitions, axioms and rules — which is the right trade for a
route that builds a system and badly wrong for one that wants to add a `WHERE`
clause.

What a spine never reaches is a **sibling**: two systems sharing a parent are two
systems, and a reference in one has nothing to do with a proof in the other. That
is why this walks the edge from the system asked about rather than collecting the
tree its root sits over.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import FormalSystem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The same ceiling `app.routers.systems.MAX_INHERITANCE_DEPTH` enforces when an
# edge is written. Restated as a loop bound rather than imported, because the
# router imports *this* layer and not the other way round — and because what it
# does here is stop a cycle that should not exist from spinning forever.
MAX_DEPTH = 8


async def ancestor_ids(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID]:
    """``system_id`` and every system it inherits from, nearest first."""
    chain = [system_id]
    current = system_id
    for _ in range(MAX_DEPTH):
        parent = await session.scalar(
            select(FormalSystem.inherits_from_id).where(FormalSystem.id == current)
        )
        if parent is None or parent in chain:
            break
        chain.append(parent)
        current = parent
    return chain


async def descendant_ids(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID]:
    """``system_id`` and every system that inherits from it, breadth first.

    One query per level rather than a recursive CTE: a spine is three layers, the
    depth is bounded by the same rule that bounds a chain, and the CTE's syntax
    differs enough between Postgres and SQLite to be worth avoiding for a walk
    this short.
    """
    found = [system_id]
    frontier = [system_id]
    for _ in range(MAX_DEPTH):
        children = (
            await session.scalars(
                select(FormalSystem.id).where(
                    FormalSystem.inherits_from_id.in_(frontier)
                )
            )
        ).all()
        frontier = [child for child in children if child not in found]
        if not frontier:
            break
        found.extend(frontier)
    return found


async def spine_ids(session: AsyncSession, system_id: uuid.UUID) -> list[uuid.UUID]:
    """Every system connected to ``system_id`` by inheritance, nearest first.

    Ancestors ahead of descendants, and each walk in its own order, so a caller
    breaking a tie by position resolves to the closest layer — a system's own row
    first, then what it was built on, then what was built on it.
    """
    chain = await ancestor_ids(session, system_id)
    below = await descendant_ids(session, system_id)
    return [*chain, *(found for found in below if found not in chain)]
