"""Owner-scoped CRUD endpoints for formal systems.

Runs the router end to end against a throwaway SQLite database (only the auth +
system-decomposition tables are created — the pgvector `theorems` table isn't
SQLite-creatable), with `get_session` pointed at it and the real fastapi-users
auth flow (register/login) driving owner scoping.
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
from sqlalchemy import NullPool, create_engine, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db import Base, FormalSystem, SideConditionRow, spec_to_system
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
    regex_prod,
    statement_line,
    variable_prod,
)
from website.logical.declarative import LineSpec, SystemSpec

# Auth tables + the system-decomposition tables (all SQLite-creatable).
_TABLES = [
    m.__table__
    for m in (
        User, OAuthAccount, FormalSystem, BracketRow, SymbolRow,
        ProductionBindingRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow,
        SideConditionRow,
    )
]


def zfc_spec() -> SystemSpec:
    # A small but genuine ZFC fragment used to give the read/validate/source
    # paths real content, assembled directly as a SystemSpec.
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


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "systems.db"

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine, tables=_TABLES)
    sync_engine.dispose()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)

    # SQLite ignores ON DELETE CASCADE unless foreign keys are enabled per
    # connection; turn it on so a system delete cascades to its child rows as it
    # does on Postgres.
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


def _seed_spec(db_path, owner_id: str, spec: SystemSpec, published: bool = False) -> str:
    # Insert a system assembled as a SystemSpec directly (child CRUD is a later
    # phase), owned by the given user, so the read/validate/source paths have
    # real content. `published=True` sets published_at directly, which is the
    # only way to reach a broken-but-published state now that the publish
    # endpoint gates on the system compiling.
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            system = spec_to_system(spec)
            system.owner_id = uuid.UUID(owner_id)
            if published:
                system.published_at = datetime.now(timezone.utc)
            session.add(system)
            session.commit()
            return str(system.id)
    finally:
        engine.dispose()


def _seed_zfc(db_path, owner_id: str) -> str:
    return _seed_spec(db_path, owner_id, zfc_spec())


# A system that stores fine but cannot be lowered: the line shape has no
# `<placeholder>` naming a grammar sort, so `lower()` raises DeclarativeError.
def broken_spec() -> SystemSpec:
    return SystemSpec(
        name="Broken",
        productions=[regex_prod("formula", "atom", "[a-z]+")],
        line=LineSpec(name="statement", shape="assertion", parts=[],
                      logical_sort="formula"),
    )


# ---------------------------------------------------------------------------
# Auth is required
# ---------------------------------------------------------------------------


def test_endpoints_require_authentication(client):
    assert client.get("/formal-systems").status_code == 401
    assert client.post("/formal-systems", json={"name": "X"}).status_code == 401


def test_spa_guard_covers_the_systems_collection_path():
    # The router mounts as a nested router (not flat APIRoutes), so its
    # collection path must be fed into the SPA fallback's API-path guard.
    from app.main import _mounted_api_paths

    assert "formal-systems" in _mounted_api_paths()


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------


def test_create_returns_detail_with_slug_and_empty_children(client):
    _register_login(client, "ada@example.com")
    response = client.post("/formal-systems", json={"name": "My Logic", "description": "hi"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "My Logic"
    assert body["slug"] == "my-logic"
    assert body["description"] == "hi"
    assert body["productions"] == [] and body["rules"] == []
    assert uuid.UUID(body["id"])  # a real UUID


def test_get_returns_created_system(client):
    _register_login(client, "ada@example.com")
    created = client.post("/formal-systems", json={"name": "Peano"}).json()
    fetched = client.get(f"/formal-systems/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_list_returns_only_summaries_in_creation_order(client):
    _register_login(client, "ada@example.com")
    client.post("/formal-systems", json={"name": "First"})
    client.post("/formal-systems", json={"name": "Second"})
    listed = client.get("/formal-systems").json()
    assert listed["total"] == 2
    assert [s["name"] for s in listed["items"]] == ["First", "Second"]
    assert "productions" not in listed["items"][0]  # summary, not detail


def test_list_paginates_with_limit_and_offset(client):
    _register_login(client, "ada@example.com")
    for i in range(5):
        client.post("/formal-systems", json={"name": f"S{i}"})

    first = client.get("/formal-systems", params={"limit": 2, "offset": 0}).json()
    assert first["total"] == 5  # full count, not just the page
    assert [s["name"] for s in first["items"]] == ["S0", "S1"]

    second = client.get("/formal-systems", params={"limit": 2, "offset": 2}).json()
    assert [s["name"] for s in second["items"]] == ["S2", "S3"]

    last = client.get("/formal-systems", params={"limit": 2, "offset": 4}).json()
    assert [s["name"] for s in last["items"]] == ["S4"]


def test_list_rejects_an_oversized_page(client):
    _register_login(client, "ada@example.com")
    assert client.get("/formal-systems", params={"limit": 101}).status_code == 422
    assert client.get("/formal-systems", params={"limit": 0}).status_code == 422
    assert client.get("/formal-systems", params={"offset": -1}).status_code == 422


def test_list_searches_name_and_description_case_insensitively(client):
    _register_login(client, "ada@example.com")
    client.post("/formal-systems", json={"name": "Alpha"})
    client.post("/formal-systems", json={"name": "Beta", "description": "an alphabet soup"})
    client.post("/formal-systems", json={"name": "Gamma"})

    hits = client.get("/formal-systems", params={"search": "alph"}).json()
    assert hits["total"] == 2  # count reflects the filter, for the page controls
    assert {s["name"] for s in hits["items"]} == {"Alpha", "Beta"}


def test_list_sorts_by_a_requested_column(client):
    _register_login(client, "ada@example.com")
    for name in ("Banana", "Apple", "Cherry"):
        client.post("/formal-systems", json={"name": name})

    asc = client.get("/formal-systems", params={"sort": "name"}).json()
    assert [s["name"] for s in asc["items"]] == ["Apple", "Banana", "Cherry"]

    desc = client.get("/formal-systems", params={"sort": "name", "desc": True}).json()
    assert [s["name"] for s in desc["items"]] == ["Cherry", "Banana", "Apple"]

    # An unknown sort key falls back to the default (creation) order.
    fallback = client.get("/formal-systems", params={"sort": "bogus"}).json()
    assert [s["name"] for s in fallback["items"]] == ["Banana", "Apple", "Cherry"]


def test_duplicate_name_gets_a_distinct_slug(client):
    _register_login(client, "ada@example.com")
    first = client.post("/formal-systems", json={"name": "Logic"}).json()
    second = client.post("/formal-systems", json={"name": "Logic"}).json()
    assert first["slug"] == "logic"
    assert second["slug"] == "logic-2"


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def test_patch_updates_fields_and_reslugs_on_rename(client):
    _register_login(client, "ada@example.com")
    system = client.post("/formal-systems", json={"name": "Old"}).json()
    response = client.patch(
        f"/formal-systems/{system['id']}", json={"name": "New Name", "published": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["slug"] == "new-name"
    assert body["published_at"] is not None

    # Unpublish clears the timestamp.
    cleared = client.patch(f"/formal-systems/{system['id']}", json={"published": False})
    assert cleared.json()["published_at"] is None


def test_delete_removes_the_system(client):
    _register_login(client, "ada@example.com")
    system = client.post("/formal-systems", json={"name": "Doomed"}).json()
    assert client.delete(f"/formal-systems/{system['id']}").status_code == 204
    assert client.get(f"/formal-systems/{system['id']}").status_code == 404


def _count(db_path, model) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as session:
            return session.scalar(select(func.count()).select_from(model)) or 0
    finally:
        engine.dispose()


def test_delete_cascades_to_symbols_and_bindings(client, db):
    # Deleting a populated system must clear every child row through its
    # cascading FKs — and must not choke on the self-referential `symbols` table
    # (a production points at its union via member_of_union_id) or the symbol_id
    # binding FKs. So no error on delete, and no orphans left behind.
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)

    # Sanity: the seed populates the tables whose cascade we're checking,
    # including the line type and its parts (LineRow / LinePartRow).
    assert _count(db, SymbolRow) > 0  # sorts + productions in one table
    assert _count(db, ProductionBindingRow) > 0
    assert _count(db, DefinitionRow) > 0
    assert _count(db, LineRow) > 0 and _count(db, LinePartRow) > 0

    assert client.delete(f"/formal-systems/{system_id}").status_code == 204

    for model in (
        SymbolRow, ProductionBindingRow, DefinitionRow, DefinitionBindingRow,
        AxiomRow, AxiomBindingRow, RuleRow, RuleBindingRow, RuleAntecedentRow,
        LineRow, LinePartRow, BracketRow,
    ):
        assert _count(db, model) == 0, model.__name__


# ---------------------------------------------------------------------------
# Inheritance reference validation
# ---------------------------------------------------------------------------


def test_inherits_from_must_be_an_owned_system(client):
    _register_login(client, "ada@example.com")
    base = client.post("/formal-systems", json={"name": "Base"}).json()

    ok = client.post("/formal-systems", json={"name": "Derived", "inherits_from_id": base["id"]})
    assert ok.status_code == 201
    assert ok.json()["inherits_from_id"] == base["id"]

    bad = client.post(
        "/formal-systems", json={"name": "Bad", "inherits_from_id": str(uuid.uuid4())}
    )
    assert bad.status_code == 400


# ---------------------------------------------------------------------------
# Owner scoping
# ---------------------------------------------------------------------------


def test_a_user_cannot_see_another_users_system(client):
    owner_id = _register_login(client, "owner@example.com")
    system = client.post("/formal-systems", json={"name": "Private"}).json()
    client.post("/auth/logout")

    _register_login(client, "intruder@example.com")
    assert owner_id  # sanity
    assert client.get(f"/formal-systems/{system['id']}").status_code == 404
    assert client.delete(f"/formal-systems/{system['id']}").status_code == 404
    assert client.get("/formal-systems").json()["items"] == []


# ---------------------------------------------------------------------------
# Validate + source, against seeded content
# ---------------------------------------------------------------------------


def test_validate_reports_a_compilable_system(client, db):
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)

    response = client.post(f"/formal-systems/{system_id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["system_name"] == "ZFC"
    assert body["inference_rule_count"] == 2  # HYP, MP (EXT is an axiom line type)
    assert body["line_type_count"] >= 1


def test_source_returns_lowered_edi(client, db):
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)

    response = client.get(f"/formal-systems/{system_id}/source")
    assert response.status_code == 200
    source = response.json()["source"]
    assert source.startswith("FormalSystem ZFC:")
    assert "InferenceRule modus_ponens:" in source
    assert "Define x ⊆ y as" in source


def test_source_on_a_broken_published_system_is_422_not_500(client, db):
    # Defense in depth for a broken-but-published system (published before the
    # compile gate existed, or broken by a later edit): published systems are
    # world-readable and `lower()` raises on this one, so an unguarded /source
    # would be an unauthenticated 500. It must be a 422 with the error text.
    # Seed it published directly — the publish endpoint now refuses a broken one.
    owner_id = _register_login(client, "owner@example.com")
    system_id = _seed_spec(db, owner_id, broken_spec(), published=True)
    client.post("/auth/logout")

    response = client.get(f"/formal-systems/{system_id}/source")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail  # error strings, not an HTML 500


def test_validate_is_owner_scoped(client, db):
    owner_id = _register_login(client, "owner@example.com")
    system_id = _seed_zfc(db, owner_id)
    client.post("/auth/logout")

    _register_login(client, "intruder@example.com")
    assert client.post(f"/formal-systems/{system_id}/validate").status_code == 404


# ---------------------------------------------------------------------------
# Verify a proof against a stored system (assembled server-side from rows)
# ---------------------------------------------------------------------------


def test_verify_valid_proof_against_owned_system(client, db):
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)
    res = client.post(
        f"/formal-systems/{system_id}/verify", json={"proof_text": "x ∈ y [HYP]"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["proof"]["indicator"] == "ok"
    assert len(body["proof"]["lines"]) == 1


def test_verify_unparseable_line_is_reported_not_raised(client, db):
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)
    res = client.post(
        f"/formal-systems/{system_id}/verify", json={"proof_text": "HELLO 123"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert body["proof"]["lines"][0]["valid"] is False


def test_verify_on_a_non_compiling_system_is_400(client, db):
    # A stored system that cannot be lowered/compiled surfaces the errors as a
    # 400 the client renders verbatim, rather than a 500.
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_spec(db, owner_id, broken_spec())
    res = client.post(
        f"/formal-systems/{system_id}/verify", json={"proof_text": "anything"}
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert isinstance(detail, list) and detail


def test_verify_published_system_needs_no_auth(client, db):
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_spec(db, owner_id, zfc_spec(), published=True)
    client.post("/auth/logout")
    res = client.post(
        f"/formal-systems/{system_id}/verify", json={"proof_text": "x ∈ y [HYP]"}
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_verify_is_owner_scoped_for_drafts(client, db):
    owner_id = _register_login(client, "owner@example.com")
    system_id = _seed_zfc(db, owner_id)
    client.post("/auth/logout")

    _register_login(client, "intruder@example.com")
    assert owner_id  # sanity
    res = client.post(
        f"/formal-systems/{system_id}/verify", json={"proof_text": "x ∈ y [HYP]"}
    )
    assert res.status_code == 404


def test_verify_checker_exception_returns_structured_error(client, db, monkeypatch):
    # If the checker raises against an otherwise-valid stored system (e.g. a line
    # type whose context edit targets a missing key), the endpoint returns a
    # structured error, not a 500.
    import app.routers.systems as systems_router

    class ExplodingSystem:
        def parse(self, text):
            raise Exception("Can't find 'bad' in proof context.")

    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_zfc(db, owner_id)
    monkeypatch.setattr(
        systems_router, "build_spec", lambda spec: {"system": ExplodingSystem()}
    )
    res = client.post(f"/formal-systems/{system_id}/verify", json={"proof_text": "x"})
    assert res.status_code == 200
    assert res.json() == {
        "success": False,
        "errors": ["Can't find 'bad' in proof context."],
        "proof": None,
    }


# ---------------------------------------------------------------------------
# Public visibility: the shared master list + published-or-owner reads
# ---------------------------------------------------------------------------


def _publish(client: TestClient, system_id: str) -> None:
    assert (
        client.patch(f"/formal-systems/{system_id}", json={"published": True}).status_code == 200
    )


def test_public_list_needs_no_auth_and_shows_only_published(client):
    _register_login(client, "ada@example.com")
    draft = client.post("/formal-systems", json={"name": "Draft"}).json()
    published = client.post("/formal-systems", json={"name": "Published"}).json()
    _publish(client, published["id"])
    client.post("/auth/logout")

    listed = client.get("/formal-systems/public")
    assert listed.status_code == 200  # no auth required
    ids = [s["id"] for s in listed.json()["items"]]
    assert published["id"] in ids
    assert draft["id"] not in ids  # drafts are excluded


def test_public_list_names_the_owner_without_leaking_email(client):
    user_id = _register_login(client, "ada@example.com")
    assert client.patch("/users/me", json={"display_name": "Ada L."}).status_code == 200
    system = client.post("/formal-systems", json={"name": "Pub"}).json()
    _publish(client, system["id"])
    client.post("/auth/logout")

    owner = client.get("/formal-systems/public").json()["items"][0]["owner"]
    assert owner["id"] == user_id
    assert owner["display_name"] == "Ada L."
    assert "email" not in owner


def test_non_owner_cannot_publish_or_unpublish(client):
    # Publish/unpublish is the one write that flips a system's *global*
    # visibility, so owner-scoping it is the highest-value guarantee. A non-owner
    # gets a 404 (ownership stays hidden), and neither system's visibility moves.
    _register_login(client, "owner@example.com")
    draft = client.post("/formal-systems", json={"name": "Draft"}).json()
    published = client.post("/formal-systems", json={"name": "Published"}).json()
    _publish(client, published["id"])
    client.post("/auth/logout")

    _register_login(client, "intruder@example.com")
    assert (
        client.patch(f"/formal-systems/{draft['id']}", json={"published": True}).status_code == 404
    )
    assert (
        client.patch(f"/formal-systems/{published['id']}", json={"published": False}).status_code
        == 404
    )
    client.post("/auth/logout")

    public_ids = [s["id"] for s in client.get("/formal-systems/public").json()["items"]]
    assert draft["id"] not in public_ids  # the intruder's publish did nothing
    assert published["id"] in public_ids  # the intruder's unpublish did nothing


def test_cannot_publish_a_non_compiling_system(client, db):
    # Publishing makes a system world-readable; a broken one would then break
    # /source (and any future public consumer) for anonymous viewers. Gate it.
    owner_id = _register_login(client, "ada@example.com")
    system_id = _seed_spec(db, owner_id, broken_spec())

    response = client.patch(f"/formal-systems/{system_id}", json={"published": True})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)  # the compile errors

    # It stayed a draft: absent from the public list.
    client.post("/auth/logout")
    assert system_id not in [
        s["id"] for s in client.get("/formal-systems/public").json()["items"]
    ]


def test_cannot_publish_a_system_inheriting_from_an_unpublished_parent(client):
    # A published child exposes inherits_from_id, and GET /{parent} 404s for
    # anonymous viewers when the parent is still a private draft — so block the
    # publish until the parent is public.
    _register_login(client, "ada@example.com")
    parent = client.post("/formal-systems", json={"name": "Parent"}).json()
    child = client.post(
        "/formal-systems", json={"name": "Child", "inherits_from_id": parent["id"]}
    ).json()

    blocked = client.patch(f"/formal-systems/{child['id']}", json={"published": True})
    assert blocked.status_code == 400

    # Publishing the parent first unblocks the child.
    assert client.patch(f"/formal-systems/{parent['id']}", json={"published": True}).status_code == 200
    assert client.patch(f"/formal-systems/{child['id']}", json={"published": True}).status_code == 200


def test_cannot_unpublish_a_parent_with_published_children(client):
    # The mirror of the publish gate: unpublishing the parent would strand the
    # published child with an inherits_from_id that GET /{parent} now 404s on.
    _register_login(client, "ada@example.com")
    parent = client.post("/formal-systems", json={"name": "Parent"}).json()
    child = client.post(
        "/formal-systems", json={"name": "Child", "inherits_from_id": parent["id"]}
    ).json()
    _publish(client, parent["id"])
    _publish(client, child["id"])

    # The parent can't be pulled out from under a published child.
    blocked = client.patch(f"/formal-systems/{parent['id']}", json={"published": False})
    assert blocked.status_code == 400

    # Unpublishing the child first frees the parent.
    assert client.patch(f"/formal-systems/{child['id']}", json={"published": False}).status_code == 200
    assert client.patch(f"/formal-systems/{parent['id']}", json={"published": False}).status_code == 200


def test_published_system_is_readable_by_anyone(client, db):
    owner_id = _register_login(client, "owner@example.com")
    system_id = _seed_zfc(db, owner_id)
    _publish(client, system_id)
    client.post("/auth/logout")

    # Signed out: detail, validate and source are all served.
    assert client.get(f"/formal-systems/{system_id}").status_code == 200
    assert client.post(f"/formal-systems/{system_id}/validate").json()["success"] is True
    assert client.get(f"/formal-systems/{system_id}/source").status_code == 200

    # A different signed-in user can read it too, but it is not one of *their*
    # systems (the owner-scoped list stays empty for them).
    _register_login(client, "reader@example.com")
    assert client.get(f"/formal-systems/{system_id}").status_code == 200
    assert client.get("/formal-systems").json()["items"] == []


def test_unpublishing_removes_from_public_and_hides_from_others(client, db):
    owner_id = _register_login(client, "owner@example.com")
    system_id = _seed_zfc(db, owner_id)
    _publish(client, system_id)
    assert any(
        s["id"] == system_id for s in client.get("/formal-systems/public").json()["items"]
    )

    assert (
        client.patch(f"/formal-systems/{system_id}", json={"published": False}).status_code == 200
    )
    assert client.get("/formal-systems/public").json()["items"] == []

    # Back to a draft: invisible to a signed-out visitor again.
    client.post("/auth/logout")
    assert client.get(f"/formal-systems/{system_id}").status_code == 404
