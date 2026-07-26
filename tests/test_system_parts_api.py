"""Per-object CRUD for a system's parts, end to end.

The headline test builds a whole (ZFC-shaped) system through the child endpoints
and then validates that it compiles — proving a system can be authored via the
API with no `.edi`. The rest cover the per-type mechanics: sort resolution,
template/regex exclusivity, wholesale binding replacement, reorder, cascade, and
owner scoping.
"""

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.auth.backend as backend
from app.db import (
    Base,
    FormalSystem,
    Proof,
    ProofLineAntecedentRow,
    ProofLineRow,
    SideConditionRow,
    TermChildRow,
    TermRow,
)
from app.db.models import OAuthAccount, User
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
from app.main import app

_TABLES = [
    m.__table__
    for m in (
        User, OAuthAccount, FormalSystem, BracketRow, SymbolRow,
        ProductionBindingRow, ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow,
        SideConditionRow,
        # A part edit invalidates the system's proofs and their stored structure
        # (app/db/proofs_mapping.discard_system_checks), so those tables must
        # exist even though this module authors no proofs.
        Proof, ProofLineRow, ProofLineAntecedentRow, TermRow, TermChildRow,
    )
]


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    db_path = tmp_path / "parts.db"

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine, tables=_TABLES)
    sync_engine.dispose()

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)

    @event.listens_for(async_engine.sync_engine, "connect")
    def _fk_pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_session, None)


def _login(client: TestClient, email: str, password: str = "password123") -> None:
    assert client.post("/api/auth/register", json={"email": email, "password": password}).status_code == 201
    assert client.post("/api/auth/login", data={"username": email, "password": password}).status_code == 204


def _new_system(client: TestClient, name: str = "Sys") -> str:
    response = client.post("/api/formal-systems", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _post(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Headline: build a whole system through the child endpoints, then validate it
# ---------------------------------------------------------------------------


def _build_zfc(client: TestClient, sid: str) -> None:
    base = f"/api/formal-systems/{sid}"
    _post(client, f"{base}/brackets", {"opening": "(", "closing": ")"})
    _post(client, f"{base}/sorts", {"name": "term"})
    _post(client, f"{base}/sorts", {"name": "formula"})

    _post(client, f"{base}/productions", {"name": "variable", "sort": "term", "regex": "[a-z][a-z0-9]*"})
    _post(client, f"{base}/productions", {
        "name": "membership", "sort": "formula", "template": "s ∈ t",
        "bindings": [{"var": "s", "sort": "term"}, {"var": "t", "sort": "term"}],
    })
    _post(client, f"{base}/productions", {
        "name": "equality", "sort": "formula", "template": "s = t",
        "bindings": [{"var": "s", "sort": "term"}, {"var": "t", "sort": "term"}],
    })
    _post(client, f"{base}/productions", {
        "name": "implication", "sort": "formula", "template": "(p → q)",
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
    })

    _post(client, f"{base}/line-types", {
        "name": "statement", "shape": "<formula> [<reference>]", "logical_sort": "formula",
        "parts": [{"name": "reference", "regex": "[A-Za-z0-9 ,]+"}],
    })

    _post(client, f"{base}/axioms", {"label": "EXT", "name": "extensionality", "formula": "∀x x = x"})

    _post(client, f"{base}/rules", {
        "label": "HYP", "name": "hypothesis", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    _post(client, f"{base}/rules", {
        "label": "MP", "name": "modus ponens", "deduction": "q",
        "antecedents": ["p", "(p → q)"],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
    })

    _post(client, f"{base}/definitions", {
        "sort": "formula", "name": "subset", "higher": "x ⊆ y", "lower": "(x = y → x = y)",
        "bindings": [{"var": "x", "sort": "variable"}, {"var": "y", "sort": "variable"}],
    })


def test_build_a_system_through_endpoints_and_validate(client):
    _login(client, "ada@example.com")
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)

    # The assembled system compiles.
    validation = client.post(f"/api/formal-systems/{sid}/validate").json()
    assert validation["success"] is True, validation
    assert validation["inference_rule_count"] == 2          # HYP, MP
    assert validation["line_type_count"] == 2               # statement + EXT axiom line type

    # The full aggregate reflects everything created.
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert [s["name"] for s in detail["sorts"]] == ["term", "formula"]
    assert [p["name"] for p in detail["productions"]] == [
        "variable", "membership", "equality", "implication"
    ]
    assert [r["label"] for r in detail["rules"]] == ["HYP", "MP"]
    assert detail["definitions"][0]["higher"] == "x ⊆ y"


# ---------------------------------------------------------------------------
# A published system must stay compilable across child edits
# ---------------------------------------------------------------------------


def _build_published_zfc(client: TestClient) -> str:
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)
    assert client.patch(f"/api/formal-systems/{sid}", json={"published": True}).status_code == 200
    return sid


def test_editing_a_published_system_part_is_rejected(client):
    # A published system is frozen: its compiled behaviour is what published
    # proofs were verified against, so no part may be edited — even a
    # compile-preserving edit is refused (409), and it is left unchanged.
    _login(client, "ada@example.com")
    sid = _build_published_zfc(client)
    line = client.get(f"/api/formal-systems/{sid}").json()["lines"][0]

    resp = client.patch(
        f"/api/formal-systems/{sid}/line-types/{line['id']}", json={"shape": "assertion"}
    )
    assert resp.status_code == 409, resp.text

    after = client.get(f"/api/formal-systems/{sid}").json()["lines"][0]
    assert after["shape"] == line["shape"]


def test_all_part_mutations_on_a_published_system_are_rejected(client):
    # The freeze covers every mutation kind, not just breaking edits: create and
    # delete on a published system are both 409.
    _login(client, "ada@example.com")
    sid = _build_published_zfc(client)

    assert client.post(
        f"/api/formal-systems/{sid}/brackets", json={"opening": "[", "closing": "]"}
    ).status_code == 409
    definition_id = client.get(f"/api/formal-systems/{sid}").json()["definitions"][0]["id"]
    assert (
        client.delete(f"/api/formal-systems/{sid}/definitions/{definition_id}").status_code == 409
    )


def test_a_draft_still_tolerates_a_non_compiling_edit(client):
    # Drafts stay draft-tolerant: the same breaking edit that a published system
    # rejects is persisted on a draft (POST /validate reports the breakage).
    _login(client, "ada@example.com")
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)  # left unpublished
    line = client.get(f"/api/formal-systems/{sid}").json()["lines"][0]

    resp = client.patch(
        f"/api/formal-systems/{sid}/line-types/{line['id']}", json={"shape": "assertion"}
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"/api/formal-systems/{sid}").json()["lines"][0]["shape"] == "assertion"
    assert client.post(f"/api/formal-systems/{sid}/validate").json()["success"] is False


# ---------------------------------------------------------------------------
# Rule side-conditions round-trip through the child endpoints
# ---------------------------------------------------------------------------


def test_rule_side_conditions_round_trip_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "RImp", "name": "refl imp", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["not occurs(p, q)", "equal(p, q)"],
    })
    assert rule["side_conditions"] == ["not occurs(p, q)", "equal(p, q)"]

    # Read back through the aggregate detail.
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["not occurs(p, q)", "equal(p, q)"]

    # Update replaces the provisos wholesale, including a multi-node tree (an
    # update that deletes the old tree and inserts a new one in one flush).
    updated = client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}",
        json={"side_conditions": ["not occurs(q, p)", "equal(p, q)"]},
    )
    assert updated.status_code == 200
    assert updated.json()["side_conditions"] == ["not occurs(q, p)", "equal(p, q)"]
    # A single-node replacement and an empty list that clears the tree.
    single = client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": ["equal(p, q)"]}
    )
    assert single.json()["side_conditions"] == ["equal(p, q)"]
    cleared = client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": []}
    )
    assert cleared.json()["side_conditions"] == []


def test_rule_matching_kind_round_trips_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "miustr"})

    # Defaults to structural when omitted.
    default_rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "HYP", "name": "hyp", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "miustr"}],
    })
    assert default_rule["matching"] == "structural"

    # A string-rewriting rule stores and reads back its kind.
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R2", "name": "double", "deduction": "Mxx", "antecedents": ["Mx"],
        "bindings": [{"var": "x", "sort": "miustr"}], "matching": "string",
    })
    assert rule["matching"] == "string"
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert {r["label"]: r["matching"] for r in detail["rules"]} == {
        "HYP": "structural", "R2": "string",
    }

    # PATCH can flip the kind, and only the kind.
    flipped = client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}", json={"matching": "structural"}
    )
    assert flipped.status_code == 200
    assert flipped.json()["matching"] == "structural"
    assert flipped.json()["deduction"] == "Mxx"


def test_rule_subproof_round_trips_through_the_api(client):
    # A discharge rule's subproof persists and reads back; a PATCH can clear it.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    created = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "CP", "name": "conditional proof", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "subproof": {"derive": "q", "assume": "p"},
    })
    assert created["subproof"] == {"derive": "q", "assume": "p", "fresh": None}

    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["rules"][0]["subproof"]["assume"] == "p"

    # PATCH clears the subproof back to a plain rule.
    cleared = client.patch(
        f"/api/formal-systems/{sid}/rules/{created['id']}", json={"subproof": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["subproof"] is None


def test_rule_subproof_requires_exactly_one_opener_via_api(client):
    # The Subproof model enforces exactly one of assume/fresh, so both-or-neither
    # is a 422 rather than a build-time surprise.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    both = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "CP", "name": "cp", "deduction": "(p → q)",
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "subproof": {"derive": "q", "assume": "p", "fresh": "x"},
    })
    assert both.status_code == 422

    neither = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "CP", "name": "cp", "deduction": "(p → q)",
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "subproof": {"derive": "q"},
    })
    assert neither.status_code == 422


def test_discharge_rule_cannot_carry_antecedents_or_side_conditions_via_api(client):
    # The discharge check ignores line antecedents and side-conditions, so the
    # API rejects the pairing on create and when a PATCH flips a plain rule into
    # a conflicting discharge rule (checked across the final combined state).
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    binds = [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}]

    with_antecedents = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "CP", "name": "cp", "deduction": "(p → q)", "antecedents": ["p"],
        "bindings": binds, "subproof": {"derive": "q", "assume": "p"},
    })
    assert with_antecedents.status_code == 422

    # A plain rule with an antecedent, then PATCHed to add a subproof, is caught.
    plain = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "reit", "deduction": "p", "antecedents": ["p"],
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    conflicted = client.patch(
        f"/api/formal-systems/{sid}/rules/{plain['id']}",
        json={"subproof": {"derive": "p", "assume": "p"}},
    )
    assert conflicted.status_code == 422


def test_rule_allow_extra_antecedents_round_trips_through_the_api(client):
    # The flag persists on the write response and the aggregate detail, defaults
    # to False when omitted, and PATCH flips it back off.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    binds = [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}]

    extra = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "MPX", "name": "mpx", "deduction": "q",
        "antecedents": ["p", "(p → q)"], "bindings": binds,
        "allow_extra_antecedents": True,
    })
    assert extra["allow_extra_antecedents"] is True

    # Omitting the field on create leaves it off (an exact citation).
    plain = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "MP", "name": "mp", "deduction": "q",
        "antecedents": ["p", "(p → q)"], "bindings": binds,
    })
    assert plain["allow_extra_antecedents"] is False

    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert {r["label"]: r["allow_extra_antecedents"] for r in detail["rules"]} == {
        "MPX": True, "MP": False
    }

    # A metadata-only PATCH (model_fields_set excludes the flag) preserves it.
    assert client.patch(
        f"/api/formal-systems/{sid}/rules/{extra['id']}", json={"name": "renamed"}
    ).json()["allow_extra_antecedents"] is True

    assert client.patch(
        f"/api/formal-systems/{sid}/rules/{extra['id']}",
        json={"allow_extra_antecedents": False},
    ).json()["allow_extra_antecedents"] is False


def test_discharge_rule_may_allow_extra_antecedents_inertly_via_api(client):
    # A discharge rule cites exactly one subproof opener, so the discharge check
    # never consults `allow_extra_antecedents`. Unlike antecedents/side-conditions
    # (whose loss would drop a soundness constraint, hence the 422 above), an
    # ignored allowance is only ever stricter, so the pairing is stored as-is
    # rather than rejected.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    binds = [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}]

    both = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "CP", "name": "cp", "deduction": "(p → q)", "bindings": binds,
        "subproof": {"derive": "q", "assume": "p"}, "allow_extra_antecedents": True,
    })
    assert both["allow_extra_antecedents"] is True
    assert both["subproof"] == {"derive": "q", "assume": "p", "fresh": None}

    # An extra-antecedent rule later PATCHed into a discharge rule keeps the flag.
    plain = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "MPX", "name": "mpx", "deduction": "q", "bindings": binds,
        "allow_extra_antecedents": True,
    })
    patched = client.patch(
        f"/api/formal-systems/{sid}/rules/{plain['id']}",
        json={"subproof": {"derive": "q", "assume": "p"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["allow_extra_antecedents"] is True


def test_string_rule_cannot_carry_side_conditions_via_api(client):
    # The string path has no term binding to evaluate a proviso against, so the
    # API rejects the pairing (create and both PATCH directions) rather than
    # store a rule whose side-conditions would be silently ignored.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    # Create with both is a 422.
    both = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "matching": "string", "side_conditions": ["equal(p, p)"],
    })
    assert both.status_code == 422

    # A structural rule with provisos is fine; flipping it to string then 422s.
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["equal(p, p)"],
    })
    flip = client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}", json={"matching": "string"}
    )
    assert flip.status_code == 422

    # And adding provisos to an existing string rule is likewise a 422.
    string_rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "S", "name": "s", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}], "matching": "string",
    })
    add = client.patch(
        f"/api/formal-systems/{sid}/rules/{string_rule['id']}",
        json={"side_conditions": ["equal(p, p)"]},
    )
    assert add.status_code == 422


def test_string_rewriting_system_authored_via_api_verifies_a_proof(client):
    # Author Hofstadter's MIU (a string-rewriting system) entirely through the
    # child endpoints, then check a real derivation against it — proving the
    # matching="string" path works end to end from the API down to the checker.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    base = f"/api/formal-systems/{sid}"

    _post(client, f"{base}/sorts", {"name": "miustr"})
    _post(client, f"{base}/productions", {"name": "raw", "sort": "miustr", "regex": "[MIU]+"})
    _post(client, f"{base}/line-types", {
        "name": "theorem", "shape": "<miustr> [<reference>]", "logical_sort": "miustr",
        "parts": [{"name": "reference", "regex": "[A-Za-z0-9 ,]+"}],
    })
    _post(client, f"{base}/axioms", {"label": "AX", "name": "mi axiom", "formula": "MI"})
    for label, name, ant, ded, variables in [
        ("R1", "rule one", ["xI"], "xIU", ["x"]),
        ("R2", "rule two", ["Mx"], "Mxx", ["x"]),
        ("R3", "rule three", ["xIIIy"], "xUy", ["x", "y"]),
        ("R4", "rule four", ["xUUy"], "xy", ["x", "y"]),
    ]:
        _post(client, f"{base}/rules", {
            "label": label, "name": name, "deduction": ded, "antecedents": ant,
            "bindings": [{"var": v, "sort": "miustr"} for v in variables],
            "matching": "string",
        })

    good = client.post(f"{base}/verify", json={
        "proof_text": "MI\nMII [R2, 1]\nMIIII [R2, 2]\nMUI [R3, 3]"
    })
    assert good.status_code == 200, good.text
    assert good.json()["success"] is True

    bad = client.post(f"{base}/verify", json={"proof_text": "MI\nMIII [R2, 1]"})
    assert bad.json()["success"] is False


def test_unknown_rule_matching_kind_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}], "matching": "bogus",
    })
    assert response.status_code == 422


def test_malformed_rule_side_condition_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["bogus(p, q)"],
    })
    assert response.status_code == 422


def test_rule_or_proviso_round_trips_through_the_api(client):
    # A disjunctive proviso (`A or B`) is accepted and read back verbatim.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "DIS", "name": "disj", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q) or not occurs(p, q)"],
    })
    assert rule["side_conditions"] == ["equal(p, q) or not occurs(p, q)"]
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["equal(p, q) or not occurs(p, q)"]


def test_rule_member_proviso_round_trips_through_the_api(client):
    # `member(x, sort)` names a sort argument; it round-trips like `atom`/`disjoint`.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["member(p, formula)"],
    })
    assert rule["side_conditions"] == ["member(p, formula)"]
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["member(p, formula)"]


def test_member_proviso_over_unknown_sort_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["member(p, nope)"],  # `nope` is not a sort of the system
    })
    assert response.status_code == 422


def test_rule_term_argument_proviso_round_trips_and_validates(client):
    # A literal-term argument (here the compound `(p → p)`, using a production and
    # the metavariable `p`) is accepted, read back verbatim, and compiles.
    _login(client, "ada@example.com")
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "TQ", "name": "term arg", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(q, (p → p))"],
    })
    assert rule["side_conditions"] == ["equal(q, (p → p))"]
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert next(r for r in detail["rules"] if r["label"] == "TQ")["side_conditions"] == [
        "equal(q, (p → p))"
    ]
    assert client.post(f"/api/formal-systems/{sid}/validate").json()["success"] is True


def test_undeclared_argument_is_accepted_as_a_term_not_rejected_at_write(client):
    # An argument that isn't a declared metavariable is now a *literal term*, so the
    # write is draft-tolerant (201) rather than an early 422 — a term that doesn't
    # parse is caught by POST /validate, like any other draft breakage.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],  # q is undeclared → a term
        "side_conditions": ["equal(p, q)"],
    })
    assert response.status_code == 201


def test_definition_binding_and_proviso_updated_together(client):
    # A single PATCH that adds a binding AND a proviso referencing it must
    # succeed: bindings are applied before the condition is validated, so the
    # proviso is checked against the new binding set, not the stale one.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}],
    })
    updated = client.patch(f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "condition": "disjoint(x, y)",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["condition"] == "disjoint(x, y)"


def test_binding_only_patch_that_orphans_a_proviso_metavar_is_422(client):
    # Dropping a binding a stored proviso still names must be rejected even though
    # the proviso itself isn't in the PATCH — otherwise the rule persists malformed
    # and blows up in the kernel when applied.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q)"],
    })
    # PATCH bindings only, dropping q — the stored `equal(p, q)` now names an
    # undeclared metavariable.
    orphaning = client.patch(f"/api/formal-systems/{sid}/rules/{rule['id']}", json={
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    assert orphaning.status_code == 422

    # A binding-only PATCH that keeps every named metavariable still succeeds.
    ok = client.patch(f"/api/formal-systems/{sid}/rules/{rule['id']}", json={
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
    })
    assert ok.status_code == 200


def test_blank_rule_side_condition_is_rejected_not_dropped(client):
    # A blank proviso line is a malformed input, not a silent no-op: reject it
    # rather than storing the rule with the blank quietly discarded.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/api/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q)", ""],
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Definition provisos: the structured `provisos` surface (D0), at parity with
# a rule's `side_conditions`, plus back-compat with the old `condition` string.
# ---------------------------------------------------------------------------


def _defn_system(client: TestClient) -> str:
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    return sid


def test_definition_fresh_round_trips_through_the_api(client):
    # The `fresh` clause (the defining form's bound variables) persists and reads
    # back like bindings, both on the write response and the aggregate detail.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "subset", "higher": "x sub y", "lower": "all z . stuff",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "fresh": [{"var": "z", "sort": "term"}],
    })
    assert defn["fresh"] == [{"var": "z", "sort": "term"}]
    assert client.get(f"/api/formal-systems/{sid}").json()["definitions"][0]["fresh"] == [
        {"var": "z", "sort": "term"}
    ]

    # PATCH replaces the fresh list wholesale; an empty list clears it.
    updated = client.patch(f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={
        "fresh": [{"var": "z", "sort": "term"}, {"var": "w", "sort": "term"}],
    })
    assert updated.json()["fresh"] == [
        {"var": "z", "sort": "term"}, {"var": "w", "sort": "term"}
    ]
    assert client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"fresh": []}
    ).json()["fresh"] == []


def test_definition_patch_omitting_fresh_leaves_it_unchanged(client):
    # A metadata-only PATCH (model_fields_set excludes `fresh`) preserves the
    # stored bound variables, exactly like bindings.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "fresh": [{"var": "z", "sort": "term"}],
    })
    renamed = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"name": "renamed"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["fresh"] == [{"var": "z", "sort": "term"}]


def test_definition_label_round_trips_through_the_api(client):
    # The citation `label` persists on the write response and the aggregate detail,
    # PATCH changes it, a metadata-only PATCH leaves it alone, and a null PATCH
    # clears it (an unnamed definition, cited only via the generic `[Def, line]`).
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "subset", "higher": "x sub y", "lower": "x in y",
        "label": "sub",
    })
    assert defn["label"] == "sub"
    assert client.get(f"/api/formal-systems/{sid}").json()["definitions"][0]["label"] == "sub"

    assert client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"label": "subseteq"}
    ).json()["label"] == "subseteq"

    # A metadata-only PATCH (model_fields_set excludes `label`) preserves it.
    assert client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"name": "renamed"}
    ).json()["label"] == "subseteq"

    # An explicit null clears the label back to unnamed.
    assert client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"label": None}
    ).json()["label"] is None


def test_definition_fresh_over_unknown_sort_is_rejected(client):
    # A fresh var naming a sort the system doesn't declare is rejected at write
    # time (400, the same _resolve_symbol path as bindings), not a 500 or a
    # silently-dropped row.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    response = client.post(f"/api/formal-systems/{sid}/definitions", json={
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "fresh": [{"var": "z", "sort": "no_such_sort"}],
    })
    assert response.status_code == 400


def test_definition_provisos_round_trip_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["not occurs(x, y)", "disjoint(x, y)"],
    })
    assert defn["provisos"] == ["not occurs(x, y)", "disjoint(x, y)"]
    # The deprecated `condition` view is the same tree, `;`-joined.
    assert defn["condition"] == "not occurs(x, y) ; disjoint(x, y)"

    # Read back through the aggregate detail.
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["definitions"][0]["provisos"] == ["not occurs(x, y)", "disjoint(x, y)"]

    # PATCH replaces the provisos wholesale (delete old tree, insert new in one flush).
    updated = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}",
        json={"provisos": ["not occurs(y, x)", "disjoint(x, y)"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["provisos"] == ["not occurs(y, x)", "disjoint(x, y)"]
    # A single-node replacement, then an empty list that clears the tree.
    single = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"provisos": ["disjoint(x, y)"]}
    )
    assert single.json()["provisos"] == ["disjoint(x, y)"]
    assert single.json()["condition"] == "disjoint(x, y)"
    cleared = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"provisos": []}
    )
    assert cleared.json()["provisos"] == []
    assert cleared.json()["condition"] is None


def test_definition_condition_input_still_works_and_reads_back_as_provisos(client):
    # A pre-D0 client sending the old `;`-joined `condition` keeps working, and the
    # stored tree reads back through the new `provisos` surface too.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "condition": "not occurs(x, y) ; disjoint(x, y)",
    })
    assert defn["condition"] == "not occurs(x, y) ; disjoint(x, y)"
    assert defn["provisos"] == ["not occurs(x, y)", "disjoint(x, y)"]

    # A PATCH sending only `condition` still rewrites the tree.
    updated = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"condition": "disjoint(x, y)"}
    )
    assert updated.json()["provisos"] == ["disjoint(x, y)"]


def test_definition_provisos_win_over_condition_when_both_sent(client):
    # When a client sends both, the structured `provisos` is authoritative.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["disjoint(x, y)"],
        "condition": "not occurs(x, y)",
    })
    assert defn["provisos"] == ["disjoint(x, y)"]
    assert defn["condition"] == "disjoint(x, y)"


def test_definition_or_proviso_round_trips_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["occurs(x, y) or equal(x, y)"],
    })
    assert defn["provisos"] == ["occurs(x, y) or equal(x, y)"]


def test_malformed_definition_proviso_is_422(client):
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    response = client.post(f"/api/formal-systems/{sid}/definitions", json={
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}],
        "provisos": ["not a real predicate(x)"],
    })
    assert response.status_code == 422


def test_metadata_only_patch_preserves_the_stored_provisos(client):
    # The crux of the provisos/condition dispatch: a PATCH that touches neither
    # field (here, a rename) must leave the stored proviso tree untouched. Guards
    # the model_fields_set-vs-all-fields distinction the write path hinges on.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["not occurs(x, y)", "disjoint(x, y)"],
    })
    renamed = client.patch(
        f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={"name": "renamed"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed"
    assert renamed.json()["provisos"] == ["not occurs(x, y)", "disjoint(x, y)"]


def test_definition_binding_only_patch_that_orphans_a_proviso_metavar_is_422(client):
    # Dropping a binding a stored proviso still names must be rejected even though
    # the proviso isn't in the PATCH — mirrors the rule guard so a definition can't
    # persist a proviso whose metavariable has no binding to check against.
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    defn = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["equal(x, y)"],
    })
    orphaning = client.patch(f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={
        "bindings": [{"var": "x", "sort": "term"}],
    })
    assert orphaning.status_code == 422

    # A binding-only PATCH that keeps every named metavariable still succeeds.
    ok = client.patch(f"/api/formal-systems/{sid}/definitions/{defn['id']}", json={
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
    })
    assert ok.status_code == 200


def test_blank_definition_proviso_is_rejected_not_dropped(client):
    # A blank proviso line is malformed input, not a silent no-op (mirrors rules).
    _login(client, "ada@example.com")
    sid = _defn_system(client)
    response = client.post(f"/api/formal-systems/{sid}/definitions", json={
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}, {"var": "y", "sort": "term"}],
        "provisos": ["disjoint(x, y)", ""],
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Productions: sort resolution and template/regex rules
# ---------------------------------------------------------------------------


def test_production_requires_a_known_sort(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    response = client.post(
        f"/api/formal-systems/{sid}/productions",
        json={"name": "p", "sort": "nope", "template": "a"},
    )
    assert response.status_code == 400
    assert "Unknown sort" in response.json()["detail"]


def test_production_needs_exactly_one_of_template_or_regex(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})

    both = client.post(
        f"/api/formal-systems/{sid}/productions",
        json={"name": "p", "sort": "term", "template": "a", "regex": "a"},
    )
    assert both.status_code == 400

    neither = client.post(
        f"/api/formal-systems/{sid}/productions", json={"name": "p", "sort": "term"}
    )
    assert neither.status_code == 400


def test_atom_productions_round_trip_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    const = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {"name": "falsum", "sort": "formula", "atom_value": "⊥"},
    )
    assert const["kind"] == "atom"
    assert const["atom_value"] == "⊥" and const["atom_base"] is None

    family = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {"name": "prop", "sort": "formula", "atom_base": "p"},
    )
    assert family["kind"] == "atom"
    assert family["atom_base"] == "p" and family["atom_value"] is None

    # Read back through the full aggregate.
    by_name = {p["name"]: p for p in client.get(f"/api/formal-systems/{sid}").json()["productions"]}
    assert by_name["falsum"]["atom_value"] == "⊥"
    assert by_name["prop"]["atom_base"] == "p"


def test_object_language_role_round_trips_and_defaults_off(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    # Omitted on create: variable-like, the safe reading of an undeclared leaf.
    undeclared = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {"name": "setvar", "sort": "formula", "atom_value": "c"},
    )
    assert undeclared["denotes_constant"] is False

    declared = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {"name": "falsum", "sort": "formula", "atom_value": "⊥", "denotes_constant": True},
    )
    assert declared["denotes_constant"] is True

    # A patch flips it without disturbing the discriminator fields.
    patched = client.patch(
        f"/api/formal-systems/{sid}/productions/{undeclared['id']}",
        json={"denotes_constant": True},
    ).json()
    assert patched["denotes_constant"] is True
    assert patched["atom_value"] == "c" and patched["kind"] == "atom"

    by_name = {p["name"]: p for p in client.get(f"/api/formal-systems/{sid}").json()["productions"]}
    assert by_name["falsum"]["denotes_constant"] is True
    assert by_name["setvar"]["denotes_constant"] is True


def test_binding_slots_round_trip_and_default_empty(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "setvar"})
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/api/formal-systems/{sid}/productions",
          {"name": "letter", "sort": "setvar", "regex": "[a-z]"})

    created = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {
            "name": "forall", "sort": "formula", "template": "∀x.phi",
            "bindings": [
                {"var": "x", "sort": "setvar", "scopes_over": ["phi"]},
                {"var": "phi", "sort": "formula"},
            ],
        },
    )
    assert [b["scopes_over"] for b in created["bindings"]] == [["phi"], []]

    # An ordinary slot list omits the field entirely; it reads back as empty
    # rather than absent, so a client need not special-case it.
    plain = _post(
        client, f"/api/formal-systems/{sid}/productions",
        {
            "name": "membership", "sort": "formula", "template": "(x ∈ y)",
            "bindings": [{"var": "x", "sort": "setvar"}, {"var": "y", "sort": "setvar"}],
        },
    )
    assert [b["scopes_over"] for b in plain["bindings"]] == [[], []]

    by_name = {p["name"]: p for p in client.get(f"/api/formal-systems/{sid}").json()["productions"]}
    assert by_name["forall"]["bindings"][0]["scopes_over"] == ["phi"]


def test_binding_slot_must_name_a_sibling_slot(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "setvar"})
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/api/formal-systems/{sid}/productions",
          {"name": "letter", "sort": "setvar", "regex": "[a-z]"})

    for scopes_over, detail in [(["psi"], "not a slot"), (["x"], "scope over itself")]:
        response = client.post(
            f"/api/formal-systems/{sid}/productions",
            json={
                "name": "forall", "sort": "formula", "template": "∀x.phi",
                "bindings": [
                    {"var": "x", "sort": "setvar", "scopes_over": scopes_over},
                    {"var": "phi", "sort": "formula"},
                ],
            },
        )
        assert response.status_code == 400
        assert detail in response.json()["detail"]


def test_production_rejects_mixing_atom_with_another_kind(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    resp = client.post(
        f"/api/formal-systems/{sid}/productions",
        json={"name": "x", "sort": "formula", "atom_value": "⊥", "template": "a"},
    )
    assert resp.status_code == 400


def test_production_rejects_empty_atom_inputs(client):
    # An empty base would match `_0`, `_1`, … and an empty constant no token at
    # all, so neither is a valid atom — rejected at the schema (422).
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    for body in ({"atom_value": ""}, {"atom_base": ""}):
        resp = client.post(
            f"/api/formal-systems/{sid}/productions", json={"name": "x", "sort": "formula", **body}
        )
        assert resp.status_code == 422, resp.text


def test_multiple_line_types_are_allowed(client):
    # A system may declare several logical line types; both are stored and read
    # back in creation order.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/line-types", {"name": "claim", "shape": "<x>"})
    second = client.post(
        f"/api/formal-systems/{sid}/line-types", json={"name": "assume", "shape": "<y>"}
    )
    assert second.status_code == 201, second.text
    lines = client.get(f"/api/formal-systems/{sid}").json()["lines"]
    assert [line["name"] for line in lines] == ["claim", "assume"]


def test_duplicate_line_type_name_is_rejected(client):
    # The engine keys line types by name, so a duplicate would silently drop a
    # shape; reject it (409) rather than store an unusable pair.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/line-types", {"name": "claim", "shape": "<x>"})
    dup = client.post(
        f"/api/formal-systems/{sid}/line-types", json={"name": "claim", "shape": "<y>"}
    )
    assert dup.status_code == 409


def test_line_type_scope_is_stored_and_read_back(client):
    # A scope-opening line persists its `scope` and surfaces it on read.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    created = _post(
        client,
        f"/api/formal-systems/{sid}/line-types",
        {"name": "assume", "shape": "assume <x>", "scope": "assumption"},
    )
    assert created["scope"] == "assumption"

    line = client.get(f"/api/formal-systems/{sid}").json()["lines"][0]
    assert line["scope"] == "assumption"

    # A PATCH can clear the scope back to a plain line.
    patched = client.patch(
        f"/api/formal-systems/{sid}/line-types/{created['id']}", json={"scope": None}
    )
    assert patched.status_code == 200
    assert patched.json()["scope"] is None


def test_invalid_line_type_scope_is_rejected_as_422(client):
    # Only "assumption"/"variable"/None are valid openers; anything else is a
    # validation error, not a build-time surprise.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    response = client.post(
        f"/api/formal-systems/{sid}/line-types",
        json={"name": "weird", "shape": "<x>", "scope": "bogus"},
    )
    assert response.status_code == 422


def test_line_type_behaviour_is_stored_and_read_back(client):
    # A comment line persists its behaviour and surfaces it on read; a logical
    # line keeps the default without the client having to send it.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    created = _post(
        client,
        f"/api/formal-systems/{sid}/line-types",
        {"name": "note", "shape": "-- <text>", "behaviour": "comment"},
    )
    assert created["behaviour"] == "comment"

    plain = _post(client, f"/api/formal-systems/{sid}/line-types", {"name": "claim", "shape": "<x>"})
    assert plain["behaviour"] == "logical"

    behaviours = {
        line["name"]: line["behaviour"]
        for line in client.get(f"/api/formal-systems/{sid}").json()["lines"]
    }
    assert behaviours == {"note": "comment", "claim": "logical"}

    # A metadata-only PATCH must not silently reset the behaviour.
    patched = client.patch(
        f"/api/formal-systems/{sid}/line-types/{created['id']}", json={"shape": "// <text>"}
    )
    assert patched.status_code == 200
    assert patched.json()["behaviour"] == "comment"


def test_invalid_line_type_behaviour_is_rejected_as_422(client):
    # The engine has more behaviours, but only these two are authorable — an
    # unsupported one is a validation error, not a build-time surprise.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    response = client.post(
        f"/api/formal-systems/{sid}/line-types",
        json={"name": "block", "shape": "<x>", "behaviour": "indent"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra", [{"scope": "assumption"}, {"logical_sort": "formula"}]
)
def test_comment_line_cannot_carry_a_formula_or_a_scope_via_api(client, extra):
    # Both pairings fail the build, so the API refuses them up front rather than
    # storing a system that will not compile.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(
        f"/api/formal-systems/{sid}/line-types",
        json={"name": "note", "shape": "-- <text>", "behaviour": "comment", **extra},
    )
    assert response.status_code == 422


def test_oversized_fields_are_rejected_as_422(client):
    # Free-text fields are capped to their DB column width, so an oversized value
    # is a validation error, not a Postgres truncation 500.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})

    too_long = "a" * 600  # DefinitionRow.higher is String(512)
    response = client.post(
        f"/api/formal-systems/{sid}/definitions",
        json={"sort": "formula", "name": "d", "higher": too_long, "lower": "b"},
    )
    assert response.status_code == 422


def test_production_update_replaces_bindings(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/api/formal-systems/{sid}/productions", {
        "name": "membership", "sort": "term", "template": "s ∈ t",
        "bindings": [{"var": "s", "sort": "term"}, {"var": "t", "sort": "term"}],
    })
    updated = client.patch(
        f"/api/formal-systems/{sid}/productions/{prod['id']}",
        json={"bindings": [{"var": "s", "sort": "term"}]},
    )
    assert updated.status_code == 200
    assert updated.json()["bindings"] == [{"var": "s", "sort": "term", "scopes_over": []}]


# ---------------------------------------------------------------------------
# Sorts: uniqueness and cascade
# ---------------------------------------------------------------------------


def test_duplicate_sort_name_is_conflict(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    dup = client.post(f"/api/formal-systems/{sid}/sorts", json={"name": "term"})
    assert dup.status_code == 409


def test_duplicate_sort_race_falls_back_to_409(client, monkeypatch):
    # Simulate the check-then-insert race by disabling the pre-check, so the
    # duplicate reaches the DB unique constraint; that IntegrityError must be
    # translated to a 409, not surface as a 500.
    import app.routers.system_parts as parts

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(parts, "_require_symbol_name_free", _noop)

    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    dup = client.post(f"/api/formal-systems/{sid}/sorts", json={"name": "term"})
    assert dup.status_code == 409


def test_deleting_a_sort_with_productions_is_blocked(client):
    # Explicit over silent: a non-empty sort can't be deleted out from under its
    # productions. Remove the production first, then the sort deletes.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/api/formal-systems/{sid}/productions", {
        "name": "variable", "sort": "term", "regex": "[a-z]+",
    })
    assert client.delete(f"/api/formal-systems/{sid}/sorts/{sort['id']}").status_code == 409

    assert client.delete(f"/api/formal-systems/{sid}/productions/{prod['id']}").status_code == 204
    assert client.delete(f"/api/formal-systems/{sid}/sorts/{sort['id']}").status_code == 204
    assert client.get(f"/api/formal-systems/{sid}").json()["sorts"] == []


def test_deleting_a_sort_used_only_by_a_rule_proviso_is_blocked(client):
    # A sort named by a proviso (disjoint/atom sort arg) is referenced only via
    # SideConditionRow.sort_symbol_id — no binding points at it. Deleting it would
    # cascade-drop the predicate and silently weaken the soundness condition, so
    # it must 409. Remove the proviso first, then the sort deletes.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    setvar = _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "setvar"})
    rule = _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        # `setvar` appears only as the proviso's sort argument, not as a binding.
        "side_conditions": ["disjoint(p, q, setvar)"],
    })
    assert client.delete(f"/api/formal-systems/{sid}/sorts/{setvar['id']}").status_code == 409

    # Clear the proviso; now nothing references setvar and it deletes.
    assert client.patch(
        f"/api/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": []}
    ).status_code == 200
    assert client.delete(f"/api/formal-systems/{sid}/sorts/{setvar['id']}").status_code == 204


def test_renaming_a_sort_keeps_references_intact(client):
    # The point of the symbol model: rename a sort and its bindings follow, so
    # the system still compiles (no dangling name references).
    _login(client, "ada@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "HYP", "name": "hypothesis", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    # Rename the sort; the rule's binding referenced it by FK.
    assert client.patch(
        f"/api/formal-systems/{sid}/sorts/{sort['id']}", json={"name": "prop"}
    ).status_code == 200

    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["sorts"][0]["name"] == "prop"
    # The binding now reads the new name — no dangling "formula".
    assert detail["rules"][0]["bindings"] == [{"var": "p", "sort": "prop"}]


def test_deleting_a_referenced_production_is_blocked(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/api/formal-systems/{sid}/productions", {
        "name": "variable", "sort": "term", "regex": "[a-z]+",
    })
    # A binding references the `variable` production directly.
    _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "x", "antecedents": [],
        "bindings": [{"var": "x", "sort": "variable"}],
    })
    assert client.delete(f"/api/formal-systems/{sid}/productions/{prod['id']}").status_code == 409


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


def test_reorder_productions(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "t"})
    a = _post(client, f"/api/formal-systems/{sid}/productions", {"name": "a", "sort": "t", "regex": "a"})
    b = _post(client, f"/api/formal-systems/{sid}/productions", {"name": "b", "sort": "t", "regex": "b"})

    reordered = client.put(
        f"/api/formal-systems/{sid}/productions/order", json={"ids": [b["id"], a["id"]]}
    )
    assert reordered.status_code == 200
    assert [p["name"] for p in reordered.json()] == ["b", "a"]
    # Persisted: the detail read reflects the new order.
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert [p["name"] for p in detail["productions"]] == ["b", "a"]


def test_reorder_rejects_a_non_permutation(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "t"})
    a = _post(client, f"/api/formal-systems/{sid}/productions", {"name": "a", "sort": "t", "regex": "a"})

    bad = client.put(
        f"/api/formal-systems/{sid}/productions/order",
        json={"ids": [a["id"], str(uuid.uuid4())]},
    )
    assert bad.status_code == 400


def _defs_grammar(client: TestClient) -> str:
    # A minimal grammar for layering tests: one sort `f` with an atom production,
    # so a definition's higher form is new notation and its lower form is either
    # an atom or an earlier definition's higher form.
    #
    # The atom is *declared* a constant of the object language. These definitions
    # are nullary (`S ≝ a` takes no arguments), so a variable-like `a` would be
    # free in the defining form — a name the unfold conjures, which the build
    # refuses. A constant denotes one fixed thing and can be neither renamed nor
    # captured, but only the declaration says so: `atom_value` alone would leave
    # it variable-like, exactly as `setvar ::= a | b | c` intends.
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "f"})
    _post(client, f"/api/formal-systems/{sid}/productions",
          {"name": "atom", "sort": "f", "atom_value": "a", "denotes_constant": True})
    return sid


def test_definition_reorder_that_breaks_layering_is_rejected(client):
    # `T ≝ S` builds on `S ≝ a`, so S must stay ahead of T. Dragging T first would
    # leave T's defining form `S` unrecognised — the endpoint rejects it rather
    # than silently un-defining T.
    _login(client, "ada@example.com")
    sid = _defs_grammar(client)
    sub = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "sub", "higher": "S", "lower": "a",
    })
    sup = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "sup", "higher": "T", "lower": "S",
    })

    rejected = client.put(
        f"/api/formal-systems/{sid}/definitions/order", json={"ids": [sup["id"], sub["id"]]}
    )
    assert rejected.status_code == 400
    assert "sup" in rejected.json()["detail"]
    # The stored order is untouched — the reorder never committed.
    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert [d["name"] for d in detail["definitions"]] == ["sub", "sup"]


def test_definition_reorder_that_preserves_layering_is_allowed(client):
    # Two independent definitions (neither uses the other) may be reordered freely.
    _login(client, "ada@example.com")
    sid = _defs_grammar(client)
    first = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "one", "higher": "S", "lower": "a",
    })
    second = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "two", "higher": "T", "lower": "b",
    })

    ok = client.put(
        f"/api/formal-systems/{sid}/definitions/order", json={"ids": [second["id"], first["id"]]}
    )
    assert ok.status_code == 200
    assert [d["name"] for d in ok.json()] == ["two", "one"]


def test_definition_reorder_may_fix_an_already_broken_order(client):
    # A definition created ahead of its dependency never layered to begin with, so
    # a reorder that moves the dependency in front of it drops nothing — it's an
    # improvement, and must be allowed.
    _login(client, "ada@example.com")
    sid = _defs_grammar(client)
    sup = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "sup", "higher": "T", "lower": "S",
    })
    sub = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "sub", "higher": "S", "lower": "a",
    })

    ok = client.put(
        f"/api/formal-systems/{sid}/definitions/order", json={"ids": [sub["id"], sup["id"]]}
    )
    assert ok.status_code == 200
    assert [d["name"] for d in ok.json()] == ["sub", "sup"]


def test_definition_reorder_guard_is_keyed_by_row_not_by_defined_form(client):
    # `base` and `dup` both define `Q`; `dup` builds on `S`. Moving `dup` ahead of
    # `S` drops `dup` even though `base` keeps `Q` recognised — the guard tracks
    # each definition by row, so it isn't fooled by the shared defined form.
    _login(client, "ada@example.com")
    sid = _defs_grammar(client)
    s = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "s", "higher": "S", "lower": "a",
    })
    base = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "base", "higher": "Q", "lower": "a",
    })
    dup = _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "f", "name": "dup", "higher": "Q", "lower": "S",
    })

    rejected = client.put(
        f"/api/formal-systems/{sid}/definitions/order",
        json={"ids": [dup["id"], s["id"], base["id"]]},
    )
    assert rejected.status_code == 400
    assert "dup" in rejected.json()["detail"]


# ---------------------------------------------------------------------------
# Owner scoping
# ---------------------------------------------------------------------------


def test_child_writes_are_owner_scoped(client):
    _login(client, "owner@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "term"})
    client.post("/api/auth/logout")

    _login(client, "intruder@example.com")
    # Can't add to, or edit, a system you don't own.
    assert client.post(f"/api/formal-systems/{sid}/sorts", json={"name": "x"}).status_code == 404
    assert client.patch(
        f"/api/formal-systems/{sid}/sorts/{sort['id']}", json={"name": "x"}
    ).status_code == 404
    assert client.delete(f"/api/formal-systems/{sid}/sorts/{sort['id']}").status_code == 404


# ---------------------------------------------------------------------------
# The remaining part types create and surface in the aggregate
# ---------------------------------------------------------------------------


def test_brackets_definitions_axioms_rules_appear_in_detail(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/api/formal-systems/{sid}/brackets", {"opening": "[", "closing": "]"})
    _post(client, f"/api/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/api/formal-systems/{sid}/axioms", {"label": "AX", "name": "ax", "formula": "a"})
    _post(client, f"/api/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "a", "antecedents": ["a"],
        "bindings": [{"var": "a", "sort": "formula"}],
    })
    _post(client, f"/api/formal-systems/{sid}/definitions", {
        "sort": "formula", "name": "d", "higher": "hi", "lower": "lo",
    })

    detail = client.get(f"/api/formal-systems/{sid}").json()
    assert detail["brackets"][0]["opening"] == "["
    assert detail["axioms"][0]["label"] == "AX"
    assert detail["rules"][0]["antecedents"] == ["a"]
    assert detail["definitions"][0]["name"] == "d"
