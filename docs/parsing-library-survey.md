# Should the matching layer use a parsing library?

Asked because `website/logical/matching` is hand-written and the largest single
cost in the engine. Answered by measurement rather than by reading feature lists;
every number below is reproducible from the scripts described in each section.

**Short answer: no, and the thing worth taking from the exercise is not a
library.** The candidates are slower than what is here, for reasons that are
structural rather than incidental. But the survey did locate the layer's real
scaling problem, and the fix for it needs no dependency.

## What the layer actually is

Worth stating precisely, because it is what disqualifies most candidates:

- The grammar is **defined at runtime** by the user, and **mutates**. A Metamath
  import adds one syntax production per `$a` as it walks the file, checking each
  theorem against only the notation that precedes it — reaching 1,441
  productions by the end.
- It is **ambiguous in general**. `p → q → r` has two parses in a grammar without
  grouping brackets, and nothing rejects such a grammar (see
  `docs/metamath-import-roadmap.md` and the ambiguity note below).
- A parse is not a tree of tokens but a `Match`: it records which slot each
  substring filled, marks metavariable leaves `is_variable`, and can be produced
  through a `DefinedNotation` unfold. `kernel.from_match` depends on all of it.

## Wholesale replacement: measured against `lark`

`lark` is the strongest candidate — it is the only mature Python toolkit that
builds a grammar from a string at runtime and offers a general (Earley) parser.

**It is slower on every input**, against an equivalent propositional grammar:

| input | chars | ours | lark Earley | lark LALR |
|---|---:|---:|---:|---:|
| `nest-8` | 49 | 80 µs | 1,105 µs (0.07x) | 113 µs (0.71x) |
| `nest-16` | 97 | 192 µs | 2,295 µs (0.08x) | 205 µs (0.94x) |
| `balanced-5` | 187 | 74 µs | 4,546 µs (0.02x) | 397 µs (0.19x) |
| `balanced-7` | 763 | 202 µs | 18,612 µs (0.01x) | 1,607 µs (0.13x) |

LALR is the closer column and **cannot be used**: it requires an unambiguous
grammar, which a user-defined system is not obliged to be. Earley is the mode
that matches this layer's contract, and it is 13–100x slower — the gap widening
with nesting, because the memo and the bracket prune here do work Earley's chart
does not.

**Grammar construction is the harder problem.** Building a lark grammar is not
free, and this layer's grammar changes:

| productions | lark Earley build |
|---:|---:|
| 10 | 24 ms |
| 100 | 42 ms |
| 400 | 143 ms |
| 1,400 | 505 ms |

The import mutates the grammar 1,441 times and parses between each mutation.
Rebuilding per addition is ~11 minutes of construction alone, against a current
whole-corpus import of 23 minutes total. Nothing in lark rebuilds incrementally.

Beyond speed, replacement would mean rebuilding `Match`, the definition-unfold
path, metavariable binding and side-condition plumbing on top of a third-party
tree — and moving the parser of a proof assistant's trusted input path into a
dependency. The performance case does not survive; the rest is not worth
relitigating without it.

`parsimonious` (PEG) was installed and not benchmarked: PEG's ordered choice
resolves ambiguity by fiat at the grammar level, which is the same silent
arbitrary-parse behaviour noted below, and it is consistently reported slower
than lark.

## The real finding: cost grows with the *grammar*, not the formula

Parsing one small formula, against a `set.mm`-shaped grammar (every compound
opens `( `, distinguished by a middle token) plus 1,200 nullary constants:

| same-opening compounds | `( K0 F0 K1 )` | nested |
|---:|---:|---:|
| 2 | 17 µs | 42 µs |
| 50 | 55 µs | 165 µs |
| 150 | 155 µs | 461 µs |
| 400 | 417 µs | 1,306 µs |

Linear in the number of productions sharing an opening. This is the same curve
the roadmap records from the whole-corpus run — 2.7 ms/theorem over the first
5,000, 28.8 ms/theorem by 45,000, as the grammar grows to 1,441 — and it is a
cost the user cannot do anything about, because it scales with *their system*
rather than with what they wrote.

The cause is `UnionPattern.leaf_candidates`: it narrows candidates by the
string's **first character**, and in this shape every compound opens `(`, so all
of them are tried.

## The fix, and whether a library supplies it

Index each production by a literal it *cannot match without* — for `( a F0 b )`
that is ` F0 ` — and ask which of those literals occur in the string. On the
1,000-compound grammar this narrows **1,000 candidate leaves to 1**:

| compounds | leaves tried now | with the index | end-to-end |
|---:|---:|---:|---:|
| 50 | 50 | 1 | 0.4x (slower) |
| 150 | 150 | 1 | 1.1x |
| 400 | 400 | 1 | 2.7x |
| 1,000 | 1,000 | 1 | **6.5x** |

Note the crossover: below ~150 productions the index costs more than it saves, so
an implementation has to be free for small grammars rather than merely cheap.

**`pyahocorasick` is the obvious tool and is not needed.** Finding which of many
literals occur in one pass is exactly what Aho-Corasick is for, but a plain dict
keyed by the literals' *tokens*, looked up against `s.split()`, gets the same
answer:

| | 12-char input | 240-char input |
|---|---:|---:|
| `pyahocorasick` | 0.36 µs | 4.36 µs |
| plain dict on `split()` | 0.47 µs | 7.13 µs |

Both return 1 leaf. The library is 1.3–1.6x faster and pulls further ahead on
long inputs, but it is a C extension on the build for a fraction of a
microsecond. It would earn its place only for a grammar whose literals do not
align with whitespace tokens, where `split()` cannot be the index key — worth
revisiting if such a system appears.

The other place it was measured, the opaque-token scan in `_opaque_positions`
(15 tokens, `set.mm`'s bracket-spelling constants), is 1.1–2.6x faster with
Aho-Corasick — on a path worth ~6% of a parse in the only systems that have it.
Not a dependency's worth.

## Recommendation

1. **Take no parsing library.** The measurements are decisive and the structural
   objections (runtime-mutating grammar, ambiguity, `Match` semantics, trust
   boundary) all point the same way.
2. **Build the required-literal index in-house**, as a plain dict. It is the one
   change that addresses cost growing with grammar size, worth 6.5x at `set.mm`
   scale, and it needs nothing new on the dependency list. It must no-op for
   small grammars.
3. **Revisit `pyahocorasick` only** if a grammar appears whose literals do not
   align with whitespace tokens.

## Not evaluated

- **Compiling the module** (`mypyc`, Cython). This is the remaining large lever —
  the hot loops are pure-Python character and index arithmetic, which is what
  those tools are best at — and it is orthogonal to the algorithm. It is also
  invasive: a build step, a wheel per platform, and a debugging story. Worth its
  own investigation, with the caveat that it buys a constant factor where the
  index above buys an asymptote.
- **`regex` module features.** Already a dependency, used by `RegexPattern`. The
  split search deliberately cannot be a regex — a slot is filled by *parsing* a
  substring at its declared sort, and several splits can place the same literal
  identically with only one of them parsing.

## Aside: ambiguity is unguarded

Surfaced while characterising what a replacement would have to preserve, and
recorded here because it is independent of the answer. A grammar with infix
productions and no grouping brackets is genuinely ambiguous — `p → q → r` has two
parses, `p → q → r → p` has five — and the engine returns whichever the search
reaches first, with no warning. There is no ambiguity detection anywhere in
`website/logical`. An exhaustive-parse enumerator (`tests/test_matching_stress.py`
carries one for a different purpose) would be the basis of a build-time check.
