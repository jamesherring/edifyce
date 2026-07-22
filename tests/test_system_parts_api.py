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


def test_rule_proviso_over_undeclared_metavar_is_422(client):
    # A proviso may only mention the rule's declared bindings: `q` is not one, so
    # `equal(p, q)` has no metavariable to check against and is rejected up front
    # rather than blowing up in the kernel when the rule is later applied.
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "formula"})
    response = client.post(f"/formal-systems/{sid}/rules", json={
        "label": "R", "name": "r", "deduction": "(p → q)", "antecedents": [],
        "bindings": [{"var": "p", "sort": "formula"}],  # only p is declared
        "side_conditions": ["equal(p, q)"],
    })
    assert response.status_code == 422


def test_definition_proviso_over_undeclared_metavar_is_422(client):
    _login(client, "ada@example.com")
    sid = _new_system(client)
    _post(client, f"/formal-systems/{sid}/sorts", {"name": "term"})
    response = client.post(f"/formal-systems/{sid}/definitions", json={
        "sort": "term", "name": "d", "higher": "x", "lower": "y",
        "bindings": [{"var": "x", "sort": "term"}],  # only x is declared
        "condition": "disjoint(x, y)",
    })
    assert response.status_code == 422


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
