#!/usr/bin/env python
"""Assert that importing a corpus **as a spine** changes nothing about the import.

    uv run python scripts/check_layering.py set.mm --limit 2676

D4/D5's headline invariant (docs/system-relationships-roadmap.md §7.2, §8). A
layer plan says how a corpus is *filed*; it must say nothing about how it is
*checked*. So the same file imported twice — once flat, once as a spine of
systems — has to agree on:

- the theorem count and the per-theorem verdicts;
- the **byte-identical** proof sources, which is the whole of §7.2's "preserving
  references": a citation is stored as a bare label and resolves through the
  spine, so splitting the corpus must not rewrite a single one of them;
- the promoted library, label for label;
- the derived rows a reader depends on — folders and descriptions move between
  systems, but a partition may not create or lose one.

A strict equality, not a summary comparison: two runs whose counts match while
their *contents* differ is exactly the failure this exists to catch.

**Why a script and not a test.** `set.mm` is not in the repository, and the claim
is about `set.mm` — `tests/test_metamath_layered_store.py` pins the same equality
on a three-layer fixture, which proves the mechanism and not the corpus. This is
the corpus half, run by hand at a milestone and recorded in the roadmap, the same
way D1's measurement was.

Runs against throwaway in-memory SQLite, so it needs no ``DATABASE_URL`` and
leaves nothing behind.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/check_layering.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base  # noqa: E402
from app.db.descriptions import LabelDescriptionRow  # noqa: E402
from app.db.metamath_store import import_corpus  # noqa: E402
from app.db.models import FormalSystem, Proof, ProofFolder  # noqa: E402
from app.db.proof_lines import ProofLineRow  # noqa: E402
from app.db.promoted_theorems import PromotedTheoremRow  # noqa: E402
from app.db.promoted_theorems_mapping import cited_labels  # noqa: E402
from website.logical.metamath import parse  # noqa: E402
from website.logical.metamath.corpus import corpus_layers, theorems  # noqa: E402
from website.logical.metamath.setmm import LAYERS  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from website.logical.metamath.sections import Layer


@dataclass(frozen=True)
class Run:
    """What one import produced, in the form the two runs are compared in.

    Everything here is keyed by something the *file* names — a label — rather
    than by a row id or a system id, because those are the two things a layered
    run is expected to differ in. A comparison keyed on either would fail on
    every run and prove nothing.
    """

    checked: int
    verified: int
    rejected: int
    failed: int
    lines: int
    formulas: int
    described: int
    sections: int
    notation: int
    # The library counters. Compared separately from the labels below because a
    # *failure* to promote is the thing a label set catches only by absence: the
    # first corpus run of this script found 354 promotions refused under a spine,
    # and `theorems_failed` says so directly.
    theorems: int
    primitives: int
    theorems_failed: int
    # label -> (source, valid). The byte-identical half of the invariant.
    proofs: dict[str, tuple[str, bool]]
    # Every promoted label, and whether it is a primitive of its system.
    library: dict[str, bool]
    # Section titles, as a multiset would be: a partition may move a folder
    # between systems but must not drop or duplicate one.
    folders: list[str]
    # Every documented label.
    described_labels: set[str]
    # The spine this run actually produced: (layer name, proofs filed there),
    # root first. **Not** what the plan asked for — a plan whose section titles
    # the file does not open, or a `--limit` short of the second boundary, gives
    # one system, and then the comparison below is between two identical runs and
    # confirms nothing (found in review).
    spine: list[tuple[str, int]]
    # Where each proof was actually filed: label -> the *name* of the system it
    # was stored against. Names rather than ids, because an id is different in
    # every run by construction and so can be compared with nothing.
    owners: dict[str, str]
    # Citations a stored proof makes that its own chain cannot reach. Empty on
    # any run worth trusting; see `unreachable_citations` for what it catches
    # and why a positional plan cannot produce one.
    unreachable: tuple[Unreachable, ...] = ()
    seconds: float = 0.0


@dataclass(frozen=True)
class Unreachable:
    """A citation whose theorem exists, filed where the citing proof cannot see it.

    The precise shape of a misfiled plan. `set.mm`'s order guarantees a cited
    label is declared before the proof citing it, and every boundary is a
    position in the file, so a *positional* partition cannot produce one — which
    is why this is exercised by injecting a bad partition rather than by writing
    a bad plan (relationships roadmap, §8's D5).

    Sound because it asks only about labels the run **did** promote. A citation
    resolving to no promoted row at all is a different thing and not an error:
    it may name a rule, a definition, or one of the theorem's own `$e`
    hypotheses, which `read_library` reaches through `hypotheses_of` rather than
    through the chain. On `set.mm` 2,539 citations are of that kind. A citation
    that genuinely resolves to nothing already fails the *import* — `walk`
    refuses it with "proof cites unknown label" and stores no proof.
    """

    proof: str
    filed_in: str
    label: str
    declared_in: str


@dataclass
class Difference:
    """One way the two runs disagreed, with enough detail to act on."""

    what: str
    detail: str


@dataclass
class Comparison:
    differences: list[Difference] = field(default_factory=list)

    def require(self, what: str, flat: object, spined: object) -> None:
        if flat != spined:
            self.differences.append(
                Difference(what=what, detail=f"flat={flat!r} spined={spined!r}")
            )

    def require_keys(
        self, what: str, flat: set[str], spined: set[str]
    ) -> None:
        missing = sorted(flat - spined)[:5]
        extra = sorted(spined - flat)[:5]
        if missing or extra:
            self.differences.append(
                Difference(
                    what=what,
                    detail=(
                        f"{len(flat - spined)} only flat (e.g. {missing}), "
                        f"{len(spined - flat)} only spined (e.g. {extra})"
                    ),
                )
            )


def run_import(source: str, limit: int | None, plan: Sequence[Layer]) -> Run:
    """Import ``source`` once and read back what it stored.

    Parsed per run rather than shared: a `Database` is handed to the walk, which
    builds and grows a system from it, and two runs must not be able to influence
    each other through anything it holds.
    """
    started = time.monotonic()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            report = import_corpus(
                session,
                parse(source),
                limit=limit,
                name="Metamath",
                batch=200,
                plan=plan,
            )
            named = {
                system.id: system.name
                for system in session.scalars(select(FormalSystem))
            }
            proofs = {
                proof.name: (proof.source, bool(proof.valid))
                for proof in session.scalars(select(Proof))
            }
            owners = {
                proof.name: named[proof.formal_system_id]
                for proof in session.scalars(select(Proof))
            }
            library = {
                row.label: bool(row.primitive)
                for row in session.scalars(select(PromotedTheoremRow))
            }
            folders = sorted(
                folder.name for folder in session.scalars(select(ProofFolder))
            )
            described = {
                row.label for row in session.scalars(select(LabelDescriptionRow))
            }
            unreachable = unreachable_citations(session)
    finally:
        engine.dispose()

    return Run(
        checked=report.checked,
        verified=report.verified,
        rejected=report.rejected,
        failed=report.failed,
        lines=report.lines,
        formulas=report.formulas,
        described=report.described,
        sections=report.sections,
        notation=report.notation,
        theorems=report.theorems,
        primitives=report.primitives,
        theorems_failed=report.theorems_failed,
        proofs=proofs,
        library=library,
        folders=folders,
        described_labels=described,
        spine=[(layer.name, layer.proofs) for layer in report.layers],
        owners=owners,
        unreachable=unreachable,
        seconds=time.monotonic() - started,
    )


def unreachable_citations(session: Session) -> tuple[Unreachable, ...]:
    """Every citation a stored proof makes that its own chain cannot reach.

    The invariant that makes a spine mean anything: a proof is filed against one
    layer, and §5.2 says its citations resolve against that layer's library and
    then its *ancestors'* — never a sibling's and never a descendant's. A proof
    filed where it cannot see what it cites is stored as verified and is not
    re-verifiable, which is a lie in the database rather than a failure of the
    run, and so is exactly the kind of thing nothing notices.

    Asked only of labels this run promoted; see :class:`Unreachable` for why the
    rest are not this function's business.
    """
    names = {system.id: system.name for system in session.scalars(select(FormalSystem))}
    parent = {
        system.id: system.inherits_from_id
        for system in session.scalars(select(FormalSystem))
    }

    def visible(system_id: uuid.UUID) -> set[uuid.UUID]:
        seen = set()
        while system_id is not None and system_id not in seen:
            seen.add(system_id)
            system_id = parent[system_id]
        return seen

    declared = {
        row.label: row.system_id
        for row in session.scalars(select(PromotedTheoremRow))
    }
    references: dict[uuid.UUID, list[str | None]] = {}
    for line in session.scalars(select(ProofLineRow)):
        references.setdefault(line.proof_id, []).append(line.reference)

    found: list[Unreachable] = []
    for proof in session.scalars(select(Proof)):
        reachable = visible(proof.formal_system_id)
        for label in cited_labels(references.get(proof.id, ())):
            home = declared.get(label)
            if home is not None and home not in reachable:
                found.append(
                    Unreachable(
                        proof=proof.name,
                        filed_in=names[proof.formal_system_id],
                        label=label,
                        declared_in=names[home],
                    )
                )
    return tuple(found)


def expected_owners(source: str, limit: int | None) -> dict[str, str]:
    """Which layer each walked theorem *should* be filed in, derived here.

    The point is that it is derived **here**, from the file and the plan, rather
    than read back from the run: `corpus_layers` is the declared boundary list,
    and this does its own assignment against it rather than trusting
    `metamath_store`'s routing. So a regression anywhere between the boundaries
    and the stored row — `_layer_of_label`, `_Routed`, `index_of`, the checkpoint
    rebind — shows up as a disagreement.

    **From review**, and the gap it closes is a real one: requiring only that
    *some* two layers carry proofs passes a run that filed every ZF theorem
    under first-order logic, since two non-empty shares summing correctly is all
    that check ever asked for. The partition has to be compared element by
    element or it is not being compared at all.
    """
    database = parse(source)
    opens = corpus_layers(database, limit, plan=LAYERS)
    names = [name for name, _at in opens]
    starts = [at for _name, at in opens]
    return {
        theorem.label: names[
            max(bisect_right(starts, database.position(theorem.label)) - 1, 0)
        ]
        for theorem in theorems(database, limit)
    }


def compare(flat: Run, spined: Run, expected: Mapping[str, str]) -> Comparison:
    """Every way the two runs must agree, checked one at a time.

    All of them, rather than stopping at the first: a run is minutes long, and
    knowing that the sources match while the library does not is a different
    diagnosis from knowing only that something differs.

    ``expected`` is :func:`expected_owners` — where each theorem *should* have
    been filed, derived from the file rather than read back from the run. It is
    required rather than defaulted, because skipping it is precisely the failure
    this function exists to avoid.
    """
    result = Comparison()
    # **Before anything else**: can this run demonstrate anything at all? A plan
    # whose section titles this file does not open, or a `--limit` short of the
    # second boundary, gives one layer — and then every equality below holds
    # because the two runs are the same run, and a green result would mean
    # nothing (found in review). Asked of the *expected* partition, not the
    # realised one, so a run that wrongly collapsed is a failure below rather
    # than an excuse here.
    if len(set(expected.values())) < 2:
        result.differences.append(
            Difference(
                what="nothing here is a comparison",
                detail=(
                    f"the plan covers these theorems with {sorted(set(expected.values()))} "
                    "— one layer, so the two runs are the same run. Raise --limit "
                    "until a second layer opens, or check that the plan's section "
                    "titles match this file"
                ),
            )
        )
    # **The partition itself**, element by element. Requiring only that some two
    # layers be non-empty passes a run that filed every ZF theorem under
    # first-order logic — two non-empty shares summing correctly is all such a
    # check ever asks (found in review). Every other comparison below is blind to
    # which system a row landed in, so this is the only thing that sees it.
    misfiled = sorted(
        label
        for label, layer in expected.items()
        if label in spined.owners and spined.owners[label] != layer
    )
    if misfiled:
        example = misfiled[0]
        result.differences.append(
            Difference(
                what="proofs filed in the wrong layer",
                detail=(
                    f"{len(misfiled)} of {len(expected)}, e.g. {example}: "
                    f"expected {expected[example]!r}, filed under "
                    f"{spined.owners[example]!r}"
                ),
            )
        )
    # And the report's own breakdown has to describe the run it came from.
    if sum(proofs for _name, proofs in spined.spine) != len(spined.proofs):
        result.differences.append(
            Difference(
                what="per-layer proof counts",
                detail=(
                    f"{sum(p for _n, p in spined.spine)} across layers against "
                    f"{len(spined.proofs)} stored"
                ),
            )
        )
    # A flat run files everything in one system by construction; if it ever did
    # not, every "same either way" result below would be comparing the wrong
    # thing.
    if len(set(flat.owners.values())) > 1:
        result.differences.append(
            Difference(
                what="the flat run is not flat",
                detail=f"{sorted(set(flat.owners.values()))}",
            )
        )

    # **Every citation must be reachable from where its proof was filed.** Not a
    # comparison between the runs — a fact about the spined one alone, and the
    # invariant that makes a spine mean anything (§5.2). A proof filed where it
    # cannot see what it cites is stored as verified and is not re-verifiable.
    for stranded in spined.unreachable[:5]:
        result.differences.append(
            Difference(
                what="a citation the citing proof's chain cannot reach",
                detail=(
                    f"{stranded.proof} (in {stranded.filed_in!r}) cites "
                    f"{stranded.label!r}, declared in {stranded.declared_in!r}"
                ),
            )
        )
    if len(spined.unreachable) > 5:
        result.differences.append(
            Difference(
                what="unreachable citations",
                detail=f"{len(spined.unreachable)} in all; first five above",
            )
        )
    # And the flat run has one system, so nothing there can be out of reach —
    # if it ever were, the comparison below would be against a broken baseline.
    result.require("unreachable in the flat run", (), flat.unreachable)

    result.require("checked", flat.checked, spined.checked)
    result.require("verified", flat.verified, spined.verified)
    result.require("rejected", flat.rejected, spined.rejected)
    result.require("failed", flat.failed, spined.failed)
    result.require("lines", flat.lines, spined.lines)
    result.require("formulas", flat.formulas, spined.formulas)
    result.require("described", flat.described, spined.described)
    result.require("sections", flat.sections, spined.sections)
    result.require("notation", flat.notation, spined.notation)
    result.require("theorems", flat.theorems, spined.theorems)
    result.require("primitives", flat.primitives, spined.primitives)
    result.require("theorems failed", flat.theorems_failed, spined.theorems_failed)

    result.require_keys("proofs stored", set(flat.proofs), set(spined.proofs))
    # The headline. Named separately from the label set, because a proof present
    # in both runs under a *different source* is the failure that matters and the
    # one a count cannot show.
    differing = sorted(
        label
        for label in set(flat.proofs) & set(spined.proofs)
        if flat.proofs[label] != spined.proofs[label]
    )
    if differing:
        example = differing[0]
        result.differences.append(
            Difference(
                what="proof sources or verdicts",
                detail=(
                    f"{len(differing)} differ, e.g. {example}: "
                    f"flat={flat.proofs[example]!r} spined={spined.proofs[example]!r}"
                ),
            )
        )

    result.require_keys("library labels", set(flat.library), set(spined.library))
    primitives = sorted(
        label
        for label in set(flat.library) & set(spined.library)
        if flat.library[label] != spined.library[label]
    )
    if primitives:
        result.differences.append(
            Difference(
                what="primitive flags",
                detail=f"{len(primitives)} differ, e.g. {primitives[0]}",
            )
        )

    result.require("folder titles", flat.folders, spined.folders)
    result.require_keys(
        "described labels", flat.described_labels, spined.described_labels
    )
    return result


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "compare only the first N theorems. 2676 is the milestone slice — "
            "the smallest at which all three of set.mm's layers are populated"
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    # `.mm` is UTF-8 (set.mm's comments and `$t` block are not ASCII).
    source = arguments.source.read_text(encoding="utf-8")

    print(f"Importing {arguments.source} flat…", flush=True)
    flat = run_import(source, arguments.limit, ())
    print(f"  {flat.checked} checked in {flat.seconds:.1f}s", flush=True)

    # The plan's length, not the spine's — this is what is being *attempted*.
    # What it actually opened is printed below, from the run.
    print(f"Importing {arguments.source} against a {len(LAYERS)}-layer plan…", flush=True)
    spined = run_import(source, arguments.limit, LAYERS)
    print(f"  {spined.checked} checked in {spined.seconds:.1f}s", flush=True)
    for name, proofs in spined.spine:
        print(f"    {name}: {proofs} proofs")

    result = compare(flat, spined, expected_owners(source, arguments.limit))
    print()
    print(f"  checked   {flat.checked}")
    print(f"  verified  {flat.verified}")
    print(f"  rejected  {flat.rejected}")
    print(f"  failed    {flat.failed}")
    print(f"  proofs    {len(flat.proofs)}")
    print(f"  library   {len(flat.library)} ({flat.primitives} primitive, "
          f"{flat.theorems_failed} refused)")
    print(f"  folders   {len(flat.folders)}")
    print(f"  described {len(flat.described_labels)}")
    print()
    if not result.differences:
        print("Layering changed nothing. Same verdicts, byte-identical sources.")
        return 0
    print(f"{len(result.differences)} difference(s):")
    for difference in result.differences:
        print(f"  ! {difference.what}: {difference.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
