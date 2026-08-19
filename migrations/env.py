"""Alembic environment: how a migration finds the database and the models.

The models in `app/db/` are the source of truth. `--autogenerate` and `check`
compare them against a live database, so both need one to point at; `upgrade`
needs the database it is changing. All three take the URL from here.

Two things this configures that Alembic leaves off by default, and that the
Atlas setup this replaced checked as a matter of course: `compare_type` and
`compare_server_default`. Without them a widened column or a changed
`server_default` is invisible to the drift check, which is most of what the
drift check is for.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from alembic import context
from sqlalchemy import create_engine, make_url, pool

from app.db import Base

if TYPE_CHECKING:
    from alembic.autogenerate.api import AutogenContext

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """The database this invocation targets.

    Three sources, most explicit first: `-x url=...` on the command line, then
    `MIGRATE_URL` (what the apply workflow sets, so a deploy can point at the
    unpooled endpoint without disturbing the app's own `DATABASE_URL`), then
    `DATABASE_URL`.

    Normalised on the way through, because the URLs already in circulation are
    not spelled the way SQLAlchemy wants them: they name an async driver the app
    uses, or carry a `search_path` parameter that only Atlas ever understood.
    """
    raw = (
        context.get_x_argument(as_dictionary=True).get("url")
        or os.environ.get("MIGRATE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not raw:
        raise RuntimeError(
            "No database URL. Set DATABASE_URL (or MIGRATE_URL), or pass "
            "`-x url=postgresql://...`."
        )

    url = make_url(raw)
    # psycopg (v3) rather than asyncpg: a migration runs on a plain Connection,
    # and asyncpg cannot supply one. Rewritten rather than rejected so the app's
    # own DATABASE_URL works here unchanged.
    if url.drivername.startswith("postgres"):
        url = url.set(drivername="postgresql+psycopg")
    # `search_path` is an Atlas-specific query parameter, left over in the
    # deployment URLs from the tool this replaced. libpq rejects it, and Alembic
    # does not need it: it reflects only the default schema, so Neon's unrelated
    # `neon_auth` schema stays out of view either way.
    if "search_path" in url.query:
        url = url.difference_update_query(["search_path"])
    return url.render_as_string(hide_password=False)


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    """Render pgvector's column type with an import that resolves.

    Autogenerate spells the type by its module path but does not know to import
    the module, so a generated migration referencing it fails with `NameError`.
    Everything else falls through to the default rendering.
    """
    if type_ == "type" and type(obj).__module__.startswith("pgvector."):
        autogen_context.imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def run_migrations_offline() -> None:
    """Emit the SQL a migration would run, without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run the migrations."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                render_item=_render_item,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
