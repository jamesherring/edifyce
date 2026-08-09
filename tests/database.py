"""Throwaway databases for the API test suites.

SQLite by default: fast, no setup, and every table these suites touch is
SQLite-creatable (the pgvector ``theorems`` table is excluded everywhere).

Set ``EDIFYCE_TEST_DATABASE_URL`` to run the same tests against a real
Postgres — ``scripts/edifyce-dev db up`` provisions one and ``scripts/edifyce-dev
env`` prints the URL::

    EDIFYCE_TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:5439/edifyce" \\
      uv run pytest tests/test_proofs_api.py

That is worth doing because SQLite hides the things the real deployment does
differently, and the proof-verify path leans on several of them: the recursive
CTE that sweeps a term subgraph, ``ON DELETE`` behaviour (SQLite ignores it
without a per-connection pragma), the advisory lock that serialises term
interning (a no-op off Postgres), and the native ``uuid``/``jsonb`` types where
SQLite stores text.

Every test gets an empty schema. On Postgres that means dropping and recreating
the tables, so a Postgres run is serial by construction — it shares one database
rather than one file per test, and ``tests/conftest.py`` refuses to run one under
xdist for that reason. On SQLite each test gets its own file, copied from a
prebuilt empty one, and the suite parallelises freely — which is what CI does.
"""

from __future__ import annotations

import os
from pathlib import Path
from shutil import copyfile
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Protocol, TypeGuard

from sqlalchemy import create_engine, event, make_url

if TYPE_CHECKING:
    from sqlalchemy import Table

# The URL a test run targets, or None for a per-test SQLite file.
TEST_DATABASE_URL = os.environ.get("EDIFYCE_TEST_DATABASE_URL")
ON_POSTGRES = TEST_DATABASE_URL is not None


def database_url(tmp_path: Path, name: str = "test") -> str:
    """The synchronous URL for this test's throwaway database."""
    if TEST_DATABASE_URL is None:
        return f"sqlite:///{tmp_path / f'{name}.db'}"
    # psycopg (v3) rather than the default psycopg2: it is what the dev group
    # installs, and the app's own asyncpg is async-only.
    return make_url(TEST_DATABASE_URL).set(
        drivername="postgresql+psycopg"
    ).render_as_string(hide_password=False)


def async_url(url: str) -> str:
    """The async driver URL matching a synchronous one."""
    parsed = make_url(url)
    driver = "sqlite+aiosqlite" if parsed.drivername.startswith("sqlite") else "postgresql+asyncpg"
    return parsed.set(drivername=driver).render_as_string(hide_password=False)


def create_tables(url: str, tables: list[Table]) -> None:
    """Give this test an empty schema.

    Everything is dropped first, not just ``tables``: a Postgres run reuses one
    database across suites, so a previous suite's rows would be visible and — the
    part that actually breaks — a table it created may hold a foreign key *into*
    one of these, which then refuses to drop. SQLite gets a fresh file per test
    and does not care either way.

    Deduped, because a suite naming one of the `_always` tables itself is not an
    error — it is a suite whose own list is honest about what it uses.
    """
    wanted = list(dict.fromkeys([*tables, *_always()]))
    if not ON_POSTGRES:
        _copy_empty_schema(url, wanted)
        return

    engine = create_engine(url)
    try:
        metadata = tables[0].metadata
        metadata.drop_all(engine)
        metadata.create_all(engine, tables=wanted)
    finally:
        engine.dispose()


# One built schema per distinct table set, keyed by the names in it. Process-local,
# so an xdist worker builds its own and no two workers share a file.
_SCHEMA_TEMPLATES: dict[frozenset[str], Path] = {}


def _copy_empty_schema(url: str, wanted: list[Table]) -> None:
    """The SQLite half of :func:`create_tables`, as a file copy.

    Issuing ~47 ``CREATE TABLE``s takes ~0.1s, and several hundred tests each
    want the same empty schema — the same seventeen table sets over and over. So
    build each set once and copy the resulting file, which is the identical
    result for about a millisecond.

    Nothing is shared *between* tests by doing this: every test still gets its
    own file, and the template is only ever read. It is the CREATE statements
    that are cached, not any data — a template is empty and stays empty.
    """
    key = frozenset(table.name for table in wanted)
    template = _SCHEMA_TEMPLATES.get(key)
    if template is None:
        template = Path(mkdtemp(prefix="edifyce-schema-")) / "template.db"
        engine = create_engine(f"sqlite:///{template}")
        try:
            wanted[0].metadata.create_all(engine, tables=wanted)
        finally:
            engine.dispose()
        _SCHEMA_TEMPLATES[key] = template

    copyfile(template, make_url(url).database)


def _always() -> list[Table]:
    """Tables every system-building test needs whether it names them or not.

    `load_effective` queries `system_relations` on every build — an edge is one
    of the places a citation may resolve (R4) — so the table is part of the
    minimum a system needs, exactly as `terms` and `promoted_theorems` already
    are. `notation_pieces` joins them for the same reason on the read side: a
    system's detail reports which notations it stores, so every read of one
    queries the table whether the test has heard of notations or not. So do
    `label_descriptions` / `label_attributions` / `label_references`, which a single
    proof read consults for the corpus's record of that proof's label — and, since
    that record carries its cross-references, its bibliography citations and what
    points back at it, for both directions of the reference graph.
    `label_claims` rides along with it: the same read reports what the corpus's
    `$j` markup asserts about that label. So does
    `theorem_assumptions`: promoting a theorem records what it rests on that
    nobody proved, so the table is written on a path no test has to know about
    (and `assumptions` is read beside it). `proof_lines` and `theorems` join them
    for the delete side: tearing a system down clears everything that cites its
    term graph before the terms themselves (`terms_mapping.delete_system_terms`),
    so both tables are named by a statement every system delete issues, empty or
    not. `theorems` carries a pgvector column, which SQLite stores as a plain
    declared type — only the HNSW index is Postgres-specific, and that rides a
    `postgresql_using` other dialects ignore. Added here rather than to each
    module's own list because "what a system minimally needs" is one fact, and
    ten copies of it drift.
    """
    from app.db.system_relations import (
        SystemRelationExtraRow,
        SystemRelationObligationRow,
        SystemRelationRow,
        SystemRelationSortRow,
        SystemRelationSymbolRow,
    )
    from app.db.assumptions import AssumptionRow, TheoremAssumptionRow
    from app.db.formalizations import (
        FormalizationRow,
        GlossaryEntryRow,
        SourceDocumentRow,
    )
    from app.db.claims import LabelClaimRow
    from app.db.models import Theorem
    from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
    from app.db.descriptions import (
        LabelAttributionRow,
        LabelCitationRow,
        LabelDescriptionRow,
        LabelReferenceRow,
    )
    from app.db.systems import (
        NotationPieceRow,
        NotationRulePieceRow,
        NotationRulePinRow,
        NotationRuleRow,
    )

    return [
        SystemRelationRow.__table__,
        SystemRelationSortRow.__table__,
        SystemRelationSymbolRow.__table__,
        SystemRelationExtraRow.__table__,
        SystemRelationObligationRow.__table__,
        NotationPieceRow.__table__,
        NotationRuleRow.__table__,
        NotationRulePinRow.__table__,
        NotationRulePieceRow.__table__,
        LabelDescriptionRow.__table__,
        LabelAttributionRow.__table__,
        LabelReferenceRow.__table__,
        LabelCitationRow.__table__,
        LabelClaimRow.__table__,
        AssumptionRow.__table__,
        TheoremAssumptionRow.__table__,
        SourceDocumentRow.__table__,
        FormalizationRow.__table__,
        GlossaryEntryRow.__table__,
        ProofLineRow.__table__,
        ProofLineAntecedentRow.__table__,
        Theorem.__table__,
    ]


def enable_foreign_keys(engine) -> None:  # noqa: ANN001 - Engine or AsyncEngine's sync_engine
    """SQLite ignores ``ON DELETE`` unless asked, per connection. Postgres does
    not need telling, and the pragma is not valid there."""
    if not engine.url.drivername.startswith("sqlite"):
        return

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):  # noqa: ANN001, ANN202
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


class DBAPIConnection(Protocol):
    """The one method these helpers ask of a raw driver connection."""

    def execute(self, sql: str, /) -> object: ...


def is_sqlite_connection(dbapi_connection: object) -> TypeGuard[DBAPIConnection]:
    """Whether a DBAPI connection is one of the two SQLite drivers.

    SQLAlchemy's ``connect`` event carries the raw connection and no dialect, and
    ``isinstance(..., sqlite3.Connection)`` sees only the synchronous driver —
    aiosqlite's is an adapter class of SQLAlchemy's own. Both live under a module
    path naming the dialect, which is what tells them from psycopg/asyncpg.
    """
    return "sqlite" in type(dbapi_connection).__module__


def relax_sqlite_durability(dbapi_connection: DBAPIConnection) -> None:
    """Stop a throwaway database paying for crash safety it cannot use.

    SQLite fsyncs at every commit by default, and each test's schema is ~47
    ``CREATE TABLE``s against a fresh file — around 0.2s of waiting on the disk
    before the test has done anything, on every one of the several hundred tests
    that ask for a database. These files live in ``tmp_path`` and are read only
    by the process that wrote them, so a crash mid-test destroys nothing a rerun
    would not rebuild anyway.

    Only durability is given up. Transactions, rollback and foreign keys behave
    exactly as before, so nothing a test asserts about the database changes.
    """
    dbapi_connection.execute("PRAGMA synchronous=OFF")
