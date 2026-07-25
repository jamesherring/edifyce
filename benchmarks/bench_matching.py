"""Benchmark the matching layer: what a parse costs, and where it goes.

Run it::

    uv run python -m benchmarks.bench_matching                 # all scenarios
    uv run python -m benchmarks.bench_matching --only nest     # a subset
    uv run python -m benchmarks.bench_matching --save base.json
    uv run python -m benchmarks.bench_matching --compare base.json

Each scenario is a single ``pattern.match(text, context)`` — the unit a proof
line is made of — timed as best-of-``--repeat`` so an unlucky GC pause does not
become the number. ``--compare`` re-runs everything and prints the ratio against
a saved run, which is the only form of these numbers worth quoting: they are
wall-clock on whatever machine ran them.

Scenarios that would not finish in reasonable time are declared with a ``budget``
instead of being left to hang: a scenario whose *first* parse exceeds it is
reported as over budget and abandoned, and the rest of the run continues. The
budget is checked between parses, never inside one, so it bounds a scenario at
roughly one parse rather than interrupting a pathological single match.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from website.logical.matching import Context

from benchmarks import grammars


@dataclass
class Scenario:
    """One timed parse: what to match, against what, how often."""

    name: str
    setup: Callable[[], tuple[object, str, Context]]
    iterations: int = 100

    # Wall-clock ceiling for a single parse, in seconds. Checked after the
    # warm-up and again between iterations - a scenario over it is abandoned and
    # reported rather than run `iterations` more times, so a pathological case
    # can be *stated* here and cost the benchmark one parse.
    budget: float = 5.0

    # Whether the parse runs with a fresh memo, as `LineType.parse_line` gives a
    # real proof line. Off for the scenarios that exist to show what the memo is
    # worth.
    memo: bool = True

    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ProofScenario:
    """One whole proof checked end to end, rather than one parse timed."""

    name: str
    depth: int
    iterations: int = 20
    budget: float = 5.0
    memo: bool = True
    tags: tuple[str, ...] = ("proof",)

    def setup(self):
        system = grammars.propositional_system()
        text = grammars.modus_ponens_proof(self.depth)

        # A parsed proof, wrapped so `run` can drive it like a pattern match. The
        # assertion is the point of the scenario as much as the timing: a proof
        # that stopped checking would otherwise just look fast.
        class Checked:
            @staticmethod
            def match(_text, _context):
                proof = system.parse(text)
                return proof if proof.valid else None

        return Checked, text, Context()


@dataclass
class Result:
    name: str
    seconds: float | None  # None when the scenario went over budget
    iterations: int


def _context(sort=None, metavariables: int = 0) -> Context:
    if metavariables:
        return grammars.metavariable_context(sort, metavariables)
    return Context()


# --- scenario definitions --------------------------------------------------


def _propositional_nest(depth: int, memo: bool = True) -> Scenario:
    def setup():
        formula = grammars.propositional()
        return formula, grammars.nest(depth), _context()

    return Scenario(
        name=f"nest-{depth}" + ("" if memo else "-nomemo"),
        setup=setup,
        iterations=20 if depth > 12 else 100,
        memo=memo,
        tags=("nest",),
    )


def _propositional_balanced(depth: int, memo: bool = True) -> Scenario:
    def setup():
        formula = grammars.propositional()
        return formula, grammars.balanced(depth), _context()

    return Scenario(
        name=f"balanced-{depth}" + ("" if memo else "-nomemo"),
        setup=setup,
        iterations=20 if depth > 4 else 100,
        memo=memo,
        tags=("balanced",),
    )


def _wide(constants: int, text: str, label: str) -> Scenario:
    def setup():
        expression = grammars.wide(constants)
        return expression, text, _context()

    return Scenario(name=f"wide-{constants}-{label}", setup=setup, tags=("wide",))


def _juxtaposition(depth: int) -> Scenario:
    def setup():
        term = grammars.juxtaposition()
        text = "x"
        for _ in range(depth):
            text = f"({text} y)"
        return term, text, _context()

    return Scenario(name=f"apply-{depth}", setup=setup, iterations=50, tags=("apply",))


def _adjacent(depth: int) -> Scenario:
    def setup():
        term = grammars.adjacent()
        text = "x"
        for _ in range(depth):
            text = f"[{text}y]"
        return term, text, _context()

    return Scenario(name=f"adjacent-{depth}", setup=setup, iterations=50, tags=("adjacent",))


def _sequent(depth: int) -> Scenario:
    def setup():
        line, _ = grammars.sequent()
        side = grammars.nest(depth)
        return line, f"{side} ⊢ {side}", _context()

    return Scenario(name=f"sequent-{depth}", setup=setup, iterations=50, tags=("sequent",))


def _metavariables(count: int) -> Scenario:
    def setup():
        formula = grammars.propositional()
        text = grammars.nest(6, atom="m0")
        return formula, text, _context(formula, metavariables=count)

    return Scenario(name=f"metavars-{count}", setup=setup, iterations=50, tags=("metavars",))


def _reject(name: str, text: str, iterations: int = 100) -> Scenario:
    def setup():
        formula = grammars.propositional()
        return formula, text, _context()

    return Scenario(name=f"reject-{name}", setup=setup, iterations=iterations, tags=("reject",))


SCENARIOS: list[Scenario] = [
    # Depth: the cost that ought to grow with the formula, not explode on it.
    _propositional_nest(4),
    _propositional_nest(8),
    _propositional_nest(12),
    _propositional_nest(16),
    _propositional_nest(24),
    # The same nest without the memo, to keep honest about what it buys.
    _propositional_nest(8, memo=False),
    _propositional_nest(12, memo=False),
    # Balanced: every subformula is read under several candidate splits of its
    # parent, so this is where re-reading shows up.
    _propositional_balanced(3),
    _propositional_balanced(4),
    _propositional_balanced(5),
    # Deep enough that anything quadratic in the formula's length shows it. A
    # depth-7 formula is 763 characters; a proof line can be that long.
    _propositional_balanced(6),
    _propositional_balanced(7),
    _propositional_balanced(4, memo=False),
    _propositional_balanced(5, memo=False),
    # Grammar width: a small formula against a vocabulary of 1,200.
    _wide(1200, "(a0 + b1)", "compound"),
    _wide(1200, "l999", "atom"),
    _wide(1200, "(a0 + (b1 x c2))", "nested"),
    # Adjacent slots: nothing separates the operands, so every position splits.
    _juxtaposition(4),
    _juxtaposition(6),
    _juxtaposition(8),
    # Slots with nothing between them: every boundary is a candidate.
    _adjacent(3),
    _adjacent(5),
    # A line whose one literal occurs many times in the string being read.
    _sequent(4),
    _sequent(8),
    # Metavariables in scope, consulted at every candidate variable position.
    _metavariables(4),
    _metavariables(32),
    _metavariables(128),
    # Failure: the union tries every leaf before giving up, so a rejection is
    # generally dearer than an acceptance.
    _reject("unbalanced", grammars.nest(8)[:-1]),
    _reject("bad-connective", grammars.nest(8).replace("→", "⊗", 1)),
    _reject("deep-truncated", grammars.nest(14)[:-1], iterations=20),
    # End to end: a whole proof checked, to confirm the numbers above reach the
    # path a user is actually waiting on.
    ProofScenario(name="proof-mp-2", depth=2),
    ProofScenario(name="proof-mp-4", depth=4),
    ProofScenario(name="proof-mp-5", depth=5),
]


# --- running ---------------------------------------------------------------


def run(scenario: Scenario) -> Result:
    pattern, text, context = scenario.setup()

    # One warm-up, outside the timing: the first parse fills the union's
    # flattening and leaf-index memos, which are a build-time cost, not a
    # per-parse one, and would otherwise be charged entirely to iteration one.
    # Timed all the same, so a scenario that blows its budget costs one parse
    # rather than `iterations` of them.
    context.parse_memo = {} if scenario.memo else None

    started = time.perf_counter()
    warmed = pattern.match(text, context)
    warm_up = time.perf_counter() - started

    if warmed is None and not scenario.name.startswith("reject-"):
        raise AssertionError(f"scenario {scenario.name} does not parse its own input")

    if warm_up > scenario.budget:
        return Result(scenario.name, None, 0)

    best = None
    deadline = time.perf_counter() + scenario.budget
    for _ in range(scenario.iterations):
        context.parse_memo = {} if scenario.memo else None

        started = time.perf_counter()
        pattern.match(text, context)
        elapsed = time.perf_counter() - started

        if best is None or elapsed < best:
            best = elapsed

        if time.perf_counter() > deadline:
            if best > scenario.budget:
                return Result(scenario.name, None, scenario.iterations)
            break

    return Result(scenario.name, best, scenario.iterations)


def _format(seconds: float | None) -> str:
    if seconds is None:
        return "over budget"
    if seconds < 1e-3:
        return f"{seconds * 1e6:8.1f} µs"
    if seconds < 1:
        return f"{seconds * 1e3:8.2f} ms"
    return f"{seconds:8.3f} s "


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=[],
                        help="run scenarios whose name or tag contains this (repeatable)")
    parser.add_argument("--save", help="write the timings to this JSON file")
    parser.add_argument("--compare", help="print each timing as a ratio against this JSON file")
    parser.add_argument("--budget", type=float, help="override every scenario's budget, in seconds")
    args = parser.parse_args(argv)

    selected = SCENARIOS
    if args.only:
        selected = [
            scenario for scenario in SCENARIOS
            if any(needle in scenario.name or needle in scenario.tags for needle in args.only)
        ]

    baseline = {}
    if args.compare:
        with open(args.compare) as handle:
            baseline = json.load(handle)

    if not selected:
        print(f"no scenario matches {args.only}", file=sys.stderr)
        return 1

    width = max(len(scenario.name) for scenario in selected)
    results = {}

    for scenario in selected:
        if args.budget is not None:
            scenario.budget = args.budget

        result = run(scenario)
        results[result.name] = result.seconds

        line = f"{result.name:<{width}}  {_format(result.seconds)}"

        was = baseline.get(result.name)
        if was is not None and result.seconds:
            ratio = was / result.seconds
            line += f"   was {_format(was)}   {ratio:6.2f}x"
        elif was is not None and result.seconds is None:
            line += f"   was {_format(was)}   REGRESSED"
        elif args.compare and result.seconds is not None:
            line += "   (new)"

        print(line, flush=True)

    if args.save:
        with open(args.save, "w") as handle:
            json.dump(results, handle, indent=2, sort_keys=True)
        print(f"\nwrote {args.save}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
