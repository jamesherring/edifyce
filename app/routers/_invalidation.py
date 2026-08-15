"""What a change to *what a citation resolves to* has to reach.

A verdict is only as good as what it rested on, and a verify now **trusts** a
lemma's stored rows rather than re-checking them
(``docs/verification-from-rows.md``) — so anything that changes what a label
names has to go back and clear the verdicts that were reached through it, or a
third proof will rest on a check nobody would reach today.

Three things do that, and this module is what they share. Promoting a theorem
makes a label resolve to something *nearer* than it did; retiring one makes it
resolve to nothing; and **relating two systems** (`system_relations`) makes a
whole library resolve where it did not — or, on a delete, stop. The roadmap's
§9.15 states the rule the first two taught and §9.19 the generalisation: *any*
new way for a label to resolve is a new way for a verdict to go stale.

Model-aware, unlike :mod:`app.routers._common`, which is deliberately not — that
is why this is its own module rather than an addition there.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy import update as sa_update

from app.db import (
    FormalSystem,
    PromotedTheoremRow,
    SystemRelationObligationRow,
    SystemRelationRow,
)
from app.db.models import Proof, ProofReference
from app.db.proof_lines import ProofLineRow
from app.db.proofs_mapping import clear_proof_lines
from app.db.systems import RuleRow
from app.routers._common import lock_system

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


async def citing_systems(
    session: AsyncSession, system_id: uuid.UUID, label: str | None
) -> list[uuid.UUID]:
    """Every system whose proofs may resolve ``label`` to ``system_id``'s entry.

    That system, plus the ones inheriting from it transitively — a citation
    resolves against a system's own library and then its ancestors' (`R2`), so a
    descendant's proof can rest on an entry stored here — and the ones a
    discharged relation edge reaches, which is the same reach by the other
    mechanism (R4a).

    The walk stops at a system that claims ``label`` **itself**: what it declares
    is nearer, so neither it nor anything below it was ever reaching ours.
    Following the resolver's own shadowing rule is what keeps this from
    invalidating proofs that never depended on the entry in question.

    Claiming it means *either* a library entry of that label or an **inference
    rule** of it — `Proof.get_reference` tries `rule_by_label` before the
    library, so a descendant's rule shadows an ancestor's theorem just as
    thoroughly as a nearer theorem would. Missing that half is the difference
    between invalidating a subtree and invalidating the right one.

    ``label`` is ``None`` for a caller whose change is about a **library** rather
    than a name — relating two systems makes every entry of one resolve in the
    other, and there is no one label to be shadowed. The walk then stops
    nowhere, which over-reaches by exactly the systems that shadow whichever
    labels were involved. That is the safe direction and the one R4a already
    took for the edge half of this walk: invalidation may reach further than
    resolution, never less, and the cost of the difference is a re-verify.

    Returned **ancestor-first, and by id within a generation**, which is the
    order the caller then locks in; see :func:`invalidate_citations` for why it
    has to be that and not simply sorted.
    """
    reached = [system_id]
    frontier = [system_id]
    while frontier:
        # Both ways a library reaches further: down the spine, and across a
        # discharged relation edge. Found in review — R4a widened where a
        # citation may resolve without widening this, so a sibling target kept a
        # verdict resting on a theorem it could no longer reach. Reach and
        # invalidation are one question asked twice and have to agree.
        children = sorted(
            set(
                await session.scalars(
                    select(FormalSystem.id).where(
                        FormalSystem.inherits_from_id.in_(frontier)
                    )
                )
            )
            | set(
                await session.scalars(
                    select(SystemRelationRow.target_system_id).where(
                        SystemRelationRow.source_system_id.in_(frontier),
                        SystemRelationRow.status == "discharged",
                    )
                )
            )
        )
        if not children:
            break
        shadowing = (
            set()
            if label is None
            else set(
                await session.scalars(
                    select(PromotedTheoremRow.system_id).where(
                        PromotedTheoremRow.system_id.in_(children),
                        PromotedTheoremRow.label == label,
                    )
                )
            )
            | set(
                await session.scalars(
                    select(RuleRow.system_id).where(
                        RuleRow.system_id.in_(children), RuleRow.label == label
                    )
                )
            )
        )
        # Sorted, because the query's row order is not defined and the caller
        # locks in exactly this order — two operations that met a generation in
        # different orders would be two lock orders.
        frontier = sorted(
            child
            for child in children
            if child not in shadowing and child not in reached
        )
        reached.extend(frontier)
    return reached


async def invalidate_citations(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> None:
    """Invalidate every proof whose verdict rests on what ``label`` resolved to
    in ``system_id``, so changing what it names cannot leave a standing verdict
    behind it.

    Both directions need this, and for one reason. **Retiring** an entry makes
    the label resolve to nothing; **promoting** one makes it resolve to something
    nearer than it did. Either way a proof that already verified against the old
    answer is now recording a check nobody would reach today.

    Which proofs cited it is a question the stored structure answers: a citation
    of a promoted theorem resolves to an ephemeral rule carrying the theorem's
    label, and `proof_lines.rule` records the rule that justified each line. So
    this reads the rows rather than re-parsing any source — and then follows the
    reference graph out from them, because a citer is itself citable and a proof
    resting on one rests on the entry at one remove.

    Takes the system lock for every system it touches, and the **order matters**,
    because this is the first caller to hold more than one. It is *not* sorted by
    id, which was the first answer here and was wrong: every caller reaches this
    already holding ``system_id``'s lock — a verify takes it before reading
    anything, and an invalidation before writing — so sorting by id can put a
    descendant's key ahead of one already held. Two operations at different
    levels of one tower then acquire in opposite orders and Postgres aborts one
    of them (found in review).

    The order is **(depth, id)**, which `citing_systems` returns: a system's
    depth in the tower is a property of the tower rather than of who is asking,
    so any two operations order any two systems they share identically — which is
    what a global lock order means. And it makes the pre-held key the *first*
    one, since ``system_id`` is the unique shallowest member of its own subtree.
    Inheritance is single-parent, so two subtrees are nested or disjoint and
    there is no third case to worry about.
    """
    systems = await citing_systems(session, system_id, label)
    await _lock_all(session, systems)

    citing = list(
        await session.scalars(
            select(Proof.id)
            .join(ProofLineRow, ProofLineRow.proof_id == Proof.id)
            .where(
                Proof.formal_system_id.in_(systems),
                ProofLineRow.rule == label,
            )
            .distinct()
        )
    )
    if not citing:
        return
    # A dependent lives in the same system as the proof it cites, and that system
    # is one of the ones just locked — so the closure needs no further locking.
    await clear_verdicts(session, citing + await dependent_closure(session, citing))


async def invalidate_library_reach(
    session: AsyncSession,
    target_id: uuid.UUID,
    source_ids: Sequence[uuid.UUID],
) -> None:
    """The same, for an **edge** rather than a label: what a whole library reaches.

    Writing, discharging, re-ordering or deleting a `system_relations` row
    changes which labels resolve in ``target_id`` and everything below it, and
    every one of those is a way a standing verdict can go stale. Creating one is
    included deliberately, though adding a resolution cannot make a *failing*
    proof's cached verdict wrong: two edges can offer the same label, and which
    of them wins is decided by `position`, so an edge arriving ahead of another
    silently redirects a citation that already resolved.

    ``source_ids`` is the source system **and its ancestors** — an edge reaches
    the source's whole chain (R4a), so those are the libraries that become
    citable. The proofs are narrowed to the ones actually citing a label one of
    them provides, which is a join rather than an ``IN`` list of every label: an
    imported corpus has tens of thousands, and the labels are not the ask.

    Not narrowed by *shadowing*, which `citing_systems` explains: a whole library
    has no one label to be shadowed, so the walk over-reaches by the systems that
    declare some of these names themselves. The cost of that is a re-verify.
    """
    systems = await citing_systems(session, target_id, None)
    await _lock_all(session, systems)

    citing = list(
        await session.scalars(
            select(Proof.id)
            .join(ProofLineRow, ProofLineRow.proof_id == Proof.id)
            .join(PromotedTheoremRow, PromotedTheoremRow.label == ProofLineRow.rule)
            .where(
                Proof.formal_system_id.in_(systems),
                PromotedTheoremRow.system_id.in_(list(source_ids)),
            )
            .distinct()
        )
    )
    if not citing:
        return
    await clear_verdicts(session, citing + await dependent_closure(session, citing))


async def invalidate_warranted_edges(
    session: AsyncSession, theorem_id: uuid.UUID
) -> None:
    """Clear what resolved across every edge ``theorem_id`` was discharging.

    An obligation may be discharged by a theorem the target proved (§5.4), and
    the FK is ``ON DELETE SET NULL`` — so retiring that theorem leaves an
    obligation naming neither a primitive nor a theorem, which `related_layers`
    reads as outstanding, which stops the edge resolving. The proofs that
    resolved *across* it cited the **source's** labels rather than the warrant's,
    so the label walk that retires the theorem never reaches them.

    Called from the retirement path rather than from the relations router,
    because this is a way an edge stops resolving that nothing in that router
    ever sees — the same shape as deleting an edge's source
    (`systems.delete_system`).

    Targets in id order, so two retirements touching one pair of towers acquire
    their locks the same way round.
    """
    edges = (
        await session.execute(
            select(
                SystemRelationRow.target_system_id, SystemRelationRow.source_system_id
            )
            .join(
                SystemRelationObligationRow,
                SystemRelationObligationRow.relation_id == SystemRelationRow.id,
            )
            .where(SystemRelationObligationRow.discharged_by_theorem_id == theorem_id)
            .distinct()
        )
    ).all()
    for target_id, source_id in sorted(edges):
        await invalidate_library_reach(
            session, target_id, await _own_chain(session, source_id)
        )


async def _own_chain(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID]:
    # A system and its ancestors, root-last — the libraries an edge from it
    # reaches. Read here rather than through `systems.load_chain` because that
    # loads a whole aggregate this needs no part of, and importing it would point
    # this module at a router.
    chain: list[uuid.UUID] = []
    current: uuid.UUID | None = system_id
    while current is not None and current not in chain and len(chain) <= _MAX_DEPTH:
        chain.append(current)
        current = await session.scalar(
            select(FormalSystem.inherits_from_id).where(FormalSystem.id == current)
        )
    return chain


# The bound `systems.MAX_INHERITANCE_DEPTH` enforces when a chain is written,
# restated rather than imported for the reason `_own_chain` gives.
_MAX_DEPTH = 32


async def _lock_all(session: AsyncSession, systems: Sequence[uuid.UUID]) -> None:
    # In the order `citing_systems` returned them; see `invalidate_citations`.
    for locked in systems:
        await lock_system(session, locked)


async def dependent_closure(
    session: AsyncSession, proof_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Every proof that transitively references one of ``proof_ids``, excluding
    the roots themselves.

    Shared by the things that invalidate: a lemma changing under its dependents,
    a library entry being withdrawn from under the proofs that cited it, and an
    edge changing what a whole library reaches. The last two reach here because a
    citer is itself citable — a proof that rests on the citer would otherwise keep
    a verdict that rests, one hop further back, on a theorem that is gone.
    """
    roots = set(proof_ids)
    reached: set[uuid.UUID] = set()
    frontier = list(proof_ids)
    while frontier:
        rows = (
            await session.scalars(
                select(ProofReference.proof_id).where(
                    ProofReference.references_id.in_(frontier)
                )
            )
        ).all()
        frontier = [pid for pid in rows if pid not in reached]
        reached.update(frontier)
    return [pid for pid in reached if pid not in roots]


async def clear_verdicts(
    session: AsyncSession, proof_ids: Sequence[uuid.UUID]
) -> None:
    """Drop the cached verdict and the stored structure of each proof.

    The pair is one artefact of one check (``proofs._discard_check``), so they go
    together wherever a check stops meaning anything.
    """
    ids = list(proof_ids)
    if not ids:
        return
    await session.execute(
        sa_update(Proof).where(Proof.id.in_(ids)).values(valid=None, result=None)
    )
    await session.run_sync(lambda sync: clear_proof_lines(sync, ids))
