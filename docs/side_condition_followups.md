# Side-condition follow-ups

Definition provisos are written with a `where` clause —
`Define <higher> as <lower> [fresh <binds>] [where <provisos>]` — and checked
structurally over kernel terms (see `website/logical/formal_system/definitions.py`).
`where`, like a rule's `side_conditions:` block, parses through the closed kernel
algebra in `website/logical/kernel/side_conditions.py`
(`occurs` / `equal` / `disjoint` / `atom` / `member`, with `not` on a predicate,
`or` between predicates within a clause, and an implicit `and` across clauses — a
rule's lines, or a `where`'s `;`-separated parts). There is no parenthesised
grouping, so the boolean structure is a flat conjunction-of-disjunctions.

The legacy pseudo-python `if <cond>` proviso on definitions has been **retired**:
`Define ... if ...` is now a compile error directing the author to `where`, and
the `matching.Definition` no longer carries a string `Condition` guard. (The
`Condition` / `get_by_path` interpreter still backs the unrelated pattern-function
DSL — `while` loops, `instances(...; condition)` filters, `SystemConditionPattern`
— which is a separate, larger retirement; see the last section.)

The extensions below were considered and **deliberately deferred**. They are
tracked here so the decisions aren't relitigated from scratch.

## 1. `Member` / `InSort` predicate

*Status: **implemented**.*

`member(x, R)` asserts the term bound to `x` belongs to sort `R` — the same sort
test the unifier applies (`_sort_admits`) *without* `atom`'s extra atomicity
guard, so a compound term of the sort qualifies. It is the tool to reach for when
a slot's declared binding is broader than a rule needs (e.g. a metavariable bound
to a union that the rule must pin to one member sort), where `atom(x, R)` would
wrongly reject any compound member. The sort argument is required (unlike `atom`,
where it is an optional extra guard). See `IsMember` in
`website/logical/kernel/side_conditions.py`.

Membership in an *object-level* set (e.g. `x ∈ S` over the proof's assumptions)
is a different thing — a proof obligation, not a structural guard (see below).

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

*Status: **implemented**.*

A predicate argument is now either a declared metavariable (resolved against the
match binding, as before) **or** a literal term expression built from the
grammar. An argument that is not a declared metavariable of the owner is parsed
against the grammar — its productions **and its definitions** (`sort.match` +
`from_match`, keeping the owner's metavariables schematic via `abstract`); at
check time the match binding is substituted into it (`Term.substitute`) to get the
ground term to compare. So a guard can mention a constant, a compound term, or
defined notation — `equal(p, ⊥)`, `not equal(x, ∅)`, `equal(p, ¬q)`,
`occurs(⊥, phi)` — where the argument may embed the rule's metavariables.

Provisos (rule `side_conditions:` and definition `where`) are parsed in the
compiler's finalisation pass, once the system's definitions have resolved, so
defined notation in an argument resolves like it does anywhere else. Comparison
stays structural: a defined symbol is an opaque constructor, so `equal(x, ∅)`
holds when `x` is the `∅` term itself, not merely something equal to its
definiens (no unfolding).

A term argument must be **ground after substitution**: every metavariable it
names must be one the match actually bound, or the condition fails loud (fails
closed) — a term naming an unbound metavariable can't be compared soundly.

Reasoning *up to* definitions (`equal` modulo unfolding) remains intentionally
excluded — that is semantic and belongs in the proof (cite the definition and
prove the equality as a step), mirroring the ordering decision above.

Disambiguation is by the declared-metavariable set (`context.string_variables`
for the engine, the owner's binding names for storage), so every existing proviso
is unchanged and the two layers agree. One consequence: an argument that *looks*
like a mistyped metavariable but isn't declared is treated as a term and validated
when the system compiles, rather than rejected at write time — consistent with
the rest of the draft-tolerant part API. In storage, `side_conditions` gains
`left_is_term` / `right_is_term` flags so a dropped binding that a stored
*metavariable* argument still names is still caught early, while term arguments
defer to compile.

## Not in scope: retiring `get_by_path`

Retiring the definition `if` proviso does **not** remove the pseudo-python value
interpreter (`website/logical/matching/paths.py` `get_by_path`) or
`matching/conditions.py`. Those still back the pattern-function DSL
(`while` loops, `instances(...; condition)` filters, `SystemConditionPattern`)
and the engine's value derivation (proof-line `formula()`/`label()`, definition
construction, custom pattern functions). Retiring that value interpreter is a
separate, larger project.
