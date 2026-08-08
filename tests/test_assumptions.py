"""Citable statements nobody proved, and the debt they leave behind.

§4.1/§4.2 of docs/informal-source-ingestion-roadmap.md. An assumption lets a
translation from an informal source cite a result before anyone has proved it —
"by Lemma 2.1 of [7]" — which is the difference between a top-down translation
that can start and one that cannot.

The whole point is that taking the debt on must not lose it. So the tests here
are mostly about *propagation*: a proof citing an assumption rests on it, a
theorem promoted from that proof rests on it, and a proof citing **that** theorem
rests on it too — at which point no line of the third proof mentions the
assumption at all, and only the stored closure knows.

The worked example is the PC/FOL/ZFC tower the promotion tests use, and Peirce's
law as the thing assumed: a real theorem, in the grammar, that a Łukasiewicz
derivation would take genuine work to reach.
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
import app.routers.proofs as proofs_router
from app.db.assumptions import AssumptionRow, TheoremAssumptionRow, rests_on
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_proofs_api import _TABLES
from tests.test_proof_promotion import (
    IDENTITY_PROOF,
    make_proof,
    proved_and_published,
    promote,
    publish,
    verify,
)
from tests.test_system_inheritance import seed_tower
from tests.test_systems_api import _register_login


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "assumptions")
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


# Peirce's law, held schematic — so a citation instantiates it, exactly as a
# promoted theorem's statement is instantiated.
PEIRCE = "(((P → Q) → P) → P)"
PEIRCE_VARS = {"P": "formula", "Q": "formula"}


def tower(db, client, email: str) -> tuple[str, str, str]:
    owner = _register_login(client, email)
    pc, fol, zfc = seed_tower(db, owner, published_top=True)
    return pc, fol, zfc


def assume(
    client,
    system_id: str,
    label: str = "peirce",
    statement: str = PEIRCE,
    metavariables: dict[str, str] | None = None,
    reason: str = "Classical; proved in every textbook, not yet proved here.",
    source: str | None = "arXiv:0000.00000",
    **extra: object,
) -> tuple[int, dict]:
    body: dict = {
        "label": label,
        "statement": statement,
        "metavariables": PEIRCE_VARS if metavariables is None else metavariables,
        "reason": reason,
        "source": source,
        **extra,
    }
    response = client.post(f"/api/formal-systems/{system_id}/assumptions", json=body)
    return response.status_code, (response.json() if response.content else {})


def provenance(client, proof_id: str) -> tuple[int, dict]:
    response = client.get(f"/api/proofs/{proof_id}/provenance")
    return response.status_code, (response.json() if response.content else {})


def assumed_labels(report: dict) -> list[str]:
    return [entry["label"] for entry in report["assumes"]]


# ---------------------------------------------------------------------------
# The valid case: an assumption is an ordinary citation
# ---------------------------------------------------------------------------


def test_an_assumption_is_citable_like_any_other_library_entry(db, client):
    # The whole mechanism in one call: the entry is stored as a theorem the
    # system asserts, so a proof cites it with no new syntax and the checker
    # needs to have learned nothing.
    pc, _fol, _zfc = tower(db, client, "assume-cite@example.com")

    status, entry = assume(client, pc)
    assert status == 201, entry
    assert entry["label"] == "peirce"
    assert entry["dependents"] == 0

    checked = verify(client, make_proof(client, pc, "(((A → B) → A) → A) [peirce]"))
    assert checked["success"] is True, checked


def test_an_assumption_is_citable_two_layers_up(db, client):
    # Where it has to work for an ingestion pipeline: the debt is taken on in the
    # layer that owns the mathematics, and the translation is written above it.
    pc, _fol, zfc = tower(db, client, "assume-tower@example.com")
    assert assume(client, pc)[0] == 201

    checked = verify(client, make_proof(client, zfc, "(((A → B) → A) → A) [peirce]"))
    assert checked["success"] is True, checked


def test_a_proof_citing_an_assumption_says_so(db, client):
    # §4.2: a conditional result is legitimate and must not be silent.
    pc, _fol, _zfc = tower(db, client, "assume-report@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, "(((A → B) → A) → A) [peirce]")
    verify(client, proof)

    status, report = provenance(client, proof)
    assert status == 200, report
    assert assumed_labels(report) == ["peirce"]
    assert report["complete"] is True
    assert report["assumes"][0]["reason"].startswith("Classical")
    assert report["assumes"][0]["source"] == "arXiv:0000.00000"


def test_a_proof_that_assumes_nothing_reports_nothing(db, client):
    # The negative control the test above needs: the report is a fact about this
    # proof, not a restatement of what the system happens to hold. The assumption
    # exists and is citable; this proof simply does not cite it.
    pc, _fol, _zfc = tower(db, client, "assume-none@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, IDENTITY_PROOF)
    verify(client, proof)

    status, report = provenance(client, proof)
    assert status == 200, report
    assert report["assumes"] == []
    assert report["complete"] is True


# ---------------------------------------------------------------------------
# Propagation — the claim that makes tracking worth anything
# ---------------------------------------------------------------------------


def test_a_theorem_promoted_from_an_assuming_proof_carries_the_debt(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-promote@example.com")
    assert assume(client, pc)[0] == 201
    proof = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")

    status, entry = promote(client, proof, "pa")
    assert status == 201, entry
    assert entry["assumes"] == ["peirce"]


def test_the_debt_survives_a_hop_no_line_mentions(db, client):
    # The load-bearing case. The second proof cites `pa` and nothing else; the
    # word "peirce" appears nowhere in its source, in its lines, or in its
    # citations. Only the stored closure knows — which is exactly the situation a
    # translation built on a library of assumed lemmas is in.
    pc, _fol, zfc = tower(db, client, "assume-transitive@example.com")
    assert assume(client, pc)[0] == 201
    first = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, first, "pa")[0] == 201

    second = make_proof(client, zfc, "(((A → B) → A) → A) [pa]")
    assert verify(client, second)["success"] is True

    status, report = provenance(client, second)
    assert status == 200, report
    assert assumed_labels(report) == ["peirce"]


def test_a_second_promotion_inherits_the_closure_rather_than_rewalking_it(db, client):
    # The storage claim behind the hop above: each entry's closure is written at
    # its own promotion, so the third entry's rows name the assumption directly
    # and reading them is one query at any depth.
    pc, _fol, _zfc = tower(db, client, "assume-closure@example.com")
    assert assume(client, pc)[0] == 201
    first = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, first, "pa")[0] == 201
    second = proved_and_published(client, pc, "(((A → B) → A) → A) [pa]")
    assert promote(client, second, "pa2")[0] == 201

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            by_label = {
                row.label: row.id
                for row in session.scalars(select(PromotedTheoremRow))
            }
            resting = set(
                session.scalars(
                    select(TheoremAssumptionRow.assumption_id).where(
                        TheoremAssumptionRow.theorem_id == by_label["pa2"]
                    )
                )
            )
            assert resting == {by_label["peirce"]}
    finally:
        engine.dispose()


def test_a_proof_resting_on_no_assumption_stores_no_closure(db, client):
    # The other half of the same claim, and the one that says the closure is a
    # measurement rather than a marker: an ordinary promotion writes no rows.
    pc, _fol, _zfc = tower(db, client, "assume-empty@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    status, entry = promote(client, proof, "id")
    assert status == 201, entry
    assert entry["assumes"] == []

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            assert session.scalars(select(TheoremAssumptionRow.theorem_id)).all() == []
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The register: what rests on what, publicly
# ---------------------------------------------------------------------------


def test_the_public_register_ranks_by_what_rests_on_each(db, client):
    # The motivating view: two debts, one of which the development has actually
    # been built on. The ranking is the roadmap.
    pc, _fol, _zfc = tower(db, client, "assume-register@example.com")
    assert assume(client, pc, label="peirce")[0] == 201
    assert assume(client, pc, label="lonely", statement="(¬¬P → P)",
                 metavariables={"P": "formula"})[0] == 201

    used = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, used, "pa")[0] == 201

    response = client.get("/api/assumptions/public")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["label"] for item in items] == ["peirce", "lonely"]
    assert [item["dependents"] for item in items] == [1, 0]
    assert items[0]["formal_system_name"]


def test_the_register_counts_entries_that_rest_on_it_transitively(db, client):
    # What "rests on" means in the register, asserted through the register.
    # `pa2` cites `pa` and nothing else — the assumption is two hops away and
    # named nowhere in its proof — so a count of *direct* citers would say one
    # here, and the register would rank a debt by how visible it is rather than
    # by how much has been built on it.
    pc, _fol, _zfc = tower(db, client, "assume-transitive-count@example.com")
    assert assume(client, pc)[0] == 201

    first = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, first, "pa")[0] == 201
    second = proved_and_published(client, pc, "(((A → B) → A) → A) [pa]")
    assert promote(client, second, "pa2")[0] == 201

    items = client.get("/api/assumptions/public").json()["items"]
    assert [(item["label"], item["dependents"]) for item in items] == [("peirce", 2)]

    detail = client.get(f"/api/formal-systems/{pc}/assumptions/peirce").json()
    assert sorted(detail["dependent_labels"]) == ["pa", "pa2"]


def test_the_register_is_readable_without_an_account(db, client):
    # A published system's gaps are public: a reader deciding whether to rest on
    # this development needs them, and they are not the owner's to withhold.
    pc, _fol, _zfc = tower(db, client, "assume-anon@example.com")
    assert assume(client, pc)[0] == 201
    client.cookies.clear()

    response = client.get("/api/assumptions/public")
    assert response.status_code == 200, response.text
    assert [item["label"] for item in response.json()["items"]] == ["peirce"]


def test_a_draft_systems_assumptions_stay_private(db, client):
    # The register is published systems only, for the reason every `/public`
    # listing is: a draft's contents are the owner's until they say otherwise.
    owner = _register_login(client, "assume-draft@example.com")
    pc, _fol, zfc = seed_tower(db, owner, published_top=False)
    assert assume(client, zfc, label="drafted")[0] == 201

    labels = [
        item["label"] for item in client.get("/api/assumptions/public").json()["items"]
    ]
    assert "drafted" not in labels


def test_one_assumption_names_the_entries_that_rest_on_it(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-detail@example.com")
    assert assume(client, pc)[0] == 201
    proof = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, proof, "pa")[0] == 201

    response = client.get(f"/api/formal-systems/{pc}/assumptions/peirce")
    assert response.status_code == 200, response.text
    assert response.json()["dependent_labels"] == ["pa"]
    assert response.json()["dependents"] == 1


# ---------------------------------------------------------------------------
# Rejections, one per guard
# ---------------------------------------------------------------------------


def test_an_assumption_may_not_take_a_label_the_library_holds(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-clash@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert assume(client, pc, label="id")[0] == 409


def test_an_assumption_may_not_take_a_rules_label(db, client):
    # A citation resolves a rule before the library, so the entry would be
    # unreachable — the same guard promotion makes, for the same reason.
    pc, _fol, _zfc = tower(db, client, "assume-rule@example.com")
    status, detail = assume(client, pc, label="MP")
    assert status == 409, detail


def test_a_ground_statement_the_grammar_cannot_read_is_refused(db, client):
    # Refused at the door rather than stored as an entry no citation could match.
    # Ground only: a *schematic* statement that parses nothing is left alone by
    # the engine — it yields a theorem that never applies, as an authored rule
    # schema does — and this route does not overrule that. See its docstring.
    pc, _fol, _zfc = tower(db, client, "assume-garbage@example.com")
    status, detail = assume(
        client, pc, statement="(((A → B) → A)", metavariables={}
    )
    assert status == 422, detail


def test_a_metavariable_over_a_sort_the_system_lacks_is_refused(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-sort@example.com")
    status, detail = assume(client, pc, metavariables={"P": "formula", "Q": "widget"})
    assert status == 422, detail


def test_a_reason_is_required(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-reason@example.com")
    response = client.post(
        f"/api/formal-systems/{pc}/assumptions",
        json={"label": "nope", "statement": PEIRCE, "reason": ""},
    )
    assert response.status_code == 422, response.text


def test_only_the_systems_owner_may_assume(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-owner@example.com")
    _register_login(client, "stranger@example.com")

    status, _ = assume(client, pc, label="theirs")
    assert status == 404


def test_provenance_of_an_unverified_proof_says_to_verify(db, client):
    # Not "it assumes nothing": nothing has resolved its citations, so the honest
    # answer is that the question cannot be asked yet.
    pc, _fol, _zfc = tower(db, client, "assume-unchecked@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, "(((A → B) → A) → A) [peirce]")

    status, _ = provenance(client, proof)
    assert status == 409


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


def test_withdrawing_an_assumption_stops_the_label_resolving(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-withdraw@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, "(((A → B) → A) → A) [peirce]")
    assert verify(client, proof)["success"] is True

    removed = client.delete(f"/api/formal-systems/{pc}/assumptions/peirce")
    assert removed.status_code == 204, removed.text
    assert verify(client, proof)["success"] is False


def test_withdrawing_clears_the_verdicts_that_rested_on_it(db, client):
    # The invalidation half: a proof that verified through the assumption must
    # not keep a standing verdict nobody would reach today.
    pc, _fol, _zfc = tower(db, client, "assume-invalidate@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, "(((A → B) → A) → A) [peirce]")
    assert verify(client, proof)["success"] is True

    client.delete(f"/api/formal-systems/{pc}/assumptions/peirce")
    detail = client.get(f"/api/proofs/{proof}").json()
    assert detail["valid"] is None


def test_a_proved_entry_cannot_be_withdrawn_through_this_route(db, client):
    # It would withdraw a theorem while leaving the proof that established it
    # pointing at nothing. Retiring a promotion is the proof's own route.
    pc, _fol, _zfc = tower(db, client, "assume-notmine@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    removed = client.delete(f"/api/formal-systems/{pc}/assumptions/id")
    assert removed.status_code == 404, removed.text


def test_withdrawing_removes_the_row_and_its_closure_edges(db, client):
    pc, _fol, _zfc = tower(db, client, "assume-cascade@example.com")
    assert assume(client, pc)[0] == 201
    client.delete(f"/api/formal-systems/{pc}/assumptions/peirce")

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            assert session.scalars(select(AssumptionRow.theorem_id)).all() == []
            assert session.scalars(select(TheoremAssumptionRow.theorem_id)).all() == []
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The honest half: a label the report cannot account for
# ---------------------------------------------------------------------------


def test_a_citation_the_walk_cannot_follow_is_reported_not_dropped(db, client):
    # `unresolved` is the guard that keeps a short list from reading as a
    # complete one, and it is asserted at the storage layer because the API's own
    # write path cannot produce one: a citation that resolves to nothing leaves
    # `proof_lines.rule` null, and withdrawing what it did resolve to clears the
    # rows outright. A corpus import can (it stores the labels a `.mm` file
    # wrote, whether or not this database holds every one of them), and this is
    # that shape: ask for the closure against a library the label is not in.
    pc, _fol, _zfc = tower(db, client, "assume-unresolved@example.com")
    assert assume(client, pc)[0] == 201
    proof = make_proof(client, pc, "(((A → B) → A) → A) [peirce]")
    verify(client, proof)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            report = rests_on(session, uuid.UUID(proof), systems=[])
            assert report.assumptions == ()
            assert report.unresolved == ("peirce",)
            assert report.complete is False
    finally:
        engine.dispose()


def test_a_rule_is_not_reported_as_an_unaccounted_citation(db, client):
    # The false-positive control on the same guard: `MP` names an inference rule,
    # which is not a dependency on anything unproved — so a proof full of them
    # must come back complete rather than as five labels nobody could follow.
    pc, _fol, _zfc = tower(db, client, "assume-rules-ok@example.com")
    proof = make_proof(client, pc, IDENTITY_PROOF)
    verify(client, proof)

    status, report = provenance(client, proof)
    assert status == 200, report
    assert report["unresolved"] == []
    assert report["complete"] is True


# ---------------------------------------------------------------------------
# The other way a proof reaches an assumption: through a cited lemma *proof*
# ---------------------------------------------------------------------------

# `L.1` is the lemma proof's conclusion; line 1 is `ax-1` over it, and modus
# ponens closes. Nothing in this source names the assumption.
VIA_LEMMA = (
    "((((A → B) → A) → A) → (B → (((A → B) → A) → A))) [ax-1]\n"
    "(B → (((A → B) → A) → A)) [MP, L.1, 1]"
)


def cite_lemma(client, proof_id: str, lemma_id: str, alias: str = "L") -> None:
    response = client.put(
        f"/api/proofs/{proof_id}/references",
        json={"references": [{"referenced_proof_id": lemma_id, "alias": alias}]},
    )
    assert response.status_code == 200, response.text


def test_a_debt_reached_through_a_cited_lemma_proof_is_not_lost(db, client):
    # A proof reaches the library through two doors: a rule label its lines
    # resolve, and a *lemma proof* whose lines it cites as `[L.1]`. The second
    # leaves no label behind — `proof_lines.rule` here says `ax-1` and `MP` — so
    # a report that read only the first would call this proof unconditional.
    pc, _fol, _zfc = tower(db, client, "assume-via-lemma@example.com")
    assert assume(client, pc)[0] == 201
    lemma = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")

    proof = make_proof(client, pc, VIA_LEMMA)
    cite_lemma(client, proof, lemma)
    assert verify(client, proof)["success"] is True

    status, report = provenance(client, proof)
    assert status == 200, report
    assert assumed_labels(report) == ["peirce"]
    assert report["complete"] is True


def test_a_promotion_stores_a_debt_reached_through_a_lemma(db, client):
    # The consequential half of the case above: the closure is *written* here, so
    # a miss is permanent — everything promoted on top of this entry would
    # inherit an empty set and report itself unconditional forever.
    pc, _fol, _zfc = tower(db, client, "assume-lemma-promote@example.com")
    assert assume(client, pc)[0] == 201
    lemma = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")

    proof = make_proof(client, pc, VIA_LEMMA)
    cite_lemma(client, proof, lemma)
    publish(client, proof)

    status, entry = promote(client, proof, "viaL")
    assert status == 201, entry
    assert entry["assumes"] == ["peirce"]


def test_reading_the_proof_back_still_says_the_theorem_is_conditional(db, client):
    # `POST /promote` returns the debt; the *detail* read is a different code
    # path, and `assumes` defaults to empty — so a caller that forgot to fill it
    # would serialize a conditional theorem as an unconditional one, which is
    # the one thing this surface exists to prevent (found in review).
    pc, _fol, _zfc = tower(db, client, "assume-detail-read@example.com")
    assert assume(client, pc)[0] == 201
    proof = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, proof, "pa")[0] == 201

    detail = client.get(f"/api/proofs/{proof}").json()
    assert detail["theorem"]["label"] == "pa"
    assert detail["theorem"]["assumes"] == ["peirce"]


def test_a_proof_establishing_nothing_assumed_reads_back_unconditional(db, client):
    # The control: the field is a measurement, not a marker.
    pc, _fol, _zfc = tower(db, client, "assume-detail-clean@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert client.get(f"/api/proofs/{proof}").json()["theorem"]["assumes"] == []


def test_an_assumption_with_dependents_cannot_be_withdrawn(db, client):
    # Retiring an ordinary entry invalidates the proofs citing *its* label, which
    # is the set that rested on it. An assumption's dependents are not that set:
    # an entry promoted from a proof that cited this is citable under a different
    # label, so the walk never reaches the proofs resting on it at one remove —
    # while the row cascade empties that entry's closure, leaving it standing and
    # reporting itself unconditional (found in review).
    pc, _fol, _zfc = tower(db, client, "assume-withdraw-blocked@example.com")
    assert assume(client, pc)[0] == 201
    proof = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, proof, "pa")[0] == 201

    refused = client.delete(f"/api/formal-systems/{pc}/assumptions/peirce")
    assert refused.status_code == 409, refused.text
    assert "'pa'" in refused.json()["detail"]

    # And the debt is still there to be found, rather than half-removed.
    assert client.get(f"/api/formal-systems/{pc}/assumptions/peirce").json()[
        "dependent_labels"
    ] == ["pa"]


def test_withdrawing_works_once_the_dependent_entry_is_retired(db, client):
    # The refusal above is a gate, not a dead end.
    pc, _fol, _zfc = tower(db, client, "assume-withdraw-after@example.com")
    assert assume(client, pc)[0] == 201
    proof = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, proof, "pa")[0] == 201

    retired = client.delete(f"/api/proofs/{proof}/promote")
    assert retired.status_code == 204, retired.text
    removed = client.delete(f"/api/formal-systems/{pc}/assumptions/peirce")
    assert removed.status_code == 204, removed.text


# ---------------------------------------------------------------------------
# Discharge: promoting a proof under the assumption's own label
# ---------------------------------------------------------------------------
#
# Withdrawal is refused while anything rests on an assumption, which leaves
# exactly one way to retire a well-used one: prove it. Discharging replaces the
# debt with its warrant, and the entries that rested on it inherit whatever the
# warrant rests on — one hop further down — rather than silently losing the
# record or keeping a pointer to a row that is gone.

def discharging_proof(client, system_id: str, label: str = "peirce") -> str:
    """A proof of the assumed statement — cheated, and deliberately so.

    The point under test is what *discharge* does to the rows, and deriving
    Peirce's law from the Łukasiewicz axioms would be ninety lines that test the
    checker instead. So the warrant is a second assumption under another label,
    cited once: the proof genuinely stands, genuinely concludes the statement,
    and genuinely rests on something unproved — which is the *interesting* case,
    since it is what makes the dependents inherit rather than come out clean.
    """
    assert assume(
        client,
        system_id,
        label="peirce-lemma",
        reason="Stands in for the real derivation; see the module note.",
    )[0] == 201
    return proved_and_published(
        client, system_id, "(((A → B) → A) → A) [peirce-lemma]"
    )


def test_promoting_under_an_assumed_label_discharges_it(db, client):
    pc, _fol, _zfc = tower(db, client, "discharge-basic@example.com")
    assert assume(client, pc)[0] == 201
    warrant = discharging_proof(client, pc)

    status, entry = promote(client, warrant, "peirce", {"A": "formula", "B": "formula"})
    assert status == 201, entry
    assert entry["discharged"] is True
    assert entry["proved_by_id"] == warrant

    # The debt is gone from the register: the label now names a proved theorem.
    labels = [
        item["label"]
        for item in client.get(f"/api/formal-systems/{pc}/assumptions").json()
    ]
    assert labels == ["peirce-lemma"]


def test_what_rested_on_it_inherits_the_warrants_own_debts(db, client):
    # The load-bearing case. `pa` rested on `peirce`; `peirce` is now proved, but
    # by a proof that itself rests on `peirce-lemma`. So `pa` must come out
    # resting on `peirce-lemma` — not on `peirce` (proved), and not on nothing.
    pc, _fol, _zfc = tower(db, client, "discharge-inherit@example.com")
    assert assume(client, pc)[0] == 201
    resting = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")
    assert promote(client, resting, "pa")[0] == 201

    warrant = discharging_proof(client, pc)
    assert promote(client, warrant, "peirce", {"A": "formula", "B": "formula"})[0] == 201

    detail = client.get(f"/api/proofs/{resting}").json()
    assert detail["theorem"]["assumes"] == ["peirce-lemma"]


def test_a_discharge_by_an_unconditional_proof_leaves_dependents_clean(db, client):
    # The control on the case above: when the warrant rests on nothing, the debt
    # is paid off outright and what rested on it comes back unconditional.
    pc, _fol, _zfc = tower(db, client, "discharge-clean@example.com")
    assert assume(
        client, pc, label="triv", statement="(P → P)", metavariables={"P": "formula"}
    )[0] == 201
    resting = proved_and_published(client, pc, "(A → A) [triv]")
    assert promote(client, resting, "usedit")[0] == 201

    warrant = proved_and_published(client, pc, IDENTITY_PROOF)
    status, entry = promote(client, warrant, "triv", {"P": "formula"})
    assert status == 201, entry
    assert entry["discharged"] is True
    assert entry["assumes"] == []

    assert client.get(f"/api/proofs/{resting}").json()["theorem"]["assumes"] == []
    assert client.get("/api/assumptions/public").json()["items"] == []


def test_a_proof_of_something_else_does_not_discharge(db, client):
    # The guard that keeps "paid the debt" and "replaced the entry with a
    # different claim" apart, since from here they look identical.
    pc, _fol, _zfc = tower(db, client, "discharge-mismatch@example.com")
    assert assume(client, pc)[0] == 201
    other = proved_and_published(client, pc, IDENTITY_PROOF)

    status, detail = promote(client, other, "peirce", {"P": "formula"})
    assert status == 409, detail
    assert "does not establish what it assumes" in detail["detail"]

    # And nothing moved: the assumption is intact.
    assert client.get(f"/api/formal-systems/{pc}/assumptions/peirce").json()["label"] == (
        "peirce"
    )


def test_a_proof_that_assumes_what_it_claims_does_not_discharge(db, client):
    # Circular: left alone it would resolve its own citation to the entry
    # replacing it and record an empty closure, laundering the assumption into an
    # unconditional theorem.
    pc, _fol, _zfc = tower(db, client, "discharge-circular@example.com")
    assert assume(client, pc)[0] == 201
    circular = proved_and_published(client, pc, "(((A → B) → A) → A) [peirce]")

    status, detail = promote(client, circular, "peirce", {"A": "formula", "B": "formula"})
    assert status == 409, detail
    assert "does not discharge it" in detail["detail"]


def test_discharging_needs_the_statements_to_match_not_merely_the_shape(db, client):
    # Held schematic on the assumption and ground on the proof is a *weaker*
    # theorem under the same label, which every schematic citation of it would
    # stop resolving against. α-equality covers the naming; it does not paper
    # over the difference between "for all φ" and "for this one".
    pc, _fol, _zfc = tower(db, client, "discharge-ground@example.com")
    assert assume(client, pc)[0] == 201
    warrant = discharging_proof(client, pc)

    status, detail = promote(client, warrant, "peirce")
    assert status == 409, detail


def test_an_ancestors_assumption_is_shadowed_rather_than_discharged(db, client):
    # A descendant proving it settles nothing for the ancestor, which still
    # asserts it and whose other descendants still rest on it. Shadowing is the
    # existing behaviour and stays exactly that.
    pc, _fol, zfc = tower(db, client, "discharge-ancestor@example.com")
    assert assume(client, pc)[0] == 201
    warrant = proved_and_published(client, zfc, "(((A → B) → A) → A) [peirce]")

    status, entry = promote(client, warrant, "peirce")
    assert status == 201, entry
    assert entry["discharged"] is False
    assert entry["formal_system_id"] == zfc

    # The ancestor's assumption is untouched.
    assert [
        item["label"]
        for item in client.get(f"/api/formal-systems/{pc}/assumptions").json()
    ] == ["peirce"]


def test_a_discharged_assumption_can_then_be_withdrawn_downstream(db, client):
    # The whole point of the feature, end to end: withdrawal was refused while
    # anything rested on the assumption, and discharging is the way out that does
    # not delete anyone's work.
    pc, _fol, _zfc = tower(db, client, "discharge-endtoend@example.com")
    assert assume(
        client, pc, label="triv", statement="(P → P)", metavariables={"P": "formula"}
    )[0] == 201
    resting = proved_and_published(client, pc, "(A → A) [triv]")
    assert promote(client, resting, "usedit")[0] == 201

    refused = client.delete(f"/api/formal-systems/{pc}/assumptions/triv")
    assert refused.status_code == 409, refused.text

    warrant = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, warrant, "triv", {"P": "formula"})[0] == 201

    # No longer an assumption at all, so there is nothing left to withdraw.
    assert client.get(f"/api/formal-systems/{pc}/assumptions/triv").status_code == 404


# `ax-5` is the tower's one rule with a proviso, so a schematic promotion over a
# proof that cites it carries `not occurs(...)` into the entry.
VACUOUS = "(A → ∀y A) [ax-5]"


def test_a_warrant_carrying_a_new_proviso_does_not_discharge(db, client):
    # A distinct-variable condition the debt never had makes the warrant
    # *narrower*: it refuses instances the assumption allowed, so what lands is
    # not the theorem the dependents were written against — and after they
    # inherit its closure they would read as unconditional besides (found in
    # review).
    _pc, fol, _zfc = tower(db, client, "discharge-proviso@example.com")
    assert assume(
        client,
        fol,
        label="vacuous",
        statement="(P → ∀x P)",
        metavariables={"P": "formula", "x": "term"},
    )[0] == 201
    warrant = proved_and_published(client, fol, VACUOUS)

    status, detail = promote(
        client, warrant, "vacuous", {"A": "formula", "y": "term"}
    )
    assert status == 409, detail
    assert "carries provisos" in detail["detail"]

    # Nothing moved: the assumption is intact and still the thing citations reach.
    assert client.get(f"/api/formal-systems/{fol}/assumptions/vacuous").status_code == 200


def test_discharging_clears_what_the_assumption_was_standing_in_for(db, client):
    # An edge's obligation may be discharged by a theorem, and the FK is
    # ON DELETE SET NULL — so losing this row takes the edge down with it, and
    # the proofs that resolved *across* it cited the source's labels rather than
    # this one, which the label walk never reaches. `_retire_promotion` calls
    # this for exactly that reason; the first cut of discharge did not.
    #
    # Pinned by the call rather than by building a tower of related systems: what
    # went wrong was an omission, and the omission is what this catches.
    pc, _fol, _zfc = tower(db, client, "discharge-edges@example.com")
    assert assume(
        client, pc, label="triv", statement="(P → P)", metavariables={"P": "formula"}
    )[0] == 201
    assumption_id = client.get(f"/api/formal-systems/{pc}/assumptions/triv").json()["id"]

    cleared: list[str] = []
    original = proofs_router.invalidate_warranted_edges

    async def record(session, theorem_id):
        cleared.append(str(theorem_id))
        await original(session, theorem_id)

    proofs_router.invalidate_warranted_edges = record
    try:
        warrant = proved_and_published(client, pc, IDENTITY_PROOF)
        assert promote(client, warrant, "triv", {"P": "formula"})[0] == 201
    finally:
        proofs_router.invalidate_warranted_edges = original

    assert assumption_id in cleared
