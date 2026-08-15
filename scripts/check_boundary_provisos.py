#!/usr/bin/env python
"""Does a `$d` still refuse a capture after crossing a layer boundary?

    uv run python scripts/check_boundary_provisos.py set.mm --limit 2676

D5's last invariant (docs/system-relationships-roadmap.md §8): R2's guarantee,
restated over corpus data instead of a fixture. `set.mm`'s `ax-5` is
`( ph -> A. x ph )` carrying `$d x ph`, and a layered import files it in the
**first-order** layer. A proof written in the **ZF** layer that cites it must be
refused where the instance would capture and accepted where it would not — both
directions, because either one alone is passed by a check that is not running.

What the run exercises, end to end: the `$d` is read from the file, expanded to
one `disjoint` proviso per variable sort — `x` must not occur in `ph` as a
variable of *any* of them — stored against the layer that declares the theorem,
resolved from a *descendant* layer through `LibraryChain`, rebuilt from its
cached term rather than re-parsed, and enforced by the kernel.

Four things are asserted before the verdicts are believed, because each is a way
for this to pass while proving nothing:

- the chain is more than one system, so there is a boundary at all;
- `ax-5` is filed in an **ancestor** of the system the citations are parsed in,
  so the citation genuinely crosses it;
- its entry is digest-**fresh**, so the provisos come from the stored term. A
  miss is fatal for an inherited entry rather than merely slow (`promote`), so
  a run that lost the cache would not reach the verdicts — but it is checked
  here anyway, since "the cached term carried the proviso" is half the claim;
- what arrived carries side conditions at all.

A fifth is a verdict rather than a precondition: see :func:`control`.

A script rather than a test because `set.mm` is not in the repository. The
mechanism is pinned on fixtures by `tests/test_cross_system_citation.py` (R2)
and `tests/test_metamath_layered_store.py` (the import and the chain); this is
where the two meet on the real corpus.

Runs against throwaway in-memory SQLite, so it needs no ``DATABASE_URL`` and
leaves nothing behind.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/check_boundary_provisos.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base  # noqa: E402
from app.db.definition_terms import load_definition_terms  # noqa: E402
from app.db.metamath_store import import_corpus  # noqa: E402
from app.db.models import FormalSystem  # noqa: E402
from app.db.promoted_theorems_mapping import read_library  # noqa: E402
from app.db.schema_terms import load_schema_terms  # noqa: E402
from app.db.systems_mapping import (  # noqa: E402
    effective_library,
    inherited_definition_count,
    inherited_rule_count,
)
from app.db.terms_mapping import prefetch_terms, term_context  # noqa: E402
from website.logical.declarative import build_spec  # noqa: E402
from website.logical.metamath import parse  # noqa: E402
from website.logical.metamath.setmm import LAYERS  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.db.promoted_theorems_mapping import LibraryChain
    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system.promotion import PromotedTheorem

# The theorem whose proviso is under test, and the label a proof cites it by.
CITED = "ax-5"


@dataclass(frozen=True)
class Case:
    """One citation of :data:`CITED`, and the verdict the `$d` demands of it."""

    name: str
    text: str
    valid: bool


# Both instantiate `ax-5`'s `ph`. The first puts the bound `x` inside it, which
# `$d x ph` forbids; the second uses a different variable and is admissible.
CASES = (
    Case("capturing", "( x e. y -> A. x x e. y ) [ax-5]", False),
    Case("non-capturing", "( z e. y -> A. x z e. y ) [ax-5]", True),
)


def spine(session: Session, leaf_id: uuid.UUID) -> list[FormalSystem]:
    """The inheritance chain ending at ``leaf_id``, root first."""
    rows = {system.id: system for system in session.scalars(select(FormalSystem))}
    chain: list[FormalSystem] = []
    current: uuid.UUID | None = leaf_id
    while current is not None:
        system = rows[current]
        chain.append(system)
        current = system.inherits_from_id
    return list(reversed(chain))


def build(
    session: Session, chain: Sequence[FormalSystem], spec: SystemSpec
) -> EngineSystem:
    """Build the leaf of ``chain`` from its stored rows, ancestors folded in."""
    result = build_spec(
        spec,
        schema_terms=load_schema_terms(
            session, chain[-1], spec, inherited_rule_count(chain)
        ),
        definition_terms=load_definition_terms(
            session, chain[-1], spec, inherited_definition_count(chain)
        ),
    )
    if "errors" in result:
        raise SystemExit(f"the stored {chain[-1].name} does not build: {result['errors']}")
    return result["system"]


def promote(
    session: Session,
    chain: Sequence[FormalSystem],
    library: LibraryChain,
    built: EngineSystem,
) -> tuple[str, PromotedTheorem]:
    """Promote :data:`CITED` into ``built``; return its layer and the theorem.

    Spelled out rather than left to ``load_theorems`` so the vacuity guards can
    be asked of the same read the promotion uses: which system owns the entry,
    whether its cached term was still fresh, and whether it arrived carrying the
    `$d` at all.
    """
    names = {system.id: system.name for system in chain}
    pending = read_library(session, library, [CITED])
    entries = {entry.label: entry for entry in pending.cited}
    if CITED not in entries:
        raise SystemExit(f"{CITED} was not promoted by the import — nothing to cite.")
    owner = entries[CITED].system_id
    if owner == chain[-1].id:
        raise SystemExit(
            f"{CITED} is filed in {names[owner]}, the system the citations are "
            "parsed in — no boundary is crossed and the run proves nothing."
        )
    if CITED not in pending.fresh:
        raise SystemExit(
            f"{CITED}'s stored terms are stale, so its proviso would come from a "
            "re-parse rather than the row. See load_theorems' digest contract."
        )
    graph = prefetch_terms(session, pending.term_ids)
    promoted = pending.promote(built, term_context(built), graph)
    for theorem in promoted.values():
        built.promote(theorem)
    theorem = promoted[CITED]
    if not theorem.side_conditions:
        raise SystemExit(
            f"{CITED} crossed the boundary carrying no side conditions — its $d "
            "was lost on the way, and there is nothing here to enforce."
        )
    return names[owner], theorem


def verdict(built: EngineSystem, case: Case) -> bool:
    """Parse ``case`` against ``built`` and report whether it went as demanded."""
    line = built.parse(case.text).numbered_lines[0]
    got = bool(line.valid)
    print(
        f"  {'OK ' if got == case.valid else '** '} {case.name:<14} "
        f"valid={got} (want {case.valid})  {line.invalid_message or ''}"
    )
    return got == case.valid


def control(built: EngineSystem, theorem: PromotedTheorem) -> bool:
    """Re-run the capturing case with the proviso stripped; it must now pass.

    Without this the run's headline could be produced by a citation that simply
    fails to unify — "ax-5 does not apply" is what the checker says either way,
    and a refusal for the wrong reason is a check that is not running (§8's D5
    hit that shape more than once). Promoting a proviso-less copy under the same
    label answers it directly: if the capture is accepted once the `$d` is gone,
    the `$d` is what was refusing it.
    """
    built.promote(replace(theorem, side_conditions=()))
    capturing = next(case for case in CASES if not case.valid)
    return verdict(built, replace(capturing, name="control", valid=True))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit",
        type=int,
        default=2676,
        help=(
            "import only the first N theorems. The default 2676 is the milestone "
            "slice — the smallest at which the ZF layer holds a theorem at all, "
            "and so the smallest that puts a citation across a boundary"
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    # `.mm` is UTF-8 (set.mm's comments and `$t` block are not ASCII).
    source = arguments.source.read_text(encoding="utf-8")

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        print(f"Importing {arguments.source} against a {len(LAYERS)}-layer plan…",
              flush=True)
        report = import_corpus(
            session,
            parse(source),
            limit=arguments.limit,
            name="Metamath",
            batch=200,
            plan=LAYERS,
        )
        chain = spine(session, report.system_ids[-1])
        if len(chain) < 2:
            raise SystemExit(
                "the import produced one system, so there is no boundary to cross "
                "— raise --limit past the plan's second section."
            )
        print("  chain:", " -> ".join(system.name for system in chain))

        # One read of the chain's rows serves both the build and the library.
        spec, library = effective_library(chain)
        built = build(session, chain, spec)
        owner, theorem = promote(session, chain, library, built)
        print(f"  {CITED} promoted from {owner} into {chain[-1].name}, from its "
              f"cached term, carrying {len(theorem.side_conditions)} side "
              "condition(s)")
        print()
        # The control mutates the promotion, so it runs last.
        went_right = [verdict(built, case) for case in CASES]
        went_right.append(control(built, theorem))

    wrong = went_right.count(False)
    print()
    if wrong:
        print(f"{wrong} case(s) went the wrong way.")
        return 1
    print("The $d survives the boundary: capture refused, non-capture accepted, "
          "and the refusal is the proviso's doing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
