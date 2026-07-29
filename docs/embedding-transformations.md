# Design: Phase-3 embedding transformations — what a fold can and cannot absorb

**Status:** analysed, **not built**. This note answers the design questions
Phase 3 of [search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md)
leaves open, and it changes two of that phase's claims. The short version:

- The dimension budget is a real ceiling, but it is **not** the one to worry
  about, because the transformations should not consume dimensions at all.
- A *linear* fold cannot absorb even **one** equality as a congruence, let alone
  `n` of them. The failure is qualitative, not a matter of running out of room.
- Both are avoided by the same move: put the transformation **inside** the fold
  (at the constructor, keyed on a canonical class) rather than **after** it (as
  a map on already-computed vectors). Inside, capacity is a hash table and is
  unbounded; outside, capacity is a subspace and is `n`.
- Terms and equations do **not** need different embeddings — in this schema an
  equation *is* a term. The genuinely different levels are hypotheses-plus-
  conclusion, proofs, and — the one the roadmap misses — **unfold depth**.
- The roadmap's cost claim, "a re-fold is `O(#distinct subterms)` with
  memoisation", is **false for an α-invariant fold**, for the same reason
  `store_term` already pays `O(rows × subterm)` for `alpha_digest`.

---

## 1. Three places a transformation can live

Write the fold as a catamorphism over the interned DAG
(`website/logical/kernel/terms.py`):

```
emb(Var v : s)              = leaf(s, v)
emb(Bound i : s)            = bound(s, i)
emb(Node c {l₁:t₁ … l_k:t_k}) = f_c(emb(t₁), …, emb(t_k))
```

A fact — a definition, or a proven equality `u = v` — can be honoured in three
distinct places, and almost all of the difficulty in the roadmap's Phase 3 comes
from not distinguishing them:

| Where | Mechanism | Congruence | Capacity |
|---|---|---|---|
| **Before** the fold | rewrite `t` to a canonical form, then fold | free (you folded the canonical form) | unbounded — it is a rewrite system |
| **Inside** the fold | `f_c` for the defined constructor returns the defining form's vector; or a per-node lookup keyed on the node's class | free (compositionality) | unbounded — it is a lookup table |
| **After** the fold | a map `Q : ℝⁿ → ℝⁿ` with `Q·emb(u) = Q·emb(v)` | **must be imposed**, and cannot be | `n`, at best |

The roadmap's own three bullets are all *inside*-the-fold moves ("commutative
constructor → symmetric combiner", "definition → the higher form's combiner
returns the lower form's embedding"). The question in this task — "for each
definition, a transformation that ensures equivalent statements get an identical
embedding … how does this scale when the number of definitions exceeds the number
of dimensions?" — is an *after*-the-fold framing. The two have completely
different cost models, and the rest of this note is mostly about why the
after-the-fold framing is the one that fails.

---

## 2. Why the after-the-fold transform fails, and it is not about counting

Suppose the fold is linear (the roadmap's default, "a fixed tensor over child
vectors"):

```
emb(c(t₁ … t_k)) = Σᵢ A_{c,i} · emb(tᵢ) + b_c
```

We prove `u = v` and want a quotient `Q` with `Q·emb(u) = Q·emb(v)`, i.e.
`d = emb(u) − emb(v) ∈ ker Q`. The obvious move is
`Q = I − dd^T/‖d‖²` — one rank-one projection, one dimension spent. If that were
the whole story, the budget would be `n` facts and the question would be exactly
the counting question posed.

It is not the whole story, because **equality is a congruence**. If `u = v` then
`C[u] = C[v]` for every context `C`, so `Q` must also kill
`emb(C[u]) − emb(C[v])`. For a linear fold the additive offsets cancel and

```
emb(C[t]) = M_C · emb(t) + b_C,     M_C = A_{c₁,i₁} A_{c₂,i₂} ⋯ A_{c_m,i_m}
```

— a product of slot matrices along the path from the root to the hole. So

```
emb(C[u]) − emb(C[v]) = M_C · d
```

and `ker Q` must contain `M_C·d` for **every** context, i.e. `ker Q` must be an
invariant subspace for the multiplicative semigroup `S = ⟨{A_{c,i}}⟩` containing
`d`.

> **The collapse.** If `S` acts irreducibly on `ℝⁿ` — which is the *generic* case;
> two or more random matrices generate a subsemigroup of `GL(n)` with no proper
> invariant subspace almost surely — then the only invariant subspaces are `0`
> and `ℝⁿ`. Since `d ≠ 0`, `ker Q = ℝⁿ`, so **`Q = 0`**.

A single exactly-honoured equality annihilates the entire space. Not the 1537th;
the first. The counting question never gets a chance to bite.

### 2.1 The escapes, and what each costs

**Make the combiners reducible on purpose.** Choose the `A_{c,i}` block-diagonal
so that plenty of proper invariant subspaces exist, and reserve one per future
fact. This restores the naive budget — you can now merge along at most `n`
pre-reserved invariant lines — but at a price that is easy to miss: *the more
invariant subspaces you leave available for merging, the less the combiners mix
child vectors, and the weaker the structural fingerprint*. In the limit of `n`
one-dimensional invariant subspaces, every `A_{c,i}` is diagonal, the fold is `n`
independent scalar folds, and `emb` distinguishes almost nothing. **Expressiveness
of the fold and capacity for post-hoc merging are in direct tension**, and they
trade against each other one dimension at a time.

**Settle for "almost identical".** Contract instead of project:
`Q = ∏ᵢ (I − λᵢ dᵢ dᵢᵀ)`. This is the option the question proposes, on the
strength of the (correct) observation that `ℝⁿ` hosts exponentially many
near-orthogonal directions. The observation is true and the conclusion does not
follow. Take `K` difference directions `d₁ … d_K`, unit, pairwise `|⟨dᵢ,dⱼ⟩| ≤ ε`,
with `K ≫ n`. Generic such families are approximate tight frames:

```
Σᵢ dᵢ dᵢᵀ ≈ (K/n) · I     with fluctuation O(√(n/K))
```

so to first order in `λ`

```
Q ≈ I − λ (K/n) I = (1 − λK/n) · I
```

— a **scalar multiple of the identity**. And cosine similarity is scale-invariant.
So once the number of facts exceeds the dimension, a linear correction is in one
of exactly two regimes:

- `λK/n < 1`: `Q` is (to first order) isotropic. It shrinks everything uniformly
  and **changes no cosine at all**. The only signal is the `O(√(n/K))`
  fluctuation term, which *shrinks as you prove more theorems*.
- `λK/n → 1`: `Q → 0`. The space collapses.

There is no useful middle. The exponential supply of near-orthogonal directions
buys you the ability to **keep many things apart**; it buys nothing for
**bringing pairs together**, because merging consumes rank and rank is exactly `n`.

This is worth stating as the general principle, because it is not obvious:

> **Separation capacity is exponential in `n`; identification capacity is linear
> in `n`.** A fixed-dimension space can distinguish `exp(Ω(ε²n))` classes to
> within cosine `ε`, but can absorb at most `n` independent linear
> identifications. The two are not symmetric and no amount of
> "almost" recovers the gap.

Concretely, at the schema's current `EMBEDDING_DIMENSIONS = 1536`
(`app/db/models.py:62`): separating ~10⁷ distinct classes at pairwise cosine
≤ 0.25 is comfortable; absorbing more than 1536 merges is impossible. A realistic
target corpus — set.mm via `website/logical/metamath/importer.py` — carries on
the order of 10³ definitions and well over 10⁴ equational and biconditional
theorems. So the ceiling is not hypothetical; it is crossed by the first corpus
we intend to import.

### 2.2 Where the exponential capacity *does* pay

Replace the global linear `Q` with a **localised nonlinear edit applied at every
node during the fold**:

```
E(x) = x + Σᵢ λ · σ(⟨x, kᵢ⟩ − τ) · wᵢ
emb(Node c {…}) = normalise( E( f_c(emb(t₁), …, emb(t_k)) ) )
```

with `kᵢ` a key derived from one side of fact `i` and `wᵢ` pushing toward the
class representative. This is a key-value memory, structurally the same object as
a transformer's feed-forward block or a `ROME`/`MEMIT`-style model edit. Two
things change:

1. **Congruence becomes free.** We no longer need `Q` to commute with contexts,
   because the correction is applied *inside* the bottom-up fold: when the node
   for `e^{ix}` is corrected toward the vector for `cos x + i·sin x`, every parent
   recomputes from the corrected child, so `f(e^{ix})` and `f(cos x + i·sin x)`
   agree automatically. Compositionality does the work that the invariant-subspace
   condition could not.
2. **Capacity becomes the number of ε-separated keys**, which *is*
   `exp(Ω(ε²n))`. This is the regime the question's intuition was reaching for,
   and here it is correct.

The price is precision: any term whose raw vector lands within `τ` of a key gets
merged whether or not it is equal. That is the honest content of "almost
identical" — it costs **false merges**, not dimensions.

### 2.3 …and why the localised edit is still the wrong build

Push `τ → 0` and `σ` toward an indicator and `E` becomes an exact lookup keyed on
the raw vector. But a raw vector is a *lossy* key — it is a fixed-dimension hash
of the term. We already have a **lossless** key for exactly this: Phase 2's
`theory_digest`, sitting next to `digest` and `alpha_digest` on `TermRow`
(`app/db/terms.py:75-80`). Keying the lookup on the digest is exact, `O(1)`,
collision-free, and needs no dimensions.

> **The answer to "can we generate and support an arbitrary number of such
> transforms?"** Yes — unboundedly many — precisely because we should not be
> spending dimensions on them. Each definition and each oriented equality is a
> row in a rewrite/class table consulted during the fold, not a direction in
> `ℝⁿ`. The vector space's only job is to make *unrelated-but-similar* things
> close, and for that its exponential separation capacity is more than enough.

So the recommendation reverses Phase 3's implied division of labour:
**exact invariance comes from canonicalisation; the embedding supplies only
smooth similarity.** Phase 3's own success criterion,
`cos(emb(a+b), emb(b+a)) == 1`, should be met by folding the *e-class
representative*, not by transforming `ℝⁿ`. Which means Phase 3 does not stand
alone — it is a fold over Phase 2's output, and building it first would be
building the weak half of a mechanism whose strong half is a hash column.

---

## 3. Definitions specifically: free, but not costless

A definition (`website/logical/kernel/definitions.py`) is a pair `(higher, lower)`
with a fixed orientation, and unfolding terminates. So it needs no transformation
at all: fold the unfolded form. `emb(x ⊆ y) := emb(∀z (z ∈ x → z ∈ y))`, by
construction, at zero dimensional cost.

Two costs are real, and neither is the one the question anticipated.

**Expansion blow-up.** Definitions nest. Fully unfolding a statement in a mature
ZFC development can grow it by orders of magnitude, and the fold's cost is linear
in the *unfolded* DAG. Mitigated by the interning — a shared unfolded subterm is
folded once — but the bound is the unfolded graph, not the surface one.

**Abstraction loss, which is worse.** If everything is folded fully unfolded, then
every statement in set theory is a formula over `∈` and the logical connectives,
and the embedding has thrown away exactly the layer a human searches by. "Find
lemmas about `⊆`" becomes unanswerable, because `⊆` no longer exists in the folded
representation. The invariance we wanted at the top of the ladder destroys the
discriminative power we wanted at the bottom.

The fix is a **graded, multi-resolution embedding**: fold at several unfold
depths and store them side by side.

```
emb₀  — surface notation, no unfolding      → "looks like a subset statement"
emb₁  — one level of definitional unfolding
emb∞  — primitives only                     → "the same thing said differently"
```

`emb₀` and `emb∞` answer genuinely different queries and neither subsumes the
other. This is the first of the "multiple levels" the question asks about, and the
roadmap does not currently have it.

A constraint the codebase imposes on all of this: the kernel **deliberately** does
not see through definitions. `Term.equal` and `unify` are purely structural, and a
definitional unfold is a *cited step* (`kernel/terms.py`, "Design invariant — the
kernel hard-codes no logic"; `kernel/definitions.py`). An embedding that silently
identifies `x ⊆ y` with its unfolding therefore disagrees with the kernel's notion
of equality. That is fine for retrieval and must never leak into checking — the
vector is a prefilter and `unify` remains the authority, exactly as Phase 1 states
for the discrimination tree.

---

## 4. Theorems: the orientable fragment, and the rest

Can the same mechanism carry proved results? The Euler example is well chosen,
because it is the easy case and it is easy for a reason worth naming.

`e^{ix} = cos x + i·sin x` **can** be treated exactly like a definition: orient it
left-to-right and the rewrite terminates, because the right-hand side contains no
`e^{i·}` to fire again. Fold the right-hand side and both sides get the same
vector, at zero dimensional cost, congruence included. So: yes, for this theorem,
and for the whole **orientable, terminating** fragment.

The fragment has hard edges:

- **Not orientable.** `a + b = b + a` has the same term size on both sides, and
  either orientation loops. Commutativity is not handled as a rewrite; it is
  handled by a *symmetric combiner*, `f_c(x, y) = g(x + y)`, which is the
  roadmap's own bullet and is genuinely free.
- **Associativity is not free, and the roadmap implies it is.** Tying slot
  matrices gives commutativity but not associativity: with
  `f_+(x,y) = P x + P y`, `emb(a+(b+c)) = P a + P²b + P²c` while
  `emb((a+b)+c) = P²a + P²b + P c`. These differ. AC needs the argument list
  *flattened and canonically ordered before* the combiner runs — i.e. a
  canonicalisation step, i.e. Phase 2 again. The combiner alone gets you C, U
  (units) and idempotence; it does not get you A.
- **Divergence.** Turning a growing set of proven equalities into a terminating,
  confluent rewrite system is Knuth–Bendix completion, which is semi-decidable and
  can diverge. Worse for an *evolving* system: adding one equation can break
  confluence of the whole set, so the "evolving" step is not merely a re-fold, it
  is a re-completion. The roadmap's cost model ("proving `+` commutative flips its
  combiner to symmetric; then re-fold") understates this.
- **Undecidability.** The word problem for a finitely presented equational theory
  is undecidable in general, so "equivalent statements get an identical embedding"
  is unachievable as stated. What is achievable, and what Phase 2 already asks
  for, is the sound direction only: *merged ⟹ provably equal*, never the
  converse. The embedding inherits that — it is incomplete by construction, never
  unsound. Coverage is a metric, not a guarantee.

---

## 5. Levels: what actually differs, and what only appears to

> "we could be applying it to the term space, so that specific entries such as
> `e^(ix)` get an embedding. But also to equations such as `f(x) = e^x`. These are
> both graphs but are different kinds."

In this schema they are **not** different kinds. `f(x) = e^x` is a `Node` whose
constructor is the system's equality production, with two children; `e^{ix}` is a
`Node` whose constructor is exponentiation. Both are `TermRow`s in the same graph
(`app/db/terms.py`), and `Theorem.statement_term_id` points at a `TermRow` like
any other (`app/db/models.py:343`). The engine's uniformity here is real and worth
keeping: one fold, one space, no special case for "statement".

That uniformity is also *required* by the use cases. Rewrite search (`rw?`) needs
a vector for every subterm, and premise selection needs a vector for the statement
root; if these lived in different spaces you could not ask "which stored equation's
left-hand side resembles this subterm of my goal".

What differs is not the space but the **query distribution**, and that is an index
concern, not an embedding concern: one column on `terms`, several partial HNSW
indexes (statement roots; subterms; per sort). Not several folds.

The levels that are *genuinely* different objects:

1. **Sequent level — hypotheses plus conclusion.** A Metamath `$p` with `$e`
   hypotheses, or a `PromotedTheorem` (`website/logical/promotion.py`), is a *set*
   of terms plus a distinguished one. That is not a term and cannot be folded as
   one. It wants its own aggregation — an order-insensitive pool over the
   hypotheses concatenated with the conclusion vector, `2n` wide, so that
   conclusion-matching (which is what `apply?` needs) is not diluted by
   hypothesis-matching.
2. **Proof level.** A proof is a DAG of `ProofLineRow`s. "Find proofs shaped like
   this one" pools line vectors and the multiset of cited rule names. Different
   object, different index, same underlying fold.
3. **Unfold depth**, per §3. The axis the roadmap is missing.
4. **System level**, if cross-system search is wanted — see §6.

---

## 6. Should the sort be part of what gets embedded?

Mostly it already is, and where it is not, it should not be.

**Already implicit.** A node's vector is produced by its constructor's combiner,
and a constructor determines the sort it inhabits. Distinct sorts therefore land in
distinct regions of the space with no extra machinery. Reserving explicit
coordinates for a one-hot sort tag spends dimensions to re-encode something the
combiner already encodes.

**And it should stay a filter, not a dimension.** Sort is a *hard* constraint —
a `class` must never be returned when the goal wants a `wff` — and hard constraints
belong in `WHERE`, not in a cosine. `TermRow.sort` is already a column
(`app/db/terms.py:70`). The one caveat is the standard filtered-ANN problem:
pgvector's HNSW post-filters by default, so a selective `WHERE sort = …` degrades
recall. With few sorts per system the clean fix is a **partial HNSW index per
(system, sort)** rather than one global index with a filter.

**The seed is the more interesting question.** Terms are interned *per system*
(`uq_terms_system_digest`), and if the combiner matrices are seeded per system then
vectors from two systems are incomparable — you could never ask "does another
system already have this lemma". But `Constructor.signature`
(`kernel/constructors.py:48`) is precisely the template skeleton with variable
occurrences replaced by anonymous holes, deliberately ignoring the production's
name and its variable spellings. Seeding

```
A_{c,i} = H(c.signature, i)
```

makes the fold **system-independent**: two systems that spell implication the same
way get the same combiner, and cross-system retrieval falls out for free. The cost
is collisions — two systems using one glyph for different things become spuriously
similar — which is a false-positive in a prefilter and therefore acceptable. This
seems clearly worth doing and is not in the roadmap.

---

## 7. The α-invariance problem, which this repo has already paid for once

The roadmap says a re-fold is `O(#distinct subterms)` with memoisation. For a raw
structural fold that is right. For an **α-invariant** fold it is wrong, and the
evidence is already in the tree.

`alpha_digest` numbers free variables by first occurrence in a pre-order walk over
the whole term (`app/db/terms_mapping.py:170-186`). That numbering is a property of
the *root*, not of the subterm — the α-hash of `(z ∈ x)` depends on where `x` and
`z` first appeared in the enclosing statement. Which is why `store_term` computes
each row's `alpha_digest` by a *separate* call and its docstring records the price
outright: "Computing it per row is `O(rows × subterm)`" (`terms_mapping.py:284`).
The parent's α-digest cannot be assembled from the children's stored α-digests.

An α-invariant embedding inherits exactly this. Memoise `emb` per `TermRow` and the
root is not α-invariant; make the root α-invariant and the memo is keyed by
(subterm, enclosing numbering) and stops being shared across statements. The DAG
sharing that makes the whole scheme cheap is lost precisely where we most want it.

Note what is *not* affected: `Bound` is de Bruijn-indexed and intrinsic
(`kernel/terms.py:211`), so bound-variable α-equivalence is compositional and free.
The problem is confined to free and schematic `Var`s.

Three ways out, in increasing order of ambition:

- **Sort-generic variables.** All free variables of a sort embed to one vector.
  α-invariance and memoisation are both free; the cost is that `a ∈ a` and `a ∈ b`
  collapse. Recover the difference with a small separate sharing signature
  (a hash of the variable-occurrence partition) appended at the statement root
  only. Cheapest, and probably right for a first cut.
- **Memoise ground subterms only.** Correct and simple; sharing benefits drop to
  whatever fraction of the corpus is ground, which in a schematic library is low.
- **Fold to a multilinear map rather than a vector.** Represent a term with `k`
  free variables as a constant vector plus a coefficient vector per variable, and
  symmetrise over variable orderings. α-invariance is then automatic (names never
  enter) and sharing is preserved (the map is symmetric only where the term is),
  and composition works. Cost is `O(k)` storage per node and a truncation at some
  `k_max`. Attractive; unproven; would want its own note.

---

## 8. The evolving index, which is the other understated cost

Every merged class changes vectors, and pgvector HNSW does not update in place —
an updated row is a delete plus a reinsert, and graph quality degrades under churn.
Dependency tracking bounds the recompute to affected classes, as the roadmap says,
but the bound is weak where it matters: a fact touching a *primitive* — `∈`, `→`,
equality — touches essentially the whole corpus, so the worst case is a full
re-embed and a full reindex. Two consequences to design in from the start:

- **Version the embedding.** An `embedding_version` column, rebuild offline into a
  new index, swap atomically. Live mutation of a 10⁶-row HNSW under query load is
  not a thing to attempt.
- **Vectors are not a stable identifier.** Anything cached against them — "related
  theorems" shown to a user, and especially Phase 5's training signal, which is
  collected *under* an embedding — goes stale on every re-embed. Phase 5's feedback
  loop needs to record the version it was collected under or it will train on
  a moving target.

Finally, a schema gap: there is no `embedding` column on `terms` at all. The only
vector in the schema is `theorems.embedding`, and it is sized `1536` to match a
*text* embedding model (`app/db/models.py:60-62`). A deterministic fold wants its
own column at its own dimension, and the roadmap's Phase 4 explicitly wants both
kept side by side. Two columns, two dimensions, two indexes.

---

## 9. What this changes in the roadmap

Concretely, Phase 3 as written should be amended:

1. **Reorder the dependency.** Phase 3 is a fold over Phase-2 class
   representatives, not a parallel mechanism. Built before Phase 2 it can deliver
   smooth similarity but not the invariance claims in its own success criteria.
2. **Drop the after-the-fold framing.** Never transform `ℝⁿ` to honour a fact; the
   linear version provably collapses (§2) and the nonlinear version is a worse
   spelling of a digest lookup (§2.3). Every transformation goes inside the fold.
3. **Correct "commutative constructor → symmetric combiner".** It buys C, U and
   idempotence. It does **not** buy A; associativity needs flattening at
   canonicalisation.
4. **Correct the re-fold cost.** `O(#distinct subterms)` holds only for a
   non-α-invariant fold (§7).
5. **Add unfold depth as a stored axis** (§3) — the single change that most
   improves retrieval quality per unit of work.
6. **Seed combiners from `Constructor.signature`**, not per system (§6).
7. **Add the sequent-level aggregation** for hypotheses-plus-conclusion (§5);
   `apply?` needs it and no fold over a single term provides it.

---

## Appendix A — a worked example in 3 dimensions

Small enough to print every vector. One system: sort `term` (variables, `∅`, `ω`,
`(x ∪ y)`), sort `formula` (`x ∈ y`, `x ⊆ y`, `(p → q)`, `∀.p`). One orthogonal
`3×3` matrix per (constructor, slot), seeded from the constructor's signature;
leaves are seeded unit vectors; `Bound` is de Bruijn, so binders need no leaf.

```
emb(Node c {l₁:t₁ … l_k:t_k}) = ( Σᵢ A_{c,lᵢ} · emb(tᵢ) ) / √k
```

Scaling by `1/√k` instead of normalising per node keeps the fold exactly affine,
which is what lets a definition's compiled map be displayed below.

**A.1 One matrix per slot, not one matrix on the sum.** Tying a constructor's
slot matrices together *is* "apply one matrix to the sum of the children" — and
that is precisely the commutative combiner, so it must be opt-in:

```
per-slot     cos(∅ ∈ ω, ω ∈ ∅) = +0.229      order preserved
slots tied   cos(∅ ∈ ω, ω ∈ ∅) = +1.000      order discarded
```

**A.2 A definition costs one compiled affine map, not a dimension.**
With `x ⊆ y ≝ ∀z.(z ∈ x → z ∈ y)`:

```
before wiring   emb(a ⊆ b)        = [ 0.814  0.469  0.010]
                emb(∀z.(z∈a → z∈b)) = [ 0.481  0.592 -0.350]   cos = +0.844
after  wiring   both              = [ 0.481  0.592 -0.350]     cos = +1.000
```

and because the fold is affine, the definiens folds *once* into a map reusable at
every occurrence — `O(1)` per node thereafter, no unfolding at fold time:

```
emb(x ⊆ y) = b + L_x·emb(x) + L_y·emb(y)
L_x = [-0.161 -0.028 +0.472; -0.471 +0.057 -0.157; +0.045 +0.496 +0.045]
L_y = [+0.347 +0.167 -0.319; +0.205 +0.272 +0.366; +0.296 -0.385 +0.120]
```

**A.3 A new theorem updates one flag, and congruence follows.** Proving
`x ∪ y = y ∪ x` ties `union`'s two slot matrices. Nothing else is edited:

```
                                    before     after
cos(∅ ∪ ω,      ω ∪ ∅)             -0.967     +1.000
cos((∅ ∪ ω) ⊆ c, (ω ∪ ∅) ⊆ c)      +0.739     +1.000     ← congruence, unedited
emb(a ∈ b)                         unchanged  unchanged  ← locality
```

The context case is the point: no correction was applied to `⊆`, yet the two
`⊆` statements agree, because the fold is bottom-up and the parent recomputes
from a corrected child. This is the whole content of §2's "inside, not after".

**A.4 The variable-naming choice, and its cost.** Numbering free variables by
first occurrence (what `alpha_digest` does) gives the wanted invariance *with*
sharing; a sort-generic leaf gives the invariance and loses sharing:

```
first-occurrence   cos(a∈b, y∈z) = +1.000     cos(a∈b, a∈a) = +0.469
sort-generic       cos(a∈b, y∈z) = +1.000     cos(a∈b, a∈a) = +1.000   ← a∈a lost
```

But first-occurrence numbering is a property of the *root*, so the same term row
folds to different vectors in different contexts:

```
emb(c ∈ a) standalone          [ 0.431 -0.685  0.517]   numbering {c:0, a:1}
emb(c ∈ a) inside (a∈b)→(c∈a)  [ 0.941 -0.355  0.253]   numbering {a:0, b:1, c:2}
                                                        cos = +0.783
```

— §7's non-compositionality, made concrete. A memo keyed on the term row is
simply wrong.

**A.5 The compositional fix, and its degeneracy.** Carry, per node, the affine
form `emb(t) = b(t) + Σ_v L_v(t)·e(v)` keyed by *variable identity*. This
composes (`L_v(c(t₁,t₂)) = (A_1 L_v(t₁) + A_2 L_v(t₂))/√2`), mentions no
numbering, and so is memoisable on the exact `digest` — which is what `TermRow`
is already interned by. α-invariance is then a **readout** taken at index time,
symmetric in the variables. Two candidate readouts, and neither works alone:

```
lin = b + Σ_v L_v·v₀        G = Σ_v L_v L_vᵀ

                    lin                        ‖G − I‖
a ∈ b               [-1.044 -0.195 -0.365]      0.000
y ∈ z               [-1.044 -0.195 -0.365]      0.000
a ∈ a               [-1.044 -0.195 -0.365]      1.527
(a∈b) → (c∈d)       [ 0.580 -0.342 -0.343]      0.000
(a∈b) → (a∈d)       [ 0.580 -0.342 -0.343]      0.631
```

`lin` is exactly the sort-generic fold: it carries structure and is blind to
sharing (rows 1–3 coincide). `G` is blind to structure — with orthogonal slot
matrices and `1/√k` scaling the quadratic form telescopes to `I` for *any* term
whose leaves are all distinct free variables (rows 1, 2, 4), so it registers only
the sharing partition and the leaf-weight profile. They are exactly
complementary, and the usable α-invariant key is the **pair** `(lin, G)` — `lin`
in the vector column, `G` (or a fixed contraction of it) as a small appended
block. Cost is `O(#free vars)` matrices per node during the fold, which is why
the truncation at some `k_max` in §7 matters.

---

And one thing the embedding will never do, worth recording so it is not
rediscovered: cosine is **symmetric**, so it cannot express *subsumption* —
"my goal is an instance of this lemma" is a directed relation and a
nearest-neighbour query has no way to represent it. That is what Phase 1's
discrimination tree is for, and if the ordering is ever wanted in vector form it
needs an order-embedding geometry (box or cone embeddings), not a metric one.
