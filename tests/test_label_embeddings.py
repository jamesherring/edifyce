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
    owner = _register_login(client, owner_email)
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
    return client.put(
        f"/api/formal-systems/{system_id}/embeddings",
        json={"model": model, "entries": entries},
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

    anonymous = upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert anonymous.status_code == 401

    _register_login(client, "bob@example.com")
    stranger = upload(client, system_id, [{"label": "wn", "embedding": vector(1.0)}])
    assert stranger.status_code == 404


def test_reading_coverage_follows_the_system(client, db):
    # A draft system's coverage says which labels it documents and what their
    # prose is, which is what the label routes say — so it is gated the same way.
    system_id = seed(client, db)
    client.post("/api/auth/logout")

    assert client.get(f"/api/formal-systems/{system_id}/embeddings").status_code == 404
    assert similar(client, system_id, model=MODEL, embedding=vector(1.0)).status_code == 404


def test_the_text_composed_is_the_text_digested():
    # The one function both halves depend on agreeing about: `pending` hands this
    # out and the stored digest is taken over it, so a caller that embeds exactly
    # what it was given is never reported stale on arrival.
    assert embeddable_text("A title.", "The prose.") == "A title.\n\nThe prose."
    assert embeddable_text(None, "The prose.") == "The prose."
    assert embeddable_text("A title.", "") == "A title."
