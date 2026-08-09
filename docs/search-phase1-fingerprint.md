# Phase 1: the fingerprint index

Phase 1 of [search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md)
is a structural retrieval index — the thing that makes a goal-directed candidate
set *small* rather than merely smaller. This note records how it is being built,
starting from the engine primitive and working outward to storage and the
retrieval wiring.

## What is already here, and why it is not enough

Retrieval today (`app/db/retrieval.py`, shipped as §9d of
[authoring-and-ingestion-roadmap.md](authoring-and-ingestion-roadmap.md)) narrows
a library to the theorems whose conclusion has the **same root production** as a
goal — an indexed column, `terms.constructor`, and a kernel-`unify` confirm. That
is one sampled position, the root, and it degenerates exactly where the retrieval
PR's sequent-calculus example showed: when every statement is `Γ ⊢ φ`, the head
symbol is always the turnstile, the filter narrows nothing, and the informative
structure — the succedent — sits one level below where it can see.

The fix is to sample more than the root.

## The representation: a fingerprint, not a trie

A textbook discrimination tree is a trie over the pre-order flattening of a term
with variables collapsed to a wildcard. It is the right data structure in memory;
it is the wrong one for a stateless service whose every other index is a **row**
(`terms`, `schema_terms`, the promoted-theorem statement terms). Rebuilding a trie
per request, or maintaining one as parent-pointer rows, both fight the grain.

**Fingerprint indexing** (Schulz 2012 — the indexing in E and, as
substitution/fingerprint trees, Vampire) is the SQL-native member of the same
family. Fix a small set of sample positions; record, per indexed term, the
feature at each. A fingerprint is then a fixed-width vector — columns a database
stores and compares position by position. Position `()` is the head-symbol filter
that is already shipped, **refined**: it keys on the constructor like that filter,
but also carries a ground leaf's token, so it splits `a` from `b` where the
constructor-only filter does not (still recall-safe — the unifier compares
literals too). So the deeper positions do not replace the head-symbol filter; they
extend a refinement of it, and adding positions only sharpens pruning — it never
changes what matches.

The engine primitive is `website/logical/fingerprint.py`, a dependency-free leaf
utility over kernel terms (beside `graphs.py`, and like the digests in
`app/db/terms_mapping.py`, never consulted by the checker).

### Features

At a sampled position a term has either a **symbol** — its constructor
*signature* (what the unifier compares by, so a rename is one feature), plus the
literal token for a ground leaf, since two atoms of one production unify only
when their tokens agree — or one of three markers, following Schulz:

| marker | meaning | compatible with |
|---|---|---|
| `A` (`VARIABLE`) | a variable sits exactly here | anything **present** — every symbol, `A`, `B`; **not** `N` |
| `B` (`BELOW_VAR`) | the position lies under a variable | **everything** — the variable above subsumes it |
| `N` (`ABSENT`) | the path ran off the end of the term | only `N` and `B` |

Two symbols are compatible iff equal. Everything else follows the table. The
letters are Schulz's (`A` variable, `B` below-variable, `N` nonexistent), so a
stored fingerprint reads against the paper.

### The contract: 100% recall

`compatible(fingerprint(a), fingerprint(b))` is `True` for **every** pair the
kernel can unify. The proof is position-local: in a successful match, at each
sampled position either a variable (or a position below one) sits on one side —
compatible by construction — or both sides carry concrete structure the unifier
already reconciled, so their symbols are equal and their arities agree, leaving no
`A`/`B` or symbol/symbol clash. So a caller that keeps the compatible candidates
and confirms each with `unify` loses nothing; the filter only ever saves the
unifier work. `tests/test_fingerprint.py` pins this against the kernel unifier as
oracle — a curated cross-product and a seeded fuzz of random goals — so a
fingerprint that ever pruned a real match fails the suite. Precision (how much it
prunes) is reported alongside, because a filter that keeps everything is sound and
useless.

### The position set

`FINGERPRINT_POSITIONS` is E's default FP7 — `{ε, 0, 1, 00, 01, 10, 11}`, the
root, its first two children, and their first two. It is the one knob Phase 1's
measurements turn: widening it sharpens pruning at the cost of a wider stored
vector, and never affects recall.

## Why seven — measured on 10k set.mm theorems

Measured against the development corpus: **10,101 theorem conclusions** from a
layered set.mm import (Propositional ⊂ FOL ⊂ ZF). Recall is a proven 100%, so
what is measured is *pruning power* — how much each width narrows the library
before the unifier is asked — over 10 realistic goals spanning the common head
symbols and a range of sizes. Candidate set as a fraction of the library:

| width | positions | mean candidate set | note |
|---|---|---|---|
| W1 (head only) | `{ε}` | **22.2%** | the shipped filter; **63.7%** for an implication goal |
| W3 | `+ {0, 1}` | **2.2%** | a 10× cut — the root's children are 77–87% concrete symbols |
| **W7 (shipped)** | `+ {00,01,10,11}` | **1.6%** | halves the deep goals: `2r19.29` 589→294, `ax12wdemo` 580→302 |
| W15 | `+ depth 3` | **1.6%** | ~1% better; depth-3 positions are ~90% variable/absent markers |
| full disc-tree | all positions | **1.6%** | within ~1% of W7 |

Two things make the choice. First, **64% of set.mm conclusions are implications**
(`wi`), so the head-symbol filter (W1) leaves two-thirds of the library for the
single most common goal shape — it is barely a filter there. Second, the pruning
is concentrated in the top two levels: at depth 1 positions are 77–87% concrete
symbols, at depth 2 about half, and by depth 3 only ~5–16% (the rest are shared
metavariables — `ph`, `ps`, `x` — which fingerprint as "compatible with anything"
and do not prune). The distinct-fingerprint count says the same: W1 partitions
the library into 46 buckets (mean 220 theorems each), W3 into 1,784 (mean 5.7),
**W7 into 5,861 (mean 1.7)**, W15 into 6,698 (mean 1.5).

So **W7 sits at the knee**: W1→W3 is the big win, W3→W7 roughly halves the
candidate set for the *deep* goals (nested implications, quantified statements —
exactly the large terms whose `unify` confirm is most expensive), and W7→W15→full
buys ~1% for a wider or unbounded key. A **full discrimination tree** — a
variable-length preorder key needing a trie — lands within ~1% of the fixed
seven-integer fingerprint, which is why fingerprint indexing exists as its own
technique: the fixed vector a database indexes trivially captures essentially all
the structural pruning the corpus offers, and the kernel confirm mops up the rest.
(These figures are the structural filter; the true `unify`-able set is ≤ them, and
that residual — repeated-variable and sort constraints — is common to every width,
so it does not move the comparison.)

## Definitions, and the theory boundary

A fingerprint filters for *syntactic* unification, so it does **not** see through
definitions — and it must not, because neither does the confirm it feeds. A
definition makes `⊆` (`wss`) its own constructor; the unfolding
`∀x (x ∈ A → x ∈ B)` (`wal`) is a different term with a different head. On the
corpus, `df-ss` is stored as the biconditional `( A ⊆ B ↔ ∀x (x ∈ A → x ∈ B) )`,
and its two sides fingerprint incompatibly at the root:

```
A ⊆ B                       ε:wss   0:A   1:A    00:B  01:B  10:B     11:B
∀x ( x ∈ A → x ∈ B )        ε:wal   0:A   1:wi   00:B  01:B  10:wcel  11:wcel
                            └── clash at ε: wss vs wal — pruned, and the unifier agrees
```

A `⊆` goal retrieves the 141 `⊆`-headed theorems and none of the 22 `∀`-form
ones, though some are definitionally equivalent. This is correct: the filter and
the confirm must stay in lockstep, since recall is defined *relative to the
confirm*. Making the filter definition-aware without a definition-aware confirm
would be unsound. Crossing a definition is therefore a **step**, not a match: an
author applies the definition (a definitional step, or a biconditional rewrite
citing `df-ss`) to change the goal's head from `wss` to `wal`, and *then*
retrieval finds the `∀`-form theorems.

Merging synonyms directly is exactly **Phase 2** (theory-aware canonical digest):
an e-graph over the definitions and equational lemmas normalises each term to a
canonical representative *before* fingerprinting, so the `⊆`-form and the `∀`-form
reduce to one normal form and one fingerprint. The fingerprint machinery is
unchanged — it runs over normalised terms, and the confirm normalises too, so the
lockstep and the recall guarantee hold, now up to the definitional theory. The
layered guarantee: Phase 0 recall up to α-renaming, **Phase 1 up to syntactic
unification** (synonyms distinct), Phase 2 up to the definitional + equational
theory (synonyms merged).

## What is left

- **Storage** — *done.* A fingerprint per promoted-theorem conclusion, computed
  in `store_theorem` from the conclusion term (`promoted.deduction.schema_term`,
  under the same `StringPattern` guard as `statement_term_id`, so imports are
  covered automatically) and stored on `promoted_theorems.conclusion_fingerprint`
  as `[position-set key, features]` JSON (`app/db/fingerprints.py`). It is present
  exactly when the cached term is, so a theorem is "indexed" consistently. Existing
  rows carry NULL until re-indexed — the same "unindexed" state a NULL cached term
  already has. One Atlas migration (a nullable column add).
- **Wiring** — *done.* `conclusion_candidates` takes an optional `goal_fingerprint`
  and, given one, adds a per-position compatibility filter
  (`app/db/fingerprints.py::fingerprint_filter`) to the WHERE clause. It is layered
  *on top of* the indexed head-symbol filter rather than replacing it: the
  constructor column is a btree index and picks the bucket, and the fingerprint —
  a JSON column no index covers — narrows within it, so the two play the roles the
  measurements assumed. The reconciliation the design called for — the head filter
  keys on the constructor *name*, a fingerprint on the *signature* — is settled by
  scope: a signature is invariant to a production's name and variable spellings but
  **not** to its surface skeleton or a constant's token, which a *mapped* rename
  edge is allowed to change (`translation.py`: only an *unmapped* name is held to
  equal signatures). So the fingerprint is applied only to **identity-translation
  layers** — the inheritance spine and any edge that agrees on spelling, where the
  stored and query signatures match by construction — and a mapped relation edge
  falls back to the head filter's name inversion (`stored_name`) alone, exactly as
  before the fingerprint existed. Recall is preserved four ways — the filter only
  ever *adds* conditions to the head filter, and never crosses a mapped edge;
  a NULL or stale-position-set fingerprint falls back to the head filter rather
  than being dropped (the engine `compatible` *raises* on a key mismatch, so it is
  never silently miscompared); and `tests/test_fingerprint_sql.py` pins the SQL
  per-position predicate to the engine's `features_compatible` over every feature
  pair. The kernel-`unify` confirm is untouched — the filter feeds it a shorter
  list, nothing more. Two of the three call sites pass a fingerprint: the
  statement search and a proof line's citations, both of which already hold a built
  goal term. The browse-by-stored-term route
  (`GET /formal-systems/{id}/theorems`) deliberately does not build the system, and
  a signature-keyed fingerprint is what a build produces, so it stays on the head
  filter alone. The JSON extraction is dialect-aware (`type_coerce` on SQLite,
  `cast` on Postgres), since neither form reads a stored fingerprint on the other.
  One Postgres constraint shaped the storage: a feature carries the signature
  skeleton's hole marker, a NUL byte, and Postgres can neither bind a NUL parameter
  nor extract a `json` value that contains one — it *raises* on any such row rather
  than skipping it, so there is no SQL that safely reads around one. Both the stored
  form and the query features therefore replace NUL with a control byte no template
  uses (`app/db/fingerprints.py`), and a one-shot data migration
  (`migrations/20260809100841_sanitize_fingerprint_nul.sql`) rewrites the
  fingerprints the storage step wrote before this to the same NUL-free form. SQLite
  tolerates NUL, so this is invisible there; it is what makes the deployment work.
- **Measurement** — *done* (see "Why seven" above): candidate-set-size reduction
  over the head-symbol baseline on the 10k-theorem corpus, and the width analysis
  justifying W7 against W3, W15, and a full discrimination tree.
