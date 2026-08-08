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

## What is left

- **Storage.** A fingerprint per promoted-theorem conclusion, computed at
  promotion/import time and stored as rows or columns keyed for the per-position
  compatibility query. This needs an Atlas migration — the first schema change the
  retrieval work has required.
- **Wiring.** `conclusion_candidates` gains a per-position compatibility filter in
  place of the single `constructor` equality; position `()` refines today's
  behaviour (it splits ground leaves by token too), and the deeper positions only
  narrow further, so the change never keeps a candidate the shipped filter would
  have dropped. One reconciliation the wiring must make: the shipped filter keys
  on the constructor *name* (with rename handling via `stored_name`), while a
  fingerprint keys on the *signature* — the same distinction the confirm already
  draws, to settle at that step. The kernel-`unify` confirm stays exactly
  as it is — the filter feeds it a shorter list, nothing more.
- **Measurement.** Recall (must be 100% against a brute-force `unify` oracle) and
  candidate-set-size reduction over the head-symbol baseline, on a corpus slice —
  the metrics the roadmap's Phase 1 already names, now with a baseline to beat
  rather than only the oracle.
