"""The citation graph of an imported corpus, over HTTP.

The direction `proof_references` cannot answer. That table is the alias-lemma
mechanism a hand-authored proof uses (`[alias.line]`), and an import writes none
of it — a Metamath step cites a *theorem*, which resolves through the library by
label. So "what does this cite" and "what cites this" are queried from
`proof_lines.rule`, and this is the route that serves them.
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
from app.db.models import Proof, ProofReference
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_metamath_layered_specs import CORPUS
from tests.test_metamath_persistence import PROPOSITIONAL
from tests.test_proofs_api import _TABLES
from website.logical.metamath import parse
from website.logical.metamath.setmm import LAYERS

# The layered fixture, plus a ZF theorem whose proof cites a *propositional* one.
# `CORPUS` crosses a layer only to `ax-1`, which is a `$a` with no proof — so the
# reverse direction has no page to be asked from, and the spine walk that makes
# the whole thing work is never exercised from a proof's own route.
LAYERED_CITATION = CORPUS + (
    "zf-cites-pc $p |- ( ph -> ( ps -> ph ) ) $= ( pc-thm ) ABC $.\n"
)


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "citations")
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


def seed(db_path) -> dict[str, str]:
    """Import the propositional corpus, published, returning label -> proof id."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            import_corpus(session, parse(PROPOSITIONAL), name="t")
            session.commit()
            proofs = list(session.scalars(select(Proof)))
            for proof in proofs:
                proof.published_at = proof.created_at
                proof.formal_system.published_at = proof.created_at
            session.commit()
            return {proof.name: str(proof.id) for proof in proofs}
    finally:
        engine.dispose()


def citations(client, proof_id: str) -> dict:
    response = client.get(f"/api/proofs/{proof_id}/citations")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_proof_reports_the_theorems_it_cites(client, db):
    # `a1i` is proved from `ax-1` and `ax-mp`, both primitives of the corpus.
    body = citations(client, seed(db)["a1i"])

    assert [entry["label"] for entry in body["cites"]] == ["ax-1", "ax-mp"]


def test_a_cited_theorem_reports_what_cites_it(client, db):
    # The direction the file itself never states. `2a1i` is proved from `a1i`.
    ids = seed(db)
    body = citations(client, ids["a1i"])

    assert [entry["label"] for entry in body["cited_by"]] == ["2a1i"]
    assert body["cited_by_total"] == 1


def test_a_citation_of_a_proved_theorem_carries_the_page_to_open(client, db):
    ids = seed(db)
    cited_by = citations(client, ids["a1i"])["cited_by"]

    assert cited_by[0]["proof_id"] == ids["2a1i"]


def test_a_citation_of_a_primitive_has_no_page(client, db):
    # Half a corpus's labels are `$a`s with no proof at all. The citation is still
    # real and still shows; there is simply nothing to open.
    body = citations(client, seed(db)["a1i"])

    assert all(entry["proof_id"] is None for entry in body["cites"])


def test_the_graph_is_computed_rather_than_stored(client, db):
    """An import writes no `proof_references`, and this must not depend on it."""
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            assert session.scalars(select(ProofReference)).all() == []
    finally:
        engine.dispose()

    assert citations(client, ids["a1i"])["cited_by"] != []


def test_dependents_are_found_by_the_library_label_not_the_proof_name(client, db):
    """A proof is cited under its promoted label, which need not be its name.

    Promotion defaults to the *slug*, so a proof called "My Lemma" is cited as
    `my-lemma` and asking `proof_lines.rule` for the name finds nothing. An import
    happens to set the two alike, which is what made the original bug invisible
    here (found in review).
    """
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            renamed = session.scalars(select(Proof).where(Proof.name == "a1i")).one()
            renamed.name = "Inference adding an antecedent"
            session.commit()
    finally:
        engine.dispose()

    body = citations(client, ids["a1i"])
    assert [entry["label"] for entry in body["cited_by"]] == ["2a1i"]


def test_a_proof_with_no_library_entry_has_no_dependents(client, db):
    """Nothing can cite what has no label to be cited by."""
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalars(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "a1i")
            ).one()
            session.delete(entry)
            session.commit()
    finally:
        engine.dispose()

    body = citations(client, ids["a1i"])
    assert body["cited_by"] == []
    assert body["cited_by_total"] == 0


def test_a_proof_citing_nothing_reports_nothing(client, db):
    # `mp2` cites only `ax-mp`; nothing in this corpus cites `mp2`.
    body = citations(client, seed(db)["mp2"])

    assert body["cited_by"] == []
    assert body["cited_by_total"] == 0


def test_an_unreadable_proof_is_a_404(client, db):
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            proof = session.scalars(
                select(Proof).where(Proof.name == "a1i")
            ).one()
            # Back to a draft, and an import is ownerless — so nobody may read it.
            proof.published_at = None
            session.commit()
    finally:
        engine.dispose()

    assert client.get(f"/api/proofs/{ids['a1i']}/citations").status_code == 404


def test_a_dependent_the_viewer_may_not_read_is_not_named_at_all(client, db):
    """A dependent is a proof, and an unreadable proof's *name* is not public.

    The asymmetry with a cross-reference is deliberate. A reference's target is a
    word the published corpus itself says, so showing it unlinked is truthful.
    A dependent is someone's draft, and its name is a string they typed into it —
    listing it here would publish it (found in review, where this test asserted
    the leak).
    """
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            dependent = session.scalars(select(Proof).where(Proof.name == "2a1i")).one()
            dependent.published_at = None
            session.commit()
    finally:
        engine.dispose()

    body = citations(client, ids["a1i"])
    assert body["cited_by"] == []
    assert body["cited_by_total"] == 0


def test_a_cited_theorem_nobody_may_read_still_shows_unlinked(client, db):
    """The other direction, where withholding the label would be the lie.

    This proof's own lines name it — that is a fact about the proof being read,
    not about the draft behind it — so the citation shows and only the link goes.
    """
    ids = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            cited = session.scalars(select(Proof).where(Proof.name == "a1i")).one()
            cited.published_at = None
            session.commit()
    finally:
        engine.dispose()

    cites = citations(client, ids["2a1i"])["cites"]
    assert [entry["label"] for entry in cites] == ["a1i"]
    assert cites[0]["proof_id"] is None


# ---------------------------------------------------------------------------
# Across a layer boundary
#
# A layered import files each statement against the layer its own section falls
# in, so a citation routinely points out of the citing proof's system. Both
# directions therefore walk the spine, not the one id.
# ---------------------------------------------------------------------------


def seed_layered(db_path) -> dict[str, str]:
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            import_corpus(session, parse(LAYERED_CITATION), name="c", plan=LAYERS)
            session.commit()
            proofs = list(session.scalars(select(Proof)))
            for proof in proofs:
                proof.published_at = proof.created_at
                proof.formal_system.published_at = proof.created_at
            session.commit()
            return {proof.name: str(proof.id) for proof in proofs}
    finally:
        engine.dispose()


def test_a_citation_resolves_into_a_layer_below(client, db):
    ids = seed_layered(db)

    body = citations(client, ids["zf-cites-pc"])

    # `pc-thm` is filed against the propositional root, two layers down.
    assert [entry["label"] for entry in body["cites"]] == ["pc-thm"]
    assert body["cites"][0]["proof_id"] == ids["pc-thm"]


def test_dependents_reach_the_layers_above(client, db):
    ids = seed_layered(db)

    body = citations(client, ids["pc-thm"])

    assert [entry["label"] for entry in body["cited_by"]] == ["zf-cites-pc"]
    assert body["cited_by"][0]["proof_id"] == ids["zf-cites-pc"]
