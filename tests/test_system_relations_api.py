"""Writing an edge through the API rather than into its rows.

R4's third piece. `tests/test_system_relations.py` covers what an edge
*resolves*, against edges written straight to the tables; this covers the route
that writes them — what it refuses, and what a write has to reach afterwards.

The division is deliberate. A resolution test wants an edge in whatever state it
is describing, including states the route refuses to write; a route test wants
the states an author can actually reach. Written as accepted/rejected pairs for
§8.0's reason, and every refusal is asserted with its message, since three of
them are 422s that would otherwise be indistinguishable.
"""

from __future__ import annotations

import uuid
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
from app.db import PromotedTheoremRow
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.layered_systems import (
    PC_RENAME,
    narrowed_propositional_calculus_spec,
    propositional_calculus_spec,
    renamed_propositional_calculus_spec,
)
from tests.test_cross_system_citation import IDENTITY, promote_into, verify_proof
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed
from tests.test_systems_api import _register_login, broken_spec


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "relations-api")
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


def relate(client, target: str, source: str, **body) -> tuple[int, dict]:
    response = client.post(
        f"/api/formal-systems/{target}/relations",
        json={"source_system_id": source, **body},
    )
    return response.status_code, (response.json() if response.content else {})


def rename(mapping: dict[str, dict[str, str]]) -> dict:
    """`PC_RENAME`'s two dicts as the route's list-of-pairs shape."""
    return {
        "sorts": [{"source": s, "target": t} for s, t in mapping["sorts"].items()],
        "symbols": [{"source": s, "target": t} for s, t in mapping["symbols"].items()],
    }


def siblings(db_path, client, email: str) -> tuple[str, str]:
    owner = _register_login(client, email)
    return (
        seed(db_path, propositional_calculus_spec("Left"), owner, None),
        seed(db_path, propositional_calculus_spec("Right"), owner, None),
    )


# ---------------------------------------------------------------------------
# What the route writes
# ---------------------------------------------------------------------------


def test_a_written_edge_is_what_makes_a_citation_resolve(db, client):
    # The headline: an edge written through the route does what an edge written
    # into the rows does. Paired with the same proof before it exists, so the
    # test says the edge is what changed and not the seeding.
    left, right = siblings(db, client, "written@example.com")
    promote_into(db, left, IDENTITY)

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False

    status_code, edge = relate(client, right, left, status="discharged")
    assert status_code == 201, edge
    assert edge["resolves"] is True

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True


def test_a_draft_edge_is_written_and_resolves_nothing(db, client):
    # The state an author works in: an edge exists, is listed, and transfers
    # nothing until it is discharged. `resolves` reports that rather than the
    # route refusing to write it — a half-built edge is a real thing to have.
    left, right = siblings(db, client, "draft-write@example.com")
    promote_into(db, left, IDENTITY)

    status_code, edge = relate(
        client, right, left, obligations=[{"source_label": "MP"}]
    )
    assert status_code == 201, edge
    assert edge["resolves"] is False
    assert edge["outstanding"] == ["MP"]
    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False

    listed = client.get(f"/api/formal-systems/{right}/relations").json()
    assert [entry["id"] for entry in listed] == [edge["id"]]
    assert listed[0]["source_system_name"] == "Left"


def test_discharging_through_the_route_makes_the_same_proof_stand(db, client):
    # The PATCH, and the pairing that says what carried the weight: the same
    # proof, re-run, going from failing to standing because the edge was
    # completed — not because anything about the proof changed.
    left, right = siblings(db, client, "discharge@example.com")
    promote_into(db, left, IDENTITY)
    _, edge = relate(
        client, right, left, status="discharged",
        obligations=[{"source_label": "MP"}],
    )
    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False

    patched = client.patch(
        f"/api/formal-systems/{right}/relations/{edge['id']}",
        json={"obligations": [{
            "source_label": "MP",
            "discharged_by_primitive": "MP",
            "status": "discharged",
        }]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["resolves"] is True

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_a_narrowing_map_is_refused_at_the_write(db, client):
    # §9.17's escape, taken: the map's check runs where there is a request to
    # report it to, so an author gets `translation_errors`' own words instead of
    # a citation that mysteriously does not resolve.
    #
    # Paired with the map that checks out, onto a target whose sort *does* admit
    # the branch — the same map, the same source, one difference in the target.
    owner = _register_login(client, "narrow-write@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    wide = seed(db, renamed_propositional_calculus_spec("Wide"), owner, None)
    narrow = seed(db, narrowed_propositional_calculus_spec("Narrow"), owner, None)

    assert relate(client, wide, source, **rename(PC_RENAME))[0] == 201

    status_code, body = relate(client, narrow, source, **rename(PC_RENAME))
    assert status_code == 422
    assert "'conjunction'" in body["detail"] and "does not admit" in body["detail"]


def test_a_map_against_a_system_that_does_not_build_says_so(db, client):
    # A check that cannot be made is not a check that failed, and saying "the map
    # narrows" about a system with no grammar would name the wrong problem.
    owner = _register_login(client, "unbuildable@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    # A line type whose shape names no sort: stored happily, builds to errors,
    # which is the draft state the parts CRUD is deliberately tolerant of.
    broken = seed(db, broken_spec(), owner, None)

    status_code, body = relate(client, broken, source, **rename(PC_RENAME))
    assert status_code == 422
    assert "cannot be checked until both systems build" in body["detail"]


def test_a_system_cannot_be_related_to_itself(db, client):
    left, _right = siblings(db, client, "self@example.com")

    status_code, body = relate(client, left, left)
    assert status_code == 400
    assert "cannot be related to itself" in body["detail"]


def test_a_source_you_cannot_see_is_refused(db, client):
    # The visibility rule inheritance follows: owned, or published. A stranger's
    # draft is neither, and its id must not read as anything but absent.
    stranger = _register_login(client, "stranger@example.com")
    private = seed(db, propositional_calculus_spec("Private"), stranger, None,
                   published=False)
    mine = seed(db, propositional_calculus_spec("Mine"),
                _register_login(client, "mine@example.com"), None)

    status_code, body = relate(client, mine, private)
    assert status_code == 400
    assert "not a system you can relate to" in body["detail"]


def test_a_published_source_needs_no_ownership(db, client):
    # The other half, and the case the feature exists for: an imported corpus is
    # ownerless, so requiring ownership would lock everyone out of building on
    # one. Publication is what makes it relatable.
    stranger = _register_login(client, "publisher@example.com")
    public = seed(db, propositional_calculus_spec("Public"), stranger, None)
    mine = seed(db, propositional_calculus_spec("Mine"),
                _register_login(client, "borrower@example.com"), None)

    assert relate(client, mine, public)[0] == 201


def test_a_target_you_do_not_own_is_not_found(db, client):
    # 404 rather than 403, as everywhere else in this router: an id must not leak.
    stranger = _register_login(client, "owner@example.com")
    theirs = seed(db, propositional_calculus_spec("Theirs"), stranger, None)
    mine = seed(db, propositional_calculus_spec("Mine"),
                _register_login(client, "other@example.com"), None)

    assert relate(client, theirs, mine)[0] == 404
    assert client.get(f"/api/formal-systems/{theirs}/relations").status_code == 404


def test_two_edges_the_same_way_round_are_one(db, client):
    left, right = siblings(db, client, "duplicate@example.com")
    assert relate(client, right, left)[0] == 201

    status_code, body = relate(client, right, left)
    assert status_code == 409
    assert "already related" in body["detail"]

    # The other direction is a second edge, with its own obligations — which is
    # what the table's unique index says, and it is not a duplicate.
    assert relate(client, left, right)[0] == 201


def test_an_obligation_may_not_claim_two_discharges(db, client):
    left, right = siblings(db, client, "two-discharges@example.com")
    promote_into(db, right, IDENTITY)
    entry = _theorem_id(db, "id")

    status_code, body = relate(
        client, right, left,
        obligations=[{
            "source_label": "MP",
            "discharged_by_primitive": "MP",
            "discharged_by_theorem_id": entry,
        }],
    )
    assert status_code == 422
    assert "not both" in body["detail"]


def test_an_obligation_must_name_a_theorem_this_system_can_cite(db, client):
    # A discharge the target cannot reach is a warrant no proof here could cite,
    # and `related_layers` reads only whether the column is filled — so an
    # unreachable one would pass the gate.
    owner = _register_login(client, "reachable@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)
    elsewhere = seed(db, propositional_calculus_spec("Elsewhere"), owner, None)
    promote_into(db, elsewhere, IDENTITY)

    status_code, body = relate(
        client, right, left,
        obligations=[{
            "source_label": "MP",
            "discharged_by_theorem_id": _theorem_id(db, "id"),
        }],
    )
    assert status_code == 422
    assert "cannot cite" in body["detail"]

    # And the accepted half: the same obligation, discharged by a theorem the
    # target has itself.
    promote_into(db, right, IDENTITY)
    assert relate(
        client, right, left,
        obligations=[{
            "source_label": "MP",
            "discharged_by_theorem_id": _theorem_id(db, "id", system=right),
            "status": "discharged",
        }],
    )[0] == 201


# ---------------------------------------------------------------------------
# What a write has to reach
# ---------------------------------------------------------------------------


def test_deleting_an_edge_invalidates_what_resolved_through_it(db, client):
    # The rule §9.15 states and §9.19 generalises: any change to what a label
    # resolves to is a change a standing verdict may be resting on. A proof that
    # verified across this edge keeps `valid`, `result` and its `proof_lines`
    # unless someone clears them — and a verify *trusts* a lemma's stored rows,
    # so a third proof would rest on it too.
    left, right = siblings(db, client, "delete-invalidates@example.com")
    promote_into(db, left, IDENTITY)
    _, edge = relate(client, right, left, status="discharged")

    proof = _proof(client, right, "(P → P) [id]")
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is True
    assert client.get(f"/api/proofs/{proof}").json()["valid"] is True

    assert client.delete(
        f"/api/formal-systems/{right}/relations/{edge['id']}"
    ).status_code == 204

    assert client.get(f"/api/proofs/{proof}").json()["valid"] is None


def test_a_write_leaves_a_proof_that_never_cited_the_source_alone(db, client):
    # The other half: an invalidation that cleared every proof in the system
    # would pass the test above for the wrong reason. This proof cites an axiom
    # of its own system, which no edge can change.
    left, right = siblings(db, client, "bystander@example.com")
    promote_into(db, left, IDENTITY)
    _, edge = relate(client, right, left, status="discharged")

    bystander = _proof(client, right, "(P → (Q → P)) [ax-1]")
    assert client.post(f"/api/proofs/{bystander}/verify").json()["success"] is True

    assert client.delete(
        f"/api/formal-systems/{right}/relations/{edge['id']}"
    ).status_code == 204

    assert client.get(f"/api/proofs/{bystander}").json()["valid"] is True


def test_a_published_target_may_be_related_and_its_proofs_are_invalidated(db, client):
    # Publishing freezes a system's *grammar*; its library was never frozen —
    # `POST /proofs/{id}/promote` writes into a published system's library today.
    # An edge is library reach, so it is allowed here, and it carries the same
    # obligation promotion does.
    owner = _register_login(client, "published-target@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)
    promote_into(db, left, IDENTITY)

    # `seed` publishes, so `right` is frozen — and the contrast is the claim:
    # an edit to the system itself is refused, an edge onto it is not.
    assert client.patch(
        f"/api/formal-systems/{right}", json={"description": "no"}
    ).status_code == 409

    status_code, edge = relate(client, right, left, status="discharged")
    assert status_code == 201, edge

    proof = _proof(client, right, "(P → P) [id]")
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is True

    assert client.delete(
        f"/api/formal-systems/{right}/relations/{edge['id']}"
    ).status_code == 204

    assert client.get(f"/api/proofs/{proof}").json()["valid"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proof(client, system_id: str, source: str) -> str:
    created = client.post(
        "/api/proofs",
        json={"name": f"p-{uuid.uuid4().hex[:8]}", "formal_system_id": system_id,
              "source": source},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _theorem_id(db_path, label: str, system: str | None = None) -> str:
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            stmt = select(PromotedTheoremRow).where(PromotedTheoremRow.label == label)
            if system is not None:
                stmt = stmt.where(PromotedTheoremRow.system_id == uuid.UUID(system))
            entry = session.scalar(stmt)
            assert entry is not None, f"no promoted theorem {label!r}"
            return str(entry.id)
    finally:
        engine.dispose()
