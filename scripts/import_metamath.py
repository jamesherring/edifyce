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
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/import_metamath.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.metamath_store import ImportReport, import_corpus  # noqa: E402
from app.db.models import FormalSystem, User  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.db.systems_mapping import system_slug  # noqa: E402
from website.logical.metamath import CheckedTheorem, parse  # noqa: E402
from website.logical.metamath.setmm import (  # noqa: E402
    DISPLAY_OVERRIDES,
    DISPLAY_RULES,
    LAYERS,
)


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
        "--setmm-overrides",
        action="store_true",
        help=(
            "apply the curated set.mm display tables (setmm.DISPLAY_OVERRIDES and "
            "setmm.DISPLAY_RULES). Off by default: a Metamath label is local to "
            "its library, so the tables mean what they say only for set.mm"
        ),
    )
    parser.add_argument(
        "--owner",
        metavar="EMAIL",
        default=None,
        help=(
            "hand the import to this registered user — every system and every "
            "proof. Ownerless by default, which is what a shared library wants. "
            "An owned import is reachable by the owner-scoped routes, so a verify "
            "on one of its proofs will write its verdict back over the imported "
            "structure; that is the trade, and it is why this is opt-in"
        ),
    )
    parser.add_argument(
        "--setmm-layers",
        action="store_true",
        help=(
            "store the corpus as a spine of systems (setmm.LAYERS: propositional "
            "calculus, then first-order logic, then ZF set theory) rather than "
            "one. Off by default, and off for the same reason the display tables "
            "are: a layer plan names one library's own section titles"
        ),
    )
    return parser.parse_args()


async def _owner(session: AsyncSession, email: str | None) -> uuid.UUID | None:
    """Resolve ``--owner`` to a user id, before a single row is written.

    Looked up rather than created: handing a corpus to an address nobody has
    registered would silently produce an owner who cannot sign in, and the
    mistake would not surface until someone went looking for 47,000 proofs that
    are not in anyone's list. Matched case-insensitively, since that is how
    fastapi-users stores and compares an address.
    """
    if email is None:
        return None
    # The id alone, not the row: `User` eagerly joins its OAuth accounts, and an
    # ownership assignment wants neither them nor the password hash.
    owner = (
        await session.scalars(
            select(User.id).where(func.lower(User.email) == email.strip().lower())
        )
    ).first()
    if owner is None:
        raise LookupError(
            f"No registered user with the address {email!r}. "
            "Register the account first, or drop --owner to import ownerless."
        )
    return owner


async def _refuse_a_slug_collision(
    session: AsyncSession, owner: uuid.UUID | None, names: Sequence[str]
) -> None:
    """Stop an owned import that would collide with the owner's own systems.

    `formal_systems` is uniquely indexed on (owner, slug) for owned rows, so a
    corpus whose layer names slugify onto systems this user already has raises an
    integrity error out of `layered_systems`' first flush. That is seconds in
    rather than minutes, so nothing is lost — but a stack trace is a poor way to
    say "you already have one of these", and unlike the parse above it costs
    nothing to ask first.
    """
    if owner is None:
        return
    wanted = {system_slug(name) for name in names}
    taken = set(
        (
            await session.scalars(
                select(FormalSystem.slug).where(
                    FormalSystem.owner_id == owner, FormalSystem.slug.in_(wanted)
                )
            )
        ).all()
    )
    if taken:
        raise LookupError(
            "This user already owns a system at "
            + ", ".join(repr(slug) for slug in sorted(taken))
            + ". Rename with --name, or import ownerless and assign it later."
        )


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
        try:
            owner = await _owner(session, arguments.owner)
            # The names the run *could* create. An unlayered import makes exactly
            # one system, called `--name`; a layered one makes the plan's — except
            # where the file opens none of the plan's sections, which
            # `corpus_specs` treats as no plan at all and which therefore falls
            # back to `--name` again. So a layered run checks both rather than the
            # plan alone, or the one name it would actually use is the one name
            # unchecked, and the collision this exists to pre-empt arrives as the
            # IntegrityError instead (found in review).
            #
            # Over-approximating is the settled policy here: refusing a collision
            # the import would not have reached is the safe direction for a check
            # whose whole job is to fail early.
            await _refuse_a_slug_collision(
                session,
                owner,
                [arguments.name, *(layer.name for layer in LAYERS)]
                if arguments.setmm_layers
                else [arguments.name],
            )
        except LookupError as refused:
            print(f"\n{refused}", file=sys.stderr)
            await get_engine().dispose()
            return 2
        report = await session.run_sync(
            lambda sync: import_corpus(
                sync,
                database,
                limit=arguments.limit,
                name=arguments.name,
                batch=arguments.batch,
                progress=progress,
                # Opt-in, because a Metamath label is local to its library: a
                # foreign `cfv` matching set.mm's name and slots would still be
                # rendered by set.mm's judgement about what `cfv` means.
                # `display.applicable` stops the mess, not the presumption.
                overrides=DISPLAY_OVERRIDES if arguments.setmm_overrides else None,
                rules=DISPLAY_RULES if arguments.setmm_overrides else None,
                plan=LAYERS if arguments.setmm_layers else (),
                owner=owner,
                # The file's name, which the parse does not carry: it is what
                # names the library in the provenance every system records.
                source=arguments.source.name,
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
    # The spine, root first. Printed only when there is one to print: for an
    # unlayered import the single entry restates the totals above, which reads as
    # noise rather than as information.
    if len(report.layers) > 1:
        print("\n  layers (root first)")
        for layer in report.layers:
            print(
                f"    {layer.name}\n"
                f"      {layer.proofs} proofs, {layer.theorems} theorems "
                f"({layer.primitives} primitive), "
                f"{layer.sections} sections, {layer.described} described"
            )
    for label, error in report.failures:
        print(f"    ! {label}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
