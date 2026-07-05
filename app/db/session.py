"""Async engine and session wiring.

Kept lazy on purpose: importing this module must not open a connection (the Atlas
schema loader imports the package offline, and the API should boot without a
database when `DATABASE_URL` is unset). The engine is created on first use.
"""

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at the Neon *pooled* connection "
            "string (the '-pooler' host) for serverless deployments."
        )
    # Accept the common `postgresql://` / `postgres://` forms and route them to
    # the asyncpg driver the app actually uses.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    # NullPool: on serverless (Vercel functions) an external pooler (Neon's
    # PgBouncer endpoint) owns pooling; the app should not hold its own idle pool.
    from sqlalchemy import NullPool

    return create_async_engine(_database_url(), poolclass=NullPool)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request."""
    async with get_sessionmaker()() as session:
        yield session
