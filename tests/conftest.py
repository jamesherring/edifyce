"""Suite-wide wiring.

Both hooks here exist for the same reason: a per-test cost that no test is about,
paid several hundred times. Neither changes what any test can observe — the
SQLite one gives up durability a throwaway file cannot use, and the password one
turns argon2's work factor down without swapping argon2 for anything else.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.database import ON_POSTGRES, is_sqlite_connection, relax_sqlite_durability

if TYPE_CHECKING:
    from pwdlib import PasswordHash

# The module whose subject *is* the password flow, and so the one that keeps the
# real work factor: if the shipped hasher were unusable, this is where it should
# be noticed.
_KEEPS_THE_REAL_HASHER = "test_auth.py"


def pytest_configure(config: pytest.Config) -> None:
    """Refuse the one combination that cannot work.

    A SQLite run gets a fresh file per test, so workers cannot see each other.
    A Postgres run shares one database and drops every table between tests
    (``tests/database.py``), so a second worker would tear down the schema out
    from under the first. Serial is not a preference there, it is the design.
    """
    if ON_POSTGRES and (config.getoption("numprocesses", None) or 0) != 0:
        raise pytest.UsageError(
            "EDIFYCE_TEST_DATABASE_URL runs share one database and drop its "
            "tables between tests; run them serially (-n 0)."
        )


@event.listens_for(Engine, "connect")
def _tune_throwaway_sqlite(dbapi_connection: object, _record: object) -> None:
    """Applied here rather than in a fixture because it has to reach engines the
    suites open for themselves: seeding a system, reading rows back, and the
    async engine the API runs against are three separate ``create_engine`` calls
    per test, across seventeen modules. A class-level listener catches all of
    them, including the sync engine inside an async one.

    Postgres runs (``EDIFYCE_TEST_DATABASE_URL``) are left exactly as they are:
    the point of running against one is that it behaves like the deployment.
    """
    if is_sqlite_connection(dbapi_connection):
        relax_sqlite_durability(dbapi_connection)


_CHEAP_ARGON2: PasswordHash | None = None


def _cheap_argon2() -> PasswordHash:
    """argon2 at its floor, built once.

    Deliberately still argon2 — the same hasher, the same verify path, the same
    stored-hash format — so what the suite exercises is the code that ships and
    only the cost parameters differ. fastapi-users' default is ~86ms to hash and
    ~76ms to verify, and several hundred tests register a user and log them in
    purely to have someone to own a system.
    """
    global _CHEAP_ARGON2
    if _CHEAP_ARGON2 is None:
        # Imported here, not at the top: every suite that touches auth opens with
        # `pytest.importorskip("fastapi_users")`, so a conftest that imported its
        # dependencies at collection time would turn those skips into errors.
        from pwdlib import PasswordHash  # noqa: PLC0415
        from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: PLC0415

        _CHEAP_ARGON2 = PasswordHash(
            (Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),)
        )
    return _CHEAP_ARGON2


@pytest.fixture(autouse=True)
def _cheap_password_hashing(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turn argon2's work factor down for everything but the auth suite.

    ``BaseUserManager`` reaches for ``PasswordHelper`` by name when its caller
    passes none, which ``app.auth.users.get_user_manager`` does, so that name is
    what a test-only work factor has to hold onto.
    """
    if request.path.name == _KEEPS_THE_REAL_HASHER:
        return
    if "fastapi_users" not in sys.modules:
        # Nothing in this module reached auth, so there is no manager to patch —
        # and importing fastapi-users to find that out would defeat the skips.
        return

    from fastapi_users import manager  # noqa: PLC0415 - see _cheap_argon2
    from fastapi_users.password import PasswordHelper  # noqa: PLC0415

    cheap = _cheap_argon2()
    monkeypatch.setattr(manager, "PasswordHelper", lambda: PasswordHelper(cheap))
