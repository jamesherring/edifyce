# Theorem search, pattern matching, and evolving embeddings — a roadmap

This note records the plan for turning the persisted **term graph**
([`app/db/terms.py`](../app/db/terms.py),
[`app/db/terms_mapping.py`](../app/db/terms_mapping.py)) into a full theorem
*search* and, eventually, proof-*assistance* substrate. It grew out of a
question about the `terms` table's `digest` interning: exact structural hashing
answers "have we got this exact statement?", but not the queries a real proof
library is actually asked — "same statement up to what the variables are
called", "which lemma applies to my goal", "what's related to this".

The through-line: **retrieval and strategy are separable, and most of the value
lands before any AI.** Each phase below is independently shippable, states what
it unlocks with examples, and — importantly — how we measure that it works.

---

## Motivation

The engine treats a formal system as source it recompiles, and a proof as text
it re-checks. That is the right core, but it means the only way to ask a
*structural* question across a corpus ("which theorems are implications", "which
mention `∈`", "which lemma unifies with this goal") would be to load and reparse
everything. The term graph fixed the storage half of that: statement structure
is now normalised, shared rows queryable in plain SQL.

What remains is the *query* half. Structural search over stored terms is a
spectrum, from cheap-and-exact to fuzzy-and-semantic:

1. **exact equality** — dedup, "is this already proven";
2. **equality up to variable renaming** — "the same theorem, different letters";
3. **equality up to the known theory** — `a + b` vs `b + a` once commutativity
   is proven; `x ⊆ y` vs `∀z (z ∈ x → z ∈ y)` by definition;
4. **pattern / partial match** — "a lemma of the shape `? ⊆ ?`", "whose
   conclusion unifies with my goal";
5. **semantic similarity** — "theorems *about* the same thing", fuzzy recall.

A single mechanism does not span this. Whole-term hashes handle (1)–(3);
(4) is a matching/unification problem; (5) wants an embedding. The roadmap builds
each in turn, reusing the same term rows.

---

## Phase 0 — Exact and α-renaming digests **(done)**

`digest` (exact structural hash, the interning key) and, as of this branch,
`alpha_digest` — a second hash that numbers free variables by first occurrence,
so it is invariant under consistent renaming while `digest` is not.

**Unlocks**

- Dedup / "already proven?": exact `digest` lookup, `O(1)`.
- "Same statement up to variable names": `alpha_digest` equality.
  `a ∈ b` and `y ∈ z` share an `alpha_digest`; `a ∈ a` (a shared variable) does
  not — sharing is preserved.

```sql
-- every theorem α-equivalent to a query statement, one indexed lookup
SELECT digest FROM terms
WHERE formal_system_id = :sys AND alpha_digest = :query_alpha;
```

**Measuring success**

- *Correctness (unit):* α-invariance across renamings, sensitivity to variable
  sharing and to structure — see
  [`tests/test_alpha_digest.py`](../tests/test_alpha_digest.py). The oracle is
  the kernel's own `Term.equal` up to a renaming.
- *Property test (future):* for random terms, `alpha_digest(t) ==
  alpha_digest(rename(t))` for every bijective renaming, and collisions imply
  α-equivalence on a sampled corpus (no false merges).

---

## Phase 1 — Structural retrieval index (pattern / goal-directed search)

**The prefilter half of this is built** — see
[authoring-and-ingestion-roadmap.md](authoring-and-ingestion-roadmap.md) §9d. The
head-symbol filter (`terms.constructor`, indexed per system) and the `unify`
confirm are in place and serving two endpoints; the α-exact case is Phase 0's
digest doing the work. What that filter does *not* do on its own — narrow below the
root, so the candidate set is small rather than merely smaller — is the fingerprint
index below, now built on top of it.

**The deeper index has now landed** as a *fingerprint index* (Schulz 2012,
the SQL-native member of the discrimination-tree family), with the design and the
100%-recall argument in [search-phase1-fingerprint.md](search-phase1-fingerprint.md).
The engine primitive (`website/logical/fingerprint.py`) and its soundness suite
(`tests/test_fingerprint.py`) landed first; then storage (a fingerprint per
promoted-theorem conclusion) and the wiring into `conclusion_candidates`
(`app/db/fingerprints.py::fingerprint_filter`), which the statement search and a
proof line's citations now pass a goal fingerprint to. Position `()` of the
fingerprint is a refinement of the head-symbol filter above (it also splits ground
leaves by token), and the deeper positions only narrow further — so the wiring
extends the filter rather than replacing it.

That ordering was deliberate: the cheap filter needs no new representation and no
new storage, so it could ship behind the same interface a term net will use.
Candidates in, unification confirms; `app/db/retrieval.py` is the seam, and
replacing its query with an index lookup is a local change. The measurements below
are still the ones that say whether it was worth doing — and now have a baseline
to beat rather than a brute-force oracle alone.

A **discrimination tree** (a.k.a. term net) over the term graph, plus a
head-symbol prefilter, plus a kernel-`unify` confirm step. The index key is the
pre-order flattening of a term with variable positions collapsed to a wildcard
`*`; a query pattern (its holes → `*`) retrieves the small candidate set of
unifiable terms, and [`website/logical/kernel/unify.py`](../website/logical/kernel/unify.py)
confirms each and yields the substitution.

This is the data structure behind Lean's `DiscrTree`, HOL term-nets, and (as
substitution/fingerprint trees) the indexing in Vampire and E.

**Unlocks** — the queries that dominate real use:

- `find_theorems`-style search: "lemmas of the form `? ⊆ ?`", "`x ⊆ ?` for a
  fixed `x`".
- **Goal-directed apply search** (`exact?` / `apply?`): "which stored theorem's
  conclusion unifies with my current goal `(A ∧ B) → C`?"
- **Rewrite search** (`rw?`): "equations whose LHS matches a subterm of my
  goal" — per-subterm index rows make "matches *anywhere*" tractable.

**Measuring success**

- *Recall/precision against a brute-force oracle:* on a fixed corpus, compare
  index results to the ground truth from running kernel `unify` against *every*
  stored term. Target **100% recall** (the index must never miss a real match —
  it is a filter, unification is the authority) and report precision (candidate
  set size / true matches) as the pruning quality.
- *Latency & scaling:* median/p95 query time vs corpus size (1e3 … 1e6 terms);
  candidate-set size vs corpus size (should stay near-constant, not linear).
- *End-to-end:* on a benchmark of proofs, how often the lemma a human actually
  cited appears in the top-k retrieved (recall@k) — this is the metric that
  predicts usefulness of `apply?`.

---

## Phase 2 — Theory-aware canonical digest (α + equational theory)

A congruence structure — congruence closure / an **e-graph** (à la egg /
egglog / equality saturation) — over the system's *known* equalities:
definitions' higher↔lower (oriented, terminating rewrites) and proven equational
lemmas (commutativity, associativity, …). Terms are normalised to a canonical
class representative before hashing, giving a `theory_digest` that extends the
`digest → alpha_digest` ladder one step further.

**The design note is [search-phase2-theory-digest.md](search-phase2-theory-digest.md),
and it disagrees with this section in three places worth reading before starting.**
The two halves above are not one phase: the *definitional* half has its input
structured, its termination already proven by the conservativity check and its
binder canonicalisation already solved, while the *equational* half has no input
at all — a system cannot declare which of its productions means equality, and
nothing structural distinguishes `↔` from `→`. **Congruence is not free**: a
congruence closure merges `f(a)` with `f(b)` by construction, but in a declared
logic that is a theorem schema, and set.mm proves it one position at a time
(`oveq1d`, `fveq2d`, …), so an e-graph would assume what a corpus spends its bulk
establishing. And "oriented, terminating" is not enough: the definitional relation
is acyclic but **not confluent**, since two definitions may share a defined form,
so a term can have two normal forms and therefore two digests. The note's
recommendation is to split the phase and build the definitional half first — which
needs no equality declaration, since a definition already *is* an oriented
equation, and no congruence, since an unfold is licensed at a position by the
kernel's own definitional step.

**Unlocks**

- Dedup and exact search **up to the known theory**: `a + b` and `b + a` merge
  once commutativity is proven; `x ⊆ y` and `∀z (z ∈ x → z ∈ y)` merge by
  definition. "Do we already have this, in any equivalent form?"
- Normal forms for downstream layers (a stable key for the embedding in Phase 3).

**Measuring success**

- *Soundness (must-hold):* two terms share a `theory_digest` **only if** they
  are provably equal under the recorded equalities. Test by generating equal
  pairs from known rewrites (positive) and near-miss unequal pairs (negative);
  zero false merges on the negatives.
- *Completeness (best-effort, it is undecidable in general):* fraction of
  known-equal pairs the canonicaliser actually merges, at a fixed saturation
  budget. Track this as coverage; regressions flag a canonicaliser weakness.
- *Cost:* saturation time per term and per new axiom; guard against AC blow-up
  with a step budget and report how often the budget is hit.

---

## Phase 3 — Deterministic *evolving* embedding

A deterministic, compositional fold of the term DAG into ℝⁿ — a catamorphism
with a **fixed (non-learned) combiner per constructor**:

- default: an order-sensitive positional combiner (a fixed tensor over child
  vectors);
- **commutative constructor → a symmetric combiner** (sum / max / multiset
  pooling), so `emb(a + b) = emb(b + a)` *by construction*;
- **definition → the higher form's combiner returns the lower form's
  embedding**, so `emb(x ⊆ y) = emb(∀z (z ∈ x → z ∈ y))`.

It is *evolving*: proving `+` commutative flips its combiner to symmetric; a new
definition wires its combiner; then re-fold. Because terms are an interned DAG,
a re-fold is `O(#distinct subterms)` with memoisation, and dependency tracking
limits recomputation to the classes a new fact actually touches. Vectors land in
the existing pgvector column (cosine via HNSW).

**Unlocks**

- Fuzzy structural retrieval by cosine similarity — a fast prefilter that
  complements the exact Phase-1 index ("roughly this shape / theory-class").
- An embedding whose notion of "similar" **improves as the library grows**:
  each proven equality reshapes the space so equivalent statements draw together
  — without an LLM, deterministically, reproducibly.

**Measuring success**

- *Invariance:* after proving an equality, `cos(emb(a+b), emb(b+a)) == 1`
  (identical), and definitional pairs collapse — a direct assertion.
- *Retrieval quality:* nearest-neighbour recall@k against the Phase-2
  `theory_digest` classes as ground truth (does cosine surface the truly-related
  terms before the unrelated ones?). Report ROC/AUC of "same theory-class" vs
  cosine.
- *Update cost & stability:* re-fold + reindex time per new axiom; and
  embedding *stability* — how much unrelated vectors move when one axiom lands
  (should be local; large drift means the combiner design leaks).

---

## Phase 4 — AI / strategy layer

Retrieval (Phases 1–3) becomes the substrate for *assistance*:

- **Premise selection**: heuristic relevance first (symbol overlap, MePo-style),
  then learned (transformer premise selectors — Magnushammer / ReProver /
  LeanDojo style).
- **Retrieval-augmented tactic / LLM suggestion**: feed the retrieved lemmas to
  a model that proposes the next step or a whole sketch.
- **Proof search**: best-first / MCTS over the rule set, seeded by retrieval.
- A **learned semantic embedding** (LLM or GNN) stored *alongside* the
  deterministic Phase-3 vector — the deterministic one captures
  structure-modulo-theory, the learned one captures "aboutness". They are
  complementary; keep both.

This is the "Sledgehammer / Lean-Copilot for Edifyce" layer.

**Measuring success**

- *Premise selection:* recall@k of the human-cited premises on held-out proofs;
  ablation vs the Phase-1 structural baseline (does learning beat structure?).
- *End-to-end autoformalisation/closure rate:* fraction of held-out goals the
  assistant closes within a step/time budget — the headline number.
- *Human-in-the-loop:* acceptance rate of suggestions; log which retrieved
  lemmas actually closed goals.

---

## Phase 5 — Feedback loop

Every closed goal records which retrieved lemmas were used → a training signal
that continuously improves the Phase-4 ranker (and can retune Phase-3 combiner
weights). Success = the recall@k and closure-rate metrics above trending up over
time on a frozen benchmark.

---

## On the evolving embedding: novelty and neighbouring ideas

The **exact** half (canonicalise modulo a growing equational theory, then hash)
is *not* novel in isolation — it is congruence closure / e-graphs / equality
saturation (egg, egglog, SMT cores) and AC-canonicalisation (Maude), well-trodden
ground. What is comparatively **novel is the framing as an incrementally-updated
embedding for retrieval**: making a *vector* space quotient by a theory that
*grows as theorems are proven*, and accepting a full re-embed on each new axiom
as the price. Most learned embeddings for maths (ReProver, Magnushammer, HOList,
GNN term embeddings) are trained offline and are only *approximately* invariant
to anything; they do not update their metric the moment a lemma is proven, and
their invariances are emergent, not guaranteed. A deterministic fold with
*symmetric combiners switched on by proven algebraic facts* gives **exact,
auditable invariance that evolves** — that specific combination is uncommon.

Neighbouring ideas worth considering:

- **E-graph–backed retrieval directly** (skip the vector): index on e-class ids,
  so "up to theory" search is a class lookup, not a cosine. Exact, but no fuzzy
  recall — pairs well with Phase 3 rather than replacing it.
- **Anti-unification / least-general-generalisation indexing**: index theorems
  by their most-specific common generalisations, enabling "find lemmas of which
  my goal is an instance" and analogy search. Classic but under-used in
  interactive provers.
- **Learned combiners under a hard invariance constraint** (equivariant /
  invariant neural nets): keep the compositional fold, but *learn* the per-node
  combiners while *architecturally* enforcing the symmetric-for-AC constraint —
  a hybrid of Phase 3 and Phase 4 that stays exactly invariant yet generalises.
- **Hashing modulo theories as a hash family**: treat `digest`, `alpha_digest`,
  `theory_digest`, and a locality-sensitive hash of the embedding as one ladder
  of coarsening buckets, chosen per query — a clean, uniform API over the whole
  exact→fuzzy spectrum.
- **Contrastive training from the proof corpus itself**: use proven equalities
  as positive pairs and refutations/distinct-normal-forms as negatives to train
  the learned embedding — the corpus supplies its own labels, no annotation.

The pragmatic recommendation stands: build Phases 1–2 (exact, high-value, no ML)
first; treat the evolving embedding (Phase 3) as a deterministic complement to
that index and a bridge into the learned layer (Phase 4), not a replacement for
either.
