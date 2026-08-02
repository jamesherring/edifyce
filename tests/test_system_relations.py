"""A theorem crossing a relation edge, rather than the inheritance spine.

R4 of docs/system-relationships-roadmap.md. The spine says one thing well —
single-parent, grammar-extending — and `system_relations` says the rest: a
second parent (R4a), and a **rename** (R4b). Both halves are here, and they
divide as the tables do: what an edge *resolves* is identity on names, which is
what a second parent is, and what a map lets it resolve is everything below
"R4b: the rename". The map's own checks are `tests/test_translation.py`'s, since
they are a question about two grammars rather than about any row.

Written as accepted/rejected pairs, for §8.0's reason: every gate here errs
closed, so a bug shows up as a valid citation being refused, and a suite of
refusals cannot tell that from a gate that refuses everything.
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
from sqlalchemy import NullPool, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db import (
    FormalSystem,
    LibraryChain,
    PromotedTheoremRow,
    SystemRelationObligationRow,
    SystemRelationRow,
    SystemRelationSortRow,
    SystemRelationSymbolRow,
    effective_library,
    effective_spec,
    related_layers,
)
from app.db.promoted_theorems_mapping import load_theorems
from app.db.session import get_session
from app.main import app
from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.layered_systems import (
    FOL_RENAME,
    PC_RENAME,
    first_order_logic_spec,
    narrowed_propositional_calculus_spec,
    propositional_calculus_spec,
    renamed_first_order_spec,
    renamed_propositional_calculus_spec,
    respelled_propositional_calculus_spec,
)
from website.logical.declarative import build_spec
from website.logical.promotion import TheoremSpec
from tests.test_cross_system_citation import (
    IDENTITY,
    _chain,
    promote_into,
    verify_proof,
)
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed
from tests.test_systems_api import _register_login

@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "relations")
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


def relate(
    db_path,
    source: str,
    target: str,
    *,
    status: str = "discharged",
    kind: str = "extension",
    obligations: list[tuple[str, str | None]] | None = None,
    sorts: dict[str, str] | None = None,
    symbols: dict[str, str] | None = None,
) -> str:
    """Store one edge, with an obligation per named source primitive.

    Written straight to the rows: the edge CRUD is R4's third piece, and what
    this module is about is what an edge *resolves*.

    ``sorts`` and ``symbols`` are the rename (R4b), absent for the identity.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            edge = SystemRelationRow(
                source_system_id=uuid.UUID(source),
                target_system_id=uuid.UUID(target),
                kind=kind,
                status=status,
            )
            for index, (original, renamed) in enumerate((sorts or {}).items()):
                edge.sorts.append(
                    SystemRelationSortRow(
                        position=index, source_sort=original, target_sort=renamed
                    )
                )
            for index, (original, renamed) in enumerate((symbols or {}).items()):
                edge.symbols.append(
                    SystemRelationSymbolRow(
                        position=index, source_symbol=original, target_symbol=renamed
                    )
                )
            for index, (label, discharged_by) in enumerate(obligations or []):
                edge.obligations.append(
                    SystemRelationObligationRow(
                        position=index,
                        source_label=label,
                        discharged_by_primitive=discharged_by,
                        status="discharged" if discharged_by else "draft",
                    )
                )
            session.add(edge)
            session.commit()
            return str(edge.id)
    finally:
        engine.dispose()


def two_systems(db_path, client, email: str) -> tuple[str, str]:
    """Two *unrelated* published systems, each able to state `(P → P)`.

    Siblings rather than a tower: an edge between them is the case the spine
    cannot express, which is the whole reason this table exists.
    """
    owner = _register_login(client, email)
    left = seed(db_path, propositional_calculus_spec("Left"), owner, None)
    right = seed(db_path, propositional_calculus_spec("Right"), owner, None)
    return left, right


# ---------------------------------------------------------------------------
# What an edge resolves
# ---------------------------------------------------------------------------


def test_a_theorem_crosses_a_discharged_edge(db, client):
    # The headline: `Right` neither inherits from `Left` nor is inherited by it,
    # and a theorem proved in `Left` is citable in `Right` because an edge says
    # so. Nothing about the spine reaches here.
    left, right = two_systems(db, client, "edge@example.com")
    promote_into(db, left, IDENTITY)

    checked = verify_proof(client, db, right, "(P → P) [id]")
    assert checked["success"] is False, "sibling systems must not resolve by default"

    relate(db, left, right)
    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True


def test_a_draft_edge_resolves_nothing(db, client):
    # `status` is the gate: an edge under construction must not transfer a
    # theorem on the strength of the obligations that happen to be discharged.
    left, right = two_systems(db, client, "draft-edge@example.com")
    promote_into(db, left, IDENTITY)
    relate(db, left, right, status="draft")

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False


def test_an_edge_with_an_outstanding_obligation_resolves_nothing(db, client):
    # §2's rule, as rows: a theorem transfers only when every primitive of the
    # source is available on the other side. One undischarged obligation is one
    # primitive that may not be, and the theorem could have used it.
    #
    # The edge's own `status` says discharged here, deliberately: the column is a
    # cache of the obligations' verdict, and a stale cache must fail closed.
    left, right = two_systems(db, client, "outstanding@example.com")
    promote_into(db, left, IDENTITY)
    relate(
        db,
        left,
        right,
        obligations=[("ax-1", "ax-1"), ("ax-2", "ax-2"), ("MP", None)],
    )

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False


def test_discharging_the_last_obligation_is_what_makes_it_resolve(db, client):
    # The same proof, re-run: nothing about it changes, and it goes from failing
    # to standing because the edge was completed. That pairing is what says the
    # obligations are the gate rather than something else about the setup.
    left, right = two_systems(db, client, "last-obligation@example.com")
    promote_into(db, left, IDENTITY)
    edge = relate(db, left, right, obligations=[("MP", None)])

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            outstanding = session.scalar(
                select(SystemRelationObligationRow).where(
                    SystemRelationObligationRow.relation_id == uuid.UUID(edge)
                )
            )
            outstanding.discharged_by_primitive = "MP"
            outstanding.status = "discharged"
            session.commit()
    finally:
        engine.dispose()

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True


def test_an_edge_transfers_only_in_the_direction_it_names(db, client):
    # An edge is ordered. `Left → Right` says a theorem of `Left` is citable in
    # `Right`, and says nothing the other way — otherwise every edge would be two.
    left, right = two_systems(db, client, "direction@example.com")
    promote_into(db, right, IDENTITY)
    relate(db, left, right)

    assert verify_proof(client, db, left, "(P → P) [id]")["success"] is False


def test_two_parents_resolve_labels_from_both(db, client):
    # R4's other named case. `Target` reaches two sources by edge, and a
    # citation resolves against whichever has the label — which is what a second
    # parent is, expressed without touching the single-parent spine.
    owner = _register_login(client, "two-parents@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)
    target = seed(db, propositional_calculus_spec("Target"), owner, None)

    promote_into(db, left, IDENTITY)
    promote_into(db, right, _renamed(IDENTITY, "id2"))
    relate(db, left, target)
    relate(db, right, target)

    assert verify_proof(client, db, target, "(P → P) [id]")["success"] is True
    assert verify_proof(client, db, target, "(P → P) [id2]")["success"] is True


def test_an_edge_reaches_the_sources_own_ancestors(db, client):
    # A source is a system, so it comes with its chain: a theorem proved two
    # layers below the source is citable across the edge exactly as it is below
    # it. Otherwise an edge onto a tower would reach only its top.
    owner = _register_login(client, "source-chain@example.com")
    base = seed(db, propositional_calculus_spec("Base"), owner, None)
    upper = seed(db, first_order_logic_spec("Upper"), owner, base)
    target = seed(db, propositional_calculus_spec("Target"), owner, None)

    promote_into(db, base, IDENTITY)
    relate(db, upper, target)

    assert verify_proof(client, db, target, "(P → P) [id]")["success"] is True


def test_an_edge_into_an_ancestor_reaches_the_descendant(db, client):
    # The mirror: an ancestor's library is already citable here, so an edge that
    # extends *its* library extends this one. Anything else would make an edge's
    # reach depend on which layer of a tower it was attached to.
    owner = _register_login(client, "edge-below@example.com")
    parent = seed(db, propositional_calculus_spec("Parent"), owner, None)
    child = seed(db, first_order_logic_spec("Child"), owner, parent)
    other = seed(db, propositional_calculus_spec("Other"), owner, None)

    promote_into(db, other, IDENTITY)
    relate(db, other, parent)

    assert verify_proof(client, db, child, "(P → P) [id]")["success"] is True


# ---------------------------------------------------------------------------
# R4b: the rename
# ---------------------------------------------------------------------------


def test_a_theorem_crosses_a_renaming_edge(db, client):
    # The headline of R4b, as a pair on one edge: the same two systems, the same
    # theorem, the same proof, and the *map* is the only thing that changes.
    #
    # Without it the citation cannot resolve at all, and not for want of an edge —
    # the stored statement is a term whose constructor is called `implication`,
    # and this system declares no such production. With it the term is rebuilt
    # over `imp`, which is R4b: a rename applied to the constructors rather than
    # to any text.
    owner = _register_login(client, "rename@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    target = seed(db, renamed_propositional_calculus_spec("Target"), owner, None)
    promote_into(db, source, IDENTITY)
    edge = relate(db, source, target)

    unmapped = verify_proof(client, db, target, "(P → P) [id]")
    assert unmapped["success"] is False
    # And for the stated reason, not some other thing about the setup.
    assert "implication" in _why(unmapped)

    _rename(db, edge, **PC_RENAME)
    assert verify_proof(client, db, target, "(P → P) [id]")["success"] is True


def test_a_narrowing_sort_map_transfers_nothing(db, client):
    # §3.2, end to end. Two targets differing in one thing — whether `conj` is a
    # `wff` — the same source, the same map and the same proof. The target whose
    # sort admits the source's conjunctions takes the theorem; the one whose sort
    # does not is refused, because the transferred statement would quantify over
    # a sort that does not contain what it is about.
    #
    # Every name the map mentions is declared on both sides, so a check written
    # over names would accept both. `tests/test_translation.py` pins that
    # discriminator directly; this is what it means for a citation.
    owner = _register_login(client, "narrow@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    wide = seed(db, renamed_propositional_calculus_spec("Wide"), owner, None)
    narrow = seed(db, narrowed_propositional_calculus_spec("Narrow"), owner, None)
    promote_into(db, source, IDENTITY)
    _rename(db, relate(db, source, wide), **PC_RENAME)
    _rename(db, relate(db, source, narrow), **PC_RENAME)

    assert verify_proof(client, db, wide, "(P → P) [id]")["success"] is True

    refused = verify_proof(client, db, narrow, "(P → P) [id]")
    assert refused["success"] is False
    # The edge contributed no layer at all, so the label resolves to nothing —
    # rather than resolving and then failing on something about the statement.
    assert "Invalid reference: id" in _why(refused)


# `⊢ (P → ∀x P)`, where `x` is not free in `P` — a binder in the statement and a
# proviso over its variable. What a rename has to carry, and where losing either
# would show up as a citation that should have been refused.
VACUOUS = TheoremSpec(
    label="vac",
    statement="(P → ∀x P)",
    metavariables={"P": "formula", "x": "term"},
    distinct=("not occurs(x, P)",),
)

# A proviso carrying a **sort** argument, which is the one part of a side
# condition a rename touches (§3.5): the algebra is untouched and the sort is
# mapped, or the target cannot even parse the condition back.
DISTINCT = TheoremSpec(
    label="dv",
    statement="(x = y → x = y)",
    metavariables={"x": "term", "y": "term"},
    distinct=("disjoint(x, y, term)",),
)


def _binder_tower(db_path, client, email: str) -> tuple[str, str]:
    """The PC ⊂ FOL tower, and a renamed flat system with an edge from its top."""
    owner = _register_login(client, email)
    pc = seed(db_path, propositional_calculus_spec("PC"), owner, None)
    fol = seed(db_path, first_order_logic_spec("FOL"), owner, pc)
    target = seed(db_path, renamed_first_order_spec("Target"), owner, None)
    promote_into(db_path, fol, VACUOUS)
    promote_into(db_path, fol, DISTINCT)
    _rename(db_path, relate(db_path, fol, target), **FOL_RENAME)
    return fol, target


def test_a_binder_crosses_a_rename_in_both_directions(db, client):
    # §8.0's complex accepted case, with its refusal. The theorem's statement
    # binds, so it transfers only if the target's `all` is read as the source's
    # `universal` — and its proviso says the bound variable is not free in the
    # instance, which has to be re-checked *here*, against a binding made in this
    # system's terms.
    #
    # Both halves, because either alone is passed by a check that never runs: a
    # transfer that dropped the proviso takes the second line too, and one that
    # refused every instance takes neither.
    _fol, target = _binder_tower(db, client, "binder-rename@example.com")

    assert verify_proof(client, db, target, "(A → ∀a A) [vac]")["success"] is True

    # `a` *is* free in the instance of `P`, so the proviso refuses it — and the
    # message is asserted because the first version of this test was refused for
    # a line that did not parse at all, which is the failure §8.0's negative
    # controls exist to catch.
    captured = verify_proof(client, db, target, "(a = b → ∀a a = b) [vac]")
    assert captured["success"] is False
    assert "vac does not apply" in _why(captured)


def test_a_provisos_sort_argument_is_mapped(db, client):
    # The same pair for the sort-carrying proviso. `disjoint(x, y, term)` names a
    # sort the target calls `ind`, so an unmapped argument does not resolve to a
    # sort here at all — and the *accepted* half is what catches that, since a
    # proviso that cannot be read refuses every instance.
    _fol, target = _binder_tower(db, client, "proviso-rename@example.com")

    assert verify_proof(
        client, db, target, "(a = b → a = b) [dv]"
    )["success"] is True

    same = verify_proof(client, db, target, "(a = a → a = a) [dv]")
    assert same["success"] is False
    assert "dv does not apply" in _why(same)


def _why(response: dict) -> str:
    """Everything a failed verify said, as one string to assert against.

    A refusal is only informative if it is the *right* refusal, and this area has
    three that look alike from a boolean: the citation resolved and the instance
    was refused (`does not apply`), the citation resolved to nothing at all
    (`Invalid reference`), and the whole verify failed before the proof was
    checked — which is where a term that could not be rebuilt surfaces.
    """
    proof = response.get("proof") or {}
    return " | ".join(
        [
            *response.get("errors", []),
            *[
                line["invalid_message"]
                for line in proof.get("lines", [])
                if line.get("invalid_message")
            ],
        ]
    )


def test_a_rename_may_move_the_notation_too(db, client):
    # A production carries its template, so renaming one changes how the
    # transferred statement is *written*: `(P → P)` proved in the source is
    # `(P ⊃ P)` here, and the proof that cites it is written in this system's
    # notation because that is the only notation it has.
    #
    # The entry's own statement string is re-rendered from its translated term
    # rather than carried over, which is asserted directly — for a structural
    # check the term is what matters, so a stale string would otherwise sit there
    # unnoticed until something displayed it.
    owner = _register_login(client, "respell@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    target = seed(db, respelled_propositional_calculus_spec("Target"), owner, None)
    promote_into(db, source, IDENTITY)
    _rename(db, relate(db, source, target), **PC_RENAME)

    assert verify_proof(client, db, target, "(P ⊃ P) [id]")["success"] is True
    assert _resolve_across(db, target, ["id"])["id"].deduction.pattern == "(P ⊃ P)"


def test_a_renamed_statement_is_the_targets_own_term(db, client):
    # §8.0's "assert over terms where the claim is about terms". The transferred
    # statement is not a look-alike built from the source's rendering: its root is
    # *this* system's `imp` constructor, and its metavariable ranges over this
    # system's `wff`. A string comparison would pass for two terms that differ in
    # constructor and therefore in sort, which is the whole thing being claimed.
    owner = _register_login(client, "renamed-term@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    target = seed(db, renamed_propositional_calculus_spec("Target"), owner, None)
    promote_into(db, source, IDENTITY)
    _rename(db, relate(db, source, target), **PC_RENAME)

    statement = _resolve_across(db, target, ["id"])["id"].deduction.schema_term
    assert statement.constructor.name == "imp"
    assert statement.children["p"].sort.name == "wff"


def test_a_rename_composes_nothing(db, client, monkeypatch):
    # §3.1 across an edge, which is what R2 pinned across the spine: the transfer
    # is a term-graph read and not a re-parse, and a rename does not change that —
    # it renames the constructor each stored row resolves to, one lookup earlier.
    #
    # Pinned by making composing fatal, because nothing else keeps it true under
    # a later edit: a re-parse here would give the same answer for this system
    # and quietly cost a parse of the whole grammar per citation.
    owner = _register_login(client, "renamed-parse@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    target = seed(db, renamed_propositional_calculus_spec("Target"), owner, None)
    promote_into(db, source, IDENTITY)
    _rename(db, relate(db, source, target), **PC_RENAME)

    import website.logical.build_context as build_context

    def refuse(*_args, **_kwargs):
        raise AssertionError("a renamed citation must not re-compose its term")

    # Patched after both systems are built: a build composes its own rules'
    # schema terms, which is a different use of the same function.
    resolved = _resolve_across(
        db, target, ["id"],
        before=lambda: monkeypatch.setattr(
            build_context, "compose_schema_term", refuse
        ),
    )
    assert set(resolved) == {"id"}


def _resolve_across(db_path, system_id: str, labels: list[str], before=None) -> dict:
    """Promote ``labels`` in ``system_id``, through its chain **and its edges**.

    `tests.test_cross_system_citation.resolve` for a system whose library reaches
    past the spine — the same three steps `load_effective` takes, in the same
    order, so a test cannot pass with the ordering or the digests wrong.
    """
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = session.get(FormalSystem, uuid.UUID(system_id))
            chain = _chain(session, system)
            spec, library = effective_library(chain)
            library = LibraryChain(
                library.layers + tuple(related_layers(session, chain, spec))
            )
            built = build_spec(spec)["system"]
            context = copy(built.context)
            context.variables.update(built.build_context.variables)
            if before is not None:
                before()
            return load_theorems(session, library, labels, built, context)
    finally:
        engine.dispose()


def _rename(db_path, edge: str, sorts: dict[str, str], symbols: dict[str, str]) -> None:
    """Give an existing edge its map, leaving everything else about it alone."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            row = session.get(SystemRelationRow, uuid.UUID(edge))
            for index, (original, renamed) in enumerate(sorts.items()):
                row.sorts.append(
                    SystemRelationSortRow(
                        position=index, source_sort=original, target_sort=renamed
                    )
                )
            for index, (original, renamed) in enumerate(symbols.items()):
                row.symbols.append(
                    SystemRelationSymbolRow(
                        position=index, source_symbol=original, target_symbol=renamed
                    )
                )
            session.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Ordering: the spine keeps what it already answers
# ---------------------------------------------------------------------------


def test_the_spine_shadows_an_edge_on_a_shared_label(db, client):
    # An edge may only *add*. A label the tower already answers keeps its answer,
    # because the spine is a claim the builder checked and an edge is a claim an
    # author made — so the conservative direction is the spine's.
    #
    # Asserted by making the two say different things and checking which one the
    # proof gets, as the inheritance shadowing test does.
    owner = _register_login(client, "shadow-edge@example.com")
    home = seed(db, propositional_calculus_spec("Home"), owner, None)
    other = seed(db, propositional_calculus_spec("Other"), owner, None)

    promote_into(db, home, IDENTITY)
    promote_into(db, other, _restated(IDENTITY, "(Q → (P → Q))"))
    relate(db, other, home)

    # `home`'s own `id` is `(P → P)`; the edge's is a different statement.
    assert verify_proof(client, db, home, "(P → P) [id]")["success"] is True
    assert verify_proof(client, db, home, "(Q → (P → Q)) [id]")["success"] is False


def test_a_system_reached_twice_is_one_layer(db, client):
    # Two edges onto the same source must not put it in the chain twice: a
    # duplicated layer makes `LibraryChain.rank` answer by whichever copy came
    # first, so a shadowing decision would depend on insertion order.
    #
    # Asserted on the layers themselves, not on the citation — a duplicate whose
    # digest happens to agree resolves fine, so a passing proof says nothing
    # about whether the dedup ran.
    owner = _register_login(client, "twice@example.com")
    source = seed(db, propositional_calculus_spec("Source"), owner, None)
    middle = seed(db, propositional_calculus_spec("Middle"), owner, None)
    # A *different* spec for the child: two copies of one grammar in a chain
    # collide on their production names, which `layered_spec` refuses.
    target = seed(db, first_order_logic_spec("Target"), owner, middle)

    promote_into(db, source, IDENTITY)
    relate(db, source, middle)
    relate(db, source, target)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            chain = [
                session.get(FormalSystem, uuid.UUID(middle)),
                session.get(FormalSystem, uuid.UUID(target)),
            ]
            layers = related_layers(session, chain, effective_spec(chain))
    finally:
        engine.dispose()

    reached = [layer.system_id for layer in layers]
    assert reached == [uuid.UUID(source)]

    assert verify_proof(client, db, target, "(P → P) [id]")["success"] is True


def test_an_edge_onto_the_citing_system_itself_adds_no_layer(db, client):
    # The degenerate self-edge. Nothing should break, and nothing should be
    # added — the system's own library is layer zero already.
    left, _right = two_systems(db, client, "self-edge@example.com")
    promote_into(db, left, IDENTITY)
    relate(db, left, left)

    assert verify_proof(client, db, left, "(P → P) [id]")["success"] is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _renamed(spec, label: str):
    from dataclasses import replace

    return replace(spec, label=label)


def _restated(spec, statement: str):
    from dataclasses import replace

    return replace(spec, statement=statement)


def test_the_promoted_fixture_says_what_these_tests_assume(db, client):
    # A guard on the fixture: every refusal above would also pass against a
    # library that was never seeded.
    left, _right = two_systems(db, client, "fixture@example.com")
    promote_into(db, left, IDENTITY)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            entry = session.scalar(
                select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
            )
            assert entry is not None
            assert entry.statement == "(P → P)"
    finally:
        engine.dispose()

    assert verify_proof(client, db, left, "(P → P) [id]")["success"] is True


# ---------------------------------------------------------------------------
# Both P1s from review: what a discharge is, and what invalidation must reach
# ---------------------------------------------------------------------------


def test_an_obligation_whose_theorem_vanished_is_outstanding(db, client):
    # Found in review (Codex). An obligation discharged by a *theorem* loses it
    # to `ON DELETE SET NULL` when that theorem is retired, and nothing writes
    # back to the obligation's own status — so the cached `discharged` outlives
    # the warrant. This module's own model already claimed a NULL "leaves the
    # obligation undischarged"; only the column was doing that, not the query.
    left, right = two_systems(db, client, "vanished@example.com")
    promote_into(db, left, IDENTITY)
    promote_into(db, right, _renamed(IDENTITY, "stands-in"))
    edge = relate(db, left, right, obligations=[])

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            warrant = session.scalar(
                select(PromotedTheoremRow).where(
                    PromotedTheoremRow.label == "stands-in"
                )
            )
            session.add(
                SystemRelationObligationRow(
                    relation_id=uuid.UUID(edge),
                    source_label="MP",
                    discharged_by_theorem_id=warrant.id,
                    status="discharged",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    # Discharged by a standing theorem: the edge transfers.
    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is True

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            # What retiring the theorem leaves behind: the FK nulled, the
            # obligation's own status untouched.
            obligation = session.scalar(select(SystemRelationObligationRow))
            obligation.discharged_by_theorem_id = None
            session.commit()
            assert obligation.status == "discharged"
    finally:
        engine.dispose()

    assert verify_proof(client, db, right, "(P → P) [id]")["success"] is False


def test_retiring_a_theorem_invalidates_a_proof_that_cited_it_across_an_edge(db, client):
    # Found in review (Codex). R4a widened where a citation may resolve without
    # widening what invalidation reaches, so a *sibling* target kept `valid`,
    # `result` and its `proof_lines` after the theorem it rested on was gone —
    # and a verify trusts a lemma's stored rows, so a third proof would rest on
    # it too. Reach and invalidation are one question asked twice.
    owner = _register_login(client, "edge-invalidation@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)

    # A promoted proof, so retiring it goes through the route that invalidates.
    proof = _proved_and_promoted(client, left, "id")
    relate(db, left, right)

    citing = _make(client, right, "(P → P) [id]")
    assert _verify(client, citing)["success"] is True

    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204

    assert client.get(f"/api/proofs/{citing}").json()["valid"] is None


def test_retiring_leaves_an_unrelated_system_alone(db, client):
    # The other half: a walk that invalidated every system would pass the test
    # above for the wrong reason. With no edge, nothing is disturbed.
    owner = _register_login(client, "no-edge@example.com")
    left = seed(db, propositional_calculus_spec("Left"), owner, None)
    right = seed(db, propositional_calculus_spec("Right"), owner, None)

    proof = _proved_and_promoted(client, left, "id")
    bystander = _make(client, right, "(P → (P → P)) [ax-1]")
    assert _verify(client, bystander)["success"] is True

    assert client.delete(f"/api/proofs/{proof}/promote").status_code == 204

    assert client.get(f"/api/proofs/{bystander}").json()["valid"] is True


def _make(client, system_id: str, source: str) -> str:
    from tests.test_proof_promotion import make_proof

    return make_proof(client, system_id, source)


def _verify(client, proof_id: str) -> dict:
    from tests.test_proof_promotion import verify

    return verify(client, proof_id)


def _proved_and_promoted(client, system_id: str, label: str) -> str:
    """A real promoted proof in ``system_id`` — the route retirement runs from."""
    from tests.test_proof_promotion import (
        IDENTITY_PROOF,
        proved_and_published,
        promote,
    )

    proof = proved_and_published(client, system_id, IDENTITY_PROOF)
    status, body = promote(client, proof, label)
    assert status == 201, body
    return proof
