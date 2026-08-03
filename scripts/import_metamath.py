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
from website.logical.metamath.setmm import DISPLAY_OVERRIDES  # noqa: E402


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {number}")
    return number


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit", type=_positive, default=None, help="import only the first N theorems"
    )
    parser.add_argument("--name", default="Metamath", help="name for the stored system")
    parser.add_argument(
        "--batch", type=_positive, default=50, help="commit every N theorems (default 50)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress the per-theorem progress line"
    )
    parser.add_argument(
        "--no-overrides",
        action="store_true",
        help=(
            "skip the curated per-production display overrides, storing each "
            "notation exactly as the file's $t map derives it"
        ),
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
    # `.mm` is UTF-8 (set.mm's comments and `$t` block are not ASCII); reading it
    # under the platform locale fails outright wherever that is not UTF-8.
    database = parse(arguments.source.read_text(encoding="utf-8"))
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
                # `set.mm`'s table, and this script imports any `.mm` — but an
                # override naming a constructor this grammar lacks, or slots it
                # does not take, is dropped rather than stored (`display.applicable`),
                # so handing it over costs a file that is not `set.mm` nothing.
                overrides=None if arguments.no_overrides else DISPLAY_OVERRIDES,
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
    print(f"  theorems  {report.theorems} ({report.primitives} primitive)")
    # What the run derived beside the proofs. Reported because a zero here is the
    # only sign that a file carried no `$t`, no comments or no section headers —
    # each of which is legitimate, and each of which silently costs a feature.
    print(f"  described {report.described}")
    print(f"  notation  {report.notation}")
    print(f"  sections  {report.sections}")
    for label, error in report.failures:
        print(f"    ! {label}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
