"""CRUD for formal systems, owner-scoped.

Systems are stored as normalised rows (`app/db/systems.py`); this router is the
thin HTTP layer over them. Reads assemble the full aggregate; `validate`
rebuilds a `SystemSpec` and hands it to the engine (`declarative.build_spec`) —
no compile logic lives here.

A system's rows are its **own** parts, but what it is *built* from is its
inheritance chain: `load_effective` walks `inherits_from_id` and hands
`app.db.effective_spec` the ancestors, root first. Every path that builds a
system goes through it, here and in `app/routers/proofs.py`.

This phase covers **system-level** writes (create / update / delete) plus read
and validate. Editing the component parts (productions, definitions, rules, …)
is a later phase; the read models already expose each part's `id` so that layer
can address them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import current_active_user, current_active_user_optional
from app.db import (
    Base,
    FormalSystem,
    chain_libraries,
    discard_system_checks,
    effective_spec,
    get_session,
    inherited_rule_count,
    system_to_spec,
)
from app.routers._common import (
    PageParams,
    lock_system,
    page_params,
    paginate_summaries,
    unique_slug,
)
from app.db.models import User
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import (
    definition_provisos_list,
    rule_side_conditions_list,
)
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LineRow,
    ProductionBindingRow,
    ProductionBindingScopeRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.schemas import (
    Axiom,
    DefinitionBinder,
    DefinitionBinders,
    Binding,
    BracketPair,
    Definition,
    FormalSystemCreate,
    FormalSystemDetail,
    FormalSystemSummary,
    FormalSystemUpdate,
    Justification,
    LinePart,
    LineType,
    Page,
    Production,
    ProductionBinding,
    ProofVerifyRequest,
    Rule,
    Sort,
    Subproof,
    SystemOwner,
    SystemValidation,
    VerifyProofResponse,
)
from app.db.promoted_theorems_mapping import LibraryChain
from website.logical.declarative import DeclarativeError, SystemSpec, build_spec

router = APIRouter(prefix="/formal-systems", tags=["formal-systems"])


# The child collections `system_to_spec` and the detail serializer touch. Async
# has no lazy load, so every one must be eagerly fetched. `owner` is here too so
# the summary/detail serializers can name the author without a lazy load.
_CHILD_LOADS = (
    selectinload(FormalSystem.owner),
    selectinload(FormalSystem.brackets),
    selectinload(FormalSystem.symbols).selectinload(SymbolRow.union),
    selectinload(FormalSystem.symbols)
    .selectinload(SymbolRow.bindings)
    .selectinload(ProductionBindingRow.symbol),
    selectinload(FormalSystem.symbols)
    .selectinload(SymbolRow.bindings)
    .selectinload(ProductionBindingRow.scopes)
    .selectinload(ProductionBindingScopeRow.scoped),
    selectinload(FormalSystem.lines).selectinload(LineRow.parts),
    selectinload(FormalSystem.lines).selectinload(LineRow.logical_symbol),
    selectinload(FormalSystem.definitions).selectinload(DefinitionRow.symbol),
    selectinload(FormalSystem.definitions)
    .selectinload(DefinitionRow.bindings)
    .selectinload(DefinitionBindingRow.symbol),
    selectinload(FormalSystem.definitions)
    .selectinload(DefinitionRow.fresh)
    .selectinload(DefinitionFreshRow.symbol),
    # The proviso tree (flat) + each node's sort reference, for
    # definition_provisos_list on the async read path.
    selectinload(FormalSystem.definitions)
    .selectinload(DefinitionRow.side_conditions)
    .selectinload(SideConditionRow.sort_symbol),
    selectinload(FormalSystem.axioms)
    .selectinload(AxiomRow.bindings)
    .selectinload(AxiomBindingRow.symbol),
    selectinload(FormalSystem.rules).selectinload(RuleRow.antecedents),
    selectinload(FormalSystem.rules)
    .selectinload(RuleRow.bindings)
    .selectinload(RuleBindingRow.symbol),
    # The rule's proviso tree (flat) + each node's sort reference, for
    # rule_side_conditions_list on the async read path.
    selectinload(FormalSystem.rules)
    .selectinload(RuleRow.side_conditions)
    .selectinload(SideConditionRow.sort_symbol),
)


async def _unique_slug(
    session: AsyncSession, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> str:
    # Slugs are unique per owner; disambiguate collisions with a numeric suffix.
    async def _taken(slug: str) -> bool:
        stmt = select(FormalSystem.id).where(
            FormalSystem.owner_id == owner_id, FormalSystem.slug == slug
        )
        if exclude_id is not None:
            stmt = stmt.where(FormalSystem.id != exclude_id)
        return await session.scalar(stmt) is not None

    return await unique_slug(name, _taken, fallback="system")


async def _load_owned(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> FormalSystem | None:
    stmt = (
        select(FormalSystem)
        .where(FormalSystem.id == system_id, FormalSystem.owner_id == owner_id)
        .options(*_CHILD_LOADS)
    )
    return await session.scalar(stmt)


async def _get_owned_or_404(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> FormalSystem:
    system = await _load_owned(session, system_id, owner_id)
    if system is None:
        # 404 (not 403) for another owner's id, so ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return system


async def load_system(session: AsyncSession, system_id: uuid.UUID) -> FormalSystem | None:
    stmt = select(FormalSystem).where(FormalSystem.id == system_id).options(*_CHILD_LOADS)
    return await session.scalar(stmt)


# How deep a chain may be. Enforced when an edge is *written*
# (`_require_inheritable_reference`), so a legal chain is always walkable; the
# bound is repeated in the walk so a row that got past that — a hand edit, or an
# ancestor repointed under a descendant — terminates rather than hanging a
# request.
MAX_INHERITANCE_DEPTH = 32


async def load_chain(session: AsyncSession, system: FormalSystem) -> list[FormalSystem]:
    """``system`` and its ancestors, **root first** — `effective_spec`'s argument.

    Stops early on a chain that should not exist: a missing parent (the FK is
    ``SET NULL``, but a concurrent delete can be read either way), a cycle, or
    one past ``MAX_INHERITANCE_DEPTH``. The caller can tell, because the chain
    it gets back still declares a parent it does not contain — and must refuse
    to build it (`truncated_chain_errors`). Building the prefix would be
    building a *different system* from the one the rows declare, quietly: an
    intermediate layer that adds only definitions would still compile with the
    root's grammar missing.
    """
    chain = [system]
    seen = {system.id}
    while chain[0].inherits_from_id is not None and len(chain) < MAX_INHERITANCE_DEPTH:
        parent = await load_system(session, chain[0].inherits_from_id)
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        chain.insert(0, parent)
    return chain


def truncated_chain_errors(chain: Sequence[FormalSystem]) -> list[str]:
    """Refuse a chain :func:`load_chain` could not walk to the top.

    The root of what came back still names a parent, so an ancestor is missing:
    deleted under us, part of a cycle, or past the depth bound. Every one of
    those means the rows declare a system this is not.
    """
    if chain[0].inherits_from_id is None:
        return []
    return [
        f"This system inherits from {chain[0].inherits_from_id}, which could not "
        "be loaded: it no longer exists, the chain cycles, or it is more than "
        f"{MAX_INHERITANCE_DEPTH} systems deep. A system is built from its whole "
        "chain, so it cannot be built from part of one."
    ]


def draft_ancestor_errors(chain: Sequence[FormalSystem]) -> list[str]:
    """Refuse to build on an ancestor that is still a draft.

    Publishing freezes a system, and that freeze is what a descendant rests on:
    a parent edit changes the grammar every proof beneath it was checked against,
    and the parts routes only ever invalidate the *edited* system's proofs. With
    the parent frozen there is nothing to cascade, so this rule is what keeps a
    stale-but-believed proof snapshot out of the schema.

    Enforced when a chain is written too (`_require_inheritable_reference`), so
    this reaches only a row that predates the rule or a parent unpublished by
    some other route. Returned as build errors rather than raised, because every
    caller here is already reporting a system that does not build.
    """
    drafts = [system.name for system in chain[:-1] if system.published_at is None]
    if not drafts:
        return []
    return [
        "This system inherits from "
        + ", ".join(repr(name) for name in drafts)
        + ", which is not published. A system may only build on a published "
        "parent, because publishing is what freezes the grammar its proofs were "
        "checked against."
    ]


def _is_readable(system: FormalSystem, user: User | None) -> bool:
    # Published systems are public; drafts are visible only to their owner.
    if system.published_at is not None:
        return True
    return user is not None and system.owner_id == user.id


async def _get_readable_or_404(
    session: AsyncSession, system_id: uuid.UUID, user: User | None
) -> FormalSystem:
    system = await load_system(session, system_id)
    if system is None or not _is_readable(system, user):
        # 404 (not 403) for a draft you don't own, so unpublished ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return system


async def owned_system_id_or_404(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> uuid.UUID:
    """Assert the system exists and is owned, without loading it. 404 otherwise.

    Shared with the child-CRUD router so a child write can scope to an owned
    parent with a single cheap query.
    """
    owned = await session.scalar(
        select(FormalSystem.id).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == owner_id
        )
    )
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    return owned


@dataclass(frozen=True)
class EffectiveSystem:
    """A stored system resolved against its inheritance chain, ready to build.

    ``spec`` is ``None`` exactly when ``errors`` is non-empty. Both routers take
    this shape because both already report a system that does not build as
    errors rather than as an exception.
    """

    chain: list[FormalSystem]
    spec: SystemSpec | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def rule_offset(self) -> int:
        """How many of ``spec.rules`` an ancestor contributed; see `schema_terms`."""
        return inherited_rule_count(self.chain)

    @property
    def library(self) -> LibraryChain:
        """Where a citation resolves, nearest first — this system, then upward.

        A system's citable library is its own entries and its ancestors', which
        is what makes a theorem proved low in a tower usable high in it. Each
        layer carries its own digest; see :class:`LibraryChain` for why an
        ancestor's stored terms are guarded by the ancestor's.
        """
        return LibraryChain(tuple(reversed(chain_libraries(self.chain))))


async def load_effective(
    session: AsyncSession, system: FormalSystem
) -> EffectiveSystem:
    """Resolve ``system`` against its ancestors, or say why it cannot be."""
    chain = await load_chain(session, system)
    errors = truncated_chain_errors(chain) + draft_ancestor_errors(chain)
    if errors:
        return EffectiveSystem(chain, errors=errors)
    try:
        return EffectiveSystem(chain, spec=effective_spec(chain))
    except DeclarativeError as exc:
        # A cross-layer collision. The chain describes no system at all, so this
        # is the same kind of failure as a spec that will not build, reported the
        # same way.
        return EffectiveSystem(chain, errors=[str(exc)])


async def _require_inheritable_reference(
    session: AsyncSession,
    parent_id: uuid.UUID,
    owner_id: uuid.UUID,
    child_id: uuid.UUID | None = None,
) -> None:
    """The three things a parent must be, checked before the edge is stored.

    **Visible** — owned, or published. Owned-only was the rule while inheritance
    resolved to nothing; it would now lock every user out of building on an
    imported corpus, which is ownerless by construction.

    **Published** — see :func:`draft_ancestor_errors` for why the freeze is
    load-bearing rather than tidy.

    **Not already below the child** — the guard this replaces caught only
    ``parent == child``, so a two-step cycle went through and every walk over a
    chain had to be written to survive one.

    And **shallow enough**: the depth bound belongs here, where a chain is made,
    rather than only in the walk that reads one. Enforced only at the write, a
    chain past it would be legal to build and impossible to load whole.
    """
    row = (
        await session.execute(
            select(FormalSystem.owner_id, FormalSystem.published_at).where(
                FormalSystem.id == parent_id
            )
        )
    ).first()
    if row is None or (row.owner_id != owner_id and row.published_at is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"inherits_from_id {parent_id} is not a system you can build on.",
        )
    if row.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"inherits_from_id {parent_id} is an unpublished draft. Publish it "
            "first: a system may only build on a parent whose grammar is frozen.",
        )
    if child_id is not None and await _inherits_from(session, parent_id, child_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That would make the inheritance chain cycle.",
        )
    if await _chain_depth(session, parent_id) >= MAX_INHERITANCE_DEPTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"An inheritance chain may be at most {MAX_INHERITANCE_DEPTH} systems "
            "deep, and this one already is.",
        )


async def _chain_depth(session: AsyncSession, system_id: uuid.UUID) -> int:
    # How many systems `system_id` and its ancestors make. Bounded by the same
    # limit it is used to enforce, so a pre-existing over-deep chain terminates.
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = system_id
    while current is not None and current not in seen and len(seen) <= MAX_INHERITANCE_DEPTH:
        seen.add(current)
        current = await session.scalar(
            select(FormalSystem.inherits_from_id).where(FormalSystem.id == current)
        )
    return len(seen)


async def _inherits_from(
    session: AsyncSession, start_id: uuid.UUID, ancestor_id: uuid.UUID
) -> bool:
    # Whether `ancestor_id` is at or above `start_id`. Walked one row at a time
    # rather than with a recursive CTE: a chain is a handful of systems deep, and
    # this runs once per write.
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = start_id
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = await session.scalar(
            select(FormalSystem.inherits_from_id).where(FormalSystem.id == current)
        )
    return False


async def _require_publishable(session: AsyncSession, system: FormalSystem) -> None:
    """Reject a publish that would expose a broken or dangling public system.

    Two things a published system must not do, since it becomes world-readable:
    it must compile — against its whole chain, which is what it is actually built
    from — and if it inherits from another system that parent must itself be
    public. A published child exposes `inherits_from_id`, and `GET /{parent}`
    404s for anonymous viewers when the parent is a private draft.
    """
    effective = await load_effective(session, system)
    if effective.errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=effective.errors
        )
    result = build_spec(effective.spec)
    if "errors" in result:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["errors"])

    if system.inherits_from_id is not None:
        parent_published_at = await session.scalar(
            select(FormalSystem.published_at).where(FormalSystem.id == system.inherits_from_id)
        )
        if parent_published_at is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot publish a system that inherits from an unpublished draft; "
                "publish the parent system first.",
            )


async def require_editable_system(
    session: AsyncSession, system_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    """Assert the system is owned *and* still a draft; the guard for every edit.

    A published system is **frozen**: its compiled behaviour is exactly what its
    published proofs were verified against, so any part edit (child-CRUD router)
    or system-level edit could silently invalidate them. Publishing is therefore
    a one-way door — unpublishing is refused too (see `update_system`) — and
    editing a published system is a 409. 404 (not 409) when it isn't owned, so
    ids don't leak. Shared with the child-CRUD router.

    NOTE: this closes the *sequential* hole (an edit after a system is published
    is rejected), not a *concurrent* one. An owner who publishes and edits a part
    in overlapping transactions can read ``published_at`` as still-NULL here,
    admit the edit, and commit it after the publish commits — landing a change on
    a now-published system. Closing that means serializing publication against
    part writes (a ``SELECT ... FOR UPDATE`` lock on the parent row in both this
    guard and the publish path). It's deferred: the window needs one owner racing
    a publish and an edit on the same system, and the lock is Postgres-only
    behaviour the SQLite test suite can't exercise — so it belongs with
    deliberate concurrency hardening, tested against Postgres.
    """
    row = (
        await session.execute(
            select(FormalSystem.published_at).where(
                FormalSystem.id == system_id, FormalSystem.owner_id == owner_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    if row.published_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This system is published and can no longer be edited. Publishing is "
            "final so that proofs verified against the system stay valid.",
        )


def _owner_out(system: FormalSystem) -> SystemOwner | None:
    if system.owner is None:
        return None
    return SystemOwner(id=system.owner.id, display_name=system.owner.display_name)


def _summary(system: FormalSystem) -> FormalSystemSummary:
    return FormalSystemSummary(
        id=system.id,
        name=system.name,
        slug=system.slug,
        description=system.description,
        inherits_from_id=system.inherits_from_id,
        published_at=system.published_at,
        created_at=system.created_at,
        updated_at=system.updated_at,
        owner=_owner_out(system),
    )


# Per-child serializers (row -> read schema). Shared with the child-CRUD router
# (app/routers/system_parts.py), which returns individual objects.


def _bindings_out(rows: Sequence[Base]) -> list[Binding]:
    # A binding references a symbol by FK; its `sort` in the API is that symbol's
    # name (a sort or a production).
    return [Binding(var=b.var, sort=b.symbol.name) for b in rows]


def bracket_out(b: BracketRow) -> BracketPair:
    return BracketPair(id=b.id, opening=b.opening, closing=b.closing)


def sort_out(s: SymbolRow) -> Sort:
    return Sort(id=s.id, name=s.name)


def production_out(p: SymbolRow) -> Production:
    return Production(
        id=p.id,
        name=p.name,
        sort=p.union.name,
        kind=p.kind,
        template=p.template,
        regex=p.regex,
        atom_value=p.atom_value,
        atom_base=p.atom_base,
        denotes_constant=p.denotes_constant,
        bindings=[
            ProductionBinding(
                var=b.var,
                sort=b.symbol.name,
                scopes_over=[s.scoped.var for s in b.scopes],
            )
            for b in p.bindings
        ],
    )


def line_out(line: LineRow) -> LineType:
    return LineType(
        id=line.id,
        name=line.name,
        shape=line.shape,
        logical_sort=line.logical_symbol.name if line.logical_symbol is not None else None,
        scope=line.scope,
        behaviour=line.behaviour,
        parts=[LinePart(id=pt.id, name=pt.name, regex=pt.regex) for pt in line.parts],
    )


def definition_out(d: DefinitionRow) -> Definition:
    return Definition(
        id=d.id,
        sort=d.symbol.name,
        name=d.name,
        higher=d.higher,
        lower=d.lower,
        provisos=definition_provisos_list(d),
        bindings=_bindings_out(d.bindings),
        fresh=_bindings_out(d.fresh),
        label=d.label,
        # Both columns are written together, so the label alone decides whether
        # there is an obligation (see `app.db.systems.DefinitionRow`).
        justification=(
            Justification(label=d.justification_label, statement=d.justification_statement or "")
            if d.justification_label is not None
            else None
        ),
    )


def axiom_out(a: AxiomRow) -> Axiom:
    return Axiom(id=a.id, label=a.label, name=a.name, formula=a.formula, bindings=_bindings_out(a.bindings))


def rule_out(r: RuleRow) -> Rule:
    return Rule(
        id=r.id,
        label=r.label,
        name=r.name,
        deduction=r.deduction,
        antecedents=[ant.pattern for ant in r.antecedents],
        bindings=_bindings_out(r.bindings),
        side_conditions=rule_side_conditions_list(r),
        matching=r.matching,
        subproof=_subproof_out(r),
        allow_extra_antecedents=r.allow_extra_antecedents,
    )


def _subproof_out(r: RuleRow) -> Subproof | None:
    # A discharge rule is exactly the one carrying a subproof conclusion.
    if r.subproof_derive is None:
        return None
    return Subproof(derive=r.subproof_derive, assume=r.subproof_assume, fresh=r.subproof_fresh)


def _detail(system: FormalSystem) -> FormalSystemDetail:
    return FormalSystemDetail(
        **_summary(system).model_dump(),
        brackets=[bracket_out(b) for b in system.brackets],
        token_separated=system.token_separated,
        sorts=[sort_out(s) for s in system.symbols if s.kind == "union"],
        productions=[production_out(s) for s in system.symbols if s.kind != "union"],
        lines=[line_out(line) for line in system.lines],
        definitions=[definition_out(d) for d in system.definitions],
        axioms=[axiom_out(a) for a in system.axioms],
        rules=[rule_out(r) for r in system.rules],
    )


@router.get("", response_model=Page[FormalSystemSummary])
async def list_systems(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[FormalSystemSummary]:
    return await paginate_summaries(
        session,
        FormalSystem,
        User,
        base_conditions=[FormalSystem.owner_id == user.id],
        default_order=[FormalSystem.created_at],
        params=params,
        summarize=_summary,
    )


# Declared before `/{system_id}` so "public" isn't parsed as a system id.
@router.get("/public", response_model=Page[FormalSystemSummary])
async def list_public_systems(
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[FormalSystemSummary]:
    """The shared master list: every published system, any owner, no auth.

    Drafts (``published_at IS NULL``) are excluded; unpublishing removes a system
    from this list. Newest publications first, unless the client asks to sort.
    """
    return await paginate_summaries(
        session,
        FormalSystem,
        User,
        base_conditions=[FormalSystem.published_at.is_not(None)],
        default_order=[FormalSystem.published_at.desc(), FormalSystem.created_at.desc()],
        params=params,
        summarize=_summary,
    )


@router.post("", response_model=FormalSystemDetail, status_code=status.HTTP_201_CREATED)
async def create_system(
    payload: FormalSystemCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    if payload.inherits_from_id is not None:
        await _require_inheritable_reference(session, payload.inherits_from_id, user.id)

    system = FormalSystem(
        owner_id=user.id,
        name=payload.name,
        slug=await _unique_slug(session, user.id, payload.name),
        description=payload.description,
        inherits_from_id=payload.inherits_from_id,
    )
    session.add(system)
    await session.commit()

    # Reload so the (empty) child collections are eagerly present for the
    # detail serializer, and server-default timestamps are populated.
    return _detail(await _get_owned_or_404(session, system.id, user.id))


@router.get("/{system_id}", response_model=FormalSystemDetail)
async def get_system(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    # Published systems are readable by anyone; drafts only by their owner.
    return _detail(await _get_readable_or_404(session, system_id, user))


@router.patch("/{system_id}", response_model=FormalSystemDetail)
async def update_system(
    system_id: uuid.UUID,
    payload: FormalSystemUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> FormalSystemDetail:
    system = await _get_owned_or_404(session, system_id, user.id)
    changes = payload.model_dump(exclude_unset=True)

    # A published system is frozen: no field edits and no unpublishing, so proofs
    # verified against it stay valid (child-part edits are blocked the same way in
    # the system-parts router). Reject any change; an empty PATCH is a harmless
    # no-op. Publishing a *draft* is still allowed (handled below).
    if system.published_at is not None and changes:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This system is published and can no longer be edited or unpublished. "
            "Publishing is final so that proofs verified against it stay valid.",
        )

    if "inherits_from_id" in changes and changes["inherits_from_id"] is not None:
        if changes["inherits_from_id"] == system_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A system cannot inherit from itself.")
        await _require_inheritable_reference(
            session, changes["inherits_from_id"], user.id, child_id=system_id
        )

    if changes.get("name") is not None:
        system.name = changes["name"]
        system.slug = await _unique_slug(session, user.id, changes["name"], exclude_id=system.id)
    if "description" in changes:
        system.description = changes["description"]
    if "inherits_from_id" in changes and changes["inherits_from_id"] != system.inherits_from_id:
        system.inherits_from_id = changes["inherits_from_id"]
        # Repointing the parent changes the grammar, the rules and the
        # definitions this system's proofs were checked against — a bigger edit
        # than any part edit, and those all invalidate. Without this the proofs
        # keep the verdict *and* the stored line terms of a check against the old
        # chain, and a verify trusts a stored lemma rather than re-checking it
        # (docs/verification-from-rows.md, P1) — so another proof could go on
        # citing one under a parent it was never checked against. Under the
        # system lock, for the reason the part routes take it: a verify in flight
        # is reading those rows and believing them.
        await lock_system(session, system_id)
        await session.run_sync(lambda sync: discard_system_checks(sync, system_id))
    if changes.get("token_separated") is not None:
        system.token_separated = changes["token_separated"]

    # Publishing makes a system world-readable and is a one-way door — once set,
    # the freeze above rejects any later edit or unpublish. `published: false`
    # only reaches here for a draft (already unpublished), so it's a no-op.
    if changes.get("published"):
        await _require_publishable(session, system)
        system.published_at = datetime.now(timezone.utc)

    await session.commit()
    return _detail(await _get_owned_or_404(session, system_id, user.id))


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Ownership first. The dependent check below names systems that may be
    # someone else's private drafts, so asking it for a system the caller does
    # not own would answer 409-with-names where the rest of this router answers
    # 404 — and ids are exactly what that convention keeps from leaking.
    await owned_system_id_or_404(session, system_id, user.id)

    # A system something *inherits from* cannot be deleted. `inherits_from_id` is
    # `ON DELETE SET NULL`, so the delete would succeed and silently take the
    # descendants' grammar with it: what they build from changes, while their
    # proofs keep the `valid`, `result` and `proof_lines` rows of a check against
    # a system that no longer exists. Refused rather than cascaded, because the
    # cascade is not the author's to trigger from here — the descendants may be
    # someone else's, and a published parent is exactly the case where they are.
    dependents = (
        await session.scalars(
            select(FormalSystem.name).where(FormalSystem.inherits_from_id == system_id)
        )
    ).all()
    if dependents:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This system cannot be deleted while "
            + ", ".join(repr(name) for name in dependents)
            + " inherits from it. Delete those first.",
        )

    # One owner-scoped Core DELETE; the folders/proofs/parts go via their
    # ON DELETE CASCADE foreign keys, so nothing is loaded here.
    result = await session.execute(
        sa_delete(FormalSystem).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == user.id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Formal system not found.")
    await session.commit()


@router.post("/{system_id}/validate", response_model=SystemValidation)
async def validate_system(
    system_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> SystemValidation:
    system = await _get_readable_or_404(session, system_id, user)

    # Validated against the whole chain: a child that relies on its parent's
    # grammar is only a system at all once the parent's parts are in front of
    # its own (`app.db.effective_spec`).
    effective = await load_effective(session, system)
    if effective.errors:
        return SystemValidation(success=False, errors=effective.errors)
    result = build_spec(effective.spec)

    if "errors" in result:
        return SystemValidation(success=False, errors=result["errors"])

    compiled = result["system"]
    # The counts describe the *effective* system — the chain — because that is
    # what was built and what a proof here is checked against. `definitions` is
    # narrower on purpose: it carries row ids, and only this system's rows are
    # addressable through this system's routes. Two scopes in one response, and
    # deliberately so; the schema says which is which.
    return SystemValidation(
        success=True,
        system_name=compiled.name or None,
        line_type_count=len(compiled.line_types),
        inference_rule_count=len(compiled.inference_rules),
        definitions=_definition_binders(system, compiled),
    )


def _definition_binders(
    system: FormalSystem, compiled: object
) -> list[DefinitionBinders]:
    """Pair each stored definition with the binders the engine settled on.

    `definition_layering` is what makes the pairing sound: one flag per stored
    definition, in the same order, true exactly when that definition's defining
    form was recognised and a kernel definition was appended. So the compiled
    list is the true-flagged subsequence, and a dropped definition simply has no
    counterpart. Zipped strictly — a length mismatch would mean the builder and
    the rows disagree about what a definition is, which is a bug rather than a
    condition to paper over.

    ``compiled`` is built from the whole inheritance chain, so its lists are the
    ancestors' definitions followed by this system's. Only this system's are
    reported, because only they have a row here to name; the ancestors' belong to
    the systems that declare them, and are reported by *their* validate.
    """
    inherited = len(compiled.definition_layering) - len(system.definitions)
    layering = compiled.definition_layering[inherited:]
    # The kernel list is the true-flagged subsequence of the whole chain, so skip
    # what the ancestors contributed to it before pairing.
    kernel_definitions = iter(
        compiled.definitions[sum(compiled.definition_layering[:inherited]):]
    )
    reported: list[DefinitionBinders] = []
    for row, layered in zip(system.definitions, layering, strict=True):
        if not layered:
            continue
        definition = next(kernel_definitions)
        reported.append(
            DefinitionBinders(
                definition_id=row.id,
                label=definition.label,
                defined_form=definition.higher.to_string(),
                binders=[
                    DefinitionBinder(
                        var=binder.name,
                        sort=binder.sort.name,
                        inferred=not binder.declared,
                    )
                    for binder in definition.fresh
                ],
            )
        )
    return reported


@router.post("/{system_id}/verify", response_model=VerifyProofResponse)
async def verify_proof(
    system_id: uuid.UUID,
    payload: ProofVerifyRequest,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> VerifyProofResponse:
    """Check a proof against a stored system, assembled server-side from rows.

    Replaces the raw-source verify: the client sends only the proof text and the
    system id, never a serialised copy of the system itself. Readable systems are published ones
    (any viewer) or the owner's own drafts. Built against the system's whole
    inheritance chain, as everything else that builds one is.
    """
    system = await _get_readable_or_404(session, system_id, user)

    effective = await load_effective(session, system)
    if effective.errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=effective.errors)
    result = build_spec(effective.spec)
    if "errors" in result:
        # The stored system no longer compiles; surface the compile errors as a
        # 400 the client renders verbatim, as the old raw-source verify did.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["errors"])

    compiled = result["system"]
    # The proof checker raises on malformed proofs against otherwise-valid
    # systems (e.g. a line type whose context edit targets a missing key);
    # return a structured error rather than letting it escape as a 500.
    try:
        proof = compiled.parse(payload.proof_text)
    except Exception as e:
        return VerifyProofResponse(success=False, errors=[str(e)])

    return VerifyProofResponse(success=proof.valid, proof=proof.data())
