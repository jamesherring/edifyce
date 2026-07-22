"""Owner-scoped CRUD endpoints for proofs.

Mirrors ``tests/test_systems_api.py``: runs the proofs router end to end against
a throwaway SQLite database (auth + system-decomposition + proof tables, all
SQLite-creatable — the pgvector ``theorems`` table is excluded), with
``get_session`` pointed at it and the real fastapi-users auth flow driving owner
scoping. A proof is attached to a seeded formal system and verified against it.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db import Base, FormalSystem, Proof, ProofFolder, SideConditionRow, spec_to_system
from app.db.models import OAuthAccount, User
from app.db.session import get_session
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.main import app
from website.logical.declarative import parse

# Auth tables + the system-decomposition tables + the proof tables (all
# SQLite-creatable). The pgvector `theorems` table is deliberately omitted.
_TABLES = [
    m.__table__
    for m in (
        User, OAuthAccount, FormalSystem, BracketRow, SymbolRow,
        ProductionBindingRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof,
    )
]


ZFC_SOURCE = """system ZFC

notation
  brackets ( )

grammar
  term      | variable    | matches [a-z][a-z0-9]*
  formula   | membership  | s ∈ t   | s, t : term
  formula   | equality    | s = t   | s, t : term
  formula   | implication | (p → q) | p, q : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

axioms
  EXT | extensionality | ∀x x = x

rules
  HYP | hypothesis   | from             | infer p | p : formula
  MP  | modus ponens | from p ; (p → q) | infer q | p, q : formula

definitions
  formula | subset | x ⊆ y | means (x = y → x = y) | x, y : variable
"""

# A single hypothesis line; verifies against ZFC_SOURCE.
VALID_PROOF = "x = x [HYP]"
# Matches no line type — reported as an invalid line, not raised.
INVALID_PROOF = "this is not a formula"


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "proofs.db"

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine, tables=_TABLES)
    sync_engine.dispose()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)

    # SQLite ignores ON DELETE unless foreign keys are enabled per connection.
    @event.listens_for(async_engine.sync_engine, "connect")
    def _fk_pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield db_path
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(db, monkeypatch) -> Iterator[TestClient]:
    # The auth cookie is Secure by default; relax it so httpx replays it over http.
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    with TestClient(app) as test_client:
        yield test_client


def _register_login(client: TestClient, email: str, password: str = "password123") -> str:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]
    assert client.post("/auth/login", data={"username": email, "password": password}).status_code == 204
    return user_id


def _logout(client: TestClient) -> None:
    assert client.post("/auth/logout").status_code == 204


def _seed_system(db_path, owner_id: str, published: bool = False) -> str:
    # Insert a ZFC system owned by the given user directly, so a proof has a real
    # system to attach to and verify against.
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            system = spec_to_system(parse(ZFC_SOURCE))
            system.owner_id = uuid.UUID(owner_id)
            # Distinct slug per seed so a user can own several (the (owner, slug)
            # index is unique); the API isn't exercised for system creation here.
            system.slug = f"zfc-{uuid.uuid4().hex[:8]}"
            if published:
                system.published_at = datetime.now(timezone.utc)
            session.add(system)
            session.commit()
            return str(system.id)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Auth is required
# ---------------------------------------------------------------------------


def test_endpoints_require_authentication(client):
    assert client.get("/proofs").status_code == 401
    assert client.post("/proofs", json={"name": "X", "formal_system_id": str(uuid.uuid4())}).status_code == 401


def test_spa_guard_covers_the_proofs_collection_path():
    from app.main import _mounted_api_paths

    assert "proofs" in _mounted_api_paths()


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------


def test_create_returns_detail_with_slug_and_source(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    response = client.post(
        "/proofs",
        json={"name": "My Proof", "formal_system_id": system_id, "source": VALID_PROOF},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "My Proof"
    assert body["slug"] == "my-proof"
    assert body["source"] == VALID_PROOF
    assert body["formal_system_id"] == system_id
    assert body["valid"] is None  # not verified on create
    assert uuid.UUID(body["id"])


def test_create_rejects_unknown_system(client, db):
    _register_login(client, "ada@example.com")
    response = client.post(
        "/proofs", json={"name": "P", "formal_system_id": str(uuid.uuid4())}
    )
    assert response.status_code == 400


def test_create_rejects_another_users_draft_system(client, db):
    other = _register_login(client, "grace@example.com")
    other_system = _seed_system(db, other)  # draft, owned by grace
    _logout(client)
    _register_login(client, "ada@example.com")
    response = client.post(
        "/proofs", json={"name": "P", "formal_system_id": other_system}
    )
    assert response.status_code == 400


def test_create_allows_a_published_system_owned_by_another(client, db):
    other = _register_login(client, "grace@example.com")
    published = _seed_system(db, other, published=True)
    _logout(client)
    _register_login(client, "ada@example.com")
    response = client.post(
        "/proofs", json={"name": "P", "formal_system_id": published}
    )
    assert response.status_code == 201, response.text


def test_get_returns_created_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    fetched = client.get(f"/proofs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_list_returns_only_summaries_in_creation_order(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    client.post("/proofs", json={"name": "First", "formal_system_id": system_id})
    client.post("/proofs", json={"name": "Second", "formal_system_id": system_id})
    listed = client.get("/proofs").json()
    assert [p["name"] for p in listed] == ["First", "Second"]
    assert "source" not in listed[0]  # summary, not detail


def test_list_can_scope_to_one_system(client, db):
    owner = _register_login(client, "ada@example.com")
    system_a = _seed_system(db, owner)
    system_b = _seed_system(db, owner)
    client.post("/proofs", json={"name": "A", "formal_system_id": system_a})
    client.post("/proofs", json={"name": "B", "formal_system_id": system_b})
    scoped = client.get("/proofs", params={"formal_system_id": system_a}).json()
    assert [p["name"] for p in scoped] == ["A"]


def test_duplicate_name_gets_a_distinct_slug(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    first = client.post("/proofs", json={"name": "Lemma", "formal_system_id": system_id}).json()
    second = client.post("/proofs", json={"name": "Lemma", "formal_system_id": system_id}).json()
    assert first["slug"] == "lemma"
    assert second["slug"] == "lemma-2"


def test_another_users_draft_proof_is_not_readable(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/proofs", json={"name": "Secret", "formal_system_id": system_id}).json()
    _logout(client)
    _register_login(client, "eve@example.com")
    assert client.get(f"/proofs/{created['id']}").status_code == 404
    assert created["id"] not in [p["id"] for p in client.get("/proofs").json()]


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def test_update_edits_fields_and_reslugs(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/proofs", json={"name": "Old", "formal_system_id": system_id}).json()
    updated = client.patch(
        f"/proofs/{created['id']}", json={"name": "New Name", "source": VALID_PROOF}
    ).json()
    assert updated["name"] == "New Name"
    assert updated["slug"] == "new-name"
    assert updated["source"] == VALID_PROOF


def test_editing_source_clears_the_cached_verdict(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    assert client.post(f"/proofs/{created['id']}/verify").json()["success"] is True
    assert client.get(f"/proofs/{created['id']}").json()["valid"] is True
    # A source edit invalidates the stored verdict until re-verified.
    client.patch(f"/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert client.get(f"/proofs/{created['id']}").json()["valid"] is None


def test_delete_removes_the_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    assert client.delete(f"/proofs/{created['id']}").status_code == 204
    assert client.get(f"/proofs/{created['id']}").status_code == 404


def test_delete_another_users_proof_is_404(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    _logout(client)
    _register_login(client, "eve@example.com")
    assert client.delete(f"/proofs/{created['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_valid_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    response = client.post(f"/proofs/{created['id']}/verify")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] == []
    assert body["proof"]["indicator"] == "ok"
    # The verdict is cached back onto the row.
    assert client.get(f"/proofs/{created['id']}").json()["valid"] is True


def test_verify_invalid_proof_reports_not_raises(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": INVALID_PROOF}
    ).json()
    body = client.post(f"/proofs/{created['id']}/verify").json()
    assert body["success"] is False
    assert body["proof"]["indicator"] == "error"


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def test_publish_requires_a_verifying_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": INVALID_PROOF}
    ).json()
    response = client.patch(f"/proofs/{created['id']}", json={"published": True})
    assert response.status_code == 422


def test_publish_requires_a_published_system(client, db):
    owner = _register_login(client, "ada@example.com")
    draft_system = _seed_system(db, owner, published=False)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": draft_system, "source": VALID_PROOF}
    ).json()
    response = client.patch(f"/proofs/{created['id']}", json={"published": True})
    assert response.status_code == 400


def test_publish_then_public_read_and_listing(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "Public Proof", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    published = client.patch(f"/proofs/{created['id']}", json={"published": True})
    assert published.status_code == 200
    assert published.json()["published_at"] is not None

    # Anonymous read + public listing now see it.
    _logout(client)
    assert client.get(f"/proofs/{created['id']}").status_code == 200
    public = client.get("/proofs/public").json()
    assert created["id"] in [p["id"] for p in public]


def test_unpublish_removes_from_public_list(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    client.patch(f"/proofs/{created['id']}", json={"published": True})
    client.patch(f"/proofs/{created['id']}", json={"published": False})
    _logout(client)
    assert client.get(f"/proofs/{created['id']}").status_code == 404
    assert client.get("/proofs/public").json() == []
