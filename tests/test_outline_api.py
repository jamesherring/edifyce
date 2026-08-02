"""A system's folder tree over HTTP.

The read side of `tests/test_outline_store.py`. For an imported corpus this is
the outline its `.mm` file draws with section headers, which is the difference
between browsing 47,000 proofs and browsing a book.
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
from tests.test_metamath_sections import SOURCE
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.metamath import parse


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "outline")
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


def seed(db_path, publish_proofs: bool = False) -> str:
    """Import the sectioned fixture, published so an anonymous read reaches it.

    ``publish_proofs`` is separate because an import leaves every proof a draft:
    a corpus is ownerless and unpublished, which is exactly the case the counts
    have to get right.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            session.commit()
            proofs = list(session.scalars(select(Proof)))
            proofs[0].formal_system.published_at = proofs[0].created_at
            if publish_proofs:
                for proof in proofs:
                    proof.published_at = proof.created_at
            session.commit()
            return str(report.system_id)
    finally:
        engine.dispose()


def test_the_outline_is_served_as_a_tree(client, db):
    system_id = seed(db)

    roots = client.get(f"/api/formal-systems/{system_id}/folders").json()
    assert [r["name"] for r in roots] == ["LOGIC"]
    (part,) = roots
    assert part["description"] == "The first part, with a note about what it contains."
    assert [c["name"] for c in part["children"]] == ["Implication", "Afterwards"]

    implication = part["children"][0]
    assert [c["name"] for c in implication["children"]] == ["Axioms"]
    assert [c["name"] for c in implication["children"][0]["children"]] == ["The identity"]


def test_a_folder_counts_the_proofs_directly_in_it(client, db):
    # Directly, not cumulatively: a corpus's part-level node holds nothing itself
    # and thousands beneath it, and a subtree total would make every ancestor look
    # equally full.
    system_id = seed(db, publish_proofs=True)

    (part,) = client.get(f"/api/formal-systems/{system_id}/folders").json()
    assert part["proofs"] == 0
    identity = part["children"][0]["children"][0]["children"][0]
    assert (identity["name"], identity["proofs"]) == ("The identity", 1)
    assert part["children"][1]["proofs"] == 1  # `Afterwards` holds `id2`


def test_a_count_omits_proofs_the_reader_cannot_read(client, db):
    # The same rule a single proof read applies. An import is ownerless and every
    # proof in it is a draft, so a published system would otherwise advertise
    # counts for proofs `/proofs/public` omits and `GET /proofs/{id}` 404s on —
    # a disclosure of drafts, and a number nobody can act on.
    system_id = seed(db)

    (part,) = client.get(f"/api/formal-systems/{system_id}/folders").json()
    identity = part["children"][0]["children"][0]["children"][0]
    assert identity["proofs"] == 0
    assert part["children"][1]["proofs"] == 0
    # The structure is still served — it is the file's, not the proofs'.
    assert identity["name"] == "The identity"


def test_a_system_that_draws_no_outline_serves_an_empty_tree(client, db):
    _register_login(client, "ada@example.com")
    created = client.post("/api/formal-systems", json={"name": "Hand authored"})
    assert created.status_code == 201, created.text

    resp = client.get(f"/api/formal-systems/{created.json()['id']}/folders")
    assert resp.status_code == 200 and resp.json() == []


def test_the_outline_of_a_draft_is_owner_only(client, db):
    # Visibility follows the system, as every other read of one does.
    _register_login(client, "ada@example.com")
    draft = client.post("/api/formal-systems", json={"name": "Draft"}).json()["id"]
    assert client.get(f"/api/formal-systems/{draft}/folders").status_code == 200

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get(f"/api/formal-systems/{draft}/folders").status_code == 404
