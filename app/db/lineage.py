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

What a spine never reaches is a **sibling of the system asked about**: two systems
sharing its parent are two systems, and a reference in one has nothing to do with
a proof in the other. That is why this walks the edge from the system asked about
rather than collecting the tree its root sits over.

It does reach **both branches below a fork**, though, and that is a real limit
rather than a claim. A system with two children has two descendants that are
siblings of each other, and if both declare a proof of the same name then a
reference in the parent's prose names neither in particular — the parent's comment
predates both. `descendant_ids` orders such a pair by id so the answer is at least
the same twice, and the caller resolves nearest-first, so an ancestor or the
system's own row always wins over either. Scoping instead to "the systems one
import wrote" would settle it properly, and there is nothing recording that today
(the closest thing is `formal_systems.provenance`, which a spine shares) — so this
is written down rather than guessed at (raised in review).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import FormalSystem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The same bound `systems.MAX_INHERITANCE_DEPTH` applies on the spine, restated
# here rather than imported: this module is the persistence layer and must not
# depend on a router (as `notations_mapping` and `system_relations_mapping`
# already record). A cycle is refused when the edge is stored, so the `seen`
# checks below are a backstop against data that predates that check.
#
# It has to be the *same* number. At a smaller one these walks stop early on a
# legal chain and silently drop the layers past it — references beyond the bound
# resolve to nothing and mentions go unreported, with nothing saying so (found in
# review, where this read 8).
_MAX_DEPTH = 32


async def ancestor_ids(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID]:
    """``system_id`` and every system it inherits from, nearest first."""
    chain = [system_id]
    current = system_id
    for _ in range(_MAX_DEPTH):
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
    for _ in range(_MAX_DEPTH):
        children = (
            await session.scalars(
                select(FormalSystem.id)
                .where(FormalSystem.inherits_from_id.in_(frontier))
                # By id, so a fork's two branches come back in the same order
                # every time. Without it the database is free to reorder them and
                # a caller breaking a tie by position resolves differently between
                # two reads of the same rows (raised in review).
                .order_by(FormalSystem.id)
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
