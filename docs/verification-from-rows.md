# Design: verification from rows, not from text

**Status:** proposal (no code yet) · **Prerequisite work:** merged (the term
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

### P1. Trust a stored lemma verdict

The smallest change and the largest saving. `_verify_with_references` currently
compiles the whole transitive reference closure and re-checks every lemma, only
to ask `_is_usable_lemma` a question the database already answers:

```python
def _is_usable_lemma(engine_proof) -> bool:
    return bool(engine_proof.valid) and not engine_proof.has_warnings
```

Both halves are stored: `proofs.valid`, and `has_warnings` is exactly *any line
carries a `warning_message`* (`FormalSystem.check_proof`), which is an `EXISTS`
over `proof_lines`. A citation reaching into a lemma (`[alias.3]`) needs that
lemma's line 3, which is `proof_lines` keyed by `(proof_id, number)` — already
the coordinate `proof_line_antecedents` records for cross-proof edges.

**Measure:** verifying a proof at the head of a chain of *N* lemmas issues zero
parses of those lemmas, and wall clock stops growing with *N*.

**Watch for:** a lemma whose verdict is stale must not be trusted. The existing
invalidation (`_invalidate_dependents`, `discard_system_checks`) is what makes
`valid` safe to read; this phase's real work is proving that it is airtight, not
the read itself.

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
