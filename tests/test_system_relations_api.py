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


# ---------------------------------------------------------------------------
# From review
# ---------------------------------------------------------------------------


def test_a_discharge_must_name_a_primitive_this_system_has(db, client):
    # From review. The theorem half of a discharge was checked from the start and
    # the primitive half was not — which is the worse of the two to miss, since a
    # label is far easier to mistype than a UUID. `related_layers` reads only
    # whether the column is *filled*, so a primitive naming a rule nothing
    # declares discharged §2's obligation with a string, and the theorems
    # transferred on it.
    left, right = siblings(db, client, "primitive@example.com")
    promote_into(db, left, IDENTITY)

    status_code, body = relate(
        client, right, left, status="discharged",
        obligations=[{"source_label": "MP",
                      "discharged_by_primitive": "no-such-rule-anywhere",
                      "status": "discharged"}],
    )
    assert status_code == 422
    assert "does not have" in body["detail"]

    # The accepted half: `MP` is a rule this system does declare.
    assert relate(
        client, right, left, status="discharged",
        obligations=[{"source_label": "MP", "discharged_by_primitive": "MP",
                      "status": "discharged"}],
    )[0] == 201
    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True


def test_a_collection_may_not_name_one_thing_twice(db, client):
    # From review, and one refusal for two failures. The per-edge unique index
    # was left to catch this, where it surfaced two different wrong ways: during
    # a PATCH's autoflush, escaping as a 500 with a failed transaction; and on a
    # create, caught by the same handler as the (source, target) index, which
    # then reported "these two systems are already related" about an edge that
    # did not exist.
    left, right = siblings(db, client, "twice@example.com")

    status_code, body = relate(
        client, right, left,
        obligations=[{"source_label": "MP"}, {"source_label": "MP"}],
    )
    assert status_code == 422
    assert "more than once" in body["detail"]

    _, edge = relate(client, right, left)
    patched = client.patch(
        f"/api/formal-systems/{right}/relations/{edge['id']}",
        json={"obligations": [{"source_label": "MP"}, {"source_label": "MP"}]},
    )
    assert patched.status_code == 422
    assert "more than once" in patched.json()["detail"]


def test_a_map_that_has_gone_stale_can_still_be_turned_off(db, client):
    # From review. The map's check ran on *every* PATCH, so once either grammar
    # drifted the edge became un-editable — including the one edit that would
    # stop it resolving. An edge that has stopped checking out is exactly the one
    # an author needs to reach.
    #
    # So the check runs on what is being *written*: a status change goes through,
    # and re-asserting the map is still refused.
    owner = _register_login(client, "stale-map@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    target = seed(db, renamed_propositional_calculus_spec("Target"), owner, None)
    _, edge = relate(client, target, source, status="discharged",
                     **rename(PC_RENAME))

    _drop_production(db, target, "conj")

    assert client.patch(
        f"/api/formal-systems/{target}/relations/{edge['id']}",
        json={"status": "draft"},
    ).status_code == 200

    rewritten = client.patch(
        f"/api/formal-systems/{target}/relations/{edge['id']}",
        json=rename(PC_RENAME),
    )
    assert rewritten.status_code == 422


def test_deleting_the_source_invalidates_what_resolved_through_it(db, client):
    # From review, and the one way an edge disappears that this router never
    # sees: `system_relations` cascades from either end, so deleting the *source*
    # took the edge with it and left the target's proofs holding a verdict that
    # rested on theorems no longer in the database. The re-verify is asserted too,
    # because it is what says the cleared verdict was the right answer rather
    # than a cautious one.
    left, right = siblings(db, client, "delete-source@example.com")
    promote_into(db, left, IDENTITY)
    relate(client, right, left, status="discharged")

    proof = _proof(client, right, "(P → P) [id]")
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is True

    assert client.delete(f"/api/formal-systems/{left}").status_code == 204

    assert client.get(f"/api/proofs/{proof}").json()["valid"] is None
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is False


def _drop_production(db_path, system_id: str, name: str) -> None:
    """Move a system's grammar under an edge that was checked against it.

    Straight to the row: the parts route refuses this one, because the target's
    definition of `∧` still references it — and what is being simulated is any
    ordinary part edit, not this particular one.
    """
    from app.db.systems import SymbolRow

    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            row = session.scalar(
                select(SymbolRow).where(
                    SymbolRow.name == name,
                    SymbolRow.system_id == uuid.UUID(system_id),
                )
            )
            assert row is not None, f"no production {name!r} to drop"
            session.delete(row)
            session.commit()
    finally:
        engine.dispose()


def test_an_interpretation_cannot_discharge_nothing(db, client):
    # From review (Codex, P1). `related_layers` asks the *obligations*, not the
    # author, so an edge claiming to be discharged while naming none of them
    # discharges the whole of §2 with a status column — and the source's entire
    # library crosses on it.
    #
    # Both ways an edge can arrive in that state: created so, and patched into
    # it later with the obligations left as they were.
    owner = _register_login(client, "empty-interpretation@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)
    other = seed(db, propositional_calculus_spec("Other"), owner, None)
    promote_into(db, left, IDENTITY)

    status_code, body = relate(
        client, right, left, kind="interpretation", status="discharged",
    )
    assert status_code == 422
    assert "cannot be marked discharged with no obligations" in body["detail"]

    _, edge = relate(client, right, left, kind="interpretation")
    patched = client.patch(
        f"/api/formal-systems/{right}/relations/{edge['id']}",
        json={"status": "discharged"},
    )
    assert patched.status_code == 422

    # The accepted half — and the reason this is not a check on `extension`,
    # whose claim is that every primitive is present here under its own name.
    # A second source, since the pair above is already related.
    assert relate(client, right, other, kind="extension", status="discharged")[0] == 201


def test_a_source_must_be_published(db, client):
    # From review (Codex, P1). This first allowed an owned *draft* source,
    # reasoning that an entry whose system moved under it fails closed on the
    # next verify. It does — and the proofs that already verified keep `valid`,
    # `result` and their `proof_lines` meanwhile, which a later verify trusts.
    # Freezing is what the spine chose for exactly this, so both now say it.
    owner = _register_login(client, "draft-source@example.com")
    draft = seed(db, propositional_calculus_spec("Draft"), owner, None,
                 published=False)
    target = seed(db, propositional_calculus_spec("Target"), owner, None)

    status_code, body = relate(client, target, draft)
    assert status_code == 400
    assert "unpublished draft" in body["detail"]

    published = seed(db, propositional_calculus_spec("Published"), owner, None)
    assert relate(client, target, published)[0] == 201


def test_retiring_a_warrant_invalidates_what_crossed_its_edge(db, client):
    # From review (Codex, P1). An obligation discharged by a theorem loses it to
    # `ON DELETE SET NULL` when that theorem retires, which stops the edge
    # resolving — but the proofs that crossed it cited the *source's* labels, so
    # the label walk that retires the theorem never reaches them. Another way an
    # edge stops resolving that the relations router never sees.
    from tests.test_proof_promotion import IDENTITY_PROOF, promote, proved_and_published

    owner = _register_login(client, "warrant@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)
    promote_into(db, left, IDENTITY)

    warrant = proved_and_published(client, right, IDENTITY_PROOF)
    assert promote(client, warrant, "stands-in")[0] == 201
    assert relate(
        client, right, left, status="discharged",
        obligations=[{"source_label": "MP",
                      "discharged_by_theorem_id": _theorem_id(db, "stands-in"),
                      "status": "discharged"}],
    )[0] == 201

    proof = _proof(client, right, "(P → P) [id]")
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is True

    assert client.delete(f"/api/proofs/{warrant}/promote").status_code == 204

    assert client.get(f"/api/proofs/{proof}").json()["valid"] is None
    assert client.post(f"/api/proofs/{proof}/verify").json()["success"] is False


# ---------------------------------------------------------------------------
# The statement template (S2)
# ---------------------------------------------------------------------------


def test_a_template_that_will_not_compose_is_refused_at_the_write(db, client):
    # §9.17's rule applied to the other thing an edge carries. A wrap is a claim
    # about *one* grammar — this system's — so unlike a rename it needs no second
    # system to check, and an author gets `template_errors`' own words rather
    # than a citation that mysteriously does not resolve.
    #
    # Paired with the template that does compose, against the same target: one
    # sort name differs between the two calls.
    from tests.sequent_system import hilbert_spec, sequent_spec

    owner = _register_login(client, "template-write@example.com")
    source = seed(db, hilbert_spec(), owner, None)
    target = seed(db, sequent_spec(), owner, None)

    wrap = {"statement_template": "G ⊢ {wff}",
            "extras": [{"name": "G", "sort": "context"}]}
    assert relate(client, target, source, kind="interpretation", **wrap)[0] == 201

    second = seed(db, sequent_spec("Second"), owner, None)
    status_code, body = relate(
        client, second, source, kind="interpretation",
        statement_template="G ⊢ {formula}",
        extras=[{"name": "G", "sort": "context"}],
    )
    assert status_code == 422
    assert "'formula'" in body["detail"] and "does not declare" in body["detail"]


def test_template_metavariables_need_a_template_to_appear_in(db, client):
    # Extras with no template are a statement about nothing — the wrap is what
    # introduces them, so declaring one without the other is a half-written edge
    # that would silently transfer unwrapped theorems.
    from tests.sequent_system import hilbert_spec, sequent_spec

    owner = _register_login(client, "orphan-extras@example.com")
    source = seed(db, hilbert_spec(), owner, None)
    target = seed(db, sequent_spec(), owner, None)

    status_code, body = relate(
        client, target, source, kind="interpretation",
        extras=[{"name": "G", "sort": "context"}],
    )
    assert status_code == 422
    assert "no statement template" in body["detail"]


def test_a_template_can_be_turned_off_after_the_grammar_moves(db, client):
    # §9.21's rule, for the wrap: a check runs on *what is being written*, so an
    # edge whose template has stopped composing can still be edited — including
    # the edit that turns it off, which is the one its author needs. Paired with
    # re-asserting the template, which is refused.
    from tests.sequent_system import hilbert_spec, sequent_spec

    owner = _register_login(client, "template-off@example.com")
    source = seed(db, hilbert_spec(), owner, None)
    target = seed(db, sequent_spec(), owner, None)
    created = relate(
        client, target, source, kind="interpretation",
        statement_template="G ⊢ {wff}", extras=[{"name": "G", "sort": "context"}],
    )
    assert created[0] == 201
    edge = created[1]["id"]

    # Clearing the template alone, without also naming `extras` — which is what
    # an author would actually send, and what review found 422ing because the
    # orphaned extras rows survived the clear (they are now cleared with it).
    turned_off = client.patch(
        f"/api/formal-systems/{target}/relations/{edge}",
        json={"statement_template": ""},
    )
    assert turned_off.status_code == 200, turned_off.text
    assert turned_off.json()["statement_template"] is None
    assert turned_off.json()["extras"] == []

    refused = client.patch(
        f"/api/formal-systems/{target}/relations/{edge}",
        json={"statement_template": "G ⊢ {formula}",
              "extras": [{"name": "G", "sort": "context"}]},
    )
    assert refused.status_code == 422


def test_an_edge_round_trips_its_template(db, client):
    # The wrap is on the read model too, so an author can see what an edge does
    # without reading the rows.
    from tests.sequent_system import hilbert_spec, sequent_spec

    owner = _register_login(client, "template-read@example.com")
    source = seed(db, hilbert_spec(), owner, None)
    target = seed(db, sequent_spec(), owner, None)
    assert relate(
        client, target, source, kind="interpretation",
        statement_template="G ⊢ {wff}", extras=[{"name": "G", "sort": "context"}],
    )[0] == 201

    listed = client.get(f"/api/formal-systems/{target}/relations").json()
    assert [edge["statement_template"] for edge in listed] == ["G ⊢ {wff}"]
    assert listed[0]["extras"] == [{"name": "G", "sort": "context"}]


def test_an_extension_may_not_restate_what_it_transfers(db, client):
    # **From review (Codex, P1), and it was a hole rather than a wrinkle.**
    # §5.4 defines an extension as the degenerate edge — the target contains the
    # source, so every primitive is present under its own label and the
    # obligations are filled in from the spine. A template contradicts that
    # outright: it says the two do not even state the same kind of thing.
    #
    # Left unchecked, the empty-obligations refusal is scoped to
    # `interpretation` and `related_layers` never reads `kind` at all — so a
    # discharged `extension` carrying a template wrapped every source theorem
    # into this system's shape with no primitive image established anywhere. The
    # whole of §2, skipped by setting one column.
    #
    # Three assertions: refused on create, refused on a PATCH that changes the
    # kind under an existing template, and accepted as the interpretation it
    # actually is.
    from tests.sequent_system import hilbert_spec, sequent_spec

    owner = _register_login(client, "extension-wrap@example.com")
    source = seed(db, hilbert_spec(), owner, None)
    target = seed(db, sequent_spec(), owner, None)
    wrap = {"statement_template": "G ⊢ {wff}",
            "extras": [{"name": "G", "sort": "context"}]}

    status_code, body = relate(
        client, target, source, kind="extension", status="discharged", **wrap
    )
    assert status_code == 422
    assert "extension edge transfers theorems as they are" in body["detail"]

    created = relate(client, target, source, kind="interpretation", **wrap)
    assert created[0] == 201
    edge = created[1]["id"]

    demoted = client.patch(
        f"/api/formal-systems/{target}/relations/{edge}",
        json={"kind": "extension"},
    )
    assert demoted.status_code == 422, demoted.text
