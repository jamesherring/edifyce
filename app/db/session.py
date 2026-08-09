"""Engine and session wiring — async for the API, synchronous for batch work.

Kept lazy on purpose: importing this module must not open a connection (the Atlas
schema loader imports the package offline, and the API should boot without a
database when `DATABASE_URL` is unset). The engine is created on first use.

Both drivers are configured from the *same* environment variable and the same
pair of URL rules, so a deployment describes its database once
(`_configured_url`, `asyncpg_url`, `psycopg_url`).
"""

import os
from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import NullPool, create_engine, make_url
from sqlalchemy.engine import URL, Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def asyncpg_url(raw: str | URL) -> URL:
    """``raw`` on the asyncpg driver, with libpq-only query params dealt with.

    Public because anything opening an async engine against a URL a *platform*
    wrote needs exactly this, and there is nowhere else the knowledge lives: a
    Neon or Vercel connection string is a libpq string, and asyncpg is not libpq.
    A second copy of these two rules would be a second thing to keep in step
    (`scripts/restore_proofs.py` is the other caller).
    """
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


def psycopg_url(raw: str | URL) -> URL:
    """``raw`` on psycopg 3, which is the synchronous counterpart of the above.

    Two things make this more than a `set(drivername=...)`. SQLAlchemy resolves a
    bare ``postgresql://`` to **psycopg2**, which this project does not depend on;
    and ``postgres://`` — the scheme Neon, Vercel and Heroku hand out — resolves to
    no dialect at all. Either dies inside `create_engine`.

    Query params are deliberately left as they came, which is the whole
    difference from :func:`asyncpg_url`: psycopg speaks libpq, so ``sslmode`` and
    ``channel_binding`` already mean there exactly what they mean in the URL.

    Here rather than in a script because this and `asyncpg_url` are two halves of
    one fact about platform URLs, and a copy kept somewhere else is a copy that
    drifts. Batch work reaches for this: a walk of a corpus is synchronous from
    end to end, and driving it through the async engine costs it the event loop
    (see `scripts/import_metamath.py`).
    """
    return make_url(raw).set(drivername="postgresql+psycopg")


def _configured_url() -> str:
    # Prefer DATABASE_URL, but fall back to POSTGRES_URL: the Neon/Vercel
    # Marketplace integration provisions the latter (pooled) automatically, so
    # accepting it lets those deployments work without a manual alias.
    raw = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not raw:
        raise RuntimeError(
            "Neither DATABASE_URL nor POSTGRES_URL is set. Point one at the Neon "
            "*pooled* connection string (the '-pooler' host) for serverless "
            "deployments."
        )
    return raw


def _database_url() -> URL:
    return asyncpg_url(_configured_url())


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


@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    """The same database on a synchronous driver, for batch work off the request path.

    Nothing the API serves wants this — a request is async all the way down. A
    *corpus import* is the opposite: `app.db.metamath_store.import_corpus` is
    synchronous, and reaching it through `AsyncSession.run_sync` puts a greenlet
    hop and an event-loop iteration around every statement it issues. Measured
    over the first 3,000 theorems of `set.mm`, the same import writing the same
    rows costs 46.9 ms/theorem through the async engine and 24.5 ms through this
    one — the transport, not the work.

    Deliberately not the pool the async engine uses: `NullPool` is there because
    a serverless function should hold no idle connections, and a batch job that
    runs for an hour on one session wants the ordinary pool.
    """
    return create_engine(psycopg_url(_configured_url()))
