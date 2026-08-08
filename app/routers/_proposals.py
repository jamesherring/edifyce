"""Turning a *proposed* term into a resolved one, and checking it round-trips.

The shared half of the structured write path (docs/authoring-and-ingestion-roadmap.md
§9c). A caller names productions of the system's own grammar rather than writing
surface syntax, so the vocabulary is closed and enumerable; this is what turns
that into a kernel term.

Two callers now: a proof line (`POST /proofs/{id}/lines`) and a bare statement
(`POST /formal-systems/{id}/statements`), which is why it is here rather than
private to the proofs router. The difference between them is only *where* the
round trip is checked — a line splices into an existing line's shape, a bare
statement parses at the sorts a line is read at — and neither difference reaches
the resolution itself.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select

from app.db.terms import TermRow
from app.db.terms_mapping import prefetch_terms, term_context
from website.logical.formal_system.proposals import (
    Proposal,
    ProposalError,
    grammar_index,
    resolve,
)
from website.logical.kernel import from_match
from website.logical.promotion import logical_sorts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.schemas import TermProposalIn
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context


def proposal(payload: TermProposalIn) -> Proposal:
    """The API shape as the engine's, recursively.

    Two dataclasses rather than one shared model because the engine must not
    depend on Pydantic — and because ``ref`` is a caller-facing id here and an
    opaque string there, which is what lets `resolve` know nothing about storage.
    """
    return Proposal(
        ref=str(payload.ref) if payload.ref is not None else None,
        constructor=payload.constructor,
        slots={slot: proposal(child) for slot, child in payload.slots.items()},
        literal=payload.literal,
        sort=payload.sort,
    )


def referenced(payload: TermProposalIn) -> list[uuid.UUID]:
    """Every existing term the proposal points at, to sweep in one query."""
    found = [payload.ref] if payload.ref is not None else []
    for child in payload.slots.values():
        found.extend(referenced(child))
    return found


async def resolve_proposal(
    session: AsyncSession,
    payload: TermProposalIn,
    system_id: uuid.UUID,
    compiled: EngineSystem,
) -> tuple[Term, Context]:
    """Resolve a proposal against a built system, or raise the caller's answer.

    Returns the term and the context it was resolved in, since every caller then
    renders or re-parses against that same context.

    A referenced term must belong to **this** system: interning is per system, so
    a foreign id names a term built over another grammar, and resolving one would
    state a formula this system cannot mean.
    """
    context = term_context(compiled)
    wanted = referenced(payload)
    owners = (
        dict(
            (
                await session.execute(
                    select(TermRow.id, TermRow.formal_system_id).where(
                        TermRow.id.in_(wanted)
                    )
                )
            ).all()
        )
        if wanted
        else {}
    )
    foreign = [str(rid) for rid in wanted if owners.get(rid) != system_id]
    if foreign:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This system has no term with id {foreign[0]}.",
        )
    graph = await session.run_sync(lambda sync: prefetch_terms(sync, wanted))

    grammar = grammar_index(context)
    try:
        term = resolve(
            proposal(payload),
            context,
            lambda name: compiled.constructor_named(name, context, grammar),
            lambda ref: graph.term(uuid.UUID(ref), context),
        )
    except ProposalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LookupError as exc:
        # A referenced term whose constructor this grammar no longer has. Term
        # rows outlive the productions that built them, so the ownership check
        # above passes and `TermGraph.term` is where it surfaces — as a raise, out
        # of a rebuild. That is a stale id in a request, not a fault here.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "A referenced term was built over a grammar this system no longer "
                f"has, so it cannot be restated here: {exc}"
            ),
        ) from exc
    return term, context


def reparse_statement(
    compiled: EngineSystem, context: Context, text: str
) -> Term | None:
    """Read ``text`` back as a term, at the sorts a proof line is read at.

    The round trip for a statement that is not in a line. A proof line's is a
    splice into an existing line's shape (`FormalSystem.restate`); a bare
    statement has no line, so it is parsed at the system's **logical sorts** —
    which is exactly how a promoted theorem's ground statement is composed
    (`website.logical.promotion`), and therefore the sorts a line would have read
    it at anyway.

    ``None`` where no logical sort reads it, which the caller must refuse rather
    than treat as a match: a statement that parses at no sort is one no proof
    line could ever state.
    """
    for sort in logical_sorts(compiled):
        matched = sort.match(text, context)
        if matched is not None:
            return from_match(matched)
    return None
