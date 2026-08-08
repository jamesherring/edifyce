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
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import ColumnElement

    from app.db.models import User

# A query is a name, not an essay. Past this the `AND` is certainly matching
# nothing and each token is another `LIKE` over the whole haystack.
MAX_TOKENS = 8

# How much prose an excerpt carries. Enough for the sentence the match sits in,
# short enough that twenty of them are still a list.
EXCERPT_WIDTH = 240

# Where the query landed, best first. Ordering by this is the whole ranking: a
# corpus label is a mnemonic somebody may know outright (`ax-mp`), its title is
# the sentence a reader recognises, and the body is everything else.
_EXACT, _LABEL, _TITLE, _TEXT = 0, 1, 2, 3

_MATCHED = {_EXACT: "label", _LABEL: "label", _TITLE: "title", _TEXT: "text"}

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
    proof_id: uuid.UUID | None = None
    proof_title: str | None = None
    discouraged_usage: bool = False
    discouraged_modification: bool = False


@dataclass(frozen=True)
class Hits:
    """A page of hits, and how much prose there was to miss.

    ``documented`` is the count this whole search is judged against. A caller
    seeing nothing needs to tell "the words are not in this corpus" from "this
    system documents nothing", and those are the same empty list — the same
    distinction :class:`app.db.retrieval.Candidates` draws with ``unindexed``,
    for the same reason: a short answer must never read as a complete one.
    """

    hits: list[Hit]
    total: int
    documented: int


def tokens_of(query: str) -> list[str]:
    """The words to look for, lowercased and deduplicated.

    Whitespace only — not a tokenizer. Splitting on punctuation would break
    `df-un` and `ax-mp` into pieces that match half the corpus, and those are
    exactly the strings someone types this query with.
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
    query: str,
    tokens: Sequence[str],
    spine: Sequence[uuid.UUID],
    source: int,
) -> tuple[ColumnElement[bool], ColumnElement[int], ColumnElement[int], ColumnElement[int]]:
    """The match condition, rank, source and depth for one of the two haystacks.

    Every token must appear *somewhere* — the label, the title or the body. `AND`
    rather than `OR` because a two-word query is a name and an `OR` over it
    returns everything containing the commoner half, which on a corpus is
    everything.

    **The columns go in bare, never wrapped in `COALESCE`.** A null title yields
    a null comparison, which never matches, which is exactly right — and a
    `COALESCE` around it says the same thing while making the predicate an
    expression no index covers. Measured on the 50,550-row corpus: with it the
    planner sequential-scans at 393 ms, without it the same predicate is a bitmap
    `OR` over the three trigram indexes at 2.8 ms. Coalescing is for the
    *projection*, where a null becomes the empty string an excerpt needs, and a
    projection is not something an index has to serve.
    """
    matches = and_(
        *(
            or_(_contains(label, token), _contains(title, token), _contains(body, token))
            for token in tokens
        )
    )
    rank = case(
        (func.lower(label) == query.strip().lower(), _EXACT),
        (_all_in(label, tokens), _LABEL),
        (_all_in(title, tokens), _TITLE),
        else_=_TEXT,
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
    return matches, rank, literal(source), depth


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
    start = max(0, min(found) - EXCERPT_WIDTH // 3)
    end = min(len(body), start + EXCERPT_WIDTH)
    if start:
        space = body.find(" ", start, end)
        start = start + 1 if space < 0 else space + 1
    if end < len(body):
        space = body.rfind(" ", start, end)
        if space > start:
            end = space
    return f"{'…' if start else ''}{body[start:end].strip()}{'…' if end < len(body) else ''}"


async def search_labels(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    query: str,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> Hits:
    """The labels in ``spine`` whose prose contains every word of ``query``.

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
    words = tokens_of(query)
    if not words:
        # A caller who asked for nothing gets nothing, rather than the corpus: an
        # empty `AND` is vacuously true and would page the whole library.
        return Hits(hits=[], total=0, documented=await _documented(session, spine))

    described, rank, source, depth = _branch(
        label=LabelDescriptionRow.label,
        title=LabelDescriptionRow.title,
        body=LabelDescriptionRow.text,
        system_id=LabelDescriptionRow.formal_system_id,
        query=query,
        tokens=words,
        spine=spine,
        source=_DESCRIPTION,
    )
    descriptions = select(
        LabelDescriptionRow.label.label("label"),
        LabelDescriptionRow.formal_system_id.label("system_id"),
        LabelDescriptionRow.title.label("title"),
        func.coalesce(LabelDescriptionRow.text, "").label("body"),
        rank.label("rank"),
        source.label("source"),
        depth.label("depth"),
    ).where(LabelDescriptionRow.formal_system_id.in_(spine), described)

    matched, rank, source, depth = _branch(
        label=Proof.name,
        title=Proof.title,
        body=Proof.description,
        system_id=Proof.formal_system_id,
        query=query,
        tokens=words,
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

    flags = await _flags(session, spine, [row.label for row in rows])
    links = await proofs_named(session, spine, [row.label for row in rows], viewer)
    return Hits(
        hits=[
            Hit(
                label=row.label,
                system_id=row.system_id,
                title=row.title,
                excerpt=_excerpt(row.body, words),
                matched=_MATCHED[row.rank],
                proof_id=links.get(row.label, (None, None))[0],
                proof_title=links.get(row.label, (None, None))[1],
                discouraged_usage=flags.get(row.label, (False, False))[0],
                discouraged_modification=flags.get(row.label, (False, False))[1],
            )
            for row in rows
        ],
        total=total,
        documented=await _documented(session, spine),
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
) -> dict[str, tuple[bool, bool]]:
    """The discouragement markers for these labels, nearest layer first.

    Read here rather than carried through the union because a hit may have won on
    its *proof* row, which has no such markers — reporting False for a label the
    corpus marks "New usage is discouraged" would be this layer inventing a
    reassurance. It is one indexed query over a page's worth of labels, and it is
    right in every case rather than in most.

    They matter more here than anywhere: a search result is what an aligning
    caller picks a citation from, and `set.mm` discourages 5,169 of its own.
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
    depth = {found: index for index, found in enumerate(spine)}
    found: dict[str, tuple[bool, bool]] = {}
    for system_id, label, usage, modification in sorted(
        rows, key=lambda row: depth[row[0]]
    ):
        found.setdefault(label, (usage, modification))
    return found


async def proofs_named(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    labels: Sequence[str],
    viewer: User | None,
) -> dict[str, tuple[uuid.UUID, str | None]]:
    """Which of these labels are proofs the viewer may open, nearest layer first.

    What it buys a search is that a hit is *followable*. Half of a corpus's
    labels are `$a`s with no proof at all, so this is null as often as not, and
    null is the honest answer — the label is still citable, there is simply
    nothing to open.

    Shared with `app.routers._documentation`, which asks it of a
    cross-reference's target and where it used to live. Moved down here when this
    module wanted the same answer: two copies of a nearest-first resolution is
    two chances for a hit and the link on it to disagree about which layer they
    mean, and the rule belongs beside the query either way.

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
    # `Proof.name` is unique per system but not per spine, so the tie is real —
    # and sorted here rather than left to the `IN`, which returns rows in no
    # order the chain knows about.
    depth = {found: index for index, found in enumerate(spine)}
    resolved: dict[str, tuple[uuid.UUID, str | None]] = {}
    for owner, name, found, title in sorted(rows, key=lambda row: depth[row[0]]):
        resolved.setdefault(name, (found, title))
    return resolved
