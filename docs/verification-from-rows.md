# Design: verification from rows, not from text

**Status:** P1 shipped, P2–P5 proposed · **Prerequisite work:** merged (the term
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

| Verification needs | Stored today | Used today |
|---|---|---|
| A line's formula as a term | **yes** — `proof_lines.term_id` → `terms` | **no** — `load_term` has no callers outside tests |
| Line type and behaviour | yes — `proof_lines.line_type` / `behaviour` | no — re-derived by re-matching the source line |
| Justification edges | yes — `proof_line_antecedents` | no — re-derived from the citation string |
| Scope tree (for discharge) | yes — `proof_lines.opens_scope` / `scope_id` | no — re-derived |
| Whether a cited lemma stands | **yes** — `proofs.valid`, and warnings via `proof_lines.warning_message` | **no** — the whole transitive closure is re-parsed and re-checked |
| Rule schema terms | **no** | composed at build time by parsing the `rules` template strings |
| Definition higher/lower forms | **no** | same — stored as strings, parsed at build |
| Promoted theorems | **no** | not persisted at all (metamath roadmap §3.2) |

Two distinct gaps, and they are different sizes.

**The proof side is nearly closed.** Everything a proof contributes is in rows
already; `store_proof_lines` writes it on every verify and nothing reads it back
except `GET /proofs/{id}` for display. The rows are a **write-only read-model**.

**The system side is not started.** Rule and definition schemas live as template
strings, so compiling a system parses them every time — `compose_schema_term`
parses each rule template against the productions at build. That is per-verify,
not per-line, but under this model it should not happen either. Promoted
theorems are the extreme case: nothing at all, which is why an imported Metamath
proof cannot currently be re-checked from its own rows.

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

Recording the decision matters more than the mechanism: it should be taken
deliberately, once, rather than arrived at by a series of caching optimisations.

**Decided, and P1 acts on it.** Stored terms are the authoritative parse. Two
consequences were taken with it: there is **no fallback to parsing** a lemma
whose rows are missing — a compatibility path for data written before the rows
existed is legacy debt, and the database it would serve is empty — and the
invalidation paths above are now soundness-critical, so they are tested rather
than trusted. The engine-version stamp remains open; the digest covers structure
and names, not the kernel semantics that read them.

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

### P2. Rebuild a proof from its rows instead of parsing it

Reconstruct `ProofLine`s directly: formula via `load_term`, line type by stored
name, antecedents from the edges, scope from `scope_id`, then run the existing
`check` over them. No `FormalSystem.parse` on the path.

This is where §3's contract inversion actually lands.

**Measure:** re-verifying an unedited proof produces the identical verdict *and*
byte-identical rows (an idempotence test), with no parse invoked.

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
