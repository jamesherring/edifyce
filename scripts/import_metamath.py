#!/usr/bin/env python
"""Import a Metamath database into Edifyce's tables.

    uv run python scripts/import_metamath.py set.mm --limit 1000

Reads the `.mm` file, checks each theorem with Edifyce's own kernel in
declaration order, and stores what checked: one formal system, one proof per
theorem, and the proof's structure — its lines, their justification edges, and
their formulas interned into the system's shared term graph.

Needs `DATABASE_URL` (or `POSTGRES_URL`) pointing at a migrated database;
`scripts/edifyce-dev db up && scripts/edifyce-dev migrate` provisions one.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable
from pathlib import Path

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/import_metamath.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.metamath_store import ImportReport, import_corpus  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from website.logical.metamath import CheckedTheorem, parse  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit", type=int, default=None, help="import only the first N theorems"
    )
    parser.add_argument("--name", default="Metamath", help="name for the stored system")
    parser.add_argument(
        "--batch", type=int, default=50, help="commit every N theorems (default 50)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress the per-theorem progress line"
    )
    return parser.parse_args()


def _reporter(total: int | None) -> Callable[[ImportReport, CheckedTheorem], None]:
    # Rate-limited to twice a second: a whole-corpus run checks tens of thousands
    # of theorems, and redrawing the line for each of them costs more than the
    # import does.
    last = [0.0]

    def report(running: ImportReport, checked: CheckedTheorem) -> None:
        now = time.monotonic()
        if now - last[0] < 0.5 and running.checked != total:
            return
        last[0] = now
        of = f"/{total}" if total else ""
        print(
            f"\r  {running.checked}{of} checked — "
            f"{running.verified} verified, {running.rejected} rejected, "
            f"{running.failed} failed, {running.lines} lines"
            f"  (last: {checked.label})".ljust(100),
            end="",
            flush=True,
        )

    return report


async def main() -> int:
    arguments = _arguments()

    started = time.monotonic()
    print(f"Reading {arguments.source}…", flush=True)
    database = parse(arguments.source.read_text())
    print(
        f"  {len(database.assertions)} assertions in {time.monotonic() - started:.1f}s",
        flush=True,
    )

    started = time.monotonic()
    progress = None if arguments.quiet else _reporter(arguments.limit)
    async with get_sessionmaker()() as session:
        report = await session.run_sync(
            lambda sync: import_corpus(
                sync,
                database,
                limit=arguments.limit,
                name=arguments.name,
                batch=arguments.batch,
                progress=progress,
            )
        )
    await get_engine().dispose()

    if progress is not None:
        print()
    elapsed = time.monotonic() - started
    print(f"\nSystem {report.system_id} — {elapsed:.1f}s")
    print(f"  checked   {report.checked}")
    print(f"  verified  {report.verified}")
    print(f"  rejected  {report.rejected}")
    print(f"  failed    {report.failed}")
    print(f"  lines     {report.lines} ({report.formulas} carrying a formula)")
    for label, error in report.failures:
        print(f"    ! {label}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
