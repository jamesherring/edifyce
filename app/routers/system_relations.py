"""CRUD for the general edge between two formal systems.

R4's third piece (docs/system-relationships-roadmap.md §5.4). The tables and the
resolver landed first — `app/db/system_relations.py` and `related_layers` — and
every edge until now was written straight to its rows, which is fine for a test
and no use to an author.

**The path names the target.** An edge is `source → target`: theorems proved in
the source become citable in the target, so it is the target's proofs that gain
something to rest on and the target's owner who may say so. The source must be
**visible** — owned or published, since an ownerless imported corpus is the case
the whole feature exists for — and **published**, which is the rule a parent
follows and for the same reason: a system whose grammar can still move leaves
every target holding a verdict nobody would reach today.

**A published target may still be related**, and that is deliberate rather than
an oversight. Publishing freezes a system's *grammar*, so that proofs checked
against it stay checked against it; a system's **library** was never frozen —
`POST /proofs/{id}/promote` writes into a published system's library today. An
edge is library reach, not grammar, so it belongs on the same side of that line.
What it shares with promotion is the obligation that comes with it: changing what
a citation resolves to invalidates the verdicts reached through it
(:func:`~app.routers._invalidation.invalidate_library_reach`).

**A rename is checked here, and still checked at resolution time.** §9.17 named
the write as where the map's check belongs — an author gets
`translation_errors`' actual messages, rather than a citation that mysteriously
does not resolve — and that is what this does. It does *not* remove the check
`related_layers` makes on every verify: the systems either side may be drafts,
whose grammars move under an edge that was checked once. What is gained is the
report, not a saving.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user
from app.db import (
    FormalSystem,
    PromotedTheoremRow,
    SystemRelationExtraRow,
    SystemRelationObligationRow,
    SystemRelationRow,
    SystemRelationSortRow,
    SystemRelationSymbolRow,
    effective_spec,
    get_session,
)
from app.db.models import User
from app.db.systems import RuleRow
from app.routers._invalidation import invalidate_library_reach
from app.routers.systems import (
    draft_ancestor_errors,
    load_chain,
    load_system,
    owned_system_id_or_404,
    truncated_chain_errors,
)
from app.schemas import (
    SystemRelation,
    SystemRelationCreate,
    SystemRelationExtra,
    SystemRelationObligation,
    SystemRelationRename,
    SystemRelationUpdate,
)
from website.logical.declarative import DeclarativeError, build_spec
from website.logical.formal_system import FormalSystem as EngineSystem
from website.logical.translation import Translation, translation_errors
from website.logical.wrapping import StatementTemplate, template_errors

router = APIRouter(prefix="/formal-systems/{system_id}/relations", tags=["formal-systems"])


# The four child collections every read and every write touches. Async has no
# lazy load, so each has to be asked for.
_EDGE_LOADS = (
    selectinload(SystemRelationRow.sorts),
    selectinload(SystemRelationRow.symbols),
    selectinload(SystemRelationRow.extras),
    selectinload(SystemRelationRow.obligations),
    selectinload(SystemRelationRow.source_system),
)


@router.get("", response_model=list[SystemRelation])
async def list_relations(
    system_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[SystemRelation]:
    """Every edge **into** this system, in the order they resolve.

    Edges *out of* it are deliberately not listed here: they are a fact about
    other systems' libraries, and each is readable from the target that owns it.
    """
    await owned_system_id_or_404(session, system_id, user.id)
    edges = (
        await session.scalars(
            select(SystemRelationRow)
            .where(SystemRelationRow.target_system_id == system_id)
            .order_by(SystemRelationRow.position, SystemRelationRow.id)
            .options(*_EDGE_LOADS)
        )
    ).all()
    return [_serialise(edge) for edge in edges]


@router.post("", response_model=SystemRelation, status_code=status.HTTP_201_CREATED)
async def create_relation(
    system_id: uuid.UUID,
    payload: SystemRelationCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SystemRelation:
    await owned_system_id_or_404(session, system_id, user.id)
    await _require_relatable_source(session, payload.source_system_id, system_id, user.id)

    edge = SystemRelationRow(
        source_system_id=payload.source_system_id,
        target_system_id=system_id,
        kind=payload.kind,
        status=payload.status,
        statement_template=payload.statement_template or None,
        position=await _next_position(session, system_id),
    )
    await _assign(session, edge, system_id, payload.model_dump(exclude_unset=True), payload)
    session.add(edge)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        # The unique index on (source, target). Two systems relate at most one
        # way round per direction; the other direction is a second edge with its
        # own obligations, which is what the model says.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "These two systems are already related in that direction. Edit that "
            "edge instead.",
        ) from exc

    await _invalidate(session, edge)
    await session.commit()
    return _serialise(await _get_or_404(session, system_id, edge.id))


@router.patch("/{relation_id}", response_model=SystemRelation)
async def update_relation(
    system_id: uuid.UUID,
    relation_id: uuid.UUID,
    payload: SystemRelationUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SystemRelation:
    await owned_system_id_or_404(session, system_id, user.id)
    edge = await _get_or_404(session, system_id, relation_id)
    changes = payload.model_dump(exclude_unset=True)

    if payload.kind is not None:
        edge.kind = payload.kind
    if payload.status is not None:
        edge.status = payload.status
    if payload.position is not None:
        edge.position = payload.position
    if payload.statement_template is not None:
        # The empty string clears it; `None` means "leave it alone", as it does
        # for every other field of a partial edit.
        edge.statement_template = payload.statement_template or None
        if edge.statement_template is None and payload.extras is None:
            # Clearing the wrap clears what it introduced. The extras exist only
            # to appear in a template — `_require_a_composable_template` refuses
            # them without one — so leaving them behind would make the edit that
            # turns an edge off the one edit it refuses, which is precisely the
            # edit its author needs (§9.21, found in review). An explicit
            # `extras` in the same PATCH wins, and is then refused for saying
            # both things at once.
            await _clear(session, edge.extras)
    await _assign(session, edge, system_id, changes, payload)

    # Whatever changed, it changed what this edge resolves: `status` is the gate,
    # the obligations are what the gate reads, the maps decide whether the edge
    # checks out at all, and `position` decides which of two edges wins a shared
    # label. There is no field here that a verdict cannot rest on.
    await _invalidate(session, edge)
    await session.commit()
    return _serialise(await _get_or_404(session, system_id, relation_id))


@router.delete("/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relation(
    system_id: uuid.UUID,
    relation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await owned_system_id_or_404(session, system_id, user.id)
    edge = await _get_or_404(session, system_id, relation_id)

    # Before the delete, while the edge is still there to say what it reached.
    await _invalidate(session, edge)
    await session.execute(
        sa_delete(SystemRelationRow).where(SystemRelationRow.id == relation_id)
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Writing one edge
# ---------------------------------------------------------------------------


async def _assign(
    session: AsyncSession,
    edge: SystemRelationRow,
    system_id: uuid.UUID,
    changes: dict,
    payload: SystemRelationCreate | SystemRelationUpdate,
) -> None:
    """Apply the collections and check what the result claims.

    Each collection is replaced whole when it is given, which is the shape the
    parts router uses for a rule's bindings and antecedents: an edge's map is one
    statement rather than a set of independently editable rows.
    """
    _require_distinct_names(payload)

    if "sorts" in changes and payload.sorts is not None:
        await _clear(session, edge.sorts)
        edge.sorts = [
            SystemRelationSortRow(
                position=index, source_sort=entry.source, target_sort=entry.target
            )
            for index, entry in enumerate(payload.sorts)
        ]
    if "symbols" in changes and payload.symbols is not None:
        await _clear(session, edge.symbols)
        edge.symbols = [
            SystemRelationSymbolRow(
                position=index, source_symbol=entry.source, target_symbol=entry.target
            )
            for index, entry in enumerate(payload.symbols)
        ]
    if "extras" in changes and payload.extras is not None:
        await _clear(session, edge.extras)
        edge.extras = [
            SystemRelationExtraRow(position=index, name=entry.name, sort=entry.sort)
            for index, entry in enumerate(payload.extras)
        ]
    if "obligations" in changes and payload.obligations is not None:
        await _clear(session, edge.obligations)
        edge.obligations = [
            SystemRelationObligationRow(
                position=index,
                source_label=entry.source_label,
                discharged_by_primitive=entry.discharged_by_primitive,
                discharged_by_theorem_id=entry.discharged_by_theorem_id,
                status=entry.status,
            )
            for index, entry in enumerate(payload.obligations)
        ]

    # Unconditionally, not only when the obligations are what changed: a PATCH
    # that sets `status` alone is the other way an edge starts claiming to be
    # discharged, and the rows it would be discharged by are the stored ones.
    await _require_discharges_the_target_can_honour(session, system_id, edge)

    # Only when the map is what is being written. A grammar either side can move
    # after an edge is checked, and an edge that has stopped checking out is
    # exactly the one an author needs to edit — to turn it off, if nothing else.
    # Refusing every later PATCH would leave it stuck resolving nothing and
    # unable to say so. The resolution-time check is what keeps that safe (§9.21).
    if "sorts" in changes or "symbols" in changes:
        await _require_a_checkable_map(session, edge)

    # Same rule, for the same reason: checked when the wrap is what is being
    # written, never on a PATCH that only turns the edge off.
    if "statement_template" in changes or "extras" in changes:
        await _require_a_composable_template(session, edge)


def _require_distinct_names(
    payload: SystemRelationCreate | SystemRelationUpdate,
) -> None:
    """Refuse a collection that says two things about one name.

    Each of these tables carries a unique index on (edge, source name) — a map
    may say one thing about a name, and an obligation is one primitive — so a
    repeat is refused here rather than left to the index. Two reasons it cannot
    be left there: the constraint surfaces during autoflush, which escapes a
    PATCH as a 500 with a failed transaction; and on a create it is caught by
    the same ``except IntegrityError`` as the (source, target) index, which then
    reports "these two systems are already related" about an edge that does not
    exist (both found in review).
    """
    for field, names in (
        ("sorts", [entry.source for entry in payload.sorts or []]),
        ("symbols", [entry.source for entry in payload.symbols or []]),
        ("extras", [entry.name for entry in payload.extras or []]),
        ("obligations", [entry.source_label for entry in payload.obligations or []]),
    ):
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{field} names {', '.join(repr(name) for name in repeated)} more "
                "than once. An edge says one thing about each name.",
            )


async def _clear(session: AsyncSession, collection: list) -> None:
    """Empty one of the edge's collections, flushing the removals immediately.

    A unit of work issues its INSERTs before its DELETEs, so replacing a map with
    one that reuses a name would trip the unique index against rows already on
    their way out. This flush is what orders the two, and it is skipped when
    there is nothing to remove — which is every create.
    """
    if collection:
        collection.clear()
        await session.flush()


async def _require_discharges_the_target_can_honour(
    session: AsyncSession, system_id: uuid.UUID, edge: SystemRelationRow
) -> None:
    """What an obligation may point at, checked before it is believed.

    An obligation names **at most one** discharge — a primitive of the target or
    a theorem it has proved — because the two are different claims and a row
    asserting both says neither clearly.

    And whichever it names has to be something the **target can actually
    reach**. `related_layers` reads only whether the columns are *filled*, so an
    unreachable warrant passes the gate and the theorems transfer on it: a
    primitive naming a rule nothing declares discharges §2's obligation with a
    label, which is the one thing an obligation must not be (found in review —
    the theorem half was checked here from the start and the primitive half was
    not, which is the worse of the two to miss, since a label is easier to
    mistype than a UUID).

    Both are required to belong to the target's **own chain** rather than merely
    to exist. Something the target reaches *across another edge* would be
    circular in a way nothing here unpicks — edge A discharged by a theorem that
    is only citable because of edge B, and B by one citable because of A.
    """
    if edge.kind == "interpretation" and edge.status == "discharged" and not edge.obligations:
        # An interpretation translates the source's vocabulary, so each of its
        # primitives needs a theorem of this system standing in for it (§2). An
        # edge claiming to be discharged while naming *nothing* discharges the
        # whole of that with a status column, and `related_layers` — which asks
        # the obligations, not the author — sees an empty set and lets the
        # source's entire library across (found in review).
        #
        # What is *not* checked is whether the list is complete: see §9.22 for
        # what settling that needs.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "An interpretation edge discharges its source's primitives one by "
            "one, so it cannot be marked discharged with no obligations at all. "
            "Name them, or leave the edge a draft.",
        )

    both = [
        obligation.source_label
        for obligation in edge.obligations
        if obligation.discharged_by_primitive is not None
        and obligation.discharged_by_theorem_id is not None
    ]
    if both:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "An obligation is discharged by a primitive of this system *or* by a "
            "theorem it has proved, not both: "
            + ", ".join(repr(label) for label in both),
        )

    theorems = [
        obligation.discharged_by_theorem_id
        for obligation in edge.obligations
        if obligation.discharged_by_theorem_id is not None
    ]
    primitives = [
        obligation.discharged_by_primitive
        for obligation in edge.obligations
        if obligation.discharged_by_primitive is not None
    ]
    if not theorems and not primitives:
        return

    system = await load_system(session, system_id)
    chain = [layer.id for layer in await load_chain(session, system)]

    if theorems:
        reachable = set(
            await session.scalars(
                select(PromotedTheoremRow.id).where(
                    PromotedTheoremRow.id.in_(theorems),
                    PromotedTheoremRow.system_id.in_(chain),
                )
            )
        )
        missing = [entry for entry in theorems if entry not in reachable]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "An obligation names a theorem this system cannot cite: "
                + ", ".join(str(entry) for entry in missing)
                + ". A discharge must be a theorem of this system or one it "
                "inherits.",
            )

    if primitives:
        # A *rule*, specifically. `Proof.get_reference` tries `rule_by_label`
        # before the library, and it is the rules that are a system's primitives;
        # a theorem it has proved is the other column.
        declared = set(
            await session.scalars(
                select(RuleRow.label).where(
                    RuleRow.label.in_(primitives), RuleRow.system_id.in_(chain)
                )
            )
        )
        absent = sorted(set(primitives) - declared)
        if absent:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "An obligation names a primitive this system does not have: "
                + ", ".join(repr(label) for label in absent)
                + ". A discharge must be a rule of this system or one it "
                "inherits, or a theorem it has proved.",
            )


async def _require_a_checkable_map(
    session: AsyncSession, edge: SystemRelationRow
) -> None:
    """Refuse a rename that does not read the source's language into this one.

    §9.17's escape, taken: the check needs both grammars projected, and here
    there is a request to report it to. `translation_errors` is the same function
    `related_layers` calls on the citation path — this does not replace that one,
    because either system may be a draft whose grammar moves after the edge is
    written. It replaces the *silence*.

    A system that will not build is not a failed check but an unanswerable one,
    and it is reported as such: refusing with "the map narrows" would name the
    wrong problem.
    """
    translation = Translation(
        sorts={row.source_sort: row.target_sort for row in edge.sorts},
        symbols={row.source_symbol: row.target_symbol for row in edge.symbols},
    )
    if translation.identity:
        return

    source, source_error = await _build_effective(session, edge.source_system_id)
    target, target_error = await _build_effective(session, edge.target_system_id)
    unbuildable = source_error or target_error
    if unbuildable is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This map cannot be checked until both systems build: " + unbuildable,
        )

    errors = translation_errors(source, target, translation)
    if errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This map does not read the source's language into this system's. "
            + " ".join(errors),
        )


async def _require_a_composable_template(
    session: AsyncSession, edge: SystemRelationRow
) -> None:
    """Refuse a wrap that will not compose a statement of *this* system (S2).

    The same split `_require_a_checkable_map` is one half of, for the other thing
    an edge can carry. A template is read against the **target** alone — it says
    what shape this system states things in, and nothing about the source — so
    unlike a rename it needs one grammar rather than two.

    And, as with a rename, this does not replace the check `related_layers` makes
    on every verify: the target may be a draft whose grammar moves after the edge
    is written. It replaces the silence.
    """
    template = StatementTemplate(
        text=edge.statement_template or "",
        extras={row.name: row.sort for row in edge.extras},
    )
    if template.identity:
        if edge.extras:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "This edge declares template metavariables ("
                + ", ".join(repr(row.name) for row in edge.extras)
                + ") and no statement template for them to appear in.",
            )
        return

    target, unbuildable = await _build_effective(session, edge.target_system_id)
    if unbuildable is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This template cannot be checked until the system builds: " + unbuildable,
        )

    errors = template_errors(target, template)
    if errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This statement template does not restate a theorem in this system. "
            + " ".join(errors),
        )


async def _build_effective(
    session: AsyncSession, system_id: uuid.UUID
) -> tuple[EngineSystem | None, str | None]:
    """``(built system, None)`` or ``(None, why it did not build)``.

    The chain is refused on the same two grounds `load_effective` refuses one —
    truncated, or resting on a draft ancestor — rather than only on what
    `build_spec` says, so this cannot check a map against a system nobody could
    verify a proof in.
    """
    system = await load_system(session, system_id)
    if system is None:
        return None, f"system {system_id} not found"
    chain = await load_chain(session, system)
    refusals = truncated_chain_errors(chain) + draft_ancestor_errors(chain)
    if refusals:
        return None, f"{system.name}: " + "; ".join(refusals)
    try:
        spec = effective_spec(chain)
    except DeclarativeError as exc:
        return None, f"{system.name}: {exc}"
    built = build_spec(spec)
    if "errors" in built:
        return None, f"{system.name}: " + "; ".join(built["errors"])
    return built["system"], None


async def _invalidate(session: AsyncSession, edge: SystemRelationRow) -> None:
    """Clear the verdicts this edge's write could have made stale.

    The libraries in question are the source's **and its ancestors'** — an edge
    reaches the source's whole chain — so that is the set of systems whose
    theorems become (or stop being) citable here.
    """
    source = await load_system(session, edge.source_system_id)
    if source is None:
        return
    await invalidate_library_reach(
        session,
        edge.target_system_id,
        [layer.id for layer in await load_chain(session, source)],
    )


async def _next_position(session: AsyncSession, system_id: uuid.UUID) -> int:
    highest = await session.scalar(
        select(func.max(SystemRelationRow.position)).where(
            SystemRelationRow.target_system_id == system_id
        )
    )
    return 0 if highest is None else highest + 1


async def _require_relatable_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    """What the other end of an edge has to be.

    **Visible** — owned or published, the rule inheritance follows and for the
    same reason: the corpus this feature exists to build on is ownerless.

    Not **itself**, which is the one edge that can only be a mistake. The
    resolver tolerates a self-edge (it adds no layer, since the system's own
    library is layer zero already), so this refuses the writing of one rather
    than the reading — data that predates this route still loads.

    And **published**, on the same rule and for the same reason as a parent.
    This first said publication was *not* required, reasoning that a source's
    library is only cited and that an entry whose own system moved under it
    already fails closed (§9.12). That is wrong in the one way that matters, and
    review found it: failing closed happens on the *next* verify, while the
    proofs that already verified keep `valid`, `result` and their `proof_lines` —
    and a verify trusts a lemma's stored rows rather than re-checking them. A
    draft source repointed at a different parent, or edited at all, leaves every
    target holding a verdict nobody would reach today.

    The alternative was to wire every source mutation into relation
    invalidation — every part edit, every repoint. Freezing is what the spine
    already chose for exactly this problem, and one rule across both is worth
    more than the extra freedom: **you may build on a system once it is frozen.**
    """
    if source_id == target_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A system cannot be related to itself: its own library is already "
            "the first place a citation resolves.",
        )
    row = (
        await session.execute(
            select(FormalSystem.owner_id, FormalSystem.published_at).where(
                FormalSystem.id == source_id
            )
        )
    ).first()
    if row is None or (row.owner_id != owner_id and row.published_at is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"source_system_id {source_id} is not a system you can relate to.",
        )
    if row.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"source_system_id {source_id} is an unpublished draft. Publish it "
            "first: an edge may only reach a library whose system is frozen.",
        )


async def _get_or_404(
    session: AsyncSession, system_id: uuid.UUID, relation_id: uuid.UUID
) -> SystemRelationRow:
    edge = await session.scalar(
        select(SystemRelationRow)
        .where(
            SystemRelationRow.id == relation_id,
            # Scoped to the path's system, so an id from another target reads as
            # absent rather than as someone else's edge.
            SystemRelationRow.target_system_id == system_id,
        )
        .options(*_EDGE_LOADS)
    )
    if edge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relation not found.")
    return edge


def _serialise(edge: SystemRelationRow) -> SystemRelation:
    # `outstanding` mirrors `related_layers`' gate rather than restating it: an
    # obligation is outstanding when its own status says so *or* when it names
    # neither a primitive nor a theorem — the second being what a discharge that
    # vanished with its theorem leaves behind (R4a, from review).
    outstanding = sorted(
        obligation.source_label
        for obligation in edge.obligations
        if obligation.status != "discharged"
        or (
            obligation.discharged_by_primitive is None
            and obligation.discharged_by_theorem_id is None
        )
    )
    return SystemRelation(
        id=edge.id,
        source_system_id=edge.source_system_id,
        source_system_name=edge.source_system.name,
        target_system_id=edge.target_system_id,
        kind=edge.kind,
        status=edge.status,
        position=edge.position,
        statement_template=edge.statement_template,
        sorts=[
            SystemRelationRename(source=row.source_sort, target=row.target_sort)
            for row in edge.sorts
        ],
        symbols=[
            SystemRelationRename(source=row.source_symbol, target=row.target_symbol)
            for row in edge.symbols
        ],
        extras=[
            SystemRelationExtra(name=row.name, sort=row.sort) for row in edge.extras
        ],
        obligations=[
            SystemRelationObligation(
                id=row.id,
                source_label=row.source_label,
                discharged_by_primitive=row.discharged_by_primitive,
                discharged_by_theorem_id=row.discharged_by_theorem_id,
                status=row.status,
            )
            for row in edge.obligations
        ],
        resolves=edge.status == "discharged" and not outstanding,
        outstanding=outstanding,
    )
