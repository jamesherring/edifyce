"""Guards for the engine URL handling (no database connection needed)."""

import pytest

pytest.importorskip("sqlalchemy")

from app.db.session import _database_url


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


def test_missing_database_url_raises(monkeypatch):
    # _database_url falls back to POSTGRES_URL, so both must be unset for the
    # "no database configured" path to raise.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    with pytest.raises(RuntimeError):
        _database_url()
