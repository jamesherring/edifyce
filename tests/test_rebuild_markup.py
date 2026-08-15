"""Re-reading the markup in descriptions an older import already stored.

The migration that adds ``label_references`` adds an empty table and two `false`
columns; nothing re-reads the prose behind them, so a corpus imported before the
change goes on showing `~ ax-13` as punctuation (raised in review on #196). This
is the upgrade path, and the two things worth proving about it are that it lands
on exactly what a fresh import would have written, and that running it twice does
not undo the first run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from sqlalchemy import NullPool, create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.db.descriptions import LabelDescriptionRow, LabelReferenceRow
from app.db.metamath_store import import_corpus
from scripts.rebuild_markup import rebuild
from tests.database import async_url, database_url, enable_foreign_keys
from tests.test_descriptions_store import MARKED, SOURCE
from website.logical.metamath import parse


@pytest.fixture
def db(tmp_path) -> Iterator[str]:
    url = database_url(tmp_path, "rebuild")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url


def _import(url: str) -> None:
    engine = create_engine(url)
    enable_foreign_keys(engine)
    try:
        with Session(engine) as session:
            import_corpus(session, parse(MARKED), name="M")
            session.commit()
    finally:
        engine.dispose()


def _unread(url: str) -> None:
    """Put the rows back the way an older import would have left them.

    The prose with its markup still in it, no references, no flags — which is
    exactly the state the migration produces on a database imported before any of
    this existed.
    """
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            for row in session.scalars(select(LabelDescriptionRow)):
                markers = "".join(
                    f" ({what} is discouraged.)"
                    for what, flag in (
                        ("New usage", row.discouraged_usage),
                        ("Proof modification", row.discouraged_modification),
                    )
                    if flag
                )
                row.text = f"{row.text}{markers}"
                row.discouraged_usage = False
                row.discouraged_modification = False
                row.references.clear()
                row.citations.clear()
            session.commit()
    finally:
        engine.dispose()


def _run(url: str, dry_run: bool = False) -> dict[str, int]:
    async def go() -> dict[str, int]:
        engine = create_async_engine(async_url(url), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await rebuild(session, dry_run)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _state(url: str) -> dict[str, tuple]:
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            return {
                row.label: (
                    row.text,
                    row.discouraged_usage,
                    row.discouraged_modification,
                    tuple(
                        (r.position, r.target, r.start_offset, r.end_offset)
                        for r in row.references
                    ),
                    tuple(
                        (c.position, c.work, c.page, c.start_offset, c.end_offset)
                        for c in row.citations
                    ),
                )
                for row in session.scalars(select(LabelDescriptionRow))
            }
    finally:
        engine.dispose()


def test_it_lands_on_what_a_fresh_import_would_have_written(db):
    _import(db)
    fresh = _state(db)
    _unread(db)
    assert _state(db) != fresh, "the fixture must actually be un-read first"

    _run(db)

    assert _state(db) == fresh


def test_running_it_twice_changes_nothing_the_first_run_did(db):
    # The trap the script is written around: a row it has already fixed has no
    # marker left to find, so *assigning* the result would clear a flag that is
    # right. Read again, the second pass must be a no-op.
    _import(db)
    _unread(db)
    _run(db)
    once = _state(db)

    _run(db)

    assert _state(db) == once


def test_a_dry_run_reports_without_writing(db):
    _import(db)
    _unread(db)
    before = _state(db)

    tally = _run(db, dry_run=True)

    assert _state(db) == before
    assert tally["references"] > 0
    assert tally["usage"] == 1 and tally["modification"] == 1


def test_an_already_current_database_is_left_alone(db):
    # The common case once the change has shipped: nothing to do, and nothing done.
    _import(db)
    before = _state(db)

    tally = _run(db)

    assert _state(db) == before
    assert tally["usage"] == 0 and tally["modification"] == 0


def test_it_rebuilds_the_bibliography_citations_too(db):
    """A corpus imported before citations were read keeps its prose and loses none.

    `MARKED` cites nothing, so the tests above exercise only the reference half.
    `SOURCE` carries `Axiom A1 of [Margaris] p. 49.`, which is the whole point of
    the backfill existing: the key is in the stored prose already, and re-reading
    it needs no `.mm` file.
    """
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            import_corpus(session, parse(SOURCE), name="S")
            session.commit()
    finally:
        engine.dispose()
    fresh = _state(db)
    _unread(db)
    assert _state(db) != fresh, "the fixture must actually be un-read first"

    tally = _run(db)

    assert tally["citations"] == 1
    assert _state(db) == fresh
