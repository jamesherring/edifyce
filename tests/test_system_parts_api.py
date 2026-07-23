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
from app.db import Base, FormalSystem, SideConditionRow
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
    assert client.post("/auth/register", json={"email": email, "password": password}).status_code == 201
    assert client.post("/auth/login", data={"username": email, "password": password}).status_code == 204


def _new_system(client: TestClient, name: str = "Sys") -> str:
    response = client.post("/formal-systems", json={"name": name})
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
    base = f"/formal-systems/{sid}"
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
    validation = client.post(f"/formal-systems/{sid}/validate").json()
    assert validation["success"] is True, validation
    assert validation["inference_rule_count"] == 2          # HYP, MP
    assert validation["line_type_count"] == 2               # statement + EXT axiom line type

    # The full aggregate reflects everything created.
    detail = client.get(f"/formal-systems/{sid}").json()
    assert [s["name"] for s in detail["sorts"]] == ["term", "formula"]
    assert [p["name"] for p in detail["productions"]] == [
        "variable", "membership", "equality", "implication"
    ]
    assert [r["label"] for r in detail["rules"]] == ["HYP", "MP"]
    assert detail["definitions"][0]["higher"] == "x ⊆ y"

    # And the lowered source captures the layered pieces.
    source = client.get(f"/formal-systems/{sid}/source").json()["source"]
    assert "InferenceRule modus_ponens:" in source
    assert "Define x ⊆ y as (x = y → x = y)" in source


# ---------------------------------------------------------------------------
# A published system must stay compilable across child edits
# ---------------------------------------------------------------------------


def _build_published_zfc(client: TestClient) -> str:
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)
    assert client.patch(f"/formal-systems/{sid}", json={"published": True}).status_code == 200
    return sid


def test_editing_a_published_system_part_is_rejected(client):
    # A published system is frozen: its compiled behaviour is what published
    # proofs were verified against, so no part may be edited — even a
    # compile-preserving edit is refused (409), and it is left unchanged.
    _login(client, "ada@example.com")
    sid = _build_published_zfc(client)
    line = client.get(f"/formal-systems/{sid}").json()["lines"][0]

    resp = client.patch(
        f"/formal-systems/{sid}/line-types/{line['id']}", json={"shape": "assertion"}
    )
    assert resp.status_code == 409, resp.text

    after = client.get(f"/formal-systems/{sid}").json()["lines"][0]
    assert after["shape"] == line["shape"]


def test_all_part_mutations_on_a_published_system_are_rejected(client):
    # The freeze covers every mutation kind, not just breaking edits: create and
    # delete on a published system are both 409.
    _login(client, "ada@example.com")
    sid = _build_published_zfc(client)

    assert client.post(
        f"/formal-systems/{sid}/brackets", json={"opening": "[", "closing": "]"}
    ).status_code == 409
    definition_id = client.get(f"/formal-systems/{sid}").json()["definitions"][0]["id"]
    assert (
        client.delete(f"/formal-systems/{sid}/definitions/{definition_id}").status_code == 409
    )


def test_a_draft_still_tolerates_a_non_compiling_edit(client):
    # Drafts stay draft-tolerant: the same breaking edit that a published system
    # rejects is persisted on a draft (POST /validate reports the breakage).
    _login(client, "ada@example.com")
    sid = _new_system(client, "ZFC")
    _build_zfc(client, sid)  # left unpublished
    line = client.get(f"/formal-systems/{sid}").json()["lines"][0]

    resp = client.patch(
        f"/formal-systems/{sid}/line-types/{line['id']}", json={"shape": "assertion"}
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"/formal-systems/{sid}").json()["lines"][0]["shape"] == "assertion"
    assert client.post(f"/formal-systems/{sid}/validate").json()["success"] is False


# ---------------------------------------------------------------------------
# Rule side-conditions round-trip through the child endpoints
# ---------------------------------------------------------------------------


def test_rule_side_conditions_round_trip_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "RImp", "name": "refl imp", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["not occurs(p, q)", "equal(p, q)"],
    })
    assert rule["side_conditions"] == ["not occurs(p, q)", "equal(p, q)"]

    # Read back through the aggregate detail.
    detail = client.get(f"/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["not occurs(p, q)", "equal(p, q)"]

    # Update replaces the provisos wholesale, including a multi-node tree (an
    # update that deletes the old tree and inserts a new one in one flush).
    updated = client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}",
        json={"side_conditions": ["not occurs(q, p)", "equal(p, q)"]},
    )
    assert updated.status_code == 200
    assert updated.json()["side_conditions"] == ["not occurs(q, p)", "equal(p, q)"]
    # A single-node replacement and an empty list that clears the tree.
    single = client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": ["equal(p, q)"]}
    )
    assert single.json()["side_conditions"] == ["equal(p, q)"]
    cleared = client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": []}
    )
    assert cleared.json()["side_conditions"] == []


def test_rule_matching_kind_round_trips_through_the_api(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "miustr"})

    # Defaults to structural when omitted.
    default_rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "HYP", "name": "hyp", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "miustr"}],
    })
    assert default_rule["matching"] == "structural"

    # A string-rewriting rule stores and reads back its kind.
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R2", "name": "double", "deduction": "Mxx", "antecedents": ["Mx"],
        "bindings": [{"var": "x", "sort": "miustr"}], "matching": "string",
    })
    assert rule["matching"] == "string"
    detail = client.get(f"/formal-systems/{sid}").json()
    assert {r["label"]: r["matching"] for r in detail["rules"]} == {
        "HYP": "structural", "R2": "string",
    }

    # PATCH can flip the kind, and only the kind.
    flipped = client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}", json={"matching": "structural"}
    )
    assert flipped.status_code == 200
    assert flipped.json()["matching"] == "structural"
    assert flipped.json()["deduction"] == "Mxx"


def test_string_rule_cannot_carry_side_conditions_via_api(client):
    # The string path has no term binding to evaluate a proviso against, so the
    # API rejects the pairing (create and both PATCH directions) rather than
    # store a rule whose side-conditions would be silently ignored.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})

    # Create with both is a 422.
    both = client.post(f"/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "matching": "string", "side_conditions": ["equal(p, p)"],
    })
    assert both.status_code == 422

    # A structural rule with provisos is fine; flipping it to string then 422s.
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["equal(p, p)"],
    })
    flip = client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}", json={"matching": "string"}
    )
    assert flip.status_code == 422

    # And adding provisos to an existing string rule is likewise a 422.
    string_rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "S", "name": "s", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}], "matching": "string",
    })
    add = client.patch(
        f"/formal-systems/{sid}/rules/{string_rule['id']}",
        json={"side_conditions": ["equal(p, p)"]},
    )
    assert add.status_code == 422


def test_string_rewriting_system_authored_via_api_verifies_a_proof(client):
    # Author Hofstadter's MIU (a string-rewriting system) entirely through the
    # child endpoints, then check a real derivation against it — proving the
    # matching="string" path works end to end from the API down to the checker.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    base = f"/formal-systems/{sid}"

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
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}], "matching": "bogus",
    })
    assert response.status_code == 422


def test_malformed_rule_side_condition_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["bogus(p, q)"],
    })
    assert response.status_code == 422


def test_rule_or_proviso_round_trips_through_the_api(client):
    # A disjunctive proviso (`A or B`) is accepted and read back verbatim.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "DIS", "name": "disj", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q) or not occurs(p, q)"],
    })
    assert rule["side_conditions"] == ["equal(p, q) or not occurs(p, q)"]
    detail = client.get(f"/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["equal(p, q) or not occurs(p, q)"]


def test_rule_member_proviso_round_trips_through_the_api(client):
    # `member(x, sort)` names a sort argument; it round-trips like `atom`/`disjoint`.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
        "side_conditions": ["member(p, formula)"],
    })
    assert rule["side_conditions"] == ["member(p, formula)"]
    detail = client.get(f"/formal-systems/{sid}").json()
    assert detail["rules"][0]["side_conditions"] == ["member(p, formula)"]


def test_member_proviso_over_unknown_sort_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
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
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "TQ", "name": "term arg", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(q, (p → p))"],
    })
    assert rule["side_conditions"] == ["equal(q, (p → p))"]
    detail = client.get(f"/formal-systems/{sid}").json()
    assert next(r for r in detail["rules"] if r["label"] == "TQ")["side_conditions"] == [
        "equal(q, (p → p))"
    ]
    assert client.post(f"/formal-systems/{sid}/validate").json()["success"] is True


def test_undeclared_argument_is_accepted_as_a_term_not_rejected_at_write(client):
    # An argument that isn't a declared metavariable is now a *literal term*, so the
    # write is draft-tolerant (201) rather than an early 422 — a term that doesn't
    # parse is caught by POST /validate, like any other draft breakage.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
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
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    defn = _post(client, f"/formal-systems/{sid}/definitions", {
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}],
    })
    updated = client.patch(f"/formal-systems/{sid}/definitions/{defn['id']}", json={
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
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q)"],
    })
    # PATCH bindings only, dropping q — the stored `equal(p, q)` now names an
    # undeclared metavariable.
    orphaning = client.patch(f"/formal-systems/{sid}/rules/{rule['id']}", json={
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    assert orphaning.status_code == 422

    # A binding-only PATCH that keeps every named metavariable still succeeds.
    ok = client.patch(f"/formal-systems/{sid}/rules/{rule['id']}", json={
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
    })
    assert ok.status_code == 200


def test_blank_rule_side_condition_is_rejected_not_dropped(client):
    # A blank proviso line is a malformed input, not a silent no-op: reject it
    # rather than storing the rule with the blank quietly discarded.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        "side_conditions": ["equal(p, q)", ""],
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Productions: sort resolution and template/regex rules
# ---------------------------------------------------------------------------


def test_production_requires_a_known_sort(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    response = client.post(
        f"/formal-systems/{sid}/productions",
        json={"name": "p", "sort": "nope", "template": "a"},
    )
    assert response.status_code == 400
    assert "Unknown sort" in response.json()["detail"]


def test_production_needs_exactly_one_of_template_or_regex(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})

    both = client.post(
        f"/formal-systems/{sid}/productions",
        json={"name": "p", "sort": "term", "template": "a", "regex": "a"},
    )
    assert both.status_code == 400

    neither = client.post(
        f"/formal-systems/{sid}/productions", json={"name": "p", "sort": "term"}
    )
    assert neither.status_code == 400


def test_only_one_line_type_is_allowed(client):
    # The declarative layer lowers a single line type, so a second is rejected
    # rather than silently ignored by validate/source.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/line-types", {"name": "statement", "shape": "<x>"})
    second = client.post(
        f"/formal-systems/{sid}/line-types", json={"name": "other", "shape": "<y>"}
    )
    assert second.status_code == 409


def test_oversized_fields_are_rejected_as_422(client):
    # Free-text fields are capped to their DB column width, so an oversized value
    # is a validation error, not a Postgres truncation 500.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})

    too_long = "a" * 600  # DefinitionRow.higher is String(512)
    response = client.post(
        f"/formal-systems/{sid}/definitions",
        json={"sort": "formula", "name": "d", "higher": too_long, "lower": "b"},
    )
    assert response.status_code == 422


def test_production_update_replaces_bindings(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/formal-systems/{sid}/productions", {
        "name": "membership", "sort": "term", "template": "s ∈ t",
        "bindings": [{"var": "s", "sort": "term"}, {"var": "t", "sort": "term"}],
    })
    updated = client.patch(
        f"/formal-systems/{sid}/productions/{prod['id']}",
        json={"bindings": [{"var": "s", "sort": "term"}]},
    )
    assert updated.status_code == 200
    assert updated.json()["bindings"] == [{"var": "s", "sort": "term"}]


# ---------------------------------------------------------------------------
# Sorts: uniqueness and cascade
# ---------------------------------------------------------------------------


def test_duplicate_sort_name_is_conflict(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    dup = client.post(f"/formal-systems/{sid}/sorts", json={"name": "term"})
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
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    dup = client.post(f"/formal-systems/{sid}/sorts", json={"name": "term"})
    assert dup.status_code == 409


def test_deleting_a_sort_with_productions_is_blocked(client):
    # Explicit over silent: a non-empty sort can't be deleted out from under its
    # productions. Remove the production first, then the sort deletes.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/formal-systems/{sid}/productions", {
        "name": "variable", "sort": "term", "regex": "[a-z]+",
    })
    assert client.delete(f"/formal-systems/{sid}/sorts/{sort['id']}").status_code == 409

    assert client.delete(f"/formal-systems/{sid}/productions/{prod['id']}").status_code == 204
    assert client.delete(f"/formal-systems/{sid}/sorts/{sort['id']}").status_code == 204
    assert client.get(f"/formal-systems/{sid}").json()["sorts"] == []


def test_deleting_a_sort_used_only_by_a_rule_proviso_is_blocked(client):
    # A sort named by a proviso (disjoint/atom sort arg) is referenced only via
    # SideConditionRow.sort_symbol_id — no binding points at it. Deleting it would
    # cascade-drop the predicate and silently weaken the soundness condition, so
    # it must 409. Remove the proviso first, then the sort deletes.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    setvar = _post(client, f"/formal-systems/{sid}/sorts", {"name": "setvar"})
    rule = _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}, {"var": "q", "sort": "formula"}],
        # `setvar` appears only as the proviso's sort argument, not as a binding.
        "side_conditions": ["disjoint(p, q, setvar)"],
    })
    assert client.delete(f"/formal-systems/{sid}/sorts/{setvar['id']}").status_code == 409

    # Clear the proviso; now nothing references setvar and it deletes.
    assert client.patch(
        f"/formal-systems/{sid}/rules/{rule['id']}", json={"side_conditions": []}
    ).status_code == 200
    assert client.delete(f"/formal-systems/{sid}/sorts/{setvar['id']}").status_code == 204


def test_renaming_a_sort_keeps_references_intact(client):
    # The point of the symbol model: rename a sort and its bindings follow, so
    # the system still compiles (no dangling name references).
    _login(client, "ada@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/formal-systems/{sid}/rules", {
        "label": "HYP", "name": "hypothesis", "deduction": "p", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],
    })
    # Rename the sort; the rule's binding referenced it by FK.
    assert client.patch(
        f"/formal-systems/{sid}/sorts/{sort['id']}", json={"name": "prop"}
    ).status_code == 200

    detail = client.get(f"/formal-systems/{sid}").json()
    assert detail["sorts"][0]["name"] == "prop"
    # The binding now reads the new name — no dangling "formula".
    assert detail["rules"][0]["bindings"] == [{"var": "p", "sort": "prop"}]


def test_deleting_a_referenced_production_is_blocked(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    prod = _post(client, f"/formal-systems/{sid}/productions", {
        "name": "variable", "sort": "term", "regex": "[a-z]+",
    })
    # A binding references the `variable` production directly.
    _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "x", "antecedents": [],
        "bindings": [{"var": "x", "sort": "variable"}],
    })
    assert client.delete(f"/formal-systems/{sid}/productions/{prod['id']}").status_code == 409


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


def test_reorder_productions(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "t"})
    a = _post(client, f"/formal-systems/{sid}/productions", {"name": "a", "sort": "t", "regex": "a"})
    b = _post(client, f"/formal-systems/{sid}/productions", {"name": "b", "sort": "t", "regex": "b"})

    reordered = client.put(
        f"/formal-systems/{sid}/productions/order", json={"ids": [b["id"], a["id"]]}
    )
    assert reordered.status_code == 200
    assert [p["name"] for p in reordered.json()] == ["b", "a"]
    # Persisted: the detail read reflects the new order.
    detail = client.get(f"/formal-systems/{sid}").json()
    assert [p["name"] for p in detail["productions"]] == ["b", "a"]


def test_reorder_rejects_a_non_permutation(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "t"})
    a = _post(client, f"/formal-systems/{sid}/productions", {"name": "a", "sort": "t", "regex": "a"})

    bad = client.put(
        f"/formal-systems/{sid}/productions/order",
        json={"ids": [a["id"], str(uuid.uuid4())]},
    )
    assert bad.status_code == 400


# ---------------------------------------------------------------------------
# Owner scoping
# ---------------------------------------------------------------------------


def test_child_writes_are_owner_scoped(client):
    _login(client, "owner@example.com")
    sid = _new_system(client)
    sort = _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    client.post("/auth/logout")

    _login(client, "intruder@example.com")
    # Can't add to, or edit, a system you don't own.
    assert client.post(f"/formal-systems/{sid}/sorts", json={"name": "x"}).status_code == 404
    assert client.patch(
        f"/formal-systems/{sid}/sorts/{sort['id']}", json={"name": "x"}
    ).status_code == 404
    assert client.delete(f"/formal-systems/{sid}/sorts/{sort['id']}").status_code == 404


# ---------------------------------------------------------------------------
# The remaining part types create and surface in the aggregate
# ---------------------------------------------------------------------------


def test_brackets_definitions_axioms_rules_appear_in_detail(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/brackets", {"opening": "[", "closing": "]"})
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    _post(client, f"/formal-systems/{sid}/axioms", {"label": "AX", "name": "ax", "formula": "a"})
    _post(client, f"/formal-systems/{sid}/rules", {
        "label": "R", "name": "r", "deduction": "a", "antecedents": ["a"],
        "bindings": [{"var": "a", "sort": "formula"}],
    })
    _post(client, f"/formal-systems/{sid}/definitions", {
        "sort": "formula", "name": "d", "higher": "hi", "lower": "lo",
    })

    detail = client.get(f"/formal-systems/{sid}").json()
    assert detail["brackets"][0]["opening"] == "["
    assert detail["axioms"][0]["label"] == "AX"
    assert detail["rules"][0]["antecedents"] == ["a"]
    assert detail["definitions"][0]["name"] == "d"
