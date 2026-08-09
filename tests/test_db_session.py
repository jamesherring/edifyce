"""Guards for the engine URL handling (no database connection needed)."""

import pytest

pytest.importorskip("sqlalchemy")

from app.db.session import _database_url, asyncpg_url, psycopg_url


def test_sslmode_is_translated_to_asyncpg_ssl(monkeypatch):
    # The documented Neon/Vercel URL uses ?sslmode=require, which asyncpg does not
    # accept as a keyword (it spells it `ssl`); the driver must translate it.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h.neon.tech/db?sslmode=require")
    url = _database_url()
    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
    assert url.query.get("ssl") == "require"


def test_channel_binding_is_dropped(monkeypatch):
    # Neon/Vercel pooled URLs also carry ?channel_binding=require, another
    # libpq-only param asyncpg has no keyword for (it negotiates channel binding
    # automatically over SSL). Left in place it raises "unexpected keyword
    # argument 'channel_binding'" on first connect, so the driver must drop it.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@h-pooler.neon.tech/db?channel_binding=require&sslmode=require",
    )
    url = _database_url()
    assert "channel_binding" not in url.query
    assert url.query.get("ssl") == "require"


def test_non_asyncpg_scheme_is_normalised(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert _database_url().drivername == "postgresql+asyncpg"


def test_the_sync_driver_is_one_a_checkout_actually_installs():
    # A bare `postgresql://` resolves to psycopg2, which nothing here depends on,
    # and `postgres://` resolves to no dialect at all. Either dies in
    # create_engine, so the batch path would not survive its own first line.
    assert psycopg_url("postgres://u:p@h/db").drivername == "postgresql+psycopg"
    assert psycopg_url("postgresql://u:p@h/db").drivername == "postgresql+psycopg"


def test_libpq_params_reach_psycopg_unchanged():
    # psycopg *is* libpq, so the platform's own spelling needs no translation —
    # this is the whole difference from the asyncpg side.
    url = psycopg_url("postgresql://u:p@h.neon.tech/db?sslmode=require&channel_binding=require")
    assert url.query.get("sslmode") == "require"
    assert url.query.get("channel_binding") == "require"


def test_asyncpgs_ssl_spelling_is_translated_back_for_psycopg():
    # `ssl` is asyncpg's keyword, not libpq's. A URL that has already been through
    # `asyncpg_url` — or one written as postgresql+asyncpg://…?ssl=require because
    # that is what the app takes — would otherwise reach psycopg as
    # `invalid connection option "ssl"` (raised in review).
    url = psycopg_url("postgresql+asyncpg://u:p@h/db?ssl=require")
    assert url.drivername == "postgresql+psycopg"
    assert "ssl" not in url.query
    assert url.query.get("sslmode") == "require"


def test_the_two_url_rules_are_inverses_over_a_platform_url():
    # Round-tripping a Neon URL through the async translation and back must land
    # on something libpq accepts, which is the property the bug above broke.
    raw = "postgresql://u:p@h.neon.tech/db?sslmode=require&channel_binding=require"
    round_tripped = psycopg_url(asyncpg_url(raw))
    assert round_tripped.drivername == "postgresql+psycopg"
    assert round_tripped.query.get("sslmode") == "require"
    assert "ssl" not in round_tripped.query


def test_an_explicit_sslmode_is_not_overwritten_by_ssl():
    # Both spellings present is a malformed URL rather than a real one, but the
    # translation must not silently prefer asyncpg's over what libpq already
    # understands.
    url = psycopg_url("postgresql://u:p@h/db?sslmode=verify-full&ssl=require")
    assert url.query.get("sslmode") == "verify-full"
    assert "ssl" not in url.query


def test_missing_database_url_raises(monkeypatch):
    # _database_url falls back to POSTGRES_URL, so both must be unset for the
    # "no database configured" path to raise.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    with pytest.raises(RuntimeError):
        _database_url()
