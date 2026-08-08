#!/usr/bin/env python
"""Re-read the markup in descriptions a previous import already stored.

    uv run python scripts/rebuild_markup.py --dry-run
    uv run python scripts/rebuild_markup.py

An import written before cross-references and the discouragement markers were
understood stored the prose with both still *in* it: `~ ax-13` as punctuation, and
`(New usage is discouraged.)` as a sentence. The migration that adds
``label_references`` cannot fix that — it adds empty columns and an empty table,
and nothing re-reads the text afterwards (raised in review), so a corpus imported
before the change goes on showing raw markup until someone re-imports 47,000
theorems.

It does not need re-importing, because **the answer is already in the row**. The
references were always extracted from the assembled prose and their offsets index
exactly that, so running the reader over ``label_descriptions.text`` produces the
same rows a fresh import would — no `.mm` file, no re-check, no walk.

**Idempotent**, which matters because the obvious implementation is not. A row
this has already rewritten has its markers gone, so reading it again finds none —
and *assigning* the result would clear flags that are correctly set. The flags are
therefore OR-ed in and never cleared. The references are replaced outright, which
is safe for the opposite reason: re-extraction from the same text is exact.

Needs ``DATABASE_URL`` (or ``POSTGRES_URL``) pointing at the database to fix.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.descriptions import LabelDescriptionRow, LabelReferenceRow  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from website.logical.metamath.comments import read_comment  # noqa: E402

# How many descriptions to hold at once. `set.mm` stores 50,550 of them and each
# carries its prose, so the whole table is hundreds of megabytes — the same reason
# an import checkpoints rather than accumulating.
CHUNK = 2000


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    return parser.parse_args()


async def rebuild(session: AsyncSession, dry_run: bool) -> dict[str, int]:
    """Re-read every stored description's markup, returning what moved."""
    total = await session.scalar(
        select(func.count()).select_from(LabelDescriptionRow)
    )
    tally = {"read": 0, "rewritten": 0, "references": 0, "usage": 0, "modification": 0}

    for offset in range(0, total or 0, CHUNK):
        rows = (
            await session.scalars(
                select(LabelDescriptionRow)
                # By id, so the pages of one run partition the table: an unordered
                # `LIMIT/OFFSET` may show a row twice and skip another.
                .order_by(LabelDescriptionRow.id)
                .limit(CHUNK)
                .offset(offset)
            )
        ).all()
        for row in rows:
            tally["read"] += 1
            # The stored prose is already unwrapped and already has its
            # attributions removed, and both are idempotent — so this reads as the
            # markup pass alone.
            redone = read_comment(row.text)
            changed = redone.text != row.text
            gained = list(redone.references)
            if not (changed or gained or redone.discouraged_usage
                    or redone.discouraged_modification):
                continue

            tally["rewritten"] += changed
            tally["references"] += len(gained)
            tally["usage"] += redone.discouraged_usage and not row.discouraged_usage
            tally["modification"] += (
                redone.discouraged_modification and not row.discouraged_modification
            )
            if dry_run:
                continue

            row.text = redone.text
            # OR-ed, never assigned: a row this has already fixed has no marker
            # left to find, and assigning would take back a flag that is right.
            row.discouraged_usage = row.discouraged_usage or redone.discouraged_usage
            row.discouraged_modification = (
                row.discouraged_modification or redone.discouraged_modification
            )
            await session.execute(
                delete(LabelReferenceRow).where(
                    LabelReferenceRow.description_id == row.id
                )
            )
            session.add_all(
                LabelReferenceRow(
                    description_id=row.id,
                    position=position,
                    target=reference.target,
                    start_offset=reference.start,
                    end_offset=reference.end,
                )
                for position, reference in enumerate(gained)
            )
        if not dry_run:
            await session.commit()

    return tally


async def main() -> int:
    arguments = _arguments()
    async with get_sessionmaker()() as session:
        tally = await rebuild(session, arguments.dry_run)
    await get_engine().dispose()

    print("would change" if arguments.dry_run else "changed")
    print(f"  descriptions read     {tally['read']}")
    print(f"  prose rewritten       {tally['rewritten']}")
    print(f"  references stored     {tally['references']}")
    print(f"  newly usage-flagged   {tally['usage']}")
    print(f"  newly modif.-flagged  {tally['modification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
