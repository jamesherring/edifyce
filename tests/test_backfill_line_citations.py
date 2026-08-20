"""Filling in which entry each citation named, on proofs stored before the column.

``proof_lines.theorem_id`` records the resolution a check performed, so the
provenance report can stop rebuilding the library order to re-derive it. A proof
checked before the column has nothing recorded, and ``proofs.citations_stored``
is what tells the two apart.

The two things worth proving about the upgrade path are the same two the markup
rebuild had to prove: that it lands on exactly what a fresh import writes, and
that running it twice does not undo the first run. Two more matter here because
the flag is a *claim*: a system that no longer builds, and a proof citing a label
the library cannot account for, must both be left unflagged rather than marked
resolved on no resolution at all.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from sqlalchemy import NullPool, create_engine, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.db.metamath_store import import_corpus
from app.db.models import FormalSystem, Proof
from app.db.proof_lines import ProofLineRow
from app.db.promoted_theorems import PromotedTheoremRow
from scripts.backfill_line_citations import backfill
from tests.database import (
    async_url,
    create_every_table,
    database_url,
    enable_foreign_keys,
)
from tests.test_metamath_persistence import PROPOSITIONAL
from website.logical.metamath import parse


@pytest.fixture
def db(tmp_path) -> Iterator[str]:
    url = database_url(tmp_path, "backfill")
    # Every table, not this suite's own list: what it exercises loads a system the
    # ordinary way, and that reaches most of the schema.
    create_every_table(url)
    yield url


def _import(url: str) -> None:
    engine = create_engine(url)
    enable_foreign_keys(engine)
    try:
        with Session(engine) as session:
            import_corpus(session, parse(PROPOSITIONAL), name="P")
            session.commit()
    finally:
        engine.dispose()


def _unresolved(url: str) -> None:
    """Put the rows back the way a pre-column import would have left them.

    The labels still on the lines and the entries still in the library, but no
    link between them and the flag down — which is exactly what the migration
    produces on a database imported before any of this existed.
    """
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            for line in session.scalars(select(ProofLineRow)):
                line.theorem_id = None
            for proof in session.scalars(select(Proof)):
                proof.citations_stored = False
            session.commit()
    finally:
        engine.dispose()


def _run(url: str, dry_run: bool = False) -> dict[str, int]:
    async def go() -> dict[str, int]:
        engine = create_async_engine(async_url(url), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await backfill(session, dry_run)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _state(url: str) -> dict[tuple[str, int], tuple]:
    """Every line's recorded citation, keyed by the proof and position it is on."""
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            proofs = {proof.id: proof for proof in session.scalars(select(Proof))}
            return {
                (proofs[line.proof_id].name, line.position): (
                    line.rule,
                    line.theorem_id,
                    proofs[line.proof_id].citations_stored,
                )
                for line in session.scalars(select(ProofLineRow))
            }
    finally:
        engine.dispose()


def test_it_lands_on_what_a_fresh_import_would_have_written(db):
    _import(db)
    fresh = _state(db)
    # The fixture has to be a real corpus for the comparison to mean anything:
    # a run over proofs that cite no library entry would pass trivially.
    assert any(recorded is not None for _rule, recorded, _flag in fresh.values())

    _unresolved(db)
    assert _state(db) != fresh, "the fixture must actually be un-resolved first"

    tally = _run(db)

    assert _state(db) == fresh
    assert tally["lines"] > 0
    assert tally["skipped"] == 0


def test_running_it_twice_changes_nothing(db):
    _import(db)
    _unresolved(db)
    _run(db)
    once = _state(db)

    # Every proof carries the flag now, so the second run has nothing to select.
    again = _run(db)

    assert _state(db) == once
    assert again["proofs"] == 0
    assert again["lines"] == 0


def test_a_dry_run_writes_nothing(db):
    _import(db)
    _unresolved(db)
    before = _state(db)

    tally = _run(db, dry_run=True)

    assert _state(db) == before
    # It still says what it would have done, or there would be no point running it.
    assert tally["lines"] > 0


def test_a_system_that_no_longer_builds_is_left_unflagged(db):
    # The flag claims its columns were written. A system whose grammar no longer
    # resolves offers no library order to write them from, so the honest outcome
    # is to leave the proofs on the old read path — not to mark them resolved and
    # have them report resting on nothing.
    _import(db)
    _unresolved(db)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            # A chain with no top. `load_chain` cannot walk to one, and
            # `truncated_chain_errors` refuses the prefix rather than building a
            # different system from the one the rows declare — so there is no
            # library order to resolve against.
            #
            # A system inheriting from *itself* rather than from an id that is not
            # there: both are cycles as far as the walk is concerned, and this one
            # satisfies the foreign key, so it is a state the real database can
            # actually hold. A dangling id is not — `inherits_from_id` is
            # `ON DELETE SET NULL`, and Postgres refuses to store one in the first
            # place.
            for system in session.scalars(select(FormalSystem)):
                system.inherits_from_id = system.id
            session.commit()
    finally:
        engine.dispose()

    tally = _run(db)

    assert tally["lines"] == 0
    assert tally["skipped"] > 0
    assert all(flag is False for _rule, _id, flag in _state(db).values())


def test_a_citation_the_library_cannot_account_for_is_left_unflagged(db):
    # The other way the flag can be a claim nothing backs. A label naming no
    # entry is usually a rule or a hypothesis — neither a dependency — but it can
    # also be an entry this database does not hold, which the report exists to
    # name. Flagging that proof would reclassify the citation as "cited no entry"
    # and lose it silently, so only the proofs that cite it stay behind.
    _import(db)
    fresh = _state(db)
    missing = next(rule for rule, recorded, _flag in fresh.values() if recorded)
    _unresolved(db)

    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.execute(
                sa_delete(PromotedTheoremRow).where(
                    PromotedTheoremRow.label == missing
                )
            )
            session.commit()
    finally:
        engine.dispose()

    tally = _run(db)

    state = _state(db)
    citing = {name for (name, _at), (rule, _id, _flag) in state.items() if rule == missing}
    assert citing, "the fixture must actually cite the entry that went missing"
    assert all(
        flag is False
        for (name, _at), (_rule, _id, flag) in state.items()
        if name in citing
    )
    assert tally["skipped"] == len(citing)
    # The rest of the system is unaffected: one unaccountable label is one
    # proof's problem, not the corpus's.
    assert any(
        flag is True
        for (name, _at), (_rule, _id, flag) in state.items()
        if name not in citing
    )
