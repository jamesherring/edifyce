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


def test_non_asyncpg_scheme_is_normalised(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert _database_url().drivername == "postgresql+asyncpg"


def test_missing_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        _database_url()
