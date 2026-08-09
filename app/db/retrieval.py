"""Narrowing a library to the theorems that could conclude a goal.

The query half of §9d (docs/authoring-and-ingestion-roadmap.md). A caller holding
a goal — a hole, or the premise a `slot-unsatisfied` failure named — needs to know
which of a system's theorems could conclude it. On the set.mm corpus that is a
question about 47,589 entries, and unifying against every one of them is not an
answer.

It does not need to be. A conclusion's **root production is a column**
(`terms.constructor`), indexed per system, so "theorems whose conclusion is an
implication" is an index scan rather than a search. That is a Metamath-style
head-symbol prefilter, and it is enough to hand the unifier a handful instead of a
library. Confirming a candidate stays
:mod:`website.logical.formal_system.retrieval`; nothing here decides anything.

**A filter, never a verdict.** Every row this returns still has to be unified, and
the order it returns them in is a hint about which to try first. What it must
never do is *drop* a theorem that would have unified — a false negative is a
citation the caller will never be offered and cannot know it missed. Two places
that could happen are handled explicitly rather than left to chance:

* a **translated** layer spells the goal's production differently, so the goal's
  constructor is inverted into each layer's own names before the rows are asked
  (`Translation.stored_name`); and
* an entry whose ``statement_term_id`` is NULL has no constructor to filter on and
  is invisible here. That is a cache miss, not an absence — see
  :class:`Candidates`, which counts them and says so, because a retrieval that
  silently skipped part of the library would read as one that found nothing there.

Sharper indexes are possible and this is deliberately not one of them: a
discrimination tree over the whole term (`docs/search-and-embeddings-roadmap.md`
Phase 1) prunes far harder. The point of doing the cheap one first is that it
needs no new representation and no new storage — only columns that already exist —
and it slots in behind the same interface a better index would.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.fingerprints import fingerprint_filter
from app.db.promoted_theorems import PromotedTheoremPremiseRow, PromotedTheoremRow
from app.db.terms import TermRow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.sql.elements import ColumnElement

    from app.db.promoted_theorems_mapping import LibraryChain
    from website.logical.fingerprint import Fingerprint


@dataclass(frozen=True)
class Candidate:
    """One theorem worth unifying against the goal, and why it is worth it.

    ``exact`` is the α-digest signal: this conclusion *is* the goal up to a
    consistent renaming of its free variables, so no instantiation is needed at
    all. It is the case `alpha_digest` was built for ("have I already got this?"),
    it costs one indexed comparison, and it is a **ranking** hint rather than a
    tier of its own — an exact hit still has to unify, and a non-exact one may
    unify perfectly well by instantiating a metavariable.
    """

    label: str
    system_id: uuid.UUID
    # The interned root of the conclusion, so a matched candidate is *point-at-able*
    # — feed it to `GET /formal-systems/{id}/terms/{id}` to walk its structure
    # rather than reparse `statement`. Never null: the query inner-joins on it, so
    # a theorem without a cached term is `unindexed`, not a candidate.
    statement_term_id: uuid.UUID
    statement: str
    primitive: bool
    premise_count: int
    exact: bool = False


@dataclass(frozen=True)
class Candidates:
    """What the prefilter found, and what it could not see.

    Two counts, and both are the honest part — a short list must never read as a
    complete one.

    ``unindexed``: a theorem whose statement term was never cached (or was
    invalidated) carries no constructor, so no query here can reach it. Reporting
    the count lets a caller distinguish "this library has nothing that concludes
    your goal" from "part of this library is not indexed", and only one of those
    means the search is finished.

    ``unfiltered``: a whole *layer* this filter cannot ask. Two edges do that. One
    that **restates** what it transfers (`Γ ⊢ φ` where the source proved `φ`,
    `wrapping.StatementTemplate`) gives its theorems a conclusion here whose root
    is the template's, while the stored row's root is the source statement's — so
    filtering by the goal's production matches none of them and would be a
    confident empty answer. And one that **renames** a production this system has
    but the layer spells for something else has no pre-image to ask about at all
    (`Translation.stored_name` returning ``None``). Neither is a defect; both are
    edges this filter is too cheap to cross, and saying so is the difference
    between a limitation and a wrong answer.
    """

    candidates: tuple[Candidate, ...] = ()
    # How many rows the prefilter matched, before `limit` cut the list — the head
    # filter alone, or that narrowed by the fingerprint when a goal carries one.
    matched: int = 0
    unindexed: int = 0
    unfiltered: int = 0
    # The per-layer spelling the goal's constructor was asked about, so a caller
    # (or a test) can see a rename having been applied. A layer that was not
    # asked at all is absent.
    asked: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """Whether `limit` hid candidates the filter had already matched."""
        return self.matched > len(self.candidates)


def conclusion_candidates(
    session: Session,
    chain: LibraryChain,
    constructor: str,
    *,
    alpha_digest: str | None = None,
    goal_fingerprint: Fingerprint | None = None,
    limit: int = 25,
    exclude: Sequence[str] = (),
) -> Candidates:
    """Theorems in ``chain`` whose conclusion could unify with the goal.

    ``constructor`` is the goal's root production, in the **citing** system's
    names; each layer is asked about its own spelling of it, and it is the indexed
    head-symbol filter (`ix_terms_system_constructor`).

    ``goal_fingerprint`` sharpens that filter: given it, a per-position
    compatibility test (`app.db.fingerprints.fingerprint_filter`) narrows within
    the constructor bucket, dropping theorems whose conclusion cannot unify with
    the goal below the root. It is layered on top of the head filter and only ever
    removes candidates, so recall is unchanged — a caller still confirms each with
    the kernel. It applies only to **identity-translation layers**, though: the
    fingerprint keys on constructor *signatures*, which a mapped rename edge may
    change (the head filter crosses such an edge by inverting the constructor
    *name*, which a signature has no analogue of here), so a mapped layer falls
    back to the head filter alone rather than risk pruning a real match — see the
    condition below. Absent, retrieval is exactly the head-symbol prefilter it was.
    ``alpha_digest`` is the goal's, and is only ever used to order — pass it and an
    α-identical conclusion sorts first.

    ``exclude`` drops labels the caller already has an answer for, which is what
    keeps a proposal search from re-offering what it has already tried.

    Ordered exact-first, then nearest layer, then by label, and **cut in the
    database**: a corpus where twelve thousand theorems conclude an implication
    must not be assembled in memory to return twenty-five of them. Nearest-layer
    ordering mirrors :func:`~app.db.promoted_theorems_mapping._nearest` — a label
    declared twice means the nearer system's theorem, so the ancestor's would be
    a proposal that resolves to something else.
    """
    if limit <= 0 or not chain.layers:
        return Candidates()

    rank = {layer.system_id: index for index, layer in enumerate(chain.layers)}
    # A translated layer spells the goal's production differently, and inverting
    # the goal's name per layer is what keeps a renamed edge's theorems findable
    # at all. Two layers cannot be asked at all and are counted instead of being
    # quietly answered for — see `Candidates`: one that restates what it carries
    # (the stored root is the source statement's, not the template's), and one
    # whose rename leaves this production without a pre-image.
    asked: dict[uuid.UUID, str] = {}
    skipped: list[uuid.UUID] = []
    for layer in chain.layers:
        stored = (
            layer.translation.stored_name(constructor) if layer.template.identity else None
        )
        if stored is None:
            skipped.append(layer.system_id)
        else:
            asked[layer.system_id] = stored

    unfiltered = _theorem_count(session, skipped)
    if not asked:
        return Candidates(
            unindexed=unindexed_theorems(session, chain), unfiltered=unfiltered
        )

    # Both sides of the join are constrained to the askable layers: the theorem's
    # system for correctness, and the *term's* so the read can use
    # `ix_terms_system_constructor` rather than scanning constructors across every
    # system's graph at once.
    conditions = [
        PromotedTheoremRow.system_id.in_(list(asked)),
        TermRow.formal_system_id.in_(list(asked)),
        _constructor_matches(asked),
        # A label a **nearer** layer also declares resolves to that one, so this
        # entry is not the theorem a citation of it would reach. `_nearest` drops
        # it on the read path; dropping it here too is what keeps a shadowed
        # ancestor from consuming a `limit` slot, being offered under a name that
        # means something else, and lending its α-digest to the wrong theorem.
        ~_shadowed(rank),
    ]
    if goal_fingerprint is not None:
        # The deep half of the prefilter: same rows in, a shorter list out. It
        # reads a JSON column position by position, which no index covers, so it
        # sits *after* the indexed head filter above — the constructor bucket is
        # chosen by the index, this narrows within it.
        #
        # Restricted to identity-translation layers. A fingerprint keys on
        # constructor *signatures* — a string production's surface skeleton, a
        # constant's token — and a **mapped** rename edge is allowed to change both
        # (`translation.py`: only an *unmapped* name is held to equal signatures).
        # The head filter crosses such an edge by inverting the constructor name
        # (`stored_name`), but a stored fingerprint is written in the source's
        # spelling and there is no per-layer inverse for a skeleton here — so
        # comparing it against the goal's spelling would prune a theorem that
        # unifies once rebuilt in this system's constructors, the silent
        # false-negative this filter must never produce. On the spine and any edge
        # that agrees on spelling (`translation.identity`), the signatures match by
        # construction; a mapped layer falls back to the head filter alone, exactly
        # as it did before the fingerprint existed.
        signature_stable = {
            layer.system_id for layer in chain.layers if layer.translation.identity
        } & set(asked)
        if signature_stable:
            deep = fingerprint_filter(
                PromotedTheoremRow.conclusion_fingerprint,
                goal_fingerprint,
                session.get_bind().dialect.name,
            )
            conditions.append(
                or_(
                    PromotedTheoremRow.system_id.notin_(list(signature_stable)),
                    deep,
                )
            )
    if exclude:
        conditions.append(PromotedTheoremRow.label.notin_(list(exclude)))

    matched = session.scalar(
        select(func.count())
        .select_from(PromotedTheoremRow)
        .join(TermRow, TermRow.id == PromotedTheoremRow.statement_term_id)
        .where(*conditions)
    )

    premises = (
        select(func.count())
        .select_from(PromotedTheoremPremiseRow)
        .where(PromotedTheoremPremiseRow.theorem_id == PromotedTheoremRow.id)
        .scalar_subquery()
    )
    is_exact = (
        case((TermRow.alpha_digest == alpha_digest, 0), else_=1)
        if alpha_digest is not None
        else None
    )
    nearest = case(
        *((PromotedTheoremRow.system_id == system_id, index) for system_id, index in rank.items()),
        else_=len(rank),
    )

    rows = session.execute(
        select(
            PromotedTheoremRow.label,
            PromotedTheoremRow.system_id,
            PromotedTheoremRow.statement_term_id,
            PromotedTheoremRow.statement,
            PromotedTheoremRow.primitive,
            premises.label("premises"),
            *([] if is_exact is None else [is_exact.label("exact")]),
        )
        .join(TermRow, TermRow.id == PromotedTheoremRow.statement_term_id)
        .where(*conditions)
        .order_by(
            *([] if is_exact is None else [is_exact]),
            nearest,
            PromotedTheoremRow.label,
        )
        .limit(limit)
    ).all()

    return Candidates(
        candidates=tuple(
            Candidate(
                label=row.label,
                system_id=row.system_id,
                statement_term_id=row.statement_term_id,
                statement=row.statement,
                primitive=row.primitive,
                premise_count=row.premises,
                exact=is_exact is not None and row.exact == 0,
            )
            for row in rows
        ),
        matched=matched or 0,
        unindexed=unindexed_theorems(session, chain),
        unfiltered=unfiltered,
        asked=asked,
    )


def _constructor_matches(asked: dict[uuid.UUID, str]) -> ColumnElement[bool]:
    """The per-layer constructor filter, as one condition.

    A single ``constructor IN (...)`` would be wrong across a rename: it would let
    a layer answer about a *different* layer's spelling, which is a theorem
    retrieved under a name its own system does not use. So the pairing is kept —
    each layer asked about its own name — and the common case (every layer
    agreeing, which is the whole of an inheritance chain) collapses to a single
    equality anyway.
    """
    names = set(asked.values())
    if len(names) == 1:
        return TermRow.constructor == next(iter(names))

    return or_(
        *(
            (TermRow.formal_system_id == system_id) & (TermRow.constructor == name)
            for system_id, name in asked.items()
        )
    )


def _shadowed(rank: dict[uuid.UUID, int]) -> ColumnElement[bool]:
    """Whether a **nearer** layer in the chain declares this row's label too.

    A citation resolves to the nearest layer that has the label, so a shadowed
    ancestor entry is not the theorem anyone would reach by naming it. Expressed
    as a correlated ``EXISTS`` rather than settled after the read, because the
    limit is applied in the database: dropping shadowed rows afterwards would
    leave a short page and a `matched` count that included entries no caller can
    cite.

    Written as an explicit rank comparison rather than a join on position, since
    "nearer" is the chain's order and the chain is not a table.
    """
    nearer = aliased(PromotedTheoremRow)
    nearer_rank = case(
        *((nearer.system_id == system_id, index) for system_id, index in rank.items()),
        else_=len(rank),
    )
    this_rank = case(
        *(
            (PromotedTheoremRow.system_id == system_id, index)
            for system_id, index in rank.items()
        ),
        else_=len(rank),
    )
    return (
        select(nearer.id)
        .where(
            nearer.label == PromotedTheoremRow.label,
            nearer.system_id.in_(list(rank)),
            nearer_rank < this_rank,
        )
        .exists()
    )


def _theorem_count(session: Session, system_ids: Sequence[uuid.UUID]) -> int:
    """How many promoted entries these systems hold, for a count this cannot filter."""
    if not system_ids:
        return 0
    return (
        session.scalar(
            select(func.count())
            .select_from(PromotedTheoremRow)
            .where(PromotedTheoremRow.system_id.in_(list(system_ids)))
        )
        or 0
    )


def unindexed_theorems(session: Session, chain: LibraryChain) -> int:
    """How many of ``chain``'s theorems have no cached conclusion term.

    What the prefilter cannot see. A NULL ``statement_term_id`` is a cache miss —
    the same contract as everywhere else here, where a miss costs a parse and
    never a difference — but retrieval is the one reader that cannot pay that
    price, because it is choosing *which* theorems to look at at all. So the
    count is reported rather than the rows being quietly absent.
    """
    if not chain.layers:
        return 0
    return (
        session.scalar(
            select(func.count())
            .select_from(PromotedTheoremRow)
            .where(
                PromotedTheoremRow.system_id.in_(chain.system_ids),
                PromotedTheoremRow.statement_term_id.is_(None),
            )
        )
        or 0
    )
