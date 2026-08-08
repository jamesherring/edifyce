"""What a formal statement claims to be a formalization *of*.

§4.3 of docs/informal-source-ingestion-roadmap.md. The kernel certifies that a
proof establishes a term in a system and has no opinion on whether that term is
Theorem 3.2 of the paper someone was reading — so this layer does not check the
claim, it records it, attributes it, and makes its absence visible.

Which means the tests are almost all about the *record* rather than about
mathematics: that a version is a row, that the informal statement is frozen at
the moment of claiming, that a claim naming things which do not hang together is
refused, and that "reviewed" cannot be said by the person who claimed it.
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
import app.routers.formalizations as formalizations_router
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed_tower
from tests.test_systems_api import _register_login


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "formalizations")
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


IDENTITY = {
    "constructor": "implication",
    "slots": {
        "p": {"constructor": "prop_var", "literal": "A"},
        "q": {"constructor": "prop_var", "literal": "A"},
    },
}

PAPER = {
    "kind": "arxiv",
    "identifier": "2401.01234",
    "version": "v1",
    "title": "On things that follow from themselves",
}


def tower(db, client, email: str) -> tuple[str, str, str]:
    owner = _register_login(client, email)
    pc, fol, zfc = seed_tower(db, owner, published_top=True)
    return pc, fol, zfc


def login(client, email: str, password: str = "password123") -> None:
    """Switch back to an account that already exists — `_register_login` would
    trip on the duplicate registration."""
    response = client.post(
        "/api/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 204, response.text


def register(client, **overrides: object) -> tuple[int, dict]:
    response = client.post("/api/sources", json={**PAPER, **overrides})
    return response.status_code, (response.json() if response.content else {})


def store_statement(client, system_id: str) -> str:
    """A term id, by the route §4.4 added for exactly this."""
    response = client.post(
        f"/api/formal-systems/{system_id}/statements",
        json={"statement": IDENTITY, "store": True},
    )
    assert response.status_code == 200, response.text
    return response.json()["term_id"]


def claim(client, system_id: str, document_id: str, **overrides: object):
    body = {
        "document_id": document_id,
        "claim": "Theorem 3.2",
        "informal_statement": "Everything implies itself.",
        "formal_system_id": system_id,
        "statement_term_id": store_statement(client, system_id),
        "reasoning": "The paper's φ ⇒ φ is this system's implication over one atom.",
        **overrides,
    }
    response = client.post("/api/formalizations", json=body)
    return response.status_code, (response.json() if response.content else {})


# ---------------------------------------------------------------------------
# A version is a row
# ---------------------------------------------------------------------------


def test_registering_the_same_work_twice_returns_one_row(db, client):
    # Idempotent on identity, so two people formalizing one paper share the row
    # rather than racing to own it — and a retrying caller gets the same id.
    tower(db, client, "form-source@example.com")

    first = register(client)
    second = register(client, title="A different title, later")
    assert first[0] == 201
    assert second[1]["id"] == first[1]["id"]
    # The first registration's metadata stands: a second caller's title is no
    # more authoritative, and overwriting would make the row depend on who asked
    # last.
    assert second[1]["title"] == PAPER["title"]


def test_a_new_version_is_a_new_document(db, client):
    # The requirement made structural rather than checked: a v2 may restate the
    # theorem, so a claim made against v1 must keep pointing at the v1 its author
    # read.
    tower(db, client, "form-version@example.com")

    first = register(client)[1]
    second = register(client, version="v2")[1]
    assert second["id"] != first["id"]


def test_the_informal_statement_is_frozen_at_the_claim(db, client):
    # Copied onto the claim rather than read from the document, so nothing — an
    # edit, a revision — can rewrite what the attestation was about.
    pc, _fol, _zfc = tower(db, client, "form-frozen@example.com")
    document = register(client)[1]["id"]
    status, body = claim(client, pc, document)
    assert status == 201, body

    # A revision arrives, saying something else. The claim is unmoved.
    register(client, version="v2", title="Revised")
    reread = client.get(f"/api/formalizations/{body['id']}").json()
    assert reread["informal_statement"] == "Everything implies itself."
    assert reread["document"]["version"] == "v1"


# ---------------------------------------------------------------------------
# The claim itself
# ---------------------------------------------------------------------------


def test_a_claim_records_the_attestation_and_both_sides(db, client):
    # The whole point: the paper's words, the term they were read as, and who
    # said the two correspond — together, so a reader can judge.
    pc, _fol, _zfc = tower(db, client, "form-claim@example.com")
    document = register(client)[1]["id"]

    status, body = claim(client, pc, document, attested_as="claude-opus-5")
    assert status == 201, body
    assert body["informal_statement"] == "Everything implies itself."
    # The formal side is named rather than rendered: the term route is what
    # renders a stored term, and does it better. See `Formalization`.
    assert body["statement_term_id"]
    assert body["reasoning"].startswith("The paper's")
    # The agent is recorded *beside* the account, not instead of it: an account
    # is accountable and a model is not.
    assert body["attested_as"] == "claude-opus-5"
    assert body["attested_by"]["id"]
    # And nobody has reviewed it, which is the ordinary state and looks like one.
    assert body["review_verdict"] is None


def test_a_claim_carries_its_glossary(db, client):
    # The alignment claim at the granularity a disagreement happens at: a
    # reviewer can reject one reading without rejecting the whole statement.
    pc, _fol, _zfc = tower(db, client, "form-glossary@example.com")
    document = register(client)[1]["id"]

    status, body = claim(
        client,
        pc,
        document,
        glossary=[
            {
                "notion": "⇒",
                "label": "implication",
                "reasoning": "The paper's material conditional.",
            }
        ],
    )
    assert status == 201, body
    assert [entry["notion"] for entry in body["glossary"]] == ["⇒"]


def test_a_glossary_entry_naming_nothing_is_refused(db, client):
    # It would record only that somebody thought about the word.
    pc, _fol, _zfc = tower(db, client, "form-empty-gloss@example.com")
    document = register(client)[1]["id"]

    status, _ = claim(
        client, pc, document, glossary=[{"notion": "⇒", "reasoning": "Hmm."}]
    )
    assert status == 422


def test_a_claim_with_no_reasoning_is_refused(db, client):
    # A claim with no argument is a tick, and a tick is what this layer exists to
    # refuse.
    pc, _fol, _zfc = tower(db, client, "form-noreason@example.com")
    document = register(client)[1]["id"]

    status, _ = claim(client, pc, document, reasoning="")
    assert status == 422


def test_a_term_of_another_system_is_refused(db, client):
    # Interning is per system, so a term of another names a statement this one
    # cannot mean — the claim would be about two different things.
    pc, _fol, zfc = tower(db, client, "form-foreign@example.com")
    document = register(client)[1]["id"]

    status, detail = claim(
        client, pc, document, statement_term_id=store_statement(client, zfc)
    )
    assert status == 422, detail


def test_a_proof_of_another_system_is_refused(db, client):
    pc, _fol, zfc = tower(db, client, "form-foreignproof@example.com")
    document = register(client)[1]["id"]
    elsewhere = client.post(
        "/api/proofs",
        json={"name": "elsewhere", "formal_system_id": zfc, "source": "(A → A) [?]"},
    ).json()["id"]

    status, detail = claim(client, pc, document, proof_id=elsewhere)
    assert status == 422, detail


def test_two_readings_of_one_theorem_both_stand(db, client):
    # Not deduplicated, deliberately: two people may formalize one theorem
    # differently, and that disagreement is what a reader should see rather than
    # a race to be the row.
    pc, _fol, _zfc = tower(db, client, "form-two@example.com")
    document = register(client)[1]["id"]

    assert claim(client, pc, document)[0] == 201
    assert claim(client, pc, document, reasoning="A different reading.")[0] == 201

    listed = client.get(f"/api/formalizations?document_id={document}").json()
    assert listed["total"] == 2


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def test_a_second_reader_can_confirm_a_claim(db, client):
    pc, _fol, _zfc = tower(db, client, "form-attestor@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]

    _register_login(client, "form-reviewer@example.com")
    response = client.post(
        f"/api/formalizations/{made}/review",
        json={"verdict": "confirmed", "note": "Read the paper; this is 3.2."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_verdict"] == "confirmed"
    assert response.json()["reviewed_by"]["id"]


def test_the_attestor_may_not_review_their_own_claim(db, client):
    # The entire value of the word is independence, and a self-review that reads
    # as reviewed is the silent overstatement this layer exists to refuse.
    pc, _fol, _zfc = tower(db, client, "form-self@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]

    response = client.post(
        f"/api/formalizations/{made}/review", json={"verdict": "confirmed"}
    )
    assert response.status_code == 403, response.text


def test_a_dispute_must_say_what_is_wrong(db, client):
    # A dispute nobody explained is not a finding — and a dispute is the more
    # valuable of the two verdicts.
    pc, _fol, _zfc = tower(db, client, "form-dispute@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]
    _register_login(client, "form-disputer@example.com")

    assert (
        client.post(
            f"/api/formalizations/{made}/review", json={"verdict": "disputed"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/formalizations/{made}/review",
            json={"verdict": "disputed", "note": "3.2 is about a *strict* order."},
        ).status_code
        == 200
    )


def test_unreviewed_claims_can_be_listed(db, client):
    # "Its absence is visible" as a query rather than a phrase.
    pc, _fol, _zfc = tower(db, client, "form-unreviewed@example.com")
    document = register(client)[1]["id"]
    reviewed = claim(client, pc, document)[1]["id"]
    claim(client, pc, document, claim="Theorem 3.3")

    _register_login(client, "form-checker@example.com")
    client.post(f"/api/formalizations/{reviewed}/review", json={"verdict": "confirmed"})

    open_claims = client.get("/api/formalizations?unreviewed=true").json()
    assert [c["claim"] for c in open_claims["items"]] == ["Theorem 3.3"]


def test_editing_the_glossary_withdraws_the_review(db, client):
    # A reviewer agreed with a reading of the paper's words. Change the words and
    # nobody has agreed with the reading that now stands.
    pc, _fol, _zfc = tower(db, client, "form-regloss@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]

    _register_login(client, "form-regloss-reviewer@example.com")
    client.post(f"/api/formalizations/{made}/review", json={"verdict": "confirmed"})
    assert client.get(f"/api/formalizations/{made}").json()["review_verdict"] == (
        "confirmed"
    )

    login(client, "form-regloss@example.com")
    response = client.put(
        f"/api/formalizations/{made}/glossary",
        json=[{"notion": "⇒", "label": "implication"}],
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_verdict"] is None


def test_only_the_attestor_may_edit_or_withdraw(db, client):
    pc, _fol, _zfc = tower(db, client, "form-owner@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]

    _register_login(client, "form-stranger@example.com")
    assert client.put(f"/api/formalizations/{made}/glossary", json=[]).status_code == 404
    assert client.delete(f"/api/formalizations/{made}").status_code == 404


def test_withdrawing_a_claim_leaves_the_mathematics_alone(db, client):
    # Nothing formal depends on a fidelity claim: a proof establishes its term
    # whether or not anyone still says the term is Theorem 3.2. So this is a
    # plain delete rather than the gated withdrawal an assumption needs.
    pc, _fol, _zfc = tower(db, client, "form-withdraw@example.com")
    document = register(client)[1]["id"]
    body = claim(client, pc, document)[1]
    term = body["statement_term_id"]

    assert client.delete(f"/api/formalizations/{body['id']}").status_code == 204
    assert client.get(f"/api/formalizations/{body['id']}").status_code == 404
    # The term is untouched and still readable.
    assert client.get(f"/api/formal-systems/{pc}/terms/{term}").status_code == 200


# ---------------------------------------------------------------------------
# What the record says about itself, checked against what it accepts
# ---------------------------------------------------------------------------
#
# Four guards that were stated and not enforced (found in review). Each is a
# place the schema or the docstring made a promise the code did not keep, which
# on a surface whose whole job is honest bookkeeping is the failure that matters.


def test_a_glossary_term_of_another_system_is_refused(db, client):
    # The same check `statement_term_id` gets: a term of another system would
    # leave the glossary pointing outside the system the claim is about, and a
    # nonexistent one would reach the foreign key and answer 500.
    pc, _fol, zfc = tower(db, client, "form-gloss-foreign@example.com")
    document = register(client)[1]["id"]
    elsewhere = store_statement(client, zfc)

    status, detail = claim(
        client,
        pc,
        document,
        glossary=[{"notion": "⇒", "term_id": elsewhere}],
    )
    assert status == 422, detail


def test_replacing_the_glossary_checks_its_terms_too(db, client):
    # The create path and the replace path have to agree, or the guard is a
    # detour rather than a rule.
    pc, _fol, zfc = tower(db, client, "form-gloss-replace@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]
    elsewhere = store_statement(client, zfc)

    response = client.put(
        f"/api/formalizations/{made}/glossary",
        json=[{"notion": "⇒", "term_id": elsewhere}],
    )
    assert response.status_code == 422, response.text


def test_whitespace_is_not_an_argument(db, client):
    # `min_length` counts characters, not content, so a reasoning of three
    # spaces satisfied it — admitting exactly the empty attestation the schema
    # says it refuses.
    pc, _fol, _zfc = tower(db, client, "form-blank@example.com")
    document = register(client)[1]["id"]

    assert claim(client, pc, document, reasoning="   ")[0] == 422
    assert claim(client, pc, document, informal_statement=" \t ")[0] == 422


def test_a_blank_label_names_nothing(db, client):
    # An entry whose label is three spaces names exactly as little as one with
    # no label at all.
    pc, _fol, _zfc = tower(db, client, "form-blanklabel@example.com")
    document = register(client)[1]["id"]

    status, _ = claim(client, pc, document, glossary=[{"notion": "⇒", "label": "  "}])
    assert status == 422


def test_a_racing_registration_returns_the_winner(db, client):
    # The idempotency guarantee is what a retrying agent relies on, and it would
    # have failed precisely for the concurrent ones: both callers read "no such
    # row", both inserted, and the loser got a 500 from the unique index. The
    # index still decides; the loser now gets told what it decided.
    #
    # The race is simulated by making the pre-read miss once, which is what the
    # losing request actually experiences.
    tower(db, client, "form-race@example.com")
    first = register(client)[1]

    original = formalizations_router._document_like
    seen: list[int] = []

    async def miss_once(session, payload):
        seen.append(1)
        return None if len(seen) == 1 else await original(session, payload)

    formalizations_router._document_like = miss_once
    try:
        status, second = register(client)
    finally:
        formalizations_router._document_like = original

    assert status == 201, second
    assert second["id"] == first["id"]


# ---------------------------------------------------------------------------
# Who may read a claim
# ---------------------------------------------------------------------------


def test_a_claim_about_a_draft_system_is_its_owners(db, client):
    # A claim carries its system's id, its term, its proof and its prose, so
    # serving one about a draft answers in detail the question
    # `GET /formal-systems/{id}` answers with a 404. The leak the repo's
    # 404-not-403 policy exists to prevent (found in review).
    owner = _register_login(client, "form-draft@example.com")
    pc, _fol, zfc = seed_tower(db, owner, published_top=False)
    document = register(client)[1]["id"]
    made = claim(client, zfc, document)[1]["id"]

    # The owner still sees it.
    assert client.get(f"/api/formalizations/{made}").status_code == 200
    assert client.get("/api/formalizations").json()["total"] == 1

    _register_login(client, "form-nosy@example.com")
    assert client.get(f"/api/formalizations/{made}").status_code == 404
    assert client.get("/api/formalizations").json()["items"] == []

    # And anonymously, which is where an unauthenticated read used to serve it.
    client.cookies.clear()
    assert client.get(f"/api/formalizations/{made}").status_code == 404
    assert client.get("/api/formalizations").json()["items"] == []


def test_a_claim_about_a_published_system_is_public(db, client):
    # The control: publishing is what makes a system's claims reviewable, and a
    # reviewer needs no account to read one.
    pc, _fol, _zfc = tower(db, client, "form-public@example.com")
    document = register(client)[1]["id"]
    made = claim(client, pc, document)[1]["id"]

    client.cookies.clear()
    assert client.get(f"/api/formalizations/{made}").status_code == 200


def test_a_claim_reports_its_documents_real_count(db, client):
    # `/sources` reported the true number for a row while a claim reported zero
    # for the same one (found in review).
    pc, _fol, _zfc = tower(db, client, "form-count@example.com")
    document = register(client)[1]["id"]
    claim(client, pc, document)
    body = claim(client, pc, document, claim="Theorem 3.3")[1]

    assert body["document"]["formalizations"] == 2
    listed = client.get("/api/sources").json()["items"]
    assert listed[0]["formalizations"] == 2


def test_the_source_listing_is_paged(db, client):
    tower(db, client, "form-paged@example.com")
    register(client)
    register(client, version="v2")

    page = client.get("/api/sources?limit=1").json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
