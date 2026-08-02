# Design: verification from rows, not from text

**Status:** P1–P6 and P2a shipped · **Prerequisite work:** merged (the term
graph, `proof_lines`, the kernel-takes-terms change #121, and the Metamath
corpus import #124)

> **The claim.** Verifying a proof should require no parsing once the proof and
> its dependencies are stored. A proof line should be parsed **exactly once** —
> when it is written, whether by a user through the API or by a corpus import —
> and every check thereafter should run on the stored graph. Parsing and
> verification are separate problems, and today they are fused.

The surprise, on tracing it, is how little of the engine this asks to change.
The kernel already works this way. What re-parses is the layer that hands work
*to* the kernel, because it throws the parse away and re-derives it from
`proofs.source` on every verify.

---

## 1. Verification is already parse-free

`InferenceRule.check`'s structural path never touches the string matcher:

```python
# website/logical/formal_system/rules.py
# Structural check over terms (the graph representation): the deduction and
# every logical antecedent must match their schemas under one shared binding,
# derived by unification. The formulae are already parsed, so we project them
# straight to terms and never re-run the string matcher.
binding = self._term_binding(antecedents, deduction, context)
```

Everything downstream of that is kernel data:

| Step | Runs on |
|---|---|
| Rule application | `_term_binding` → `kernel.unify.match_all` over `schema_term` and `ProofLine.formula_term` |
| Provisos | `_side_conditions_hold(binding, …)` → `kernel.side_conditions` |
| Discharge | `check_discharge` over `formula_term`, `Subproof.eigenvariable_is_fresh` |
| Definitional steps | `kernel.definitions`, which since #121 is built from terms and reads no strings |

AGENTS.md now states the invariant outright: *"The kernel also reads no strings
… nothing in the trusted core re-parses at check time."*

So "verify the proof steps via the kernel, no parsing and no pattern-class
usage" is **already true inside a process**. Parsing happens strictly upstream,
producing `ProofLine.formula_term`. This proposal is about moving that boundary
to the *write* path and persisting what it produces — not about changing what
checking does.

## 2. What is stored, and what is thrown away

This table is what the phases below work through; **used** is the state after
P1–P6.

| Verification needs | Stored | Used |
|---|---|---|
| A line's formula as a term | yes — `proof_lines.term_id` → `terms` | **yes** (P2) |
| Line type and behaviour | yes — `proof_lines.line_type` / `behaviour` | **yes** (P2) |
| The citation a line was written with | yes — `proof_lines.reference` | **yes** (P2) |
| Whether a cited lemma stands | yes — its lines' verdicts | **yes** (P1) |
| Justification edges | yes — `proof_line_antecedents` | no — *re-derived* from the citation, deliberately |
| Scope tree (for discharge) | yes — `proof_lines.opens_scope` / `scope_id` | no — *re-derived*, deliberately |
| Rule schema terms | yes — `rules.deduction_term_id` etc. → `terms` | **yes** (P3), when `rules.schema_digest` still matches |
| Definition higher/lower forms | yes — `definitions.higher_term_id` / `lower_term_id` → `terms` | **yes** (P6), when `definitions.term_digest` still matches |
| A line's flat string (string-rewriting) | no — *derived* | **yes** (P5), rendered from the term rather than stored |
| Promoted theorems | yes — `promoted_theorems` → `terms` | **yes** (P4), resolved by label per citation |

The two *deliberate* nos are the point rather than an omission. Edges and scope
are stored so the graph is queryable, and re-derived so a check is a check: if a
row could supply a line's justification, a corrupted row could assert one.
Everything a verdict rests on is recomputed; the rows supply only what each line
*states*.

**The proof side is closed.** Everything a proof contributes is in rows and read
back on every check.

**The system side is closed too.** Rule schemas are stored as composed terms and
read back (P3); the citable library is stored and resolved by label (P4), so an
imported Metamath proof re-checks from its own rows; and a definition's two forms
are stored as the terms they parse to (P6), so the kernel definition an unfold is
checked against no longer derives from text on the read path.

A rebuild still reads the two form strings, but for *grammar* rather than
structure: whether the defining form parses at all given the definitions before
it, whether the definition is circular, and the notation template that makes the
defined form grammatical. Each is the parser answering a question about the
grammar, and none produces a term the checker uses — which is the line this
document has drawn throughout.

## 3. The contract this inverts

`app/db/proof_lines.py` is explicit today:

> The snapshot is derived, never authoritative: it is dropped whenever the
> proof's verdict is invalidated and rewritten on the next verify, so it can
> never disagree with `source`.

This proposal makes the stored terms the **authoritative parse**, and `source`
the surface echo of it. That is the same promotion `app/db/systems.py` already
made for grammars — *rows are canonical, the engine is rebuilt on demand* — so
there is precedent in the codebase for the move. But it changes what an edit
means, and the invalidation boundary becomes soundness-critical rather than
merely tidy:

- **Writing `source` is the parse boundary.** An edit re-parses and rewrites the
  rows; there is no other moment at which text becomes structure.
- **A system edit must invalidate every term in it.** A stored term names its
  constructors by *name*, so a production that changes shape silently changes
  what a stored term means. `proofs_mapping.discard_system_checks` already does
  this on every part route, and a published system is frozen — but it stops
  being a cache-freshness nicety and becomes the thing that keeps a stored
  parse honest.
- **A verdict then rests on stored data.** Reading rows to decide validity means
  a corrupted or stale row is a soundness problem, where today it is a stale
  render. Worth deciding whether rows carry a schema/engine version stamp; the
  digest covers structure and names, not the kernel semantics that read them.
- **Invalidation must serialise against verification.** It did not: the lock was
  taken by `_record_verdict` immediately before writing and by the
  reference-graph edit, while a source edit, a delete and a system-part edit took
  nothing — so a verify could read a lemma's rows, a concurrent `PATCH` could
  invalidate them and commit, and the verify would write a valid snapshot back
  over that invalidation. The lost update predates P1 (the same interleaving
  overwrote `proofs.valid` when lemmas were re-parsed), but its *consequence* did
  not: a stale verdict used to be corrected by the next verify that re-checked
  the lemma, and is now trusted instead. **Closed** — see §3.1.

Recording the decision matters more than the mechanism: it should be taken
deliberately, once, rather than arrived at by a series of caching optimisations.

**Decided, and P1 acts on it.** Stored terms are the authoritative parse. Two
consequences were taken with it: there is **no fallback to parsing** a lemma
whose rows are missing — a compatibility path for data written before the rows
existed is legacy debt, and the database it would serve is empty — and the
invalidation paths above are now soundness-critical, so they are tested rather
than trusted. The engine-version stamp remains open; the digest covers structure
and names, not the kernel semantics that read them.

### 3.1 Serialising edits against verification

`_common.lock_system` — a transaction-scoped Postgres advisory lock keyed by the
system — is now taken at the **start** of a verify, before it reads anything, and
by every path that invalidates: a source edit, a reference edit, a delete, and a
system-part edit. The read and the write are one critical section, so an
invalidation can no longer land between them.

Two choices worth recording:

- **The invalidation helpers take the lock themselves** (`_discard_check`,
  `_invalidate_dependents`), rather than each call site taking it. Forgetting it
  at one new call site is exactly how the guarantee would be lost, and it would
  fail nothing else.
- **One key, always acquired first.** A proof may only reference proofs in its
  own system, so a single system key covers a whole reference closure and there
  is no lock ordering to get wrong.

The cost is real and worth stating: **all verification in a system now serialises
behind any edit to it.** That is the right trade at present scale — a verify is
seconds at worst and edits are interactive — but it is a global lock, and a
busier deployment would want the finer-grained alternative (a version column on
`proofs`, bumped by every invalidation and checked at write time, which closes
the race without excluding concurrent verifies).

Testing it needed two halves, because the lock is a no-op on SQLite. Each route
is covered by asserting it *takes* the lock (`test_every_invalidation_path_takes_
the_system_lock`, one case per path); that the lock then excludes anything is a
Postgres-only test which fails if the acquire is removed.

## 4. The exception that turned out not to be one

String-rewriting systems (semi-Thue: MIU and friends, `matching == "string"`)
cannot be term-*only* by construction. `InferenceRule._string_pairs` matches
schemas against `ProofLine.formula_string` by associative matching — the
splitting and concatenation the term unifier deliberately cannot express.

This section used to pose a choice: persist `formula_string` beside the term, or
carve the regime out and let it re-parse. **Neither was needed.** A term renders
back to its own surface string, so the flat form is *derived* rather than stored
a second time or re-parsed — and the regime checks from rows like any other.

That is exact, not approximate, and the reason is worth stating because it is the
whole basis for trusting it: `Term.to_string` walks its constructor's template
pieces and a ground leaf returns its own literal, so a render can differ from the
source only if a template *literal* matched text it does not equal. The matcher
admits no such spelling — every whitespace variant of a template simply fails to
parse. `test_a_rendered_formula_string_is_the_one_the_parse_recorded` asserts it
over every shape the round trip composes proofs from, rather than leaving it as
an argument.

So there is no carve-out and no second copy to keep in step, which is a better
answer than either option originally on offer. What there *was* is described in
P5: the derivation was conditional on a question that could not be answered where
it was asked.

---

## 5. Phases

Each is independently shippable and states how we would know it worked.

### P1. Trust a stored lemma verdict — *done*

`_verify_with_references` compiled the whole transitive reference closure and
re-checked every lemma, only to ask `_is_usable_lemma` a question the database
already answered. Lemmas are now **loaded** from their stored lines
(`proofs_mapping.load_proof_lines`) and never re-parsed; the root proof is still
parsed, which is P2's job. `test_verifying_parses_the_proof_and_none_of_its_lemmas`
pins it: exactly one parse, whatever the closure.

Three things this settled, none of which the plan above had right.

**A lemma must have been verified.** The closure used to check each lemma on the
way past, so a proof could be "proved" by a lemma nobody had ever checked. Now a
lemma with no stored lines is simply not seeded, and the response says which one
and why. This is a **visible behaviour change**: verify the lemma first. It is
also the honest reading of "a proof may rest only on a lemma that stands", and it
is what makes the guarantee a guarantee rather than a cache.

**Usability comes off the lines, not off `proofs.valid`.**
`FormalSystem.check_proof` defines proof validity as *every line valid* and
`has_warnings` as *any line carrying a warning*. Both are per-line and both
columns are stored, so deriving them from the rows being returned is equivalent
by construction and cannot disagree with the structure it ships with. No
`proofs.valid` read is involved.

**Batching is not an optimisation, it is the whole point.** Reading a proof back
is latency, not work: a couple of round trips and almost no CPU. Done one lemma
at a time it *loses to re-parsing* — measured at 7.2 ms per proof against 0.6 ms
to parse it, on a small grammar. Batching the closure into two queries brings it
to 1.15 ms per proof and flat in the number of lemmas.
`test_the_reference_closure_is_read_in_a_fixed_number_of_queries` pins the query
count so it cannot quietly go back to per-lemma.

Two traps worth recording, because both were silent:

- **The identity map holds weak references.** A prefetch that loads the term
  subgraph and returns nothing is collected immediately, and every lookup it was
  meant to serve goes back to the database. The fix at the time was that
  `prefetch_terms` returns its rows and the caller must hold them — a rule, which
  P3 and P4 each went on to break. P2a made it moot: the sweep returns flat data
  rather than ORM instances, so there is nothing to collect.
- **A query does not populate an instance already in the identity map.** Loading
  the line rows puts the root terms in the map with `children` unloaded, and a
  later `selectinload` of those same rows is a no-op without
  `populate_existing`. The sweep looked correct and did nothing.

**It is not yet faster, and that should be said plainly.** Measured against dev
Postgres over a 6,600-theorem set.mm import (221 productions), 40 cited proofs:

| | per proof |
|---|---|
| re-parse + re-check | **2.0 ms** |
| load from rows (3 queries total) | **2.6 – 4.5 ms** |

So P1 currently costs about 1.3–2× what it replaces. Two things say the
direction is still right. Loading is flat in grammar size — it is term nodes and
two queries — while parsing is not: the same corpus walk costs 2.7 ms/theorem
over the first 5,000 and 28.8 ms/theorem by 45,000 as the grammar reaches 1,441
productions (Metamath roadmap §1.1). And the remaining cost is ORM row
hydration, not the term rebuild, so reading `terms`/`term_children` as Core rows
is an available lever that has not been pulled.

But the honest justification for P1 today is **correctness, not speed**: a proof
may now rest only on a lemma that has actually been checked. The speed argument
belongs to P2–P4, where the root proof, the rule schemas and the promoted
theorems stop being re-parsed too.

**What P1 rests on.** A stored verdict is only as good as the invalidation that
clears it — `_discard_check` on a source edit, `_invalidate_dependents`
transitively on a lemma's edit or deletion, `discard_system_checks` on a system
part edit. Those existed to keep a *cache* honest and now keep a *verdict*
honest, so they are covered by tests rather than assumed
(`test_a_lemma_whose_structure_was_discarded_is_no_longer_citable`).

### P2. Rebuild a proof from its rows instead of parsing it — *done*

`FormalSystem.parse` splits in two, which is the thesis of this document made
literal:

- **`read_line`** takes a line's content off the grammar — the matched line type,
  the formula as a kernel term, its flat string, the citation string. Exactly
  four things, and every one of them is a column on `proof_lines`.
- **`check_proof`** numbers each line, places it in its subproof and justifies
  it, then reads the verdict off the lines. It needs no text.

So `proofs_mapping.load_proof_for_check` populates the lines from rows and hands
them to `check_proof`. A proof checked once never has its text parsed again; the
route falls back to parsing exactly when there are no rows, which is exactly when
there is nothing to trust — never checked, or invalidated.

**The verdict is not read back.** Numbering, scope and justification are all
re-derived, so a stored row supplies what a line *says* and never whether it
stands. That is what keeps this a check rather than a cache read, and it is why
`test_a_proof_checked_from_rows_still_fails_when_it_should` is not redundant.

One ordering property is load-bearing and easy to lose. `check_proof` keeps
number/scope/execute interleaved **per line**, as parsing did. A discharge cites
its subproof by the opener's line number and is validated structurally; what
stops it reaching a subproof *below* it is that later lines are not yet numbered
or scoped when it runs. Doing the three as separate passes would quietly admit a
forward discharge.

**Still not faster.** Measured against dev Postgres over a 6,600-theorem set.mm
import (221 productions), 20 proofs per bucket:

| proof size | parse + check | rows + check |
|---|---|---|
| ~4 lines | **1.2 ms** | 21.0 ms |
| ~10 lines | **4.5 ms** | 24.0 ms |
| ~32 lines | **18.9 ms** | 59.2 ms |

Reading a proof back is three round trips whatever it contains, and that floor
dominates everything at this scale. But the curves converge fast: over an
eight-fold increase in lines the parse grows sixteen-fold and the row path under
threefold, and the parse also grows with the *grammar* (2.7 ms/theorem early in
the set.mm walk against 49 ms by 45,000) where the row path does not. The
crossover is a bigger proof and a bigger library, both of which the Metamath work
produces.

As with P1, the case for P2 today is that it makes the rows load-bearing — the
parse happens once, at the write — not that it is quicker yet.

**One correctness lesson worth keeping, and it cost two bugs to learn.** Both
were a proof coming back *valid* on the second verify that had been invalid on
the first, and both had the same cause: a verdict the parse path reached by
noticing something was **missing**, which the row path then could not reach
because a row records the absence and not the reason for it.

- A line matching **no line type** stored no line type, so nothing executed and
  the line kept `ProofLine`'s optimistic default.
- A line whose type matched but whose formula would not **project** stored its
  type and a null term. An axiom line asserts its formula by fiat and a scope
  opener is granted by fiat, so neither consults the formula and both accepted a
  line stating nothing.

Both are now decided in `check_proof`, structurally — no line type, or a declared
formula field with no term, means the line cannot stand — so they hold for a line
rebuilt from a row exactly as for one just parsed. `read_line` reports what it
found and judges nothing.

The generalisation is the thing to keep: **a check from rows is sound only if
every verdict is re-derived, and the ones that hide are those settled by an
absence.** A test that only exercises proofs which fail *loudly* will not find
them, which is why the agreement test runs over shapes rather than cases.

### P2a. The constant factor — *done*

Profiled before touching anything, and the profile moved the target. This
section predicted the cost was in *reading a proof back*; by P4 it was not. On a
set.mm re-check, **76% of a check was the library resolution** P4 added, not the
proof-line load — three separate term sweeps and 15.5 queries for one proof.

**Done: one query and one term sweep for everything a proof may cite.**
`load_theorems` and `load_hypotheses` were two functions doing the same shape of
work on the same table, back to back, each paying its own recursive closure over
`term_children` and its own row fetch. They are one function with a
`hypotheses_of` argument. And the many-to-one loads *under* a collection (a
binding's symbol, a proviso's sort) are `joinedload` rather than `selectinload`,
so each is a row on a query already being issued rather than a round trip.

**Done: term rows come back as data, not as ORM instances.** `prefetch_terms`
hydrated a `TermRow` object graph and `load_term` walked its relationships, for
data that is immutable, never written back and read exactly once — none of the
identity map, the instrumented attributes or the unit of work earns its keep
there. It now issues one Core query and returns a `TermGraph`: flat rows in a
plain dict, rebuilt into kernel terms on demand and memoised across every root
it was asked for. `load_term` is gone; the graph is the only way to read a
stored term.

That also **removes a hazard rather than documenting it**. The ORM version
handed back instances the caller had to keep a reference to, because a session's
identity map holds weak references — a row nothing referred to was collected,
and the lookup meant to hit memory went back to the database, silently slower or
a greenlet error outside the session. That caught this codebase three times (P1,
P3, P4), each time fixed by a comment telling the next caller to hold on to
something. Flat rows in a dict cannot be collected out from under a caller, so
the rule no longer exists to be broken.

The last third of it was not hydration at all: **the closure query was being
built per call**, and a recursive CTE has to set up its column collection before
`edges.c.child_id` can name one. The statement is now a module-level constant
with its roots as an expanding bind parameter, so SQLAlchemy compiles it once.

**And the sweep is one query rather than two**, which arrived by way of a review
finding. The second query had asked for the closure's edges by naming every
parent in an `IN` list — one bind parameter per reachable node, where the
`selectinload` it replaced had chunked at 500. A 5,000-theorem set.mm slice
already sweeps to 8,190 nodes, so the whole corpus would clear both Postgres's
65,535 parameter cap and SQLite's 32,766. The fix was not to chunk but to notice
that **the recursive CTE already computes every edge of the closure** — it simply
was not carrying `slot` and `position`. With those two columns added, the nodes
left-join their own edges and the whole sweep is one statement whose only
parameter is the roots the caller asked for.

| | per re-checked proof |
|---|---|
| before | 12.96 ms, 15.5 queries |
| after the merge | 9.4 ms, 9.0 queries |
| after Core rows | 7.85 ms, 9.0 queries |
| after the cached statement | 5.52 ms, 9.0 queries |
| after folding the sweep into one query | **5.49 ms, 7.0 queries** |

−58% and −55% in all. Worth being precise about which change bought what: of the
query count, the merge is most of it and the fold is the rest; the `joinedload`
change is one, in because a many-to-one under a collection should not be a round
trip, not because it showed up. Of the time, the first three changes are roughly
a third each and the fold is free — it removes a round trip and adds a repeated
node column per edge, and those cancel. `prefetch_terms` no longer appears in the
profile's top twenty-six; what is left is dominated by the ORM load of the
theorem rows themselves.

**Done: one term sweep instead of two.** A check prefetched twice — once for the
proof's own line terms, once for the library's — and the enabler for merging them
was always there: a line's citation is `proof_lines.reference`, a plain column,
so *what a proof cites is settled before any term is loaded*. The order is now
read line rows → read theorem rows → one sweep over both sets of roots → build
and check.

What made it worth doing deliberately was the interface. `before_check` was one
callback run after the lines were built, which is too late to contribute roots to
their sweep, so it splits: `resolve_citations` is handed the stored citations and
returns a `PendingCitations` — the term roots it wants, and what to do once they
are loaded. On the library side that is `read_library` (rows and digests, no
terms) and `PendingLibrary.promote(built, context, graph)` (terms, no database),
with `load_theorems` still composing the two for the caller that has no sweep to
share: the **parse** path, whose lines already carry their terms because they
were just parsed.

| | per re-checked proof |
|---|---|
| two sweeps | 8.05 ms, 7.0 queries |
| one sweep | **7.08 ms, 6.0 queries** |

−12%, against dev Postgres, paired. The query is the certain part; the time is
not, and the gap between databases is the point. On SQLite in-memory the same
comparison is ~5%, because a saved round trip costs nothing when the database is
in-process. This is P1's "reading a proof back is **latency, not work**" showing
up as a measurement — so loopback Postgres is itself a floor for a deployed one.

`test_a_re_check_sweeps_the_term_graph_once` counts the closure queries, because
nothing about the *result* changes if this regresses: the same terms arrive
either way, just in two round trips instead of one, which no assertion on a
verdict could see.

**Done: theorem rows come back as data too.** The same argument as for term
rows, applied to the four tables a library entry spans. `load_theorems` selected
`PromotedTheoremRow` with three `selectinload`s under it, and those three were
1.15 s of a 3.17 s profiled re-check — **36% of the whole check** for an object
graph that is read once, never written back and never consulted twice.

It now reads `StoredTheorem`: flat dataclasses over four Core queries. The
queries are the same four `selectinload` issued — a theorem has three
*independent* child collections, so one joined statement would be their cartesian
product, which is why `selectinload` splits them in the first place. What goes is
the machinery on top.

Two things fell out of doing it:

- **Rendering a proviso now reads a name, not a relationship.** The renderer took
  a `SideConditionRow` and reached `row.sort_symbol.name`, which a flat read has
  no instance to offer. It is written against a `ProvisoNode` protocol with a
  `sort_name` instead, satisfied by the ORM row (a property) and by the flat row
  (a column the join already resolved). The rule and definition readers are
  unchanged.
- **The four statements are built once**, as the term sweep's is, with everything
  varying bound. That needed one wrinkle: whether a caller wants a proof's
  *owning* theorem varies per call, so branching on it would mean two statements
  — the owner is a bind parameter and `NULL` is "no owner", since `id = NULL` is
  never true. Roughly half the gain came from each of the two.

| | per re-checked proof |
|---|---|
| ORM rows | 9.33 ms, 7.0 queries |
| flat rows | **5.40 ms, 7.0 queries** |

**−42%.** Measured paired — the two builds alternated three times in one run,
median reported — which is the only way these numbers mean anything: the same
comparison read 5.44 ms against 4.22 ms (−22%) on an unloaded host an hour
earlier. Both halves are real; the *ratio* is not stable across machine states,
because the ORM path is far more CPU-bound and so degrades faster under
contention than the flat path it replaces. Take −22% as the floor.

**One thing tried and rejected on measurement.** The three child queries take the
ids the first query found, which is the shape the term sweep had to abandon
above — so it was worth checking. It is not the same situation: a sweep's closure
is unboundedly larger than its roots (269 nodes from a proof's six), whereas
these ids are at most one per label asked for, and *that* `IN` list is already in
the first query. If the ids overflow, the labels overflowed first. Re-asking
instead — the children repeating the label predicate as a subquery — costs 19%
paired, because three more label lookups are dearer than the ids they save. So
the ids stay, and the reasoning is in `_statements` rather than left for the next
reader to re-derive.

**One case is pinned that is not a correctness bug.** Asking for no labels, or
for no owner, must render *false* rather than true — and if either widened,
nothing would be incorrect, because the caller filters by what it asked for
either way. It would show up only as every verify scanning the whole library.
`test_a_degenerate_ask_reads_no_library_at_all` is there because a silent
whole-library scan is exactly what this phase exists to prevent.

**What is left, and why the phase stops here.** A re-check is now roughly a third
term sweep, a third library read and a third engine work (`promote_spec`
composing what the caches miss), with no single hot spot — which is the shape a
constant-factor phase should end in. The remaining lever is the one it never
had: **a single-proof load cannot amortise its floor.** Verifying one proof is
one proof, six round trips is close to the number of distinct questions being
asked, and the levers worth pulling from here are ones that change *what* is
asked rather than how it is fetched.

### P3. Store schema terms — *done*

A rule's deduction, antecedents and subproof lines are template **strings**
parsed at every system build: `_build_rule` calls `build_schema_pattern` per
slot, and that composes `pattern.schema_term` by parsing the template against the
productions (`compose_schema_term`). A verify compiles the system, so this was
per-verify work, and it scaled with the grammar exactly as a proof's parse does.

It now reads the term a previous build composed
(`app/db/schema_terms.py`), and writes back anything it had to compose itself.
This is the **last parse on the check path** other than promotion, which is P4.

**The fork, settled: a map beside the spec, not fields on it.** `build_spec`
takes an optional `schema_terms` source; `SystemSpec` is untouched, and its
dataclass `==` — which the storage round-trip test rests on — is unchanged. What
the design sketch got wrong is that the map cannot hold `Term`s: a stored term
names its constructors, and those only exist part-way through the build. So the
source is a **callable**, asked per slot with the live build context, and it is
keyed positionally (`SchemaSlot(rule index, slot, ordinal)`) rather than by row
id, because a `SystemSpec` carries no ids and adding them would be the thing
option (2) exists to avoid. Positions are exact here: `system_to_spec` emits
`spec.rules` in row order and `build_system` consumes it in that order.

**Invalidation was the real work, and the answer was not to do any.** The sketch
proposed rewriting every schema term on every part edit, and called completeness
the risk. Instead each rule row carries `schema_digest` — a fingerprint of the
grammar plus that rule's own templates and bindings
(`declarative.schema_digests`) — and a row whose digest no longer matches is
simply **not read**. No cascade, no sweep, no ordering guarantee, and a stale row
is inert rather than believed.

That inverts the risk relative to P1 and P2, and deliberately. There the row *is*
the record, so a stale one is believed by default and only correct invalidation
saves it. Here the template sits beside the term and composing it again is what
the build did before any of this — so a missed cache costs time and only a
wrongly-*hit* one could cost correctness. The digest is what makes hits
conservative, so `tests/test_schema_terms.py` tests its **reach**: for each edit
to the grammar or to a rule, whatever term moved, its digest must have moved too.

Two details the digest gets right by being computed on the right thing:

- It covers the **derived** bracket map and opaque-token set, not the declared
  `spec.brackets`. Undeclaring `()` on a system that writes parens changes
  nothing — the build falls back to them — and digesting the declaration would
  have thrown away every term for no reason.
- It covers which grammar names the *rest* of the build namespace shadows —
  the collisions only, not every name a line, part or axiom binds. See below.
- It omits a rule's **label**, which affects nothing composition reads. A pure
  rename therefore keeps the terms, which is right.

**The namespace has two readers, and only one of them is composition.** The
first cut left lines, line parts and axioms out of the digest, on the argument
that a template spelled like one of them resolves to that declared pattern and
composes nothing — so no stored term is served for it. True, and beside the
point. Those names share `ctx.variables` with the grammar and are registered
after it, so an axiom named `implication` leaves that name bound to its line
type. Composing is indifferent: it parses against the sort *unions*, which hold
the production objects. But a stored term names its constructors by **name** and
resolves them back through that same namespace (`terms_mapping.TermGraph`), and
finds the line type. Cold build fine, warm build dead — from an edit that changes
no composed term at all, which is why the digest-reach test could not see it and
a warm-equals-cold test now does.

`_shadowed_grammar_names` covers exactly the collisions, not every outside name:
a line renamed to something no production is called shadows nothing, and
invalidating for it would be cost with no defect behind it. Both directions are
pinned by tests.

Worth noting that **P2 has the same hazard and is saved by something else**: a
stored proof-line term resolves its constructors through the same shadowed
namespace, but `discard_system_checks` drops every proof in the system on any
part edit, so the rows never survive the rename. P3 deliberately has no such
blanket invalidation — that is the whole point of the digest — so it has to carry
this itself.

**One trap, and it was P1's trap again — now gone at the root.** `prefetch_terms`
loads the schema graph in one sweep, but the build runs *outside* the session, so
when it returned ORM rows a descendant that nothing held was collected and the
edge reaching it went back to the database: inside a `run_sync` merely slow, here
`greenlet_spawn has not been called`, which `build_spec` catches and returns as a
build error. The fix at the time was for `SchemaTermCache` to hold the whole
graph rather than just the roots. P2a removed the hazard instead — the sweep
returns flat data, which nothing can collect out from under a caller.

**Measure, and it is the same shape as P1 and P2.** Composing is 27% of a build
at the ZFC fixture's five productions and 51% at seventy-six, so what the phase
removes grows with the grammar — but what it adds is a term-row read, and that
has the flat floor P1 and P2 both ran into. Against dev Postgres, building the
stored system with and without the cache (re-measured after P2a):

| system | productions | rules | cold build | warm build | change |
|---|---|---|---|---|---|
| scoped ZFC | 5 | 4 | **1.1 ms** | 2.2 ms | −95% |
| synthetic, depth 2 | 10 | 8 | **2.6 ms** | 3.3 ms | −24% |
| synthetic, depth 3 | 20 | 16 | 5.9 ms | **5.1 ms** | +13% |
| synthetic, depth 4 | 42 | 30 | 12.1 ms | **9.2 ms** | +25% |
| synthetic, depth 5 | 76 | 40 | 18.8 ms | **12.7 ms** | +33% |

So the crossover is around fifteen productions, and below it a verify pays a
fraction of a millisecond it did not before. When this was first measured the
crossover was at thirty and the smallest system paid 3.7 ms; the whole of that
difference was `prefetch_terms`, then 55% of the warm path and almost all
SQLAlchemy instance hydration, which is what P2a went and fixed. It was the lever
under all three phases rather than P2's alone. And a real system is far past the
crossover either way: set.mm reaches 1,441 productions, where the build, not the
proof, is where a verify's time has gone.

As with P1 and P2, then: the case for P3 today is that the check path no longer
parses a rule schema, not that it is quicker at every size.

**One write site.** Only `_verify_with_references` stores what it composed, and
it does so under the system lock alongside everything else it writes (§3.1). The
other places that build a system — the compile preview, the publish gate — read
nothing and write nothing here: they take no lock, and a system is warmed by its
first verify anyway. It is also skipped when the caller's transaction will be
rolled back (an anonymous viewer verifying a published proof), so the public path
does not pay for inserts that are about to be discarded.

**Rows pair with built rules by label, not by position.**
`FormalSystem.add_inference_rule` *replaces* a rule of the same label, so a system
with a duplicate builds to fewer rules than it has rows and index alignment
attaches one rule's terms to another. The shadowed row's schemas were composed and
then discarded, so it keeps no digest and composes on every build — the behaviour
it had before this phase. A duplicate rule label is a system defect that nothing
currently refuses; that is worth fixing, but not here, and not by way of a 500 on
verify.

**Storage.** `rules.schema_digest` plus `rules.deduction_term_id`,
`subproof_derive_term_id`, `subproof_assume_term_id`, `subproof_fresh_term_id`,
and `rule_antecedents.term_id` — each a nullable FK to `terms`, `ON DELETE SET
NULL` so losing a term costs a re-compose and never a rule.

**A NULL term id is a miss, even under a matching digest**, and the type the
build sees has no way to say otherwise. The first cut let a NULL mean "this
template composes to nothing" — a *hit*, on the reasoning that those are the
templates nothing parses and re-composing one is the most expensive miss there
is. That was wrong three ways over: the same NULL is what `ON DELETE SET NULL`
leaves behind, and what a slot resolving to a declared grammar pattern rather
than a composed one stores, and what a stale-but-digest-matching row holds after
a line or axiom leaves the build namespace. Believing it would have degraded a
rule to its flat projection, which unifies against nothing its nested schema used
to match — a proof that verified yesterday failing today, silently. Composing
again settles all three cases, costs a parse on the one template that genuinely
composes to nothing, and is what the build did before this existed.

**Not in this phase.** Definitions. The design sketch listed
`definitions.higher_term_id` / `lower_term_id` alongside the rules, but a
definition's forms do not go through `build_schema_pattern` at all — they are
matched and registered as *notation* against the finished grammar
(`_finalise_definition`), which mutates the grammar rather than reading it. That
is a different seam. It is now P6, and the difference held up: the storage is
P3's shape exactly, while everything about *where* the cache is consulted follows
from the notation.

### P4. Store promoted theorems — *done*

The metamath roadmap's §3.2, seen from this side. `inference_rules` had a table;
`promoted_theorems` had none, so a corpus import stored a grammar-only system and
its proofs could not be re-checked from rows — a rebuilt system had no `ax-mp` to
resolve, and every imported proof failed on its first citation.

**Measure, met.** Every imported set.mm theorem re-checks from its rows alone and
agrees with the verdict the import recorded — the `.mm` file gone, no statement
parsed:

| walk | productions | library stored | re-checked | agreed | per proof |
|---|---|---|---|---|---|
| first 1,000 | 18 | 1,007 (7 primitive) | 1,000 | **1,000** | 18.4 ms |
| first 5,000 | 148 | 5,069 (69 primitive) | 5,000 | **5,000** | 19.6 ms |

The per-proof cost is worth noting for being *flat*: an eight-fold grammar costs
6%, because what a re-check does is read rows and unify terms, and neither scales
with the grammar. That is the property the whole document is after, and this is
the first phase where it can be seen end to end rather than argued for.

**One library table, and both kinds are lazy.** §3.2 proposed splitting an
imported library by kind: logical `$a` into the existing `rules`, `$p` into a
table of its own, so an imported system's axioms would be real `inference_rules`.
Measurement says the axiom half does not scale. `build_system` builds every rule
eagerly, and at 309 productions 269 axioms-as-rules already cost 0.29 s per build
— extrapolated to set.mm's 1,559 axioms at 1,441 productions, seconds on every
verify. A full import would have been effectively unverifiable.

So the split is by **provenance** rather than by kind: `rules` keeps its meaning —
the handful of primitives an author declared, built with the system — and
`promoted_theorems` holds a library that arrived whole, resolved by label on
demand. `primitive` records which of a library entry's two kinds it is, so "what
does this system assume?" is still one query; it is read by nothing in checking,
because a citation of an axiom and of a derived theorem are checked identically.
That is the same fact §3.2 rests on, pointed at storage instead of at namespaces.

**Loading is by label, and that is the phase.** Promoting one theorem costs a
parse of its statement against the grammar — 0.44 ms at 18 productions, 1.05 ms
at 309, rising with the grammar as any parse does — so promoting 47,546 of them
per build is minutes. A verify instead reads the citations off the proof's own
lines, loads exactly those labels, and promotes them. That is P1's shape applied
to the library: load the lemmas a proof cites, not every proof in the system.

Two things had to move to make the citations knowable before the check:

- **`FormalSystem.read_proof`** — `parse` minus the check, so the parse path can
  read the lines, resolve what they cite, and only then check. `parse` is now
  exactly that pair, and the route calls the halves separately.
- **`load_proof_for_check(..., before_check=…)`** — the same moment on the row
  path: lines populated, nothing resolved yet. P2a moved it *earlier* still, to
  before the lines are built, so the library's terms could join their sweep; it
  is `resolve_citations` now.

**Hypotheses are scoped by storage, as the walk scopes them in time.** A theorem
proves *under* its `$e` hypotheses, and its proof states them as lines citing
their labels — but a `$e` registered as a library entry is a bare `|- ph` that
proves anything, for anyone. The walk handles this by promoting them for the
length of one check and withdrawing them (`corpus._givens`); the rows handle it by
making them reachable only through the theorem that owns them
(`promoted_theorem_premises.label`, `load_theorems`'s `hypotheses_of`), and
`proofs.theorem_id` says which theorem "this proof" establishes. Found by writing
the measure test first: without it, every multi-hypothesis theorem re-checked as
invalid.

**The terms are cached too**, on P3's contract exactly: `schema_digest` guards
them, a NULL or a stale digest is a *miss*, and a miss costs a parse and never a
difference. `library_digest` is the system half of that digest and is wider than
`schema_digests`', because promotion reads more of the system than a rule schema
does — a statement is composed at the sorts a **line** is read at, and a ground
one may use the system's resolved **definitions**.

**One asymmetry worth naming.** For an imported corpus the *cached* term is more
faithful than a re-parse, which is unusual — everywhere else in this document the
stored value is a saved copy of what re-deriving would produce. A walk promotes
each theorem against the grammar as of its own position; the stored system is the
union over the whole walk, so re-composing a statement against that union can read
it through notation declared later (the capture the ordering exists to prevent —
metamath roadmap §1). The digest covers the union, so an unedited import always
hits the cache and gets the term the walk composed. Only the fallback is
approximate, and only for a system whose grammar has since moved, where nothing
about the import is current anyway.

**What this does not do.** Promoting a *natively-authored* proof — the storage is
there, but deciding what a proved lemma generalises to is the metamath roadmap's
A1 and a separate question. And `_link_proofs_to_theorems` joins a proof to its
theorem by name, which is exact for an import (both come from one `$p`) and would
need saying differently for a library assembled any other way.

### P5. Settle the string-rewriting path — *done*

§4's choice had already been made, by P2, without being recorded as made: the row
path recovered a line's flat string by rendering its term (`needs_strings` in
`proofs_mapping`). So the regime was never carved out and `formula_string` was
never stored twice. Half of this phase is just saying so — §4 now does, with the
argument for why rendering is exact rather than close enough.

**The other half is a divergence P4 opened and this found.** The recovery was
*conditional*:

```python
needs_strings = any(rule.matching == "string" for rule in system.inference_rules)
```

Two things wrong with that question, and they compound. A promoted theorem
carries `matching` too and is **not** an inference rule — so a system whose only
string-matching schema is a library entry answered "no". And the library was
resolved after a proof's lines were populated — so even asking about it would
have been asking before the answer existed. (P2a since reversed that order, which
would have fixed this instance and not the class.) The result was
the P2 bug class exactly: a proof that verified when parsed failed when checked
from its rows, silently, with `formula_string` left `None` on every line.

The fix removes the question rather than answering it. `ProofLine.formula_string`
is now a property: the parse's own substring when there is one, the term's render
otherwise. No caller has to know whether a string will be wanted, because no
caller is in a position to know. The parse path is untouched — an explicitly set
string always wins — so this can only ever have added an answer where there was
`None`.

**Measure:** a system whose only string-matching schema is a promoted theorem
round-trips with the same verdict and the same per-line fingerprint
(`test_a_string_matched_theorem_checks_the_same_from_rows`). Mutation-checked:
restoring the conditional fails exactly that case.

**What is still an exception, and honestly so.** Nothing here makes the string
regime *term*-checked — `_string_pairs` still matches flat text, because an
associative rule like `Mx ⊢ Mxx` has no term-unification expression. The claim
this document makes is that verification never *parses*, and that now holds for
string-rewriting systems too. It was never that everything is unification.

### P6. Store definition forms — *done*

P3's deferral, taken up. A definition is written as two strings — `(x ⊆ y)` and
`∀z.((z ∈ x) → (z ∈ y))` — and the build parsed both into the terms an unfold is
checked against. `definitions.higher_term_id` / `lower_term_id` now hold those
terms, guarded by `definitions.term_digest`, on P3's contract exactly: a
mismatched digest makes the rows inert rather than wrong, and a NULL is a miss
rather than "parses to nothing".

**The digest is per system, not per definition**, which is the one place this
diverges from P3. `declarative.definition_digest` fingerprints the grammar and the
*whole ordered block*, and every row of a system carries that one value. Two
reasons, either sufficient: a definition's forms are parsed against the grammar as
extended by the definitions before it, so no definition's terms survive another's
edit; and the slot key is a spec position, which an insertion or a reorder moves
under every later definition. A per-definition digest would have had to cover
every earlier definition anyway, and would still have been wrong about the
indices.

**The stored term stops before binder placement**, and this is the failure this
phase could most easily have shipped. The obvious thing to store is the finished
`Definition.lower`. It round-trips *wrong*: `bind_scoped` places one binder per
ground leaf sitting in a binder slot, and a form that has already been through it
has no such leaves left — so a rebuilt definition would come back with an empty
`fresh`, silently losing the capture-avoidance proviso that is the whole reason
binders are abstract. Nothing about that failure is visible in a proof's verdict;
`test_the_binders_survive_the_round_trip` is what pins it. So `parse_definition`
hands its `record` callback the pair *before* `bind`/`bind_scoped`, and a rebuild
runs both on the stored term exactly as on a parsed one.

That is the general rule this phase confirms, and P3 stated: store what the parse
produced, not what the build did with it. A cache of a derivation's *input* is
inert when stale; a cache of its output is a second implementation.

**What is not skipped.** Only the two parses that produce kernel terms. A rebuild
still matches both forms against the grammar to decide layering and
non-circularity, and still registers the defined form as notation — see §2 on why
those are grammar questions rather than structure. Two smaller derivations also
remain, both bounded: a declared binder's `default` (its bare name, parsed against
its own sort) and a definition's provisos (surface lines into the side-condition
algebra).

**A shadowed grammar name, found in review, and older than this phase.**
`ctx.variables` is one namespace: lines, line parts, axioms and the system are
registered into it after the productions, so an axiom named after a production
leaves a `LineType` under that key and a line *part* leaves a `RegexPattern`.
Composing never noticed — it parses against the sort unions, which hold the
production objects — but a stored term resolves its constructors *by name*. So a
system with such a collision verified once, stored its terms, and then failed on
every later verify: an `AttributeError` for the axiom case, a **silently wrong
term** for the line-part one.

`_shadowed_grammar_names` is in the digest, which reads like a guard against
exactly this, and is not: it catches a collision being *introduced*, while one
present from the outset matches at both ends and is served. The digest is right
that nothing changed — the defect is in the lookup, not the freshness.

So `TermGraph` now resolves a stored constructor through the sort unions and
falls back to the namespace only for a top-level sort, which is the one grammar
pattern no union contains. The index is built once per graph rather than searched
per node: an O(grammar) scan there measured **68× a dict lookup at 400
productions**, on a path that runs per node, which is the mistake
`build_context._GrammarIndex` already records for the build side.

This predates P6 — the same failure reproduces against P3's rule schemas on a
tree without it — but P6 is what surfaced it, and the fix repairs both.

**Measure:** monkeypatching `abstract` — the one call every definition-form parse
goes through — to raise, and requiring a warm build to succeed anyway
(`test_a_served_form_is_not_parsed_at_all`). It does, with zero calls, and
produces a definition set structurally identical to a cold build's. Agreement
alone would not have shown this: a build that consulted the cache and discarded
its answer would pass every other test in the file.

---

### Beyond the phases

Three things this work surfaced that are not phases of it — they belong to
whatever picks up theorem *search*, and are recorded here because that is where
the reasoning is.

**The `theorems` / `promoted_theorems` overlap.** P4 gave a library entry a
`statement` and a `statement_term_id`; the forward-looking `theorems` table
already had both, plus a pgvector `embedding` and an HNSW index. They are two
views of one object, and the duplication is real rather than superficial. Two
things kept them apart, one principled and one not: a `theorems` row is a
statement where a library entry is a *schema* (metavariables, premises, provisos
— which is what makes it applicable rather than merely findable), and their access
patterns are opposite (broad search scan against point lookup by label on the
verify path); but `theorems` was also simply unpopulated, so reusing it would have
meant redesigning an unused table mid-phase. The clean end state is probably one
library row with search metadata hanging off it, rather than each carrying its own
copy of the statement. The moment `theorems` is populated is the moment the
duplication starts costing something, and also the first moment there is enough
information to decide which way to merge.

**Label allocation, if a theorem is ever promoted on demand.**
`promoted_theorems` requires a unique label per system. `proofs.name` has no
uniqueness constraint at all — only `slug`, and only per owner and system — so
promoting a user's proof under its own name collides as soon as two proofs share
one. This also interacts with `_link_proofs_to_theorems`, which joins a proof to
its library entry *by name*: exact for an import, where both come from one
Metamath `$p`, and in want of a different answer for anything else. The two want
settling together, and before the generalisation policy (metamath roadmap A1)
rather than after — a policy that decides *what* a proof generalises to still
needs somewhere unambiguous to put it.

**Goal-directed retrieval needs an index this does not have.** Worth stating
because the naming invites a wrong assumption: `schema_digest` is *not* a search
key. It fingerprints the grammar and a theorem's own text so a cached term can be
trusted, changes when the grammar does, and differs between systems for identical
statements. The search keys are on `terms` — `digest` (exact structure) and
`alpha_digest` (invariant under consistent renaming). `alpha_digest` answers "has
anyone proved exactly this?", which is genuinely useful and is not what proof
search asks: a goal `(A → B)` must retrieve a theorem concluding `ps → ph`, whose
metavariables are `Var` leaves that no whole-term hash relates to the goal. The
cheap first cut is two denormalised columns on `promoted_theorems` — the
conclusion's top constructor (null for a bare metavariable, which matches
anything and must always be a candidate) and the premise count — which prunes
tens of thousands of candidates to hundreds before the kernel confirms by
unification. A path or discrimination index over the conclusion term is the step
up, and `term_children` already has the shape for it; worth measuring before
building, because the top constructor may be enough.

One thing that already works and is easy to miss: **speculative promotion is
free**. `promote_spec` builds a `PromotedTheorem` from a `TheoremSpec` — strings
and names, no database — so a search may promote, try and discard candidates
without writing anything. A row is only needed to make something *durably*
citable. That falls out of keeping the spec engine-object-free, and it is what
makes search cheap.

## 6. Why this is worth doing

Beyond the obvious: the Metamath corpus makes the cost concrete. The whole-corpus
pass spends **1,132 s of its 1,392 s in `check`**, and that time is dominated by
parsing, not by the kernel. The terms for all of it are now stored (metamath
roadmap §1.3) and read by nothing.

It also removes the reason the import is currently ownerless. A stored proof that
cannot be re-checked from its own rows has to be kept away from the verify route,
because a re-check would fail and overwrite the imported structure. Under this
design that failure mode does not exist.

And it is the precondition for the search roadmap's later phases: "which lemma
unifies with my goal" is a query over stored terms, and it is only trustworthy if
those terms are the same objects the checker uses rather than a render of them.

## 7. What this does not change

- **The kernel.** It already takes terms and reads no strings. Nothing here
  touches the trusted core, which is the point — this is a persistence and
  plumbing change with a soundness *boundary* (§3), not a soundness change.
- **Parsing itself.** The matching layer stays exactly as it is; it just runs
  once per line, at write time.
- **The proof source.** `proofs.source` remains what the author typed and what
  the editor renders. It stops being the thing every check reads.
