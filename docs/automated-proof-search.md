# Automated proof search over a stored corpus

This note records what a sequence of experiments established about turning
Edifyce's stored term graph into something that *finds* proofs, and what it
established about the Boolean-algebra idea the work started from. Everything
here was measured against a `set.mm` import — 10,177 theorems, 207,311 interned
subterms, 101,790 citation edges — and the code is in
[`experiments/`](../experiments/README.md), which carries the run instructions
and the raw results. This note is the argument; that README is the lab book.

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
being a representation and starts being a *procedure*.
[`certify.py`](../experiments/lindenbaum/certify.py) abstracts a statement into
a propositional formula over **atoms** — maximal subterms not built from
connectives — and certifies a goal when it is `+1` at the distinguished
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

[`prover.py`](../experiments/lindenbaum/prover.py) is a backward prover: to
prove a goal, find a library theorem whose conclusion unifies with it and recurse
on its premises. Each goal is handed **only what was declared before it** — no
citations, no proof length, nothing from its own proof — and every returned proof
is re-derived by [`checking.py`](../experiments/lindenbaum/checking.py), which
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

A solve rate says how far the prover gets, not what is stopping it.
[`run_failures.py`](../experiments/lindenbaum/run_failures.py) runs the same 150
goals three times — the shipping ranker; an **oracle ranker** that reads the
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
equal. [`quotient.py`](../experiments/lindenbaum/quotient.py) closes that gap — a
premise-free `⊢ A ↔ B` is a licence to rewrite one side into the other inside any
propositional context, so the closer computes modulo the biconditionals already
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


## 7. What to build next

Ordered by what §4 measured, not by what is most interesting.

1. **Quantifier handling in the closer.** Where the quotient's reach ends, and
   now the clearest bound: most of set.mm's biconditionals characterise one
   notion in terms of another *under a quantifier*, and `∀` is not a connective
   this algebra has. A closer that treated `∀`/`∃` as more than opaque — even
   just prenex handling and instantiation of a bound variable by a term already
   in the problem — would unlock the `dfss2`-shaped rewrites the current
   productivity test correctly refuses.
2. **Congruence closure over `wceq`/`wcel`, as a second closer.** The held-out
   goals are about equalities between opaque terms, and EUF is the same move one
   level down: quotient the *term* algebra by the equations the corpus proves.
3. **Forward saturation meeting the backward search.** The direct answer to a
   breadth wall: backward chaining commits to a decomposition, while a 12-lemma
   proof wants facts assembled bottom-up. Metamath proofs are natively forward,
   so this matches the corpus's grain. The algebra supplies the *subsumption
   order* a saturation loop needs — `φ ≤ ψ` iff the closer proves `φ → ψ` — which
   is the lattice structure the experiments so far used only the top element of.
4. **Macro steps mined from the citation DAG.** set.mm's proofs are mostly glue —
   `syl`, `ax-mp`, `bitri`, `adantr`, `imp`/`ex`. Compiling the frequent motifs
   into single steps collapses exactly the failing cases, and the mining is a
   query over rows already stored.
5. **Deduction/inference normalisation.** Half the failures carry hypotheses, and
   set.mm systematically pairs `⊢ φ → ψ` with an inference form. Converting
   between them by rewriting rather than by search removes a class of branching.
6. **Best-first search with a learned cost**, replacing iterative deepening,
   which re-does work every round and cannot prioritise across branches.
7. **A learned premise selector.** Worth doing; worth not doing first, since the
   oracle bounds its payoff at 7 points and §6 already collected them.
8. **Expanding a `$taut` step into kernel-checkable Metamath**, so a found proof
   is a proof rather than a proof with a certified gap.
9. **Dummy-variable support**, for correctness rather than coverage.

## 8. Reproducing

See [`experiments/README.md`](../experiments/README.md). Everything runs against
a Metamath import in any migrated database, reads the corpus over psycopg or over
Neon's SQL-over-HTTP endpoint, and brings `numpy`/`scikit-learn` in with
`uv run --with` rather than adding them to the project. Nothing under
`experiments/` is imported by `app/` or `website/`, and the test suite does not
read it.
