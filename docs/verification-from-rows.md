# Design: verification from rows, not from text

**Status:** P1 and P2 shipped, P3–P5 proposed · **Prerequisite work:** merged (the term
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

This table is what the phases below work through; **used** is the state after P1
and P2.

| Verification needs | Stored | Used |
|---|---|---|
| A line's formula as a term | yes — `proof_lines.term_id` → `terms` | **yes** (P2) |
| Line type and behaviour | yes — `proof_lines.line_type` / `behaviour` | **yes** (P2) |
| The citation a line was written with | yes — `proof_lines.reference` | **yes** (P2) |
| Whether a cited lemma stands | yes — its lines' verdicts | **yes** (P1) |
| Justification edges | yes — `proof_line_antecedents` | no — *re-derived* from the citation, deliberately |
| Scope tree (for discharge) | yes — `proof_lines.opens_scope` / `scope_id` | no — *re-derived*, deliberately |
| Rule schema terms | **no** | composed at build time by parsing the `rules` template strings (P3) |
| Definition higher/lower forms | **no** | same — stored as strings, parsed at build (P3) |
| Promoted theorems | **no** | not persisted at all (P4; metamath roadmap §3.2) |

The two *deliberate* nos are the point rather than an omission. Edges and scope
are stored so the graph is queryable, and re-derived so a check is a check: if a
row could supply a line's justification, a corrupted row could assert one.
Everything a verdict rests on is recomputed; the rows supply only what each line
*states*.

**The proof side is closed.** Everything a proof contributes is in rows and read
back on every check.

**The system side is not started.** Rule and definition schemas live as template
strings, so compiling a system parses them every time — `compose_schema_term`
parses each rule template against the productions at build. That is per-verify,
not per-line, but under this model it should not happen either. Promoted
theorems are the extreme case: nothing at all, which is why an imported Metamath
proof cannot yet be re-checked from its own rows.

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

**One correctness lesson worth keeping.** A first cut let a proof with an
unparseable line come back *valid* on the second verify: the row records no line
type, so nothing executed, so the line kept `ProofLine`'s optimistic default.
Every other verdict was re-derived and that one was not. Deciding "no line type
⇒ cannot stand" in `check_proof` rather than where the match failed fixes it, and
the shape of the mistake is the thing to remember — a check from rows is only
sound if *every* verdict is re-derived, including the ones that look like they
were settled by the absence of something.

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

### P3. Store schema terms

Rule deductions and antecedents, and definition higher/lower forms, as terms
interned into the same `terms` DAG rather than as template strings parsed at
build. Note that `_schema_term(pattern, occurrence, …)` freshens bare-sort
positions per occurrence — that is a runtime step over a stored term, not a
parse, and stays.

**Measure:** compiling a system with *N* rules invokes no parse; system build
time stops scaling with template complexity.

### P4. Store promoted theorems

The metamath roadmap's §3.2, seen from this side. `inference_rules` have a
table; `promoted_theorems` have none, which is why the corpus import stores a
grammar-only system and its proofs cannot be re-checked from rows. It also
unblocks promoting natively-authored proofs (that needs the generalisation
policy in the metamath roadmap's A1, which is a separate question).

**Measure:** an imported set.mm theorem re-checks from rows alone and agrees
with the verdict the import recorded.

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
