"""`inherits_from_id`, resolved: a child builds on its parent's grammar.

The API half of `tests/test_layered_spec.py`. What it adds is everything the
engine cannot see: which parents may be built on, what a chain that should not
exist does, and the fact that validating and verifying both go through the whole
chain rather than the one row.

The three-layer tower is `tests/layered_systems.py`, seeded a layer at a time —
each published before the next inherits it, which is the rule under test.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone

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
from app.db import spec_to_system, system_to_spec
from app.db.session import get_session
from app.db.systems import RuleRow
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.layered_systems import (
    bound_constant_spec,
    first_order_logic_spec,
    propositional_calculus_spec,
    redeclared_implication_spec,
    stacked_definitions_spec,
    tower,
    zfc_spec,
)
from tests.spec_helpers import rule
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.declarative import SystemSpec


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "inheritance")
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


def seed(
    db_path,
    spec: SystemSpec,
    owner_id: str | None,
    parent_id: str | None = None,
    published: bool = True,
) -> str:
    """Store one layer directly, since the parts CRUD would take a hundred calls."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = spec_to_system(spec)
            system.owner_id = None if owner_id is None else uuid.UUID(owner_id)
            system.inherits_from_id = None if parent_id is None else uuid.UUID(parent_id)
            if published:
                system.published_at = datetime.now(timezone.utc)
            session.add(system)
            session.commit()
            return str(system.id)
    finally:
        engine.dispose()


def seed_tower(db_path, owner_id: str, published_top: bool = False) -> list[str]:
    """The three layers, each inheriting the one below. The top stays a draft."""
    ids: list[str] = []
    parent: str | None = None
    specs = tower()
    for index, spec in enumerate(specs):
        top = index == len(specs) - 1
        parent = seed(
            db_path,
            spec,
            owner_id,
            parent,
            published=published_top if top else True,
        )
        ids.append(parent)
    return ids


def test_a_layer_may_store_parts_over_sorts_it_does_not_declare():
    # ZFC's `⊆` is a `formula` over `term`, and it declares neither: both are the
    # layers below. Storage resolves a sort name to a symbol by FK, so the layer
    # needs a row of its own to hold each name — self-contained, rather than an
    # FK into an ancestor's namespace. The round trip is what says that row
    # carries the name and nothing else: it must not read back as a sort this
    # layer declares.
    spec = zfc_spec()
    assert system_to_spec(spec_to_system(spec)) == spec
    assert spec.sort_names() == []


# ---------------------------------------------------------------------------
# The chain is what a system is built from
# ---------------------------------------------------------------------------


def test_a_child_validates_against_its_ancestors_grammar(client, db):
    owner = _register_login(client, "tower@example.com")
    _pc, _fol, zfc = seed_tower(db, owner)

    response = client.post(f"/api/formal-systems/{zfc}/validate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body.get("errors")
    # The chain's rules, not this layer's: ZFC declares none of its own.
    assert body["inference_rule_count"] == 7
    # The definitions reported are this layer's, though — those are the ones with
    # a row here to name. `df-an` and `df-ex` belong to the layers that declare
    # them and are reported by *their* validate.
    assert [reported["label"] for reported in body["definitions"]] == ["df-ss"]
    # And the binder is the one inferred from the ancestors' `∀`, which is the
    # whole reason a child has to be built against its chain.
    ((binder,),) = [reported["binders"] for reported in body["definitions"]]
    assert binder["var"] == "z" and binder["sort"] == "term"


def test_the_top_layer_alone_would_not_have_validated(client, db):
    # The control for the test above. Seeded with no parent, the ZFC layer is a
    # definition and an axiom over notation nothing declares — which is exactly
    # what `inherits_from_id` resolving is for.
    owner = _register_login(client, "alone@example.com")
    orphan = seed(db, zfc_spec(), owner, published=False)

    body = client.post(f"/api/formal-systems/{orphan}/validate").json()
    assert body["success"] is False


def test_a_proof_in_the_child_may_cite_every_layers_rules(client, db):
    owner = _register_login(client, "verify@example.com")
    _pc, _fol, zfc = seed_tower(db, owner)

    response = client.post(
        f"/api/formal-systems/{zfc}/verify",
        json={
            "proof_text": (
                "(A → (B → A)) [ax-1]\n"
                "∀x (A → (B → A)) [GEN, 1]\n"
                "(∀x (A → (B → A)) → (∀x A → ∀x (B → A))) [ax-4]\n"
                "(∀x A → ∀x (B → A)) [MP, 2, 3]"
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True, response.json()["errors"]


def test_an_ancestors_proviso_still_rejects_a_bad_step(client, db):
    # The negative control for the test above: the same route, the same chain,
    # a step that must not stand. `ax-5` belongs to the middle layer and its
    # `occurs` proviso is evaluated over the term in the top one.
    owner = _register_login(client, "proviso@example.com")
    _pc, _fol, zfc = seed_tower(db, owner)

    def verify(text: str) -> bool:
        response = client.post(
            f"/api/formal-systems/{zfc}/verify", json={"proof_text": text}
        )
        assert response.status_code == 200, response.text
        return response.json()["success"]

    assert verify("(A → ∀x A) [ax-5]")
    assert not verify("(x ∈ y → ∀x x ∈ y) [ax-5]")


def test_a_cross_layer_collision_is_reported_as_a_validation_error(client, db):
    owner = _register_login(client, "collide@example.com")
    pc = seed(db, propositional_calculus_spec(), owner)
    child = seed(db, redeclared_implication_spec(), owner, pc, published=False)

    body = client.post(f"/api/formal-systems/{child}/validate").json()
    assert body["success"] is False
    assert any("implication" in error for error in body["errors"])


def test_a_check_that_only_fires_because_of_the_layer_below(client, db):
    # `∅` declared a constant of the object language is true of its own layer and
    # false once a quantifier ranges over its sort. Both halves through the API,
    # because the message has to reach an author who is looking at one layer.
    owner = _register_login(client, "constant@example.com")
    pc = seed(db, propositional_calculus_spec(), owner)
    constants = seed(db, bound_constant_spec(), owner, pc)
    assert client.post(f"/api/formal-systems/{constants}/validate").json()["success"]

    quantified = seed(db, first_order_logic_spec(), owner, constants, published=False)
    body = client.post(f"/api/formal-systems/{quantified}/validate").json()
    assert body["success"] is False
    assert any("zero" in error for error in body["errors"])


# ---------------------------------------------------------------------------
# Which parents may be built on
# ---------------------------------------------------------------------------


def test_a_parent_must_be_published(client, db):
    owner = _register_login(client, "draft@example.com")
    draft = seed(db, propositional_calculus_spec(), owner, published=False)

    response = client.post(
        "/api/formal-systems", json={"name": "Child", "inherits_from_id": draft}
    )
    assert response.status_code == 400
    assert "unpublished draft" in response.json()["detail"]


def test_a_published_system_may_be_built_on_by_anyone(client, db):
    # The rule this replaces was owned-only, which would lock every user out of
    # an imported corpus: a corpus belongs to no user.
    _register_login(client, "author@example.com")
    corpus = seed(db, propositional_calculus_spec(), owner_id=None)

    response = client.post(
        "/api/formal-systems", json={"name": "Mine", "inherits_from_id": corpus}
    )
    assert response.status_code == 201, response.text
    assert response.json()["inherits_from_id"] == corpus


def test_an_unpublished_system_of_another_owner_is_still_refused(client, db):
    other = _register_login(client, "other@example.com")
    hidden = seed(db, propositional_calculus_spec(), other, published=False)
    _register_login(client, "stranger@example.com")

    response = client.post(
        "/api/formal-systems", json={"name": "Peek", "inherits_from_id": hidden}
    )
    assert response.status_code == 400
    # 400, and the message must not distinguish "not yours" from "not there".
    assert "not a system you can build on" in response.json()["detail"]


def test_a_chain_may_not_be_closed_into_a_cycle(client, db):
    owner = _register_login(client, "cycle@example.com")
    # The root stays a draft so it is still editable; the middle is published so
    # it is a legal parent. Seeded directly, since the write guard is what is
    # under test.
    root = seed(db, propositional_calculus_spec(), owner, published=False)
    middle = seed(db, first_order_logic_spec(), owner, root)
    # The guard this replaces caught only `parent == self`, so a two-step cycle
    # went through and the walk that resolves a chain would have to survive it.
    response = client.patch(
        f"/api/formal-systems/{root}", json={"inherits_from_id": middle}
    )
    assert response.status_code == 400
    assert "cycle" in response.json()["detail"]


def test_a_system_still_may_not_inherit_from_itself(client, db):
    owner = _register_login(client, "self@example.com")
    system = seed(db, propositional_calculus_spec(), owner, published=False)
    response = client.patch(
        f"/api/formal-systems/{system}", json={"inherits_from_id": system}
    )
    assert response.status_code == 400


def test_publishing_a_child_builds_it_against_its_chain(client, db):
    owner = _register_login(client, "publish@example.com")
    _pc, _fol, zfc = seed_tower(db, owner)

    response = client.patch(f"/api/formal-systems/{zfc}", json={"published": True})
    assert response.status_code == 200, response.text
    assert response.json()["published_at"] is not None


def test_a_draft_ancestor_is_refused_at_build_time_too(client, db):
    # Belt and braces for a row that predates the write-time rule: the walk finds
    # a draft above and says so, rather than building on a grammar that can still
    # move under the proofs beneath it.
    owner = _register_login(client, "legacy@example.com")
    pc = seed(db, propositional_calculus_spec(), owner, published=False)
    child = seed(db, first_order_logic_spec(), owner, pc, published=False)

    body = client.post(f"/api/formal-systems/{child}/validate").json()
    assert body["success"] is False
    assert any("not published" in error for error in body["errors"])


def test_a_missing_parent_leaves_the_child_buildable_on_its_own_parts(client, db):
    # `inherits_from_id` is `ON DELETE SET NULL`, so a dangling id is not
    # reachable through the API — but the walk must terminate on one all the
    # same, reporting a system that does not build rather than hanging.
    owner = _register_login(client, "dangling@example.com")
    child = seed(
        db,
        propositional_calculus_spec(),
        owner,
        parent_id=str(uuid.uuid4()),
        published=False,
    )
    body = client.post(f"/api/formal-systems/{child}/validate").json()
    assert body["success"] is True


def test_the_summary_still_reports_the_parent(client, db):
    owner = _register_login(client, "summary@example.com")
    _pc, fol, zfc = seed_tower(db, owner)
    body = client.get(f"/api/formal-systems/{zfc}").json()
    assert body["inherits_from_id"] == fol
    # The detail view is this system's *own* parts, unchanged: the chain is what
    # a system is built from, not what it is.
    assert [rule["label"] for rule in body["rules"]] == []
    assert [axiom["label"] for axiom in body["axioms"]] == ["ax-ext"]


# ---------------------------------------------------------------------------
# Verifying a stored proof — the row-based path
# ---------------------------------------------------------------------------

TOWER_PROOF = (
    "(A → (B → A)) [ax-1]\n"
    "∀x (A → (B → A)) [GEN, 1]\n"
    "(∀x (A → (B → A)) → (∀x A → ∀x (B → A))) [ax-4]\n"
    "(∀x A → ∀x (B → A)) [MP, 2, 3]"
)


def test_a_stored_proof_in_the_child_verifies_and_stays_verified(client, db):
    # The path `POST /formal-systems/{id}/verify` does not take: it caches the
    # rules' composed schema terms, keyed by a digest of the spec — which is now
    # the *chain's*. Run twice, because the second run is the one that reads what
    # the first stored, and a mispaired offset would attach one rule's terms to
    # another and change the verdict.
    owner = _register_login(client, "stored@example.com")
    _pc, _fol, zfc = seed_tower(db, owner)

    created = client.post(
        "/api/proofs",
        json={"name": "Tower", "formal_system_id": zfc, "source": TOWER_PROOF},
    )
    assert created.status_code == 201, created.text
    proof_id = created.json()["id"]

    for _ in range(2):
        response = client.post(f"/api/proofs/{proof_id}/verify")
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True, response.json()["errors"]


def test_only_the_childs_own_rules_cache_their_schema_terms(client, db):
    # An ancestor's rule row cannot hold the term its template composes to *here*
    # — that term is a function of the whole chain's grammar, and the ancestor
    # has its own. So the offset must stamp this system's rows and leave the
    # ancestors' alone. Verified in the *middle* layer, which has rules of its
    # own as well as inherited ones, so both halves of that are visible.
    owner = _register_login(client, "cache@example.com")
    pc, fol, _zfc = seed_tower(db, owner)
    created = client.post(
        "/api/proofs",
        json={
            "name": "Generalised",
            "formal_system_id": fol,
            "source": "(A → (B → A)) [ax-1]\n∀x (A → (B → A)) [GEN, 1]",
        },
    )
    assert created.status_code == 201, created.text
    verified = client.post(f"/api/proofs/{created.json()['id']}/verify")
    assert verified.status_code == 200 and verified.json()["success"], verified.text

    def digests(system_id: str) -> dict[str, str | None]:
        engine = create_engine(db)
        try:
            with Session(engine) as session:
                return dict(
                    session.execute(
                        select(RuleRow.label, RuleRow.schema_digest).where(
                            RuleRow.system_id == uuid.UUID(system_id)
                        )
                    ).all()
                )
        finally:
            engine.dispose()

    own = digests(fol)
    assert set(own) == {"ax-4", "GEN", "ax-5"}
    assert all(digest is not None for digest in own.values())

    inherited = digests(pc)
    assert set(inherited) == {"ax-1", "ax-2", "ax-3", "MP"}
    assert all(digest is None for digest in inherited.values())


def test_a_layer_may_store_a_proviso_over_an_ancestors_sort():
    # A proviso's sort argument is resolved to a symbol exactly as a binding's is,
    # so a layer whose `disjoint(..., term)` names a sort it does not declare
    # needs a row holding that name too.
    spec = SystemSpec(
        name="Provisos",
        rules=[
            rule(
                "R",
                "restricted",
                [],
                "P",
                [("P", "formula"), ("x", "term")],
                side_conditions=["disjoint(x, P, term)"],
            )
        ],
    )
    assert system_to_spec(spec_to_system(spec)) == spec


def test_a_system_cannot_be_deleted_while_something_inherits_from_it(client, db):
    # `inherits_from_id` is `ON DELETE SET NULL`, so the delete would succeed and
    # silently take the descendants' grammar with it — while their proofs keep
    # the verdict of a check against a system that no longer exists.
    owner = _register_login(client, "delete@example.com")
    pc, fol, zfc = seed_tower(db, owner)

    blocked = client.delete(f"/api/formal-systems/{pc}")
    assert blocked.status_code == 409
    assert "inherits from it" in blocked.json()["detail"]

    # Bottom-up is allowed, and each delete frees the one below it.
    assert client.delete(f"/api/formal-systems/{zfc}").status_code == 204
    assert client.delete(f"/api/formal-systems/{fol}").status_code == 204
    assert client.delete(f"/api/formal-systems/{pc}").status_code == 204


def test_a_definition_reorder_is_guarded_against_the_whole_chain(client, db):
    # Read against this system alone, a child's definitions are written in
    # notation nothing declares — so none of them layer, no order can *lose* one,
    # and the guard silently passes everything. `df-nor` is written in `df-nand`'s
    # notation, so putting it first must be refused.
    owner = _register_login(client, "reorder@example.com")
    pc = seed(db, propositional_calculus_spec(), owner)
    child = seed(db, stacked_definitions_spec(), owner, pc, published=False)

    body = client.get(f"/api/formal-systems/{child}").json()
    ids = [row["id"] for row in body["definitions"]]
    assert len(ids) == 2

    refused = client.put(
        f"/api/formal-systems/{child}/definitions/order",
        json={"ids": [ids[1], ids[0]]},
    )
    assert refused.status_code == 400, refused.text
    assert "un-define" in refused.json()["detail"]

    # The control: the order it already has is accepted, so the guard is
    # refusing an order rather than refusing to reorder.
    kept = client.put(
        f"/api/formal-systems/{child}/definitions/order", json={"ids": ids}
    )
    assert kept.status_code == 200, kept.text
