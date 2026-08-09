"""Guards for the test suite's own throwaway-database helper.

``tests/database.py`` is machinery rather than subject matter, and normally that
means it is tested by every suite that leans on it. One thing is not covered that
way: it hands out SQLite databases by *copying a prebuilt file*, so a template
that ever picked up a row, or a cache key that conflated two different table
sets, would hand several hundred tests a schema they did not ask for — and each
of those tests would fail somewhere far from the cause, or worse, quietly pass on
data a previous test left behind. These pin the two properties that makes safe.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, text

from app.db.models import FormalSystem, User
from tests.database import create_tables, database_url


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
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, is_active,"
                    " is_superuser, is_verified) VALUES ('x', 'a@b.c', 'h', 1, 0, 0)"
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


def test_asking_for_different_tables_gets_different_schemas(tmp_path):
    # Templates are cached per table set. Were the key to conflate two sets, the
    # second suite to ask would silently receive the first one's schema — which
    # for a superset looks like nothing at all until a missing table is used.
    small = database_url(tmp_path, "small")
    create_tables(small, [User.__table__])

    large = database_url(tmp_path, "large")
    create_tables(large, [User.__table__, FormalSystem.__table__])

    assert "formal_systems" not in _table_names(small)
    assert "formal_systems" in _table_names(large)
    # …and asking again for the first set still gets the first set, rather than
    # whatever was built most recently.
    again = database_url(tmp_path, "again")
    create_tables(again, [User.__table__])
    assert _table_names(again) == _table_names(small)
