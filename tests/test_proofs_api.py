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
from app.db import (
    Base,
    FormalSystem,
    Proof,
    ProofFolder,
    ProofReference,
    SideConditionRow,
    spec_to_system,
)
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
from tests.spec_helpers import (
    axiom,
    brackets,
    defn,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    statement_line,
    variable_prod,
)
from website.logical.declarative import SystemSpec

# Auth tables + the system-decomposition tables + the proof tables (all
# SQLite-creatable). The pgvector `theorems` table is deliberately omitted.
_TABLES = [
    m.__table__
    for m in (
        User, OAuthAccount, FormalSystem, BracketRow, SymbolRow,
        ProductionBindingRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, ProofReference,
    )
]


def zfc_spec() -> SystemSpec:
    # The same small ZFC fragment the systems tests use, assembled directly as a
    # SystemSpec (the engine no longer exposes a source `parse`; systems are built
    # from spec helpers).
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), equality_prod(),
                     implication_prod()],
        line=statement_line(),
        axioms=[axiom("EXT", "extensionality", "∀x x = x")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[defn("formula", "subset", "x ⊆ y", "(x = y → x = y)",
                          [("x", "variable"), ("y", "variable")])],
    )


# A single hypothesis line; verifies against the ZFC spec above.
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
            system = spec_to_system(zfc_spec())
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


def test_create_rejects_a_published_system_owned_by_another(client, db):
    # Owned-only: even a *published* system owned by someone else can't be
    # targeted, so one owner's system delete can never cascade into another
    # user's proof.
    other = _register_login(client, "grace@example.com")
    published = _seed_system(db, other, published=True)
    _logout(client)
    _register_login(client, "ada@example.com")
    response = client.post(
        "/proofs", json={"name": "P", "formal_system_id": published}
    )
    assert response.status_code == 400


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
    assert listed["total"] == 2
    assert [p["name"] for p in listed["items"]] == ["First", "Second"]
    assert "source" not in listed["items"][0]  # summary, not detail


def test_list_can_scope_to_one_system(client, db):
    owner = _register_login(client, "ada@example.com")
    system_a = _seed_system(db, owner)
    system_b = _seed_system(db, owner)
    client.post("/proofs", json={"name": "A", "formal_system_id": system_a})
    client.post("/proofs", json={"name": "B", "formal_system_id": system_b})
    scoped = client.get("/proofs", params={"formal_system_id": system_a}).json()
    assert [p["name"] for p in scoped["items"]] == ["A"]


def test_list_paginates_searches_and_sorts(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    for name in ("Banana", "Apple", "Cherry"):
        client.post("/proofs", json={"name": name, "formal_system_id": system_id})

    page = client.get("/proofs", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3  # full count, not just the page
    assert len(page["items"]) == 2

    hits = client.get("/proofs", params={"search": "APP"}).json()
    assert [p["name"] for p in hits["items"]] == ["Apple"]

    sorted_desc = client.get("/proofs", params={"sort": "name", "desc": True}).json()
    assert [p["name"] for p in sorted_desc["items"]] == ["Cherry", "Banana", "Apple"]


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
    assert created["id"] not in [p["id"] for p in client.get("/proofs").json()["items"]]


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


def test_publishing_caches_the_verdict(client, db):
    # Publishing verifies the proof; that verdict is cached so a published proof
    # renders as checked without a separate /verify call.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    assert created["valid"] is None  # never verified yet
    client.patch(f"/proofs/{created['id']}", json={"published": True})
    assert client.get(f"/proofs/{created['id']}").json()["valid"] is True


def test_editing_a_published_proof_into_invalid_is_rejected(client, db):
    # A published (world-readable) proof must keep verifying; a source edit that
    # breaks it is rejected, leaving the published proof untouched.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    client.patch(f"/proofs/{created['id']}", json={"published": True})

    rejected = client.patch(f"/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert rejected.status_code == 422
    # The edit was rolled back: still valid, still the original source.
    fetched = client.get(f"/proofs/{created['id']}").json()
    assert fetched["valid"] is True
    assert fetched["source"] == VALID_PROOF


def test_editing_a_draft_proof_into_invalid_is_allowed(client, db):
    # The published-proof guard must not apply to drafts (they may be saved
    # mid-edit in any state).
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    ok = client.patch(f"/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert ok.status_code == 200
    assert ok.json()["source"] == INVALID_PROOF


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
    public = client.get("/proofs/public").json()["items"]
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
    assert client.get("/proofs/public").json()["items"] == []


# ---------------------------------------------------------------------------
# Proof-to-proof references (R0: storage + validation, not yet wired to verify)
# ---------------------------------------------------------------------------


def _create_proof(client: TestClient, system_id: str, name: str, source: str = VALID_PROOF) -> str:
    resp = client.post(
        "/proofs", json={"name": name, "formal_system_id": system_id, "source": source}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _set_refs(client: TestClient, proof_id: str, refs: list[dict]):
    return client.put(f"/proofs/{proof_id}/references", json={"references": refs})


def _seed_proof(db_path, owner_id: str, system_id: str, name: str, published: bool = False) -> str:
    # Insert a proof owned by an arbitrary user directly. The create endpoint
    # requires owning the proof's system, so a second owner can only get a proof
    # into someone else's system by seeding — which is exactly the cross-owner
    # case the reference-scope rule guards.
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            proof = Proof(
                owner_id=uuid.UUID(owner_id),
                formal_system_id=uuid.UUID(system_id),
                name=name,
                slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
                source=VALID_PROOF,
                published_at=datetime.now(timezone.utc) if published else None,
            )
            session.add(proof)
            session.commit()
            return str(proof.id)
    finally:
        engine.dispose()


def test_set_and_read_back_references(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a = _create_proof(client, sid, "Lemma A")
    b = _create_proof(client, sid, "Main B")

    resp = _set_refs(client, b, [{"referenced_proof_id": a, "alias": "A"}])
    assert resp.status_code == 200, resp.text
    refs = resp.json()["references"]
    assert refs == [
        {"referenced_proof_id": a, "alias": "A", "name": "Lemma A", "slug": refs[0]["slug"],
         "published": False}
    ]
    # Visible on the detail read too.
    assert [r["alias"] for r in client.get(f"/proofs/{b}").json()["references"]] == ["A"]


def test_self_reference_is_rejected(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a = _create_proof(client, sid, "A")
    assert _set_refs(client, a, [{"referenced_proof_id": a, "alias": "self"}]).status_code == 422


def test_duplicate_target_and_alias_are_rejected(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a, b, c = (_create_proof(client, sid, n) for n in ("A", "B", "C"))
    assert _set_refs(client, c, [
        {"referenced_proof_id": a, "alias": "A1"}, {"referenced_proof_id": a, "alias": "A2"},
    ]).status_code == 422
    assert _set_refs(client, c, [
        {"referenced_proof_id": a, "alias": "X"}, {"referenced_proof_id": b, "alias": "X"},
    ]).status_code == 422


def test_bad_alias_is_rejected(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a = _create_proof(client, sid, "A")
    b = _create_proof(client, sid, "B")
    for bad in ("has space", "1leading", "dot.ted", "com,ma", ""):
        assert _set_refs(client, b, [{"referenced_proof_id": a, "alias": bad}]).status_code == 422


def test_cross_system_reference_is_rejected(client, db):
    uid = _register_login(client, "ada@example.com")
    s1, s2 = _seed_system(db, uid), _seed_system(db, uid)
    a = _create_proof(client, s1, "A in s1")
    b = _create_proof(client, s2, "B in s2")
    assert _set_refs(client, b, [{"referenced_proof_id": a, "alias": "A"}]).status_code == 422


def test_cycle_is_rejected_directly_and_transitively(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a, b, c = (_create_proof(client, sid, n) for n in ("A", "B", "C"))
    # a -> b
    assert _set_refs(client, a, [{"referenced_proof_id": b, "alias": "B"}]).status_code == 200
    # b -> a closes a 2-cycle.
    assert _set_refs(client, b, [{"referenced_proof_id": a, "alias": "A"}]).status_code == 422
    # a -> b -> c, then c -> a closes a 3-cycle.
    assert _set_refs(client, b, [{"referenced_proof_id": c, "alias": "C"}]).status_code == 200
    assert _set_refs(client, c, [{"referenced_proof_id": a, "alias": "A"}]).status_code == 422


def test_references_replace_wholesale(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    a, b, c = (_create_proof(client, sid, n) for n in ("A", "B", "C"))
    assert _set_refs(client, c, [{"referenced_proof_id": a, "alias": "A"}]).status_code == 200
    # Reuse the alias "A" for a different target — the old edge is fully replaced.
    resp = _set_refs(client, c, [{"referenced_proof_id": b, "alias": "A"}])
    assert resp.status_code == 200
    assert [(r["referenced_proof_id"], r["alias"]) for r in resp.json()["references"]] == [(b, "A")]
    # Clearing removes them all.
    assert _set_refs(client, c, []).json()["references"] == []


def test_reference_scope_allows_others_published_but_not_draft(client, db):
    # A proof may reference another owner's *published* proof in the same system,
    # but not their draft. (Reachable only via seeding today — the create gate
    # keeps a system's proofs single-owner; the rule is forward-looking.)
    ada = _register_login(client, "ada@example.com")
    sid = _seed_system(db, ada)
    mine = _create_proof(client, sid, "Mine")

    bob = _register_login(client, "bob@example.com")  # switches the session to bob
    bob_published = _seed_proof(db, bob, sid, "BobPublished", published=True)
    bob_draft = _seed_proof(db, bob, sid, "BobDraft", published=False)

    # Back to ada.
    assert client.post(
        "/auth/login", data={"username": "ada@example.com", "password": "password123"}
    ).status_code == 204

    assert _set_refs(client, mine, [{"referenced_proof_id": bob_published, "alias": "P"}]).status_code == 200
    assert _set_refs(client, mine, [{"referenced_proof_id": bob_draft, "alias": "D"}]).status_code == 422


def _seed_reference(db_path, proof_id: str, referenced_id: str, alias: str) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            session.add(
                ProofReference(
                    proof_id=uuid.UUID(proof_id),
                    references_id=uuid.UUID(referenced_id),
                    alias=alias,
                )
            )
            session.commit()
    finally:
        engine.dispose()


def test_reference_to_a_private_lemma_is_hidden_from_public_readers(client, db):
    # Defense in depth: the lifecycle gates now keep a published proof from ever
    # referencing a private draft through the API, but seeded/legacy data or a
    # future path could produce that state — the read-time filter must still hide
    # the draft's identity from an anonymous reader. Seed the state directly.
    ada = _register_login(client, "ada@example.com")
    sid = _seed_system(db, ada, published=True)
    lemma = _seed_proof(db, ada, sid, "SecretLemma", published=False)
    main = _seed_proof(db, ada, sid, "Main", published=True)
    _seed_reference(db, main, lemma, "A")

    # The owner still sees their own reference.
    assert [r["alias"] for r in client.get(f"/proofs/{main}").json()["references"]] == ["A"]

    # An anonymous reader of the published proof sees no trace of the draft lemma.
    _logout(client)
    public_view = client.get(f"/proofs/{main}")
    assert public_view.status_code == 200
    assert public_view.json()["references"] == []


def test_referenced_by_lists_incoming_edges(client, db):
    # The "used by" direction: fetching a lemma reports the proofs that cite it.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma, user1, user2 = (_create_proof(client, sid, n) for n in ("Lemma", "One", "Two"))
    assert _set_refs(client, user1, [{"referenced_proof_id": lemma, "alias": "L"}]).status_code == 200
    assert _set_refs(client, user2, [{"referenced_proof_id": lemma, "alias": "Lem"}]).status_code == 200

    body = client.get(f"/proofs/{lemma}").json()
    # Sorted by referrer name ("One" < "Two") for a stable "used by" order.
    assert [(r["proof_id"], r["alias"]) for r in body["referenced_by"]] == [
        (user1, "L"),
        (user2, "Lem"),
    ]
    # The lemma itself cites nothing.
    assert body["references"] == []
    # A proof with no incoming edges reports an empty "used by".
    assert client.get(f"/proofs/{user1}").json()["referenced_by"] == []


def test_referenced_by_hides_referrers_the_viewer_cannot_read(client, db):
    # A draft proof that cites a published lemma must not leak its existence to an
    # anonymous reader of the lemma; the "used by" list is filtered by readability.
    ada = _register_login(client, "ada@example.com")
    sid = _seed_system(db, ada, published=True)
    lemma = _seed_proof(db, ada, sid, "PublicLemma", published=True)
    referrer = _seed_proof(db, ada, sid, "DraftReferrer", published=False)
    _seed_reference(db, referrer, lemma, "L")

    # The owner sees their own draft in the lemma's "used by".
    assert [r["proof_id"] for r in client.get(f"/proofs/{lemma}").json()["referenced_by"]] == [referrer]

    # An anonymous reader sees no trace of the draft referrer.
    _logout(client)
    assert client.get(f"/proofs/{lemma}").json()["referenced_by"] == []


# ---------------------------------------------------------------------------
# R1: references wired into verification
# ---------------------------------------------------------------------------

# A lemma proof asserting an implication, and a proof that uses it: cite the
# lemma's line 1 (the implication) as MP's `(p → q)` antecedent alongside a local
# `p`, to derive `q`.
_LEMMA_SRC = "(x ∈ y → x = y) [HYP]"
_USER_SRC = "x ∈ y [HYP]\nx = y [MP, A.1, 1]"


def test_reference_resolves_a_cited_lemma_at_verify(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)

    # Without the reference, `A.1` doesn't resolve, so the step fails.
    assert client.post(f"/proofs/{main}/verify").json()["success"] is False

    assert _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}]).status_code == 200
    assert client.post(f"/proofs/{main}/verify").json()["success"] is True
    # And the verdict is cached.
    assert client.get(f"/proofs/{main}").json()["valid"] is True


def test_reference_to_an_invalid_lemma_does_not_prove(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    # Valid line 1, but invalid overall (line 2 cites MP with one antecedent).
    broken = _create_proof(client, sid, "Broken", source="(x ∈ y → x = y) [HYP]\nx = y [MP, 1]")
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": broken, "alias": "A"}])
    # An invalid proof isn't a usable lemma, so `A.1` is not seeded.
    assert client.post(f"/proofs/{main}/verify").json()["success"] is False


def test_publish_requires_referenced_proofs_published(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)  # draft
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])

    # Can't publish while the referenced lemma is a draft.
    assert client.patch(f"/proofs/{main}", json={"published": True}).status_code == 422
    # Publish the lemma, then the dependent can publish (it verifies via the ref).
    assert client.patch(f"/proofs/{lemma}", json={"published": True}).status_code == 200
    assert client.patch(f"/proofs/{main}", json={"published": True}).status_code == 200


def test_editing_a_lemma_invalidates_dependents(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.post(f"/proofs/{main}/verify").json()["success"] is True
    assert client.get(f"/proofs/{main}").json()["valid"] is True

    # Editing the lemma's source makes the dependent's cached verdict stale.
    assert client.patch(f"/proofs/{lemma}", json={"source": "x = x [HYP]"}).status_code == 200
    assert client.get(f"/proofs/{main}").json()["valid"] is None


def test_published_proof_rejects_adding_a_draft_reference(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    assert client.patch(f"/proofs/{lemma}", json={"published": True}).status_code == 200
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.patch(f"/proofs/{main}", json={"published": True}).status_code == 200

    # Adding a draft reference to the now-published proof is rejected.
    draft = _create_proof(client, sid, "Draft", source=_LEMMA_SRC)
    resp = _set_refs(client, main, [
        {"referenced_proof_id": lemma, "alias": "A"},
        {"referenced_proof_id": draft, "alias": "D"},
    ])
    assert resp.status_code == 422


def test_cannot_unpublish_or_delete_a_lemma_a_published_proof_rests_on(client, db):
    # Unpublishing or deleting a lemma that a published proof references would
    # silently break that public theorem, so both are blocked (409) until the
    # dependent is taken down first.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.patch(f"/proofs/{lemma}", json={"published": True}).status_code == 200
    assert client.patch(f"/proofs/{main}", json={"published": True}).status_code == 200

    # main (published) depends on lemma, so lemma is load-bearing.
    assert client.patch(f"/proofs/{lemma}", json={"published": False}).status_code == 409
    assert client.delete(f"/proofs/{lemma}").status_code == 409

    # Once the dependent is unpublished, the lemma is free again.
    assert client.patch(f"/proofs/{main}", json={"published": False}).status_code == 200
    assert client.patch(f"/proofs/{lemma}", json={"published": False}).status_code == 200
    assert client.delete(f"/proofs/{lemma}").status_code == 204


def test_draft_dependents_do_not_block_unpublish_or_delete(client, db):
    # Only *published* dependents lock a lemma. A draft dependent's verdict is
    # just invalidated.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)  # stays a draft
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.patch(f"/proofs/{lemma}", json={"published": True}).status_code == 200
    # A draft dependent doesn't block unpublishing the lemma...
    assert client.patch(f"/proofs/{lemma}", json={"published": False}).status_code == 200
    # ...nor deleting it (the draft dependent just goes stale).
    assert client.delete(f"/proofs/{lemma}").status_code == 204
