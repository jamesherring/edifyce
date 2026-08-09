"""Writing a subproof through the structured path.

§4.6 of docs/informal-source-ingestion-roadmap.md. A paper's proof is case
splits, inductions and "assume for contradiction", and every one of those is a
**subproof** — the one thing `POST /proofs/{id}/lines` could not write. §9e
records why it went unnoticed: a Metamath corpus is flat, so the measured run
never touched a scope opener, a discharge line or an indent, and nothing in it
could have.

Mechanically a subproof is *indentation*: a line indented past an opener is
inside it, one at or left of the opener closes it. So the write path needed two
things — a choice of line type, since opening a scope is a property of the type,
and a choice of indent — and what these pin is mostly that **what was asked for
is what landed**, because a line at the wrong indent joins the wrong subproof
while checking perfectly well.

The system is `zfc_systems.scoped_zfc_spec`, the same one `tests/test_zfc_scoped`
checks the engine against: `assume <formula>` opens a hypothesis subproof,
`let <setvar>` opens a fresh-variable one, and `CP`/`UG` discharge them.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient

from tests.test_proofs_api import (  # noqa: F401 - fixtures come along
    _register_login,
    _seed_system,
    client,
    db,
)
from tests.zfc_systems import scoped_zfc_spec


def _proof(client: TestClient, db_path, owner: str, source: str) -> str:
    system_id = _seed_system(db_path, owner, spec=scoped_zfc_spec())
    created = client.post(
        "/api/proofs",
        json={"name": "P", "formal_system_id": system_id, "source": source},
    )
    assert created.status_code == 201, created.text
    proof_id = created.json()["id"]
    verified = client.post(f"/api/proofs/{proof_id}/verify")
    assert verified.status_code == 200, verified.text
    return proof_id


def membership(s: str, t: str) -> dict:
    return {
        "constructor": "membership",
        "slots": {
            "x": {"constructor": "setvar_atom", "literal": s},
            "y": {"constructor": "setvar_atom", "literal": t},
        },
    }


def implication(left: dict, right: dict) -> dict:
    return {"constructor": "implication", "slots": {"p": left, "q": right}}


def source_of(client: TestClient, proof_id: str) -> str:
    return client.get(f"/api/proofs/{proof_id}").json()["source"]


def lines_of(client: TestClient, proof_id: str) -> list[tuple[int | None, int, str]]:
    body = client.get(f"/api/proofs/{proof_id}/structure").json()
    return [(l["number"], l["indent"], l["display"]) for l in body["lines"]]


# ---------------------------------------------------------------------------
# Opening one
# ---------------------------------------------------------------------------


def test_a_proof_can_open_its_first_subproof(client, db):
    # The bootstrap case, and the reason a line type's declared shape is composed
    # from at all: there is no `assume` line to copy until there is an `assume`
    # line, so without this a proof could never open a subproof by this route.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "x ∈ y [HYP]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("a", "b"),
            "line_type": "assume",
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["display"] == "assume a ∈ b"
    assert body["opens_scope"] == "assumption"
    # At the root, since nothing said otherwise: it *opens* a scope, it is not
    # *in* one.
    assert body["scope"] is None
    assert source_of(client, proof_id) == "x ∈ y [HYP]\nassume a ∈ b"


def test_a_scope_opener_takes_no_citation(client, db):
    # A scope opener is granted by fiat — a hypothesis, not a step — so it
    # declares no reference field and there is nothing for a citation to go in.
    # Refused rather than dropped: a caller that thinks it has justified an
    # assumption has misunderstood what it just wrote.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "x ∈ y [HYP]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("a", "b"),
            "line_type": "assume",
            "rule": "R",
            "antecedents": [1],
        },
    )
    assert res.status_code == 422
    assert "assumed rather than justified" in res.json()["detail"]


def test_a_line_type_the_system_does_not_declare_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "x ∈ y [HYP]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": membership("a", "b"), "line_type": "suppose"},
    )
    assert res.status_code == 422
    assert "no line type named 'suppose'" in res.json()["detail"]


def test_the_second_subproof_copies_the_first(client, db):
    # Once there is an `assume` line, the safe path applies: its display is
    # spliced rather than the shape reconstructed.
    #
    # It also shows what `scope` defaulting to the anchor's *means* for an
    # opener: appended after an indented line, the new subproof nests inside the
    # one already open. That is the uniform rule rather than a special case for
    # openers, and opening at the root from in here is a matter of saying so —
    # see the test below.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("c", "d"),
            "line_type": "assume",
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "    assume c ∈ d"
    assert res.json()["opens_scope"] == "assumption"
    assert res.json()["scope"] == 1  # nested inside the first


def test_a_subproof_can_be_opened_back_at_the_root(client, db):
    # The other half of the above: `outside` the enclosing opener is how a caller
    # leaves one subproof and starts a sibling rather than a child.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("c", "d"),
            "line_type": "assume",
            "scope": {"opener": 1, "placement": "outside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "assume c ∈ d"
    assert res.json()["scope"] is None


# ---------------------------------------------------------------------------
# Living in one
# ---------------------------------------------------------------------------


def test_a_line_can_be_written_inside_a_subproof(client, db):
    # `inside` is the whole point of naming the placement by the opener's number:
    # the caller says which subproof, not which column.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "rule": "R",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "inside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == 1
    assert body["accepted"] is True
    # Indented to match the subproof's existing line rather than to a convention.
    assert body["display"] == "    x ∈ y [R, 1]"


def test_an_empty_subproof_is_indented_by_the_default_step(client, db):
    # Nothing in the subproof to copy, so the convention applies — and it applies
    # only here, which is what keeps a proof that indents by two indented by two.
    #
    # `line_type` is named because the line to anchor to is the opener, and an
    # opener lends no shape. That is the standing rule rather than anything about
    # scopes: the anchor lends the shape, and a caller wanting a different kind of
    # line says which.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(
        client, db, owner, "assume x ∈ y\n(x ∈ y → x ∈ y) [CP, 1]"
    )

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "line_type": "statement",
            "rule": "R",
            "antecedents": [1],
            "before": 2,
            "scope": {"opener": 1, "placement": "inside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "    x ∈ y [R, 1]"
    assert res.json()["scope"] == 1


def test_a_subproof_cannot_be_rejoined_once_it_has_closed(client, db):
    # The mechanic worth stating outright, because it is the one a caller will
    # hit: a subproof is closed by the first line that dedents past its opener,
    # and indenting cannot reopen it. So `inside` is not a place a line can be
    # *appended* to once the block has ended — it has to be written within it.
    # Caught by reading the scope back off the checked proof rather than trusting
    # the request, which is the only thing that could catch it.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(
        client, db, owner, "assume x ∈ y\n(x ∈ y → x ∈ y) [CP, 1]"
    )

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "line_type": "statement",
            "rule": "R",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "inside"},
        },
    )
    assert res.status_code == 422, res.text
    assert "cannot reopen" in res.json()["detail"]


def test_a_proof_that_indents_by_two_stays_indented_by_two(client, db):
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n  x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "rule": "R",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "inside"},
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "  x ∈ y [R, 1]"


def test_a_placement_naming_a_line_that_opens_nothing_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "scope": {"opener": 2, "placement": "inside"},
        },
    )
    assert res.status_code == 422
    assert "opens no subproof" in res.json()["detail"]


def test_a_placement_naming_no_line_at_all_is_refused(client, db):
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "scope": {"opener": 9, "placement": "inside"},
        },
    )
    assert res.status_code == 409
    assert "no line 9" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Getting back out — the discharge
# ---------------------------------------------------------------------------


def test_a_subproof_can_be_discharged(client, db):
    # The move the structured path could not make at all: a line justified by a
    # *block* rather than by cited lines, written at the indent that closes it.
    # `outside` is not a special case — a line at the opener's own indent dedents
    # past it, which is exactly what ends the subproof.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": implication(membership("x", "y"), membership("x", "y")),
            "rule": "CP",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "outside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["display"] == "(x ∈ y → x ∈ y) [CP, 1]"
    assert body["accepted"] is True
    assert body["scope"] is None  # back at the root
    assert body["valid"] is True

    assert lines_of(client, proof_id) == [
        (1, 0, "assume x ∈ y"),
        (2, 4, "x ∈ y [R, 1]"),
        (3, 0, "(x ∈ y → x ∈ y) [CP, 1]"),
    ]


def test_a_discharge_written_inside_the_subproof_is_not_accepted(client, db):
    # The engine's rule, reached through the structured path: discharging from
    # *inside* would let the subproof consume itself. The line is written and
    # reported unaccepted rather than refused — it is a wrong step, not a
    # malformed request.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": implication(membership("x", "y"), membership("x", "y")),
            "rule": "CP",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "inside"},
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["scope"] == 1
    assert res.json()["accepted"] is False


def test_a_nested_subproof_discharges_to_its_parent(client, db):
    # Two levels, discharged from the inside out. `outside` on the *inner*
    # opener lands in the outer subproof, not at the root — which is the case a
    # placement named by column would get wrong without the caller doing the
    # arithmetic.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(
        client,
        db,
        owner,
        "assume x ∈ y\n    assume z ∈ w\n        x ∈ y [R, 1]",
    )

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": implication(membership("z", "w"), membership("x", "y")),
            "rule": "CP",
            "antecedents": [2],
            "scope": {"opener": 2, "placement": "outside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Out of the inner subproof and into the outer one — not to the root.
    assert body["scope"] == 1
    assert body["accepted"] is True
    assert body["display"] == "    (z ∈ w → x ∈ y) [CP, 2]"


def test_a_fresh_variable_subproof_is_the_same_two_moves(client, db):
    # `let <setvar>` opens a scope of the other kind, and nothing about the route
    # knows which: the system declares the scope per line type, and this reports
    # what it declared.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "x ∈ y [HYP]")

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": {"constructor": "setvar_atom", "literal": "z"},
            "line_type": "introduce",
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "let z"
    assert res.json()["opens_scope"] == "variable"


# ---------------------------------------------------------------------------
# What was asked for is what landed
# ---------------------------------------------------------------------------


def test_the_line_type_is_checked_on_the_way_back(client, db):
    # A digest says nothing about which line type a line is: two types stating
    # one formula produce the same term. Without a separate check a proposal
    # asking for `assume` could come back as an ordinary step, pass the round
    # trip, and silently open no subproof — so `assume` and `statement` here both
    # state `a ∈ b` and only the type tells them apart.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "x ∈ y [HYP]")

    opened = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": membership("a", "b"), "line_type": "assume"},
    ).json()
    plain = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": membership("a", "b")},
    ).json()

    assert opened["display"] == "assume a ∈ b"
    assert opened["opens_scope"] == "assumption"
    assert plain["display"] == "a ∈ b [?]"
    assert plain["opens_scope"] is None


def test_the_scope_is_read_off_the_checked_proof_not_the_request(client, db):
    # Indentation is what places a line, so where it landed is a fact about the
    # checked proof rather than about what was asked for. A discharge told it is
    # at the root when it is still inside the subproof it meant to discharge has
    # been told the opposite of what happened.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    inside = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "rule": "R",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "inside"},
        },
    ).json()
    outside = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "rule": "R",
            "antecedents": [1],
            "scope": {"opener": 1, "placement": "outside"},
        },
    ).json()

    assert inside["scope"] == 1
    assert outside["scope"] is None
    # And the two differ only in their indent, which is the whole mechanism.
    assert inside["display"].strip() == outside["display"].strip()
    assert inside["display"] != outside["display"]


def test_an_insert_that_would_move_a_valid_line_into_another_subproof_is_refused(
    client, db
):
    # The guard §4.6 asks for, and the case that shows why validity alone cannot
    # be it. A line's scope comes from the indents around it, so inserting a
    # dedented line closes a subproof early and the lines below land in the
    # parent — where they can go on checking perfectly well while meaning
    # something else.
    #
    # Line 5 is the one that matters: it cites line 3, which is at the *root*, so
    # dedenting line 5 out of subproof 4 leaves its citation perfectly in scope
    # and its verdict untouched. Nothing about its validity moves. What moves is
    # which subproof it is a step of — and a discharge of subproof 4 would then
    # be discharging a block that no longer contains it.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(
        client,
        db,
        owner,
        "assume x ∈ y\n"
        "    x ∈ y [R, 1]\n"
        "(x ∈ y → x ∈ y) [CP, 1]\n"
        "assume a ∈ b\n"
        "    (x ∈ y → x ∈ y) [R, 3]",
    )
    before = lines_of(client, proof_id)
    assert [n for n, _, _ in before] == [1, 2, 3, 4, 5]

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("c", "d"),
            "before": 5,
            "scope": {"opener": 4, "placement": "outside"},
            "apply": True,
        },
    )
    assert res.status_code == 409, res.text
    assert "different subproof" in res.json()["detail"]
    # And nothing was written.
    assert lines_of(client, proof_id) == before


def test_an_insert_inside_the_subproof_moves_nothing(client, db):
    # The other side of the same guard: an insert at the subproof's own indent
    # leaves every line where it was, so it is allowed.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(
        client,
        db,
        owner,
        "assume x ∈ y\n    x ∈ y [R, 1]\n    x ∈ y [R, 1]",
    )

    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={
            "statement": membership("x", "y"),
            "rule": "R",
            "antecedents": [1],
            "before": 3,
            "scope": {"opener": 1, "placement": "inside"},
            "apply": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["scope"] == 1
    assert [n for n, _, _ in lines_of(client, proof_id)] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Nothing about the old path moved
# ---------------------------------------------------------------------------


def test_a_proposal_naming_neither_behaves_as_before(client, db):
    # The compatibility case. Both new fields default to the anchor's, so a
    # proposal written before subproofs were reachable is unaffected — including
    # the refusal that used to be the only thing said about scope openers.
    owner = _register_login(client, "ada@example.com")
    proof_id = _proof(client, db, owner, "assume x ∈ y\n    x ∈ y [R, 1]")

    # Appending takes the last line's shape and indent, as it always did.
    res = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": membership("a", "b")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["display"] == "    a ∈ b [?]"
    assert res.json()["scope"] == 1

    # And anchoring to a scope opener with no `line_type` is still refused, since
    # the new line would inherit a type that states nothing checkable.
    refused = client.post(
        f"/api/proofs/{proof_id}/lines",
        json={"statement": membership("a", "b"), "before": 1},
    )
    assert refused.status_code == 422
    assert "not an ordinary logical line" in refused.json()["detail"]
    assert "name a `line_type`" in refused.json()["detail"]
