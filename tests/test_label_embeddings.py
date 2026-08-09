"""Finding a label by what its prose is about.

§4.5's other half (docs/informal-source-ingestion-roadmap.md). The lexical search
matches substrings of words and says so; a paper does not quote a theorem in a
library's vocabulary, and that mismatch **is** the alignment problem. These cover
the embedding path over the same prose.

The vectors come from the caller — nothing here computes one, and the module
docstring records why — so what these mostly pin is the discipline that follows
from it: a vector is only comparable to vectors from the same model, and neither
vector carries a hint that it is the wrong one.

Storage runs on SQLite through the column's `JSON` variant and the ordering falls
back to Python; the same suite against `EDIFYCE_TEST_DATABASE_URL` exercises
pgvector's `<=>` and the HNSW index, which is the real path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db.descriptions import LabelDescriptionRow
from app.db.label_embeddings import embeddable_text
from app.db.metamath_store import import_corpus
from app.db.models import EMBEDDING_DIMENSIONS
from app.db.session import get_session
from app.main import app
from app.schemas import MAX_EMBEDDING_BATCH
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_descriptions_store import SOURCE
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.metamath import parse

MODEL = "text-embedding-3-small"


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "embeddings")
    create_tables(db_path, _TABLES)

    async_engine = create_async_engine(async_url(db_path), poolclass=NullPool)
    enable_foreign_keys(async_engine.sync_engine)
    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield db_path
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(db, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    with TestClient(app) as test_client:
        yield test_client


def vector(*leading: float) -> list[float]:
    """A full-width vector whose first coordinates are the ones that matter.

    The rest are zero, so cosine between two of these is decided entirely by the
    handful of numbers a test actually writes.
    """
    return list(leading) + [0.0] * (EMBEDDING_DIMENSIONS - len(leading))


def seed(client: TestClient, db_path, owner_email: str = "ada@example.com") -> str:
    """Import the documented fixture into a system the caller owns."""
    return seed_as(client, db_path, _register_login(client, owner_email))


def seed_as(client: TestClient, db_path, owner: str) -> str:
    """The same, for an account the caller has already signed in."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            session.commit()
            import uuid as _uuid

            from app.db.models import FormalSystem

            system = session.get(FormalSystem, report.system_id)
            system.owner_id = _uuid.UUID(owner)
            # An import publishes what it writes; unpublished here so that
            # "readable" means "owned" and the visibility cases below are about
            # something.
            system.published_at = None
            session.commit()
            return str(report.system_id)
    finally:
        engine.dispose()


def coverage(client: TestClient, system_id: str, **params) -> dict:
    res = client.get(f"/api/formal-systems/{system_id}/embeddings", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def upload(client: TestClient, system_id: str, entries: list[dict], model: str = MODEL):
    """Upload, filling in each entry's digest from what `pending` currently says.

    A caller must echo the digest of the text it embedded, which is the whole
    point of the field — so the helper reads it rather than inventing one, and a
    test that wants a *mismatched* digest passes one explicitly.
    """
    texts = {
        entry["label"]: entry["digest"]
        for entry in coverage(client, system_id, model=model, pending=MAX_EMBEDDING_BATCH)[
            "pending"
        ]
    }
    return client.put(
        f"/api/formal-systems/{system_id}/embeddings",
        json={
            "model": model,
            "entries": [
                {"digest": texts.get(entry["label"], "0" * 64), **entry}
                for entry in entries
            ],
        },
    )


def similar(client: TestClient, system_id: str, **body):
    return client.post(f"/api/formal-systems/{system_id}/labels/similar", json=body)


# ---------------------------------------------------------------------------
# What to embed, and knowing what is left
# ---------------------------------------------------------------------------


def test_coverage_hands_out_the_text_to_embed(client, db):
    # The read a backfill runs on. The text is composed server-side rather than
    # left to the caller, so that every vector in the table is a vector of the
    # same thing — a caller free to choose would embed the title on Monday and
    # the title plus the prose on Tuesday.
    system_id = seed(client, db)

    body = coverage(client, system_id, model=MODEL)

    assert body["documented"] == 5
    assert body["embedded"] == 0
    assert body["models"] == []
    pending = {entry["label"]: entry["text"] for entry in body["pending"]}
    assert set(pending) == {"wi", "wn", "df-neg", "ax-1", "id"}
    # Title first, then the prose — the sentence a reader recognises leading.
    assert pending["wn"].startswith("Wff builder for negation.")
    assert "second paragraph" in pending["df-neg"]


def test_coverage_without_a_model_reports_no_embedded_count(client, db):
    # "Embedded" is not a property a system has — it has one per model. Reporting
    # a model-free count would be reporting the maximum over models as though it
    # were the whole, which is exactly the overstatement this layer refuses.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])

    body = coverage(client, system_id)

    assert body["documented"] == 5
    assert body["embedded"] == 0
    assert body["pending"] == []
    # But which models are stored *is* systemwide, and is what a caller needs to
    # know before it can ask a useful question.
    assert body["models"] == [MODEL]


def test_pending_shrinks_as_vectors_land(client, db):
    system_id = seed(client, db)
    assert len(coverage(client, system_id, model=MODEL)["pending"]) == 5

    res = upload(
        client,
        system_id,
        [
            {"label": "wn", "embedding": vector(1.0)},
            {"label": "df-neg", "embedding": vector(0.0, 1.0)},
        ],
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"model": MODEL, "stored": 2, "skipped": []}

    body = coverage(client, system_id, model=MODEL)
    assert body["embedded"] == 2
    assert {entry["label"] for entry in body["pending"]} == {"wi", "ax-1", "id"}


# ---------------------------------------------------------------------------
# The model is the whole discipline
# ---------------------------------------------------------------------------


def test_a_search_only_ranks_vectors_from_its_own_model(client, db):
    # Cosine between two models' vectors is a number with no meaning, and neither
    # vector hints that it is the wrong one. So a vector from another model is
    # not a worse candidate — it is not a candidate.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    upload(
        client,
        system_id,
        [{"label": "df-neg", "embedding": vector(1.0)}],
        model="voyage-3",
    )

    res = similar(client, system_id, model=MODEL, embedding=vector(1.0))

    assert res.status_code == 200, res.text
    body = res.json()
    # `df-neg`'s vector is *identical*, and under another model, so it is absent.
    assert [hit["label"] for hit in body["items"]] == ["wn"]
    assert body["model"] == MODEL
    assert body["embedded"] == 1


def test_two_models_may_both_be_stored_for_one_label(client, db):
    # Two models are two opinions and both are worth keeping: a corpus embedded
    # under a better model later should not have to be deleted first.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    second = upload(
        client,
        system_id,
        [{"label": "wn", "embedding": vector(0.0, 1.0)}],
        model="voyage-3",
    )
    assert second.status_code == 200, second.text

    assert coverage(client, system_id)["models"] == [MODEL, "voyage-3"]
    assert coverage(client, system_id, model=MODEL)["embedded"] == 1
    assert coverage(client, system_id, model="voyage-3")["embedded"] == 1


def test_the_same_label_and_model_is_replaced_not_duplicated(client, db):
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    upload(client, system_id, [{"label": "wn", "embedding": vector(0.0, 1.0)}])

    assert coverage(client, system_id, model=MODEL)["embedded"] == 1
    # And the *second* vector is what searching finds.
    body = similar(client, system_id, model=MODEL, embedding=vector(0.0, 1.0)).json()
    assert body["items"][0]["similarity"] == pytest.approx(1.0)


def test_a_search_under_a_model_nobody_stored_says_so_with_a_count(client, db):
    # The distinction that makes an empty answer readable, and one the lexical
    # search has no need of: a corpus can be perfectly well documented and simply
    # not embedded yet.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])

    body = similar(client, system_id, model="nobody-stored-this", embedding=vector(1.0)).json()

    assert body["items"] == []
    assert body["embedded"] == 0
    assert body["documented"] == 5


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_nearest_comes_first_and_similarity_is_cosine(client, db):
    system_id = seed(client, db)
    upload(
        client,
        system_id,
        [
            {"label": "wn", "embedding": vector(1.0, 0.0)},
            {"label": "wi", "embedding": vector(0.0, 1.0)},
            {"label": "df-neg", "embedding": vector(1.0, 1.0)},
        ],
    )

    body = similar(client, system_id, model=MODEL, embedding=vector(1.0, 0.0)).json()

    assert [hit["label"] for hit in body["items"]] == ["wn", "df-neg", "wi"]
    # Cosine in [-1, 1], not the distance the index ranks by: a caller
    # thresholding on "close enough" thinks in similarity.
    assert body["items"][0]["similarity"] == pytest.approx(1.0)
    assert body["items"][1]["similarity"] == pytest.approx(0.7071, abs=1e-3)
    assert body["items"][2]["similarity"] == pytest.approx(0.0, abs=1e-6)


def test_a_label_may_name_the_query_point(client, db):
    # The query-string-shaped half of §4.5's `?similar=` idea: "what else is
    # about what this is about", with no embedding model needed at the call site.
    system_id = seed(client, db)
    upload(
        client,
        system_id,
        [
            {"label": "wn", "embedding": vector(1.0, 0.0)},
            {"label": "df-neg", "embedding": vector(0.99, 0.1)},
            {"label": "wi", "embedding": vector(0.0, 1.0)},
        ],
    )

    body = similar(client, system_id, model=MODEL, label="wn", limit=2).json()

    assert [hit["label"] for hit in body["items"]] == ["wn", "df-neg"]
    assert body["items"][0]["similarity"] == pytest.approx(1.0)


def test_a_label_with_no_vector_cannot_be_the_query_point(client, db):
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])

    res = similar(client, system_id, model=MODEL, label="df-neg")

    assert res.status_code == 404
    assert "nothing to search near" in res.json()["detail"]


def test_a_query_must_name_exactly_one_point(client, db):
    system_id = seed(client, db)

    for body in (
        {"model": MODEL},
        {"model": MODEL, "label": "wn", "embedding": vector(1.0)},
    ):
        res = similar(client, system_id, **body)
        assert res.status_code == 422, res.text


def test_a_hit_carries_its_title_and_layer(client, db):
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])

    (hit,) = similar(client, system_id, model=MODEL, embedding=vector(1.0)).json()["items"]

    assert hit["title"] == "Wff builder for negation."
    assert hit["formal_system_id"] == system_id


# ---------------------------------------------------------------------------
# Staleness — a vector of prose that has changed
# ---------------------------------------------------------------------------


def test_a_vector_whose_prose_changed_is_reported_stale(client, db):
    # A re-import replaces a system's descriptions wholesale, which would
    # otherwise leave every vector pointing at prose that no longer exists with
    # nothing saying so.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert coverage(client, system_id, model=MODEL)["stale"] == 0
    assert similar(client, system_id, model=MODEL, embedding=vector(1.0)).json()["items"][0][
        "stale"
    ] is False

    # The prose moves under the vector, as a re-import would move it.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            row = session.scalars(
                select(LabelDescriptionRow).where(
                    LabelDescriptionRow.label == "wn"
                )
            ).one()
            row.title = "A different sentence entirely."
            row.text = "A different sentence entirely."
            session.commit()
    finally:
        engine.dispose()

    body = coverage(client, system_id, model=MODEL)
    # Still embedded — the label has a vector and searching finds it. What it no
    # longer has is a vector of the prose the system now carries.
    assert body["embedded"] == 1
    assert body["stale"] == 1

    hit = similar(client, system_id, model=MODEL, embedding=vector(1.0)).json()["items"][0]
    # Reported rather than filtered: the vector is still the best evidence
    # available about the label.
    assert hit["label"] == "wn"
    assert hit["stale"] is True


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_vector_of_the_wrong_width_is_another_models(client, db):
    system_id = seed(client, db)

    res = upload(client, system_id, [{"label": "wn", "embedding": [1.0, 0.0, 0.0]}])

    assert res.status_code == 422
    assert "another model's" in res.json()["detail"]
    # Named, so a 256-label batch says which one.
    assert "'wn'" in res.json()["detail"]


def test_a_query_of_the_wrong_width_is_refused(client, db):
    system_id = seed(client, db)
    res = similar(client, system_id, model=MODEL, embedding=[1.0, 0.0])
    assert res.status_code == 422
    assert "different width" in res.json()["detail"]


def test_a_label_the_system_documents_nothing_about_is_skipped_by_name(client, db):
    # Skipped rather than refused: a backfill works from `pending`, and failing a
    # 256-label batch because a re-import dropped one of them would make the job
    # unresumable.
    system_id = seed(client, db)

    res = upload(
        client,
        system_id,
        [
            {"label": "wn", "embedding": vector(1.0)},
            {"label": "nosuch", "embedding": vector(1.0)},
        ],
    )

    assert res.status_code == 200, res.text
    assert res.json() == {"model": MODEL, "stored": 1, "skipped": ["nosuch"]}


def test_only_the_owner_may_store_vectors(client, db):
    system_id = seed(client, db)
    client.post("/api/auth/logout")
    # Posted directly rather than through the helper, which reads `pending` to
    # fill in the digest and is itself gated on being able to read the system.
    body = {
        "model": MODEL,
        "entries": [
            {"label": "wn", "embedding": vector(1.0), "digest": "0" * 64}
        ],
    }
    path = f"/api/formal-systems/{system_id}/embeddings"

    assert client.put(path, json=body).status_code == 401

    _register_login(client, "bob@example.com")
    assert client.put(path, json=body).status_code == 404


def test_reading_coverage_follows_the_system(client, db):
    # A draft system's coverage says which labels it documents and what their
    # prose is, which is what the label routes say — so it is gated the same way.
    system_id = seed(client, db)
    client.post("/api/auth/logout")

    assert client.get(f"/api/formal-systems/{system_id}/embeddings").status_code == 404
    assert similar(client, system_id, model=MODEL, embedding=vector(1.0)).status_code == 404


# ---------------------------------------------------------------------------
# What the review found: five ways a count or a number could be wrong
# ---------------------------------------------------------------------------


def test_the_counts_cover_what_was_ranked_not_just_the_leaf(client, db):
    # A search ranks over the whole spine, so counting the leaf alone reported
    # "0 embedded" beside a hit found on an ancestor — which is the exact
    # overstatement-in-reverse these counts exist to prevent.
    owner = _register_login(client, "ada@example.com")
    parent = seed_as(client, db, owner)
    upload(client, parent, [{"label": "wn", "embedding": vector(1.0)}])
    published = client.patch(
        f"/api/formal-systems/{parent}", json={"published": True}
    )
    assert published.status_code == 200, published.text
    child = client.post(
        "/api/formal-systems", json={"name": "Child", "inherits_from_id": parent}
    ).json()["id"]

    body = similar(client, child, model=MODEL, embedding=vector(1.0)).json()

    # The hit comes from the ancestor…
    assert [hit["formal_system_id"] for hit in body["items"]] == [parent]
    # …and so must the counts describing what it was found among.
    assert body["embedded"] == 1
    assert body["documented"] == 5


def test_a_vector_whose_description_is_gone_counts_as_stale(client, db):
    # Counted from the description side, a vector whose description was deleted
    # is never visited — and that is exactly what a re-import produces, since
    # `store_descriptions` replaces a system's prose wholesale. Coverage said
    # `stale=0` for a label the search was already reporting `stale: true`.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert coverage(client, system_id, model=MODEL)["stale"] == 0

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.delete(
                session.scalars(
                    select(LabelDescriptionRow).where(
                        LabelDescriptionRow.label == "wn"
                    )
                ).one()
            )
            session.commit()
    finally:
        engine.dispose()

    body = coverage(client, system_id, model=MODEL)
    assert body["embedded"] == 1
    assert body["stale"] == 1
    # And the two halves agree, which is the point — two answers about one row
    # is worse than either.
    hit = similar(client, system_id, model=MODEL, embedding=vector(1.0)).json()["items"][0]
    assert hit["stale"] is True


def test_a_zero_vector_scores_zero_rather_than_not_a_number(client, db):
    # A zero vector has no direction, so pgvector's `<=>` is NaN — which
    # serialises to JSON null, contradicting the field's declared float, its
    # documented [-1, 1], and the SQLite branch, which returns 0.0 for the same
    # input. Zero rather than an error: the vector is one a caller stored, and
    # "nothing in particular" is truer about it than a 500.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])

    body = similar(client, system_id, model=MODEL, embedding=vector(0.0)).json()

    (hit,) = body["items"]
    assert hit["similarity"] == 0.0
    assert isinstance(hit["similarity"], float)


def test_a_label_twice_in_one_batch_is_one_row_and_counted_once(client, db):
    # Counting entries rather than rows reported two stored against one embedded.
    # The second write is a real update of the same row — not skipped, simply not
    # another row.
    system_id = seed(client, db)

    res = upload(
        client,
        system_id,
        [
            {"label": "wn", "embedding": vector(1.0)},
            {"label": "wn", "embedding": vector(0.0, 1.0)},
        ],
    )

    assert res.status_code == 200, res.text
    assert res.json()["stored"] == 1
    assert coverage(client, system_id, model=MODEL)["embedded"] == 1


def test_an_oversized_batch_is_refused_while_it_is_parsed(client, db):
    # Bounded on the schema rather than checked in the route: a limit enforced
    # after the body has been read and turned into floats is no limit at all on a
    # body meant to be large.
    system_id = seed(client, db)

    res = upload(
        client,
        system_id,
        [
            {"label": f"l{n}", "embedding": vector(1.0)}
            for n in range(MAX_EMBEDDING_BATCH + 1)
        ],
    )

    assert res.status_code == 422, res.text


def test_a_vector_is_bound_to_the_text_it_was_made_from(client, db):
    # Hashing the *current* database text at upload time loses the race the
    # digest exists to catch: a description edited between the caller reading its
    # pending text and posting the vector would be recorded as though the vector
    # were of the new prose, marking a stale vector current and defeating the
    # whole mechanism.
    system_id = seed(client, db)
    (pending,) = [
        entry
        for entry in coverage(client, system_id, model=MODEL)["pending"]
        if entry["label"] == "wn"
    ]

    # The prose moves while the caller is off embedding the text it was handed.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            row = session.scalars(
                select(LabelDescriptionRow).where(LabelDescriptionRow.label == "wn")
            ).one()
            row.text = "Rewritten while the caller was busy."
            session.commit()
    finally:
        engine.dispose()

    res = client.put(
        f"/api/formal-systems/{system_id}/embeddings",
        json={
            "model": MODEL,
            "entries": [
                {
                    "label": "wn",
                    "embedding": vector(1.0),
                    # The digest of what was actually embedded.
                    "digest": pending["digest"],
                }
            ],
        },
    )
    assert res.status_code == 200, res.text

    # Stale on arrival, which is exactly what it is — the vector is of prose the
    # system no longer carries.
    assert coverage(client, system_id, model=MODEL)["stale"] == 1
    hit = similar(client, system_id, model=MODEL, embedding=vector(1.0)).json()["items"][0]
    assert hit["stale"] is True


def test_a_stale_label_comes_back_with_the_text_to_re_embed(client, db):
    # Counted and nowhere else, a stale label left a re-imported system stuck at
    # `stale > 0` with no way to act: this route is the only place its canonical
    # text can be got.
    system_id = seed(client, db)
    upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert coverage(client, system_id, model=MODEL)["stale"] == 0

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            row = session.scalars(
                select(LabelDescriptionRow).where(LabelDescriptionRow.label == "wn")
            ).one()
            row.text = "Something else entirely."
            session.commit()
    finally:
        engine.dispose()

    body = coverage(client, system_id, model=MODEL)
    assert body["stale"] == 1
    (entry,) = [e for e in body["pending"] if e["label"] == "wn"]
    assert entry["stale"] is True
    assert "Something else entirely." in entry["text"]

    # And acting on it clears the debt, which is the point of listing it.
    again = upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert again.status_code == 200, again.text
    assert coverage(client, system_id, model=MODEL)["stale"] == 0


def test_a_coordinate_that_is_not_a_number_is_refused(client, db):
    # JSON can carry `1e400`, which parses to `inf` — which pgvector refuses at
    # the *insert*, turning malformed input into a 500 rather than a 422, and
    # which the SQLite path stores happily before producing a similarity that
    # will not serialise.
    system_id = seed(client, db)
    path = f"/api/formal-systems/{system_id}/embeddings"

    res = client.put(
        path,
        content=(
            '{"model": "' + MODEL + '", "entries": [{"label": "wn", "digest": "'
            + "0" * 64
            + '", "embedding": [1e400' + ", 0.0" * (EMBEDDING_DIMENSIONS - 1) + "]}]}"
        ),
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 422, res.text

    # And on the query side too, where the same value would rank everything NaN.
    query = client.post(
        f"/api/formal-systems/{system_id}/labels/similar",
        content=(
            '{"model": "' + MODEL + '", "embedding": [1e400'
            + ", 0.0" * (EMBEDDING_DIMENSIONS - 1)
            + "]}"
        ),
        headers={"content-type": "application/json"},
    )
    assert query.status_code == 422, query.text


def test_the_text_composed_is_the_text_digested():
    # The one function both halves depend on agreeing about: `pending` hands this
    # out and the stored digest is taken over it, so a caller that embeds exactly
    # what it was given is never reported stale on arrival.
    assert embeddable_text("A title.", "The prose.") == "A title.\n\nThe prose."
    assert embeddable_text(None, "The prose.") == "The prose."
    assert embeddable_text("A title.", "") == "A title."
