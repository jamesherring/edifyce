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

### Design north star — revised by the PR 3 finding

The plan above assumed the interpreter still ran a rich author-facing DSL that a
typed expression layer would have to *replay*, and framed a fork over whether to
keep or redesign that DSL's surface syntax. **The PR 3 investigation showed the
fork is moot: there is no live DSL to replay.** Instrumenting `parse_path` (the
chokepoint every `get_by_path` variant hits before any operation dispatch) across
the full suite — propositional, FOL/ZFC, MIU string-rewriting, definitional steps
— found **636 of 640 calls were `Match.get_by_path("f")`/`("r")`**: projecting a
line type's `formula_field`/`reference_field` off a match, a bare `sub_matches`
lookup. The other four were synthetic unit-test strings. **Zero** DSL operations
(`instances`, `has_parent`, `replace`, `Condition`, `SystemConditionPattern`, …)
fired in real checking. The ~830-line interpreter had decayed to a single live
function: project a named sub-field off a match.

So the north star is **deletion, not a typed re-implementation**. Everything real
is already checked by the modern typed stack, and generality for the target
systems is carried by three typed pillars that stay:

- **Grammar / productions** express any notation — board syntax, chess FEN, go
  positions.
- **Structural unification** matches state and binds metavariables.
- **The closed side-condition algebra** expresses move legality / provisos.

The string DSL never contributed to that generality — it was untyped, unsound,
non-total (`while` loops) debt. New expressive needs for games/code are met by a
**typed extension driven by a worked example**, not by preserving the interpreter:
encode tic-tac-toe on today's engine and see what genuinely cannot be said. The
one credible gap is that the algebra is a flat conjunction-of-disjunctions (CNF),
while a win predicate ("three in a row") is naturally DNF — so the likely concrete
output is a small, typed extension to the algebra (nested boolean structure, or a
`line`/`count` predicate), designed with the algebra's existing discipline. That
spike is separate from, and unblocked by, the deletion.

### The PRs

Characterization (the old "PR 0") is **not** a PR — it is the local survey
already folded into this document. The shippable work:

1. **Value accessors — *done*, and they turned out to be dead, not live.** The
   plan assumed `result.get_by_path("label()"/"path()"/"display()"/"axiom()", …)`
   in `formal_system/system.py` and `lower()/higher()/for()/path()` in
   `proof.py` were live string-dispatch to convert into typed method calls. They
   are not: `formula()`/`reference()` had already become declared LineType fields,
   and the accessor-*function* definition syntax (`pattern.foo(): return …`) was
   removed from the compiler, so **nothing can define these accessors** — every
   call raises and is swallowed by its `try/except`. Instrumenting all seven
   sites across the full suite confirmed **not one ever resolves**. So this step
   was a *deletion* of dead, fail-silent plumbing, not a rewrite:
   - `label()`/`display()`/`axiom()` in `FormalSystem.parse` removed — their
     effects already come from live code (`ProofLine` defaults `display` to the
     stripped text and `label` to `None`; `behaviour: axiom` sets `is_axiom`).
     `label`/`display` per-line *overrides* are a real capability that is now
     dormant; the intent is to **reintroduce them as declared LineType fields**
     (like `formula`/`reference`), not via the interpreter — tracked for a later
     PR.
   - `get_references` (dead, no callers) removed, and the `behaviour: definition`
     / `behaviour: import` branches in `ProofLine.execute` now **fail closed** —
     a proof line with one of these behaviours is rejected as unsupported rather
     than silently accepted (their `lower/higher/for/path` derivation was the
     dead accessor; passing the line as a valid no-op would let unsupported
     syntax through, against the "fail loudly" rule). To be lifted **when the
     references/definitions feature is reimplemented with a typed mechanism**
     (see `docs/proof-references-and-definitions-plan.md`); `Proof.import_path` —
     the tested method — stays for that rewire.

   Net: seven engine → interpreter call sites gone, all behaviour-preserving
   (suite unchanged at 629 passed). Interpreter stays in place for the DSL.
2. **`edit_context` — *done*, and removed rather than typed.** The plan was to
   convert the `sub_key`/`sub_value` derivations in `ProofLine.edit_context` into
   a typed getattr mechanism. But the `context:` line-type block that feeds it is
   a legacy feature: it is exercised by **no** test, has **no** representation in
   the declarative authoring model (`SystemSpec`), and its job (accumulating
   assumptions/fresh variables) is done by the `scope:`/`Subproof` mechanism and
   the kernel side-condition algebra. Instrumenting the `edit_context` loop across
   the full suite confirmed it **never fires**. Its `sub_key`/`sub_value` strings
   are also author-facing DSL, so genuinely typing them would be the PR 4 work,
   not a mechanical step. So, per the same reasoning as step 1, this was a
   *removal*: `ProofLine.edit_context`, the compiler's `context:`/`context.X:`
   line-type key parsing (a `context:` block is now an unrecognised line-type
   parameter), and the `LineType.add_context` field are all gone, along with the
   two `get_by_path` call sites inside them. Behaviour-preserving (the feature
   was inert); the `AGENTS.md` `getattr` guidance that cited `edit_context` as its
   example was reworded. *After this, no engine-internal caller uses the
   interpreter; only `Condition` and the author-facing DSL remain.*
3. **Retire the interpreter — *done*, as a deletion (see the revised north star).**
   The instrumentation reduced the whole apparatus to one live use, so PRs 4–6 of
   the old plan (design a typed AST, build a typed expression layer, differentially
   port `Condition`) collapsed into a straight deletion:
   - Added `Match.field(name)` — the direct `sub_matches` lookup the interpreter
     always resolved to for a `formula_field`/`reference_field` — and rerouted the
     one live caller (`FormalSystem._line_field`) to it.
   - Deleted `matching/paths.py` (`get_by_path`, `parse_path`, `parse_arguments`,
     `constant`, `path_maps_to`) and `matching/conditions.py` (`Condition`) as
     whole modules; the per-class `get_by_path` overrides on `Match`/`MatchSet`/
     `ProofLine`/`Definition`; the DSL-only `Match` methods (`check_condition`,
     `contains`, `instances`, `has_parent`, `equal_any`, `is_descendant_of`) and
     `MatchSet.each`; `SystemConditionPattern` and its `_system_condition_`
     default; and the `matching/__init__.py` re-exports of all the above.
   - Trimmed the vestiges the interpreter left in kept code: `Match.replace`'s
     dead `condition` parameter, the compiler's dead `type(current_object) is
     Condition` branch, and the unsupported `mapsto` reference-mapping (now fails
     loud instead of resolving a pattern through the interpreter).
   - Methods the definitional-step / kernel path calls directly — `Match.replace`,
     `equivalent`, `equivalent_under_definitions`, `maps_to_up_to_definition`,
     `MatchSet.contains`/`union`/… — were **kept**; only the string-dispatch layer
     over them went. Behaviour-preserving: the 590 remaining tests pass; the ~33
     removed were unit tests of the deleted DSL itself.

   *After this, the `get_by_path` interpreter no longer exists.* Proof checking
   runs entirely on kernel term unification, the closed side-condition algebra,
   and the scope/subproof mechanism.

**Deferred (typed, driven by a worked example — not the string DSL):**

- **Generality spike for games/code.** Encode tic-tac-toe on the current typed
  engine; if a win/legality predicate can't be expressed, add a small typed
  extension to the side-condition algebra (see the revised north star). Chess/go
  then stress it incrementally.
- **`label`/`display` per-line overrides** (from PR 1) and the
  **references/definitions feature** (`behaviour: definition`/`import`, from
  PR 1) — both to return as typed declarations when needed, never via a revived
  interpreter.

Sequencing logic: steps 1–2 removed the interpreter's dead engine-internal
callers (value rendering, definition/import accessors, context editing); step 3
then rerouted the single surviving use to a typed accessor and deleted the
apparatus outright — the empirical finding that no live DSL remained is what
collapsed the original "design a typed layer" PRs 4–6 into that deletion. The
interpreter is now gone. `uv run pytest` stayed green at every step (each removal
behaviour-preserving), and each step shipped independently without leaving the
tree half-migrated. What remains is forward work — the generality spike and the
typed reintroductions above — not further retirement.
