"""A proof, promoted into its system's library, and cited from another system.

R3 of docs/system-relationships-roadmap.md. R2 made an ancestor's library
resolvable from a descendant; until now only a corpus import could put anything
in one, so (a)/(b) reached imported work and nothing a person proved. This is
`POST /proofs/{id}/promote`.

Held to §8.0's four parts. The worked example is the PC/FOL/ZFC tower and a real
Łukasiewicz derivation of `(P → P)` — five lines, two of them modus ponens, so a
promotion that took the wrong line has four other answers available. The valid
case that matters is the citation two layers up; the rejections are one per
guard; and the negative controls are the two ways this could look like it works
without working — a statement that came from re-parsing text rather than from the
term the checker ran on, and a retirement that removes the entry while leaving
the verdicts that rested on it standing.
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
from app.db import FormalSystem, Proof
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.proof_lines import ProofLineRow
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed_tower
from tests.test_systems_api import _register_login


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "promotion")
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


# ---------------------------------------------------------------------------
# The worked example
# ---------------------------------------------------------------------------

def identity_proof(formula: str) -> str:
    """`⊢ (A → A)` in the three Łukasiewicz axioms, for any formula ``A``.

    The shortest derivation that is not itself an axiom instance: two modus
    ponens steps, and a conclusion that is neither the first line nor the
    last-but-one, so "the proof's conclusion" has four wrong answers to be told
    apart from. Parameterised in the *test*, not in the system — the axioms take
    any formula, and what gets promoted is whichever instance was written.
    """
    a = formula
    return (
        f"(({a} → (({a} → {a}) → {a})) → (({a} → ({a} → {a})) → ({a} → {a}))) [ax-2]\n"
        f"({a} → (({a} → {a}) → {a})) [ax-1]\n"
        f"(({a} → ({a} → {a})) → ({a} → {a})) [MP, 2, 1]\n"
        f"({a} → ({a} → {a})) [ax-1]\n"
        f"({a} → {a}) [MP, 4, 3]"
    )


IDENTITY_PROOF = identity_proof("P")

# The same derivation with its last step removed: still valid, but concluding
# something else. What a source edit turns the proof above into.
PARTIAL_PROOF = "\n".join(IDENTITY_PROOF.splitlines()[:3])


def make_proof(client, system_id: str, source: str, name: str | None = None) -> str:
    created = client.post(
        "/api/proofs",
        json={
            "name": name or f"proof-{uuid.uuid4().hex[:8]}",
            "formal_system_id": system_id,
            "source": source,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def publish(client, proof_id: str) -> dict:
    response = client.patch(f"/api/proofs/{proof_id}", json={"published": True})
    assert response.status_code == 200, response.text
    return response.json()


def proved_and_published(client, system_id: str, source: str = IDENTITY_PROOF) -> str:
    """A proof that stands and is public — the state promotion requires."""
    proof_id = make_proof(client, system_id, source)
    publish(client, proof_id)
    return proof_id


def promote(client, proof_id: str, label: str | None = None) -> tuple[int, dict]:
    body: dict = {} if label is None else {"label": label}
    response = client.post(f"/api/proofs/{proof_id}/promote", json=body)
    return response.status_code, (response.json() if response.content else {})


def verify(client, proof_id: str) -> dict:
    response = client.post(f"/api/proofs/{proof_id}/verify")
    assert response.status_code == 200, response.text
    return response.json()


def check_in(client, system_id: str, source: str) -> dict:
    """Write a fresh proof in ``system_id`` and check it."""
    return verify(client, make_proof(client, system_id, source))


def tower(db, client, email: str) -> tuple[str, str, str]:
    owner = _register_login(client, email)
    pc, fol, zfc = seed_tower(db, owner, published_top=True)
    return pc, fol, zfc


# ---------------------------------------------------------------------------
# The valid case: proved in PC, cited in ZFC
# ---------------------------------------------------------------------------


def test_a_promoted_propositional_theorem_is_citable_two_layers_up(db, client):
    # (a) end to end, for work a person proved rather than imported: the lemma is
    # written and checked in propositional calculus, promoted, and cited from a
    # proof written in ZFC — a system two layers above the one that proved it.
    pc, _fol, zfc = tower(db, client, "promote-cite@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    status, entry = promote(client, proof, "id")
    assert status == 201, entry
    assert entry["label"] == "id"
    assert entry["statement"] == "(P → P)"

    checked = check_in(client, zfc, "(P → P) [id]")
    assert checked["success"] is True, checked


def test_a_promoted_theorem_is_citable_in_its_own_system(db, client):
    # The degenerate layer of the same mechanism: a citation resolves against the
    # system's own library first, so promotion is useful without any inheritance.
    pc, _fol, _zfc = tower(db, client, "promote-here@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert check_in(client, pc, "(P → P) [id]")["success"] is True


def test_promotion_composes_nothing_because_it_was_handed_the_checked_term(monkeypatch):
    # The negative control on §3.1, and the one that actually discriminates: the
    # stored-row assertion below cannot, because the term graph interns by
    # digest, so a statement re-parsed from text lands on the *same row* and
    # looks identical from the database.
    #
    # What tells them apart is that promotion must not compose at all. Make
    # composing fatal after the system is built and the proof checked, then
    # promote: the schema term has to be the very object the checker unified
    # against, not one derived again from `(P → P)`.
    from website.logical import build_context
    from website.logical.declarative import build_spec
    from website.logical.promotion import proved_theorem

    from tests.layered_systems import propositional_calculus_spec

    built = build_spec(propositional_calculus_spec())
    assert "errors" not in built, built["errors"]
    system = built["system"]
    proof = system.parse(IDENTITY_PROOF)
    assert proof.valid is True

    def fatal(*_args, **_kwargs):
        raise AssertionError("promotion re-composed a term it had already been given")

    monkeypatch.setattr(build_context, "compose_schema_term", fatal)
    _spec, theorem = proved_theorem(system, proof, "id")

    assert theorem.deduction.schema_term is proof.root_scope.conclusion.formula_term


def test_the_entry_interns_to_the_conclusion_lines_term_row(db, client):
    # The storage half of the same claim: the entry and the line that established
    # it point at one row in the shared term graph, so a citation two layers up
    # reads the term the check ran on rather than a copy of it.
    #
    # By term id rather than by statement string — two terms that render
    # identically can differ in constructor, and so in sort, and a string
    # comparison passes for both. (What this cannot see is a re-parse, which
    # interns to the same row; that is the test above.)
    pc, _fol, _zfc = tower(db, client, "same-term@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalar(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
            )
            conclusion = session.scalar(
                select(ProofLineRow)
                .where(
                    ProofLineRow.proof_id == uuid.UUID(proof),
                    ProofLineRow.number == 5,
                )
            )
            assert conclusion.term_id is not None
            assert entry.statement_term_id == conclusion.term_id
    finally:
        engine.dispose()


def test_the_conclusion_promoted_is_the_last_line_not_the_first(db, client):
    # The negative control on *which* line was taken. Line 1 is an `ax-2`
    # instance and line 3 is a modus ponens step, both perfectly promotable — so
    # a promotion that reached for the wrong line would still have produced an
    # entry and still have been citable. Only the statement tells them apart.
    pc, _fol, _zfc = tower(db, client, "which-line@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    _status, entry = promote(client, proof, "id")

    assert entry["statement"] == "(P → P)"
    assert check_in(client, pc, "((P → (P → P)) → (P → P)) [id]")["success"] is False


def test_a_ground_theorem_justifies_its_own_statement_and_no_other_instance(db, client):
    # R3 promotes what the proof concluded, verbatim: `(P → P)` and not
    # `∀ φ. (φ → φ)`. The proof would go through for any propositional letter,
    # but nothing in it *says* so — nominating metavariables is R3a — and an
    # entry that silently generalised would be asserting more than was checked.
    pc, _fol, _zfc = tower(db, client, "ground@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert check_in(client, pc, "(P → P) [id]")["success"] is True
    assert check_in(client, pc, "(Q → Q) [id]")["success"] is False


def test_a_promoted_theorem_carries_into_a_compound_step(db, client):
    # The citation is a real premise, not just a line that restates the entry: the
    # promoted `(P → P)` feeds modus ponens against an `ax-1` instance in ZFC,
    # two layers above where it was proved.
    pc, _fol, zfc = tower(db, client, "compound@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    checked = check_in(
        client,
        zfc,
        "(P → P) [id]\n"
        "((P → P) → (x = y → (P → P))) [ax-1]\n"
        "(x = y → (P → P)) [MP, 1, 2]",
    )
    assert checked["success"] is True, checked


# ---------------------------------------------------------------------------
# The guards, one rejection each
# ---------------------------------------------------------------------------


def test_an_invalid_proof_cannot_be_promoted(db, client):
    pc, _fol, _zfc = tower(db, client, "invalid@example.com")
    # `[MP, 1]` cites one antecedent where modus ponens takes two.
    proof = make_proof(client, pc, "(P → (P → P)) [ax-1]\n(P → P) [MP, 1]")

    status, body = promote(client, proof, "bogus")
    # Refused before validity is even reached: an unpublished proof is not a
    # candidate, and this one could not be published either.
    assert status == 400, body
    assert "publish" in str(body).lower()


def test_a_valid_but_unpublished_proof_cannot_be_promoted(db, client):
    # The guard that is not about soundness but about exposure: R2 makes this
    # library readable from every descendant system, and a descendant may be
    # someone else's, so promoting a draft would hand out its statement.
    pc, _fol, _zfc = tower(db, client, "draft@example.com")
    proof = make_proof(client, pc, IDENTITY_PROOF)
    assert verify(client, proof)["success"] is True

    status, body = promote(client, proof, "id")
    assert status == 400, body
    assert "published" in str(body).lower()


def test_a_proof_carrying_a_warning_establishes_no_theorem():
    # A warning is unresolved doubt about whether the proof stands, so it must
    # not become something other proofs rest on — the same rule
    # `_is_usable_lemma` applies to a cited lemma.
    #
    # Tested against the engine rather than the route because **no check
    # currently raises a warning**: `warning_message` is carried by the line, the
    # row and the loader, and nothing sets it. The guard is live for the day
    # something does, and this is what says it works then.
    from website.logical.declarative import build_spec
    from website.logical.promotion import proved_theorem

    from tests.layered_systems import propositional_calculus_spec

    system = build_spec(propositional_calculus_spec())["system"]
    proof = system.parse(IDENTITY_PROOF)
    assert proof.valid is True
    proof.has_warnings = True

    with pytest.raises(ValueError, match="warning"):
        proved_theorem(system, proof, "id")


def test_an_unusable_proof_is_refused_by_the_route(db, client, monkeypatch):
    # The wiring for the guard above: whatever makes a proof unusable, the route
    # answers 422 rather than promoting it. Forced, since the only reachable way
    # to be unusable today — not verifying — is already refused a publish, and
    # publication is the earlier gate.
    import app.routers.proofs as proofs_router

    pc, _fol, _zfc = tower(db, client, "unusable@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    monkeypatch.setattr(proofs_router, "_is_usable_lemma", lambda _proof: False)
    status, body = promote(client, proof, "id")

    assert status == 422, body


def test_a_proof_with_no_conclusion_cannot_be_promoted(db, client):
    # A proof of nothing: commentary only. Vacuously valid, publishable, and
    # establishes no theorem — which the engine says rather than the router
    # guessing (`promotion.proved_theorem`).
    pc, _fol, _zfc = tower(db, client, "empty@example.com")
    proof = proved_and_published(client, pc, "")

    status, body = promote(client, proof, "nothing")
    assert status == 422, body
    assert "conclusion" in str(body).lower()


def test_a_label_an_inference_rule_already_carries_is_refused(db, client):
    # A citation resolves rules before theorems, so this entry could never be
    # reached — better a 409 than a row nothing can cite.
    pc, _fol, _zfc = tower(db, client, "shadowed@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    status, body = promote(client, proof, "MP")
    assert status == 409, body
    assert "inference rule" in str(body).lower()


def test_a_label_another_proof_already_promoted_is_refused(db, client):
    # One label, one theorem: a citation names an entry by label, so two would
    # make `[id]` ambiguous within a single system.
    pc, _fol, _zfc = tower(db, client, "taken@example.com")
    first = proved_and_published(client, pc, IDENTITY_PROOF)
    second = proved_and_published(client, pc, PARTIAL_PROOF)
    assert promote(client, first, "id")[0] == 201

    status, body = promote(client, second, "id")
    assert status == 409, body


def test_a_label_an_import_already_carries_is_refused(db, client):
    # The NULL case of the check above. An imported entry has no `proved_by_id`,
    # so "not this proof's entry" written as `!=` is NULL rather than true and
    # the clash reaches the unique index — a 500 where the author should be told
    # to pick another label.
    pc, _fol, _zfc = tower(db, client, "import-clash@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalar(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
            )
            entry.proved_by_id = None
            session.commit()
    finally:
        engine.dispose()

    other = proved_and_published(client, pc, PARTIAL_PROOF)
    status, body = promote(client, other, "id")
    assert status == 409, body


def test_a_proof_in_someone_elses_system_is_not_promotable(db, client):
    # 404 rather than 403, as everywhere else in this router: another owner's
    # proof id must not be confirmable.
    pc, _fol, _zfc = tower(db, client, "owner@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    _register_login(client, "stranger@example.com")
    assert promote(client, proof, "id")[0] == 404


# ---------------------------------------------------------------------------
# Retirement: the entry cannot outlive the proof standing
# ---------------------------------------------------------------------------


def test_editing_the_proof_retires_the_entry(db, client):
    # The roadmap's case: cite a promoted entry after the proof was edited. The
    # entry must be *retired*, not left asserting a conclusion the proof no
    # longer reaches.
    pc, _fol, zfc = tower(db, client, "edited@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201
    assert check_in(client, zfc, "(P → P) [id]")["success"] is True

    # Truncating the proof leaves it valid and published, concluding something
    # else — which is exactly the case a stale entry would survive.
    edited = client.patch(f"/api/proofs/{proof}", json={"source": PARTIAL_PROOF})
    assert edited.status_code == 200, edited.text
    assert edited.json()["theorem"] is None

    assert check_in(client, zfc, "(P → P) [id]")["success"] is False


def test_unpublishing_the_proof_retires_the_entry(db, client):
    pc, _fol, zfc = tower(db, client, "unpublished@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    response = client.patch(f"/api/proofs/{proof}", json={"published": False})
    assert response.status_code == 200, response.text
    assert response.json()["theorem"] is None

    assert check_in(client, zfc, "(P → P) [id]")["success"] is False


def test_deleting_the_proof_retires_the_entry(db, client):
    pc, _fol, zfc = tower(db, client, "deleted@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert client.delete(f"/api/proofs/{proof}").status_code == 204
    assert check_in(client, zfc, "(P → P) [id]")["success"] is False


def test_deleting_the_proof_invalidates_what_cited_its_entry(db, client):
    # The entry goes with the proof by `ON DELETE CASCADE` whatever this route
    # does, so the test above passes even with the delete path's retirement
    # removed. What the cascade does *not* do is reach the proofs that already
    # verified against the entry — they keep a standing verdict resting on a
    # theorem the database no longer has.
    pc, _fol, zfc = tower(db, client, "deleted-citer@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    citing = make_proof(client, zfc, "(P → P) [id]")
    assert verify(client, citing)["success"] is True

    assert client.delete(f"/api/proofs/{proof}").status_code == 204

    assert client.get(f"/api/proofs/{citing}").json()["valid"] is None


def test_retiring_invalidates_the_verdicts_that_rested_on_the_entry(db, client):
    # The negative control on retirement. Removing the row is the easy half:
    # without this, a ZFC proof that already verified keeps `valid: true` and its
    # stored lines, so *another* proof citing it as a lemma reads that verdict
    # from the rows and rests on a theorem that is gone.
    pc, _fol, zfc = tower(db, client, "cascade@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    citing = make_proof(client, zfc, "(P → P) [id]")
    assert verify(client, citing)["success"] is True

    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204

    detail = client.get(f"/api/proofs/{citing}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["valid"] is None

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            lines = session.scalars(
                select(ProofLineRow.id).where(
                    ProofLineRow.proof_id == uuid.UUID(citing)
                )
            ).all()
            assert lines == []
    finally:
        engine.dispose()


def test_retiring_leaves_a_proof_that_never_cited_the_entry_alone(db, client):
    # The other half: a sweep that invalidated every proof in the tower would
    # pass the test above for the wrong reason. A ZFC proof citing nothing keeps
    # its verdict.
    pc, _fol, zfc = tower(db, client, "untouched@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    bystander = make_proof(client, zfc, "(P → (P → P)) [ax-1]")
    assert verify(client, bystander)["success"] is True

    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204

    assert client.get(f"/api/proofs/{bystander}").json()["valid"] is True


def test_a_descendants_own_entry_of_the_same_label_shadows_and_survives(db, client):
    # A label declared in two layers resolves to the nearer one, so the ZFC proof
    # was never citing PC's entry — retiring PC's must not disturb it. The
    # shadowing rule the resolver follows, followed here too.
    pc, _fol, zfc = tower(db, client, "shadow@example.com")
    lower = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, lower, "id")[0] == 201

    # ZFC's own `id`, proved there and concluding the same thing.
    nearer = proved_and_published(client, zfc, IDENTITY_PROOF)
    assert promote(client, nearer, "id")[0] == 201

    citing = make_proof(client, zfc, "(P → P) [id]")
    assert verify(client, citing)["success"] is True

    assert client.delete(f"/api/proofs/{lower}/promote").status_code == 204

    assert client.get(f"/api/proofs/{citing}").json()["valid"] is True
    assert check_in(client, zfc, "(P → P) [id]")["success"] is True


def test_retiring_a_proof_that_promoted_nothing_is_a_no_op(db, client):
    pc, _fol, _zfc = tower(db, client, "noop@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204


# ---------------------------------------------------------------------------
# Re-promotion, and the links between the two rows
# ---------------------------------------------------------------------------


def test_re_promoting_replaces_the_entry_rather_than_adding_one(db, client):
    pc, _fol, _zfc = tower(db, client, "repromote@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    first = promote(client, proof, "id")[1]
    second = promote(client, proof, "id")[1]

    assert second["id"] != first["id"]
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(PromotedTheoremRow.id).where(
                    PromotedTheoremRow.system_id == uuid.UUID(pc)
                )
            ).all()
            assert [str(row) for row in rows] == [second["id"]]
    finally:
        engine.dispose()


def test_re_promoting_after_an_edit_states_the_new_conclusion(db, client):
    # Retirement on edit is not the end of the story: the author fixes the proof
    # and promotes again, and the entry then says what the proof now concludes.
    pc, _fol, zfc = tower(db, client, "restate@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    assert client.patch(
        f"/api/proofs/{proof}", json={"source": PARTIAL_PROOF}
    ).status_code == 200
    status, entry = promote(client, proof, "id")

    assert status == 201, entry
    assert entry["statement"] == "((P → (P → P)) → (P → P))"
    assert check_in(client, zfc, "((P → (P → P)) → (P → P)) [id]")["success"] is True
    assert check_in(client, zfc, "(P → P) [id]")["success"] is False


def test_the_proof_points_at_the_entry_and_the_entry_at_the_proof(db, client):
    # Both directions, because they say different things: `proofs.theorem_id` is
    # which entry's hypotheses this proof may cite, `promoted_theorems.proved_by_id`
    # is which proof warrants the entry. Only the second discriminates a
    # promotion from an import, which is what retirement turns on.
    pc, _fol, _zfc = tower(db, client, "links@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    _status, entry = promote(client, proof, "id")

    assert entry["proved_by_id"] == proof
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            stored = session.get(Proof, uuid.UUID(proof))
            assert str(stored.theorem_id) == entry["id"]
    finally:
        engine.dispose()


def test_the_proof_detail_reports_the_entry_it_established(db, client):
    pc, _fol, _zfc = tower(db, client, "detail@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    assert client.get(f"/api/proofs/{proof}").json()["theorem"] is None
    promote(client, proof, "id")
    theorem = client.get(f"/api/proofs/{proof}").json()["theorem"]

    assert theorem["label"] == "id"
    assert theorem["statement"] == "(P → P)"
    assert theorem["proved_by_id"] == proof


def test_an_imported_entry_is_not_retired_by_editing_its_proof(db, client):
    # The reason `proved_by_id` exists. An imported library entry's warrant is the
    # corpus, not the stored proof, so an edit to that proof withdraws nothing —
    # and a blanket "the proof changed, drop its entry" rule would delete a
    # 49,000-theorem import one theorem at a time.
    pc, _fol, _zfc = tower(db, client, "imported@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    # Make the entry look imported: keep the proof's link to it, drop the entry's
    # link back — exactly the shape `_link_proofs_to_theorems` leaves behind.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalar(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
            )
            entry.proved_by_id = None
            session.commit()
    finally:
        engine.dispose()

    assert client.patch(
        f"/api/proofs/{proof}", json={"source": PARTIAL_PROOF}
    ).status_code == 200

    assert check_in(client, pc, "(P → P) [id]")["success"] is True


# ---------------------------------------------------------------------------
# Bound variables across the boundary
# ---------------------------------------------------------------------------


def test_a_quantified_theorem_proved_in_fol_is_citable_in_zfc(db, client):
    # §8.0's binder case. `∀x (P → P)` is proved in first-order logic by
    # generalising the propositional identity — so the statement carries a binder
    # introduced by the layer that proved it, and the citation two layers up has
    # to rebuild that binder's term against ZFC's wider grammar.
    _pc, fol, zfc = tower(db, client, "binder@example.com")
    proof = proved_and_published(
        client, fol, IDENTITY_PROOF + "\n∀x (P → P) [GEN, 5]"
    )

    status, entry = promote(client, proof, "gen-id")
    assert status == 201, entry
    assert entry["statement"] == "∀x (P → P)"

    assert check_in(client, zfc, "∀x (P → P) [gen-id]")["success"] is True
    # And it is still the ground theorem it was promoted as: a different bound
    # variable is a different statement, not an instance of this one.
    assert check_in(client, zfc, "∀y (P → P) [gen-id]")["success"] is False


def test_a_theorem_stated_in_an_ancestors_defined_notation_is_citable_above_it(db, client):
    # The same derivation over `(P ∧ Q)`, so the promoted statement is a compound
    # built from PC's `∧` — notation the propositional layer declares and `df-an`
    # gives meaning to. Citing it from ZFC rebuilds that constructor from ZFC's
    # own chain: the term-graph read §3.1 describes, over a grammar where `∧` is
    # inherited rather than declared.
    pc, _fol, zfc = tower(db, client, "defined@example.com")
    proof = proved_and_published(client, pc, identity_proof("(P ∧ Q)"))
    status, entry = promote(client, proof, "and-id")

    assert status == 201, entry
    assert entry["statement"] == "((P ∧ Q) → (P ∧ Q))"
    assert check_in(client, zfc, "((P ∧ Q) → (P ∧ Q)) [and-id]")["success"] is True


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def test_promotion_and_retirement_take_the_system_lock(db, client, monkeypatch):
    # Both write rows a concurrent verify reads. Asserted by observing the lock
    # is taken, as everywhere else in this router — the exclusion itself is only
    # observable against a real Postgres.
    import app.routers.proofs as proofs_router

    locked: list[uuid.UUID] = []
    original = proofs_router.lock_system

    async def record(session, system_id):
        locked.append(system_id)
        await original(session, system_id)

    pc, _fol, _zfc = tower(db, client, "locking@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)

    monkeypatch.setattr(proofs_router, "lock_system", record)
    assert promote(client, proof, "id")[0] == 201
    assert uuid.UUID(pc) in locked

    locked.clear()
    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204
    assert uuid.UUID(pc) in locked


def test_the_seeded_tower_is_the_one_these_tests_assume(db, client):
    # A guard on the fixture rather than on the code: every rejection above would
    # also pass against a tower that did not build at all.
    pc, fol, zfc = tower(db, client, "fixture@example.com")
    for system_id in (pc, fol, zfc):
        response = client.post(f"/api/formal-systems/{system_id}/validate")
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True, response.json().get("errors")

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            published = session.scalars(
                select(FormalSystem.published_at).where(
                    FormalSystem.id.in_([uuid.UUID(i) for i in (pc, fol, zfc)])
                )
            ).all()
            assert all(stamp is not None for stamp in published)
    finally:
        engine.dispose()


def test_a_published_system_is_what_promotion_needs(db, client):
    # Publication of the *proof* is the gate, and it requires a published system —
    # so a draft system cannot host a promotion at all. Pinned because it is the
    # premise §9.11's frozen-ancestor argument rests on.
    owner = _register_login(client, "draft-system@example.com")
    pc, _fol, _zfc = seed_tower(db, owner, published_top=False)
    del owner

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            system = session.get(FormalSystem, uuid.UUID(pc))
            system.published_at = None
            session.commit()
    finally:
        engine.dispose()

    proof = make_proof(client, pc, IDENTITY_PROOF)
    response = client.patch(f"/api/proofs/{proof}", json={"published": True})
    assert response.status_code == 400, response.text
    assert promote(client, proof, "id")[0] == 400


def test_promotion_stamps_the_digest_that_guards_its_terms(db, client):
    # A negative control on the cache. The entry's `schema_digest` has to be the
    # one this system's own verify computes, or the cached term misses on every
    # citation and the statement is silently re-parsed against a wider grammar —
    # the failure §9.11 exists to prevent, which no citation test can see because
    # the re-parse usually produces the same answer.
    pc, _fol, zfc = tower(db, client, "digest@example.com")
    proof = proved_and_published(client, pc, IDENTITY_PROOF)
    assert promote(client, proof, "id")[0] == 201

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalar(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
            )
            assert entry.schema_digest is not None
            assert entry.statement_term_id is not None
            # Break the term while leaving the digest: if the citation still
            # resolves, it resolved by re-parsing and the cache was never read.
            entry.statement_term_id = None
            session.commit()
    finally:
        engine.dispose()

    assert check_in(client, zfc, "(P → P) [id]")["success"] is False


def test_a_stale_timestamp_is_not_what_gates_promotion(db, client):
    # `published_at` is set by the route, never by the caller; a client that
    # sends one is ignored rather than trusted.
    pc, _fol, _zfc = tower(db, client, "stamp@example.com")
    proof = make_proof(client, pc, IDENTITY_PROOF)
    client.patch(
        f"/api/proofs/{proof}",
        json={"published_at": datetime.now(timezone.utc).isoformat()},
    )

    assert promote(client, proof, "id")[0] == 400
