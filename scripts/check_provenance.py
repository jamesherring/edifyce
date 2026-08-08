#!/usr/bin/env python
"""Where does each layer's mathematics actually come from?

    uv run python scripts/check_provenance.py set.mm --limit 2676

D6 of docs/system-relationships-roadmap.md (§5.5, §7.2). A layer plan files a
theorem by *subject matter* — the section header it sits under. This asks the
other question: following the citation graph transitively, which layer does a
theorem actually reach? A first-order theorem that touches nothing above
propositional calculus **is** a propositional theorem, and the count of those is
what says whether a boundary was drawn where the mathematics divides.

Two numbers per layer, because they answer different questions and a corpus where
they agree would hide it. **Only shallower** counts theorems every one of whose
citations is reachable from a shallower layer — nothing they cite needs this one.
**Rests on shallower axioms** counts theorems that assume nothing their own layer
adds, even where a lemma from it pins them in place. The first is the larger.

Neither is the count of theorems that could be **moved**, which is the last
column: a theorem is pinned by the notation it is stated in as well as by what it
cites, and `can move` is the conjunction.

On `set.mm` the two agree, which is itself the finding. `sptruw` is
`( A. x ph -> ph )` proved from `a1i` alone and looks like a theorem its notation
must hold in place — but the corpus declares `wal` in the syntax material that
falls in the propositional layer and only the quantifier *axioms* in the
first-order one, so `A.` is grammatical in PC and `sptruw` really can move. What
a layer declares is a fact about the file, not about what its symbols mean.

Three things are hard failures rather than measurements:

- a theorem depending on something its own chain cannot reach. A positional plan
  over a corpus in dependency order cannot produce one, and such a proof could
  not verify, so it means the rows disagree with the plan;
- a run whose spine is one system, or whose theorems all sit at depth zero —
  either makes every comparison here trivially true;
- a report that changes when the proof *source* is blanked, which would mean it
  is reading text rather than the graph.

A script rather than a test because `set.mm` is not in the repository;
`tests/test_provenance.py` pins the same properties on a fixture. Runs against
throwaway in-memory SQLite, so it needs no ``DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/check_provenance.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base  # noqa: E402
from app.db.metamath_store import import_corpus  # noqa: E402
from app.db.models import Proof  # noqa: E402
from app.db.provenance import by_layer, provenance  # noqa: E402
from website.logical.metamath import parse  # noqa: E402
from website.logical.metamath.setmm import LAYERS  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.db.provenance import Provenance

# How many examples of a layer's "could be filed lower" theorems to name by
# default. A count alone says a boundary is loose without saying where to look.
EXAMPLES = 5


def examples(reports: Sequence[Provenance], layer: str) -> list[str]:
    """The theorems of ``layer`` that cite nothing needing it, and why they stay.

    Naming the notation that pins one is the point of listing them at all: a
    reader deciding whether a boundary is in the right place needs to tell "this
    belongs lower" from "this reads lower and cannot go there".
    """
    return [
        # A theorem citing nothing at all could go anywhere, which is a different
        # thing from bottoming out in a named layer and reads wrong as "→ None".
        f"{report.proof} → {report.deepest_cited or 'cites nothing'}"
        + ("" if report.could_be_filed_lower else f" (held by {report.deepest_grammar})")
        for report in reports
        if report.filed_in == layer and report.depends_only_on_shallower
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to the .mm file")
    parser.add_argument(
        "--limit",
        type=int,
        default=2676,
        help=(
            "import only the first N theorems. The default 2676 is the milestone "
            "slice — the smallest at which all three of set.mm's layers hold one"
        ),
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=EXAMPLES,
        help="how many movable theorems to name per layer (default 5, 0 for all)",
    )
    arguments = parser.parse_args()
    shown = arguments.examples or None
    # `.mm` is UTF-8 (set.mm's comments and `$t` block are not ASCII).
    source = arguments.source.read_text(encoding="utf-8")

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        print(f"Importing {arguments.source} against a {len(LAYERS)}-layer plan…",
              flush=True)
        import_corpus(
            session, parse(source), limit=arguments.limit,
            name="Metamath", batch=200, plan=LAYERS,
        )
        reports = provenance(session)
        layers = by_layer(reports)

        if len(layers) < 2:
            raise SystemExit(
                "the import filed everything in one layer, so every depth here is "
                "zero and nothing is being compared — raise --limit past the "
                "plan's second section."
            )
        print()
        # `misfiled` is a column and not only a failure below, because the four
        # axiom buckets are exhaustive and a reader checking that they sum to
        # `proofs` needs to see all four (found in review).
        print(f"  {'layer':<26}{'proofs':>8}{'own axioms':>12}"
              f"{'shallower':>11}{'no axioms':>11}{'misfiled':>10}"
              f"{'cites lower':>13}{'can move':>10}")
        for layer in layers:
            print(f"  {layer.name:<26}{layer.proofs:>8}{layer.own_axioms:>12}"
                  f"{layer.lower_axioms:>11}{layer.no_axioms:>11}"
                  f"{layer.misfiled:>10}{layer.only_shallower:>13}"
                  f"{layer.could_be_lower:>10}")

        for layer in layers[1:]:
            movable = examples(reports, layer.name)
            if movable:
                print(f"\n  {layer.name}: {len(movable)} cite nothing that needs "
                      "this layer, e.g.")
                for example in movable[:shown]:
                    print(f"    {example}")

        # The report must be a graph query. Blanking the text a proof was read
        # from has to change nothing — the corpus-scale form of the same
        # assertion `tests/test_provenance.py` makes on a fixture.
        session.execute(update(Proof).values(source="", result=None))
        session.flush()
        textless = provenance(session)

    print()
    misfiled = [report for report in reports if report.misfiled]
    if misfiled:
        print(f"{len(misfiled)} theorem(s) cite what their own chain cannot reach:")
        for report in misfiled[:shown]:
            print(f"  ! {report.proof} (in {report.filed_in}) reaches "
                  f"{report.deepest_cited}")
        return 1
    if textless != reports:
        print("The report changed when proof source was blanked — it is reading "
              "text, not the graph.")
        return 1
    # A spine whose theorems all sit at the root is one the plan did not really
    # split, and then "nothing is misfiled" holds by having nowhere to be.
    if not any(report.filed > 0 for report in reports):
        raise SystemExit("every theorem was filed at the root; nothing was checked.")

    print("Nothing is filed above what it depends on, and the report reads only "
          "rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
