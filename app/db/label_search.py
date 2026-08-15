"""Finding a label from the words a paper used for it.

§4.5 of docs/informal-source-ingestion-roadmap.md. A model that has just read
"by the Cantor–Schröder–Bernstein theorem" has a **name** and needs a **label**,
and every search this codebase has is structural: :mod:`app.db.retrieval` narrows
by a conclusion's root production and needs a goal term to do it. That is the
wrong end of the problem. Alignment starts before there is a term — the term is
what the alignment produces — so the only handle at that moment is prose.

The prose is already stored. `set.mm` documents all 50,550 of its assertions
(:mod:`app.db.descriptions`) and it has been readable exactly one label at a time.
This is the same rows with a `WHERE` clause on them.

Two haystacks, not one
----------------------
A corpus label's prose is a :class:`~app.db.descriptions.LabelDescriptionRow`; a
proof authored through the API carries its own ``title``/``description`` and gets
no such row (that module records the split and why). Searching only the first
would answer "what does this system have about compactness" with the imported
half of the system and silently omit everything anyone wrote here — which is the
shape of wrong answer this layer exists to avoid, since a caller cannot tell an
absent result from an absent search. So both are searched and the results are one
list, deduplicated by label.

The proof half is scoped by the same published-or-yours predicate a proof read
applies. The description half is not, because a description belongs to the
*system* and the caller has already been let through to it — which is the rule
``GET /formal-systems/{id}/labels/{label}`` has always applied.

Both span the **spine** rather than the one system id, for the reason
:mod:`app.db.lineage` gives: a layered corpus files each statement against the
layer its section falls in, so a search scoped to a leaf finds a third of the
corpus and none of the foundations, which is where the recognisable names are.

What this is not
----------------
A substring match over words, ranked by where they landed. It has no stemming, no
synonyms and no notion of a phrase: `Schröder` does not find `Schroeder`,
`compactness` does not find `compact`, and a query that shares no *word* with the
prose scores nothing however well it describes it. That is the real ceiling, and
it is the ceiling `theorems.embedding` was provisioned to lift — Phase 4 of
docs/search-and-embeddings-roadmap.md, reached through ``?similar=`` beside this.

Shipping the lexical one first is not a compromise. On a corpus that names things
`cbvald` the *title* is the only thing a model can recognise, a title is prose,
and a `LIKE` over prose needs no new representation and no new storage.

What it costs
-------------
An unanchored `%word%` is not a btree lookup, so this is indexed with `pg_trgm`
(`app.db.models._trigram_index`) — 10 ms for a selective query on a 50,550-row
corpus against 419 ms without. Two characteristics of that are worth knowing
rather than discovering:

* a query whose word is in most of the corpus costs a scan and a sort of
  everything it matched however it is indexed, because deduplicating by label has
  to see every match before it can take twenty. It is the shape a *bad* query has,
  and it returns twenty rows of noise for the money; and
* the index only helps once the table has statistics, so the first searches after
  a bulk import run at the unindexed cost until autovacuum analyses. It converges
  on its own, and is written down here so a slow first search is not read as a
  broken one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, case, func, literal, or_, select

from app.db.descriptions import LabelDescriptionRow
from app.db.models import Proof

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import ColumnElement

    from app.db.models import User

# A query is a name, not an essay. Past this the `AND` is certainly matching
# nothing and each token is another `LIKE` over the whole haystack.
MAX_TOKENS = 8

# How many alternatives one search may carry. Words within an alternative were
# capped from the start and the alternatives themselves were not, which left the
# expensive axis unbounded on an anonymously-readable route: each one adds its
# tokens to the match, to every rank tier and to the credit chain, twice over for
# the two haystacks.
# Measured on the fixture, in statement build and plan cost alone — 1 alternative
# 27 ms, 200 alternatives 486 ms, 500 alternatives 1.59 s (found in review).
#
# Eight, matching `MAX_TOKENS`: expansion is a handful of guesses at what a corpus
# calls something, and a caller with fifty is not expanding, it is enumerating.
MAX_ALTERNATIVES = 8

# How much prose an excerpt carries. Enough for the sentence the match sits in,
# short enough that twenty of them are still a list.
EXCERPT_WIDTH = 240

# Where the query landed, best first: **the tightest single field that holds
# every word**, and then everything else. A corpus label is a mnemonic somebody
# may know outright (`ax-mp`), its title is the sentence a reader recognises, and
# its prose is where the rest of it is.
#
# `_SPREAD` is that "everything else" and it is a category rather than a fallback
# (found in review, where it did not exist and the last arm was an `else_` that
# said "text"). A query whose words are split across two fields — `wi wff`, with
# `wi` the label and "wff" in the title — is in *no* single field, and reporting
# it as a prose match is a claim about a body that may not contain a word of it.
_EXACT, _LABEL, _TITLE, _TEXT, _SPREAD = 0, 1, 2, 3, 4

_MATCHED = {
    _EXACT: "label",
    _LABEL: "label",
    _TITLE: "title",
    _TEXT: "text",
    _SPREAD: "record",
}

# Best first, and the order `_branch`'s `graded` returns one alternative's
# predicates in — the two are indexed against each other.
_TIERS = (_EXACT, _LABEL, _TITLE, _TEXT, _SPREAD)

# Which haystack a label came out of, as the tie-break between two rows for one
# label. The corpus's record wins over a proof's own fields: an import copies the
# title across to `proofs.title` and leaves the prose in the description, so the
# description row is the one that has more to say about the same label.
_DESCRIPTION, _PROOF = 0, 1


@dataclass(frozen=True)
class Hit:
    """One label the words matched, and where they matched it.

    ``matched`` says which of the three the ranking used, because a ranking a
    caller cannot account for is one it has to either trust blindly or ignore —
    and this one has a specific weakness worth being able to see: a common word
    in a long comment scores the same as the same word in the title of the thing
    the caller was actually looking for.

    ``system_id`` is the layer the label lives on, which on a layered corpus is
    not the system that was asked. It is what the label is stored against, so it
    is what a follow-up read has to be addressed to.
    """

    label: str
    system_id: uuid.UUID
    title: str | None
    # The prose around the first token that landed in the body, or None when the
    # match was in the label or the title and there is nothing to point at. The
    # full prose is `GET /formal-systems/{id}/labels/{label}`; a search that
    # served it would ship a corpus comment per row to render a list.
    excerpt: str | None
    matched: str
    # Which of the caller's alternatives found this, as an index into
    # `Hits.searched`. The feedback half of query expansion: a model proposing
    # five phrasings learns which one the corpus actually uses, which is the
    # thing worth carrying into the next lookup.
    matched_query: int = 0
    proof_id: uuid.UUID | None = None
    proof_title: str | None = None
    discouraged_usage: bool = False
    discouraged_modification: bool = False


@dataclass(frozen=True)
class Hits:
    """A page of hits, how much prose there was to miss, and what was asked.

    ``documented`` is the count this whole search is judged against. A caller
    seeing nothing needs to tell "the words are not in this corpus" from "this
    system documents nothing", and those are the same empty list — the same
    distinction :class:`app.db.retrieval.Candidates` draws with ``unindexed``,
    for the same reason: a short answer must never read as a complete one.

    ``searched`` is the words actually used, and it exists because the cap in
    :func:`tokens_of` would otherwise be a silent lie (found in review). The
    contract is "every word must appear"; drop the ninth word quietly and the
    answer is to a *broader* question than the one asked, and every extra row is
    a false positive the caller has no way to identify. Reported rather than
    refused: a caller pasting a sentence from a paper is doing the reasonable
    thing, and the useful response is the search plus a note of what it ran on.
    """

    hits: list[Hit]
    total: int
    documented: int
    # One token list per alternative that ran, in the order given.
    searched: list[list[str]]


def tokens_of(query: str) -> list[str]:
    """The words to look for, lowercased and deduplicated.

    Whitespace only — not a tokenizer. Splitting on punctuation would break
    `df-un` and `ax-mp` into pieces that match half the corpus, and those are
    exactly the strings someone types this query with.

    Capped at :data:`MAX_TOKENS`, which the caller is told about — see
    :attr:`Hits.searched`.
    """
    return list(dict.fromkeys(query.lower().split()))[:MAX_TOKENS]


def _like(token: str) -> str:
    """``token`` as a containment pattern, its wildcards defanged.

    A label is full of characters `LIKE` reads as syntax — `_` is in `df-un`'s
    neighbours and `%` shows up in prose — and an unescaped one silently widens
    the search instead of failing.
    """
    escaped = token.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _contains(column: ColumnElement[str], token: str) -> ColumnElement[bool]:
    return column.ilike(_like(token), escape="\\")


def _all_in(column: ColumnElement[str], tokens: Sequence[str]) -> ColumnElement[bool]:
    return and_(*(_contains(column, token) for token in tokens))


def _branch(
    *,
    label: ColumnElement[str],
    title: ColumnElement[str],
    body: ColumnElement[str],
    system_id: ColumnElement[uuid.UUID],
    queries: Sequence[str],
    variants: Sequence[Sequence[str]],
    spine: Sequence[uuid.UUID],
    source: int,
) -> tuple[
    ColumnElement[bool],
    ColumnElement[int],
    ColumnElement[int],
    ColumnElement[int],
    ColumnElement[int],
]:
    """The match condition, rank, credited alternative, source and depth.

    For one of the two haystacks.

    Every token of *some* variant must appear — the label, the title or the body.
    `AND` within a variant because a two-word query is a name and an `OR` over it
    returns everything containing the commoner half, which on a corpus is
    everything; `OR` *between* variants because that is what alternatives are.

    **Several variants is how query expansion is served** (§4.5). The caller is a
    language model and the thing it is good at is proposing what a corpus might
    have called this — "compact", "Bolzano-Weierstrass", "finite subcover" — so
    the API ranks documents against terms and the consumer decides what the terms
    are. One call rather than one per guess: the same page, the same total, and
    the ranking sees all the alternatives at once rather than the caller having to
    merge N pages itself.

    **The columns go in bare, never wrapped in `COALESCE`.** A null title yields
    a null comparison, which never matches, which is exactly right — and a
    `COALESCE` around it says the same thing while making the predicate an
    expression no index covers. Measured on the 50,550-row corpus: with it the
    planner sequential-scans at 393 ms, without it the same predicate is a bitmap
    `OR` over the three trigram indexes at 2.8 ms. Coalescing is for the
    *projection*, where a null becomes the empty string an excerpt needs, and a
    projection is not something an index has to serve.
    """
    def anywhere(tokens: Sequence[str]) -> ColumnElement[bool]:
        return and_(
            *(
                or_(
                    _contains(label, token),
                    _contains(title, token),
                    _contains(body, token),
                )
                for token in tokens
            )
        )

    def graded(query: str, tokens: Sequence[str]) -> list[ColumnElement[bool]]:
        """What one alternative achieves, one predicate per tier of `_TIERS`."""
        return [
            func.lower(label) == query.strip().lower(),
            _all_in(label, tokens),
            _all_in(title, tokens),
            _all_in(body, tokens),
            anywhere(tokens),
        ]

    # Blank alternatives are skipped but their *indices* are not: `earned` reports
    # a position in the caller's own list, so what is dropped here must not shift
    # what is left.
    scored = [
        (index, graded(queries[index], tokens))
        for index, tokens in enumerate(variants)
        if tokens
    ]
    matches = or_(*(predicates[-1] for _, predicates in scored))
    # Ordered by **rank** rather than by variant, which is what makes this the
    # best score across the alternatives rather than the first one that happened
    # to hit. Written as one `CASE` per tier with an `OR` inside it because
    # `LEAST` is not portable — Postgres has no scalar `min` and SQLite no
    # `least` — and a tier-ordered chain needs neither. The last tier is the
    # `else_`: `matches` is exactly its `OR`, so a row that reached the result set
    # reached it.
    rank = case(
        *(
            (or_(*(predicates[at] for _, predicates in scored)), tier)
            for at, tier in enumerate(_TIERS[:-1])
        ),
        else_=_SPREAD,
    )
    # Which alternative earned that rank. The same chain read the other way —
    # tier-major, so the best tier wins and the caller's earlier guess breaks a
    # tie within it — over the *same predicate objects* `rank` is built from,
    # which is the point (found in review).
    #
    # This used to be recomputed in Python over the page's twenty rows, on the
    # argument that a column would widen the scan to answer a question about the
    # handful of rows that survive it. The cost was real and the answer was wrong:
    # `ilike` and `lower` are the *database's*, and Python's Unicode folding is not
    # SQLite's ASCII-only one, so a label `Ω` against an alternative `ω` was an
    # exact match in Python and no match at all in SQL — the row then reported the
    # tier one alternative reached beside the index of another. Two engines
    # deciding one question cannot be kept in step by care.
    #
    # What it costs is bounded by construction: `earned` evaluates the predicates
    # `rank` already holds, at most once each, so it at worst doubles a `CASE` that
    # is not where this query spends its time — the trigram scan and the dedup sort
    # are. Statement build at the cap of eight alternatives went 3.9 ms to 6.2 ms.
    #
    # `else_` cannot be reached, since `matches` is the last tier's `OR`; it names
    # an alternative that actually ran rather than index 0, which may be a blank.
    earned = case(
        *(
            (predicates[at], literal(index))
            for at in range(len(_TIERS))
            for index, predicates in scored
        ),
        else_=literal(scored[0][0]),
    )
    # A `CASE` over the spine rather than a join: it is a handful of ids, it is
    # already ordered nearest-first, and the alternative is a temporary table to
    # carry six rows. `else_` puts anything unaccounted for last, which cannot
    # happen given the `IN` above and is cheaper than proving it cannot.
    depth = case(
        {found: index for index, found in enumerate(spine)},
        value=system_id,
        else_=len(spine),
    )
    return matches, rank, earned, literal(source), depth


def _excerpt(body: str, tokens: Sequence[str]) -> str | None:
    """The prose around the first token that landed in ``body``.

    Sliced on word boundaries and marked with ellipses when it is a slice, so a
    reader can see that it is one. None when no token is in the body at all,
    which is the ordinary case for a label or title match — an excerpt of prose
    the query never touched would be an answer to a question nobody asked.
    """
    if not body:
        return None
    lowered = body.lower()
    found = [at for at in (lowered.find(token) for token in tokens) if at >= 0]
    if not found:
        return None

    # A third of the window ahead of the match, so the sentence it opens is
    # visible rather than the one it closes.
    at = min(found)
    start = max(0, at - EXCERPT_WIDTH // 3)
    end = min(len(body), start + EXCERPT_WIDTH)
    if start:
        # Forward to a word boundary, but **never past the match**: a run of 240
        # characters with no space in it — a URL, a long `$t` token — put the
        # first space beyond the word that was searched for, and the excerpt came
        # back containing none of the query (found in review). Trimming is a
        # tidiness, and it does not get to cost the thing being excerpted.
        space = body.find(" ", start, end)
        start = min(space + 1, at) if space >= 0 else start
    if end < len(body):
        space = body.rfind(" ", start, end)
        # Likewise at the far end: never cut back past the start of the match.
        if space > start and space > at:
            end = space
    return f"{'…' if start else ''}{body[start:end].strip()}{'…' if end < len(body) else ''}"


async def search_labels(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    queries: Sequence[str],
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> Hits:
    """The labels in ``spine`` matching every word of *any* of ``queries``.

    ``spine`` is `app.db.lineage.spine_ids` of the system being searched, taken as
    an argument rather than walked here so a caller asking several questions about
    one system walks the chain once — as :func:`app.db.descriptions_mapping.mentions_of`
    already does.

    **One row per label.** A label may be described *and* be a proof, and a
    layered fork may spell one twice; both would put the same name on the page
    twice with no way to tell which a citation would resolve to. Nearest layer
    wins, then the corpus's record over a proof's own fields — the same
    nearest-first rule `app.routers._documentation._linkable` resolves a
    cross-reference by, so a hit and the link on it agree about which layer they
    mean.

    Ranked, then by label. The second key is not cosmetic: relevance ties are the
    common case on a rank with four values, and without a total order two reads of
    page 2 are two different pages.
    """
    # Aligned with the caller's own list, empties included, so `matched_query`
    # indexes what it *sent* rather than what survived tokenising — dropping a
    # blank alternative silently shifted every index after it (found in review).
    variants = [tokens_of(query) for query in queries]
    usable = [words for words in variants if words]
    if not usable:
        # A caller who asked for nothing gets nothing, rather than the corpus: an
        # empty `AND` is vacuously true and would page the whole library.
        return Hits(
            hits=[],
            total=0,
            documented=await _documented(session, spine),
            searched=[],
        )

    described, rank, earned, source, depth = _branch(
        label=LabelDescriptionRow.label,
        title=LabelDescriptionRow.title,
        body=LabelDescriptionRow.text,
        system_id=LabelDescriptionRow.formal_system_id,
        queries=queries,
        variants=variants,
        spine=spine,
        source=_DESCRIPTION,
    )
    descriptions = select(
        LabelDescriptionRow.label.label("label"),
        LabelDescriptionRow.formal_system_id.label("system_id"),
        LabelDescriptionRow.title.label("title"),
        func.coalesce(LabelDescriptionRow.text, "").label("body"),
        rank.label("rank"),
        earned.label("earned"),
        source.label("source"),
        depth.label("depth"),
    ).where(LabelDescriptionRow.formal_system_id.in_(spine), described)

    matched, rank, earned, source, depth = _branch(
        label=Proof.name,
        title=Proof.title,
        body=Proof.description,
        system_id=Proof.formal_system_id,
        queries=queries,
        variants=variants,
        spine=spine,
        source=_PROOF,
    )
    readable = [Proof.published_at.is_not(None)]
    if viewer is not None:
        readable.append(Proof.owner_id == viewer.id)
    proofs = select(
        Proof.name.label("label"),
        Proof.formal_system_id.label("system_id"),
        Proof.title.label("title"),
        func.coalesce(Proof.description, "").label("body"),
        rank.label("rank"),
        earned.label("earned"),
        source.label("source"),
        depth.label("depth"),
    ).where(Proof.formal_system_id.in_(spine), or_(*readable), matched)

    combined = descriptions.union_all(proofs).subquery()
    numbered = select(
        combined,
        func.row_number()
        .over(
            partition_by=combined.c.label,
            order_by=(combined.c.rank, combined.c.depth, combined.c.source),
        )
        .label("best"),
    ).subquery()
    unique = select(numbered).where(numbered.c.best == 1).subquery()

    rows = (
        await session.execute(
            select(unique)
            .order_by(unique.c.rank, unique.c.label)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    if offset == 0 and len(rows) < limit:
        # A first page that isn't full already holds every match, so the count is
        # the rows in hand — the same shortcut `_common.paginate_summaries` takes.
        total = len(rows)
    else:
        total = await session.scalar(select(func.count()).select_from(unique)) or 0

    # Both keyed by (layer, label), not by label — a hit *is* a row on a
    # particular layer, and resolving its link or its markers nearest-first would
    # answer about a different one. Two layers may declare the same name, so a
    # `pc-thm` hit reported against the root could otherwise carry the id of a
    # leaf's unrelated `pc-thm` (found in review, reproduced on Postgres).
    labels = [row.label for row in rows]
    flags = await _flags(session, spine, labels)
    links = await proofs_named(session, spine, labels, viewer)
    return Hits(
        hits=[
            Hit(
                label=row.label,
                system_id=row.system_id,
                title=row.title,
                excerpt=_excerpt(row.body, variants[row.earned]),
                matched_query=row.earned,
                matched=_MATCHED[row.rank],
                proof_id=links.get((row.system_id, row.label), (None, None))[0],
                proof_title=links.get((row.system_id, row.label), (None, None))[1],
                discouraged_usage=flags.get((row.system_id, row.label), (False, False))[0],
                discouraged_modification=flags.get(
                    (row.system_id, row.label), (False, False)
                )[1],
            )
            for row in rows
        ],
        total=total,
        documented=await _documented(session, spine),
        searched=[list(words) for words in variants],
    )


async def _documented(session: AsyncSession, spine: Sequence[uuid.UUID]) -> int:
    """How many labels in ``spine`` carry any prose at all — the haystack's size.

    Descriptions only. A proof with no title and no description is a row this
    search cannot see either, but counting proofs here would double every
    imported label (which is both) and make the number mean nothing.
    """
    return (
        await session.scalar(
            select(func.count()).where(
                LabelDescriptionRow.formal_system_id.in_(spine)
            )
        )
    ) or 0


async def _flags(
    session: AsyncSession, spine: Sequence[uuid.UUID], labels: Sequence[str]
) -> dict[tuple[uuid.UUID, str], tuple[bool, bool]]:
    """The discouragement markers for these labels, per layer.

    Read here rather than carried through the union because a hit may have won on
    its *proof* row, which has no such markers — reporting False for a label the
    corpus marks "New usage is discouraged" would be this layer inventing a
    reassurance. It is one indexed query over a page's worth of labels, and it is
    right in every case rather than in most.

    They matter more here than anywhere: a search result is what an aligning
    caller picks a citation from, and `set.mm` discourages 5,169 of its own.

    Keyed by ``(layer, label)`` because a caller has a *hit*, which is a row on a
    known layer, and answering it with a nearer layer's markers for the same name
    is the same class of mistake as linking it to a nearer layer's proof.
    """
    wanted = list(dict.fromkeys(labels))
    if not wanted:
        return {}
    rows = await session.execute(
        select(
            LabelDescriptionRow.formal_system_id,
            LabelDescriptionRow.label,
            LabelDescriptionRow.discouraged_usage,
            LabelDescriptionRow.discouraged_modification,
        ).where(
            LabelDescriptionRow.formal_system_id.in_(spine),
            LabelDescriptionRow.label.in_(wanted),
        )
    )
    return {
        (system_id, label): (usage, modification)
        for system_id, label, usage, modification in rows
    }


async def proofs_named(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    labels: Sequence[str],
    viewer: User | None,
) -> dict[tuple[uuid.UUID, str], tuple[uuid.UUID, str | None]]:
    """Which of these labels are proofs the viewer may open, **per layer**.

    What it buys a search is that a hit is *followable*. Half of a corpus's
    labels are `$a`s with no proof at all, so this is null as often as not, and
    null is the honest answer — the label is still citable, there is simply
    nothing to open.

    Shared with `app.routers._documentation`, which asks it of a
    cross-reference's target and where it used to live. Moved down here when this
    module wanted the same answer.

    **Keyed by (layer, label), because the two callers want different collapses
    of the same rows** — which is exactly why this returns the uncollapsed map
    rather than picking one (found in review, where it picked nearest-first and
    the search inherited an answer about the wrong layer). A cross-reference
    names a label and nothing else, so `_documentation` resolves it nearest-first
    through :func:`nearest`. A search *hit* already names its layer, so it looks
    up that pair and gets the proof its own row is about.

    One query for the whole set rather than one per name: a single comment can
    carry a dozen references and a page of hits twenty labels, and a round trip
    apiece would make resolving the links the expensive half of the read.
    """
    wanted = list(dict.fromkeys(labels))
    if not wanted:
        return {}
    readable = [Proof.published_at.is_not(None)]
    if viewer is not None:
        readable.append(Proof.owner_id == viewer.id)
    rows = await session.execute(
        select(Proof.formal_system_id, Proof.name, Proof.id, Proof.title).where(
            Proof.formal_system_id.in_(spine),
            Proof.name.in_(wanted),
            or_(*readable),
        )
    )
    return {(system_id, name): (found, title) for system_id, name, found, title in rows}


def nearest(
    resolved: Mapping[tuple[uuid.UUID, str], tuple[uuid.UUID, str | None]],
    spine: Sequence[uuid.UUID],
) -> dict[str, tuple[uuid.UUID, str | None]]:
    """Collapse :func:`proofs_named` to one answer per label, nearest layer first.

    For the caller that has a *name* and no layer — a cross-reference target. A
    system's own proof is what its own prose meant, so the chain is walked in the
    order `app.db.lineage.spine_ids` returns it: the system asked about, then what
    it was built on, then what was built on it.

    Sorted rather than left to the query, which returns rows in no order the
    chain knows about. `Proof.name` is unique per system but not per spine, so the
    tie is real.
    """
    depth = {found: index for index, found in enumerate(spine)}
    collapsed: dict[str, tuple[uuid.UUID, str | None]] = {}
    for (system_id, name), found in sorted(
        resolved.items(), key=lambda item: depth[item[0][0]]
    ):
        collapsed.setdefault(name, found)
    return collapsed
