# Design: verification from rows, not from text

**Status:** P1–P4 shipped, P5 proposed · **Prerequisite work:** merged (the term
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
P1–P4.

| Verification needs | Stored | Used |
|---|---|---|
| A line's formula as a term | yes — `proof_lines.term_id` → `terms` | **yes** (P2) |
| Line type and behaviour | yes — `proof_lines.line_type` / `behaviour` | **yes** (P2) |
| The citation a line was written with | yes — `proof_lines.reference` | **yes** (P2) |
| Whether a cited lemma stands | yes — its lines' verdicts | **yes** (P1) |
| Justification edges | yes — `proof_line_antecedents` | no — *re-derived* from the citation, deliberately |
| Scope tree (for discharge) | yes — `proof_lines.opens_scope` / `scope_id` | no — *re-derived*, deliberately |
| Rule schema terms | yes — `rules.deduction_term_id` etc. → `terms` | **yes** (P3), when `rules.schema_digest` still matches |
| Definition higher/lower forms | **no** | stored as strings, matched against the grammar at build |
| Promoted theorems | yes — `promoted_theorems` → `terms` | **yes** (P4), resolved by label per citation |

The two *deliberate* nos are the point rather than an omission. Edges and scope
are stored so the graph is queryable, and re-derived so a check is a check: if a
row could supply a line's justification, a corrupted row could assert one.
Everything a verdict rests on is recomputed; the rows supply only what each line
*states*.

**The proof side is closed.** Everything a proof contributes is in rows and read
back on every check.

**The system side is closed but for one seam.** Rule schemas are stored as
composed terms and read back (P3); the citable library is stored and resolved by
label (P4), so an imported Metamath proof re-checks from its own rows. What is
left is a definition's forms, which are *registered as notation* against the
finished grammar rather than composed against it — a different mechanism, and the
only remaining thing a build reads from a string.

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

## 4. The one honest exception

String-rewriting systems (semi-Thue: MIU and friends, `matching == "string"`)
cannot be term-only by construction. `InferenceRule._string_pairs` matches
schemas against `ProofLine.formula_string` by associative matching — splitting
and concatenation the term unifier deliberately cannot express. `formula_string`
is kept beside `formula_term` for exactly this reason.

Two options, both acceptable, neither free:

- persist `formula_string` alongside the term, so those systems also check from
  rows; or
- carve them out explicitly — a system declaring string matching re-parses, and
  the API says so — rather than letting them silently fall back.

Either way it must be a stated exception, since "verification never parses" is
otherwise false in a way that would surface as a mysterious performance cliff.

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
  meant to serve goes back to the database. `prefetch_terms` returns its rows and
  the caller must hold them.
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

### P2a. The constant factor — *follow-up*

Deliberately not done here, because the phase is about where the parse happens
rather than how fast the read is, and because both levers are self-contained
enough to land on their own evidence.

- **Three round trips could be two.** A load is the line rows, the recursive
  closure over `term_children`, then the term rows with their edges. The first
  two could be one statement; the closure is only ever the filter for the third.
- **Term rows are hydrated through the ORM.** `prefetch_terms` builds a
  `TermRow` object graph and `load_term` walks relationships, when the shape
  needed is flat tuples fed straight to the kernel's constructors. P1's profile
  put most of the remaining time in SQLAlchemy's instance machinery, not in the
  term rebuild.
- **A single-proof load pays the batching penalty P1 documented.** Verifying one
  proof is inherently one proof, so the fixed cost cannot be amortised the way a
  reference closure's is. That argues for cutting the per-load floor rather than
  batching harder.

Worth measuring against a *large* grammar before choosing: the crossover moves
with grammar size, and set.mm's full 1,441 productions may put it below the
current numbers without any of this.

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
resolves them back through that same namespace (`terms_mapping.load_term`), and
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

**One trap, and it is P1's trap again.** `prefetch_terms` loads the schema graph
in one sweep, but the build runs *outside* the session — so a descendant row that
nothing holds is collected, and the edge that reaches it goes back to the
database. Inside a `run_sync` that is merely slow; here it is
`greenlet_spawn has not been called`, which `build_spec` catches and returns as a
build error. `StoredSchemaTerms` holds the whole graph, not just the roots.

**Measure, and it is the same shape as P1 and P2.** Composing is 27% of a build
at the ZFC fixture's five productions and 51% at seventy-six, so what the phase
removes grows with the grammar — but what it adds is a term-row read, and that
has the flat floor P1 and P2 both ran into. Against dev Postgres, building the
stored system with and without the cache:

| system | productions | rules | cold build | warm build | change |
|---|---|---|---|---|---|
| scoped ZFC | 5 | 4 | **1.5 ms** | 5.2 ms | −243% |
| synthetic, depth 2 | 10 | 8 | **3.2 ms** | 7.1 ms | −122% |
| synthetic, depth 3 | 20 | 16 | **7.5 ms** | 8.7 ms | −16% |
| synthetic, depth 4 | 42 | 30 | 15.4 ms | **13.9 ms** | +10% |
| synthetic, depth 5 | 76 | 40 | 23.1 ms | **17.8 ms** | +23% |

So the crossover is around thirty productions, and below it a verify pays a few
milliseconds it did not before. Two things about that. The overhead is *entirely*
`prefetch_terms` — 55% of the warm path in profile, almost all SQLAlchemy
instance hydration — which is P2a's second lever, and this makes it the lever
under all three phases rather than P2's alone. And a real system is on the far
side of the crossover: set.mm reaches 1,441 productions, where the build, not the
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
is a different seam and belongs with P5's tidying, not here.

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
  path: lines populated, nothing resolved yet.

**Hypotheses are scoped by storage, as the walk scopes them in time.** A theorem
proves *under* its `$e` hypotheses, and its proof states them as lines citing
their labels — but a `$e` registered as a library entry is a bare `|- ph` that
proves anything, for anyone. The walk handles this by promoting them for the
length of one check and withdrawing them (`corpus._givens`); the rows handle it by
making them reachable only through the theorem that owns them
(`promoted_theorem_premises.label`, `load_hypotheses`), and `proofs.theorem_id`
says which theorem "this proof" establishes. Found by writing the measure test
first: without it, every multi-hypothesis theorem re-checked as invalid.

**The terms are cached too**, on P3's contract exactly: `schema_digest` guards
them, a NULL or a stale digest is a *miss*, and a miss costs a parse and never a
difference. `library_digest` is the system half of that digest and is wider than
`schema_digests`', because promotion reads more of the system than a rule schema
does — a statement is composed at the sorts a **line** is read at, and a ground
one may use the system's resolved **definitions**.

**What this does not do.** Promoting a *natively-authored* proof — the storage is
there, but deciding what a proved lemma generalises to is the metamath roadmap's
A1 and a separate question. And `_link_proofs_to_theorems` joins a proof to its
theorem by name, which is exact for an import (both come from one `$p`) and would
need saying differently for a library assembled any other way.

### P5. Settle the string-rewriting path

Per §4 — persist `formula_string`, or carve the regime out explicitly.

---

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
