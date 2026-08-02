"""Descriptions, titles and authorship over HTTP.

The read side of `tests/test_descriptions_store.py`: an imported corpus is
documented, and this is how a client sees it. Two routes carry it — a proof's own
read, which also brings the corpus's record of its label, and a system's label
route, which is how the *other three* kinds of label are reached (a production, a
definition and a primitive theorem have no proof to hang documentation on, and
`df-un` and `ax-ext` are exactly those).
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
from app.db.metamath_store import import_corpus
from app.db.models import Proof
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_descriptions_store import SOURCE
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.metamath import parse


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "descriptions")
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


def seed(db_path) -> tuple[str, str]:
    """Import the documented fixture, published so an anonymous read reaches it."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            session.commit()
            proof = session.scalars(select(Proof)).one()
            # An import is ownerless, so publishing is what makes it readable.
            proof.published_at = proof.created_at
            system_row = proof.formal_system
            system_row.published_at = proof.created_at
            session.commit()
            return str(report.system_id), str(proof.id)
    finally:
        engine.dispose()


def test_a_proof_carries_its_title_and_the_corpus_record_of_its_label(client, db):
    _, proof_id = seed(db)

    body = client.get(f"/api/proofs/{proof_id}").json()
    # The label stays the identity; the title is the sentence.
    assert body["name"] == "id"
    assert body["title"] == "Principle of identity."

    doc = body["documentation"]
    assert doc["label"] == "id"
    assert doc["title"] == "Principle of identity."
    assert [(a["kind"], a["who"], a["dated"]) for a in doc["attributions"]] == [
        ("Contributed", "NM", "4-Apr-1994"),
        ("Proof shortened", "Wolf Lammen", "8-Sep-2012"),
    ]


def test_a_label_with_no_proof_is_read_from_the_system(client, db):
    # The case the route exists for. `df-neg` is a `$a`: it became a definition,
    # has no proof, and is where the interesting prose lives.
    system_id, _ = seed(db)

    body = client.get(f"/api/formal-systems/{system_id}/labels/df-neg").json()
    assert body["title"] == "Define negation as implying a falsehood."
    assert body["text"].count("\n\n") == 1
    assert [a["who"] for a in body["attributions"]] == ["NM", "Mario Carneiro"]


def test_a_label_the_system_does_not_describe_is_a_404(client, db):
    system_id, _ = seed(db)
    assert client.get(f"/api/formal-systems/{system_id}/labels/nosuch").status_code == 404


def test_a_hand_authored_proof_has_a_title_it_sets_and_no_corpus_record(client, db):
    # The other half: `documentation` is the *system's* record, which a system
    # nobody imported keeps none of. The proof's own title is still its own.
    _register_login(client, "ada@example.com")
    created = client.post("/api/formal-systems", json={"name": "Hand authored"})
    assert created.status_code == 201, created.text
    system_id = created.json()["id"]

    made = client.post(
        "/api/proofs",
        json={
            "name": "assoc",
            "formal_system_id": system_id,
            "title": "Conjunction is associative.",
        },
    )
    assert made.status_code == 201, made.text
    assert made.json()["title"] == "Conjunction is associative."

    body = client.get(f"/api/proofs/{made.json()['id']}").json()
    assert body["documentation"] is None
    assert body["title"] == "Conjunction is associative."

    # And it is editable, which is why it is a column rather than a derivation.
    patched = client.patch(
        f"/api/proofs/{made.json()['id']}", json={"title": "Associativity of ∧."}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Associativity of ∧."


def test_a_title_can_be_cleared(client, db):
    # Null and "" are different answers, and a PATCH must be able to reach the
    # first: an imported title a reader disagrees with should be removable, not
    # only replaceable.
    _register_login(client, "ada@example.com")
    system_id = client.post("/api/formal-systems", json={"name": "Hand authored"}).json()["id"]
    proof_id = client.post(
        "/api/proofs",
        json={"name": "assoc", "formal_system_id": system_id, "title": "Something."},
    ).json()["id"]

    assert client.patch(f"/api/proofs/{proof_id}", json={"title": None}).json()["title"] is None
