"""A system's folder tree over HTTP.

The read side of `tests/test_outline_store.py`. For an imported corpus this is
the outline its `.mm` file draws with section headers, which is the difference
between browsing 47,000 proofs and browsing a book.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

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
from app.db.models import Proof, ProofFolder
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


def seed(db_path, draft_proofs: bool = False) -> str:
    """Import the sectioned fixture. An import publishes the system and every
    proof that verified, so an anonymous read reaches them as they stand.

    ``draft_proofs`` puts the proofs back to drafts — a system published over
    proofs that are not, which is the case the counts have to get right.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            if draft_proofs:
                for proof in session.scalars(select(Proof)):
                    proof.published_at = None
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
    system_id = seed(db)

    (part,) = client.get(f"/api/formal-systems/{system_id}/folders").json()
    assert part["proofs"] == 0
    identity = part["children"][0]["children"][0]["children"][0]
    assert (identity["name"], identity["proofs"]) == ("The identity", 1)
    assert part["children"][1]["proofs"] == 1  # `Afterwards` holds `id2`


def test_a_count_omits_proofs_the_reader_cannot_read(client, db):
    # The same rule a single proof read applies: a published system must not
    # advertise counts for proofs `/proofs/public` omits and `GET /proofs/{id}`
    # 404s on — a disclosure of drafts, and a number nobody can act on. An import
    # no longer produces that state on its own, so it is made here.
    system_id = seed(db, draft_proofs=True)

    (part,) = client.get(f"/api/formal-systems/{system_id}/folders").json()
    identity = part["children"][0]["children"][0]["children"][0]
    assert identity["proofs"] == 0
    assert part["children"][1]["proofs"] == 0
    # The structure is still served — it is the file's, not the proofs'.
    assert identity["name"] == "The identity"


def test_another_users_folder_is_not_in_the_tree(client, db):
    # An imported outline is ownerless — it is the file's structure, and the
    # system read has already settled whether this viewer may see it. A folder
    # someone *owns* is theirs. Nothing sets an owner today, which is why the
    # predicate is here: a later per-user folder must not arrive as a leak.
    system_id = seed(db)
    other = _register_login(client, "someone@example.com")
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.add(
                ProofFolder(
                    formal_system_id=uuid.UUID(system_id),
                    owner_id=uuid.UUID(other),
                    name="Private notes",
                    slug="private-notes",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    # Its owner sees it beside the outline...
    names = [f["name"] for f in client.get(f"/api/formal-systems/{system_id}/folders").json()]
    assert "Private notes" in names

    # ...and nobody else does, while the outline itself is unaffected.
    assert client.post("/api/auth/logout").status_code == 204
    anonymous = client.get(f"/api/formal-systems/{system_id}/folders").json()
    assert [f["name"] for f in anonymous] == ["LOGIC"]


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


# ---------------------------------------------------------------------------
# Reading the proofs a node of the outline holds
# ---------------------------------------------------------------------------
#
# The tree names sections and counts them; this is what turns one of those counts
# into the proofs behind it. Without it the outline is a table of contents for a
# book with no pages: the only public listing is every published proof at once,
# which for a corpus is 47,000 of them in one order nobody asked for.


def _folder_named(client, system_id: str, name: str) -> str:
    """The id of the outline node called ``name``, wherever it sits."""
    def walk(nodes):
        for node in nodes:
            if node["name"] == name:
                return node["id"]
            found = walk(node["children"])
            if found is not None:
                return found
        return None

    found = walk(client.get(f"/api/formal-systems/{system_id}/folders").json())
    assert found is not None, name
    return found


def test_the_public_listing_scopes_to_one_folder(client, db):
    system_id = seed(db)
    identity = _folder_named(client, system_id, "The identity")

    page = client.get("/api/proofs/public", params={"folder_id": identity})
    assert page.status_code == 200
    assert [p["name"] for p in page.json()["items"]] == ["id"]
    # `total` describes the scoped set, not the whole shelf — it is what pages the
    # list, so a count of everything would offer pages that come back empty.
    assert page.json()["total"] == 1

    # And the sibling section holds the other one, rather than both showing both.
    afterwards = _folder_named(client, system_id, "Afterwards")
    page = client.get("/api/proofs/public", params={"folder_id": afterwards})
    assert [p["name"] for p in page.json()["items"]] == ["id2"]


def test_a_system_scope_is_the_whole_corpus_in_file_order(client, db):
    # Position, not publication recency: an import publishes every proof at one
    # instant, so ordering by it falls through to `created_at DESC` and hands back
    # a corpus backwards. `id` precedes `id2` in the file and must here too.
    system_id = seed(db)

    # Stamped apart, and in import order, so the two orderings genuinely disagree
    # — a fixture whose rows share a timestamp would pass either way. Under SQLite
    # they do share one: its CURRENT_TIMESTAMP has second precision.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            for offset, proof in enumerate(
                session.scalars(select(Proof).order_by(Proof.position))
            ):
                proof.created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=offset)
            session.commit()
    finally:
        engine.dispose()

    page = client.get("/api/proofs/public", params={"formal_system_id": system_id})
    assert [p["name"] for p in page.json()["items"]] == ["id", "id2"]
    # The unscoped list is the one that leads with the newest.
    page = client.get("/api/proofs/public")
    assert [p["name"] for p in page.json()["items"]] == ["id2", "id"]


def test_a_page_is_cut_by_a_unique_key_when_the_order_ties(client, db):
    # An import gives every proof one `published_at` and — under Postgres, where
    # `created_at` defaults to the *transaction's* `now()` — one `created_at` per
    # batch. With nothing unique last in the ORDER BY the database may cut that
    # tied block differently per query, so paging repeats rows and skips others.
    # Forced here by tying every key the listings sort on.
    system_id = seed(db)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            for proof in session.scalars(select(Proof)):
                proof.position = 0
                proof.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            session.commit()
            by_id = [
                proof.name
                for proof in session.scalars(select(Proof).order_by(Proof.id))
            ]
    finally:
        engine.dispose()

    def page(offset: int, **scope) -> list[str]:
        response = client.get(
            "/api/proofs/public", params={"limit": 1, "offset": offset, **scope}
        )
        return [p["name"] for p in response.json()["items"]]

    for scope in ({}, {"formal_system_id": system_id}):
        assert [page(0, **scope), page(1, **scope)] == [[by_id[0]], [by_id[1]]]


def test_a_scoped_listing_still_omits_drafts(client, db):
    # The scope narrows the published list; it does not become a way into it.
    system_id = seed(db, draft_proofs=True)
    identity = _folder_named(client, system_id, "The identity")

    page = client.get("/api/proofs/public", params={"folder_id": identity})
    assert page.status_code == 200
    assert page.json()["items"] == [] and page.json()["total"] == 0


def test_an_imported_proof_is_readable_without_signing_in(client, db):
    # The point of publishing an import: the rows were always there, and nothing
    # could open them. Ownerless still — which is what keeps a verify from writing
    # back over the imported structure.
    system_id = seed(db)
    identity = _folder_named(client, system_id, "The identity")
    (listed,) = client.get("/api/proofs/public", params={"folder_id": identity}).json()["items"]

    detail = client.get(f"/api/proofs/{listed['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "id"
    assert detail.json()["owner"] is None
    assert client.get(f"/api/formal-systems/{system_id}").status_code == 200
