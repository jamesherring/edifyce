# Side-condition follow-ups

Definition provisos are written with a `where` clause —
`Define <higher> as <lower> [fresh <binds>] [where <provisos>]` — and checked
structurally over kernel terms (see `website/logical/formal_system/definitions.py`).
`where`, like a rule's `side_conditions:` block, parses through the closed kernel
algebra in `website/logical/kernel/side_conditions.py`
(`occurs` / `equal` / `disjoint` / `atom`, with `not` and implicit conjunction).

The legacy pseudo-python `if <cond>` proviso on definitions has been **retired**:
`Define ... if ...` is now a compile error directing the author to `where`, and
the `matching.Definition` no longer carries a string `Condition` guard. (The
`Condition` / `get_by_path` interpreter still backs the unrelated pattern-function
DSL — `while` loops, `instances(...; condition)` filters, `SystemConditionPattern`
— which is a separate, larger retirement; see the last section.)

The extensions below were considered and **deliberately deferred**. They are
tracked here so the decisions aren't relitigated from scratch.

## 1. `Member` / `InSort` predicate

*Status: deferred (small, additive when wanted).*

Membership in a declared sort — e.g. a guard like `x is a member of R` where
`R` is a declared sort/`Pattern` — is not expressible today. `atom(x, R)`
(`IsAtom`) over-constrains: it additionally forces `x` to be a single leaf, so
it is wrong when `x` may bind a compound term.

A `member(x, R)` predicate would be `_sort_admits(R, bound(x), context)`
*without* the atomicity guard — roughly a 10-line class mirroring `IsAtom.check`,
plus a `_build` arm and a surface keyword. Only meaningful when `R` is a
declared syntactic sort; membership in an *object-level* set is a proof
obligation, not a structural guard (see below).

## 2. Ordering / numeric comparison

*Status: out of scope for the algebra — model as a proof obligation.*

Comparisons like `x >= 0` have no structural meaning in the kernel: `0` is an
opaque atom and `Equal` is purely syntactic (`Term.equal`), so an order relation
cannot be built by analogy. Adding one would require giving the trusted core a
decidable order — a significant soundness surface. Note that ordering was **not
expressible in the old pseudo-python language either**, so nothing was lost.

The architecturally consistent home for "you must have established `x >= 0`" is
a **cited premise / proof obligation**, not a side-condition on the rewrite.

## 3. Formula arguments in predicate positions

*Status: deferred (feasible, additive, structural-only).*

Today a predicate's arguments are **bound variable names** (looked up in the
match binding), not formula expressions. So a guard cannot mention a
defined-symbol formula in argument position (e.g. `equal(x, ∅)` where `∅` is
introduced by another definition) — `∅` is treated as an unbound name and fails.

A future extension could parse argument-position formulas (which may use defined
notation) into terms via `sort.match` + `from_match`, letting a guard *reference*
defined notation. This stays **structural**: defined symbols are compared as
opaque constructors, with no unfolding. Reasoning *up to* definitions
(`equal` modulo unfolding) remains intentionally excluded — that is semantic and
belongs in the proof (cite the definition and prove the equality as a step),
mirroring the ordering decision above.

## Not in scope: retiring `get_by_path`

Retiring the definition `if` proviso does **not** remove the pseudo-python value
interpreter (`website/logical/matching/paths.py` `get_by_path`) or
`matching/conditions.py`. Those still back the pattern-function DSL
(`while` loops, `instances(...; condition)` filters, `SystemConditionPattern`)
and the engine's value derivation (proof-line `formula()`/`label()`, definition
construction, custom pattern functions). Retiring that value interpreter is a
separate, larger project.
