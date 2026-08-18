# Automated proof search over a stored corpus

**Status: this note is the deliverable. The code that produced it was a spike and
is deliberately not part of this repository.** It lived under `experiments/` on a
throwaway branch, imported by nothing in `app/` or `website/` and read by no
test, and was not merged. Nothing below depends on it: the numbers are recorded
here rather than only in the runs that produced them, and §8 says which parts
would earn a proper implementation and which were scaffolding.

This note records what a sequence of experiments established about turning
Edifyce's stored term graph into something that *finds* proofs, and what it
established about the Boolean-algebra idea the work started from. Everything here
was measured against a `set.mm` import — 10,177 theorems, 207,311 interned
subterms, 101,790 citation edges — with a second import to 14,000 used for
held-out goals.

## Results at a glance

Proof search over 200 sampled goals, each handed only what the corpus had
declared before it, every returned proof independently re-derived:

| configuration | in-corpus | held out (positions 10k–14k) |
|---|---|---|
| backward search, best ranking | 42 (21.0 %) | 39 (19.5 %) |
| + Boolean closer | 58 (29.0 %) | 42 (21.0 %) |
| + closer computing modulo proved equivalences | **63 (31.5 %)** | **44 (22.0 %)** |
| the same search with a *random* ranking, no closer | 13 (6.5 %) | — |

And the three measurements that should outlive the rest:

| question | answer |
|---|---|
| does syntax predict a formula's truth? | no — ρ = 0.0002, classifiers at chance |
| does syntax predict which **axioms** its proof needs? | yes — ρ = 0.489, 74.7 % vs 54.5 % baseline |
| what stops the unsolved goals? | not retrieval (7 %) and not depth (1 %) — **71 % is proof breadth** |

The through-line, stated up front because it inverts the order the work was
done in:

> **Syntax predicts almost nothing about a formula's truth, a great deal about
> which axioms its proof will need, and enough about which lemmas a proof will
> cite to nearly triple a proof search's yield. The binding constraint on the
> search is neither ranking nor depth — it is the number of distinct lemmas a
> proof has to assemble, and the Boolean algebra earns its place by collapsing
> whole runs of them into one step.**

---

## 1. The Boolean embedding, and what it is really an algebra of

The starting idea: embed a formula not by what it looks like but by its truth
value under assignments to known theorems, `E(φ) ∈ {-1,+1}^N`. Then the
connectives become exact coordinatewise operations and one distinguished
coordinate — the assignment making every generator true — decides provability.

Both halves replicate at corpus scale. Every algebraic identity is exact in
integer arithmetic (max error 0 over 1,000 formula pairs) and the distinguished
coordinate classifies all 24,000 compounds correctly. But that 100 % is a
theorem, not a measurement: if every `Aᵢ` is provable and `f(A₁…Aₙ)` is true when
all of them are, then `(A₁ ∧ … ∧ Aₙ) → f` is a propositional tautology whose
antecedent the corpus proves. It could not have come out otherwise.

The load-bearing observation is about *which* algebra this is. Taking every
assignment means the generators are treated as logically independent, so the
space is the **free** Boolean algebra on them — equivalently, the
Lindenbaum–Tarski algebra of the *empty* theory. The Lindenbaum–Tarski algebra
of ZFC is the opposite extreme: it quotients by provable equivalence, and there
every theorem is `⊤`. All 10,177 of them are one point.

That settles three things at once:

* the algebra is exact because a free Boolean algebra's operations are its
  operations — nothing could have gone wrong;
* "proof search as movement toward `1`" is degenerate, because in the algebra
  where distance would mean something everything provable is already there;
* and structural similarity cannot predict position in the free space, because
  free generators are uncorrelated *by construction* — two propositionally
  equivalent theorems get independent coordinates.

Measured: Spearman ρ between structural embedding distance and semantic Hamming
distance is **0.0002**; predicting a coordinate from syntax gives **50.9 %**,
which is chance. A 526-dimensional structural embedding classifies provability
on held-out axiom families at **55.4 / 53.7 / 50.8 %** (linear / RBF SVM /
nearest neighbour) against a skeleton-only ceiling of 69.1 %.

**The useful object is neither extreme. It is a quotient by a partial theory** —
and the rest of this note is two instances of that idea, one that discharges
goals and one that ranks lemmas.

## 2. The algebra as a decision procedure

Quotient by "propositional consequence of the library" and the algebra stops
being a representation and starts being a *procedure*. The certifier abstracts a
statement into a propositional formula over **atoms** — the maximal subterms not
built from connectives — and certifies a goal when it is `+1` at the distinguished
coordinate of the algebra earlier theorems generate: either at every coordinate
(a tautology instance, no library needed) or at the all-true one relative to
lemmas already proved.

Walking the corpus in declaration order, six seconds:

| | |
|---|---|
| premise-free theorems attempted | 5,696 |
| certified with no proof | **1,059 (18.6 %)** |
| … by truth table alone | 715 |
| … needing the library | 344, on 1.5 lemmas each |

Whole sections go entirely — *Logical conjunction* 119/119, *Logical
disjunction* 72/72 — and the library-backed certificates are the right ones:
`dfifp2`–`dfifp7` from `df-ifp`, `had0` from `df-had`.

Soundness is checked in both directions. Negations of all 1,059 certified goals:
**0** certified. Known-refutable compounds: **0** of 1,000. And the failures
locate the ceiling exactly — of 4,637 goals not reached, **4,257 had no usable
lemma at all**, because a lemma is usable here only when its atoms occur
*literally*. The bottleneck is instantiation, not the geometry.

## 3. Proof search

The prover chains backwards: to prove a goal, find a library theorem whose
conclusion unifies with it and recurse on its premises. Each goal is handed **only
what was declared before it** — no citations, no proof length, nothing from its
own proof — and every returned proof is re-derived by an independent checker that
shares nothing with the search.

What makes this a search rather than a lookup is that a Metamath rule's premises
routinely name variables its conclusion does not. `syl` concludes `φ → χ` from
`φ → ψ` and `ψ → χ`, and **nothing in the goal says what ψ is** — every use
invents an intermediate statement. The decisive implementation choice is to solve
the *most constrained* subgoal first: attack ψ directly and the prover unifies an
unconstrained variable against the whole library; attack its sibling and the
sibling determines it. With that ordering `syl` is found at depth 3 in 93
unifications, by set.mm's own route (`mpd` over `a1i`).

### Does the ranking matter?

Same 200 goals, same budget; only the order candidates are tried in varies.
`analogy` ranks a candidate by what the library entries whose *statements* look
most like the goal cited in their own proofs.

| ranker | solved / 200 | multi-step | ≥3 chained |
|---|---|---|---|
| random | 13 (6.5 %) | 8 | 1 |
| frequency | 31 (15.5 %) | 26 | 0 |
| structural | 31 (15.5 %) | 26 | 4 |
| analogy | 37 (18.5 %) | 32 | 5 |
| **all** | **42 (21.0 %)** | **37** | **8** |

Held out is the stronger test: a second import runs to 14,000 theorems and goals
are drawn from position 10,000 onward, so their statements were never in the
searched library. The combined ranker solves **39/200 (19.5 %)**, 32 of them
multi-step, and the solved theorems' *own* proofs average 7.3 lines against 3.3
in-corpus — short routes to statements set.mm reached the long way. `gchxpidm`,
57 lines in set.mm, comes out at depth 2 in 118 unifications.

36 of the 42 in-corpus proofs use a different set of lemmas than set.mm does.
That is a different *route*, not new mathematics.

### Four bugs the independent checker caught

Recorded because each would have read as a result: siblings not sharing the
substitution from the premise branch (one variable bound two ways in a single
"proof"); a variable's sort compared against a node's, which carries no sort for
a declared production — this refused every binding of a variable to a term,
`ax-mp` included; hypotheses closed by equality rather than unification, which is
exactly what a rule with an undetermined middle term needs; and children returned
in the order the search solved them rather than the order the rule listed its
premises. `$d` is checked twice, before a branch and again after, because checked
once up front it passes vacuously against bindings that do not exist yet.

## 4. What stops the rest

A solve rate says how far the prover gets, not what is stopping it. An oracle
ablation runs the same 150 goals three times — the shipping ranker; an **oracle ranker** that reads the
goal's own proof and puts its lemmas first, at the same budget; and the oracle
again at depth 9, width 24, 4,000 steps — and each run's marginal solves name a
cause.

| outcome | goals | share |
|---|---|---|
| solved | 33 | 22 % |
| lost to **retrieval** | 10 | 7 % |
| lost to **budget** | 1 | 1 % |
| lost to **structure** | **106** | **71 %** |

**Retrieval is 7 % of the gap.** A perfect premise selector at this budget takes
the prover from 22 % to 29 %; everything else is unreachable even when the search
is handed exactly the lemmas the real proof used. This is the most decision-
relevant number in the whole sequence, and it points away from where the effort
would naturally have gone.

### The wall is breadth

| | solved | structural failure |
|---|---|---|
| distinct lemmas the real proof cites | 3.1 mean / 3 median | **12.5 mean / 8 median** |
| stored proof lines | 3 median | 14.6 mean / 9 median |
| stored proof depth | 2 median | 4 median |

44 of the 106 cite ten or more distinct lemmas. Depth is *not* binding: 36 of the
106 nest deeper than the depth-5 cap, and raising it to 9 solved one more. What
defeats the search is holding a dozen partial commitments open at once.

Only 19 of the 106 look small (depth ≤ 3, ≤ 4 distinct lemmas). Reading those
named one mechanism: **dummy variables**, a proof that must introduce a variable
the goal does not determine (`elisset`: `A ∈ V → ∃x x = A`). Lifting the prover's
refusal turns exactly **3** of the 106 into proofs — real, worth fixing for
correctness, not a coverage lever.

One diagnostic that looks alarming and is not: the 55 failures that "cite
something outside the library" are citing their own `$e` hypothesis labels
(`mpbii.maj`, `syl3an3.1`), not a missing theorem.

## 5. Provenance is the coordinate system that works

The free Boolean space fails to be predictable from syntax because its
generators are independent by construction. A theorem's **transitive axiom
dependencies** are the opposite kind of coordinate: computable from the citation
DAG, different for theorems that are all equally provable (3,517 distinct
signatures over 10,176 theorems), and not free at all. The same question, asked
of both:

| | free Boolean space | axiom-dependency signature |
|---|---|---|
| ρ (structural distance vs. coordinate distance) | 0.0002 | **0.489** (p ≈ 4 × 10⁻²⁴⁰) |
| coordinate predicted from syntax | 50.9 % (chance) | **74.7 %** vs. 54.5 % majority |

Syntax says nothing about where a formula sits among truth values and a great
deal about **which axioms its proof will need**. Anything embedding-shaped that
Edifyce builds should be over provenance, not over truth —
`scripts/check_provenance.py` already computes the same closure for its own
reasons. Proof length is weakly visible too (ρ = 0.36, R² = 0.20): enough to
order a search frontier, not to estimate difficulty.

Premise-selection recall@k, ground truth being what each proof actually cited:

| ranker | @10 | @50 | @100 | @200 |
|---|---|---|---|---|
| analogy | **13.5 %** | **33.2 %** | **44.0 %** | **56.6 %** |
| structural | 12.9 % | 27.9 % | 35.1 % | 43.0 % |
| frequency | 10.7 % | 22.5 % | 29.6 % | 38.4 % |
| random | 0.6 % | 2.7 % | 5.0 % | 9.7 % |

## 6. The algebra as a closer — the largest single gain measured

Sections 1–5 leave the Boolean construction looking like a nice representation
theorem with one practical spin-off. That reading was wrong, and the correction
is the most useful result here.

§4 says the wall is the *number of distinct lemmas* a proof must assemble, and
most of what inflates that number in set.mm is propositional glue — `syl`, `imp`,
`ex`, `adantr`, `3anbi`. Those are exactly what the algebra of §2 decides. So the
certifier was wired into the prover as a **closer**: a subgoal closes outright
when the theorem's hypotheses propositionally entail it, `E*(φ) = +1` in the
algebra those hypotheses generate. The step is labelled `$taut`, and
`checking.py` re-decides it rather than taking it on trust.

Same 200 goals, same budget, the only change being whether the closer is on:

| ranker | search alone | with the algebra |
|---|---|---|
| random | 13 (6.5 %) | **37 (18.5 %)** |
| frequency | 31 (15.5 %) | 51 (25.5 %) |
| analogy | 37 (18.5 %) | 55 (27.5 %) |
| **all** | 42 (21.0 %) | **58 (29.0 %)** |

Two things to read off. The combined ranker gains **8 points**, which is as much
as §4's oracle ablation said a *perfect* premise selector would be worth — except
this is a computable procedure rather than an oracle, and the two are largely
complementary. And the closer with a **random** ranker (18.5 %) nearly matches
the best ranker without it (21.0 %): on this corpus the algebra contributes more
than the ranking does.

`mercolem5` (10 lines in set.mm), `pm5.71` (7 lines) and `syl112anc` (7 lines)
each collapse to a single `$taut` step; `imaeqalov` (21 lines) comes out as one
propositional step plus three real lemmas. Depth counts are not comparable across
the two columns for exactly this reason — the closer turns what was a deep chain
into one step.

### Quotienting the atoms by proved equivalence

§1 argued the useful algebra is a quotient by a *partial* theory. The closer as
first built quotients by nothing: its atoms are the maximal subterms whose head
is not a connective, and two atoms are the same only if structurally identical.
`A ≠ B` and `¬(A = B)` are two different atoms to it, and the corpus proves them
equal. Quotienting closes that gap: a premise-free `⊢ A ↔ B` is a licence to
rewrite one side into the other inside any propositional context, so the closer computes modulo the biconditionals already
established.

**Which rewrites to allow is the entire result.** The obvious test — take a
rewrite that *introduces a connective*, since the point is to reveal structure —
is wrong, and wrong in a way that looks right. Both directions of `df-ne` get
recorded, so the atom `A = B` is rewritten to `¬(A ≠ B)`: a connective appears, a
new opaque atom replaces the old one, and the truth table now ranges over twice
the vocabulary for no gain. That test fired on **94.6 %** of held-out goals and
bought **nothing** — 41/200 against 42/200 without it.

The test that works asks whether the expansion leaves the problem *less* opaque.
Every atom the expansion introduces must either be **strictly smaller** than what
was expanded — a definitional unfolding like `df-ifp`, which trades
`if(φ, ψ, χ)` for its three components — or **already be an atom of this
problem**, which is what makes `A ≠ B → ¬(A = B)` worth doing exactly when
`A = B` is present and pointless when it is not. The second clause is a property
of the problem rather than of the term, so abstraction becomes two passes: one to
learn which atoms the goal and its hypotheses already have, one to rewrite under
that knowledge. Both clauses are well-founded, so the walk terminates on its own.

It then fires on 16.8 % of held-out goals, and the rewrites it picks are the ones
a person would: `eqss` (`A = B ↔ A ⊆ B ∧ B ⊆ A`), `sspss`, `df-f`, `elpwb`,
`19.21v`.

| ranker | search alone | + closer | + closer + quotient |
|---|---|---|---|
| frequency | 31 (15.5 %) | 51 (25.5 %) | 52 (26.0 %) |
| analogy | 37 (18.5 %) | 55 (27.5 %) | 59 (29.5 %) |
| **all** | 42 (21.0 %) | 58 (29.0 %) | **63 (31.5 %)** |

Held out beyond the 10k: **42 → 44** of 200. Modest, consistent across rankers,
and it moves the needle in the domain where the plain closer was weakest.
`unssd` now closes in a single step; `cdeqeq` and `cdeqal` in three.

The gain is smaller than the closer's own eight points, and the reason is worth
stating: an equivalence only helps when the *other* side is propositionally
useful, and most of set.mm's biconditionals characterise one opaque notion in
terms of another opaque notion under a quantifier. `dfss2` turns `A ⊆ B` into
`∀x(x ∈ A → x ∈ B)`, and `∀` is not a connective this algebra has — so the whole
thing is one atom again and the rewrite is correctly refused. Reaching those
wants quantifier handling, not a better quotient.


**Its reach is domain-bound, and that bound is the next thing to attack.** On
held-out goals beyond the 10k — arithmetic and cardinality, where the atoms are
opaque to a propositional abstraction — the closer adds only 1.5 points
(39 → 42 of 200), and just 2 of the 20 hardest solved use it at all. What those
goals want is not more Boolean structure but a theory of *equality*.

One caveat on the proof object: a `$taut` step is not a Metamath step. It asserts
that a propositional derivation exists, which is decidable and which the checker
re-decides, but expanding it into `ax-1`/`ax-2`/`ax-3`/`ax-mp` is work the prover
does not yet do. As a macro step for search that is the right trade; as a proof
Edifyce's kernel would accept it still needs expanding.


## 7. The programme this points at

Ordered by expected value per unit of effort, not by interest. Nothing here has
been run; the predictions are stated so they can be falsified.

**Two framing corrections first, because they change what is worth building.**

The first 10 000 theorems of set.mm are the *easy* part — propositional and
predicate calculus and elementary set theory. The held-out drop (31.5 % → 22.0 %)
is the first sign of the cliff, and those goals are still elementary arithmetic
rather than research mathematics. Any figure tuned on the prefix overstates. The
primary benchmark should move to a tail split as soon as a larger import exists.

And "generate candidate statements and score them" is the right instinct with the
wrong generator. Forward inference over a 10 000-lemma library has an enormous
branching factor, and random generation is how saturation provers drown. Three
*non-random* sources of the same thing are already available, and the best of
them is sitting in the database: **`proof_lines` holds ~125 632 intermediate
statements**, and for a premise-free theorem every line of its proof is itself a
closed theorem — true by construction, and useful by construction because it
appeared in a real proof. That is a library expansion from ~10 000 facts to
~70 000, for free, from stored rows.

| # | Experiment | What it tests | Effort | Prediction |
|---|---|---|---|---|
| E1 | Add premise-free theorems' stored proof lines as library facts | Does breadth collapse when the stepping stones already exist? | M | Largest single gain; expect premise-selection recall to *fall* — measure both |
| E2 | Premise-set iterative deepening: run at top-32, then 64, 128, 256 | Exploits the measured recall curve; Sledgehammer's trick | S | +5–8 points for very little work |
| E3 | Macro steps mined as frequent connected subgraphs of the proof DAG | Halves effective depth; attacks the 26 % of proofs nesting past the cap | M | +5–10 points |
| E4 | Replace the closer's binary test with a **measure** (below) and iterative deepening with best-first | Gives the search a gradient at all | M | Prerequisite for E5/E6 more than a gain itself |
| E5 | Bidirectional: forward saturation over the retrieved premises, with subsumption, meeting the backward frontier | The direct answer to breadth | L | Biggest structural win, biggest risk |
| E6 | Learned selection (gradient boosting over hand features) | Non-LLM guidance; ground truth is already stored | M | +5–10 points, needs E4's features |
| E7 | Quantifier handling in the closer | Unlocks the `dfss2`-shaped rewrites §6 correctly refuses | M | The measured block on the quotient |
| E8 | Cache subgoals left by failed searches and re-attempt them across goals | Stepping stones, targeted rather than random | S | Modest alone; compounds with E1 |
| E9 | Portfolio: three configurations at a third of the budget each | Cheap ensemble — different rankers solve different goals | S | +3–5 points; check solved-set overlap first |

### The algebra adjustment the search actually wants

The closer asks a **binary** question: is `⋀H → G` equal to `⊤`? A search does not
need that; it needs *how far from* `⊤`. Over the shared atoms, count the
assignments that satisfy the assumptions and falsify the goal:

```
remaining(H, G) = |{ω : ⋀H(ω) = 1 and G(ω) = 0}|
```

It is zero exactly when the closer fires, it decreases monotonically as facts are
added, and it is read off the truth table already being built. In the algebra's
own terms: stop reading the top element and start reading the **measure of the
interval**. That is what turns §6's decision procedure into a heuristic a
best-first search can descend, and it is the natural next move from the framing
in §1 — the same machinery also gives **subsumption** (a derived fact is
redundant when the kept set entails it, which is what stops saturation drowning)
and a **sound pruning rule** (if the hypotheses entail a subgoal's negation, that
branch is dead).

### Evaluation protocol, which has to change first

None of the above means much measured the way §3 measured it:

* move the primary benchmark off the first 10 000 theorems;
* report by difficulty band (2–3, 4–7, 8–15, 16+ stored proof lines) — a headline
  rate hides that the solved goals average 3.3 lines and the failures 14.6;
* exclude `ALT`/`OLD` duplicate variants from the headline, or report them apart;
  7 of 39 held-out solves were single citations of an identical earlier theorem;
* compare at equal budget (solved against unifications spent), so extra machinery
  is not credited with what a larger budget would have bought anyway;
* **re-run the failure partition after E1.** Retrieval was 7 % of the gap *at
  10 000 facts*. At 70 000, or at research scale, that share should be expected to
  grow, and it is the number that keeps the effort pointed at the real
  constraint.

### What would count as success

Being blunt: published non-LLM systems on corpora of this kind have historically
landed in the 10–20 % range, and the strongest published set.mm results came from
LLM-based provers. 31.5 % on the easy prefix is a respectable non-LLM baseline
rather than a near miss on a solved problem. The programme above is what maximises
the chance of a large move; it is not a plan that arrives at 90 % by construction.

## 8. What is worth keeping, and what was scaffolding

The spike is throwaway. These are the parts that would earn a proper
implementation, in the codebase rather than beside it:

* **The propositional closer.** The largest single measured gain, it decides a
  question Edifyce can already ask of its own rows, and its output is a
  *certificate a checker re-decides* rather than something to be trusted. It
  belongs behind the authoring loop as a "this step follows" service — and it must
  expand its `$taut` into `ax-1`/`ax-2`/`ax-3`/`ax-mp` before the kernel would
  take the result, which the spike never did.
* **The equivalence quotient, and specifically its productivity test.** The idea
  is one line; the test is the result. "Rewrite when it introduces a connective"
  fires on 94.6 % of goals and buys nothing. "Rewrite only when every atom left
  behind is strictly smaller, or already an atom of this problem" fires on 16.8 %
  and is worth 5 points. Anyone reimplementing this will reach for the first test.
* **Provenance as the coordinate system.** ρ = 0.489 against ρ = 0.0002 for truth
  values. Any embedding-shaped thing Edifyce builds should be over axiom
  dependencies, and `scripts/check_provenance.py` already computes the closure.
* **Analogy premise selection** — rank a candidate by what the library entries
  whose statements resemble the goal cited in *their* proofs. Recall@100 of 44.0 %
  against 29.6 % for usage frequency, over ground truth that is already stored.
* **The independent checker.** Not an optional extra: it caught four distinct
  classes of bug, every one of which would have been reported as a result. A
  search that grades its own homework is not measuring anything.

Scaffolding, of no further interest: the corpus reader and its two transports,
the term arena and its release discipline, the fingerprint prefilter (the engine
already has `website/logical/fingerprint.py`, which is better), the vectorised
rankers, and every runner script. All of it existed to get numbers out of a
database quickly and none of it is the right shape for the engine.

Three things a reimplementation should not have to rediscover:

* a Metamath rule's premises routinely name variables its conclusion does not, so
  **the most constrained subgoal must be solved first** — that single ordering is
  the difference between finding modus ponens and never finding it;
* `$d` has to be checked **twice**, before a branch and again after it, because
  checked once up front it passes vacuously against bindings that do not exist
  yet;
* a proof that leaves a variable undetermined is Metamath's *dummy variable*, and
  is only legal against `$d` obligations a naive search does not track. Refusing
  to return one is the honest default; it costs about 3 goals in 106.
