#!/usr/bin/env python
"""Record, on proofs stored before the column existed, which entry each citation named.

    uv run python scripts/backfill_line_citations.py --dry-run
    uv run python scripts/backfill_line_citations.py

``proof_lines.rule`` holds the *label* of the rule that justified a line. A label
is only a citation: turning it back into the library entry it named means knowing
the citing system's whole library order, which is a chain load — every part row of
every ancestor — for a question the checker already answered when it resolved the
line. So a check now records the answer on the line (``proof_lines.theorem_id``),
and the provenance report reads it instead of re-deriving it.

Proofs checked before that column have no answer stored, and
``proofs.citations_stored`` is what says so. This fills them in.

**It resolves the way a citation resolves**, through the real
:class:`~app.db.promoted_theorems_mapping.LibraryChain` — nearest layer first,
relation edges included — rather than through a query that guesses at the order.
That is the whole reason this is a script and not SQL in the migration: the rule
it has to reproduce is `_nearest`'s, and a hand-written recursive CTE that gets
inheritance subtly wrong would attach a proof's citations to an ancestor's entry
where a descendant shadows it, and nothing downstream would notice.

**Per system**, because the library order is a property of the system and every
proof in one shares it: the chain is loaded once and spent over all of that
system's proofs.

**Idempotent.** A proof already carrying the flag is skipped, so a re-run costs
one query. A proof whose system no longer builds is left alone and counted — it
keeps the flag ``False`` and goes on being read the old way, which is correct
rather than merely safe.

Needs ``DATABASE_URL`` (or ``POSTGRES_URL``) pointing at the database to fill in.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.assumptions import resolve_labels  # noqa: E402
from app.db.models import Proof  # noqa: E402
from app.db.proof_lines import ProofLineRow  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.routers.systems import load_effective, load_system  # noqa: E402

# How many proofs to resolve before committing. A corpus holds ~47,000 and each
# one's lines are read to find its labels, so the run checkpoints for the same
# reason an import does.
CHUNK = 500


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    return parser.parse_args()


async def _library_order(session: AsyncSession, system_id) -> list | None:
    """Where a citation in this system resolves, or None if it no longer builds."""
    system = await load_system(session, system_id)
    if system is None:
        return None
    effective = await load_effective(session, system)
    if effective.errors:
        return None
    return effective.library.system_ids


async def backfill(session: AsyncSession, dry_run: bool) -> dict[str, int]:
    """Fill in every unresolved proof's citations, system by system."""
    tally = {"systems": 0, "proofs": 0, "lines": 0, "skipped": 0}

    systems = (
        await session.scalars(
            select(Proof.formal_system_id)
            .where(Proof.citations_stored.is_(False))
            .distinct()
        )
    ).all()

    for system_id in systems:
        tally["systems"] += 1
        order = await _library_order(session, system_id)
        pending = (
            await session.scalar(
                select(func.count())
                .select_from(Proof)
                .where(
                    Proof.formal_system_id == system_id,
                    Proof.citations_stored.is_(False),
                )
            )
        ) or 0
        if order is None:
            # Its grammar no longer resolves, so there is no order to resolve
            # against. Left unflagged, which keeps it on the old read path rather
            # than recording a resolution nobody made.
            tally["skipped"] += pending
            continue

        while True:
            proofs = (
                await session.scalars(
                    select(Proof.id)
                    .where(
                        Proof.formal_system_id == system_id,
                        Proof.citations_stored.is_(False),
                    )
                    # By id, so the pages of one run partition the set: an
                    # unordered LIMIT/OFFSET may show a row twice and skip another.
                    # No OFFSET, because each page is flagged and so leaves the
                    # predicate — except on a dry run, which changes nothing and
                    # would loop forever on the same page.
                    .order_by(Proof.id)
                    .limit(CHUNK)
                )
            ).all()
            if not proofs:
                break

            labels = (
                await session.scalars(
                    select(ProofLineRow.rule)
                    .where(
                        ProofLineRow.proof_id.in_(list(proofs)),
                        ProofLineRow.rule.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            entries = await session.run_sync(
                lambda sync: resolve_labels(sync, order, list(labels))
            )
            tally["proofs"] += len(proofs)

            if dry_run:
                # Count what would be written, then stop: nothing left the
                # predicate, so a second page would be the first one again.
                tally["lines"] += await session.scalar(
                    select(func.count())
                    .select_from(ProofLineRow)
                    .where(
                        ProofLineRow.proof_id.in_(list(proofs)),
                        ProofLineRow.rule.in_(list(entries)),
                    )
                ) or 0
                break

            for label, theorem_id in entries.items():
                result = await session.execute(
                    update(ProofLineRow)
                    .where(
                        ProofLineRow.proof_id.in_(list(proofs)),
                        ProofLineRow.rule == label,
                    )
                    .values(theorem_id=theorem_id)
                )
                tally["lines"] += result.rowcount or 0
            # Flagged last, and in the same transaction as the values above: the
            # flag is the claim that those columns were written, so a commit
            # carrying one without the other would have a proof reporting a
            # resolution it does not hold.
            await session.execute(
                update(Proof)
                .where(Proof.id.in_(list(proofs)))
                .values(citations_stored=True)
            )
            await session.commit()

    return tally


async def main() -> int:
    args = _arguments()
    engine = get_engine()
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            tally = await backfill(session, args.dry_run)
            if not args.dry_run:
                await session.commit()
    finally:
        await engine.dispose()

    print(
        f"{tally['systems']} systems, {tally['proofs']} proofs, "
        f"{tally['lines']} lines resolved"
        + (f", {tally['skipped']} proofs skipped (system does not build)"
           if tally["skipped"] else "")
        + (" (dry run, nothing written)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
