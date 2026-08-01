"""A theorem proved in one system, cited in a proof written in another.

(a) and (b) of docs/system-relationships-roadmap.md: a propositional theorem is
citable in first-order logic *and* in ZFC, and a first-order theorem is citable
in ZFC. The mechanism is `LibraryChain` — a citation resolves against the
system's own library and then its ancestors', nearest first.

Written as accepted/rejected **pairs** throughout. Every guard in this area errs
safe, so a bug shows up as a valid citation being refused, and a suite of
refusals cannot see that. The bound-variable cases are the sharpest: a proviso
that survives a layer boundary has to be shown refusing one instance *and*
admitting another, or a check that never runs passes just as well.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from copy import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db import FormalSystem, LibraryChain, effective_library
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.promoted_theorems_mapping import (
    load_theorems,
    store_theorem,
    theorem_digest,
)
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.layered_systems import (
    first_order_logic_spec,
    propositional_calculus_spec,
)
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed, seed_tower
from tests.test_systems_api import _register_login
from website.logical.declarative import build_spec
from website.logical.promotion import TheoremSpec, promote_spec


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "citation")
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
# Seeding a layer's library
# ---------------------------------------------------------------------------


def promote_into(db_path, system_id: str, spec: TheoremSpec) -> None:
    """Prove nothing; just put ``spec`` in ``system_id``'s library, with its terms.

    What a corpus import writes and what `POST /proofs/{id}/promote` will write
    (R3). Built against the system's *own* effective chain, exactly as its own
    verify would build it, so the digest stored is the one that guards it.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = session.get(FormalSystem, uuid.UUID(system_id))
            chain = _chain(session, system)
            effective, library = effective_library(chain)
            built = build_spec(effective)
            assert "errors" not in built, built["errors"]
            promoted = promote_spec(built["system"], spec)
            store_theorem(
                session,
                system,
                spec,
                {symbol.name: symbol for symbol in system.symbols},
                # `promoted_theorems` is `lazy="raise"` — an imported library is
                # tens of thousands and is never a collection to walk.
                position=session.scalar(
                    select(func.count())
                    .select_from(PromotedTheoremRow)
                    .where(PromotedTheoremRow.system_id == system.id)
                ),
                primitive=False,
                # The digest this system's *own* verify would stamp — which for
                # a layer with ancestors covers the whole chain beneath it, and
                # is what `LibraryChain` then checks it against.
                digest=theorem_digest(library.digest(system.id), spec),
                promoted=promoted,
            )
            session.commit()
    finally:
        engine.dispose()


def _chain(session: Session, system: FormalSystem) -> list[FormalSystem]:
    # The sync mirror of `systems.load_chain`, for a seeding helper that has no
    # request behind it.
    chain = [system]
    while chain[0].inherits_from_id is not None:
        parent = session.get(FormalSystem, chain[0].inherits_from_id)
        if parent is None:
            break
        chain.insert(0, parent)
    return chain


def resolve(db_path, system_id: str, labels: list[str], before=None) -> dict:
    """Promote ``labels`` against ``system_id``, through its whole chain.

    ``before`` runs after the system is built and before the library is read, for
    a test that needs to make something fatal only for the second half.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = session.get(FormalSystem, uuid.UUID(system_id))
            chain = _chain(session, system)
            # `effective_library`, not a chain assembled here: it is what the
            # verify route uses, and a test that rebuilt the ordering or the
            # per-layer digests itself would pass with either of them wrong.
            spec, library = effective_library(chain)
            built = build_spec(spec)["system"]
            context = copy(built.context)
            context.variables.update(built.build_context.variables)
            if before is not None:
                before()
            return load_theorems(session, library, labels, built, context)
    finally:
        engine.dispose()


def verify_proof(client, db_path, system_id: str, source: str) -> dict:
    """Check ``source`` in ``system_id`` through the stored-proof route.

    Not `POST /formal-systems/{id}/verify`, which builds the system and parses
    the text but resolves no library at all — so a citation of a *theorem* never
    resolves there, inherited or not. That is a gap of its own and older than
    inheritance; see the roadmap's R2 note.
    """
    created = client.post(
        "/api/proofs",
        json={"name": f"check-{uuid.uuid4().hex[:8]}", "formal_system_id": system_id,
              "source": source},
    )
    assert created.status_code == 201, created.text
    response = client.post(f"/api/proofs/{created.json()['id']}/verify")
    assert response.status_code == 200, response.text
    return response.json()


# `⊢ (P → P)`, the propositional identity — schematic in one `wff` metavariable,
# so its whole point is the instances it takes.
IDENTITY = TheoremSpec(
    label="id",
    statement="(P → P)",
    metavariables={"P": "formula"},
)


# ---------------------------------------------------------------------------
# (a) and (b): a theorem crosses the boundary
# ---------------------------------------------------------------------------


def test_a_propositional_theorem_resolves_in_first_order_logic(db, client):
    owner = _register_login(client, "up-one@example.com")
    pc, fol, _zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)

    assert set(resolve(db, fol, ["id"])) == {"id"}


def test_a_propositional_theorem_resolves_two_layers_up(db, client):
    # (a): "citable in FOL *and* in ZFC". Transitivity is not a second mechanism —
    # the chain is walked whole, so a grandparent is reached the same way.
    owner = _register_login(client, "up-two@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)

    assert set(resolve(db, zfc, ["id"])) == {"id"}


def test_a_first_order_theorem_resolves_in_zfc(db, client):
    # (b), and the case with a bound variable in the statement itself.
    owner = _register_login(client, "fol-up@example.com")
    _pc, fol, zfc = seed_tower(db, owner)
    promote_into(
        db,
        fol,
        TheoremSpec(
            label="alnex",
            statement="(∀x P → ¬∃x ¬P)",
            metavariables={"P": "formula", "x": "term"},
        ),
    )

    assert set(resolve(db, zfc, ["alnex"])) == {"alnex"}


def test_the_transfer_is_one_directional(db, client):
    # No downward transfer: a ZFC theorem is not a propositional one. The pair
    # for the tests above — the same chain, the same call, the other direction.
    owner = _register_login(client, "downward@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, zfc, TheoremSpec(label="zfc-only", statement="(P → P)",
                                      metavariables={"P": "formula"}))

    assert resolve(db, zfc, ["zfc-only"])
    assert resolve(db, pc, ["zfc-only"]) == {}


def test_a_sibling_system_is_not_in_scope(db, client):
    # Two children of one parent are not related to each other. Only the chain
    # *upward* resolves; sideways is nothing.
    owner = _register_login(client, "sibling@example.com")
    pc = seed(db, propositional_calculus_spec(), owner)
    left = seed(db, first_order_logic_spec("Left"), owner, pc)
    right = seed(db, first_order_logic_spec("Right"), owner, pc, published=False)
    promote_into(db, left, IDENTITY)

    assert resolve(db, left, ["id"])
    assert resolve(db, right, ["id"]) == {}


# ---------------------------------------------------------------------------
# The sort widening — the heart of it
# ---------------------------------------------------------------------------


def test_a_transferred_theorem_applies_to_formulas_its_own_system_cannot_spell(db, client):
    # PC proves `(P → P)` for `P` a *propositional* formula. Read in ZFC the same
    # statement quantifies over more: `P` may now be `∀x (x ∈ y)`, which the
    # system that proved it could not even write. That the citation *stands* is
    # the whole of §1.1's schematicity argument, and this is where it is checked.
    owner = _register_login(client, "widen@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)

    checked = verify_proof(client, db, zfc, "(∀x x ∈ y → ∀x x ∈ y) [id]")
    assert checked["success"] is True, checked["errors"]


def test_widening_introduces_no_capture_obligation(db, client):
    # The over-refusal this could easily become. `ax-1` transferred is
    # `(P → (Q → P))`; instantiated with a binder in `P` and a *free* `x` in `Q`,
    # nothing captures — the theorem has no binder of its own. A checker that
    # treated any binder in an instance as suspicious would refuse this, and
    # nothing else in the suite would notice.
    owner = _register_login(client, "no-capture@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(
        db,
        pc,
        TheoremSpec(
            label="simp",
            statement="(P → (Q → P))",
            metavariables={"P": "formula", "Q": "formula"},
        ),
    )

    checked = verify_proof(client, db, zfc, "(∀x x ∈ y → (x ∈ x → ∀x x ∈ y)) [simp]")
    assert checked["success"] is True, checked["errors"]


def test_a_transferred_proviso_binds_in_the_citing_system(db, client):
    # The accepted/rejected pair, across a layer boundary. `vacuous` is proved in
    # FOL under `not occurs(x, P)`; cited in ZFC it must still refuse an instance
    # whose formula mentions the quantified variable, and still admit one that
    # does not. Either half alone is passed by a proviso that is not enforced at
    # all.
    owner = _register_login(client, "proviso@example.com")
    _pc, fol, zfc = seed_tower(db, owner)
    promote_into(
        db,
        fol,
        TheoremSpec(
            label="vacuous",
            statement="(P → ∀x P)",
            metavariables={"P": "formula", "x": "term"},
            distinct=("not occurs(x, P)",),
        ),
    )

    def verify(text: str) -> bool:
        return verify_proof(client, db, zfc, text)["success"]

    assert verify("(z ∈ y → ∀x z ∈ y) [vacuous]")
    assert not verify("(x ∈ y → ∀x x ∈ y) [vacuous]")


# ---------------------------------------------------------------------------
# Shadowing, and the terms
# ---------------------------------------------------------------------------


def test_a_label_resolves_to_the_nearest_system_that_has_it(db, client):
    # Both layers claim `id`, and they say different things. The child's is the
    # answer — the same rule the rest of inheritance follows — asserted by which
    # statement comes back, not merely by which row was read.
    owner = _register_login(client, "shadow@example.com")
    pc, fol, _zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)
    promote_into(
        db,
        fol,
        TheoremSpec(
            label="id",
            statement="(∀x P → ∀x P)",
            metavariables={"P": "formula", "x": "term"},
        ),
    )

    (nearer,) = resolve(db, fol, ["id"]).values()
    assert nearer.deduction.pattern == "(∀x P → ∀x P)"
    # And the ancestor's own resolution is untouched by the child shadowing it.
    (original,) = resolve(db, pc, ["id"]).values()
    assert original.deduction.pattern == "(P → P)"


def test_an_ancestors_cached_term_is_used_rather_than_re_parsed(db, client, monkeypatch):
    # §3.1: transfer is a term-graph read, not a re-parse. The ancestor's stored
    # term is rebuilt in the *child's* context — same constructor names, the
    # child's wider slot sorts — so no statement is composed against the grammar.
    # Asserted by making a compose fatal, which is the only way this stays true
    # under later edits.
    owner = _register_login(client, "cached@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)

    import website.logical.build_context as build_context

    def refuse(*_args, **_kwargs):
        raise AssertionError("a cross-layer citation must not re-compose its term")

    # Patched *after* the system is built — building composes the rules' own
    # schema terms, which is a different use of the same function.
    assert set(
        resolve(
            db, zfc, ["id"],
            before=lambda: monkeypatch.setattr(
                build_context, "compose_schema_term", refuse
            ),
        )
    ) == {"id"}


def test_falling_back_to_a_parse_costs_time_and_not_a_difference(db, client):
    # The other half of the contract: a term that cannot be used is a *miss*.
    # Stripping the ancestor's digest forces the parse, and the theorem that
    # comes back must be the same one.
    owner = _register_login(client, "fallback@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)
    cached = resolve(db, zfc, ["id"])["id"]

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.execute(
                update(PromotedTheoremRow)
                .where(PromotedTheoremRow.label == "id")
                .values(schema_digest="stale")
            )
            session.commit()
    finally:
        engine.dispose()

    parsed = resolve(db, zfc, ["id"])["id"]
    assert parsed.deduction.pattern == cached.deduction.pattern
    assert parsed.deduction.schema_term is not None


def test_an_ancestors_entry_is_guarded_by_the_ancestors_own_digest(db, client):
    # The subtlety `LibraryChain` exists for. Checked against the *citing*
    # system's digest an ancestor's entry would miss every time — the digests
    # cover different grammars by construction — so the cache would be dead for
    # exactly the citations it matters most for.
    owner = _register_login(client, "digest@example.com")
    pc, _fol, zfc = seed_tower(db, owner)
    promote_into(db, pc, IDENTITY)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            zfc_system = session.get(FormalSystem, uuid.UUID(zfc))
            _spec, library = effective_library(_chain(session, zfc_system))
            own = library.digest(uuid.UUID(pc))
            citing = library.digest(uuid.UUID(zfc))
    finally:
        engine.dispose()

    assert own != citing, "the two grammars must differ for this to mean anything"
    assert theorem_digest(own, IDENTITY) != theorem_digest(citing, IDENTITY)


# ---------------------------------------------------------------------------
# The single-system case is unchanged
# ---------------------------------------------------------------------------


def test_a_system_with_no_ancestors_resolves_exactly_as_before(db, client):
    owner = _register_login(client, "flat@example.com")
    alone = seed(db, propositional_calculus_spec(), owner, published=False)
    promote_into(db, alone, IDENTITY)

    assert set(resolve(db, alone, ["id"])) == {"id"}
    assert resolve(db, alone, ["no-such-label"]) == {}
