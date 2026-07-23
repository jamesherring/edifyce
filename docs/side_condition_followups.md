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

## Not in scope *for the algebra work*: retiring `get_by_path`

Retiring the definition `if` proviso does **not** remove the pseudo-python value
interpreter (`website/logical/matching/paths.py` `get_by_path`) or
`matching/conditions.py`. Those still back the pattern-function DSL
(`instances(...; condition)` filters, `SystemConditionPattern`) and the engine's
value derivation (proof-line `formula()`/`label()`, definition construction,
custom pattern functions). Retiring that value interpreter is a separate, larger
project — planned below.

## Roadmap: fully retiring `get_by_path`

This section plans the deletion of the string interpreter as its own body of
work. It supersedes the "separate, larger project" note above.

### What the interpreter actually is (characterization)

Before planning, we inventoried every consumer (`get_by_path` callers plus the
per-class `get_by_path` overrides on `Match`/`MatchSet`, `ProofLine`,
`Definition`, `Condition`). The important finding, contrary to how it reads at
first glance: **this is not open-ended user Python.** It is a *closed, finite
vocabulary* of engine operations, composed via strings and re-parsed at eval
time. The whole surface is three things:

1. **Navigation** — dotted paths, `[...]` indexing, `self`, sub-match access.
2. **A fixed set of ~30 engine operations** invoked by string name, e.g.
   `instances(P; cond)` / `shallow_instances`, `has_parent`, `contains`,
   `replace`, `equivalent_under_definitions`,
   `equivalent_with_some_replacements`, `is_descendant_of`, `variables()`,
   `maps_to` / `apply_mapping`, `equal_any`, plus value accessors
   (`formula()`, `label()`, `text()`, `pattern()`, `previous_formulae()`,
   `conditions()`, `follows_from_definition(...)`, `check_condition(...)`) and a
   few literal/host forms (`None`, numeric/string constants, ` + `, `set(...)`,
   `len(...)`, `Condition(...)`, `match(...)`).
3. **The boolean `Condition` layer** (`and`/`or`/`not`/`in`/`is`/`equals`) over
   (1) and (2), plus its structural `maps_to`/`path_maps_to` mapping.

Method-name dispatch (`getattr(obj, name)(*args)`) exists but every name it
resolves is one of the operations above — nothing reaches arbitrary internals in
practice. **Because the vocabulary is finite and enumerable, a typed replacement
is tractable**: it is a re-representation, not the invention of a new language.

The soundness-critical caller (rule/definition provisos) is already gone, moved
to the closed kernel algebra. What remains is functional plumbing —
value rendering and match-tree computation — none of it in the trusted core.

### Two enabling facts

- **The production database is empty.** There are no stored formal systems to
  migrate, so we have authority to make radical changes — up to and including
  the *source syntax* of derivations — without a compatibility shim. `get_by_path`
  never has to stay string-compatible with persisted data.
- **Generality is the hard constraint, not compatibility.** Edifyce must keep
  expressing a wide span of systems: propositional and first-order logic, common
  mathematical/logical calculi, toy string-rewriting systems (Hofstadter's MIU
  and pq), and systems encoding code or games (tic-tac-toe, chess, go). The
  match-tree operations in (2) above — filtering instances by a condition,
  testing descendant/parent structure, structural replacement — are precisely
  how a game or code system expresses its moves and legal-state checks. **The
  replacement must preserve that expressive power**; those systems are the
  stress test that the new mechanism is checked against, not something to be
  narrowed away. Removing the *awkward string layer* must not remove the
  *generality it currently delivers*.

### Design north star

Replace the re-parsed string interpreter with a **typed, closed, total
expression layer**, parsed **once at compile time** into typed dataclass nodes
with an exhaustive evaluator — mirroring what `kernel/side_conditions.py` did for
provisos. Same operation vocabulary, but analyzable, IDE-navigable, fail-loud
(no `try/except: pass` swallowing typos), and total (no re-parse per evaluation).
The pivotal design fork, which the empty DB leaves open:

- **Keep the surface syntax** authors already write (`instances(P; cond)` inside
  `formula()`/`label()`/condition blocks) and only replace the *internal*
  evaluator — lower risk, smaller author-facing change; **or**
- **Redesign the surface syntax** too, now that no stored systems constrain it —
  more work, but a chance to remove the string-embedded-in-string awkwardness at
  the source level.

Decide this fork against the generality checklist above (encode a nontrivial
slice of one game system in each candidate syntax before committing).

### The PRs

Characterization (the old "PR 0") is **not** a PR — it is the local survey
already folded into this document. The shippable work:

1. **Typed value accessors (engine-authored fixed strings).** Replace
   `result.get_by_path("label()"/"formula()"/"path()"/"display()"/"axiom()", …)`
   in `formal_system/system.py` and `proof.py`, and the `lower()/higher()/for()`
   sites, with direct typed method calls. These strings are engine-authored, not
   user-authored — pure mechanical de-stringing, biggest safety win first. Split
   2–3 PRs if the diff is large. Interpreter stays in place for the DSL.
2. **Typed `edit_context` + definition construction.** The `sub_key`/`sub_value`
   derivations (`proof.py` ~1285–1330) and definition-side accessors. Slightly
   more involved (`edit_context` has genuinely dynamic keys — the one legitimate
   `getattr` case per `CLAUDE.md`). *After this, no engine-internal caller uses
   the interpreter; only `Condition` and the author-facing DSL remain.*
3. **Design spike + decision.** Land the surface-syntax fork decision and a typed
   AST sketch (node per operation, exhaustive evaluator, how `instances` /
   `has_parent` / `replace` / `SystemConditionPattern` map onto it) as a short
   design note. Validate it by hand-encoding a slice of a game system per the
   generality checklist. Cheap to write, expensive to get wrong.
4. **Typed expression layer, compiled once.** Introduce the typed AST + total
   evaluator; translate pattern-function bodies and `instances(...; condition)`
   filters into it. Run old and new in parallel and differential-test against the
   full system corpus before flipping the default.
5. **Reimplement `Condition` on the typed layer.** Rebuild `check_condition` and
   `maps_to`/`path_maps_to` on typed nodes (or fold into PR 4). Retire the string
   `Condition` and `SystemConditionPattern`'s string probe.
6. **Delete.** Remove `get_by_path`, `constant`, `parse_arguments`, `parse_path`,
   `path_maps_to` from `paths.py`; drop every per-class `get_by_path` override;
   remove the re-exports from `matching/__init__.py` (respecting that file's
   deliberate flat-API contract until this final step); update this doc and the
   `kernel/side_conditions.py` reference.

Sequencing logic: engine-authored fixed strings (1–2) first — mechanical and
low-risk, and they clear the interpreter out of value rendering. The
author-facing DSL (3–5) last, because it is the only part needing a real
replacement *language* and its scope depends on the generality checklist.
Deletion (6) only once nothing calls the interpreter; `uv run pytest` stays green
at every step, and each PR ships independently without leaving the tree
half-migrated.
