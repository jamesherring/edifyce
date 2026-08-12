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
one query. Two kinds are deliberately left unflagged and counted instead, both on
the same rule — the flag is a *claim*, and a claim nothing resolved is worse than
no claim. A proof whose **system no longer builds** has no order to resolve
against. And a proof citing a label the library **cannot account for** — one that
names neither an entry, nor a rule of the chain, nor a hypothesis of the theorem
it proves — would have that citation silently reclassified as "cited no entry" by
the flag, where the old read path reports it as unresolved. Both go on being read
the old way, which is correct rather than merely safe.

Needs ``DATABASE_URL`` (or ``POSTGRES_URL``) pointing at the database to fill in.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.assumptions import explained_labels, resolve_labels  # noqa: E402
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


async def _library_order(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID] | None:
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

        # Paged by **key**, not by "what is left in the predicate". A real page
        # mostly leaves it, but not always — a proof citing a label this library
        # cannot account for is left unflagged on purpose (see `withheld` below)
        # and would otherwise be handed back forever — and a dry run flags
        # nothing at all, so with no key it would re-read its first page and
        # report a corpus as `CHUNK` proofs. The id is what makes the pages
        # partition the set either way.
        after: uuid.UUID | None = None
        while True:
            page = select(Proof.id).where(
                Proof.formal_system_id == system_id,
                Proof.citations_stored.is_(False),
            )
            if after is not None:
                page = page.where(Proof.id > after)
            proofs = (
                await session.scalars(page.order_by(Proof.id).limit(CHUNK))
            ).all()
            if not proofs:
                break
            after = proofs[-1]

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

            # A label that resolves to no entry is usually an inference rule or a
            # hypothesis, and neither is a dependency — but it can also be an
            # entry this database does not hold, which the report is *meant* to
            # name. Flagging such a proof would turn "unresolved" into "cited no
            # entry" and lose it, so `explained_labels` draws the same line the
            # read path draws and the proofs citing what is left over keep the
            # flag down.
            theorem_ids = list(
                await session.scalars(
                    select(Proof.theorem_id).where(
                        Proof.id.in_(list(proofs)), Proof.theorem_id.is_not(None)
                    )
                )
            )
            explained = await session.run_sync(
                lambda sync: explained_labels(sync, order, theorem_ids)
            )
            unaccounted = [
                label
                for label in labels
                if label not in entries and label not in explained
            ]
            withheld: set[uuid.UUID] = set()
            if unaccounted:
                withheld = set(
                    await session.scalars(
                        select(ProofLineRow.proof_id)
                        .where(
                            ProofLineRow.proof_id.in_(list(proofs)),
                            ProofLineRow.rule.in_(unaccounted),
                        )
                        .distinct()
                    )
                )
            resolvable = [pid for pid in proofs if pid not in withheld]
            tally["skipped"] += len(withheld)

            if dry_run:
                counted = await session.scalar(
                    select(func.count())
                    .select_from(ProofLineRow)
                    .where(
                        ProofLineRow.proof_id.in_(resolvable),
                        ProofLineRow.rule.in_(list(entries)),
                    )
                )
                tally["lines"] += counted or 0
                continue

            if not resolvable:
                continue
            for label, theorem_id in entries.items():
                result = await session.execute(
                    update(ProofLineRow)
                    .where(
                        ProofLineRow.proof_id.in_(resolvable),
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
                .where(Proof.id.in_(resolvable))
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
        + (f", {tally['skipped']} proofs left unflagged (system does not build, "
           "or a citation the library cannot account for)"
           if tally["skipped"] else "")
        + (" (dry run, nothing written)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
