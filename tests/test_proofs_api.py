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
from sqlalchemy import update as sa_update
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
from app.db.notations_mapping import store_notation
from app.db.terms_mapping import prefetch_terms
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
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
from website.logical.declarative import LinePart, LineSpec, SystemSpec, build_spec
from website.logical.formal_system import FormalSystem as EngineFormalSystem
from website.logical.rendering import Projection

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
        # A verify resolves the theorems a proof cites out of the library
        # (app/db/promoted_theorems.py), so the table must exist even for a
        # system that has none.
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
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

    # `read_proof`, not `parse`: reading a line off the grammar *is* the parse,
    # and the route calls it separately from the check so the theorems a proof
    # cites can be resolved between the two (P4). Counting `parse` would now
    # count zero and prove nothing.
    parses: list[str] = []
    original = EngineFormalSystem.read_proof

    def counted(self, text, *args, **kwargs):
        parses.append(text)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(EngineFormalSystem, "read_proof", counted)
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

    # Same number of round trips for one lemma as for six: the line rows, and
    # one sweep for every term below them.
    assert queries_for(1) == queries_for(6)
    assert queries_for(6) <= 2


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
    # A stored row that no longer matches its system raises out of `TermGraph.term`,
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

    # `read_proof`, not `parse`: reading a line off the grammar *is* the parse,
    # and the route calls it separately from the check so the theorems a proof
    # cites can be resolved between the two (P4). Counting `parse` would now
    # count zero and prove nothing.
    parses: list[str] = []
    original = EngineFormalSystem.read_proof

    def counted(self, text, *args, **kwargs):
        parses.append(text)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(EngineFormalSystem, "read_proof", counted)

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


@pytest.mark.parametrize(
    "name,source",
    [
        ("valid", VALID_PROOF),
        ("unjustified", "(x ∈ y → x = y) [HYP]\nx = y [MP, 1]"),
        # Matches no line type at all: the case that caught a real divergence —
        # the row records no line type, so nothing executed, so the line kept
        # `ProofLine`'s optimistic default and the proof flipped to valid.
        ("unparseable", INVALID_PROOF),
        ("unparseable-among-valid", VALID_PROOF + "\n" + INVALID_PROOF),
        ("blank-and-comment", VALID_PROOF + "\n\n" + VALID_PROOF),
        ("unknown-rule", "x = x [NOPE]"),
        ("indented", "    " + VALID_PROOF),
    ],
)
def test_the_row_path_and_the_parse_path_agree(client, db, name, source):
    # The property the whole phase rests on: a check from rows is the *same*
    # check, not a cheaper approximation of one. Asserted per line rather than on
    # the verdict alone, so a line agreeing by accident cannot hide a divergence.
    uid = _register_login(client, f"ada-{name}@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, name, source=source)

    def lines(body) -> list[tuple]:
        # Everything the checker decides about a line, not just its verdict: a
        # line agreeing by accident must not hide a divergence.
        return [
            (
                line["number"], line["display"], line["indent"], line["name"],
                line["behaviour"], line["reference"], line["label"],
                line["valid"], line["invalid_message"], line["warning_message"],
            )
            for line in body["proof"]["lines"]
        ]

    parsed = client.post(f"/api/proofs/{pid}/verify").json()   # nothing stored yet
    from_rows = client.post(f"/api/proofs/{pid}/verify").json()  # reads its own rows

    assert from_rows["success"] == parsed["success"]
    assert lines(from_rows) == lines(parsed)


def test_a_typed_line_with_no_term_cannot_stand(client, db):
    # The second shape of "a row asserts a line valid". A line whose type matched
    # but whose formula would not project is stored with its type and a *null*
    # term, and nothing in the row says the projection was what failed. Two of
    # the three behaviours never consult the formula — an axiom line asserts
    # itself by fiat, a scope opener is granted by fiat — so both would accept a
    # line stating nothing.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, spec=scoped_zfc_spec())
    pid = _create_proof(client, sid, "CP", source=_SUBPROOF_SRC)
    assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

    # Reproduce that stored state directly: the opener keeps its line type and
    # loses its term, which is exactly what a failed projection leaves behind.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            opener = session.scalars(
                select(ProofLineRow)
                .join(Proof)
                .where(Proof.id == uuid.UUID(pid), ProofLineRow.position == 0)
            ).one()
            assert opener.line_type is not None and opener.term_id is not None
            opener.term_id = None
            session.commit()
    finally:
        engine.dispose()

    body = client.post(f"/api/proofs/{pid}/verify").json()
    assert body["success"] is False
    opener_line = body["proof"]["lines"][0]
    assert opener_line["valid"] is False
    assert "formula" in (opener_line["invalid_message"] or "")


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


def test_publishing_locks_the_system_before_it_compiles_it(client, db, locked, monkeypatch):
    # `PATCH {"published": true}` is the one publish path that holds no lock of
    # its own — `update_proof` only locks on a *source* change. The gate then
    # compiles the system and writes a verdict derived from it, so the compile has
    # to be inside the critical section, not before it.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    pid = _create_proof(client, sid, "P", source=VALID_PROOF)

    order: list[str] = []
    real_lock = _common.lock_system

    async def note_lock(session, system_id):
        order.append("lock")
        return await real_lock(session, system_id)

    real_build = proofs_router.build_spec

    def note_build(*args, **kwargs):
        order.append("build")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(_common, "lock_system", note_lock)
    monkeypatch.setattr(proofs_router, "lock_system", note_lock)
    monkeypatch.setattr(proofs_router, "build_spec", note_build)

    res = client.patch(f"/api/proofs/{pid}", json={"published": True})
    assert res.status_code == 200, res.text
    assert order and order[0] == "lock", order
    assert "build" in order


def test_a_publish_refused_on_a_cheap_gate_does_not_compile(client, db, monkeypatch):
    # Both early gates are answerable from the system row alone. A publish they
    # refuse used to pay a full compile — ~54 ms on a corpus system — and throw it
    # away.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)  # a draft system: the first gate refuses
    pid = _create_proof(client, sid, "P", source=VALID_PROOF)

    builds = _builds(monkeypatch)
    res = client.patch(f"/api/proofs/{pid}", json={"published": True})
    assert res.status_code == 400, res.text
    assert "unpublished draft" in res.json()["detail"]
    assert builds == [0]


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


def _proof_terms(db_path, proof_id) -> list[TermRow]:
    """Every term row reachable from one proof's lines."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            roots = list(session.scalars(
                select(ProofLineRow.term_id).where(
                    ProofLineRow.proof_id == uuid.UUID(proof_id),
                    ProofLineRow.term_id.is_not(None),
                )
            ))
            # The closure as `TermGraph` knows it, then the rows themselves: this
            # asserts on what was *stored*, so it reads the ORM rows rather than
            # the flat ones the graph rebuilds from.
            ids = prefetch_terms(session, roots).ids
            return list(session.scalars(select(TermRow).where(TermRow.id.in_(ids))))
    finally:
        engine.dispose()


def test_structure_is_empty_until_the_proof_is_verified(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "Unchecked", source=_MP_SRC)

    assert _structure(client, pid) == {
        "proof_id": pid, "stored": False, "notation": None, "lines": []
    }

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


def test_an_anonymous_verify_of_a_published_proof_writes_nothing(client, db):
    # A non-owner's transaction is never committed: the verdict comes back and
    # the stored state does not move. Verify now writes the schema-term cache as
    # well as the verdict, so this pins the contract over that too — cleared
    # first, so a write that reached the database would be visible rather than
    # merely redundant. (Verify also *skips* that write for a non-owner; that is
    # an efficiency guard on work the rollback would discard, so it leaves no
    # trace either way and this cannot distinguish it.)
    owner = _register_login(client, "ada@example.com")
    sid = _seed_system(db, owner, published=True)
    pid = _create_proof(client, sid, "Public", source=VALID_PROOF)
    assert client.patch(f"/api/proofs/{pid}", json={"published": True}).status_code == 200

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.execute(sa_update(RuleRow).values(schema_digest=None))
            session.commit()

        _logout(client)
        assert client.post(f"/api/proofs/{pid}/verify").json()["success"] is True

        with Session(engine) as session:
            assert session.scalars(select(RuleRow.schema_digest)).all() == [None, None]
    finally:
        engine.dispose()


def test_stored_terms_are_interned_per_system_not_per_line(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")

    # The proof's own subgraph, not the system's: a verify also stores the rules'
    # schema terms into the same interned graph (app/db/schema_terms.py), and
    # those are a property of the system rather than of this proof.
    # `x = x` three times, `(x = x → x = x)` once: three distinct subterms in all
    # (the variable `x`, the equality, the implication), stored once each.
    stored = {(term.kind, term.constructor, term.literal) for term in _proof_terms(db, pid)}
    assert stored == {
        ("node", "variable", "x"),
        ("node", "equality", None),
        ("node", "implication", None),
    }

    # Re-verifying reuses those rows rather than duplicating them.
    client.post(f"/api/proofs/{pid}/verify")
    assert len(_proof_terms(db, pid)) == 3


def test_verifying_stores_the_definition_forms_and_reuses_them(client, db):
    # The route wiring for app/db/definition_terms.py: everything in
    # tests/test_definition_terms.py drives load/store directly, so this is what
    # says the verify path actually calls them. The seeded system carries one
    # definition, whose two forms the first build parses and stores.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "MP", source=_MP_SRC)

    def stored_forms():
        with Session(create_engine(db)) as session:
            return [
                (d.term_digest, d.higher_term_id, d.lower_term_id)
                for d in session.scalars(select(DefinitionRow))
            ]

    assert stored_forms() == [(None, None, None)]

    client.post(f"/api/proofs/{pid}/verify")
    (digest, higher, lower) = stored_forms()[0]
    assert digest is not None
    assert higher is not None and lower is not None

    # A second verify reads them and writes nothing new — the digest already
    # matches, so `store_definition_terms` is a comparison per definition.
    client.post(f"/api/proofs/{pid}/verify")
    assert stored_forms() == [(digest, higher, lower)]


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


def _seed_notation(db_path, system_id: str, name: str, templates: dict) -> None:
    """Give a seeded system one named notation, as an import would."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            store_notation(
                session, uuid.UUID(system_id), Projection(templates=templates, name=name)
            )
            session.commit()
    finally:
        engine.dispose()


# The ZFC fragment writes `x = x`; this reads it as `x ≡ x`. Deliberately not the
# source spelling, so a rendered line cannot be mistaken for the stored `display`.
#
# `implication` is re-spelled as itself rather than left out, because a *stored*
# notation must name every constructor: a reader has rows and no grammar, so an
# unnamed one has no source template to fall back to. `total_projection` is what
# completes a derived notation; here the two productions are written out.
_EQUIV = {
    "equality": (("slot", "s"), ("lit", " ≡ "), ("slot", "t")),
    "implication": (
        ("lit", "("), ("slot", "p"), ("lit", " → "), ("slot", "q"), ("lit", ")")
    ),
}


def test_the_system_detail_lists_the_notations_it_stores(client, db):
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)

    assert client.get(f"/api/formal-systems/{sid}").json()["notations"] == []

    _seed_notation(db, sid, "equiv", _EQUIV)
    assert client.get(f"/api/formal-systems/{sid}").json()["notations"] == ["equiv"]


def test_a_line_reads_in_a_requested_notation(client, db):
    # The whole point: one checked term, read a second way, with no re-check and
    # no second copy of the proof.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    _seed_notation(db, sid, "equiv", _EQUIV)
    pid = _create_proof(client, sid, "Renamed", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")

    plain = _structure(client, pid)
    assert plain["notation"] is None
    # Asking for none leaves the field empty rather than repeating `display`: the
    # source spelling is already there, and a null says "not projected".
    assert [line["rendered"] for line in plain["lines"]] == [None, None, None]

    resp = client.get(f"/api/proofs/{pid}/structure", params={"notation": "equiv"})
    assert resp.status_code == 200, resp.text
    read = resp.json()
    assert read["notation"] == "equiv"
    assert [line["rendered"] for line in read["lines"]] == [
        "x ≡ x", "(x ≡ x → x ≡ x)", "x ≡ x"
    ]
    # The source is untouched by the reading of it — and note what `rendered` is
    # *not*: `display` is the whole authored line, citation included, while a
    # projection renders the line's term, which is the formula alone. A client
    # showing a notation supplies the citation from `reference`/`rule`.
    assert [line["display"] for line in read["lines"]] == [
        "x = x [HYP]", "(x = x → x = x) [HYP]", "x = x [MP]"
    ]


def test_a_notation_the_system_does_not_store_is_a_404(client, db):
    # Not a silent fall back to the source: that would look like the notation had
    # no opinion about any line, rather than like a typo in its name.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    pid = _create_proof(client, sid, "Plain", source=_MP_SRC)
    client.post(f"/api/proofs/{pid}/verify")

    resp = client.get(f"/api/proofs/{pid}/structure", params={"notation": "latex"})
    assert resp.status_code == 404
    assert "latex" in resp.json()["detail"]


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


# ---------------------------------------------------------------------------
# A stored term's shape (GET /formal-systems/{id}/terms/{term_id})
#
# What `ProofStructure` cannot say: it gives each line's term as a root identity,
# and a reader wanting the formula's *parts* had to fall back to a rendered
# string. A string cannot be pointed at.
# ---------------------------------------------------------------------------

# `x = y` twice under one implication. Interning makes that *one* row, which is
# the property the flat shape exists to preserve.
_SHARED_SUBTERM = "(x = y → x = y) [HYP]"

# Deliberately not the source spelling, so a node's reading cannot be mistaken
# for its stored shape.
_DEMO_TEMPLATES = {
    "equality": (("slot", "s"), ("lit", " EQ "), ("slot", "t")),
    "implication": (
        ("lit", "("),
        ("slot", "p"),
        ("lit", " IMP "),
        ("slot", "q"),
        ("lit", ")"),
    ),
}


def _stored_term(client: TestClient, db_path, owner: str) -> tuple[str, str]:
    """A verified proof's first term, as (system id, term id)."""
    system_id = _seed_system(db_path, owner)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": _SHARED_SUBTERM},
    ).json()
    assert client.post(f"/api/proofs/{created['id']}/verify").json()["success"] is True
    term = _structure(client, created["id"])["lines"][0]["term"]
    assert term is not None
    return system_id, term["id"]


def test_a_shared_subterm_is_one_node_referenced_twice(client, db):
    # The reason the response is flat rather than nested. `x = y` occurs at both
    # slots of the implication and is one interned row; nesting would emit it
    # twice and lose the sharing the storage exists for — and with it the ability
    # to refer to a part instead of restating it.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)

    body = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}").json()

    assert body["root"] == term_id
    assert body["truncated"] is False
    ids = [node["id"] for node in body["nodes"]]
    assert len(ids) == len(set(ids)), "a node must be reported once"
    root = next(node for node in body["nodes"] if node["id"] == term_id)
    slots = {child["slot"]: child["id"] for child in root["children"]}
    assert len(slots) == 2
    assert len(set(slots.values())) == 1, "both slots should name the same row"
    # And that row is in the response exactly once, reachable by both edges.
    assert ids.count(next(iter(slots.values()))) == 1


def test_every_node_carries_its_identity(client, db):
    # The digests are the point of serving nodes at all: structural equality and
    # equality up to renaming become id comparisons rather than string ones.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)

    body = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}").json()

    assert all(node["digest"] for node in body["nodes"])
    root = next(node for node in body["nodes"] if node["id"] == term_id)
    assert root["depth"] == 0
    assert root["kind"] == "node"
    assert root["constructor"]


def test_depth_bounds_the_output_and_marks_the_horizon(client, db):
    # A reader must be able to tell a leaf from a horizon, or it will believe a
    # formula ended where the request did. The children are reported either way,
    # so a deeper request can be aimed rather than repeated.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)

    body = client.get(
        f"/api/formal-systems/{system_id}/terms/{term_id}?depth=0"
    ).json()

    assert [node["id"] for node in body["nodes"]] == [term_id]
    assert body["truncated"] is True
    assert body["nodes"][0]["truncated"] is True
    assert body["nodes"][0]["children"], "the horizon still names what is below it"

    # The implication, the equality both its slots share, and the two variable
    # leaves. Pinned exactly, because a claim about the shape of this response is
    # the sort of thing prose in a roadmap gets wrong.
    whole = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}").json()
    assert len(whole["nodes"]) == 4
    assert whole["truncated"] is False


def test_a_child_reachable_within_the_bound_is_not_called_missing(client, db):
    # `truncated` is about what the response *omits*, not about which nodes sat at
    # the horizon. In a DAG a child beyond one node's bound is often reachable
    # within another's and already present — reporting the response incomplete
    # when it is complete costs a caller a wasted deeper request.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)

    # At depth 1: the implication and the equality it shares. The equality's own
    # children are absent, so it *is* truncated; the root is not.
    body = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}?depth=1").json()
    by_id = {node["id"]: node for node in body["nodes"]}

    assert by_id[term_id]["truncated"] is False, "both its children are present"
    assert body["truncated"] is True, "the equality's leaves are not"

    # And at full depth nothing is missing anywhere.
    whole = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}").json()
    assert not any(node["truncated"] for node in whole["nodes"])


def test_a_notation_reads_every_node(client, db):
    # The headline: the identity *and* the projection of every part at once, so a
    # caller can point at a subterm by id without restating it.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)
    _seed_notation(db, system_id, "demo", _DEMO_TEMPLATES)

    body = client.get(
        f"/api/formal-systems/{system_id}/terms/{term_id}?notation=demo"
    ).json()

    assert body["notation"] == "demo"
    readings = {node["id"]: node["rendered"] for node in body["nodes"]}
    assert readings[term_id] == "(x EQ y IMP x EQ y)"
    # Each part reads in full, including the shared one.
    assert "x EQ y" in readings.values()


def test_a_node_at_the_horizon_still_reads_in_full(client, db):
    # `depth` bounds what is *listed*, not what is rendered — a truncated node
    # that read as a hole would make a shallow request useless.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)
    _seed_notation(db, system_id, "demo", _DEMO_TEMPLATES)

    body = client.get(
        f"/api/formal-systems/{system_id}/terms/{term_id}?notation=demo&depth=0"
    ).json()

    assert body["nodes"][0]["truncated"] is True
    assert body["nodes"][0]["rendered"] == "(x EQ y IMP x EQ y)"


def test_a_notation_the_system_does_not_store_is_404(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)

    res = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}?notation=nope")
    assert res.status_code == 404


def test_a_term_of_another_system_is_not_found(client, db):
    # A term belongs to the system that interned it. Serving another system's row
    # would leak a draft's contents to anyone who could guess an id.
    owner = _register_login(client, "ada@example.com")
    _system_id, term_id = _stored_term(client, db, owner)
    other = _seed_system(db, owner)

    res = client.get(f"/api/formal-systems/{other}/terms/{term_id}")
    assert res.status_code == 404


def test_an_unknown_term_id_is_not_found(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id, _term_id = _stored_term(client, db, owner)

    res = client.get(f"/api/formal-systems/{system_id}/terms/{uuid.uuid4()}")
    assert res.status_code == 404


def test_a_draft_systems_terms_are_owner_only(client, db):
    # Visibility is the system's, which is the reason the route hangs off it.
    owner = _register_login(client, "ada@example.com")
    system_id, term_id = _stored_term(client, db, owner)
    _register_login(client, "grace@example.com")

    res = client.get(f"/api/formal-systems/{system_id}/terms/{term_id}")
    assert res.status_code == 404


def test_an_unknown_term_is_refused_before_a_notation_is_loaded(client, db):
    # Ordering, not semantics: both are 404s, but loading a notation is thousands
    # of rows on a corpus-sized system and a caller with a random id must not be
    # able to make this route pay for it. The notation here is real, so a 404 can
    # only be the term check — and it has to have run first.
    owner = _register_login(client, "ada@example.com")
    system_id, _term_id = _stored_term(client, db, owner)
    _seed_notation(db, system_id, "demo", _DEMO_TEMPLATES)

    res = client.get(
        f"/api/formal-systems/{system_id}/terms/{uuid.uuid4()}?notation=demo"
    )
    assert res.status_code == 404
    assert "term" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Structured citation proposals (POST /proofs/{id}/cite)
#
# The write half of the structured path, and the cheap half of it: a citation is
# a label and some integers, so this needs none of the term algebra that stating
# a new formula would.
# ---------------------------------------------------------------------------

# Two holes and a step that follows from them by MP. The step is a hole to begin
# with, which is how a proof gets written top-down.
_HOLED = "x ∈ y [?]\n(x ∈ y → y ∈ x) [?]\ny ∈ x [?]"


def _holed_proof(client: TestClient, db_path, owner: str) -> tuple[str, str]:
    system_id = _seed_system(db_path, owner)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": _HOLED},
    ).json()
    verdict = client.post(f"/api/proofs/{created['id']}/verify").json()
    assert verdict["holes"] == [1, 2, 3], verdict
    assert verdict["only_holes"] is True
    return system_id, created["id"]


def test_a_citation_is_proposed_as_a_label_and_line_numbers(client, db):
    # The point of the endpoint: no citation syntax crosses the wire, and the
    # response says what the proposal actually formatted to.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1, 2]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["citation"] == "MP, 1, 2"
    assert body["accepted"] is True
    assert body["failure"] is None


def _builds(monkeypatch) -> list[int]:
    """Count how many times a request compiles the system.

    Counted rather than timed, because the thing worth pinning is structural: a
    build is one object per request or it is not, and a wall-clock assertion would
    be flaky about a fact that is exact.
    """
    seen = [0]
    real = proofs_router.build_spec

    def counting(*args, **kwargs):
        seen[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(proofs_router, "build_spec", counting)
    return seen


def test_a_citation_compiles_the_system_once(client, db, monkeypatch):
    # `/cite` needs the grammar to rewrite the line *before* it can check the
    # result, and used to build a second system inside the verify to do the
    # checking — the single largest thing the route did, on a corpus system
    # (docs/authoring-and-ingestion-roadmap.md §9e).
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    builds = _builds(monkeypatch)
    res = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1, 2], "apply": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] is True
    assert builds == [1]


def test_adding_a_line_compiles_the_system_once(client, db, monkeypatch):
    # The same for `/lines`, which needs the grammar earlier still: it resolves a
    # proposal against it and renders the term back out.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    builds = _builds(monkeypatch)
    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            },
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert builds == [1]


def test_a_dry_run_changes_nothing(client, db):
    # A caller trying several justifications for one hole must not have to undo
    # the ones that did not work.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1, 2]},
    )

    detail = client.get(f"/api/proofs/{proof_id}").json()
    assert detail["source"] == _HOLED
    assert _structure(client, proof_id)["lines"][2]["failure"]["code"] == "hole"


def test_applying_rewrites_the_source_and_reports_where_the_proof_stands(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    body = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1, 2], "apply": True},
    ).json()

    assert body["applied"] is True
    assert body["accepted"] is True
    # Two holes left, and nothing wrong — which is what a loop reads to decide
    # whether it has work or a bug.
    assert body["holes"] == [1, 2]
    assert body["only_holes"] is True
    assert body["valid"] is False

    detail = client.get(f"/api/proofs/{proof_id}").json()
    assert detail["source"].splitlines()[2] == "y ∈ x [MP, 1, 2]"


def test_a_rejected_proposal_names_the_next_goal(client, db):
    # The loop closes here: a citation that does not apply comes back with the
    # same structured reason a verify gives, so the missing premise is named
    # rather than guessed at.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    body = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1]},
    ).json()

    assert body["accepted"] is False
    assert body["failure"]["code"] == "antecedent-count"
    assert body["failure"]["expected"] == 2


def test_a_line_can_be_parked_as_a_goal_again(client, db):
    # A hole is a citation, so retracting a step needs no special case — the same
    # endpoint, with the hole keyword as the rule.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)
    client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "MP", "antecedents": [1, 2], "apply": True},
    )

    body = client.post(
        f"/api/proofs/{proof_id}/cite", json={"line": 3, "rule": "?", "apply": True}
    ).json()

    assert body["citation"] == "?"
    assert body["holes"] == [1, 2, 3]
    detail = client.get(f"/api/proofs/{proof_id}").json()
    assert detail["source"] == _HOLED


def test_an_unknown_rule_is_a_rejection_and_not_an_error(client, db):
    # A machine caller guessing a label should get a verdict it can act on, not
    # a 4xx it has to special-case.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    body = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={"line": 3, "rule": "NOPE", "antecedents": [1]},
    ).json()

    assert body["accepted"] is False
    assert body["failure"]["code"] == "bad-reference"


def test_a_line_the_stored_structure_does_not_number_is_409(client, db):
    # Lines are addressed by citation number, which only a verified proof has.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/cite", json={"line": 99, "rule": "MP"}
    )
    assert res.status_code == 409
    assert "verify" in res.json()["detail"].lower()


def test_applying_is_owner_only(client, db):
    # A published proof is readable by anyone, so a dry run is too — but an edit
    # is an edit. (Published, because a proof with holes cannot be: publishing is
    # gated on verifying, and a hole is exactly what stops one doing so.)
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF},
    ).json()
    assert client.patch(
        f"/api/proofs/{created['id']}", json={"published": True}
    ).status_code == 200
    _register_login(client, "grace@example.com")

    proposal = {"line": 1, "rule": "HYP"}
    assert (
        client.post(f"/api/proofs/{created['id']}/cite", json=proposal).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/proofs/{created['id']}/cite", json={**proposal, "apply": True}
        ).status_code
        == 403
    )


def test_applying_a_citation_invalidates_dependents(client, db):
    # Applying is a *source edit*, so every consequence of one applies. Without
    # this a proof laundering through a lemma broken here would keep verifying
    # against a cached verdict for a source that no longer says what it did.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    main = _create_proof(client, sid, "Main", source=_USER_SRC)
    client.post(f"/api/proofs/{lemma}/verify")
    _set_refs(client, main, [{"referenced_proof_id": lemma, "alias": "A"}])
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is True
    assert client.get(f"/api/proofs/{main}").json()["valid"] is True

    # Park the lemma's only line as a goal: it no longer proves anything.
    body = client.post(
        f"/api/proofs/{lemma}/cite", json={"line": 1, "rule": "?", "apply": True}
    ).json()
    assert body["applied"] is True

    assert client.get(f"/api/proofs/{main}").json()["valid"] is None
    assert client.post(f"/api/proofs/{main}/verify").json()["success"] is False


def test_a_promoted_proof_survives_a_citation_that_would_break_it(client, db):
    """The library entry cannot be left warranted by a proof that no longer stands.

    Two things protect it, and only one of them is reachable. Promotion requires
    publication, and a published proof cannot be edited into not verifying — so a
    citation that would break a promoted proof is refused before it lands, and the
    entry is never orphaned. `/cite` retires the promotion anyway, as a source
    edit must, but with that gate in place there is no path that reaches it.
    """
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    lemma = _create_proof(client, sid, "Lemma", source=_LEMMA_SRC)
    assert client.patch(f"/api/proofs/{lemma}", json={"published": True}).status_code == 200
    promoted = client.post(f"/api/proofs/{lemma}/promote", json={"label": "lem"})
    assert promoted.status_code in (200, 201), promoted.text

    res = client.post(
        f"/api/proofs/{lemma}/cite", json={"line": 1, "rule": "?", "apply": True}
    )
    assert res.status_code == 422

    detail = client.get(f"/api/proofs/{lemma}").json()
    assert detail["theorem"]["label"] == "lem"
    assert detail["valid"] is True
    assert detail["source"] == _LEMMA_SRC


def test_applying_a_citation_cannot_break_a_published_proof(client, db):
    # A world-readable proof may not be edited into a non-verifying state, and
    # `[?]` is exactly such an edit — so the publish gate is load-bearing here
    # rather than inherited. The whole proposal rolls back.
    uid = _register_login(client, "ada@example.com")
    sid = _seed_system(db, uid, published=True)
    proof_id = _create_proof(client, sid, "P", source=VALID_PROOF)
    assert client.patch(f"/api/proofs/{proof_id}", json={"published": True}).status_code == 200

    res = client.post(
        f"/api/proofs/{proof_id}/cite", json={"line": 1, "rule": "?", "apply": True}
    )
    assert res.status_code == 422

    detail = client.get(f"/api/proofs/{proof_id}").json()
    assert detail["source"] == VALID_PROOF
    assert detail["valid"] is True


# A scope opener that *also* declares a reference field. Nothing forbids it, and
# such a line is granted by fiat — so its citation is never resolved, and reading
# a proposal's outcome off the line's validity would report `accepted` for a
# citation nothing looked at.
def _scoped_with_reference_spec() -> SystemSpec:
    return SystemSpec(
        name="ND",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), equality_prod(),
                     implication_prod()],
        lines=[
            statement_line(),
            LineSpec(
                name="assume",
                shape="assume <formula> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.?]+")],
                logical_sort="formula",
                scope="assumption",
            ),
        ],
        rules=[hyp_rule(), mp_rule()],
    )


def test_a_line_no_citation_justifies_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, spec=_scoped_with_reference_spec())
    created = client.post(
        "/api/proofs",
        json={
            "name": "P",
            "formal_system_id": system_id,
            "source": "assume x ∈ y [HYP]\n    x ∈ y [HYP]",
        },
    ).json()
    assert client.post(f"/api/proofs/{created['id']}/verify").json()["success"] is True

    res = client.post(
        f"/api/proofs/{created['id']}/cite",
        json={"line": 1, "rule": "NOPE", "antecedents": [99]},
    )

    # Refused, rather than reported accepted — the scope opener is valid whatever
    # its reference says, so its validity is no evidence about the citation.
    assert res.status_code == 422
    assert "granted" in res.json()["detail"]
    # And nothing was written, even though this was a dry run anyway.
    assert client.get(f"/api/proofs/{created['id']}").json()["source"].startswith(
        "assume x ∈ y [HYP]"
    )


# ---------------------------------------------------------------------------
# Structured statement proposals (POST /proofs/{id}/lines)
#
# The expensive half: stating a formula needs the grammar, so this is where the
# constructor vocabulary crosses the wire. The round trip is checked, not
# trusted — the term that parses back must be the term that went in.
# ---------------------------------------------------------------------------


def _one_line_proof(client: TestClient, db_path, owner: str) -> tuple[str, str]:
    system_id = _seed_system(db_path, owner)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": "x ∈ y [HYP]"},
    ).json()
    assert client.post(f"/api/proofs/{created['id']}/verify").json()["success"] is True
    return system_id, created["id"]


def test_a_statement_is_proposed_as_a_production_and_its_slots(client, db):
    # No surface syntax crosses the wire: `membership` is a production of the
    # system's own grammar, and the response shows the source its structure became.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["display"] == "y ∈ x [?]"
    assert body["line"] == 2
    # A hole by default: stating a premise you have not proved *is* an open goal.
    assert body["failure"]["code"] == "hole"


def test_a_statement_may_point_at_a_term_that_already_exists(client, db):
    # The reason the structured path is worth having: an interned term is shared,
    # so a caller says "that subterm" instead of restating it.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)
    existing = _structure(client, proof_id)["lines"][0]["term"]["id"]

    body = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "implication",
                "slots": {"p": {"ref": existing}, "q": {"ref": existing}},
            }
        },
    ).json()

    assert body["display"] == "(x ∈ y → x ∈ y) [?]"


def test_a_term_of_another_system_is_refused(client, db):
    # Interning is per system, so a foreign id names a term built over another
    # grammar — stating one would mean a formula this system cannot.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)
    _other_system, other_proof = _one_line_proof(client, db, owner)
    foreign = _structure(client, other_proof)["lines"][0]["term"]["id"]

    res = client.post(
        f"/api/proofs/{proof_id}/lines", json={"statement": {"ref": foreign}}
    )
    assert res.status_code == 422
    assert "no term with id" in res.json()["detail"]


def test_a_proposal_naming_the_wrong_slots_says_which(client, db):
    # A rejection in a structured path should name the production and the slot,
    # not say that something was wrong.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {"s": {"constructor": "variable", "literal": "y"}},
            }
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "membership" in detail and "missing: t" in detail


def test_a_production_the_grammar_lacks_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/lines", json={"statement": {"constructor": "nope"}}
    )
    assert res.status_code == 422
    assert "no production" in res.json()["detail"]


def test_inserting_a_line_moves_the_citations_below_it(client, db):
    # Citation numbers are positional, so a line added above one moves every
    # citation that named it — silently, because the old number still resolves.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/api/proofs",
        json={
            "name": "P",
            "formal_system_id": system_id,
            "source": "x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]",
        },
    ).json()
    proof_id = created["id"]
    assert client.post(f"/api/proofs/{proof_id}/verify").json()["success"] is True

    body = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            },
            "before": 1,
            "apply": True,
        },
    ).json()

    assert body["line"] == 1
    assert body["renumbered"] == [2, 3, 4]
    source = client.get(f"/api/proofs/{proof_id}").json()["source"].splitlines()
    assert source[0] == "y ∈ x [?]"
    # The MP citation followed its premises down.
    assert source[3] == "x = y [MP, 2, 3]"
    # And the proof still stands apart from the goal just added.
    assert body["only_holes"] is True


def test_appending_displaces_nothing(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    body = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            },
            "apply": True,
        },
    ).json()

    assert body["renumbered"] == []
    assert client.get(f"/api/proofs/{proof_id}").json()["source"].splitlines() == [
        "x ∈ y [HYP]",
        "y ∈ x [?]",
    ]


def test_a_dry_run_adds_nothing(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            }
        },
    )

    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == "x ∈ y [HYP]"


def test_a_new_line_may_be_justified_at_once(client, db):
    # The other half of the loop: state the premise and cite it in one step.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    created = client.post(
        "/api/proofs",
        json={
            "name": "P",
            "formal_system_id": system_id,
            "source": "x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]",
        },
    ).json()
    proof_id = created["id"]
    client.post(f"/api/proofs/{proof_id}/verify")

    body = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "equality",
                "slots": {
                    "s": {"constructor": "variable", "literal": "x"},
                    "t": {"constructor": "variable", "literal": "y"},
                },
            },
            "rule": "MP",
            "antecedents": [1, 2],
            "apply": True,
        },
    ).json()

    assert body["display"] == "x = y [MP, 1, 2]"
    assert body["accepted"] is True
    assert body["valid"] is True
    assert body["holes"] == []


def test_adding_a_line_is_owner_only(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": VALID_PROOF},
    ).json()
    assert client.patch(
        f"/api/proofs/{created['id']}", json={"published": True}
    ).status_code == 200
    _register_login(client, "grace@example.com")

    proposal = {
        "statement": {
            "constructor": "equality",
            "slots": {
                "s": {"constructor": "variable", "literal": "x"},
                "t": {"constructor": "variable", "literal": "x"},
            },
        }
    }
    assert (
        client.post(f"/api/proofs/{created['id']}/lines", json=proposal).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/proofs/{created['id']}/lines", json={**proposal, "apply": True}
        ).status_code
        == 403
    )


def test_a_new_line_keeps_the_indentation_of_the_line_it_copies(client, db):
    """Indentation is what places a line in a subproof, not decoration.

    `display` is stored stripped — the indent is its own column — so a line
    composed from it and written as-is lands at the root, silently escaping the
    scope it was meant to join. The `_broken_by_insert` guard catches that when
    something below depends on it; appending has nothing below, so nothing else
    would.
    """
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, spec=scoped_zfc_spec())
    created = client.post(
        "/api/proofs",
        json={
            "name": "P",
            "formal_system_id": system_id,
            "source": "assume x ∈ y\n    x ∈ y [R, 1]",
        },
    ).json()
    proof_id = created["id"]
    assert client.post(f"/api/proofs/{proof_id}/verify").json()["success"] is True

    body = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "x": {"constructor": "setvar_atom", "literal": "y"},
                    "y": {"constructor": "setvar_atom", "literal": "x"},
                },
            },
            "apply": True,
        },
    ).json()

    assert body["display"] == "    y ∈ x [?]"
    assert client.get(f"/api/proofs/{proof_id}").json()["source"].splitlines()[2] == (
        "    y ∈ x [?]"
    )


def test_a_metavariable_is_not_something_a_line_can_state(client, db):
    """A proof line states a *ground* formula.

    The engine's `Proposal` has a `var` arm — `Var` is a term — but the API's does
    not, because one could never survive the round trip: `Q` parses back as the
    grammar's variable *production*, a `Node`, not as a schematic `Var`. Offering
    it and refusing it would be worse than leaving it out, so the field is absent
    and a caller naming it gets the ordinary "names nothing" rejection.
    """
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": {"var": "Q", "sort": "formula"}},
    )

    assert res.status_code == 422
    assert "exactly one of" in res.json()["detail"]


def test_a_ref_that_carries_slots_is_refused(client, db):
    # The arm where silence would be worst: a referenced term *is* the term that
    # comes back, so the round-trip check cannot notice that slots were meant to
    # qualify it, and an applying request would commit a line stating something
    # other than what was asked for.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _one_line_proof(client, db, owner)
    existing = _structure(client, proof_id)["lines"][0]["term"]["id"]

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "ref": existing,
                "slots": {"s": {"constructor": "variable", "literal": "y"}},
            },
            "apply": True,
        },
    )

    assert res.status_code == 422
    assert "does not use" in res.json()["detail"]
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == "x ∈ y [HYP]"


def test_a_referenced_term_the_grammar_has_outgrown_is_refused(client, db):
    """A term row outlives the production that built it.

    So the same-system ownership check passes for an id whose constructor has
    since been renamed, and the raise surfaces from `TermGraph.term` during the
    rebuild. That is a stale id in a request rather than a fault here — 422, as
    `_verify_with_references` already reshapes the same raise from a lemma's rows.
    """
    owner = _register_login(client, "ada@example.com")
    system_id, proof_id = _one_line_proof(client, db, owner)
    existing = _structure(client, proof_id)["lines"][0]["term"]["id"]

    # Rename the production the stored term names, leaving the term row behind.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.execute(
                sa_update(SymbolRow)
                .where(
                    SymbolRow.system_id == uuid.UUID(system_id),
                    SymbolRow.name == "membership",
                )
                .values(name="membership_renamed")
            )
            session.commit()
    finally:
        engine.dispose()

    res = client.post(
        f"/api/proofs/{proof_id}/lines", json={"statement": {"ref": existing}}
    )

    assert res.status_code == 422, res.text
    assert "no longer has" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Removing a line: the inverse of /lines, and the same renumbering backwards
# ---------------------------------------------------------------------------


_THREE = "x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]"


def _three_line_proof(client: TestClient, db_path, owner: str) -> tuple[str, str]:
    system_id = _seed_system(db_path, owner)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": _THREE},
    ).json()
    assert client.post(f"/api/proofs/{created['id']}/verify").json()["success"] is True
    return system_id, created["id"]


def test_removing_a_line_moves_the_citations_below_it_up(client, db):
    # The mirror of inserting: everything below closes up by one, and a citation
    # that named one of those lines has to follow it or it silently names another.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _three_line_proof(client, db, owner)
    # A fourth line nothing cites, above the MP — so removing it shifts the MP's
    # own number and leaves its premises where they were.
    client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            },
            "before": 3,
            "apply": True,
        },
    )
    assert client.get(f"/api/proofs/{proof_id}").json()["source"].splitlines()[3] == (
        "x = y [MP, 1, 2]"
    )

    body = client.post(
        f"/api/proofs/{proof_id}/lines/remove", json={"line": 3, "apply": True}
    ).json()

    assert body["line"] == 3
    assert body["removed"] == "y ∈ x [?]"
    assert body["renumbered"] == [3]
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == _THREE
    assert body["valid"] is True
    assert body["holes"] == []


def test_removing_a_cited_line_is_refused_and_names_the_dependents(client, db):
    # There is no answer to give the lines that cited it — unlike an insertion,
    # which can always be undone by not making it. Naming them is more use than a
    # broken proof.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _three_line_proof(client, db, owner)

    res = client.post(
        f"/api/proofs/{proof_id}/lines/remove", json={"line": 1, "apply": True}
    )

    assert res.status_code == 409, res.text
    assert "cited by 3" in res.json()["detail"]
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == _THREE


def test_removing_a_line_is_a_dry_run_by_default(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _three_line_proof(client, db, owner)

    body = client.post(f"/api/proofs/{proof_id}/lines/remove", json={"line": 3}).json()

    assert body["applied"] is False
    assert body["removed"] == "x = y [MP, 1, 2]"
    assert body["valid"] is None
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == _THREE


def test_removing_a_line_is_owner_only(client, db):
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": _THREE},
    ).json()
    proof_id = created["id"]
    assert client.patch(
        f"/api/proofs/{proof_id}", json={"published": True}
    ).status_code == 200
    _register_login(client, "grace@example.com")

    # Readable as a dry run, like the other two proposals; owner-only to apply.
    assert client.post(
        f"/api/proofs/{proof_id}/lines/remove", json={"line": 3}
    ).status_code == 200
    assert client.post(
        f"/api/proofs/{proof_id}/lines/remove", json={"line": 3, "apply": True}
    ).status_code == 403


def test_removing_a_line_a_proof_does_not_have_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _three_line_proof(client, db, owner)

    res = client.post(f"/api/proofs/{proof_id}/lines/remove", json={"line": 9})
    assert res.status_code == 409, res.text
    assert "no line 9" in res.json()["detail"]


def test_a_line_added_and_removed_leaves_the_proof_as_it_was(client, db):
    # The round trip the loop actually needs: park a step, decide against it, put
    # the proof back. Byte-identical, not merely equivalent.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _three_line_proof(client, db, owner)

    added = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {
                "constructor": "membership",
                "slots": {
                    "s": {"constructor": "variable", "literal": "y"},
                    "t": {"constructor": "variable", "literal": "x"},
                },
            },
            "before": 2,
            "apply": True,
        },
    ).json()
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] != _THREE

    client.post(
        f"/api/proofs/{proof_id}/lines/remove",
        json={"line": added["line"], "apply": True},
    )

    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == _THREE


def test_a_failing_line_that_cites_the_removed_one_still_blocks_it(client, db):
    """The guard reads the citation, not the justification edges.

    An edge is written only where the rule *applied*, so a line that cites this
    one and does not currently check has none. Reading edges let such a line sail
    past and had its citation silently retargeted by the renumbering — `[MP, 1, 2]`
    came back as `[MP, 1, 1]`, naming a different premise. Nothing downstream
    catches that: `_broken_by_removal` only looks at lines that were valid before.
    """
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    # The MP line does not follow — `x = z` is not the consequent — so it stores
    # no antecedent edges, though its citation plainly names lines 1 and 2.
    source = "x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = z [MP, 1, 2]"
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": source},
    ).json()
    proof_id = created["id"]
    assert client.post(f"/api/proofs/{proof_id}/verify").json()["success"] is False

    res = client.post(
        f"/api/proofs/{proof_id}/lines/remove", json={"line": 1, "apply": True}
    )

    assert res.status_code == 409, res.text
    assert "cited by 3" in res.json()["detail"]
    assert client.get(f"/api/proofs/{proof_id}").json()["source"] == source


def test_a_dotted_lemma_citation_does_not_count_as_naming_a_line(client, db):
    # `[MP, A.2]`'s `2` is a line of *another* proof, which `renumber` leaves
    # alone — so the guard must not read it as naming line 2 here either.
    assert proofs_router._cites("MP, A.2", 2) is False
    assert proofs_router._cites("MP, 1, 2", 2) is True
    assert proofs_router._cites("HYP", 2) is False
    assert proofs_router._cites(None, 2) is False


def test_the_removed_line_comes_back_exactly_as_it_stood(client, db):
    # `display` is stored stripped and `indent` as a count of columns, so putting
    # the two back together turns a tab into spaces and drops trailing space. The
    # contract is that a caller can restore what was here — a re-spelling is not
    # that.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    odd = "x ∈ y [HYP]\n\t(x ∈ y → x = y) [HYP]  "
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": odd},
    ).json()
    proof_id = created["id"]
    assert client.post(f"/api/proofs/{proof_id}/verify").json()["success"] is True

    body = client.post(f"/api/proofs/{proof_id}/lines/remove", json={"line": 2}).json()

    assert body["removed"] == odd.split("\n")[1]


# ---------------------------------------------------------------------------
# Citation search (GET /proofs/{id}/lines/{n}/citations)
#
# The move the loop was missing: `/verify` says a line is a hole and `/cite` says
# whether a *named* justification works, and between them sat the question
# neither answered — which justification to name.
# ---------------------------------------------------------------------------


def _citations(client: TestClient, proof_id: str, number: int, **params) -> dict:
    res = client.get(f"/api/proofs/{proof_id}/lines/{number}/citations", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_hole_is_told_what_could_justify_it(client, db):
    # The whole point. Line 3 is stated and unproved; MP justifies it from the two
    # lines above, and nothing before this would tell a caller so.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    body = _citations(client, proof_id, 3)
    first = body["suggestions"][0]

    assert (first["rule"], first["antecedents"]) == ("MP", [1, 2])
    assert first["source"] == "rule"
    assert first["citation"] == "MP, 1, 2"


def test_a_rule_that_justifies_anything_is_reported_but_ranked_last(client, db):
    # `HYP` concludes a bare metavariable and cites nothing, so it applies to
    # every line in the system. That is a true answer and an uninformative one:
    # dropping it would hide a move an author sometimes means to make, and
    # ranking it on premise count alone would put it ahead of every real
    # justification, since it needs none.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    suggestions = _citations(client, proof_id, 3)["suggestions"]

    assert [s["rule"] for s in suggestions] == ["MP", "HYP"]
    assert [s["assumption"] for s in suggestions] == [False, True]


def test_a_suggestion_is_a_citation_proposal_that_applies(client, db):
    # The loop closing, end to end: what the search returns is what `/cite` takes,
    # and it is accepted — so a caller acts on a suggestion rather than trying it.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    suggestion = _citations(client, proof_id, 3)["suggestions"][0]
    applied = client.post(
        f"/api/proofs/{proof_id}/cite",
        json={
            "line": 3,
            "rule": suggestion["rule"],
            "antecedents": suggestion["antecedents"],
            "apply": True,
        },
    ).json()

    assert applied["accepted"] is True
    assert applied["holes"] == [1, 2]


def test_searching_does_not_fill_the_hole(client, db):
    # Asking what could justify a line must not justify it. A search runs the
    # same check a verify does, and the probe that finds an answer is the one
    # that would otherwise record it.
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    _citations(client, proof_id, 3)

    detail = client.get(f"/api/proofs/{proof_id}").json()
    assert detail["source"] == _HOLED
    assert _structure(client, proof_id)["lines"][2]["failure"]["code"] == "hole"


def test_a_line_nothing_can_justify_gets_an_empty_list(client, db):
    # Not an error: "there is no move from here" is an answer a loop acts on, and
    # the accounting says how much was looked at to reach it.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner)
    proof_id = _create_proof(
        client, system_id, "P", source="x ∈ y [?]\nx = y [?]"
    )
    client.post(f"/api/proofs/{proof_id}/verify")

    body = _citations(client, proof_id, 2)

    # Nothing derives `x = y` here; only the rule that would let an author assume
    # it, which is reported for what it is.
    assert [(s["rule"], s["assumption"]) for s in body["suggestions"]] == [
        ("HYP", True)
    ]
    assert body["rules_tried"] >= 2
    assert body["unindexed"] == 0


def test_the_search_is_readable_by_anyone_on_a_published_proof(client, db):
    # A dry run over someone else's published proof, exactly as `/cite`'s is: it
    # writes nothing, so there is nothing to own.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    proof_id = _create_proof(client, system_id, "P", source=VALID_PROOF)
    assert client.patch(
        f"/api/proofs/{proof_id}", json={"published": True}
    ).status_code == 200
    _logout(client)

    res = client.get(f"/api/proofs/{proof_id}/lines/1/citations")

    assert res.status_code == 200, res.text


def test_a_line_the_proof_does_not_have_is_404(client, db):
    owner = _register_login(client, "ada@example.com")
    _system_id, proof_id = _holed_proof(client, db, owner)

    res = client.get(f"/api/proofs/{proof_id}/lines/99/citations")

    assert res.status_code == 404


def test_a_scope_opener_has_no_citation_to_search_for(client, db):
    # A scope opener is granted rather than proved, so a justification for it
    # would be a justification of nothing — the same refusal `/cite` makes.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, spec=scoped_zfc_spec())
    proof_id = _create_proof(client, system_id, "P", source=_SUBPROOF_SRC)
    client.post(f"/api/proofs/{proof_id}/verify")

    res = client.get(f"/api/proofs/{proof_id}/lines/1/citations")

    assert res.status_code == 422
    assert "subproof" in res.json()["detail"]


def test_a_discharge_is_suggested_for_the_line_that_closes_a_subproof(client, db):
    # The rules a search would otherwise be blind to: in a natural-deduction
    # system every step that closes a subproof is a discharge, and a discharge
    # cites the subproof's *opener* rather than antecedents.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, spec=scoped_zfc_spec())
    proof_id = _create_proof(
        client,
        system_id,
        "P",
        source="assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → x ∈ y) [?]",
    )
    client.post(f"/api/proofs/{proof_id}/verify")

    body = _citations(client, proof_id, 3)

    assert ("CP", [1], True) in [
        (s["rule"], s["antecedents"], s["discharge"]) for s in body["suggestions"]
    ]


def test_a_promoted_theorem_is_found_by_the_shape_of_its_conclusion(client, db):
    # The library half, and the reason the prefilter exists: the theorem is not
    # one of the system's rules, and it is found because its conclusion's root
    # production is the goal's.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    lemma = _create_proof(client, system_id, "Lemma", source=_LEMMA_SRC)
    assert client.patch(
        f"/api/proofs/{lemma}", json={"published": True}
    ).status_code == 200
    assert client.post(
        f"/api/proofs/{lemma}/promote", json={"label": "lem"}
    ).status_code in (200, 201)

    user = _create_proof(client, system_id, "User", source="(x ∈ y → x = y) [?]")
    client.post(f"/api/proofs/{user}/verify")

    body = _citations(client, user, 1)

    assert ("lem", "theorem") in [
        (s["rule"], s["source"]) for s in body["suggestions"]
    ]
    assert body["candidates_tried"] >= 1


def test_the_library_can_be_left_out_of_the_search(client, db):
    # `candidates=0` searches the system's own rules only — the cheap question,
    # for a caller that does not want to pay for the library.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    lemma = _create_proof(client, system_id, "Lemma", source=_LEMMA_SRC)
    client.patch(f"/api/proofs/{lemma}", json={"published": True})
    client.post(f"/api/proofs/{lemma}/promote", json={"label": "lem"})
    user = _create_proof(client, system_id, "User", source="(x ∈ y → x = y) [?]")
    client.post(f"/api/proofs/{user}/verify")

    body = _citations(client, user, 1, candidates=0)

    assert "lem" not in [s["rule"] for s in body["suggestions"]]
    assert body["candidates_tried"] == 0


# ---------------------------------------------------------------------------
# Library retrieval (GET /formal-systems/{id}/theorems/matching)
#
# The filter, served against the system because that is what a library belongs
# to. Unifying the survivors is the proof-scoped search's job; this narrows.
# ---------------------------------------------------------------------------


def _library_system(client: TestClient, db_path, owner: str) -> str:
    """A published system with one promoted theorem concluding an implication."""
    system_id = _seed_system(db_path, owner, published=True)
    lemma = _create_proof(client, system_id, "Lemma", source=_LEMMA_SRC)
    assert client.patch(
        f"/api/proofs/{lemma}", json={"published": True}
    ).status_code == 200
    assert client.post(
        f"/api/proofs/{lemma}/promote", json={"label": "lem"}
    ).status_code in (200, 201)
    return system_id


def test_a_goal_finds_the_theorems_shaped_like_its_conclusion(client, db):
    # "Here are the theorems that could conclude that" — the question a caller on
    # a 47,589-entry library had no way to ask.
    owner = _register_login(client, "ada@example.com")
    system_id = _library_system(client, db, owner)
    goal = _create_proof(client, system_id, "Goal", source="(x ∈ y → x = y) [HYP]")
    client.post(f"/api/proofs/{goal}/verify")
    term_id = _structure(client, goal)["lines"][0]["term"]["id"]

    body = client.get(
        f"/api/formal-systems/{system_id}/theorems/matching", params={"term": term_id}
    ).json()

    assert body["constructor"] == "implication"
    assert [c["label"] for c in body["candidates"]] == ["lem"]
    assert body["candidates"][0]["premise_count"] == 0
    assert body["unindexed"] == 0

    # The candidate is point-at-able: its statement_term_id is a real handle that
    # `GET .../terms/{id}` resolves to the conclusion's graph — projection and
    # identity together, not a string a caller must reparse.
    node = client.get(
        f"/api/formal-systems/{system_id}/terms/{body['candidates'][0]['statement_term_id']}"
    )
    assert node.status_code == 200, node.text
    assert node.json()["root"] == body["candidates"][0]["statement_term_id"]


def test_a_goal_of_another_shape_is_not_offered_the_library(client, db):
    # The filter doing its work: the library's implication is not a candidate for
    # a membership goal, and on a real corpus that is most of it removed.
    owner = _register_login(client, "ada@example.com")
    system_id = _library_system(client, db, owner)
    goal = _create_proof(client, system_id, "Goal", source="x ∈ y [HYP]")
    client.post(f"/api/proofs/{goal}/verify")
    term_id = _structure(client, goal)["lines"][0]["term"]["id"]

    body = client.get(
        f"/api/formal-systems/{system_id}/theorems/matching", params={"term": term_id}
    ).json()

    assert body["candidates"] == []
    assert body["matched"] == 0


def test_an_already_proved_statement_comes_back_exact(client, db):
    # `alpha_digest` covering the exact case for free: the goal *is* the theorem's
    # statement, so citing it needs no instantiation at all.
    owner = _register_login(client, "ada@example.com")
    system_id = _library_system(client, db, owner)
    goal = _create_proof(client, system_id, "Goal", source=_LEMMA_SRC)
    client.post(f"/api/proofs/{goal}/verify")
    term_id = _structure(client, goal)["lines"][0]["term"]["id"]

    body = client.get(
        f"/api/formal-systems/{system_id}/theorems/matching", params={"term": term_id}
    ).json()

    assert [(c["label"], c["exact"]) for c in body["candidates"]] == [("lem", True)]


def test_a_term_from_another_system_is_404(client, db):
    # Interning is per system, so an id from elsewhere names a term built over
    # another grammar — a mistake worth hearing about, not an empty result.
    owner = _register_login(client, "ada@example.com")
    system_id = _library_system(client, db, owner)
    other_system, other_term = _stored_term(client, db, owner)
    assert other_system != system_id

    res = client.get(
        f"/api/formal-systems/{system_id}/theorems/matching",
        params={"term": other_term},
    )

    assert res.status_code == 404


def test_the_limit_reports_what_it_hid(client, db):
    # A truncated list must not read as a complete one.
    owner = _register_login(client, "ada@example.com")
    system_id = _seed_system(db, owner, published=True)
    for n in range(3):
        lemma = _create_proof(client, system_id, f"L{n}", source=_LEMMA_SRC)
        client.patch(f"/api/proofs/{lemma}", json={"published": True})
        client.post(f"/api/proofs/{lemma}/promote", json={"label": f"lem{n}"})
    goal = _create_proof(client, system_id, "Goal", source="(x ∈ y → x = y) [HYP]")
    client.post(f"/api/proofs/{goal}/verify")
    term_id = _structure(client, goal)["lines"][0]["term"]["id"]

    body = client.get(
        f"/api/formal-systems/{system_id}/theorems/matching",
        params={"term": term_id, "limit": 2},
    ).json()

    assert len(body["candidates"]) == 2
    assert body["matched"] == 3
    assert body["truncated"] is True
