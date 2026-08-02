"""Which systems a relation edge adds to a citation's reach.

`effective_library` answers that for the **spine**: a system's own library and
its ancestors', nearest first. An edge (`app/db/system_relations.py`) is the
other way a theorem becomes citable somewhere it was not proved — a second
parent, or an interpretation — and this turns the edges reaching a system into
the extra layers a `LibraryChain` needs.

The layers it produces are ordinary ones: a system id and the digest guarding
*its* stored terms. Nothing about resolution changes, which is the point — a
citation across an edge is the same term-graph read a citation across the spine
is (§3.1), resolved by the same `read_theorems` against the same digests.

**Ordering puts the spine first.** Relation layers are appended after the
inheritance chain, so a label the tower already answers keeps its answer and an
edge can only add. That is the conservative direction: an edge is a claim an
author made, the spine is a claim the builder checked.

**A draft edge resolves nothing**, and neither does a discharged one with an
obligation outstanding. Both are checked, rather than trusting `status` alone,
because the column is a cache of the obligations' verdict and a cache that has
gone stale must fail closed — an obligation is retired by its theorem
disappearing (`ON DELETE SET NULL`), which no one thought to write back to the
edge.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FormalSystem
from app.db.system_relations import (
    SystemRelationObligationRow,
    SystemRelationRow,
)
from app.db.systems_mapping import system_to_spec
from website.logical.declarative import layered_spec, library_digest

if TYPE_CHECKING:
    from collections.abc import Sequence

# Statuses that let a theorem across. A single-member tuple rather than a bare
# comparison so the gate reads the same here as it does in the model's own note.
_TRANSFERS = ("discharged",)


def related_layers(
    session: Session, chain: Sequence[FormalSystem]
) -> list[tuple[uuid.UUID, str]]:
    """The extra `LibraryChain` layers the edges into ``chain`` reach.

    ``chain`` is the citing system's inheritance chain, root first — what
    :func:`~app.db.systems_mapping.effective_library` was given. An edge into
    *any* of those systems reaches the citing one, because an ancestor's library
    is already citable here and an edge extends that library.

    Each reached source contributes its **own** chain, so a theorem proved two
    layers below the source is citable across the edge exactly as it is below it.
    Deduplicated against the citing chain and against each other, first
    occurrence winning — a system reached twice is one layer at its nearest
    position, which is what `LibraryChain.rank` means.
    """
    reachable = {system.id for system in chain}
    edges = list(
        session.scalars(
            select(SystemRelationRow)
            .where(
                SystemRelationRow.target_system_id.in_(reachable),
                SystemRelationRow.status.in_(_TRANSFERS),
            )
            .order_by(SystemRelationRow.position, SystemRelationRow.id)
        )
    )
    if not edges:
        return []

    outstanding = _edges_with_outstanding_obligations(
        session, [edge.id for edge in edges]
    )
    layers: list[tuple[uuid.UUID, str]] = []
    seen = set(reachable)
    for edge in edges:
        if edge.id in outstanding:
            continue
        for system_id, digest in _source_layers(session, edge.source_system_id):
            if system_id in seen:
                continue
            seen.add(system_id)
            layers.append((system_id, digest))
    return layers


def _edges_with_outstanding_obligations(
    session: Session, edge_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    # An edge is only as discharged as its obligations. Read separately from the
    # edge's own `status` so a stale column fails closed: the rule §2 states is
    # about the primitives, and this is the query that asks the primitives.
    return set(
        session.scalars(
            select(SystemRelationObligationRow.relation_id).where(
                SystemRelationObligationRow.relation_id.in_(edge_ids),
                SystemRelationObligationRow.status.notin_(_TRANSFERS),
            )
        )
    )


def _source_layers(
    session: Session, source_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    # The source and its ancestors, nearest first, each with the digest guarding
    # its own stored terms — `effective_library`'s calculation, for a chain read
    # here rather than handed in. The running prefix is the same: layer *i*'s
    # digest covers layers 0..i, because that is the grammar its terms were
    # composed against.
    chain: list[FormalSystem] = []
    current: uuid.UUID | None = source_id
    while current is not None and len(chain) < _MAX_DEPTH:
        system = session.get(FormalSystem, current)
        if system is None:
            break
        chain.insert(0, system)
        current = system.inherits_from_id
    if not chain:
        return []

    specs = [system_to_spec(system) for system in chain]
    return [
        (system.id, library_digest(layered_spec(specs[: index + 1])))
        for index, system in reversed(list(enumerate(chain)))
    ]


# The same bound `systems.MAX_INHERITANCE_DEPTH` applies on the spine, restated
# here rather than imported: this module is the persistence layer and must not
# depend on a router. A cycle is refused when the edge is stored, so this is a
# backstop against data that predates that check.
_MAX_DEPTH = 32
