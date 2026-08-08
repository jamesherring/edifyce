"""Stating a theorem before there is a proof to put it in.

§4.4 of docs/informal-source-ingestion-roadmap.md. Every structured write this
API has is *inside* a proof — `/proofs/{id}/lines` needs a proof, and a template
line within it to inherit shape from. A translation from an informal source needs
the opposite order: state the target first, ask whether the library already
proves it, and only then open a proof aimed at it.

That question — **is this already proved?** — is the first one any translation
asks, and until now the only way to ask it was to write a proof and see. Which is
absurd for the case it matters most in: a corpus of 47,589 theorems where the
answer is often yes and the caller has no way to find out.

**One path from vocabulary to term.** The other thing this is, and the reason it
comes before the rest of §4: an assumption's statement, a goal, and a proof
line's formula are all "a term composed against this grammar", and until now only
the third had a structured route. Taking that path once — resolved against the
grammar, round-trip checked, interned — is what lets the others stop taking text.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import current_active_user_optional
from app.db.retrieval import conclusion_candidates
from app.db.session import get_session
from app.db.terms_mapping import alpha_digest, digest_term, store_term
from app.routers._common import lock_system
from app.routers._proposals import reparse_statement, resolve_proposal
from app.routers.proofs import build_system, require_a_built_system
from app.routers.systems import readable_system_id_or_404
from app.schemas import (
    StatementOutcome,
    StatementProposal,
    TheoremCandidate,
)
from website.logical.kernel.terms import Node
from website.logical.rendering import render

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import User

router = APIRouter(tags=["formal-systems"])


@router.post(
    "/formal-systems/{system_id}/statements", response_model=StatementOutcome
)
async def propose_statement(
    system_id: uuid.UUID,
    payload: StatementProposal,
    user: User | None = Depends(current_active_user_optional),
    session: AsyncSession = Depends(get_session),
) -> StatementOutcome:
    """Compose a statement from the grammar, and say what could conclude it.

    **The round trip is checked, not trusted**, exactly as a line proposal's is
    (§9c): the resolved term is rendered into the system's own spelling and read
    back, and the statement is refused unless the term that comes out is the term
    that went in. A bare statement has no line to splice into, so it is read back
    at the sorts a proof line is read at — which is how a promoted theorem's
    ground statement is composed, and therefore the sorts a line would have read
    it at anyway.

    **A dry run unless ``store``.** Asking whether something is proved is a
    question, and a question should not write rows; storing is what hands back a
    usable ``term_id`` and is therefore the owner's. That split is what lets
    anyone ask the question of an imported corpus, which is ownerless and where
    the question is worth most.

    The search is the **same filter** `GET /formal-systems/{id}/theorems/matching`
    runs, and is a filter here too — including its ``exact`` flag, which is a
    ranking hint rather than an answer. Nothing here says "proved", and the
    restraint is deliberate: no digest settles it. The search policy renames
    regex leaves, so it over-reports in a grammar whose numerals are a ``matches``
    production (`exact_is_approximate` says when this system is one); the
    identity policy a discharge compares by would under-report, since a schematic
    theorem instantiates rather than renames. Only unification against a line
    standing in a real scope decides, which is `InferenceRule.concludes` and
    takes a `ProofLine` — a proof's context, and nothing else's
    (`GET /proofs/{id}/lines/{n}/citations`).
    """
    # Readability first and cheaply: a draft you do not own is a 404 here as it
    # is everywhere, and settling that before a system build means a stranger
    # cannot make one happen.
    await readable_system_id_or_404(session, system_id, user)
    # Taken before the build for the reason `/cite` records: the grammar a
    # statement is composed against must be the grammar it would be checked
    # against, and a lock is what makes that provable rather than likely.
    await lock_system(session, system_id)
    built = await build_system(session, system_id)
    require_a_built_system(built)
    system, effective, compiled = built.system, built.effective, built.compiled

    if payload.store and (user is None or system.owner_id != user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the owner can store a term in this system. Ask without "
            "`store` to resolve the statement and search for it.",
        )

    term, context = await resolve_proposal(
        session, payload.statement, system.id, compiled
    )
    rendered = render(term)
    read_back = reparse_statement(compiled, context, rendered)
    if read_back is None or digest_term(read_back) != digest_term(term):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"This statement reads back as {rendered!r}, which is not the term "
            "that was proposed — so no proof line could state it as written.",
        )

    # Flushed for its id, committed at the end: the whole request is one
    # transaction, so the system lock covers the search as well as the write and
    # a caller cannot read a library that moved under it half way through.
    stored = None
    if payload.store:
        row = await session.run_sync(lambda sync: store_term(sync, system, term))
        await session.flush()
        stored = row.id

    # The **search** policy, and deliberately not the one a discharge compares by
    # (`metavariables_only`). "Which theorems could conclude this" wants the
    # coarser bucket — a stored conclusion's `alpha_digest` column carries it, so
    # asking any other way would match nothing. What it must not be used for is a
    # *verdict*: see the docstring, and `exact_is_approximate` below.
    goal = alpha_digest(term)
    # Whether that coarseness bites here. A regex production whose tokens denote
    # constants is the one shape the policy renames wrongly, and it is declared
    # rather than inferred — so this is a lookup rather than a guess.
    approximate = any(
        production.regex is not None and production.denotes_constant
        for production in effective.spec.productions
    )
    # A `Node` names a production; a `Var` or a `Bound` names none, and so
    # narrows nothing — the same case `theorems/matching` refuses outright, which
    # this reports instead because resolving and rendering the statement is
    # useful whether or not it can be searched for.
    constructor = term.constructor.name if isinstance(term, Node) else None
    if constructor is None:
        if payload.store:
            await session.commit()
        return StatementOutcome(
            formal_system_id=system.id,
            term_id=stored,
            rendered=rendered,
            digest=digest_term(term),
            alpha_digest=goal,
            exact_is_approximate=approximate,
        )

    found = await session.run_sync(
        lambda sync: conclusion_candidates(
            sync,
            effective.library,
            constructor,
            alpha_digest=goal,
            limit=payload.limit,
        )
    )
    if payload.store:
        await session.commit()
    return StatementOutcome(
        formal_system_id=system.id,
        term_id=stored,
        rendered=rendered,
        constructor=constructor,
        digest=digest_term(term),
        alpha_digest=goal,
        matches=[
            TheoremCandidate(
                label=candidate.label,
                formal_system_id=candidate.system_id,
                statement_term_id=candidate.statement_term_id,
                statement=candidate.statement,
                primitive=candidate.primitive,
                premise_count=candidate.premise_count,
                exact=candidate.exact,
            )
            for candidate in found.candidates
        ],
        matched=found.matched,
        truncated=found.truncated,
        unindexed=found.unindexed,
        unfiltered=found.unfiltered,
        exact_is_approximate=approximate,
    )
