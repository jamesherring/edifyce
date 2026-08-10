# `experiments/` — the Lindenbaum–Tarski embedding experiment at corpus scale

A 2,400-formula prototype over hand-constructed ZFC axiom families found two
things: an ordinary syntax/graph embedding of a formula predicts its provability
at **chance**, while embedding a formula by its *behaviour* under assignments to
known theorems makes the connectives exact algebra and provability an exact
geometric condition. This directory re-runs both against the **10,177 theorems in
the shared dev database**, to find out which of the two results was an artefact
of scale.

Short answer: neither was. The negative result gets *stronger* with real
mathematics, and the positive one is a theorem, so it survives unchanged. What
the scale-up buys is a third measurement the prototype could not make, and it is
the discouraging one — see [The gap](#the-gap-structure-does-not-predict-semantics).

## Running it

The dev database holds a `set.mm` import as **three cumulative layers** —
propositional calculus, first-order logic, ZF — each with its own interned term
rows. Read them all; the layers are cumulative, so ⊢Aᵢ holds in the top layer
whichever one declared it, and a compound may mix them.

```bash
uv run --with numpy --with scikit-learn python -m experiments.lindenbaum.run \
    --neon-https --out experiments/results --compounds 24000
```

`--neon-https` reads over Neon's SQL-over-HTTP endpoint using `$POSTGRES_URL`,
which is what a sandbox whose egress policy does not allow the Postgres port has
to do. The whole corpus — 207,311 terms, 427,978 edges — comes across in 16 s,
keyset-paged; the analysis then takes ~80 s. Against a database reachable on 5432
drop the flag and pass `--database-url`.

To reproduce the corpus locally instead of using the shared one:

```bash
scripts/edifyce-dev db up && scripts/edifyce-dev migrate
curl -sSLo set.mm https://raw.githubusercontent.com/metamath/set.mm/develop/set.mm
DATABASE_URL=postgresql://postgres@127.0.0.1:5439/edifyce \
  uv run python scripts/import_metamath.py set.mm --limit 10000 --setmm-overrides --quiet
```

That gives one unlayered system rather than three. Both runs are committed —
[`results/dev-database.json`](results/dev-database.json) and
[`results/local-import.json`](results/local-import.json) — and every number below
is the dev database's, with the local import quoted where the two differ enough
to be worth seeing. `--cache <path>` saves the corpus to a pickle, worth doing if
you are iterating.

## What is being classified

Both experiments classify the same set of formulas, so the comparison is
like-for-like. The corpus supplies **generators** A₁…Aₙ — theorems it actually
proved — and the fragment is Boolean combinations of them, each labelled by an
argument rather than by a model:

> if every Aᵢ is a theorem and f(A₁…Aₙ) is true when every Aᵢ is true, then
> (A₁ ∧ … ∧ Aₙ) → f is a propositional tautology whose antecedent the corpus
> proves, so ⊢f. If f is false there, the same argument gives ⊢¬f.

So every formula in the fragment is *certified* provable or *certified*
refutable. Two restrictions on generators are soundness, not convenience:

- **No hypotheses.** A Metamath theorem with `$e` hypotheses asserts a rule —
  from ⊢H₁…⊢Hₖ infer ⊢C — not ⊢(H₁ ∧ … ∧ Hₖ) → C, which is exactly what fails for
  generalisation. That is 4,480 of the 10,177 entries, and treating them as ⊢C
  would make the labels wrong rather than noisy.
- **A stored conclusion term**, since a generator with no term cannot be walked.

Free metavariables are *not* a restriction: a `$p` with free `ph` is provable
under every admissible substitution and in particular the identity one, which is
the instance used.

The compounds are built in set.mm's own grammar — `wn`, `wa`, `wo`, `wi`, `wb`
over the generators' conclusion terms — so what the structural embedding sees is
a well-formed wff of the imported system averaging 69 nodes, not a synthetic tree
standing in for one.

| | |
|---|---|
| theorems | 10,177 across 3 layers (177 primitive, 4,480 with hypotheses) |
| interned subterms | 207,311 |
| citation edges | 101,790 |
| generators (closed, with a term) | 5,696 |
| compounds | 24,000, balanced 12,000 / 12,000 |
| distinct Boolean skeletons | 17,989 |

## Experiment 1 — does syntax predict truth?

A 526-dimensional embedding: 512 hashed **alpha-normalized subtree** features
plus 14 whole-term statistics, matching the prototype's width. The held-out
families mirror the prototype's {Foundation, Infinity, Separation, Replacement}
rather than being sampled — training sees propositional and predicate calculus,
Extensionality and Union; the test set is Power Sets, Infinity, Replacement and
Regularity, 2,025 generators the classifier has never seen a theorem from.

| method | unseen-family | random split | prototype (unseen) |
|---|---|---|---|
| linear classifier | **55.4 %** | 54.3 % | 50.4 % |
| RBF SVM | **53.7 %** | 53.2 % | 50.0 % |
| nearest neighbour | **50.8 %** | 48.8 % | 49.7 % |

The prototype also got ~60 % on a *random* split. Here the random split falls to
the unseen-family level: with 5,696 distinct generators rather than ten axiom
families, a random split no longer leaks a shared vocabulary, and that residual
60 % goes away. **The negative result is stronger here, not weaker.**

There is a control the prototype did not have. The label is a function of the
Boolean skeleton alone, so a classifier given *only* the skeleton is an upper
bound on what any embedding of these formulas could reach. It gets **69.1 %**.
So the ceiling is not 100 %, and the structural embedding recovers roughly a
quarter of the distance from chance to it. What it is failing at is specific:
the skeleton is present in the formula and the embedding largely cannot see it,
because 69 nodes of set.mm statement dominate the seven nodes of connective that
decide the answer.

The proof-graph correlation replicates too. Shortest-path distance in the real
101,790-edge citation graph against structural embedding distance, over 4,096
sampled pairs of theorem statements:

**ρ = 0.030** (p = 0.056, mean path length 4.12)

against the prototype's ρ ≈ 0.013 — the same "no relationship", now measured on a
citation graph rather than a small constructed one. (The local single-layer
import gives ρ = 0.016 on the same measurement; the difference between the two is
noise of the same size as the effect, which is the point.)

### The feature is checked, not assumed

A bag-of-alpha-classes that was subtly wrong — collapsing `φ → φ` into `φ → ψ`,
say — would produce a negative result that said nothing about embeddings. So the
key is validated against the engine's own `alpha_digest`, computed independently
in `app/db/terms_mapping.py` for the "same statement up to variable names" index:
over 8,510 statement roots partitioned into 7,969 alpha classes, **0
disagreements**.

(The comparison is over statement roots, not every row. The engine numbers a
term's free variables from the root of whatever statement it was stored under and
writes that digest onto each subterm row, so a shared subterm's stored digest
depends on which statement interned it first; a root's does not. Reproducing that
check is what caught the first version of the key ignoring a variable's **sort**,
which conflated a wff metavariable with a setvar.)

## Experiment 2 — the Boolean semantic embedding

E(φ) ∈ {-1,+1}^N, coordinate m being φ's truth value under assignment ωₘ to the
generators. One departure from the prototype, forced by scale: with ten
generators it could take **all** 2¹⁰ assignments, and the embedding was the full
Lindenbaum–Tarski/Stone representation of the subalgebra they generate. With
5,696 generators 2ⁿ is not enumerable, so the coordinates are *sampled* — 1,024
of them, matching the prototype's width, plus the distinguished all-true
coordinate, which is kept by construction rather than drawn. Sampling costs
completeness, not correctness: every identity below is coordinatewise, so it
holds on any subset of coordinates.

Every identity is exact — maximum error over 1,000 formula pairs, in integer
arithmetic:

| identity | max error |
|---|---|
| E(¬φ) = −E(φ) | 0 |
| E(φ ∧ ψ) = min(E(φ), E(ψ)) | 0 |
| E(φ ∨ ψ) = max(E(φ), E(ψ)) | 0 |
| E(φ → ψ) = max(−E(φ), E(ψ)) | 0 |
| E(φ ↔ ψ) = E(φ)·E(ψ) | 0 |
| ‖E(φ) − E(ψ)‖² = 4·d_H(E(φ), E(ψ)) | 0 |

And provability at the distinguished coordinate: **100.0 %** over all 24,000
compounds, E\*(φ) = +1 ⟺ ⊢φ and −1 ⟺ ⊢¬φ.

That 100 % should be read for what it is. It is not an empirical finding that got
confirmed at scale — it is the argument in [What is being
classified](#what-is-being-classified), and it could not have come out otherwise.
What running it on 10,177 real theorems establishes is narrower and still worth
having: that the construction survives contact with a real corpus — real
statements, real grammar, thousands of generators instead of ten, spread over
three layers — without the identities degrading, which is not obvious in advance,
since a real corpus contains generators logically related to each other in ways
the construction does not model.

Compressing the exact space into ordinary vectors, over 737 pairs (13 of 750 were
excluded as logically equivalent under every sampled assignment, where a relative
error is undefined):

| dimension | median distance error | 90th percentile | prototype |
|---|---|---|---|
| 8 | 16.2 % | 39.6 % | 14.4 % |
| 32 | 9.3 % | 19.9 % | 8.7 % |
| 64 | 5.3 % | 13.7 % | 7.0 % |
| 128 | 4.1 % | 9.3 % | 5.2 % |
| 256 | 3.5 % | 7.6 % | 4.4 % |

The agreement is expected — Johnson–Lindenstrauss does not care what the
coordinates mean — but it does confirm the sampled 1,024-dimensional space
compresses like the exhaustive one.

## Certifying real theorems, with no proof

The two experiments above classify a fragment built for the purpose. The
question they leave open is whether the space can establish anything the corpus
actually contains — and in the one place where the answer is decidable, it can.

`lindenbaum/certify.py` abstracts a statement into a propositional formula over
**atoms**: the maximal subterms that are not built from connectives. Then a goal
is certified when it is `+1` at the distinguished coordinate of the algebra
generated by earlier theorems — either at *every* coordinate, which makes it a
substitution instance of a tautology and needs no library at all, or at the
all-true one relative to lemmas the corpus has already proved. Both directions
are the soundness argument of Experiment 2, run in the direction a proof
assistant wants: position in the space → proof.

```bash
uv run --with numpy --with scikit-learn \
    python -m experiments.lindenbaum.run_certify --neon-https --out experiments/results
```

The corpus is walked in declaration order, so each theorem is a goal against
exactly what preceded it and then joins the library. Six seconds:

| | |
|---|---|
| premise-free theorems attempted | 5,696 |
| **certified with no proof** | **1,059 (18.6 %)** |
| … by truth table alone | 715 |
| … needing the library | 344, on 1.5 lemmas each |

Whole sections go entirely: *Logical conjunction* 119/119, *Logical disjunction*
72/72, *Abbreviated conjunction and disjunction of three wffs* 184/184, *Logical
equivalence* 49/49, *Logical negation* 34/34, *Mixed connectives* 79/79 — and
40.8 % of *Axiom scheme ax-13*, which is not a propositional section at all. The
certificates that need the library are recognisable as the right ones:
`dfifp2`–`dfifp7` from `df-ifp`, `cador` and `cadan` from `df-cad`, `had0` from
`df-had`, `merco1lem5` from `merco1lem1`.

Four controls, because a certifier that says yes to everything scores well on
that table:

| control | result |
|---|---|
| negations of the 1,059 certified goals | **0** certified |
| known-refutable compounds | **0** of 1,000 certified |
| known-provable compounds | 760 of 1,000 certified |
| negations of the refutable compounds (theorems) | 689 of 1,000 certified |

The two zeroes are the ones that matter: nothing false is ever certified. The
two recall numbers say the fragment is a floor rather than a ceiling.

And the failures say exactly where the ceiling is. Of the 4,637 goals not
reached, **4,257 had no usable lemma at all** — not a lemma that failed to
entail, but no lemma whose atoms the goal even mentions. A lemma is usable here
only when its atoms occur *literally*, so `ax-1` over `ph, ps` is found for a
goal over `ph, ps` and missed for the same goal over `( ch → th )`. The
bottleneck is **instantiation**, not the geometry — which is what
[search-phase1-fingerprint.md](../docs/search-phase1-fingerprint.md) is for, and
this gives that index a metric to be judged by.


## The gap: structure does not predict semantics

The measurement the prototype could not make, and the reason to have run this at
all. The roadmap's first follow-up question was whether **semantic fingerprints
can be approximated from graph structure** — if they can, the exact space can be
reached from syntax and the architecture closes. Two ways of asking:

- **Distance.** Spearman correlation between structural embedding distance and
  semantic Hamming distance, over the same 750 pairs: **ρ = 0.0002** (p = 0.99).
- **Prediction.** Ridge regression from the 526 structural features to 32
  semantic coordinates: **50.9 %** mean per-coordinate accuracy, best coordinate
  52.0 %. Chance.

So on this fragment the two embeddings are not merely different, they are
*unrelated* — knowing what a formula looks like tells you nothing about where it
sits in the Boolean geometry. That is the honest state of the "big missing step".

It is also, on reflection, close to inevitable *for this fragment*, and the
reason bounds what the experiment can conclude. The sampled coordinates assign
each generator an independent random sign, so two generators that are
syntactically similar — or even propositionally equivalent — get uncorrelated
coordinates by construction. The embedding encodes the logical relationships
*among compounds relative to a generator basis*, and deliberately encodes nothing
about the generators themselves. A fragment whose generators are treated as
independent atoms cannot exhibit a structure→semantics correlation, so ρ ≈ 0 here
is evidence about the construction, not yet about mathematics.

Which is the sharp form of the open question. Making it answerable needs
coordinates that are not free — assignments constrained by the theory the
generators actually live in, so that logically related theorems get correlated
coordinates and there is something for structure to predict. That is a different
experiment, and this one is the baseline it would have to beat.

## Proof search: finding steps nobody supplied

Certification proves what a truth table reaches. The remaining question — the
one the whole roadmap is for — is whether a corpus plus a geometry can find
proofs it was never told, several steps deep. `lindenbaum/prover.py` is a
backward prover that tries.

```bash
uv run --with numpy --with scikit-learn python -m experiments.lindenbaum.run_search \
    --out experiments/results --goals 200 --steps 1200 --min-lines 2 \
    --rankers random,frequency,structural,analogy,all
```

The corpus is walked in declaration order and each sampled theorem is handed
**only what preceded it** — no citations, no proof length, nothing from its own
proof. Whatever comes back is re-derived by `checking.py`, which shares nothing
with the search, before it counts.

### What makes it a search

A Metamath rule's premises routinely name variables its conclusion does not.
`syl` concludes `φ → χ` from `φ → ψ` and `ψ → χ`, and **nothing in the goal says
what ψ is** — every use of it invents an intermediate statement. That is the
step that cannot be looked up, and getting it required one specific thing:
solving the *most constrained* subgoal first. Attack `ψ` directly and the prover
unifies an unconstrained variable against the whole library; attack its sibling
first and the sibling determines it. With that ordering `syl` is found at depth 3
in 93 unifications, by exactly set.mm's own route (`mpd` over `a1i`).

### Does the geometry help?

Same goals, same budget (1,200 unifications, breadth 14, depth 5); the only
difference is which lemma the search tries first. `analogy` ranks a candidate by
what the library entries whose *statements* look most like the goal cited in
their own proofs; `all` is that combined with usage frequency and structural
similarity.

| ranker | solved / 200 | multi-step (depth ≥ 2) | depth ≥ 3 | different lemmas from set.mm |
|---|---|---|---|---|
| random | 13 (6.5 %) | 8 | 1 | 13 |
| frequency | 31 (15.5 %) | 26 | 0 | 26 |
| structural | 31 (15.5 %) | 26 | 4 | 23 |
| analogy | 37 (18.5 %) | 32 | 5 | 31 |
| **all** | **42 (21.0 %)** | **37** | **8** | 36 |

Frequency — "try what the library uses most" — is the baseline any premise
selector has to beat, and it more than doubles random. Analogy beats *it* by a
fifth, and the combination is better again. **Every proof counted here verifies**;
the checker rejected none.

Note the last column. Of 42 proofs, 36 use a different set of lemmas than set.mm
does. That is a different *route*, not new mathematics — the prover is shallow
and reaches for whatever high-level lemma the library already had — but it does
mean these are searched proofs rather than recovered ones.

### Held out: theorems beyond the library

The stronger test. A second import runs to 14,000 theorems; goals are drawn from
**position 10,000 onward**, so their statements were never in the searched
library and are largely about arithmetic and cardinality, subjects the first
10,000 theorems barely reach.

| ranker | solved / 200 | multi-step | depth ≥ 3 |
|---|---|---|---|
| frequency | 13 (6.5 %) | 6 | 0 |
| analogy | 18 (9.0 %) | 11 | 0 |
| **all** | **39 (19.5 %)** | **32** | **4** |

The solved theorems' *own* proofs average 7.3 lines, against 3.3 in-corpus — the
prover is finding short routes to statements set.mm reached the long way round.
`gchxpidm`, whose stored proof is 57 lines, comes out at depth 2 from `gchinf`,
`infxpidm2`, `numth3` and `syl2an2r` in 118 unifications.

Two honest deductions from that table. The depth-1 solves — 7 of 39 held out, 5
of 42 in-corpus — are single citations, and several are `ALT`/`OLD` duplicates
(`qexALT` from `qex`, `1lt10OLD` from `1lt10`) where an identical earlier theorem
exists. Finding those is genuinely useful library hygiene and it is not proof
search, so they are counted separately above. And nothing here goes deeper than
three chained rules: this is a shallow prover with a 1,200-unification budget,
not a competitor to a tuned ATP.

### Four bugs the checker caught

Worth recording, because each would have read as a result:

- siblings did not share the substitution from the premise branch, so one
  variable could be bound two ways in a single "proof";
- a variable's sort was compared against a node's, and a declared production's
  node carries no sort in the store — so every binding of a variable to a term
  was refused, `ax-mp` included, and the prover could not do modus ponens;
- hypotheses were closed by equality rather than unification, which is exactly
  what a rule with an undetermined middle term needs;
- children came back in the order the search solved them rather than the order
  the rule listed its premises, and a proof with permuted children verifies
  against the wrong premise.

`$d` is checked twice — before a branch and again after it — because checked only
once up front it passes vacuously, against bindings that do not exist yet. And
the prover refuses its own answer when a variable came out undetermined: that is
Metamath's *dummy variable*, legal only against `$d` obligations this does not
track, so the contract is that a returned proof verifies.

## What stops the other 78 %

A solve rate says how far the prover gets, not what is stopping it, and those
want different fixes. `run_failures.py` runs the same 150 goals three times and
partitions the outcome by what it takes to change it:

1. the combined ranker at the standard budget;
2. an **oracle ranker** — the lemmas the real proof cited, ranked first — at the
   *same* budget. What this adds was lost to **retrieval**;
3. the oracle again at depth 9, width 24, 4,000 steps. What this adds was lost to
   **budget**; what it still cannot reach is **structural**.

| outcome | goals | share |
|---|---|---|
| solved | 33 | 22 % |
| lost to retrieval | 10 | 7 % |
| lost to budget | 1 | 1 % |
| **structural** | **106** | **71 %** |

**Retrieval is 7 % of the gap.** That is the surprise, and it redirects the
effort: a perfect premise selector, at this budget, would take the prover from
22 % to 29 %. Everything else is unreachable *even when the search is told
exactly which lemmas to use*.

### The wall is proof size, not depth and not ranking

| | solved | structural failure |
|---|---|---|
| distinct lemmas the real proof cites | 3.1 mean, 3 median | **12.5 mean, 8 median** |
| stored proof lines | 3 median | 14.6 mean, 9 median |
| stored proof depth | 2 median | 4 median |

44 of the 106 cite ten or more distinct lemmas. Depth is *not* the binding
constraint — 36 of the 106 nest deeper than the standard depth-5 cap, but the
oracle ran at depth 9 and solved one more. What defeats it is **breadth**: a
proof assembled from a dozen different lemmas is a wide conjunction of subgoals,
and iterative deepening with a width cap cannot hold that many partial
commitments at once.

Only 19 of the 106 look small (depth ≤ 3 and ≤ 4 distinct lemmas), and those are
the ones worth reading one at a time. One named mechanism came out of doing so:
**dummy variables** — a proof that must introduce a variable the goal does not
determine. `elisset` (`A ∈ V → ∃x x = A`) is the shape. The prover refuses those
because their `$d` obligations are not tracked, and re-running the 106 with the
refusal lifted turns exactly **3** of them into proofs. A real but small
mechanism, worth fixing for correctness rather than for coverage.

One diagnostic that looks alarming and is not: "cites something outside the
library" fires on 55 of the 106. Every such label is a `$e` hypothesis of the
theorem itself — `mpbii.maj`, `syl3an3.1` — not a missing theorem. The library is
complete.


## Premise selection, and a geometry that is not free

`run_retrieval.py`, six seconds, ground truth already in the database:
`proof_lines.rule` is what each proof actually reached for. Recall@k over 800
goals, each ranked against the library as it stood when the theorem was written:

| ranker | @10 | @50 | @100 | @200 |
|---|---|---|---|---|
| analogy | **13.5 %** | **33.2 %** | **44.0 %** | **56.6 %** |
| structural | 12.9 % | 27.9 % | 35.1 % | 43.0 % |
| frequency | 10.7 % | 22.5 % | 29.6 % | 38.4 % |
| random | 0.6 % | 2.7 % | 5.0 % | 9.7 % |

### The coordinate system that is *not* free

This is the answer to [The gap](#the-gap-structure-does-not-predict-semantics),
and it is the most useful thing in this directory.

The sampled-assignment space gives each generator an independent random sign, so
two propositionally equivalent theorems land in uncorrelated places — which is
why structure predicted nothing about it (ρ = 0.0002). A theorem's **transitive
axiom dependencies** are the opposite kind of coordinate: computable from the
citation DAG, different for theorems that are all equally provable, and not free
at all. Over the 10,176 theorems with a stored statement there are 3,517 distinct
signatures. Asking the same question of them:

| | free Boolean space | axiom-dependency signature |
|---|---|---|
| ρ (structural distance vs. coordinate distance) | 0.0002 | **0.489** (p ≈ 4 × 10⁻²⁴⁰) |
| predicting a coordinate from syntax | 50.9 % (chance) | **74.7 %** vs. 54.5 % majority |

So syntax says almost nothing about where a formula sits in the free Boolean
algebra, and a great deal about **which axioms its proof will need**. The
embedding worth building is over provenance, not over truth values — and Edifyce
already stores everything it needs (`scripts/check_provenance.py` computes the
same closure for its own reasons).

Proof length is weakly visible too: predicting `log` lines from the same features
gives ρ = 0.36, R² = 0.20 — enough to order a search frontier, not enough to
estimate difficulty.


## Layout

| File | What it does |
|---|---|
| `lindenbaum/transport.py` | Rows out of a database, over psycopg or over Neon's SQL-over-HTTP endpoint, keyset-paged |
| `lindenbaum/corpus.py` | Reads terms, theorems, sections and the citation graph — across layers — into dense arrays |
| `lindenbaum/dag.py` | The term arena, and the compositional alpha-invariant key the subtree features are bags of |
| `lindenbaum/formulas.py` | The fragment: Boolean skeletons, and their realisation as wffs over generator statements |
| `lindenbaum/structural.py` | Experiment 1's 526-dimensional embedding |
| `lindenbaum/semantic.py` | Experiment 2's ±1 embedding, the algebra, and the random projection |
| `lindenbaum/certify.py` | Propositional abstraction, and the two sound certificates over it |
| `lindenbaum/unification.py` | The prover's term store: interning, freezing, refreshing, unification, `$d` |
| `lindenbaum/prover.py` | Backward search, the fingerprint index, and the rankers |
| `lindenbaum/checking.py` | An independent re-derivation of a found proof |
| `lindenbaum/run.py` | The embedding experiments; writes `dev-database.json` |
| `lindenbaum/run_certify.py` | The certification walk; writes `certification.json` |
| `lindenbaum/run_search.py` | The proof-search evaluation; writes `search.json` |
| `lindenbaum/run_retrieval.py` | Premise selection and signature geometry; writes `retrieval.json` |
| `lindenbaum/run_failures.py` | The oracle ablation; writes `failures.json` |

Nothing here is imported by `app/` or `website/`, and the suite does not read it
— it is an experiment, kept beside the code it measures rather than inside it.
