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

## Layout

| File | What it does |
|---|---|
| `lindenbaum/transport.py` | Rows out of a database, over psycopg or over Neon's SQL-over-HTTP endpoint, keyset-paged |
| `lindenbaum/corpus.py` | Reads terms, theorems, sections and the citation graph — across layers — into dense arrays |
| `lindenbaum/dag.py` | The term arena, and the compositional alpha-invariant key the subtree features are bags of |
| `lindenbaum/formulas.py` | The fragment: Boolean skeletons, and their realisation as wffs over generator statements |
| `lindenbaum/structural.py` | Experiment 1's 526-dimensional embedding |
| `lindenbaum/semantic.py` | Experiment 2's ±1 embedding, the algebra, and the random projection |
| `lindenbaum/run.py` | The driver; writes `results.json` |

Nothing here is imported by `app/` or `website/`, and the suite does not read it
— it is an experiment, kept beside the code it measures rather than inside it.
