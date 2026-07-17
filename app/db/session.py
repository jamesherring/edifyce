"""Async engine and session wiring.

Kept lazy on purpose: importing this module must not open a connection (the Atlas
schema loader imports the package offline, and the API should boot without a
database when `DATABASE_URL` is unset). The engine is created on first use.
"""

import os
from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import NullPool, make_url
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _database_url() -> URL:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at the Neon *pooled* connection "
            "string (the '-pooler' host) for serverless deployments."
        )
    # Route whatever scheme the platform hands us (postgres://, postgresql://,
    # even postgresql+psycopg://) onto the asyncpg driver the app uses.
    url = make_url(raw).set(drivername="postgresql+asyncpg")

    # libpq's `sslmode` query param (Neon/Vercel URLs use `?sslmode=require`) is
    # not understood by asyncpg, which spells the option `ssl` — and SQLAlchemy's
    # asyncpg dialect passes query keys straight through to asyncpg.connect. Left
    # as-is it would raise "unexpected keyword argument 'sslmode'" on first use,
    # so translate it. asyncpg accepts the same libpq value strings for `ssl`.
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if sslmode is not None and "ssl" not in query:
        query["ssl"] = sslmode

    # Neon/Vercel pooled URLs also carry `channel_binding=require`, another
    # libpq-only param SQLAlchemy would forward to asyncpg.connect (raising
    # "unexpected keyword argument 'channel_binding'"). asyncpg has no such
    # kwarg — it negotiates SCRAM channel binding automatically over SSL — so
    # the param is redundant here; drop it rather than translate it.
    query.pop("channel_binding", None)
    return url.set(query=query)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(
        _database_url(),
        # NullPool: on serverless (Vercel functions) an external pooler (Neon's
        # PgBouncer endpoint) owns pooling; the app holds no idle pool of its own.
        poolclass=NullPool,
        # Neon's pooled endpoint is PgBouncer in transaction mode: it multiplexes
        # clients onto shared server connections, where asyncpg's server-side
        # prepared statements collide. Disable asyncpg's own statement cache AND
        # SQLAlchemy's separate prepared-statement cache, and give each prepared
        # statement a unique name so names never clash across pooled backends
        # (the default asyncpg naming is sequential — __asyncpg_stmt_N__).
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request."""
    async with get_sessionmaker()() as session:
        yield session
