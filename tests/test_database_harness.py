"""Guards for the test suite's own throwaway-database helper.

``tests/database.py`` is machinery rather than subject matter, and normally that
means it is tested by every suite that leans on it. One thing is not covered that
way: it hands out SQLite databases by *copying a prebuilt file*, so a template
that ever picked up a row, or a cache key that conflated two different table
sets, would hand several hundred tests a schema they did not ask for — and each
of those tests would fail somewhere far from the cause, or worse, quietly pass on
data a previous test left behind. These pin the two properties that makes safe.

The first of the two is written to run on either engine: Postgres reaches an empty
schema by dropping and rebuilding rather than by copying a file, and a leak there
would do the most damage, since every test in a run shares the one database. The
second is about the template cache itself and so is SQLite's alone.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, text

from app.db.models import User
from app.db.systems import RuleRow
from tests.database import ON_POSTGRES, create_tables, database_url


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_every_database_starts_empty_however_many_came_before_it(tmp_path):
    # The template is built once and copied thereafter, so a row written into one
    # test's database must not be visible to the next. Written through a real
    # insert rather than by touching the file, because that is how a leak would
    # actually happen.
    first = database_url(tmp_path, "first")
    create_tables(first, [User.__table__])
    engine = create_engine(first)
    try:
        with engine.begin() as connection:
            # Through the table rather than as literal SQL: Postgres types these
            # columns as `uuid` and `boolean`, and a hand-written VALUES clause
            # that satisfies SQLite does not satisfy it.
            connection.execute(
                User.__table__.insert().values(
                    id=uuid.uuid4(),
                    email="a@b.c",
                    hashed_password="h",
                    is_active=True,
                    is_superuser=False,
                    is_verified=False,
                )
            )
        # Non-vacuous: there is actually a row to leak.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 1
    finally:
        engine.dispose()

    second = database_url(tmp_path, "second")
    create_tables(second, [User.__table__])
    engine = create_engine(second)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
    finally:
        engine.dispose()


@pytest.mark.skipif(
    ON_POSTGRES,
    reason="the template cache is the SQLite path; a Postgres run has one database",
)
def test_asking_for_different_tables_gets_different_schemas(tmp_path):
    # Templates are cached per table set. Were the key to conflate two sets, the
    # second suite to ask would silently receive the first one's schema — which
    # for a superset looks like nothing at all until a missing table is used.
    #
    # SQLite only, and not for want of trying: on Postgres every name is the same
    # database, so asking for the second set *replaces* the first rather than
    # sitting beside it. There is no cache there to get wrong either — the schema
    # is rebuilt per test rather than copied.
    small = database_url(tmp_path, "small")
    create_tables(small, [User.__table__])

    large = database_url(tmp_path, "large")
    create_tables(large, [User.__table__, RuleRow.__table__])

    # `rules` as the witness rather than something nearer the middle of the
    # schema: every set is closed over what it references, so a table any of the
    # `_always` tables points at is in *both* sets and would witness nothing.
    assert "rules" not in _table_names(small)
    assert "rules" in _table_names(large)
    # …and asking again for the first set still gets the first set, rather than
    # whatever was built most recently.
    again = database_url(tmp_path, "again")
    create_tables(again, [User.__table__])
    assert _table_names(again) == _table_names(small)
