"""Two ways to get rows out of a corpus database, behind one call.

A local import is reached with psycopg over a socket. The shared dev database is
a Neon instance whose Postgres port this sandbox's egress policy does not allow,
but whose **SQL-over-HTTP** endpoint it does — so the same queries go out as
HTTPS POSTs instead. Which transport is in use changes nothing above this module.

Neither takes bind parameters. The two endpoints spell them differently (`:name`
against `$1`), and the only value the corpus reader ever interpolates is a system
UUID that came out of a previous query — so :func:`uuid_list` validates it as a
UUID and renders it inline, and the placeholder mismatch never arises.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

from sqlalchemy import create_engine, text

from app.db.session import psycopg_url

#: A query is a SQL string in, rows out. Values arrive as whatever the transport
#: gives; the reader coerces, which is why every column is selected as text or a
#: number rather than left to a driver's type mapping.
Query = Callable[[str], list[Sequence[Any]]]

_PAGE = 50_000


def uuid_list(values: Iterable[str]) -> str:
    """``'a','b'`` for an ``in (…)`` clause, each value checked to be a UUID."""
    return ", ".join(f"'{uuid.UUID(value)}'" for value in values)


def over_psycopg(database_url: str) -> Query:
    engine = create_engine(psycopg_url(database_url), future=True)

    def run(sql: str) -> list[Sequence[Any]]:
        with engine.connect() as connection:
            return list(connection.execute(text(sql)).all())

    return run


def over_neon_https(connection_string: str | None = None) -> Query:
    """Neon's SQL-over-HTTP endpoint, driven by `curl` so it uses the CA bundle.

    `curl` rather than urllib because the sandbox's proxy and trust settings are
    already wired into it, and an experiment is a poor place to re-derive them.
    """
    url = connection_string or os.environ["POSTGRES_URL"]
    host = urllib.parse.urlparse(url).hostname
    if host is None:
        raise ValueError(f"no host in the connection string: {url!r}")
    endpoint = f"https://{host}/sql"

    def run(sql: str) -> list[Sequence[Any]]:
        finished = subprocess.run(
            [
                "curl", "-sS", "-m", "300", "-X", "POST", endpoint,
                "-H", "Content-Type: application/json",
                "-H", f"Neon-Connection-String: {url}",
                "-H", "Neon-Raw-Text-Output: true",
                "-H", "Neon-Array-Mode: true",
                "-d", json.dumps({"query": sql, "params": []}),
            ],
            capture_output=True,
            text=True,
        )
        if finished.returncode:
            raise RuntimeError(f"curl failed: {finished.stderr[:400]}")
        payload = json.loads(finished.stdout)
        if "rows" not in payload:
            # The endpoint reports a SQL error as a JSON body, not a bad status.
            raise RuntimeError(f"query failed: {json.dumps(payload)[:400]}")
        return payload["rows"]

    return run


def paged(
    query: Query, sql: str, key: str, *, unique: bool = True
) -> Iterator[Sequence[Any]]:
    """Run ``sql`` in keyset-paged chunks, yielding every row.

    ``sql`` must select ``key`` first and carry a ``{page}`` placeholder *after
    an existing* ``where`` — every caller here already restricts to a system, so
    the paging condition is emitted as an ``and``. Keyset rather than ``offset``:
    the HTTP endpoint has a response size it will not exceed, and a corpus term
    graph is comfortably past it.

    ``unique=False`` is for a key that repeats across rows — ``term_children``,
    keyed by parent. A page can then end in the middle of one key's rows, so the
    next page re-reads that key inclusively and the caller de-duplicates. That is
    correct as long as no single key has more rows than a page holds, which for a
    parent's slots is not close.
    """
    last: str | None = None
    while True:
        if last is None:
            clause = ""
        else:
            comparison = ">" if unique else ">="
            clause = f"and {key} {comparison} '{uuid.UUID(last)}'"
        rows = query(sql.format(page=clause) + f" order by {key} limit {_PAGE}")
        if not rows:
            return
        yield from rows
        if len(rows) < _PAGE:
            return
        following = str(rows[-1][0])
        if following == last:
            raise RuntimeError(f"a single {key} fills a whole page: {following}")
        last = following
