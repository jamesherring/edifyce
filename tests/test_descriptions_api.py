"""Descriptions, titles and authorship over HTTP.

The read side of `tests/test_descriptions_store.py`: an imported corpus is
documented, and this is how a client sees it. Two routes carry it — a proof's own
read, which also brings the corpus's record of its label, and a system's label
route, which is how the *other three* kinds of label are reached (a production, a
definition and a primitive theorem have no proof to hang documentation on, and
`df-un` and `ax-ext` are exactly those).
"""

from __future__ import annotations

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
from app.db.metamath_store import import_corpus
from app.db.descriptions import LabelDescriptionRow
from app.db.models import Proof
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_descriptions_store import MARKED, SOURCE
from tests.test_metamath_persistence import PROPOSITIONAL
from tests.test_metamath_layered_specs import CORPUS
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.metamath import parse
from website.logical.metamath.setmm import LAYERS


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "descriptions")
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


def seed(db_path) -> tuple[str, str]:
    """Import the documented fixture, published so an anonymous read reaches it."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            session.commit()
            proof = session.scalars(select(Proof)).one()
            # An import is ownerless, so publishing is what makes it readable.
            proof.published_at = proof.created_at
            system_row = proof.formal_system
            system_row.published_at = proof.created_at
            session.commit()
            return str(report.system_id), str(proof.id)
    finally:
        engine.dispose()


def test_a_proof_carries_its_title_and_the_corpus_record_of_its_label(client, db):
    _, proof_id = seed(db)

    body = client.get(f"/api/proofs/{proof_id}").json()
    # The label stays the identity; the title is the sentence.
    assert body["name"] == "id"
    assert body["title"] == "Principle of identity."

    doc = body["documentation"]
    assert doc["label"] == "id"
    assert doc["title"] == "Principle of identity."
    assert [(a["kind"], a["who"], a["dated"]) for a in doc["attributions"]] == [
        ("Contributed", "NM", "4-Apr-1994"),
        ("Proof shortened", "Wolf Lammen", "8-Sep-2012"),
    ]


def test_a_label_with_no_proof_is_read_from_the_system(client, db):
    # The case the route exists for. `df-neg` is a `$a`: it became a definition,
    # has no proof, and is where the interesting prose lives.
    system_id, _ = seed(db)

    body = client.get(f"/api/formal-systems/{system_id}/labels/df-neg").json()
    assert body["title"] == "Define negation as implying a falsehood."
    assert body["text"].count("\n\n") == 1
    assert [a["who"] for a in body["attributions"]] == ["NM", "Mario Carneiro"]


def test_a_label_the_system_does_not_describe_is_a_404(client, db):
    system_id, _ = seed(db)
    assert client.get(f"/api/formal-systems/{system_id}/labels/nosuch").status_code == 404


def test_a_hand_authored_proof_has_a_title_it_sets_and_no_corpus_record(client, db):
    # The other half: `documentation` is the *system's* record, which a system
    # nobody imported keeps none of. The proof's own title is still its own.
    _register_login(client, "ada@example.com")
    created = client.post("/api/formal-systems", json={"name": "Hand authored"})
    assert created.status_code == 201, created.text
    system_id = created.json()["id"]

    made = client.post(
        "/api/proofs",
        json={
            "name": "assoc",
            "formal_system_id": system_id,
            "title": "Conjunction is associative.",
        },
    )
    assert made.status_code == 201, made.text
    assert made.json()["title"] == "Conjunction is associative."

    body = client.get(f"/api/proofs/{made.json()['id']}").json()
    assert body["documentation"] is None
    assert body["title"] == "Conjunction is associative."

    # And it is editable, which is why it is a column rather than a derivation.
    patched = client.patch(
        f"/api/proofs/{made.json()['id']}", json={"title": "Associativity of ∧."}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Associativity of ∧."


def test_every_route_that_returns_a_proof_agrees_about_its_documentation(client, db):
    # `documentation` must not mean "not asked for" on one route and "none exists"
    # on another: a client — the editor among them — assigns whichever response it
    # got straight into its proof state, and cannot tell the two apart.
    _register_login(client, "ada@example.com")
    system_id = client.post("/api/formal-systems", json={"name": "Hand authored"}).json()["id"]

    created = client.post(
        "/api/proofs", json={"name": "assoc", "formal_system_id": system_id}
    )
    proof_id = created.json()["id"]
    patched = client.patch(f"/api/proofs/{proof_id}", json={"title": "A title."})
    fetched = client.get(f"/api/proofs/{proof_id}")

    for response in (created, patched, fetched):
        assert "documentation" in response.json(), response.text
        assert response.json()["documentation"] is None


def test_a_title_can_be_cleared(client, db):
    # Null and "" are different answers, and a PATCH must be able to reach the
    # first: an imported title a reader disagrees with should be removable, not
    # only replaceable.
    _register_login(client, "ada@example.com")
    system_id = client.post("/api/formal-systems", json={"name": "Hand authored"}).json()["id"]
    proof_id = client.post(
        "/api/proofs",
        json={"name": "assoc", "formal_system_id": system_id, "title": "Something."},
    ).json()["id"]

    assert client.patch(f"/api/proofs/{proof_id}", json={"title": None}).json()["title"] is None


# ---------------------------------------------------------------------------
# Cross-references, resolved
# ---------------------------------------------------------------------------


def seed_marked(db_path) -> tuple[str, dict[str, str]]:
    """Import the cross-referencing fixture; every proof of it readable."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(MARKED), name="m")
            session.commit()
            proofs = list(session.scalars(select(Proof)))
            for proof in proofs:
                proof.published_at = proof.created_at
            proofs[0].formal_system.published_at = proofs[0].created_at
            session.commit()
            return str(report.system_id), {p.name: str(p.id) for p in proofs}
    finally:
        engine.dispose()


def test_a_reference_comes_back_with_the_span_it_occupies(client, db):
    # The contract the offsets exist for: slicing the prose at them yields the
    # markup, so a client renders a link without parsing a Metamath comment.
    _, proofs = seed_marked(db)

    doc = client.get(f"/api/proofs/{proofs['id']}").json()["documentation"]

    assert [r["target"] for r in doc["references"]] == ["ax-1", "wi"]
    for reference in doc["references"]:
        assert doc["text"][reference["start"] : reference["end"]] == (
            f"~ {reference['target']}"
        )


def test_a_reference_to_a_readable_proof_carries_its_id(client, db):
    # What makes the link navigable. `ax-1` is a `$a` and has no proof, so it
    # resolves to a target and nothing else; `wi` likewise.
    system_id, proofs = seed_marked(db)

    doc = client.get(f"/api/proofs/{proofs['id2']}").json()["documentation"]

    (reference,) = doc["references"]
    assert reference["target"] == "ax-1"
    assert reference["proof_id"] is None  # a `$a`: documented, but not a proof

    # And one that *is* a proof resolves, from the system's own label route.
    body = client.get(f"/api/formal-systems/{system_id}/labels/ax-1").json()
    mentioned = {m["label"]: m for m in body["mentioned_by"]}
    assert mentioned["id"]["proof_id"] == proofs["id"]
    assert mentioned["id"]["title"] == "Principle of identity."


def test_what_points_at_a_label_comes_back_with_it(client, db):
    # The reverse direction, which the file itself cannot answer: `ax-1` says
    # nothing about what uses it, and two statements say they use it.
    system_id, _ = seed_marked(db)

    body = client.get(f"/api/formal-systems/{system_id}/labels/ax-1").json()

    assert [m["label"] for m in body["mentioned_by"]] == ["id", "id2"]
    assert body["mentioned_by_total"] == 2


def test_a_reference_to_a_draft_resolves_to_no_link(client, db):
    # The reference still shows — the corpus does say the word — but its id is
    # withheld, which is the same rule a single proof read applies.
    system_id, proofs = seed_marked(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            for proof in session.scalars(select(Proof)):
                proof.published_at = None
            session.commit()
    finally:
        engine.dispose()

    body = client.get(f"/api/formal-systems/{system_id}/labels/ax-1").json()

    assert [m["label"] for m in body["mentioned_by"]] == ["id", "id2"]
    assert all(m["proof_id"] is None for m in body["mentioned_by"])


def test_the_discouragement_markers_come_back_as_flags(client, db):
    _, proofs = seed_marked(db)

    doc = client.get(f"/api/proofs/{proofs['id']}").json()["documentation"]

    assert doc["discouraged_usage"] and doc["discouraged_modification"]
    # Out of the prose, so a reader gets a badge rather than a stray sentence.
    assert "discouraged" not in doc["text"]

    other = client.get(f"/api/proofs/{proofs['id2']}").json()["documentation"]
    assert not other["discouraged_usage"] and not other["discouraged_modification"]


# ---------------------------------------------------------------------------
# A reference that crosses a layer
# ---------------------------------------------------------------------------
#
# A layered corpus files each statement against the layer its own section falls
# in, so both directions of the reference graph cross the split: a ZF comment
# points at a propositional theorem, and that theorem's "what points at me" lives
# on a layer it has never heard of. Scoped to one system id, the forward direction
# renders dead text and the reverse under-reports in silence (both found in
# review).

# The shared fixture with one comment added, so the spec and store suites that
# match it keep the file they expect.
LAYERED = CORPUS.replace(
    "zf-thm $p", "$( A set-theoretic theorem, in the manner of ~ pc-thm . $)\nzf-thm $p", 1
)


def seed_layered(db_path) -> tuple[list[str], dict[str, str]]:
    """Import the three-layer fixture, every layer and proof readable."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(LAYERED), name="c", plan=LAYERS)
            session.commit()
            return (
                [str(found) for found in report.system_ids],
                {p.name: str(p.id) for p in session.scalars(select(Proof))},
            )
    finally:
        engine.dispose()


def test_a_reference_resolves_into_a_layer_below(client, db):
    system_ids, proofs = seed_layered(db)
    leaf = system_ids[-1]

    body = client.get(f"/api/formal-systems/{leaf}/labels/zf-thm").json()

    (reference,) = body["references"]
    assert reference["target"] == "pc-thm"
    # `pc-thm` is filed against the propositional root, three layers down.
    assert reference["proof_id"] == proofs["pc-thm"]


def test_what_points_at_a_label_reaches_the_layers_above_it(client, db):
    system_ids, proofs = seed_layered(db)
    root = system_ids[0]

    body = client.get(f"/api/formal-systems/{root}/labels/pc-thm").json()

    assert [m["label"] for m in body["mentioned_by"]] == ["zf-thm"]
    assert body["mentioned_by_total"] == 1
    assert body["mentioned_by"][0]["proof_id"] == proofs["zf-thm"]


# ---------------------------------------------------------------------------
# What a proof is declared to do without
# ---------------------------------------------------------------------------

AVOIDING = r"""
$c |- wff ( ) -> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
$( Wff builder. $)
wi $a wff ( ph -> ps ) $.
$( Axiom _Simp_. $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( A second axiom, which the theorem below is proved without. $)
ax-2 $a |- ( ph -> ( ps -> ph ) ) $.
$( Principle of identity. $)
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
$( $j usage 'id' avoids 'ax-2'; $)
"""


def seed_avoiding(db_path) -> tuple[str, str]:
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(AVOIDING), name="a")
            session.commit()
            proof = session.scalars(select(Proof)).one()
            proof.published_at = proof.created_at
            proof.formal_system.published_at = proof.created_at
            session.commit()
            return str(report.system_id), str(proof.id)
    finally:
        engine.dispose()


def test_a_proof_reports_what_the_corpus_says_it_avoids(client, db):
    # `$j usage 'id' avoids 'ax-2';` — a result about the *proof*, and nowhere
    # else to read it from: `ax-2` is nowhere in `id`'s citations, that being the
    # point of saying it.
    _, proof_id = seed_avoiding(db)

    doc = client.get(f"/api/proofs/{proof_id}").json()["documentation"]

    assert doc["avoids"] == ["ax-2"]


def test_a_label_the_file_declares_nothing_about_avoids_nothing(client, db):
    system_id, _ = seed_avoiding(db)

    body = client.get(f"/api/formal-systems/{system_id}/labels/ax-1").json()

    assert body["avoids"] == []


def test_an_undocumented_label_still_reports_what_it_avoids(client, db):
    # A `$j usage … avoids …` names a label whether or not the file also comments
    # on it — that being why the avoidances are a separate table. Returning None
    # for a record with no prose would put the two facts back together, which is
    # what this branch's first cut did (found in review).
    system_id, _ = seed_avoiding(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            # Take the prose away and leave the declaration standing.
            for row in session.scalars(select(LabelDescriptionRow)):
                if row.label == "id":
                    session.delete(row)
            session.commit()
    finally:
        engine.dispose()

    body = client.get(f"/api/formal-systems/{system_id}/labels/id")

    assert body.status_code == 200, body.text
    assert body.json()["avoids"] == ["ax-2"]
    assert body.json()["text"] == ""


def test_a_label_with_neither_prose_nor_declarations_is_still_a_404(client, db):
    system_id, _ = seed_avoiding(db)

    assert client.get(f"/api/formal-systems/{system_id}/labels/nosuch").status_code == 404


def seed_propositional(db_path) -> tuple[str, str]:
    """Import the fixture whose `mp2` proves under three *labelled* hypotheses."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(PROPOSITIONAL), name="p")
            session.commit()
            mp2 = session.scalars(select(Proof).where(Proof.name == "mp2")).one()
            for row in session.scalars(select(Proof)):
                row.published_at = row.created_at
            mp2.formal_system.published_at = mp2.created_at
            session.commit()
            return str(report.system_id), str(mp2.id)
    finally:
        engine.dispose()


def test_a_theorems_own_hypothesis_resolves_through_the_proof_citing_it(client, db):
    # A `$e` is citable from inside the block that declares it and nowhere else,
    # which is why it is a column on its theorem rather than a library entry. So
    # a system-wide lookup cannot see it, and a step of `mp2` citing `mp2.1`
    # would come back as a citation of nothing.
    system_id, proof_id = seed_propositional(db)

    res = client.get(
        f"/api/formal-systems/{system_id}/library/mp2.1", params={"proof": proof_id}
    )

    assert res.status_code == 200, res.text
    body = res.json()
    # Granted here rather than established: it is what `mp2` is proved *under*.
    assert body["kind"] == "hypothesis"
    assert body["conclusion"] == "ph"
    assert body["proof_id"] is None


def test_a_hypothesis_is_invisible_without_the_proof_that_may_cite_it(client, db):
    # The reach half of the same rule. Answering this globally would make a bare
    # `|- ph` citable by anyone, which is the thing the column exists to prevent.
    system_id, _proof_id = seed_propositional(db)

    assert (
        client.get(f"/api/formal-systems/{system_id}/library/mp2.1").status_code == 404
    )
