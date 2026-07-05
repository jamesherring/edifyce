"""Async engine and session wiring.

Kept lazy on purpose: importing this module must not open a connection (the Atlas
schema loader imports the package offline, and the API should boot without a
database when `DATABASE_URL` is unset). The engine is created on first use.
"""

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import NullPool, make_url
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _database_url() -> URL:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at the Neon *pooled* connection "
            "string (the '-pooler' host) for serverless deployments."
        )
    # Route whatever scheme the platform hands us (postgres://, postgresql://,
    # even postgresql+psycopg://) onto the asyncpg driver the app uses.
    return make_url(url).set(drivername="postgresql+asyncpg")


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(
        _database_url(),
        # NullPool: on serverless (Vercel functions) an external pooler (Neon's
        # PgBouncer endpoint) owns pooling; the app holds no idle pool of its own.
        poolclass=NullPool,
        # Neon's pooled endpoint is PgBouncer in transaction mode, which
        # multiplexes clients onto shared server connections; asyncpg's named
        # server-side prepared statements collide there, so disable its cache.
        connect_args={"statement_cache_size": 0},
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request."""
    async with get_sessionmaker()() as session:
        yield session
