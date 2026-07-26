"""Owner-scoped CRUD endpoints for proofs.

Mirrors ``tests/test_systems_api.py``: runs the proofs router end to end against
a throwaway SQLite database (auth + system-decomposition + proof tables, all
SQLite-creatable — the pgvector ``theorems`` table is excluded), with
``get_session`` pointed at it and the real fastapi-users auth flow driving owner
scoping. A proof is attached to a seeded formal system and verified against it.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from copy import copy
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
import app.routers._common as _common
import app.routers.proofs as proofs_router
import app.routers.system_parts as system_parts_router
from app.db import (
    Base,
    FormalSystem,
    Proof,
    ProofFolder,
    ProofLineAntecedentRow,
    ProofLineRow,
    ProofReference,
    SideConditionRow,
    TermChildRow,
    TermRow,
    spec_to_system,
)
from app.db.models import OAuthAccount, User
from app.db.proofs_mapping import load_proof_lines
from app.db.session import get_session
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    ProductionBindingScopeRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.db.systems_mapping import system_to_spec
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
from tests.database import (
    ON_POSTGRES,
    async_url,
    create_tables,
    database_url,
    enable_foreign_keys,
)
from tests.zfc_systems import scoped_zfc_spec
from website.logical.declarative import SystemSpec, build_spec
from website.logical.formal_system import FormalSystem as EngineFormalSystem

# Auth tables + the system-decomposition tables + the proof tables + the term
# graph a verified proof's lines are stored into (all SQLite-creatable). The
# pgvector `theorems` table is deliberately omitted.
_TABLES = [
    m.__table__
    for m in (
        User, OAuthAccount, FormalSystem, BracketRow, SymbolRow,
        ProductionBindingRow, ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, ProofReference,
        TermRow, TermChildRow, ProofLineRow, ProofLineAntecedentRow,
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
        lines=[statement_line()],
        axioms=[axiom("EXT", "extensionality", "∀x x = x")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[defn("formula", "subset", "x ⊆ y", "(x = y → x = y)",
                          [("x", "variable"), ("y", "variable")])],
    )


# A subproof plus a discharge, against `scoped_zfc_spec`: the two structural
# things a flat proof cannot exercise — a line that opens a scope, and a line
# justified by a *block* rather than by cited lines.
_SUBPROOF_SRC = "assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → x ∈ y) [CP, 1]"

# A single hypothesis line; verifies against the ZFC spec above.
VALID_PROOF = "x = x [HYP]"
# Matches no line type — reported as an invalid line, not raised.
INVALID_PROOF = "this is not a formula"


@pytest.fixture
def db(tmp_path):
    # Yields the *synchronous URL* of a throwaway database: a per-test SQLite
    # file by default, or the one `EDIFYCE_TEST_DATABASE_URL` names (see
    # tests/database.py) so the same suite can run against real Postgres.
    url = database_url(tmp_path, "proofs")
    create_tables(url, _TABLES)

    async_engine = create_async_engine(async_url(url), poolclass=NullPool)
    enable_foreign_keys(async_engine.sync_engine)

    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield url
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(db, monkeypatch) -> Iterator[TestClient]:
    # The auth cookie is Secure by default; relax it so httpx replays it over http.
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    with TestClient(app) as test_client:
        yield test_client


def _register_login(client: TestClient, email: str, password: str = "password123") -> str:
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]
    assert client.post("/api/auth/login", data={"username": email, "password": password}).status_code == 204
    return user_id


def _logout(client: TestClient) -> None:
    assert client.post("/api/auth/logout").status_code == 204


def _seed_system(
    db_path, owner_id: str, published: bool = False, spec: SystemSpec | None = None
) -> str:
    # Insert a system owned by the given user directly, so a proof has a real
    # system to attach to and verify against. Defaults to the ZFC fragment above;
    # pass `spec` for a scenario that needs different machinery (e.g. subproofs).
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = spec_to_system(spec if spec is not None else zfc_spec())
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
    assert client.get("/api/proofs").status_code == 401
    assert client.post("/api/proofs", json={"name": "X", "formal_system_id": str(uuid.uuid4())}).status_code == 401


def test_spa_guard_covers_the_proofs_collection_path():
    from app.main import _mounted_api_paths

    assert "api/proofs" in _mounted_api_paths()


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------


def test_create_returns_detail_with_slug_and_source(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    response = client.post(
        "/api/proofs",
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
        "/api/proofs", json={"name": "P", "formal_system_id": str(uuid.uuid4())}
    )
    assert response.status_code == 400


def test_create_rejects_another_users_draft_system(client, db):
    other = _register_login(client, "grace@example.com")
    other_system = _seed_system(db, other)  # draft, owned by grace
    _logout(client)
    _register_login(client, "ada@example.com")
    response = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": other_system}
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
        "/api/proofs", json={"name": "P", "formal_system_id": published}
    )
    assert response.status_code == 400


def test_get_returns_created_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/api/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    fetched = client.get(f"/api/proofs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_list_returns_only_summaries_in_creation_order(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    client.post("/api/proofs", json={"name": "First", "formal_system_id": system_id})
    client.post("/api/proofs", json={"name": "Second", "formal_system_id": system_id})
    listed = client.get("/api/proofs").json()
    assert listed["total"] == 2
    assert [p["name"] for p in listed["items"]] == ["First", "Second"]
    assert "source" not in listed["items"][0]  # summary, not detail


def test_list_can_scope_to_one_system(client, db):
    owner = _register_login(client, "ada@example.com")
    system_a = _seed_system(db, owner)
    system_b = _seed_system(db, owner)
    client.post("/api/proofs", json={"name": "A", "formal_system_id": system_a})
    client.post("/api/proofs", json={"name": "B", "formal_system_id": system_b})
    scoped = client.get("/api/proofs", params={"formal_system_id": system_a}).json()
    assert [p["name"] for p in scoped["items"]] == ["A"]


def test_list_paginates_searches_and_sorts(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    for name in ("Banana", "Apple", "Cherry"):
        client.post("/api/proofs", json={"name": name, "formal_system_id": system_id})

    page = client.get("/api/proofs", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3  # full count, not just the page
    assert len(page["items"]) == 2

    hits = client.get("/api/proofs", params={"search": "APP"}).json()
    assert [p["name"] for p in hits["items"]] == ["Apple"]

    sorted_desc = client.get("/api/proofs", params={"sort": "name", "desc": True}).json()
    assert [p["name"] for p in sorted_desc["items"]] == ["Cherry", "Banana", "Apple"]


def test_duplicate_name_gets_a_distinct_slug(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    first = client.post("/api/proofs", json={"name": "Lemma", "formal_system_id": system_id}).json()
    second = client.post("/api/proofs", json={"name": "Lemma", "formal_system_id": system_id}).json()
    assert first["slug"] == "lemma"
    assert second["slug"] == "lemma-2"


def test_another_users_draft_proof_is_not_readable(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/api/proofs", json={"name": "Secret", "formal_system_id": system_id}).json()
    _logout(client)
    _register_login(client, "eve@example.com")
    assert client.get(f"/api/proofs/{created['id']}").status_code == 404
    assert created["id"] not in [p["id"] for p in client.get("/api/proofs").json()["items"]]


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def test_update_edits_fields_and_reslugs(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/api/proofs", json={"name": "Old", "formal_system_id": system_id}).json()
    updated = client.patch(
        f"/api/proofs/{created['id']}", json={"name": "New Name", "source": VALID_PROOF}
    ).json()
    assert updated["name"] == "New Name"
    assert updated["slug"] == "new-name"
    assert updated["source"] == VALID_PROOF


def test_editing_source_clears_the_cached_verdict(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    assert client.post(f"/api/proofs/{created['id']}/verify").json()["success"] is True
    assert client.get(f"/api/proofs/{created['id']}").json()["valid"] is True
    # A source edit invalidates the stored verdict until re-verified.
    client.patch(f"/api/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert client.get(f"/api/proofs/{created['id']}").json()["valid"] is None


def test_delete_removes_the_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/api/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    assert client.delete(f"/api/proofs/{created['id']}").status_code == 204
    assert client.get(f"/api/proofs/{created['id']}").status_code == 404


def test_delete_another_users_proof_is_404(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post("/api/proofs", json={"name": "P", "formal_system_id": system_id}).json()
    _logout(client)
    _register_login(client, "eve@example.com")
    assert client.delete(f"/api/proofs/{created['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_valid_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    response = client.post(f"/api/proofs/{created['id']}/verify")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] == []
    assert body["proof"]["indicator"] == "ok"
    # The verdict is cached back onto the row.
    assert client.get(f"/api/proofs/{created['id']}").json()["valid"] is True


def test_verify_invalid_proof_reports_not_raises(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": INVALID_PROOF}
    ).json()
    body = client.post(f"/api/proofs/{created['id']}/verify").json()
    assert body["success"] is False
    assert body["proof"]["indicator"] == "error"


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def test_publish_requires_a_verifying_proof(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": INVALID_PROOF}
    ).json()
    response = client.patch(f"/api/proofs/{created['id']}", json={"published": True})
    assert response.status_code == 422


def test_publish_requires_a_published_system(client, db):
    owner = _register_login(client, "ada@example.com")
    draft_system = _seed_system(db, owner, published=False)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": draft_system, "source": VALID_PROOF}
    ).json()
    response = client.patch(f"/api/proofs/{created['id']}", json={"published": True})
    assert response.status_code == 400


def test_publishing_caches_the_verdict(client, db):
    # Publishing verifies the proof; that verdict is cached so a published proof
    # renders as checked without a separate /verify call.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    assert created["valid"] is None  # never verified yet
    client.patch(f"/api/proofs/{created['id']}", json={"published": True})
    assert client.get(f"/api/proofs/{created['id']}").json()["valid"] is True


def test_editing_a_published_proof_into_invalid_is_rejected(client, db):
    # A published (world-readable) proof must keep verifying; a source edit that
    # breaks it is rejected, leaving the published proof untouched.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    client.patch(f"/api/proofs/{created['id']}", json={"published": True})

    rejected = client.patch(f"/api/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert rejected.status_code == 422
    # The edit was rolled back: still valid, still the original source.
    fetched = client.get(f"/api/proofs/{created['id']}").json()
    assert fetched["valid"] is True
    assert fetched["source"] == VALID_PROOF


def test_editing_a_draft_proof_into_invalid_is_allowed(client, db):
    # The published-proof guard must not apply to drafts (they may be saved
    # mid-edit in any state).
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    ok = client.patch(f"/api/proofs/{created['id']}", json={"source": INVALID_PROOF})
    assert ok.status_code == 200
    assert ok.json()["source"] == INVALID_PROOF


def test_publish_then_public_read_and_listing(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "Public Proof", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    published = client.patch(f"/api/proofs/{created['id']}", json={"published": True})
    assert published.status_code == 200
    assert published.json()["published_at"] is not None

    # Anonymous read + public listing now see it.
    _logout(client)
    assert client.get(f"/api/proofs/{created['id']}").status_code == 200
    public = client.get("/api/proofs/public").json()["items"]
    assert created["id"] in [p["id"] for p in public]


def test_unpublish_removes_from_public_list(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs", json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF}
    ).json()
    client.patch(f"/api/proofs/{created['id']}", json={"published": True})
    client.patch(f"/api/proofs/{created['id']}", json={"published": False})
    _logout(client)
    assert client.get(f"/api/proofs/{created['id']}").status_code == 404
    assert client.get("/api/proofs/public").json()["items"] == []


# ---------------------------------------------------------------------------
# Proof-to-proof references (R0: storage + validation, not yet wired to verify)
# ---------------------------------------------------------------------------


def _create_proof(client: TestClient, system_id: str, name: str, source: str = VALID_PROOF) -> str:
    resp = client.post(
        "/api/proofs", json={"name": name, "formal_system_id": system_id, "source": source}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _set_refs(client: TestClient, proof_id: str, refs: list[dict]):
    return client.put(f"/api/proofs/{proof_id}/references", json={"references": refs})


def _seed_proof(db_path, owner_id: str, system_id: str, name: str, published: bool = False) -> str:
    # Insert a proof owned by an arbitrary user directly. The create endpoint
    # requires owning the proof's system, so a second owner can only get a proof
    # into someone else's system by seeding — which is exactly the cross-owner
    # case the reference-scope rule guards.
    engine = create_engine(db_path)
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
    assert [r["alias"] for r in client.get(f"/api/proofs/{b}").json()["references"]] == ["A"]


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
        "/api/auth/login", data={"username": "ada@example.com", "password": "password123"}
    ).status_code == 204

    assert _set_refs(client, mine, [{"referenced_proof_id": bob_published, "alias": "P"}]).status_code == 200
    assert _set_refs(client, mine, [{"referenced_proof_id": bob_draft, "alias": "D"}]).status_code == 422


def _seed_reference(db_path, proof_id: str, referenced_id: str, alias: str) -> None:
    engine = create_engine(db_path)
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
    assert [r["alias"] for r in client.get(f"/api/proofs/{main}").json()["references"]] == ["A"]

    # An anonymous reader of the published proof sees no trace of the draft lemma.
    _logout(client)
    public_view = client.get(f"/api/proofs/{main}")
    assert public_view.status_code == 200
    assert public_view.json()["references"] == []


def test_referenced_by_lists_incoming_edges(client, db):
    # The "used by" direction: fetching a lemma reports the proofs that cite it.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma, user1, user2 = (_create_proof(client, sid, n) for n in ("Lemma", "One", "Two"))
    assert _set_refs(client, user1, [{"referenced_proof_id": lemma, "alias": "L"}]).status_code == 200
    assert _set_refs(client, user2, [{"referenced_proof_id": lemma, "alias": "Lem"}]).status_code == 200

    body = client.get(f"/api/proofs/{lemma}").json()
    # Sorted by referrer name ("One" < "Two") for a stable "used by" order.
    assert [(r["proof_id"], r["alias"]) for r in body["referenced_by"]] == [
        (user1, "L"),
        (user2, "Lem"),
    ]
    # The lemma itself cites nothing.
    assert body["references"] == []
    # A proof with no incoming edges reports an empty "used by".
    assert client.get(f"/api/proofs/{user1}").json()["referenced_by"] == []


def test_referenced_by_hides_referrers_the_viewer_cannot_read(client, db):
    # A draft proof that cites a published lemma must not leak its existence to an
    # anonymous reader of the lemma; the "used by" list is filtered by readability.
    ada = _register_login(client, "ada@example.com")
    sid = _seed_system(db, ada, published=True)
    lemma = _seed_proof(db, ada, sid, "PublicLemma", published=True)
    referrer = _seed_proof(db, ada, sid, "DraftReferrer", published=False)
    _seed_reference(db, referrer, lemma, "L")

    # The owner sees their own draft in the lemma's "used by".
    assert [r["proof_id"] for r in client.get(f"/api/proofs/{lemma}").json()["referenced_by"]] == [referrer]

    # An anonymous reader sees no trace of the draft referrer.
    _logout(client)
    assert client.get(f"/api/proofs/{lemma}").json()["referenced_by"] == []


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
    # A lemma is cited from its *stored* lines, so it must have been verified.
    assert client.post(f"/api/proofs/{lemma}/verify").json()["success"] is True

    # Without the reference, `A.1` doesn't resolve, so the step fails.
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is False

    assert _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}]).status_code == 200
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True
    # And the verdict is cached.
    assert client.get(f"/api/proofs/{main}").json()["valid"] is True


def test_reference_to_an_invalid_lemma_does_not_prove(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    # Valid line 1, but invalid overall (line 2 cites MP with one antecedent).
    broken = _create_proof(client, sid, "Broken", source="(x ∈ y → x = y) [HYP]\nx = y [MP, 1]")
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{broken}/verify")
    _set_refs(client, main, [{"referenced_proof_id": broken, "alias": "A"}])
    # An invalid proof isn't a usable lemma, so `A.1` is not seeded.
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is False


def test_an_unverified_lemma_cannot_be_cited_and_the_reason_is_reported(client, db):
    # A lemma is cited from its *stored* lines, so one that has never been
    # verified has nothing to cite — a proof may rest only on a lemma that
    # stands. Previously the closure quietly verified it on the way past, which
    # meant a proof could be "proved" by a lemma nobody had ever checked.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])

    body = client.post(f"/api/proofs/{main}/verify").json()
    assert body["success"] is False
    # ...and it says so, rather than leaving `[MP, A.1, 1]` looking like a typo.
    assert any("Lemma" in error and "must be verified" in error for error in body["errors"])

    # Verifying the lemma is all it takes.
    assert client.post(f"/api/proofs/{lemma}/verify").json()["success"] is True
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True


def test_verifying_parses_the_proof_and_none_of_its_lemmas(client, db, monkeypatch):
    # P1's measure (docs/verification-from-rows.md): a lemma is *loaded* from its
    # stored lines, not re-parsed and re-checked, so the cost of a verify stops
    # scaling with the size of the reference closure. Two levels deep, because
    # the seeding is transitive even though the checking is not.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)

    base = _create_proof(client, sid, "Base", source=_LEMMA_SRC)
    middle = _create_proof(client, sid, "Middle", source=_USER_SRC)
    _set_refs(client, middle, [{"referenced_proof_id": base, "alias": "A"}])
    assert client.post(f"/api/proofs/{base}/verify").json()["success"] is True
    assert client.post(f"/api/proofs/{middle}/verify").json()["success"] is True

    # Cites Middle's line 2 (`x = y`) as one of MP's premises.
    main = _create_proof(
        client, sid, "Main", source="(x = y → x ∈ y) [HYP]\nx ∈ y [MP, M.2, 1]"
    )
    _set_refs(client, main, [{"referenced_proof_id": middle, "alias": "M"}])

    parses: list[str] = []
    original = EngineFormalSystem.parse

    def counted(self, text, *args, **kwargs):
        parses.append(text)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(EngineFormalSystem, "parse", counted)
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True

    # Exactly one parse: the proof being verified. Neither lemma is re-read.
    assert len(parses) == 1
    assert parses[0].startswith("(x = y → x ∈ y)")


def test_the_reference_closure_is_read_in_a_fixed_number_of_queries(client, db):
    # Reading a proof back is latency, not work: per-lemma it loses to simply
    # re-parsing, and only batching the whole closure makes it win. So the query
    # count must not scale with the number of lemmas — that regressing would undo
    # the point of reading rows at all, silently and without failing anything.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)

    lemmas = []
    for i in range(6):
        pid = _create_proof(client, sid, f"L{i}", source=_LEMMA_SRC)
        assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True
        lemmas.append(pid)

    main = _create_proof(client, sid, "Main", source=_USER_SRC)

    def queries_for(count: int) -> int:
        _set_refs(client, main, [
            {"referenced_proof_id": pid, "alias": f"A{n}" if n else "A"}
            for n, pid in enumerate(lemmas[:count])
        ])
        statements: list[str] = []
        engine = create_engine(db)
        event.listen(engine, "before_cursor_execute",
                     lambda *a, **k: statements.append(a[2]))
        try:
            with Session(engine) as session:
                system = session.scalar(select(FormalSystem))
                built = build_spec(system_to_spec(system))["system"]
                context = copy(built.context)
                context.variables.update(built.build_context.variables)
                statements.clear()
                load_proof_lines(
                    session, [uuid.UUID(pid) for pid in lemmas[:count]], built, context
                )
                return len(statements)
        finally:
            engine.dispose()

    # Same number of round trips for one lemma as for six.
    assert queries_for(1) == queries_for(6)
    assert queries_for(6) <= 3


def test_an_unverified_reference_the_proof_never_cites_is_not_reported(client, db):
    # "Not cited" explains a *failure*. A proof that stands on its own and merely
    # references something unverified has nothing to explain, and reporting it
    # alongside `success: true` reads as a contradiction. The scope is the
    # proof's own references, not the whole transitive closure.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    unverified = _create_proof(client, sid, "Unverified", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=VALID_PROOF)
    _set_refs(client, main, [{"referenced_proof_id": unverified, "alias": "A"}])

    body = client.post(f"/api/proofs/{main}/verify").json()
    assert body["success"] is True
    assert body["errors"] == []


def test_an_unverified_reference_no_failing_line_names_is_not_blamed(client, db):
    # A proof can fail for its own reasons while also declaring a reference it
    # never cites. Blaming the lemma then buries the real error under a claim the
    # reader can see is false — the failing line names no alias at all.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    unverified = _create_proof(client, sid, "Unverified", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=INVALID_PROOF)
    _set_refs(client, main, [{"referenced_proof_id": unverified, "alias": "A"}])

    body = client.post(f"/api/proofs/{main}/verify").json()
    assert body["success"] is False
    assert body["errors"] == []

    # ...but a line that *does* cite it is still explained.
    citing = _create_proof(client, sid, "Citing", source=_USER_SRC)
    _set_refs(client, citing, [{"referenced_proof_id": unverified, "alias": "A"}])
    explained = client.post(f"/api/proofs/{citing}/verify").json()
    assert explained["success"] is False
    assert any("must be verified" in error for error in explained["errors"])


def test_a_lemma_that_cannot_be_read_is_a_verdict_not_a_500(client, db, monkeypatch):
    # A stored row that no longer matches its system raises out of `load_term`,
    # and the line-numbering guard raises deliberately. Both are defects in
    # stored data, but every other failure on this path becomes a structured
    # verdict, and a corrupt lemma should not be the one that 500s.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{lemma}/verify")
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])

    def explode(*args, **kwargs):
        raise LookupError("No production or defined notation named 'gone'")

    monkeypatch.setattr(proofs_router, "load_proof_lines", explode)
    response = client.post(f"/api/proofs/{main}/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert any("could not be read" in error for error in body["errors"])


def test_re_verifying_checks_from_rows_and_parses_nothing(client, db, monkeypatch):
    # P2's measure (docs/verification-from-rows.md). The first verify parses,
    # because there is nothing stored yet. The second has rows for the proof's
    # own lines too, and everything `read_line` takes off the grammar is in them
    # — so it re-checks without touching the parser at all.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, spec=scoped_zfc_spec())
    # A proof with a subproof and a discharge, so the scope tree and the
    # justification graph are both rebuilt, not just flat lines.
    pid = _create_proof(client, sid, "CP", source=_SUBPROOF_SRC)

    parses: list[str] = []
    original = EngineFormalSystem.parse

    def counted(self, text, *args, **kwargs):
        parses.append(text)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(EngineFormalSystem, "parse", counted)

    first = client.post(f"/api/proofs/{pid}/verify").json()
    assert first["success"] is True
    assert len(parses) == 1, "the first check has nothing stored, so it parses"

    parses.clear()
    second = client.post(f"/api/proofs/{pid}/verify").json()
    assert second["success"] is True
    assert parses == [], "a proof checked once never needs its text again"


def test_checking_from_rows_is_idempotent(client, db):
    # The other half of the measure: same verdict, and byte-identical structure.
    # Numbering, scope and justification are all re-derived from the loaded
    # lines, so this says the rows are a faithful, self-sufficient record — not
    # that a cached verdict was handed back.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, spec=scoped_zfc_spec())
    pid = _create_proof(client, sid, "CP", source=_SUBPROOF_SRC)

    def snapshot() -> list[tuple]:
        lines = _structure(client, pid)["lines"]
        by_id = {line["id"]: line["number"] for line in lines}
        return [
            (
                line["position"], line["number"], line["display"], line["line_type"],
                line["rule"], line["valid"], line["opens_scope"],
                by_id.get(line["scope_id"]),
                tuple(
                    (edge["role"], edge["position"], by_id.get(edge["line_id"]))
                    for edge in line["antecedents"]
                ),
                (line["term"] or {}).get("digest"),
            )
            for line in lines
        ]

    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True
    once = snapshot()
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

    assert snapshot() == once
    assert once, "the proof stored no lines at all"


def test_a_proof_checked_from_rows_still_fails_when_it_should(client, db):
    # The rows supply what a line *says*, never whether it stands: the verdict is
    # re-derived. So a proof that fails, fails identically on the row path — and
    # a stored row cannot assert a line valid that the kernel would refuse.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    # Line 2 cites MP with one antecedent, so it cannot be justified.
    pid = _create_proof(
        client, sid, "Broken", source="(x ∈ y → x = y) [HYP]\nx = y [MP, 1]"
    )

    first = client.post(f"/api/proofs/{pid}/verify").json()
    assert first["success"] is False
    # The failed check still stores its structure, so the re-check reads rows.
    assert _structure(client, pid)["lines"], "a failed check stores no lines"

    second = client.post(f"/api/proofs/{pid}/verify").json()
    assert second["success"] is False
    assert [line["valid"] for line in second["proof"]["lines"]] == [
        line["valid"] for line in first["proof"]["lines"]
    ]


# ---------------------------------------------------------------------------
# Serialising verification against invalidation
# ---------------------------------------------------------------------------


@pytest.fixture
def locked(monkeypatch) -> list:
    """Record every system id `lock_system` is asked for.

    The lock itself is a Postgres advisory lock and a no-op on SQLite, so what a
    SQLite run can prove is that each path *takes* it. That the lock then
    excludes anything is a separate, Postgres-only test below.
    """
    taken: list = []
    real = _common.lock_system

    async def spy(session, system_id):
        taken.append(system_id)
        return await real(session, system_id)

    monkeypatch.setattr(_common, "lock_system", spy)
    monkeypatch.setattr(proofs_router, "lock_system", spy)
    monkeypatch.setattr(system_parts_router, "lock_system", spy)
    return taken


def test_verification_takes_the_system_lock_before_reading(client, db, locked):
    # The point of the whole exercise: a verify trusts its lemmas' stored rows,
    # so the read and the write must be one critical section. Locking just before
    # the write would let an invalidation commit in between.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "P", source=VALID_PROOF)

    locked.clear()
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True
    assert uuid.UUID(sid) in locked


@pytest.mark.parametrize(
    "invalidate",
    [
        pytest.param(
            lambda client, sid, pid: client.patch(
                f"/api/proofs/{pid}", json={"source": "x ∈ y [HYP]"}
            ),
            id="source-edit",
        ),
        pytest.param(
            lambda client, sid, pid: client.put(
                f"/api/proofs/{pid}/references", json={"references": []}
            ),
            id="reference-edit",
        ),
        pytest.param(
            lambda client, sid, pid: client.delete(f"/api/proofs/{pid}"),
            id="delete",
        ),
        pytest.param(
            lambda client, sid, pid: client.patch(
                f"/api/formal-systems/{sid}/rules/"
                + next(
                    r["id"]
                    for r in client.get(f"/api/formal-systems/{sid}").json()["rules"]
                    if r["label"] == "HYP"
                ),
                json={"name": "Hypothesis"},
            ),
            id="system-part-edit",
        ),
    ],
)
def test_every_invalidation_path_takes_the_system_lock(client, db, locked, invalidate):
    # A verify's read is only safe if *every* way of invalidating those rows
    # serialises against it. Forgetting one is how the guarantee would be lost,
    # and it would fail nothing else — hence a case per path.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "P", source=VALID_PROOF)
    client.post(f"/api/proofs/{pid}/verify")

    locked.clear()
    response = invalidate(client, sid, pid)
    assert response.status_code in (200, 204), response.text
    assert uuid.UUID(sid) in locked


@pytest.mark.skipif(not ON_POSTGRES, reason="advisory locks are a no-op off Postgres")
def test_the_system_lock_actually_excludes_a_second_transaction(db):
    # The spy tests above prove the paths ask for the lock; this proves the lock
    # means something. Two transactions, one key: the second cannot take it until
    # the first commits, which is what serialises a verify against an edit.
    import asyncio

    system_id = uuid.uuid4()

    async def exercise() -> tuple[bool, bool]:
        engine = create_async_engine(async_url(db), poolclass=NullPool)
        try:
            async with AsyncSession(engine) as holder, AsyncSession(engine) as other:
                await _common.lock_system(holder, system_id)
                # `try_` rather than the blocking form: a blocked acquire would
                # hang the test rather than fail it.
                blocked = await other.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                    {"k": str(system_id)},
                )
                await holder.rollback()
                free = await other.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                    {"k": str(system_id)},
                )
                return blocked, free
        finally:
            await engine.dispose()

    blocked, free = asyncio.run(exercise())
    assert blocked is False, "a second transaction took a lock the first was holding"
    assert free is True, "the lock outlived the transaction that took it"


def test_a_lemma_whose_structure_was_discarded_is_no_longer_citable(client, db):
    # The guarantee P1 rests on: a verdict is only as good as the invalidation
    # that clears it. Editing the system drops every proof's structure
    # (`discard_system_checks`), so a lemma checked against the old grammar stops
    # being citable — rather than a dependent silently resting on stored terms
    # whose constructors have since changed meaning.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{lemma}/verify")
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True

    # Any part edit invalidates every proof in the system, structure included.
    rules = client.get(f"/api/formal-systems/{sid}").json()["rules"]
    rule_id = next(r["id"] for r in rules if r["label"] == "HYP")
    assert client.patch(
        f"/api/formal-systems/{sid}/rules/{rule_id}", json={"name": "Hypothesis"}
    ).status_code == 200

    assert _structure(client, lemma)["lines"] == []
    body = client.post(f"/api/proofs/{main}/verify").json()
    assert body["success"] is False
    assert any("Lemma" in error for error in body["errors"])


def test_publish_requires_referenced_proofs_published(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)  # draft
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])

    # Can't publish while the referenced lemma is a draft.
    assert client.patch(f"/api/proofs/{main}", json={"published": True}).status_code == 422
    # Publish the lemma, then the dependent can publish (it verifies via the ref).
    assert client.patch(f"/api/proofs/{lemma}", json={"published": True}).status_code == 200
    assert client.patch(f"/api/proofs/{main}", json={"published": True}).status_code == 200


def test_editing_a_lemma_invalidates_dependents(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{lemma}/verify")
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True
    assert client.get(f"/api/proofs/{main}").json()["valid"] is True

    # Editing the lemma's source makes the dependent's cached verdict stale.
    assert client.patch(f"/api/proofs/{lemma}", json={"source": "x = x [HYP]"}).status_code == 200
    assert client.get(f"/api/proofs/{main}").json()["valid"] is None


def test_published_proof_rejects_adding_a_draft_reference(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    assert client.patch(f"/api/proofs/{lemma}", json={"published": True}).status_code == 200
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.patch(f"/api/proofs/{main}", json={"published": True}).status_code == 200

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
    assert client.patch(f"/api/proofs/{lemma}", json={"published": True}).status_code == 200
    assert client.patch(f"/api/proofs/{main}", json={"published": True}).status_code == 200

    # main (published) depends on lemma, so lemma is load-bearing.
    assert client.patch(f"/api/proofs/{lemma}", json={"published": False}).status_code == 409
    assert client.delete(f"/api/proofs/{lemma}").status_code == 409

    # Once the dependent is unpublished, the lemma is free again.
    assert client.patch(f"/api/proofs/{main}", json={"published": False}).status_code == 200
    assert client.patch(f"/api/proofs/{lemma}", json={"published": False}).status_code == 200
    assert client.delete(f"/api/proofs/{lemma}").status_code == 204


def test_draft_dependents_do_not_block_unpublish_or_delete(client, db):
    # Only *published* dependents lock a lemma. A draft dependent's verdict is
    # just invalidated.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)  # stays a draft
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.patch(f"/api/proofs/{lemma}", json={"published": True}).status_code == 200
    # A draft dependent doesn't block unpublishing the lemma...
    assert client.patch(f"/api/proofs/{lemma}", json={"published": False}).status_code == 200
    # ...nor deleting it (the draft dependent just goes stale).
    assert client.delete(f"/api/proofs/{lemma}").status_code == 204


# ---------------------------------------------------------------------------
# Stored proof structure: lines projected to kernel terms + justification edges
# ---------------------------------------------------------------------------

# Two hypotheses and the modus ponens they license. `[MP]` cites no lines, so the
# antecedents below are the ones the *checker* resolved — which is the point of
# storing edges rather than the reference string.
_MP_SRC = "x = x [HYP]\n(x = x → x = x) [HYP]\nx = x [MP]"


def _structure(client: TestClient, proof_id: str) -> dict:
    resp = client.get(f"/api/proofs/{proof_id}/structure")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _terms(db_path) -> list[TermRow]:
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            return list(session.scalars(select(TermRow)))
    finally:
        engine.dispose()


def test_structure_is_empty_until_the_proof_is_verified(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "Unchecked", source=_MP_SRC)

    assert _structure(client, pid) == {"proof_id": pid, "stored": False, "lines": []}

    client.post(f"/api/proofs/{pid}/verify")
    assert _structure(client, pid)["stored"] is True


def test_verify_stores_every_line_with_its_kernel_term(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

    lines = _structure(client, pid)["lines"]
    assert [line["position"] for line in lines] == [0, 1, 2]
    assert [line["number"] for line in lines] == [1, 2, 3]
    assert [line["behaviour"] for line in lines] == ["logical"] * 3
    assert [line["reference"] for line in lines] == ["HYP", "HYP", "MP"]
    # Here the written citation and the resolved rule agree; they need not (a
    # promoted theorem resolves to a rule in no system's rule list), which is why
    # both are stored.
    assert [line["rule"] for line in lines] == ["HYP", "HYP", "MP"]
    assert all(line["valid"] for line in lines)

    # Every formula reached the term graph, keyed by its top constructor.
    assert [line["term"]["constructor"] for line in lines] == [
        "equality", "implication", "equality",
    ]
    # And lines 1 and 3 are the *same* statement, so they share one interned row.
    assert lines[0]["term"]["id"] == lines[2]["term"]["id"]


def test_stored_terms_are_interned_per_system_not_per_line(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")

    # `x = x` three times, `(x = x → x = x)` once: three distinct subterms in all
    # (the variable `x`, the equality, the implication), stored once each.
    stored = {(term.kind, term.constructor, term.literal) for term in _terms(db)}
    assert stored == {
        ("node", "variable", "x"),
        ("node", "equality", None),
        ("node", "implication", None),
    }

    # Re-verifying reuses those rows rather than duplicating them.
    client.post(f"/api/proofs/{pid}/verify")
    assert len(_terms(db)) == 3


def test_stored_edges_record_the_lines_the_checker_actually_used(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")

    lines = _structure(client, pid)["lines"]
    assert lines[0]["antecedents"] == [] and lines[1]["antecedents"] == []
    # `[MP]` names no lines; the edges are the two the checker inferred, in slot
    # order, and they point at rows in this proof (not at a cited lemma).
    assert [(a["role"], a["line_id"]) for a in lines[2]["antecedents"]] == [
        ("antecedent", lines[0]["id"]),
        ("antecedent", lines[1]["id"]),
    ]
    assert all(a["proof_id"] is None for a in lines[2]["antecedents"])


def test_a_line_that_does_not_parse_is_stored_with_its_error_and_no_term(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "Broken", source=INVALID_PROOF)
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is False

    (line,) = _structure(client, pid)["lines"]
    assert line["valid"] is False
    assert line["line_type"] is None and line["behaviour"] is None
    # No formula to project, so no term — but the line itself is still recorded.
    assert line["term"] is None
    assert line["invalid_message"] is not None
    assert line["display"] == INVALID_PROOF


def test_editing_the_source_discards_the_stored_structure(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")
    assert len(_structure(client, pid)["lines"]) == 3

    # The snapshot describes a *checked* proof, so an edit drops it wholesale
    # rather than leaving rows that describe the old source.
    assert client.patch(f"/api/proofs/{pid}", json={"source": VALID_PROOF}).status_code == 200
    assert _structure(client, pid)["stored"] is False

    client.post(f"/api/proofs/{pid}/verify")
    assert [line["display"] for line in _structure(client, pid)["lines"]] == [VALID_PROOF]


def test_publishing_stores_the_structure_without_a_separate_verify(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    assert client.patch(f"/api/proofs/{pid}", json={"published": True}).status_code == 200
    assert len(_structure(client, pid)["lines"]) == 3


def test_a_citation_into_a_lemma_is_stored_by_proof_and_number(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{lemma}/verify")
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True

    lines = _structure(client, main)["lines"]
    edges = lines[1]["antecedents"]
    # `[MP, A.1, 1]` cites the lemma's line 1 and this proof's line 1. Edges are
    # stored in the *rule's* slot order (MP takes `p` then `(p → q)`), not the
    # order they were written, so compare as a set: what matters here is how each
    # target is addressed. The lemma's line lives in another proof — which owns
    # its own rows — so it is named by proof id and citation number, not by FK.
    assert [edge["position"] for edge in edges] == [0, 1]
    assert {(edge["proof_id"], edge["number"], edge["line_id"]) for edge in edges} == {
        (lemma, 1, None),
        (None, None, lines[0]["id"]),
    }


def test_editing_a_lemma_discards_the_dependents_structure(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    client.post(f"/api/proofs/{main}/verify")
    assert _structure(client, main)["stored"] is True

    # The dependent's structure was derived through the lemma, so it goes stale
    # with the verdict it was stored alongside.
    assert client.patch(f"/api/proofs/{lemma}", json={"source": VALID_PROOF}).status_code == 200
    assert _structure(client, main)["stored"] is False


def test_structure_visibility_follows_the_proof(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    draft = _create_proof(client, sid, "Draft", source=VALID_PROOF)
    public = _create_proof(client, sid, "Public", source=VALID_PROOF)
    assert client.patch(f"/api/proofs/{public}", json={"published": True}).status_code == 200
    _logout(client)

    assert client.get(f"/api/proofs/{draft}/structure").status_code == 404
    assert client.get(f"/api/proofs/{public}/structure").status_code == 200


def test_subproofs_and_discharge_are_stored_as_scope_and_edges(client, db):
    # The scoped system has assumption subproofs and a discharge rule (CP), so it
    # exercises the two structural things a flat proof cannot: a line that opens a
    # scope, and a line justified by a *block* rather than by cited lines.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, spec=scoped_zfc_spec())
    source = "assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → x ∈ y) [CP, 1]"
    pid = _create_proof(client, sid, "Conditional", source=source)
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

    opener, reiterated, discharge = _structure(client, pid)["lines"]
    assert opener["opens_scope"] == "assumption"
    # A scope opener is granted by fiat, so no rule justifies it.
    assert [line["rule"] for line in (opener, reiterated, discharge)] == [None, "R", "CP"]
    # The line under the opener is inside the subproof it opened; the opener
    # itself and the discharge line sit in the enclosing (root) scope.
    assert reiterated["scope_id"] == opener["id"]
    assert opener["scope_id"] is None
    assert discharge["scope_id"] is None
    # CP consumed the whole subproof, recorded by the opener that names it.
    assert [(a["role"], a["line_id"]) for a in discharge["antecedents"]] == [
        ("subproof", opener["id"])
    ]


def test_a_generic_definitional_step_records_which_definition_applied(client, db):
    # `[Def, 1]` names no definition — the checker searches those in scope — so
    # the edge to the source line is not on its own a complete justification.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "Unfold", source="x ⊆ y [HYP]\n(x = y → x = y) [Def, 1]")
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

    hypothesis, unfolded = _structure(client, pid)["lines"]
    # A rule justified the hypothesis; a definition justified the unfolding.
    assert (hypothesis["rule"], hypothesis["definition_id"]) == ("HYP", None)
    assert unfolded["rule"] is None
    assert unfolded["definition_id"] == _definition_id(client, sid, "subset")
    # The cited line is still recorded as the antecedent it is.
    assert [a["line_id"] for a in unfolded["antecedents"]] == [hypothesis["id"]]


def _definition_id(client: TestClient, system_id: str, name: str) -> str:
    definitions = client.get(f"/api/formal-systems/{system_id}").json()["definitions"]
    return next(d["id"] for d in definitions if d["name"] == name)


def test_editing_the_system_discards_its_proofs_checks(client, db):
    # A proof means nothing apart from the system it was checked against, so a
    # part edit invalidates both the verdict and the structure — whose terms name
    # productions the system may no longer have.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")
    assert client.get(f"/api/proofs/{pid}").json()["valid"] is True
    assert _structure(client, pid)["stored"] is True

    resp = client.post(
        f"/api/formal-systems/{sid}/rules",
        json={"label": "DS", "name": "disjunctive syllogism", "deduction": "q",
              "antecedents": ["p"], "bindings": [{"var": "p", "sort": "formula"},
                                                 {"var": "q", "sort": "formula"}]},
    )
    assert resp.status_code == 201, resp.text

    assert client.get(f"/api/proofs/{pid}").json()["valid"] is None
    assert _structure(client, pid)["stored"] is False
