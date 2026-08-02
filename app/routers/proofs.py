"""CRUD for proofs, owner-scoped.

Mirrors the formal-system CRUD (`app/routers/systems.py`): a proof is an
owner-scoped object stored as a single row (`app.db.models.Proof`) whose `source`
is proof text — lines written in a formal system's own grammar. This router is the thin
HTTP layer over that row — reads serialize it, `verify` rebuilds the parent
system from its stored rows and hands the proof to the engine (no proof-checking
logic lives here).

Like systems, writes persist freely (a draft proof need not verify) and
`POST /{id}/verify` reports validity on demand, caching the result. A check also
records the proof *as structure* — one row per line, each formula interned into
the system's term graph, each justification an edge (`app/db/proof_lines.py`),
readable at `GET /{id}/structure`. That snapshot is derived from the check, so
every path that invalidates a verdict drops it too. Publishing
makes a proof world-readable, so it is gated: the proof must verify **and** its
formal system must itself be published (a published proof exposes its
`formal_system_id`, and `GET` of a draft system 404s for anonymous viewers).

A proof may only be created against a system the caller **owns** (mirroring the
owned-only `inherits_from_id` reference), which keeps a proof and its system in
one ownership domain — so an owner-scoped system delete never cascades into
another user's proof.

Editing a proof's folder placement and its proof-to-proof references is a later
phase — the read models expose `folder_id` so that layer can address it, exactly
as the system read models expose each part's `id`.

A published proof's parent system can never change under it: publishing a system
is a one-way door — once published a system rejects every part edit, field edit,
and unpublish (see `systems.require_editable_system`) — so a proof verified
against a published system stays valid. A proof's *own* source is still editable
by its owner; a published proof re-verifies on a source edit (below), and an edit
that would break it is rejected.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from graphlib import CycleError
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from app.auth import current_active_user, current_active_user_optional
from app.db import (
    FormalSystem,
    cited_labels,
    Proof,
    ProofLineRow,
    ProofReference,
    clear_proof_lines,
    get_session,
    PendingCitations,
    PendingLibrary,
    load_definition_terms,
    load_proof_for_check,
    load_proof_lines,
    load_schema_terms,
    load_theorems,
    read_library,
    store_definition_terms,
    store_proof_lines,
    store_schema_terms,
    store_theorem,
    term_context,
    theorem_digest,
)
from app.db.descriptions import LabelDescriptionRow
from app.db.descriptions_mapping import load_description
from app.db.models import User
from app.db.notations_mapping import load_notation, render_stored
from app.db.terms_mapping import prefetch_terms
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.system_relations import SystemRelationRow
from app.db.systems import RuleRow
from app.routers._common import (
    PageParams,
    lock_system,
    page_params,
    paginate_summaries,
    unique_slug,
)
from app.routers.systems import load_effective, load_system
from website.logical.formal_system.proof import Proof as EngineProof
from app.schemas import (
    Attribution,
    LabelDescription,
    Page,
    ProofCreate,
    ProofDetail,
    ProofLineAntecedentOut,
    ProofLineOut,
    ProofReferenceOut,
    ProofReferencesUpdate,
    ProofPromotionRequest,
    ProofReferrerOut,
    ProofStructure,
    ProofSummary,
    ProofUpdate,
    PromotedTheoremOut,
    SystemOwner,
    THEOREM_LABEL_MAX,
    THEOREM_LABEL_PATTERN,
    TermSummary,
    VerifyProofResponse,
)
from website.logical.declarative import build_spec
from website.logical.graphs import topological_order
from website.logical.promotion import proved_theorem, schematic_theorem

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from app.routers.systems import EffectiveSystem
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system import PromotedTheorem
    from website.logical.matching.context import Context

router = APIRouter(prefix="/proofs", tags=["proofs"])


async def _unique_slug(
    session: AsyncSession,
    owner_id: uuid.UUID,
    system_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    # Slugs disambiguate a user's proofs within one system; numeric suffix on
    # collision. (Not DB-unique — proofs carry no slug constraint — but kept
    # addressable so a client can route to a proof by slug.)
    async def _taken(slug: str) -> bool:
        stmt = select(Proof.id).where(
            Proof.owner_id == owner_id,
            Proof.formal_system_id == system_id,
            Proof.slug == slug,
        )
        if exclude_id is not None:
            stmt = stmt.where(Proof.id != exclude_id)
        return await session.scalar(stmt) is not None

    return await unique_slug(name, _taken, fallback="proof")


# Loads for a detail view: the owner, plus the outgoing reference edges (with
# each referenced proof, for its identity in ProofReferenceOut) and the incoming
# ones (with each referring proof, for the "used by" list).
_DETAIL_LOADS = (
    selectinload(Proof.owner),
    selectinload(Proof.reference_links).selectinload(ProofReference.referenced),
    selectinload(Proof.referenced_by_links).selectinload(ProofReference.proof),
    # The library entry this proof establishes, so a detail read can say whether
    # it has been promoted without the client asking a second question.
    selectinload(Proof.theorem),
)


async def _load_owned(
    session: AsyncSession, proof_id: uuid.UUID, owner_id: uuid.UUID
) -> Proof | None:
    stmt = (
        select(Proof)
        .where(Proof.id == proof_id, Proof.owner_id == owner_id)
        .options(*_DETAIL_LOADS)
    )
    return await session.scalar(stmt)


async def _get_owned_or_404(
    session: AsyncSession, proof_id: uuid.UUID, owner_id: uuid.UUID
) -> Proof:
    proof = await _load_owned(session, proof_id, owner_id)
    if proof is None:
        # 404 (not 403) for another owner's id, so ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    return proof


def _is_readable(proof: Proof, user: User | None) -> bool:
    # Published proofs are public; drafts are visible only to their owner.
    if proof.published_at is not None:
        return True
    return user is not None and proof.owner_id == user.id


async def _get_readable_or_404(
    session: AsyncSession, proof_id: uuid.UUID, user: User | None
) -> Proof:
    stmt = select(Proof).where(Proof.id == proof_id).options(*_DETAIL_LOADS)
    proof = await session.scalar(stmt)
    if proof is None or not _is_readable(proof, user):
        # 404 (not 403) for a draft you don't own, so unpublished ids don't leak.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    return proof


async def _require_owned_system(
    session: AsyncSession, system_id: uuid.UUID, user: User
) -> None:
    """The system a proof is written against must be owned by the caller.

    Owned-only (not merely readable), mirroring how `inherits_from_id` requires
    an owned reference on the system side. This keeps a proof's system in the
    same ownership domain as the proof: a system delete is owner-scoped and
    cascades to proofs via `proofs.formal_system_id`, so allowing a proof against
    someone else's system would let that owner's delete destroy another user's
    proof. 400 (not 404) because it's a bad reference in the request body.
    """
    owned = await session.scalar(
        select(FormalSystem.id).where(
            FormalSystem.id == system_id, FormalSystem.owner_id == user.id
        )
    )
    if owned is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"formal_system_id {system_id} is not one of your systems.",
        )


# One reference edge as loaded for the closure: (alias, target proof id, position).
_Edge = tuple[str, uuid.UUID, int]


async def _reference_closure(
    session: AsyncSession, root_id: uuid.UUID
) -> tuple[dict[uuid.UUID, Proof], dict[uuid.UUID, list[_Edge]]]:
    """Load ``root_id`` and every proof it transitively references.

    Returns the proofs keyed by id and each proof's outgoing edges. References are
    same-system-only and the stored graph is acyclic (enforced on write), so this
    BFS terminates within the root's system.
    """
    proofs: dict[uuid.UUID, Proof] = {}
    edges: dict[uuid.UUID, list[_Edge]] = {}
    frontier = [root_id]
    while frontier:
        to_load = [pid for pid in frontier if pid not in proofs]
        frontier = []
        if not to_load:
            break
        rows = (
            await session.scalars(
                select(Proof)
                .where(Proof.id.in_(to_load))
                .options(selectinload(Proof.reference_links))
            )
        ).all()
        for proof in rows:
            proofs[proof.id] = proof
            edges[proof.id] = [
                (link.alias, link.references_id, link.position) for link in proof.reference_links
            ]
            frontier.extend(
                link.references_id
                for link in proof.reference_links
                if link.references_id not in proofs
            )
    return proofs, edges


def _dependency_order(
    node_ids: list[uuid.UUID], edges: dict[uuid.UUID, list[_Edge]]
) -> list[uuid.UUID]:
    # Proofs ordered so a lemma is compiled before the proofs that cite it.
    # Raises graphlib.CycleError if the graph is cyclic.
    return topological_order(
        {pid: [target for _alias, target, _pos in edges.get(pid, ())] for pid in node_ids}
    )


def _is_usable_lemma(engine_proof: EngineProof) -> bool:
    # A proof that does not stand cannot justify another, and a warning is
    # unresolved doubt about whether it stands. Such a lemma is left unseeded, so
    # a citation of it fails to resolve rather than resolving to something shaky.
    return bool(engine_proof.valid) and not engine_proof.has_warnings


@dataclass
class _Verification:
    """The outcome of checking a stored proof, plus the inputs a snapshot needs.

    ``valid`` is ``None`` when the proof could not be checked *at all* — its
    system no longer builds, or its source does not parse — which is a different
    thing from a checked proof that came out false. The remaining fields are
    populated only on the checked path, and are exactly what
    :func:`~app.db.proofs_mapping.store_proof_lines` projects into rows.
    """

    response: VerifyProofResponse
    valid: bool | None
    engine_proof: EngineProof | None = None
    system: FormalSystem | None = None
    # The system as resolved and as built, kept because a caller that needs them
    # after the check would otherwise read the chain's rows and compose every
    # rule schema a second time — measured at five times the read and about half
    # a build. Only `promote` wants them so far.
    effective: EffectiveSystem | None = None
    compiled_system: EngineSystem | None = None
    # Every lemma this proof may cite, paired with its stored id. Holding the
    # compiled proofs (not just their ids) is what lets the snapshot match a
    # cited line to its proof by identity — see store_proof_lines.
    cited_proofs: list[tuple[EngineProof, uuid.UUID]] = field(default_factory=list)


async def _verify_with_references(
    session: AsyncSession,
    proof: Proof,
    system: FormalSystem | None = None,
    persist: bool = True,
) -> _Verification:
    """Verify a stored proof, resolving the lemmas it cites from other proofs.

    Compiles the system once and parses the whole transitive reference closure in
    dependency order (a lemma before its dependents), pre-seeding each proof's
    ``reference_context`` with the already-compiled proofs it references — keyed by
    the stored citation alias — so a `[alias.line]` citation resolves to that
    lemma's line. Only *usable* lemmas (fully valid, warning-free) are seeded, so
    a proof leaning on an unproven lemma fails rather than borrowing an unsound
    line. Pass ``system`` to reuse an already-loaded system (a publish gate has
    one in hand); otherwise it is loaded here.

    ``persist=False`` for a caller whose transaction will be rolled back — an
    anonymous viewer verifying a published proof. The verdict is the same either
    way; what it skips is warming the schema-term cache, whose inserts would be
    discarded with everything else.
    """
    # Before anything is read. A verify now trusts the lemmas' stored rows
    # instead of re-checking them, so the read and the write must sit inside one
    # critical section: otherwise an invalidation can commit between them and
    # this transaction writes a valid snapshot back over it. See lock_system.
    await lock_system(session, proof.formal_system_id)

    if system is None:
        system = await load_system(session, proof.formal_system_id)
    if system is None:
        return _Verification(
            VerifyProofResponse(
                success=False, errors=["The proof's system no longer exists."]
            ),
            None,
        )

    # The rules' schema templates are parsed against the grammar to get the terms
    # the checker unifies with, which is about half of a build and the same
    # answer every time. Read the terms a previous build composed, and write back
    # anything this one had to compose itself — a system settles after one
    # verify, and a grammar edit makes the stored terms inert rather than wrong
    # (see app/db/schema_terms.py). Under the system lock, like everything else
    # this function writes.
    #
    # Against the system's whole inheritance chain: a child is only a system at
    # all once its ancestors' parts are in front of its own, so the spec that is
    # built — and the digests computed from it — cover the chain rather than this
    # row (app.db.effective_spec).
    effective = await load_effective(session, system)
    if effective.errors:
        return _Verification(
            VerifyProofResponse(success=False, errors=effective.errors), None
        )
    spec = effective.spec
    offset = effective.rule_offset
    schema_terms = await session.run_sync(
        lambda sync: load_schema_terms(sync, system, spec, offset)
    )
    # The same trade for each definition's two surface forms, which the build
    # parses into the terms an unfold is checked against (app/db/definition_terms.py).
    definition_terms = await session.run_sync(
        lambda sync: load_definition_terms(
            sync, system, spec, effective.definition_offset
        )
    )
    build = build_spec(
        spec, schema_terms=schema_terms, definition_terms=definition_terms
    )
    if "errors" in build:
        return _Verification(
            VerifyProofResponse(success=False, errors=build["errors"]), None
        )
    compiled_system = build["system"]
    if persist:
        await session.run_sync(
            lambda sync: store_schema_terms(
                sync, system, compiled_system, schema_terms, offset
            )
        )
        await session.run_sync(
            lambda sync: store_definition_terms(
                sync, system, compiled_system, definition_terms,
                effective.definition_offset
            )
        )

    closure, edges = await _reference_closure(session, proof.id)
    try:
        order = _dependency_order(list(closure), edges)
    except CycleError:
        # The stored graph is kept acyclic (enforced on write); a defensive guard.
        return _Verification(
            VerifyProofResponse(success=False, errors=["Circular proof reference."]), None
        )

    # The root can be absent if the proof was deleted concurrently between the
    # caller's load and the closure query — a structured failure, not a 500.
    if proof.id not in closure:
        return _Verification(
            VerifyProofResponse(success=False, errors=["Proof not found."]), None
        )

    # Every lemma is *loaded* from its stored lines rather than re-parsed and
    # re-checked. A cited line's formula is already a term in the system's graph,
    # and whether the lemma stands is already recorded — so a verify reads what
    # the lemma's own verify wrote instead of redoing it. See
    # docs/verification-from-rows.md; the root is still parsed (that is P2).
    #
    # Dependency order still matters, but only for *seeding*: a citation may
    # reach through a lemma into its own lemma, so a lemma's references must be
    # resolved before anything cites it.
    context = term_context(compiled_system)
    lemma_ids = [pid for pid in order if pid != proof.id]
    # The whole closure in one go: reading a proof back is latency, not work, so
    # batching is what makes it cheaper than re-parsing (see load_proof_lines).
    # A stored row that no longer matches its system raises out of `TermGraph.term`,
    # and the line-numbering guard raises deliberately. Both are defects in
    # stored data rather than in the proof being checked, but this function
    # reshapes every other failure into a verdict rather than a 500, and a
    # corrupt lemma should not be the one exception.
    try:
        loaded = await session.run_sync(
            lambda sync: load_proof_lines(sync, lemma_ids, compiled_system, context)
        )
    except Exception as exc:  # noqa: BLE001
        return _Verification(
            VerifyProofResponse(
                success=False, errors=[f"A cited proof could not be read: {exc}"]
            ),
            None,
        )

    compiled: dict[uuid.UUID, EngineProof] = {}
    unusable: dict[uuid.UUID, str] = {}
    for pid in lemma_ids:
        lemma = loaded.get(pid)
        if lemma is None or not _is_usable_lemma(lemma):
            unusable[pid] = closure[pid].name
            continue
        # A citation may reach through a lemma into its own lemma, so a lemma's
        # references are resolved before anything cites it — which is all the
        # dependency order is still for, now that nothing is re-checked.
        #
        # Aliases go *under* the labels `load_proof_lines` installed, matching
        # the parse path: there the context is seeded with aliases and each
        # labelled line then overwrites its own name as it executes. Updating the
        # other way round would silently give an alias precedence over a line
        # label of the same name.
        lemma.reference_context = {
            **{
                alias: compiled[target]
                for alias, target, _pos in edges.get(pid, ())
                if target in compiled
            },
            **lemma.reference_context,
        }
        compiled[pid] = lemma

    root = EngineProof(formal_system=compiled_system)
    root.reference_context = {
        alias: compiled[target]
        for alias, target, _pos in edges.get(proof.id, ())
        if target in compiled
    }
    # The proof's own lines come from its rows too, when it has any: everything
    # `read_line` would take off the grammar is stored, so a proof checked once
    # never needs its text parsed again (P2). Its verdict is *not* taken from the
    # rows — numbering, scope and justification are all re-derived — so this is a
    # re-check that happens to skip the parse, not a cache read.
    #
    # Rows are absent exactly when there is nothing to trust: the proof has never
    # been checked, or an edit invalidated it. Then, and only then, parse.
    #
    # The checker raises on malformed proofs against otherwise-valid systems;
    # reshape into a structured error rather than a 500.
    # A system's library is unbounded — an imported corpus has tens of thousands
    # of theorems — so it is not built with the system and cannot be. What a proof
    # cites is knowable before it is checked, from its own lines either way, so
    # resolve exactly those labels and promote them (P4). A label with no row is
    # simply not a theorem: it may name a rule, a definition, or a cited proof's
    # line, and the resolver settles that as it always did.
    #
    # And *its ancestors'* libraries: a theorem proved in a system this one
    # inherits from is citable here, resolved nearest-first with each layer's own
    # digest guarding its own cached terms (see `LibraryChain`).
    library = effective.library

    # `hypotheses_of` covers the other half of both paths below: a proof that
    # *establishes* a library entry proves under that entry's own hypotheses, and
    # states them as lines citing their labels.
    def promote(promoted: Mapping[str, PromotedTheorem]) -> None:
        for theorem in promoted.values():
            compiled_system.promote(theorem)

    def cited_terms(sync: Session, references: Sequence[str | None]) -> PendingCitations:
        # The row path resolves its library *into the proof's own term sweep*.
        # What a proof cites is a plain column, so the theorems it names are
        # settled before any term is built — and their cached terms then load
        # alongside the lines' rather than in a second closure over
        # `term_children`. They overlap heavily: a lemma's statement is a line of
        # the proof citing it, interned to the very same row.
        pending: PendingLibrary = read_library(
            sync, library, cited_labels(references),
            hypotheses_of=proof.theorem_id,
        )
        return PendingCitations(
            pending.term_ids,
            lambda graph: promote(pending.promote(compiled_system, context, graph)),
        )

    try:
        checked = await session.run_sync(
            lambda sync: load_proof_for_check(
                sync, proof.id, compiled_system, context, proof=root,
                resolve_citations=lambda refs: cited_terms(sync, refs),
            )
        )
        if checked is None:
            # No rows: read the lines off the text, resolve what they cite, then
            # check. The same two steps in the same order — `parse` is exactly
            # this pair, and is not used here only because the library has to be
            # resolved between them.
            #
            # `load_theorems` rather than the split above, because there is no
            # sweep to share: these lines were just parsed and already carry
            # their terms, so the library's is the only one this path does.
            _read, read_context = compiled_system.read_proof(proof.source, proof=root)
            await session.run_sync(
                lambda sync: promote(
                    load_theorems(
                        sync, library,
                        cited_labels(
                            line.reference_string
                            for line in root.proof_lines
                        ),
                        compiled_system, context,
                        hypotheses_of=proof.theorem_id,
                    )
                )
            )
            compiled_system.check_proof(root, read_context)
    except Exception as exc:  # noqa: BLE001
        return _Verification(
            VerifyProofResponse(success=False, errors=[str(exc)]), None
        )

    return _Verification(
        response=VerifyProofResponse(
            success=root.valid,
            proof=root.data(),
            errors=_unusable_errors(root, edges.get(proof.id, ()), unusable),
        ),
        valid=root.valid,
        engine_proof=root,
        system=system,
        effective=effective,
        compiled_system=compiled_system,
        # The root's lines may cite lines of any lemma in the closure, and this
        # is how the snapshot names the proof they belong to.
        cited_proofs=[(engine, pid) for pid, engine in compiled.items()],
    )


def _unusable_errors(
    root: EngineProof, references: Sequence[_Edge], unusable: dict[uuid.UUID, str]
) -> list[str]:
    """Why a citation did not resolve, when the reason is a lemma rather than the
    proof. A lemma is citable only once it has been verified and stands, so an
    unverified one leaves `[alias.n]` unresolved — which reads as a mistake in
    the citing proof unless we say what actually happened.

    Narrowed three ways, because this is an explanation and not a warning.
    `unusable` spans the whole transitive closure, so only the proof's **own**
    references can explain its failure — a lemma two hops away is nothing this
    proof cites. Only a proof that **failed** needs explaining at all. And of its
    own references, only those a *failing line actually names*: an unusable lemma
    the proof merely declares and never cites explains nothing, and saying it did
    would bury the real error under a claim the reader can see is false.
    """
    if root.valid:
        return []
    cited = _cited_aliases(root)
    named = sorted({unusable[target] for alias, target, _pos in references
                    if target in unusable and alias in cited})
    if not named:
        return []
    return [
        "Not cited: "
        + ", ".join(named)
        + " — a lemma must be verified, and stand, before a proof may rest on it."
    ]


def _cited_aliases(root: EngineProof) -> set[str]:
    """The lemma aliases the proof's *failing* lines name.

    A citation into a lemma is written `[rule, alias.n, …]`, so an alias is the
    part before the first dot of a reference component that has one; a component
    without a dot is a rule label or a local line number and names no lemma.
    Read off the invalid lines only — a lemma some other line cited successfully
    is not what went wrong here.
    """
    aliases: set[str] = set()
    for line in root.proof_lines:
        if line.valid or not line.reference_string:
            continue
        for part in line.reference_string.split(", "):
            head, dot, _rest = part.partition(".")
            if dot:
                aliases.add(head)
    return aliases


async def _record_verdict(
    session: AsyncSession, proof: Proof, verification: _Verification
) -> None:
    """Cache a fresh verdict on the proof row, and store the structure behind it.

    The two belong together: ``valid``/``result`` are what the editor renders,
    the ``proof_lines`` rows are the same check as structure (each formula a term
    in the system's graph, each citation an edge). Writing one without the other
    would leave the snapshot describing a different check than the verdict does.

    ``store_proof_lines`` is synchronous, like the rest of ``terms_mapping``, so
    it runs through ``run_sync`` on this session's connection — inside the
    caller's transaction, committed with it.
    """
    proof.valid = verification.valid
    proof.result = verification.response.proof

    engine_proof = verification.engine_proof
    if engine_proof is None or verification.system is None:
        # The proof could not be checked at all, so there is no structure to
        # record — and the stale snapshot from a previous check must not survive
        # a check that failed outright.
        await session.run_sync(lambda sync: clear_proof_lines(sync, [proof.id]))
        return

    system = verification.system
    cited = verification.cited_proofs
    # No acquire here: `_verify_with_references` took the system lock before it
    # read anything, and holds it for this transaction. That is what makes the
    # term interning below safe (a read-then-insert two proofs can both lose)
    # *and* what stops an invalidation landing between the read and this write.
    await session.run_sync(
        lambda sync: store_proof_lines(sync, proof, system, engine_proof, cited)
    )


async def _discard_check(session: AsyncSession, proof: Proof) -> None:
    """Drop everything derived from the last check of ``proof``.

    The cached verdict and the stored structure are one artefact of one check, so
    they are discarded together — a snapshot describing a source that has since
    changed is worse than no snapshot at all. Both are rebuilt on the next verify.

    Takes the system lock itself rather than trusting each call site to: a verify
    reading these rows must not have them invalidated out from under it between
    its read and its write, and forgetting the lock at one new call site is
    exactly how that guarantee would be lost (see `_common.lock_system`).
    """
    await lock_system(session, proof.formal_system_id)
    proof.valid = None
    proof.result = None
    await session.run_sync(lambda sync: clear_proof_lines(sync, [proof.id]))


async def _invalidate_dependents(
    session: AsyncSession, proof_id: uuid.UUID, system_id: uuid.UUID
) -> None:
    """Invalidate every proof that transitively references ``proof_id``, so a
    stale verdict can't survive a change to a lemma it leans on (a source edit,
    or the proof's deletion). Those proofs re-verify on demand.

    ``system_id`` is the system they all live in — references are same-system, so
    one key locks the lot. Taken here for the same reason as `_discard_check`: a
    verify in flight is reading exactly these rows.
    """
    await lock_system(session, system_id)
    dependents = await _dependent_closure(session, [proof_id])
    if dependents:
        await _clear_verdicts(session, dependents)


async def _dependent_closure(
    session: AsyncSession, proof_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Every proof that transitively references one of ``proof_ids``, excluding
    the roots themselves.

    Shared by the two things that invalidate: a lemma changing under its
    dependents, and a library entry being withdrawn from under the proofs that
    cited it. The second reaches here because a citer is itself citable — a
    proof that rests on the citer would otherwise keep a verdict that rests, one
    hop further back, on a theorem that is gone.
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


async def _clear_verdicts(
    session: AsyncSession, proof_ids: Sequence[uuid.UUID]
) -> None:
    """Drop the cached verdict and the stored structure of each proof.

    The pair is one artefact of one check (`_discard_check`), so they go
    together wherever a check stops meaning anything.
    """
    ids = list(proof_ids)
    if not ids:
        return
    await session.execute(
        sa_update(Proof).where(Proof.id.in_(ids)).values(valid=None, result=None)
    )
    await session.run_sync(lambda sync: clear_proof_lines(sync, ids))


async def _has_published_dependents(session: AsyncSession, proof_id: uuid.UUID) -> bool:
    """Whether any *published* proof references ``proof_id``.

    Only direct dependents are checked: the publish invariant already forces
    every ancestor of a published proof to be published, so a published proof
    that transitively depends on this one has a published proof directly citing
    it somewhere in the chain. Used to block unpublishing or deleting a lemma
    that a public theorem rests on (which would silently break that theorem).
    """
    dependent = await session.scalar(
        select(ProofReference.proof_id)
        .join(Proof, Proof.id == ProofReference.proof_id)
        .where(ProofReference.references_id == proof_id, Proof.published_at.is_not(None))
        .limit(1)
    )
    return dependent is not None


async def _require_publishable(session: AsyncSession, proof: Proof) -> None:
    """Reject a publish that would expose an unverified or dangling public proof.

    Two things a published proof must not do, since it becomes world-readable: it
    must verify against its system, and that system must itself be public — a
    published proof exposes `formal_system_id`, and `GET /formal-systems/{id}`
    404s for anonymous viewers when the system is a private draft.

    A third: every lemma it references must itself be published — a published
    proof's references are part of the theorem it exposes, and a public reader
    must be able to follow them.

    On success the fresh verdict is cached on the row, so a published proof always
    renders as checked. Also used to keep a *published* proof valid across source
    edits: re-running it after a source edit rejects a change that would leave a
    world-readable proof unverifying.
    """
    system = await load_system(session, proof.formal_system_id)
    if system is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The proof's system no longer exists.")

    if system.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot publish a proof whose system is an unpublished draft; "
            "publish the system first.",
        )

    unpublished = [link for link in proof.reference_links if link.referenced.published_at is None]
    if unpublished:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every referenced proof must be published before this proof can be.",
        )

    # Verify with references resolved, so a proof that leans on a lemma is gated
    # on the lemma actually proving it. Reuse the system already loaded above.
    verification = await _verify_with_references(session, proof, system=system)
    if not verification.response.success:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=verification.response.errors
            or ["Proof does not verify against its system."],
        )

    # All gates passed. The proof was just verified as part of gating, so record
    # that verdict — otherwise a published proof that was never hit by /verify
    # would render as "unchecked" despite publishing having proved it valid.
    await _record_verdict(session, proof, verification)


# ---------------------------------------------------------------------------
# Promotion — a proved proof entering its system's library
# ---------------------------------------------------------------------------


async def _citing_systems(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> list[uuid.UUID]:
    """Every system whose proofs may resolve ``label`` to ``system_id``'s entry.

    That system, plus the ones inheriting from it transitively — a citation
    resolves against a system's own library and then its ancestors' (`R2`), so a
    descendant's proof can rest on an entry stored here.

    The walk stops at a system that claims ``label`` **itself**: what it declares
    is nearer, so neither it nor anything below it was ever reaching ours.
    Following the resolver's own shadowing rule is what keeps this from
    invalidating proofs that never depended on the entry in question.

    Claiming it means *either* a library entry of that label or an **inference
    rule** of it — `Proof.get_reference` tries `rule_by_label` before the
    library, so a descendant's rule shadows an ancestor's theorem just as
    thoroughly as a nearer theorem would. Missing that half is the difference
    between invalidating a subtree and invalidating the right one.

    Returned **ancestor-first, and by id within a generation**, which is the
    order the caller then locks in; see :func:`_invalidate_citations` for why it
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
        shadowing = set(
            await session.scalars(
                select(PromotedTheoremRow.system_id).where(
                    PromotedTheoremRow.system_id.in_(children),
                    PromotedTheoremRow.label == label,
                )
            )
        ) | set(
            await session.scalars(
                select(RuleRow.system_id).where(
                    RuleRow.system_id.in_(children), RuleRow.label == label
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


async def _invalidate_citations(
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

    The order is **(depth, id)**, which `_citing_systems` returns: a system's
    depth in the tower is a property of the tower rather than of who is asking,
    so any two operations order any two systems they share identically — which is
    what a global lock order means. And it makes the pre-held key the *first*
    one, since ``system_id`` is the unique shallowest member of its own subtree.
    Inheritance is single-parent, so two subtrees are nested or disjoint and
    there is no third case to worry about.
    """
    systems = await _citing_systems(session, system_id, label)
    for locked in systems:
        await lock_system(session, locked)

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
    await _clear_verdicts(session, citing + await _dependent_closure(session, citing))


def _label_from_slug(proof: Proof) -> str:
    """The default promotion label: the proof's slug, if it can be a label.

    A slug is not a label. `slugify` produces anything URL-safe — a leading
    digit, up to the 256 characters a name may run to — while a label has to be
    citable (`[label]`, which is why `ProofPromotionRequest` constrains an
    explicit one to `_ALIAS_PATTERN`) and has to fit a `String(128)` column.
    Validated rather than trusted: unchecked, the two ways a slug can fail are a
    citation that never parses and, on Postgres, a string-truncation 500.
    """
    slug = proof.slug
    if len(slug) <= THEOREM_LABEL_MAX and re.match(THEOREM_LABEL_PATTERN, slug):
        return slug
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"This proof's slug {slug!r} cannot be a theorem label — a label is "
        "cited as `[label]`, so it must start with a letter, use only letters, "
        f"digits, `-` and `_`, and be at most {THEOREM_LABEL_MAX} characters. "
        "Pass one.",
    )


async def _retire_promotion(session: AsyncSession, proof: Proof) -> None:
    """Withdraw the library entry ``proof`` established, if it established one.

    Called wherever the proof stops being the standing thing it was promoted as —
    a source edit, an unpublish, a delete. The entry's warrant *is* this proof
    (`promoted_theorems.proved_by_id`), so once the proof no longer stands the
    entry asserts something nothing here proves, and leaving it would make a
    citation of it resolve to exactly that.

    An **imported** entry is untouched: its `proved_by_id` is NULL because its
    warrant is the corpus rather than the stored proof, so a grammar edit that
    invalidates every proof in a corpus withdraws none of its library.
    """
    entry = (
        await session.execute(
            select(PromotedTheoremRow.id, PromotedTheoremRow.system_id,
                   PromotedTheoremRow.label)
            .where(PromotedTheoremRow.proved_by_id == proof.id)
        )
    ).first()
    if entry is None:
        return
    # `system_id` is the proof's own system: a proof promotes into the system it
    # is written in, so this is the same key the caller already locked — which is
    # what `_invalidate_citations` relies on to be the first lock in its order.
    entry_id, system_id, label = entry

    # Before the delete: the query below reads `proof_lines`, and a line citing
    # this entry is found by the label, not by the row.
    await _invalidate_citations(session, system_id, label)
    # Drop the proof's own pointer first, and through the relationship rather
    # than the column: `proofs.theorem_id` is `ON DELETE SET NULL`, so the
    # database would clear it either way, but the loaded object would keep the
    # old entry — and this session's next read of it comes out of the identity
    # map, which is what a route returning `_detail` then renders.
    if proof.theorem_id == entry_id:
        proof.theorem = None
        await session.flush()
    await session.execute(
        sa_delete(PromotedTheoremRow).where(PromotedTheoremRow.id == entry_id)
    )


def _owner_out(proof: Proof) -> SystemOwner | None:
    if proof.owner is None:
        return None
    return SystemOwner(id=proof.owner.id, display_name=proof.owner.display_name)


def _summary(proof: Proof) -> ProofSummary:
    return ProofSummary(
        id=proof.id,
        name=proof.name,
        slug=proof.slug,
        title=proof.title,
        description=proof.description,
        formal_system_id=proof.formal_system_id,
        folder_id=proof.folder_id,
        valid=proof.valid,
        published_at=proof.published_at,
        created_at=proof.created_at,
        updated_at=proof.updated_at,
        owner=_owner_out(proof),
    )


def _references_out(proof: Proof, viewer: User | None) -> list[ProofReferenceOut]:
    # Only surface references the viewer may themselves read. Otherwise a
    # published proof that cites the owner's own draft would leak that draft's
    # existence, name, and slug to any anonymous reader.
    return [
        ProofReferenceOut(
            referenced_proof_id=link.references_id,
            alias=link.alias,
            name=link.referenced.name,
            slug=link.referenced.slug,
            published=link.referenced.published_at is not None,
        )
        for link in proof.reference_links
        if _is_readable(link.referenced, viewer)
    ]


def _referenced_by_out(proof: Proof, viewer: User | None) -> list[ProofReferrerOut]:
    # The "used by" direction: proofs that cite this one as a lemma. Filtered to
    # those the viewer may read, so a stranger's draft that references a published
    # proof doesn't leak its existence to the public. The incoming edges have no
    # inherent order (position orders a proof's *own* references), so sort by name
    # then id for a stable, meaningful "used by" list across requests.
    referrers = [
        ProofReferrerOut(
            proof_id=link.proof_id,
            alias=link.alias,
            name=link.proof.name,
            published=link.proof.published_at is not None,
        )
        for link in proof.referenced_by_links
        if _is_readable(link.proof, viewer)
    ]
    referrers.sort(key=lambda r: (r.name, str(r.proof_id)))
    return referrers


def _theorem_out(proof: Proof) -> PromotedTheoremOut | None:
    """The library entry this proof establishes, if it establishes one.

    Reported for an *imported* entry too, whose `proved_by_id` is then null —
    the proof does establish it, and saying so is what lets a client tell an
    entry it may retire from one it may not.
    """
    theorem = proof.theorem
    if theorem is None:
        return None
    return PromotedTheoremOut(
        id=theorem.id,
        label=theorem.label,
        statement=theorem.statement,
        formal_system_id=theorem.system_id,
        proved_by_id=theorem.proved_by_id,
    )


def _documentation_out(row: LabelDescriptionRow | None) -> LabelDescription | None:
    """The system's record for a proof's label, or None if it keeps none.

    None for every hand-authored proof, which is the common case: a system
    describes the labels it was *imported* with, and a proof created through the
    API carries its own title and description instead.
    """
    if row is None:
        return None
    return LabelDescription(
        label=row.label,
        title=row.title,
        text=row.text,
        attributions=[
            Attribution(kind=a.kind, who=a.who, dated=a.dated) for a in row.attributions
        ],
    )


def _detail(
    proof: Proof,
    viewer: User | None,
    documentation: LabelDescriptionRow | None = None,
) -> ProofDetail:
    return ProofDetail(
        **_summary(proof).model_dump(),
        source=proof.source,
        result=proof.result,
        references=_references_out(proof, viewer),
        referenced_by=_referenced_by_out(proof, viewer),
        theorem=_theorem_out(proof),
        documentation=_documentation_out(documentation),
    )


@router.get("", response_model=Page[ProofSummary])
async def list_proofs(
    formal_system_id: uuid.UUID | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[ProofSummary]:
    base = [Proof.owner_id == user.id]
    # Optional scope to one system, so an editor can list just that system's proofs.
    if formal_system_id is not None:
        base.append(Proof.formal_system_id == formal_system_id)
    return await paginate_summaries(
        session,
        Proof,
        User,
        base_conditions=base,
        default_order=[Proof.created_at],
        params=params,
        summarize=_summary,
    )


# Declared before `/{proof_id}` so "public" isn't parsed as a proof id.
@router.get("/public", response_model=Page[ProofSummary])
async def list_public_proofs(
    session: AsyncSession = Depends(get_session),
    params: PageParams = Depends(page_params),
) -> Page[ProofSummary]:
    """The shared master list: every published proof, any owner, no auth.

    Drafts (``published_at IS NULL``) are excluded; unpublishing removes a proof
    from this list. Newest publications first, unless the client asks to sort.
    """
    return await paginate_summaries(
        session,
        Proof,
        User,
        base_conditions=[Proof.published_at.is_not(None)],
        default_order=[Proof.published_at.desc(), Proof.created_at.desc()],
        params=params,
        summarize=_summary,
    )


@router.post("", response_model=ProofDetail, status_code=status.HTTP_201_CREATED)
async def create_proof(
    payload: ProofCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    await _require_owned_system(session, payload.formal_system_id, user)

    proof = Proof(
        owner_id=user.id,
        formal_system_id=payload.formal_system_id,
        name=payload.name,
        slug=await _unique_slug(session, user.id, payload.formal_system_id, payload.name),
        title=payload.title,
        description=payload.description,
        source=payload.source,
    )
    session.add(proof)
    await session.commit()

    # Reload so server-default timestamps and the owner are eagerly present.
    return _detail(await _get_owned_or_404(session, proof.id, user.id), user)


@router.get("/{proof_id}", response_model=ProofDetail)
async def get_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    # Published proofs are readable by anyone; drafts only by their owner.
    proof = await _get_readable_or_404(session, proof_id, user)
    # Only the single read carries the corpus's record. A list of proofs wants
    # `title`, which is on the row; the prose and the authorship are a page's worth
    # of text each, and 47,000 of them do not belong in a listing.
    documentation = await load_description(
        session, proof.formal_system_id, proof.name
    )
    return _detail(proof, user, documentation)


@router.patch("/{proof_id}", response_model=ProofDetail)
async def update_proof(
    proof_id: uuid.UUID,
    payload: ProofUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    proof = await _get_owned_or_404(session, proof_id, user.id)
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("name") is not None:
        proof.name = changes["name"]
        proof.slug = await _unique_slug(
            session, user.id, proof.formal_system_id, changes["name"], exclude_id=proof.id
        )
    if "title" in changes:
        proof.title = changes["title"]
    if "description" in changes:
        proof.description = changes["description"]
    source_changed = "source" in changes and changes["source"] is not None
    if source_changed:
        proof.source = changes["source"]
        # The stored source changed, so everything derived from checking this
        # proof — and the cached verdict of anything that cites it as a lemma —
        # is stale.
        await _discard_check(session, proof)
        await _invalidate_dependents(session, proof.id, proof.formal_system_id)
        # Including the library entry it established, whose statement was this
        # proof's *previous* conclusion. Retired rather than re-derived: the new
        # conclusion may say something else entirely, and silently swapping the
        # statement under everything citing it would be worse than withdrawing
        # it. Re-promote to put it back.
        await _retire_promotion(session, proof)

    # Publishing is the write that makes a proof world-readable, so gate it —
    # after the field changes above so the checks see this request's final state.
    # A source edit on an already-published proof is re-gated too, so a
    # world-readable proof can't be edited into a non-verifying state. Both paths
    # re-cache the verdict.
    if "published" in changes:
        if changes["published"]:
            await _require_publishable(session, proof)
        elif await _has_published_dependents(session, proof.id):
            # Unpublishing a lemma a published proof rests on would leave that
            # public theorem depending on a private draft; block it (the
            # dependents must be unpublished first).
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cannot unpublish a proof that a published proof references.",
            )
        else:
            # Publication is what a promotion rests on — it is the gate, and it
            # is what makes the proof's statement public in the first place — so
            # withdrawing it withdraws the entry too.
            await _retire_promotion(session, proof)
        proof.published_at = datetime.now(timezone.utc) if changes["published"] else None
    elif source_changed and proof.published_at is not None:
        await _require_publishable(session, proof)

    await session.commit()
    return _detail(await _get_owned_or_404(session, proof_id, user.id), user)


async def _reference_would_cycle(
    session: AsyncSession,
    proof_id: uuid.UUID,
    target_ids: list[uuid.UUID],
    system_id: uuid.UUID,
) -> bool:
    """Whether pointing ``proof_id`` at every id in ``target_ids`` closes a cycle.

    The stored reference graph is kept acyclic, so a new cycle must run through
    ``proof_id`` (proof → target → … → proof). Load every edge in this system
    except this proof's own (they are being replaced) and ask whether any target
    already reaches ``proof_id``. References are same-system-only, so scoping the
    load to the system captures the whole reachable closure without scanning the
    global table. The reference graph is tracked relationally, not in the engine:
    a ``Proof`` knows the lemmas seeded into its ``reference_context``, not the
    edges that produced them, so this check has no engine-side counterpart.
    """
    rows = (
        await session.execute(
            select(ProofReference.proof_id, ProofReference.references_id)
            .join(Proof, Proof.id == ProofReference.proof_id)
            .where(Proof.formal_system_id == system_id, ProofReference.proof_id != proof_id)
        )
    ).all()
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for src, dst in rows:
        adjacency[src].append(dst)

    seen: set[uuid.UUID] = set()
    stack = list(target_ids)
    while stack:
        node = stack.pop()
        if node == proof_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


@router.put("/{proof_id}/references", response_model=ProofDetail)
async def set_proof_references(
    proof_id: uuid.UUID,
    payload: ProofReferencesUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProofDetail:
    """Replace a proof's outgoing references (the lemmas it cites) wholesale.

    A proof may reference another proof **in the same system** that is either the
    caller's own or published (a public lemma). Self-references, duplicate targets
    or aliases, and any edge that would make the reference graph cyclic are
    rejected (422). A published proof may only reference published proofs (its
    references are part of the public theorem). Changing the set invalidates the
    cached verdict of this proof and of anything that cites it, since references
    now feed verification.
    """
    proof = await _get_owned_or_404(session, proof_id, user.id)

    # Serialize concurrent reference edits in this system so the cycle check
    # below can't be raced into committing a cycle.
    await lock_system(session, proof.formal_system_id)

    target_ids = [r.referenced_proof_id for r in payload.references]
    aliases = [r.alias for r in payload.references]

    if proof.id in target_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A proof cannot reference itself.")
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A proof may reference another proof at most once."
        )
    if len(set(aliases)) != len(aliases):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Reference aliases must be unique within a proof."
        )

    if target_ids:
        targets = (await session.scalars(select(Proof).where(Proof.id.in_(target_ids)))).all()
        by_id = {t.id: t for t in targets}
        for tid in target_ids:
            target = by_id.get(tid)
            if target is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"Referenced proof {tid} does not exist."
                )
            if target.formal_system_id != proof.formal_system_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "A proof may only reference proofs in the same system.",
                )
            # Own proofs (draft or published) or anyone's published proof.
            if target.owner_id != user.id and target.published_at is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Referenced proof {tid} must be your own or a published proof.",
                )
            # A published proof's references are exposed publicly and must verify
            # for a public reader, so they must be published too.
            if proof.published_at is not None and target.published_at is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "A published proof may only reference published proofs.",
                )

        if await _reference_would_cycle(session, proof.id, target_ids, proof.formal_system_id):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That set of references would create a circular dependency.",
            )

    # Replace the edge set. Clear-then-flush before inserting so the unique
    # (proof_id, alias) index can't trip on an alias reused from the old set.
    proof.reference_links.clear()
    await session.flush()
    proof.reference_links = [
        ProofReference(references_id=tid, alias=alias, position=i)
        for i, (tid, alias) in enumerate(zip(target_ids, aliases))
    ]
    # References feed verification now, so this proof's check and every
    # dependent's are stale.
    await _discard_check(session, proof)
    await _invalidate_dependents(session, proof.id, proof.formal_system_id)
    # Including anything this proof established: what it proves depends on the
    # lemmas it may cite, so dropping a reference can leave a promoted entry
    # standing behind a proof that no longer verifies. Same rule as a source
    # edit — the reference set is as much a part of the proof as its text.
    await _retire_promotion(session, proof)
    await session.commit()
    return _detail(await _get_owned_or_404(session, proof_id, user.id), user)


@router.post(
    "/{proof_id}/promote",
    response_model=PromotedTheoremOut,
    status_code=status.HTTP_201_CREATED,
)
async def promote_proof(
    proof_id: uuid.UUID,
    payload: ProofPromotionRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PromotedTheoremOut:
    """Enter this proof's conclusion in its system's library, as a ground theorem.

    R3 of docs/system-relationships-roadmap.md, and the half of (a)/(b) that
    reaches work a person proves: until now only an import wrote
    `promoted_theorems`, so a lemma proved in propositional calculus could not be
    cited from a proof written in ZFC however sound the citation was.

    **Published, not merely valid.** R2 makes a system's library visible to every
    descendant, and a descendant may be someone else's — a published parent is
    exactly the case where it is — so promoting a draft would publish that proof's
    statement to strangers by another route. Publication is also what keeps the
    entry stable: `_require_publishable` re-runs on every source edit, so a
    published proof cannot be edited into not standing, and the ways it *can*
    stop standing (unpublish, edit, delete) each retire the entry.

    The statement is the conclusion's stored term rather than its text; see
    `website.logical.promotion.proved_theorem`. Re-promoting replaces the entry
    rather than adding a second, so an author who re-promotes after an edit gets
    one entry saying what the proof now concludes.
    """
    proof = await _get_owned_or_404(session, proof_id, user.id)
    if proof.published_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only a published proof can be promoted: its statement becomes "
            "citable from every system that inherits this one. Publish it first.",
        )

    # Checked here rather than trusting `proof.valid`: the cached verdict is what
    # the editor renders, and this is the write that lets other proofs rest on it.
    verification = await _verify_with_references(session, proof)
    await _record_verdict(session, proof, verification)
    engine_proof = verification.engine_proof
    if engine_proof is None or not _is_usable_lemma(engine_proof):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=verification.response.errors
            or [
                "Only a proof that verifies and carries no warning can be "
                "promoted — a warning is unresolved doubt about whether it stands."
            ],
        )

    label = payload.label or _label_from_slug(proof)
    # Reused rather than re-derived: the verify above resolved the chain and
    # built it, and doing either again is the duplicate work R2's review
    # measured. Both are non-null exactly when `engine_proof` is.
    system = verification.system
    effective = verification.effective
    compiled = verification.compiled_system

    # A reference resolves rules before theorems, so a label a rule already
    # carries would store an entry no citation could ever reach.
    if any(rule.label == label for rule in compiled.inference_rules):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label!r} is already an inference rule of this system, and a "
            "citation resolves a rule before a theorem, so the entry would be "
            "unreachable. Promote it under another label.",
        )
    # `is_distinct_from`, not `!=`: an imported entry's `proved_by_id` is NULL,
    # and a NULL inequality is NULL rather than true — so a plain `!=` would let
    # a clash with an imported label through the guard and into the unique index,
    # answering 500 where this answers 409.
    taken = await session.scalar(
        select(PromotedTheoremRow.id).where(
            PromotedTheoremRow.system_id == system.id,
            PromotedTheoremRow.label == label,
            PromotedTheoremRow.proved_by_id.is_distinct_from(proof.id),
        )
    )
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label!r} already names a theorem in this system's library.",
        )

    try:
        if payload.metavariables:
            # R3a. The nomination is a claim about every instance, so the engine
            # re-checks the proof with those leaves held schematic and refuses if
            # it stops standing — and carries forward the provisos the steps
            # relied on. Both are its business, not this router's.
            spec, promoted = schematic_theorem(
                compiled,
                engine_proof,
                label,
                payload.metavariables,
                term_context(compiled),
            )
        else:
            spec, promoted = proved_theorem(compiled, engine_proof, label)
    except ValueError as exc:
        # The engine's own guards — nothing to promote, a proof that does not
        # stand, or a nomination the proof does not support. The second should
        # have been caught above; the first is reachable by a proof whose every
        # line is commentary.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Replace rather than accumulate. Retiring first also invalidates whatever
    # cited the old entry, which a re-promotion after an edit needs just as much
    # as an outright withdrawal does: the statement may have changed under them.
    await _retire_promotion(session, proof)

    system_id = system.id
    # And whatever cited this *label*, which is not the same set: shadowing is
    # legal (R2 resolves nearest-first), so promoting a label an ancestor already
    # carries is allowed — and silently changes what every proof here and below
    # was citing. A verdict recorded against the ancestor's entry has to go for
    # the same reason a retirement's does.
    await _invalidate_citations(session, system_id, label)
    digest = theorem_digest(effective.library.digest(system_id), spec)
    symbols = {symbol.name: symbol for symbol in system.symbols}
    position = await session.scalar(
        select(func.count())
        .select_from(PromotedTheoremRow)
        .where(PromotedTheoremRow.system_id == system_id)
    )
    row = await session.run_sync(
        lambda sync: store_theorem(
            sync,
            system,
            spec,
            symbols,
            position=position or 0,
            # Derived, not assumed: this is a theorem the system proved, which is
            # exactly the distinction `primitive` records.
            primitive=False,
            digest=digest,
            promoted=promoted,
            proved_by_id=proof.id,
        )
    )
    await session.flush()
    # The other direction, and a different claim: this proof proves *under* the
    # entry's hypotheses. A ground promotion has none, so it buys nothing yet —
    # it is set because the link is what says which proof "this one" is, and a
    # schematic promotion with premises will need it (see `hypotheses_of`).
    proof.theorem_id = row.id
    await session.commit()
    return PromotedTheoremOut(
        id=row.id,
        label=row.label,
        statement=row.statement,
        formal_system_id=system_id,
        proved_by_id=proof.id,
    )


@router.delete("/{proof_id}/promote", status_code=status.HTTP_204_NO_CONTENT)
async def retire_proof_promotion(
    proof_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Withdraw the library entry this proof established.

    Idempotent: a proof that established none is a no-op rather than a 404, since
    the caller's intent — "this must not be citable" — is already true.
    """
    proof = await _get_owned_or_404(session, proof_id, user.id)
    await _retire_promotion(session, proof)
    await session.commit()


@router.delete("/{proof_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proof(
    proof_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Establish ownership first (404 for a stranger's id, so nothing leaks) before
    # any dependency checks reveal the proof exists.
    owned = (
        await session.execute(
            select(Proof.id, Proof.formal_system_id).where(
                Proof.id == proof_id, Proof.owner_id == user.id
            )
        )
    ).first()
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proof not found.")
    _, system_id = owned

    # Deleting a proof drops its reference edges (FK cascade), so a dependent's
    # `[alias.line]` citation would dangle. If a *published* proof rests on it,
    # that would silently break a public theorem — block it. Otherwise just clear
    # the (draft) dependents' stale verdicts.
    if await _has_published_dependents(session, proof_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete a proof that a published proof references.",
        )
    await _invalidate_dependents(session, proof_id, system_id)
    # The library entry goes with the proof by `ON DELETE CASCADE`, but the
    # proofs *citing* it would keep a verdict that rested on it — so retire it
    # explicitly, which is the path that invalidates them.
    await _retire_promotion(session, await _get_owned_or_404(session, proof_id, user.id))

    await session.execute(sa_delete(Proof).where(Proof.id == proof_id))
    await session.commit()


def _term_out(row: ProofLineRow) -> TermSummary | None:
    term = row.term
    if term is None:
        return None
    return TermSummary(
        id=term.id,
        kind=term.kind,
        constructor=term.constructor,
        literal=term.literal,
        sort=term.sort,
        digest=term.digest,
        alpha_digest=term.alpha_digest,
    )


def _line_out(row: ProofLineRow, rendered: str | None = None) -> ProofLineOut:
    return ProofLineOut(
        rendered=rendered,
        id=row.id,
        position=row.position,
        number=row.number,
        indent=row.indent,
        display=row.display,
        line_type=row.line_type,
        behaviour=row.behaviour,
        label=row.label,
        reference=row.reference,
        rule=row.rule,
        definition_id=row.definition_id,
        valid=row.valid,
        invalid_message=row.invalid_message,
        warning_message=row.warning_message,
        opens_scope=row.opens_scope,
        scope_id=row.scope_id,
        term=_term_out(row),
        antecedents=[
            ProofLineAntecedentOut(
                role=edge.role,
                position=edge.position,
                line_id=edge.antecedent_line_id,
                proof_id=edge.antecedent_proof_id,
                number=edge.antecedent_number,
            )
            for edge in row.antecedents
        ],
    )


@router.get("/{proof_id}/structure", response_model=ProofStructure)
async def get_proof_structure(
    proof_id: uuid.UUID,
    notation: str | None = Query(
        None,
        description=(
            "Read the lines in one of the system's stored notations. Omitted, "
            "lines carry only the source they were written in."
        ),
    ),
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> ProofStructure:
    """The proof as the checker decomposed it: lines, terms, justification edges.

    Read-only and never computed on demand — it reports what the last
    verification stored rather than quietly re-running the engine, so ``stored``
    answers "is a structure materialised", not "was this proof checked" (which is
    ``valid``). Visibility follows the proof itself.
    """
    proof = await _get_readable_or_404(session, proof_id, user)
    rows = (
        await session.scalars(
            select(ProofLineRow)
            .where(ProofLineRow.proof_id == proof.id)
            .order_by(ProofLineRow.position)
            .options(selectinload(ProofLineRow.term), selectinload(ProofLineRow.antecedents))
        )
    ).all()
    # No rows means no structure, not "checked and empty": an empty *source*
    # still stores its one blank line. A proof checked before this store existed
    # also lands here, and materialises on its next verify.
    projection = None
    if notation is not None:
        projection = await load_notation(session, proof.formal_system_id, notation)
        if projection is None:
            # A name the system does not store is a client error worth reporting:
            # silently serving the source would look like the notation had no
            # opinion about any of it.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"This proof's system has no notation named {notation!r}.",
            )

    rendered: dict[uuid.UUID, str] = {}
    if projection is not None and rows:
        # One sweep for the whole proof's terms, then a fold per line. Rendering
        # reads rows only — a stored notation names every constructor, so no
        # system rebuild is needed to show a proof (see `render_stored`).
        graph = await session.run_sync(
            lambda sync: prefetch_terms(sync, [r.term_id for r in rows])
        )
        for row in rows:
            shown = render_stored(graph, row.term_id, projection)
            # `None` (no term) is dropped and `""` (a constructor the notation
            # does not name) is kept, so a client can tell "nothing to read here"
            # from "read, and the notation had nothing to say" — the second is a
            # gap worth showing the source for.
            if shown is not None:
                rendered[row.id] = shown

    return ProofStructure(
        proof_id=proof.id,
        stored=bool(rows),
        notation=notation,
        lines=[_line_out(row, rendered.get(row.id)) for row in rows],
    )


@router.post("/{proof_id}/verify", response_model=VerifyProofResponse)
async def verify_stored_proof(
    proof_id: uuid.UUID,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> VerifyProofResponse:
    proof = await _get_readable_or_404(session, proof_id, user)

    # Only the owner's transaction is committed (an anonymous viewer of a
    # published proof gets the result but leaves the stored snapshot untouched),
    # so a non-owner's verify must not do write work that will be rolled back.
    owned = user is not None and proof.owner_id == user.id
    verification = await _verify_with_references(session, proof, persist=owned)

    # Record the verdict and the structure behind it, so a client can render the
    # proof without re-checking and the lines are searchable as terms.
    if owned:
        await _record_verdict(session, proof, verification)
        await session.commit()

    return verification.response
