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

**A renaming edge resolves nothing until its map checks out.** The sort and
symbol rows (R4b) say the target's language contains the source's under a
translation, and `website.logical.translation` is where that claim is tested —
over `Constructor.admits`, so a target that merely *spells* `wff` does not pass.
Failing it is the third way an edge transfers nothing, and it fails the same way
the other two do: silently, as a citation that does not resolve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import FormalSystem
from app.db.promoted_theorems_mapping import LibraryLayer
from app.db.system_relations import (
    SystemRelationObligationRow,
    SystemRelationRow,
)
from app.db.systems_mapping import system_to_spec
from website.logical.declarative import build_spec, layered_spec, library_digest
from website.logical.translation import Translation, translation_errors
from website.logical.wrapping import StatementTemplate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem

# Statuses that let a theorem across. A single-member tuple rather than a bare
# comparison so the gate reads the same here as it does in the model's own note.
_TRANSFERS = ("discharged",)


def related_layers(
    session: Session, chain: Sequence[FormalSystem], spec: SystemSpec
) -> list[LibraryLayer]:
    """The extra `LibraryChain` layers the edges into ``chain`` reach.

    ``chain`` is the citing system's inheritance chain, root first, and ``spec``
    what it builds to — what :func:`~app.db.systems_mapping.effective_library`
    returned for it. An edge into *any* system of that chain reaches the citing
    one, because an ancestor's library is already citable here and an edge
    extends that library.

    Each reached source contributes its **own** chain, so a theorem proved two
    layers below the source is citable across the edge exactly as it is below it.
    Deduplicated against the citing chain and against each other, first
    occurrence winning — a system reached twice is one layer at its nearest
    position, which is what `LibraryChain.rank` means.

    ``spec`` is read only by an edge that **renames**, and is why this takes one
    at all: checking a rename means projecting both grammars, so it needs the
    citing system *built* and not merely described (§3.2). That build is the
    price of a rename and is paid per verify — an edge with no map costs exactly
    what it did before R4b, which is nothing. The escape, when there is a route
    to hang it on, is to check the map once as the edge is written: it is a
    claim about two published grammars, and neither moves.
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
    layers: list[LibraryLayer] = []
    seen = set(reachable)
    transferring = [
        (edge, _translation(edge), _template(edge))
        for edge in edges
        if edge.id not in outstanding
    ]
    # Built once, and only if some edge renames — see this function's note. A
    # *template* needs no build here, and deliberately: it is carried
    # declaratively and composed at promotion, against the system the promotion
    # is using. A term built against any other instance of the same grammar
    # cannot unify with one built against that one, because sort admission
    # compares constructors by **identity** (`Constructor.admits`) and a build
    # projects its own. So the wrap is the citing system's to compose, exactly as
    # a stored term is the citing system's to rebuild (§3.1).
    target = (
        _built(spec)
        if any(not translation.identity for _edge, translation, _t in transferring)
        else None
    )
    for edge, translation, template in transferring:
        source = _source_layers(session, edge.source_system_id)
        if not translation.identity and not _translates(
            source.system, target, translation
        ):
            continue
        for system_id, digest in source.layers:
            if system_id in seen:
                continue
            seen.add(system_id)
            layers.append(
                LibraryLayer(system_id, digest, translation, template, related=True)
            )
    return layers


def _translation(edge: SystemRelationRow) -> Translation:
    """The edge's two maps, as the rename a transferred term is read through.

    Empty rows are the identity, which is what an edge between systems that agree
    on their vocabulary carries — so the common edge builds nothing and checks
    nothing.
    """
    return Translation(
        sorts={row.source_sort: row.target_sort for row in edge.sorts},
        symbols={row.source_symbol: row.target_symbol for row in edge.symbols},
    )


def _template(edge: SystemRelationRow) -> StatementTemplate:
    """The edge's wrap, as the shape a transferred statement is restated in.

    A NULL template is no wrap, which is what every edge between two systems that
    agree about what a judgement is carries — so the ordinary edge builds nothing
    and composes nothing, on the same contract the empty rename tables have.
    """
    return StatementTemplate(
        text=edge.statement_template or "",
        extras={row.name: row.sort for row in edge.extras},
    )


def _translates(
    source: EngineSystem | None,
    target: EngineSystem | None,
    translation: Translation,
) -> bool:
    # Whether the edge's map reads the source's language into the target's.
    # Either system failing to build is a map that cannot be checked rather than
    # one that is wrong, and unverifiable fails closed here as everywhere else.
    #
    # Silent, like every other way an edge transfers nothing: what the author
    # sees is the citation failing to resolve, and the reasons themselves are
    # `translation_errors`', which a route can report once there is one to report
    # them from.
    if source is None or target is None:
        return False
    return not translation_errors(source, target, translation)


def _built(spec: SystemSpec) -> EngineSystem | None:
    # None for a spec that does not build; see `_translates` for what that means.
    built = build_spec(spec)
    return None if "errors" in built else built["system"]


def _edges_with_outstanding_obligations(
    session: Session, edge_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    # An edge is only as discharged as its obligations. Read separately from the
    # edge's own `status` so a stale column fails closed: the rule §2 states is
    # about the primitives, and this is the query that asks the primitives.
    #
    # Outstanding two ways, and the second is the one a status column cannot
    # see. An obligation discharged by a *theorem* loses it to `ON DELETE SET
    # NULL` when that theorem is retired, and nothing writes back to the
    # obligation's own status — so an obligation naming neither a primitive nor a
    # theorem is outstanding whatever it says about itself. (Found in review:
    # this module's model already claimed a NULL "leaves the obligation
    # undischarged", and only the column was doing that, not the query.)
    return set(
        session.scalars(
            select(SystemRelationObligationRow.relation_id).where(
                SystemRelationObligationRow.relation_id.in_(edge_ids),
                or_(
                    SystemRelationObligationRow.status.notin_(_TRANSFERS),
                    and_(
                        SystemRelationObligationRow.discharged_by_primitive.is_(None),
                        SystemRelationObligationRow.discharged_by_theorem_id.is_(None),
                    ),
                ),
            )
        )
    )


@dataclass(frozen=True)
class _Source:
    """What one edge's source contributes: its chain's layers, and its grammar.

    ``system`` is built **lazily**, because only a renaming edge needs it and a
    build is the expensive half of reading a system at all. ``layers`` is what
    every edge needs and is computed either way.
    """

    layers: list[tuple[uuid.UUID, str]]
    spec: SystemSpec | None

    @cached_property
    def system(self) -> EngineSystem | None:
        return None if self.spec is None else _built(self.spec)


def _source_layers(session: Session, source_id: uuid.UUID) -> _Source:
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
        return _Source([], None)

    specs = [system_to_spec(system) for system in chain]
    return _Source(
        [
            (system.id, library_digest(layered_spec(specs[: index + 1])))
            for index, system in reversed(list(enumerate(chain)))
        ],
        # The source's *whole* chain: a rename is checked against the grammar the
        # source actually has, which for a layer of a tower is its ancestors' in
        # front of its own.
        layered_spec(specs),
    )


# The same bound `systems.MAX_INHERITANCE_DEPTH` applies on the spine, restated
# here rather than imported: this module is the persistence layer and must not
# depend on a router. A cycle is refused when the edge is stored, so this is a
# backstop against data that predates that check.
_MAX_DEPTH = 32
