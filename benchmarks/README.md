# `benchmarks/` — what a parse costs

Proof checking is parsing. Every proof line is read by
`StringPattern.match`/`UnionPattern.match`, several times over — once per
candidate line type, once per production the sort offers, once per candidate
split of every subformula — so the matching layer is where a slow system is slow.
These are the measurements for it.

```bash
uv run python -m benchmarks.bench_matching                    # every scenario
uv run python -m benchmarks.bench_matching --only balanced    # by name or tag
uv run python -m benchmarks.bench_matching --save mine.json
uv run python -m benchmarks.bench_matching --compare mine.json
```

`--compare` re-runs everything and prints the ratio against a saved run. **That
is the only form of these numbers worth quoting.** Absolute microseconds are
wall-clock on whatever machine produced them; a ratio between two runs on the
same machine is a measurement. Take a baseline before you change anything.

| File | What's in it |
|---|---|
| `grammars.py` | The grammars and formulas the scenarios run against, built straight from the pattern classes so the numbers measure matching and not system assembly. |
| `bench_matching.py` | The scenarios, the runner, and the save/compare plumbing. |

## What the scenarios are for

Each one isolates a cost that behaves differently as something grows:

- **`nest-N` / `balanced-N`** — depth. A right-nest is the easy case (the first
  split tried is the right one); a balanced formula is the hard one, because the
  separator the template splits on occurs once per subformula. `balanced` is
  where anything quadratic in the formula's length announces itself.
- **`*-nomemo`** — the same, with `Context.parse_memo` off, which is what a
  caller that has not opted in gets.
- **`wide-N-*`** — grammar width, not formula size: 1,200 nullary constants
  beside two compounds. A cost that grows here grows with the *system*, which a
  user cannot do anything about.
- **`apply-N` / `adjacent-N`** — templates whose slots are separated by a
  character that also occurs inside the operands, and templates whose slots are
  not separated at all. Both maximise the number of candidate splits.
- **`sequent-N`** — a line type over formulas, so the split search runs over
  whole formulas rather than over atoms.
- **`sequent-context-N`** — the sequent grammar Track S actually declares
  (`tests/sequent_system.py`), whose antecedent is a **left-recursive list**:
  `context ::= ∅ | wff | context , wff`, so the sort re-enters itself at every
  comma and each one is a candidate split. The `-nomemo` pair is the point of
  the family — memoised the read is linear in the assumptions, and without it
  exponential, which is why `LineType.parse_line` installing a fresh memo per
  line is load-bearing rather than tidy.
- **`metavars-N`** — a rule schema's metavariables, consulted at every position
  the search considers a slot. Answers "does declaring more of them cost?"
- **`reject-*`** — failure. A rejection is generally dearer than an acceptance,
  because nothing short-circuits it, and an editor rejects far more often than
  it accepts.
- **`proof-mp-N`** — a whole proof checked end to end, as the check on whether
  any of the above reaches the path a user waits on.

A scenario declares a `budget`; one that exceeds it is reported as over budget
rather than left to hang, so a pathological case can be *stated* here.

## Correctness is not measured here

`tests/test_matching_stress.py` is the other half: it compares the search against
an exhaustive reference matcher over a few hundred generated near-miss strings,
and asserts the cost property this directory measures — that a nested formula
costs one parse per subformula — by *counting* parses, so it holds on a loaded
machine. A change that makes something here faster should leave that passing
untouched.
