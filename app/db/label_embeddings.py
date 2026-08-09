"""Finding a label by what its prose is *about*.

§4.5's other half (docs/informal-source-ingestion-roadmap.md). The lexical search
beside this (:mod:`app.db.label_search`) matches substrings of words, and its
ceiling is written into its own docstring: `Schröder` does not find `Schroeder`,
`compactness` does not find `compact`, and a query sharing no *word* with the
prose scores nothing however well it describes it. A paper does not quote a
theorem in a library's vocabulary — that mismatch **is** the alignment problem —
so the lexical path answers the easy half and stops exactly where the work
starts.

An embedding is the standard answer, and this is the storage and the search for
one.

Where the vectors come from
---------------------------
**The caller.** Nothing here computes an embedding, and that is a decision rather
than an omission:

* this installation configures no embedding provider, and adding one is an
  operational choice — a key, a vendor, a per-request cost, a network hop on a
  read path — that belongs to whoever deploys it rather than to a schema;
* §2 of the ingestion roadmap splits responsibility with the API taking the
  "smaller and deterministic" tasks and the consumer the nuanced ones. Calling a
  model is neither small nor deterministic; and
* AGENTS.md asks the API layer to stay thin.

The consumer this whole roadmap is written for is a model driving an ingestion
run, which has an embedding model to hand already. So the API stores what it is
given and searches it, and a server-side backfill — should anyone want one —
lands behind this same table without changing the read path.

What follows from that is the part that has to be got right: **a vector is only
comparable to vectors from the same model**. Cosine between an OpenAI vector and
a Voyage one is a number with no meaning, and nothing about the two vectors says
they disagree. So ``model`` is stored beside every vector, a search is *against a
named model*, and rows from any other are not candidates. Not a filter for
convenience — the alternative silently ranks noise.

Why not `theorems.embedding`
----------------------------
§4.5 says to wire description text into the column already provisioned there, and
that does not survive contact with the key. A ``theorems`` row is a proof and a
statement term; a description is keyed by ``(system, label)`` and covers a
production, a definition, a primitive theorem or a proof alike — ``df-un`` has no
theorem row and never will, and it is exactly the kind of label whose prose is
worth searching. So the vectors live beside the prose, keyed as the prose is.

Descriptions only, which is narrower than the lexical search
------------------------------------------------------------
:mod:`app.db.label_search` searches two haystacks: the corpus's descriptions and
proofs' own titles. This searches only the first, and the difference is worth
stating rather than leaving to be discovered. A description belongs to the
*system*, so a caller already through the system's gate may read every one of
them; a proof is published-or-yours, so the same table would carry rows whose
visibility differs per reader. Rather than make every vector carry an access
question, the embedded corpus is the documented one — which is also the 50,550
rows the problem is actually about.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk_column
from app.db.descriptions import LabelDescriptionRow
from app.db.models import EMBEDDING_DIMENSIONS

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

# The bounds on a batch and on a neighbour list live on the schemas that enforce
# them (`app.schemas.MAX_EMBEDDING_BATCH`, `SimilarityQuery.limit`), not here.
# Pydantic rejects an oversized body *while parsing* it; a constant checked in the
# route after the fact is a limit announced only once the 300 MB has been read
# (both found in review, where this module held a `MAX_BATCH` the route checked
# late and a `MAX_NEIGHBOURS` nothing referenced at all).


class LabelEmbeddingRow(TimestampMixin, Base):
    """One vector for one label, under one model."""

    __tablename__ = "label_embeddings"
    __table_args__ = (
        # One vector per label per model. Two models are two opinions and both are
        # worth keeping — a corpus embedded under a better model later should not
        # have to be deleted first — but one model saying two things about one
        # label is a bug, and this is where it surfaces.
        Index(
            "uq_label_embeddings_system_label_model",
            "formal_system_id",
            "label",
            "model",
            unique=True,
        ),
        # Cosine, because that is what every text-embedding model is trained for
        # and what `ix_theorems_embedding` already chose. Postgres-only, like the
        # pgvector column it indexes.
        #
        # It indexes every row of the table while a search filters by *system*
        # and model, which is HNSW's known weak spot: the approximate scan
        # produces its candidates first and the filter runs after, so another
        # system's vectors can exhaust the scan and the search comes back short —
        # or empty — with matching rows sitting right there. `_iterative_scan` is
        # the answer and it needs **pgvector 0.8+**, which is what makes that a
        # requirement of this installation rather than a preference.
        Index(
            "ix_label_embeddings_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # The label described, not a foreign key into `label_descriptions`. Keyed as
    # the prose is keyed, for the reason that module gives: one label lands in one
    # of four row types depending on what the importer made of it, and the label
    # is what all four carry.
    label: Mapped[str] = mapped_column(String(128))
    # Which model produced this vector. The whole table turns on it: cosine
    # between two models' vectors is a number with no meaning, and neither vector
    # carries a hint that it is the wrong one. Verbatim and unconstrained — the
    # set of embedding models is not this schema's to enumerate, and a name it
    # refused would be a corpus it could not hold.
    #
    # No index of its own: every question asked of this column is asked *within a
    # system* ("which models are stored here", "this system's vectors under this
    # model"), and the unique index below leads with `formal_system_id`, so a
    # second one would be two indexes for one question.
    model: Mapped[str] = mapped_column(String(128))
    # A JSON array off Postgres, so the table is creatable on the SQLite test
    # database and the routes above it are testable without a server. The
    # *search* still differs by dialect — there is no `<=>` to index against —
    # and `neighbours` says so where it branches.
    # Plain `JSON`, not `models._JSON`, which is itself a variant — SQLAlchemy
    # refuses a variant as another type's variant, and the JSONB half of that one
    # would never apply here anyway.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite")
    )
    # sha256 of the text this vector was made from, so a vector left behind by an
    # edit is *detectable* rather than merely old. A re-import replaces a system's
    # descriptions wholesale (`store_descriptions`), which would otherwise leave
    # every vector pointing at prose that no longer exists, with nothing saying so.
    source_digest: Mapped[str] = mapped_column(String(64))
    # What the vector cost, as the caller reported it. Not used for anything here;
    # kept because a corpus embedded at a known token count is a corpus somebody
    # can decide whether to re-embed.
    tokens: Mapped[int | None] = mapped_column(Integer)


def embeddable_text(title: str | None, text: str) -> str:
    """The canonical prose for a label — what a vector must be made from.

    **Composed here rather than left to the caller**, and returned to it by the
    coverage route, so that every vector in the table is a vector of the same
    thing. A caller free to choose would embed the title on Monday and the title
    plus the prose on Tuesday, and the resulting neighbourhoods would be
    incomparable in a way no column could record.

    Title first because it is the sentence a reader recognises, and it is what a
    paper's own phrasing is closest to.
    """
    return "\n\n".join(part for part in (title, text) if part)


def digest_of(text: str) -> str:
    """The digest stored beside a vector — sha256 of the text it was made from."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Pending:
    """A label wanting a vector under the model asked about, and its text.

    Both kinds: never embedded, and embedded against prose that has since
    changed. A backfill has to do both and this is the only place either one's
    text can be got.
    """

    label: str
    system_id: uuid.UUID
    text: str
    digest: str
    stale: bool = False


@dataclass(frozen=True)
class Coverage:
    """How much of a system is embedded, and under what.

    ``documented`` and ``embedded`` are the pair that makes a thin search result
    readable — the same job `label_search.Hits.documented` does, extended by the
    one thing an embedding search can be short for that a lexical one cannot: the
    corpus may be perfectly well documented and simply not embedded yet.

    ``models`` names every model with a vector here, because "embedded" is not a
    property a system has — it has one per model, and a caller searching under a
    name nobody stored gets nothing for a reason worth being told.
    """

    documented: int
    embedded: int
    stale: int
    models: list[str]
    pending: list[Pending]


@dataclass(frozen=True)
class Neighbour:
    """One label near the query, and how near.

    ``similarity`` is cosine similarity in [-1, 1], not the distance the index
    ranks by, because a caller thresholding on "close enough" thinks in
    similarity and inverting it is a step at which to get a sign wrong.

    ``stale`` says the prose has changed since the vector was made. Reported
    rather than filtered: the vector is still the best evidence available about a
    label, and dropping the hit would answer a question about the corpus with a
    fact about its bookkeeping.
    """

    label: str
    system_id: uuid.UUID
    similarity: float
    title: str | None
    stale: bool


async def store_embeddings(
    session: AsyncSession,
    system_id: uuid.UUID,
    model: str,
    vectors: Iterable[tuple[str, list[float], str, int | None]],
) -> tuple[int, list[str]]:
    """Upsert ``(label, embedding, digest, tokens)`` rows, returning kept and skipped.

    The **caller's** digest is stored, not one taken of the prose as it stands
    now. Hashing the current text here would lose the race the digest exists to
    catch: a description edited between the caller reading its pending text and
    posting the vector would be recorded as though the vector were of the new
    prose (found in review). Storing what the caller says it embedded makes a
    vector that arrives already behind the prose read as stale at once, which is
    what it is.

    A label this system documents nothing about is **skipped rather than
    refused**, and the skipped labels come back by name. A caller embedding a
    corpus works from the pending list and races nothing in particular, but a
    re-import between the two calls drops labels — and failing a 256-label batch
    because one of them went away would make the whole job unresumable.
    """
    batch = list(vectors)
    labels = list({label for label, _, _, _ in batch})
    # Both lookups scoped to the batch's own labels. Reading the system's whole
    # description table instead would be 50,550 rows of prose per 256 vectors —
    # which is the scale this route exists for, so it is the scale to get right.
    #
    # Only the labels, not their prose: what a vector is *of* is the caller's
    # digest now, so this is asking "does this system document that label" and
    # nothing more.
    described = set(
        (
            await session.scalars(
                select(LabelDescriptionRow.label).where(
                    LabelDescriptionRow.formal_system_id == system_id,
                    LabelDescriptionRow.label.in_(labels),
                )
            )
        ).all()
    )
    existing = {
        row.label: row
        for row in await session.scalars(
            select(LabelEmbeddingRow).where(
                LabelEmbeddingRow.formal_system_id == system_id,
                LabelEmbeddingRow.model == model,
                LabelEmbeddingRow.label.in_(labels),
            )
        )
    }

    # Labels, not entries: a batch naming one label twice writes one row, and
    # counting the entries would report two stored against one embedded (found in
    # review). A set rather than a counter because the second write is a real
    # update of the same row — it is not skipped, it is simply not another row.
    written: set[str] = set()
    skipped: list[str] = []
    for label, embedding, digest, tokens in batch:
        if label not in described:
            skipped.append(label)
            continue
        row = existing.get(label)
        if row is None:
            row = LabelEmbeddingRow(
                formal_system_id=system_id, label=label, model=model
            )
            session.add(row)
            existing[label] = row
        row.embedding = embedding
        row.source_digest = digest
        row.tokens = tokens
        written.add(label)
    return len(written), skipped


async def counts(
    session: AsyncSession, spine: Sequence[uuid.UUID], model: str
) -> tuple[int, int]:
    """``(documented, embedded)`` across ``spine`` under one model — two counts.

    :func:`coverage`'s cheap twin, and the one a *search* uses. That one digests
    every description to decide what is stale and what is pending, which is right
    for a job runner asking deliberately and quite wrong behind a query: it would
    put a 50,550-row scan under every nearest-neighbour lookup to report two
    integers that two `COUNT(*)`s already answer.

    Over the **spine**, because that is what the search ranked over. Counted on
    the leaf alone it reported "0 embedded" beside a hit found on an ancestor
    (found in review) — which is the exact overstatement-in-reverse these counts
    exist to prevent, and it is why `coverage` is *not* what this route uses:
    that one is a per-system job report and this is a description of a search.
    """
    documented = (
        await session.scalar(
            select(func.count()).where(
                LabelDescriptionRow.formal_system_id.in_(spine)
            )
        )
    ) or 0
    embedded = (
        await session.scalar(
            select(func.count()).where(
                LabelEmbeddingRow.formal_system_id.in_(spine),
                LabelEmbeddingRow.model == model,
            )
        )
    ) or 0
    return documented, embedded


async def coverage(
    session: AsyncSession,
    system_id: uuid.UUID,
    model: str | None,
    pending_limit: int,
) -> Coverage:
    """What is embedded here, what is stale, and what is still to do.

    The read a backfill runs on: ``pending`` carries each unembedded label
    *together with the text to embed*, so a job never has to compose that itself
    and every vector in the table is a vector of the same thing
    (:func:`embeddable_text`).

    A **stale** row counts as embedded, because it is: the label has a vector and
    searching will find it. What it does not have is a vector of the prose the
    system now carries, and that is a different number.
    """
    documented = (
        await session.scalar(
            select(func.count()).where(
                LabelDescriptionRow.formal_system_id == system_id
            )
        )
    ) or 0
    models = list(
        (
            await session.scalars(
                select(LabelEmbeddingRow.model)
                .where(LabelEmbeddingRow.formal_system_id == system_id)
                .distinct()
                .order_by(LabelEmbeddingRow.model)
            )
        ).all()
    )
    if model is None:
        return Coverage(
            documented=documented, embedded=0, stale=0, models=models, pending=[]
        )

    stored = {
        row.label: row.source_digest
        for row in await session.execute(
            select(LabelEmbeddingRow.label, LabelEmbeddingRow.source_digest).where(
                LabelEmbeddingRow.formal_system_id == system_id,
                LabelEmbeddingRow.model == model,
            )
        )
    }
    # Counted from the **vector** side, not the description side. Walking
    # descriptions never visits a vector whose description is gone — which is
    # precisely the case a re-import creates, since `store_descriptions` replaces
    # a system's prose wholesale — so coverage reported `stale=0` for a label the
    # search was already reporting `stale: true` (found in review). Two answers
    # about one row is worse than either.
    current: set[str] = set(stored)
    pending: list[Pending] = []
    # Columns rather than ORM rows: this walks every description in the system to
    # digest it, and building 50,550 instances to read three fields off each is
    # the avoidable half of that.
    for row in await session.execute(
        select(
            LabelDescriptionRow.label,
            LabelDescriptionRow.title,
            LabelDescriptionRow.text,
        )
        .where(LabelDescriptionRow.formal_system_id == system_id)
        .order_by(LabelDescriptionRow.label)
    ):
        text = embeddable_text(row.title, row.text)
        wanted = digest_of(text)
        digest = stored.get(row.label)
        if digest == wanted:
            # Matched: this vector is of the prose the system now carries, and
            # there is nothing to do about it.
            current.discard(row.label)
            continue
        # Never embedded, or embedded against prose that has since moved. Both
        # are work, both need this text, and this route is the only place to get
        # it — a stale label that appeared in the count and nowhere else left a
        # re-imported system stuck at `stale > 0` with no way to act (found in
        # review).
        if len(pending) < pending_limit:
            pending.append(
                Pending(
                    label=row.label,
                    system_id=system_id,
                    text=text,
                    digest=wanted,
                    stale=digest is not None,
                )
            )
    # What is left is every vector whose prose has moved *or* gone — the same
    # question `neighbours` answers per hit, asked of the whole system.
    stale = len(current)
    return Coverage(
        documented=documented,
        embedded=len(stored),
        stale=stale,
        models=models,
        pending=pending,
    )


async def neighbours(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    model: str,
    query: list[float],
    limit: int,
) -> list[Neighbour]:
    """The labels in ``spine`` whose prose is nearest ``query`` under ``model``.

    Scoped to one model, which is the whole discipline of this table: a vector
    from another model is not a worse candidate, it is not a candidate, and
    including it would rank noise indistinguishably from signal.

    Across the spine for the reason `label_search` is: a layered corpus files each
    statement against the layer its section falls in, and the recognisable names
    are on the foundations.

    **Ordered by the index on Postgres and in Python off it.** ``<=>`` is an
    operator pgvector supplies and SQLite has no equivalent of, so the test
    database sorts in memory — which is right for the tens of rows a test has and
    would be hopeless on a corpus. Both compute the same cosine, so what the
    fallback costs is time rather than a different answer (the same shape
    `_common.lock_system` takes for the advisory lock it cannot take off
    Postgres).
    """
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await _iterative_scan(session)
        distance = LabelEmbeddingRow.embedding.cosine_distance(query)
        rows = (
            await session.execute(
                select(
                    LabelEmbeddingRow.label,
                    LabelEmbeddingRow.formal_system_id,
                    LabelEmbeddingRow.source_digest,
                    distance.label("distance"),
                )
                .where(
                    LabelEmbeddingRow.formal_system_id.in_(spine),
                    LabelEmbeddingRow.model == model,
                )
                .order_by(distance)
                .limit(limit)
            )
        ).all()
        found = [
            (
                row.label,
                row.formal_system_id,
                row.source_digest,
                _similarity(row.distance),
            )
            for row in rows
        ]
    else:
        scored = [
            (
                row.label,
                row.formal_system_id,
                row.source_digest,
                _cosine(query, row.embedding),
            )
            for row in await session.scalars(
                select(LabelEmbeddingRow).where(
                    LabelEmbeddingRow.formal_system_id.in_(spine),
                    LabelEmbeddingRow.model == model,
                )
            )
        ]
        # By label as well, so a tie takes the same slice twice — the same total
        # order the lexical search needs and for the same reason.
        scored.sort(key=lambda found: (-found[3], found[0]))
        found = scored[:limit]

    described = {
        (row.formal_system_id, row.label): row
        for row in await session.scalars(
            select(LabelDescriptionRow).where(
                LabelDescriptionRow.formal_system_id.in_(spine),
                LabelDescriptionRow.label.in_([label for label, _, _, _ in found]),
            )
        )
    }
    hits: list[Neighbour] = []
    for label, system_id, digest, similarity in found:
        row = described.get((system_id, label))
        current = (
            digest_of(embeddable_text(row.title, row.text)) if row is not None else None
        )
        hits.append(
            Neighbour(
                label=label,
                system_id=system_id,
                similarity=similarity,
                title=row.title if row is not None else None,
                # A label whose description is gone is stale in the strongest
                # sense: there is no prose for the vector to be of.
                stale=current != digest,
            )
        )
    return hits


async def embedding_of(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    model: str,
    label: str,
) -> list[float] | None:
    """One label's stored vector, for a search that names a label as its query.

    Nearest-first across the spine, as every other label lookup here resolves: a
    name with no layer means the nearest layer that has one.
    """
    rows = {
        (row.formal_system_id): row.embedding
        for row in await session.execute(
            select(
                LabelEmbeddingRow.formal_system_id, LabelEmbeddingRow.embedding
            ).where(
                LabelEmbeddingRow.formal_system_id.in_(spine),
                LabelEmbeddingRow.model == model,
                LabelEmbeddingRow.label == label,
            )
        )
    }
    for system_id in spine:
        if system_id in rows:
            return list(rows[system_id])
    return None


async def _iterative_scan(session: AsyncSession) -> None:
    """Ask HNSW to keep scanning until the filter is satisfied. **pgvector 0.8+.**

    The index covers every row of the table, and a search filters it by system
    and model — so the approximate scan produces its candidates *first* and the
    filter runs after. Nearby vectors belonging to other systems can exhaust the
    scan, and the route then returns fewer than asked for, or nothing at all,
    while the system has perfectly good matching rows (found in review). Worse
    than slow: silently short, which is the one thing this whole layer refuses.

    `hnsw.iterative_scan` is pgvector's answer — the scan resumes rather than
    stopping at `ef_search` candidates — and it arrived in **0.8**, which this
    installation therefore requires for correct recall. `relaxed_order` rather
    than `strict_order` because the ordering is re-imposed by the `ORDER BY`
    anyway and the relaxed mode is markedly faster.

    Probed rather than set blind: an unknown GUC is an *error*, and an error
    inside a transaction poisons it, so a server older than 0.8 would turn every
    search into a failed transaction rather than a slightly lossy one. Where the
    setting is absent this does nothing and recall is approximate under a filter
    — which is the pre-0.8 behaviour, and the reason the version is a
    requirement rather than a preference.
    """
    known = await session.scalar(
        text("SELECT 1 FROM pg_settings WHERE name = 'hnsw.iterative_scan'")
    )
    if known:
        await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))


def _similarity(distance: float) -> float:
    """Cosine distance as similarity, with pgvector's one non-number handled.

    ``<=>`` against a zero-magnitude vector is NaN — a zero vector has no
    direction, so there is no angle to measure. NaN then serialises to JSON
    ``null``, which contradicts the field's declared `float`, its documented
    [-1, 1], *and* the SQLite branch, which returns 0.0 for the same input
    (found in review, reproduced on pgvector).

    Zero rather than an error, matching that branch: the vector is one a caller
    stored, and "nothing in particular" is a truer answer about it than a 500.
    """
    similarity = 1.0 - distance
    return 0.0 if similarity != similarity else similarity


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    # The SQLite fallback's arithmetic, written out rather than pulled in: numpy
    # is not a dependency of this project and this runs only in tests.
    dot = sum(a * b for a, b in zip(left, right))
    magnitude = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
    # A zero vector has no direction, so it is no distance from anything. Zero
    # rather than a division error: it is a vector a caller stored, and the answer
    # "nothing in particular" is truer than a 500.
    return dot / magnitude if magnitude else 0.0
