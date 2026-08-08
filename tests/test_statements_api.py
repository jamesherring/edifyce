"""Stating a theorem before there is a proof to put it in.

§4.4 of docs/informal-source-ingestion-roadmap.md. Every other structured write
is *inside* a proof; a translation from an informal source needs the opposite
order — state the target, ask whether the library already proves it, and only
then open a proof aimed at it.

The worked example is the PC/FOL/ZFC tower the promotion and assumption tests
use, so the library this searches is one built by the same routes a caller would
have used. What the tests turn on is the three things the route promises: the
statement resolves from the grammar and nothing else, the round trip is checked
rather than trusted, and the search says *candidate* where a candidate is all it
has.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.auth.backend as backend
import app.routers.statements as statements_router
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_proofs_api import _TABLES
from tests.test_proof_promotion import (
    IDENTITY_PROOF,
    promote,
    proved_and_published,
)
from tests.test_system_inheritance import seed_tower
from tests.test_systems_api import _register_login


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "statements")
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


def tower(db, client, email: str) -> tuple[str, str, str]:
    owner = _register_login(client, email)
    pc, fol, zfc = seed_tower(db, owner, published_top=True)
    return pc, fol, zfc


# `(A → A)` in the tower's propositional grammar, named by production rather than
# written — which is the whole point of the route.
def implication(left: dict, right: dict) -> dict:
    return {"constructor": "implication", "slots": {"p": left, "q": right}}


def atom(name: str) -> dict:
    return {"constructor": "prop_var", "literal": name}


IDENTITY = implication(atom("A"), atom("A"))


def state(
    client, system_id: str, statement: dict | None = None, **extra: object
) -> tuple[int, dict]:
    response = client.post(
        f"/api/formal-systems/{system_id}/statements",
        json={"statement": IDENTITY if statement is None else statement, **extra},
    )
    return response.status_code, (response.json() if response.content else {})


# ---------------------------------------------------------------------------
# The statement resolves, and reads back as what was asked for
# ---------------------------------------------------------------------------


def test_a_statement_resolves_from_the_grammar_alone(db, client):
    # No surface syntax crosses the wire in either direction as *input*: the
    # caller names productions, and what comes back is the system's own spelling
    # of the term they named.
    pc, _fol, _zfc = tower(db, client, "state-basic@example.com")

    status, body = state(client, pc)
    assert status == 200, body
    assert body["rendered"] == "(A → A)"
    assert body["constructor"] == "implication"
    assert body["digest"] and body["alpha_digest"]


def test_a_statement_is_not_stored_unless_asked(db, client):
    # Asking whether something is proved is a question, and a question does not
    # write rows. Without an id there is nothing to point at later, which is
    # exactly the trade.
    pc, _fol, _zfc = tower(db, client, "state-dry@example.com")

    assert state(client, pc)[1]["term_id"] is None
    assert state(client, pc, store=True)[1]["term_id"] is not None


def test_a_stored_statement_is_usable_as_a_reference(db, client):
    # What storing buys: the id is a `ref` every other structured route takes, so
    # a caller states a subterm once and points at it thereafter.
    pc, _fol, _zfc = tower(db, client, "state-ref@example.com")
    inner = state(client, pc, store=True)[1]["term_id"]

    status, body = state(client, pc, implication({"ref": inner}, {"ref": inner}))
    assert status == 200, body
    assert body["rendered"] == "((A → A) → (A → A))"


def test_two_statements_of_one_term_intern_to_one_row(db, client):
    # Interning is per system and by digest, so asking twice is idempotent — a
    # caller that stores the same goal on every retry does not grow the graph.
    pc, _fol, _zfc = tower(db, client, "state-intern@example.com")

    first = state(client, pc, store=True)[1]
    second = state(client, pc, store=True)[1]
    assert first["term_id"] == second["term_id"]
    assert first["digest"] == second["digest"]


# ---------------------------------------------------------------------------
# Is it already proved?
# ---------------------------------------------------------------------------


def test_the_library_names_what_could_already_prove_it(db, client):
    # The first question any translation asks, and the one that had no answer
    # short of writing a proof and seeing. What comes back is *candidates* — the
    # route says nothing about proof, for the reasons its docstring gives.
    pc, _fol, _zfc = tower(db, client, "state-proved@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    status, body = state(client, pc, implication(atom("P"), atom("P")))
    assert status == 200, body
    assert [m["label"] for m in body["matches"]] == ["id"]
    assert body["matches"][0]["exact"] is True
    # And no field claims it is proved: `exact` is a ranking hint, and confirming
    # it is unification against a line in a real scope.
    assert "proved" not in body


def test_a_statement_nothing_proves_says_so(db, client):
    # The control: the answer is about this statement, not about whether the
    # library has anything at all. `id` is there and does not conclude this.
    pc, _fol, _zfc = tower(db, client, "state-unproved@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    status, body = state(client, pc, implication(atom("A"), atom("B")))
    assert status == 200, body
    assert [m["exact"] for m in body["matches"]] == [False]


def test_an_ancestors_theorem_answers_a_descendants_question(db, client):
    # A library is resolved through the inheritance chain, so the search has to
    # be too — otherwise a translation written in ZFC would be told nothing in
    # propositional calculus proves its goal.
    pc, _fol, zfc = tower(db, client, "state-chain@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    body = state(client, zfc, implication(atom("P"), atom("P")))[1]
    assert [m["label"] for m in body["matches"]] == ["id"]


def test_a_grammar_that_renames_constants_says_its_ranking_is_approximate(db, client):
    # `exact` compares the stored α-digest, whose policy renames every regex leaf
    # — right for search, and wrong for a production whose tokens denote
    # constants, where it reads `2 = 5` and `7 = 9` as one statement. The tower
    # declares no such production, so the flag is off; a caller on a grammar that
    # does declare one needs telling, or it has to distrust the ranking
    # everywhere (found in review).
    pc, _fol, _zfc = tower(db, client, "state-approx@example.com")
    assert state(client, pc)[1]["exact_is_approximate"] is False


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_constructor_the_grammar_does_not_have_is_refused(db, client):
    pc, _fol, _zfc = tower(db, client, "state-nogrammar@example.com")
    status, detail = state(client, pc, {"constructor": "nonesuch"})
    assert status == 422, detail


def test_a_term_of_another_system_is_refused(db, client):
    # Interning is per system, so a foreign id names a term built over another
    # grammar — resolving one would state a formula this system cannot mean.
    pc, _fol, zfc = tower(db, client, "state-foreign@example.com")
    theirs = state(client, zfc, store=True)[1]["term_id"]

    status, detail = state(client, pc, {"ref": theirs})
    assert status == 422, detail
    assert "no term with id" in detail["detail"]


def test_storing_into_a_system_you_do_not_own_is_refused(db, client):
    # Reading the question is anyone's; writing a row is the owner's.
    pc, _fol, _zfc = tower(db, client, "state-owner@example.com")
    _register_login(client, "stranger@example.com")

    assert state(client, pc)[0] == 200
    assert state(client, pc, store=True)[0] == 403


def test_a_draft_system_is_not_readable_by_a_stranger(db, client):
    owner = _register_login(client, "state-draft@example.com")
    _pc, _fol, zfc = seed_tower(db, owner, published_top=False)
    _register_login(client, "state-nosy@example.com")

    assert state(client, zfc)[0] == 404


def test_the_question_may_be_asked_without_an_account(db, client):
    # A published system's library is public, and "is this already proved?" is a
    # question about it — which is what makes the imported corpus, ownerless by
    # construction, answerable at all.
    pc, _fol, _zfc = tower(db, client, "state-anon@example.com")
    client.cookies.clear()

    assert state(client, pc)[0] == 200
    assert state(client, pc, store=True)[0] == 403


def test_the_round_trip_is_checked_rather_than_trusted(db, client, monkeypatch):
    # The guarantee that makes structural emission safe (§9c): the resolved term
    # is rendered into the system's own spelling and read back, and the statement
    # is refused unless what comes out is what went in.
    #
    # Pinned by forcing the read-back to fail rather than by finding a statement
    # this grammar renders ambiguously — the tower is fully bracketed, so no such
    # statement exists in it, and the realistic regression is the check being
    # dropped rather than defeated.
    pc, _fol, _zfc = tower(db, client, "state-roundtrip@example.com")
    monkeypatch.setattr(statements_router, "reparse_statement", lambda *_: None)

    status, detail = state(client, pc)
    assert status == 422, detail
    assert "reads back as" in detail["detail"]
