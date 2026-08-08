# Could `set.mm` be rewritten with sequents, algorithmically?

A study, not a plan. No code changed; everything below is either a measurement of
`set.mm` as it stands, a quotation from the corpus itself, or an argument clearly
marked as such. It answers two questions asked together:

1. **Could a program rewrite `set.mm` proofs into sequent form?**
2. **Would the result be simpler and more natural?**

The short answers are **mostly yes** and **yes for the library, only conditionally
for the proofs** — and the condition turns out to be the roadmap's one open item,
S4. That is the finding worth carrying: this study is the evidence S4 was said to
be waiting for.

---

## 1. The result that reframes both questions

`set.mm` **has already been rewritten with sequents, by hand.** Not partly, not
by accident — deliberately, documented, and machine-annotated.

The corpus's own preamble says so:

> Theorems can be written in different forms, including "closed form",
> "deduction form", and "inference form" […] for more advanced theorems, **we
> prefer to use the deduction form, since it permits to write proofs in the
> "deduction style"**, and we do not add theorems in inference form unless there
> are reasonable grounds for it.

And a "deduction form" theorem *is* a sequent. Where all of a theorem's
hypotheses and its conclusion share one antecedent `ph`:

```
  hypotheses:  |- ( ph -> A )      |- ( ph -> B )
  conclusion:  |- ( ph -> C )
```

that is exactly the sequent rule `Γ ⊢ A, Γ ⊢ B ⟹ Γ ⊢ C`, with `ph` as the
context and `->` as the turnstile. **98.8%** of `set.mm`'s deduction-form
theorems use the single variable `ph` for that antecedent, so the encoding is
uniform rather than incidental.

More than documentation: `set.mm` carries a **machine-readable** mapping in `$j`
annotations, declaring which token is the turnstile, which builds the context,
and which theorems play each structural role:

```
$( Add support for natural deduction, indicating the constants used to
   indicate implication, context conjunction, and empty context. $)
$j natded_init 'wi' 'wa' 'wtru';
```

So `->` is the turnstile, `/\` builds Γ, and `T.` is the empty context. Dozens of
theorems carry comments of the form *"A translation of natural deduction rule
∧ER"*.

**The question is therefore not whether the translation is possible.** It has
been done. The question is what it cost to do by hand, and what a machine with a
real context sort would do differently.

---

## 2. What the hand-rolled version cost

### 2.1 The structural library

`set.mm` tags **181 theorems** as natural-deduction machinery:

| `$j` annotation | theorems | what it is |
|---|---|---|
| `natded_assume` | 31 | the axiom rule, `Γ ⊢ A` when `A ∈ Γ` |
| `natded_weak` | 63 | weakening |
| `natded_cut` | 34 | cut |
| `natded_true` | 50 | the empty context |
| `natded_init` | 3 | the encoding itself |

In a sequent calculus with a genuine context sort those 31 + 63 + 34 collapse to
**three rules** — axiom, weakening, cut — or fewer, if the context is a set and
the structural rules are admissible.

The reason they do not collapse in `set.mm` is that Γ is not a context. It is a
**conjunction tree inside a wff**, so every position in that tree needs its own
named theorem. The consequence is visible in the names:

```
simp-11l $p |- ( ( ( ( ( ( ( ( ( ( ( ( ph /\ ps ) /\ ch ) /\ th ) /\ ta )
    /\ et ) /\ ze ) /\ si ) /\ rh ) /\ mu ) /\ la ) /\ ka ) -> ph )
```

That is the axiom rule at context depth 12. `set.mm` has `simpl`, `simpr`,
`simpll`, … up to `simp-12l`/`simp-12r`, and `adantl`, `adantr`, … up to
`ad10antlr`. **68 named forms of the axiom rule and 36 of weakening**, indexed by
position and depth.

The contexts really do get that deep. Of the 37,068 statements whose antecedent
can be read as a context:

| \|Γ\| | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| statements | 22,319 | 7,139 | 3,804 | 1,729 | 715 | 392 | 193 | 119 | 126 | 149 | 88 | 295 |

### 2.2 The proof bureaucracy

Counting `(proof, cited label)` pairs over all 47,621 proofs, restricted to
**logical** citations (excluding syntax constructors like `wcel`, which are not
inferences at all — they are 41.5% of raw citations and would flatter every ratio
below):

| family | citations | share of 904,049 |
|---|---|---|
| `syl*` — cut / chaining | 77,415 | 8.6% |
| `simp*` — projection | 50,687 | 5.6% |
| `ad*ant*` — weakening | 38,682 | 4.3% |
| `mp*` — modus ponens | 36,013 | 4.0% |
| `imp*`/`exp*` — deduction theorem | 16,948 | 1.9% |
| `a1*` — weakening (K) | 8,969 | 1.0% |
| **total** | **228,714** | **25.3%** |

A hand-curated list (rather than prefix matching) gives a stricter lower bound of
17.9%.

> **Read this table carefully — it is the one most likely to mislead, and it
> misled me.** These are `(proof, cited label)` pairs: "how many proofs name this
> label at least once". They are not steps, and they are not a prediction of how
> much shorter anything gets. §6 measures actual steps, and the answer there is
> considerably less flattering: two of the families above (`syl*`, `mp*`) are
> real inferences that survive any rewrite, and logical steps are only a sixth of
> a Metamath proof to begin with.

And deduction-form theorems — 3,862 statements, 7.9% of the logical corpus —
account for **23.0% of all logical citations**. The sequent-shaped fragment is
small in the library and dominant in use.

### 2.3 Duplication

**2,965 theorems** (6.0% of the logical corpus) exist as a `d`- or `i`-suffixed
variant of another theorem: `mulcan`/`mulcand`, `normcl`/`normcli`. Some are
genuinely distinct results, but the naming convention exists precisely because
the same mathematics has to be restated per form. That is the tax for the
deduction theorem being a *metatheorem* rather than a rule.

---

## 3. Could a program do the rewrite?

### 3.1 Propositional: yes, and the theory is old

Hilbert-style implicational logic and natural deduction are related by
Curry–Howard, concretely:

| Hilbert | combinator | ND / sequent |
|---|---|---|
| `ax-1`, `⊢ ph → (ps → ph)` | **K** | weakening |
| `ax-2`, `⊢ (ph → (ps → ch)) → ((ph → ps) → (ph → ch))` | **S** | the distribution behind `→R` |
| `ax-mp` | application | `→E` / cut |

A Hilbert propositional proof *is* a combinator term. The translation to a lambda
term (hence to an ND or sequent derivation) is a direct homomorphism —
`K ↦ λxy.x`, `S ↦ λxyz.xz(yz)` — followed by β-normalisation, which terminates
because the terms are simply typed. Mechanical and total.

The direction matters for size. Going the *other* way — ND to Hilbert — is
bracket abstraction, and that is what blows up: eliminating one abstraction can
square the term. This is the formal reason a Hilbert proof of something trivial
is long, and why the inverse translation should shrink. `idALT`, `set.mm`'s
from-the-axioms proof of `ph → ph`, is the textbook case; the corpus itself notes
it is "a popular example in the literature", identical step for step to the
proofs in Margaris, Hamilton, Bell & Machover, and Mendelson. In a sequent
calculus it is the axiom rule: one step.

**Caveat, and it matters.** `set.mm` proofs are not naive bracket-abstraction
output. They are hand-optimised against a library of 47,000 lemmas, so the
theoretical blowup has already been engineered away. The shrink from rewriting
would be far less than worst-case, and I did not measure it — see §5.

### 3.2 The practical route is not combinators

For `set.mm` specifically, the useful algorithm is much simpler and is the one
the community already runs by hand: the **deduction-style translation**. Prefix
every line of a proof with `ph ->`, and replace each cited theorem by its
deduction-form variant. It is a local, syntax-directed rewrite with one
precondition — *the deduction variant of every cited theorem must exist*.

That precondition is where a mechanical run stops. Measured across the corpus,
of cited logical labels not already in deduction form, only 4.2% have a sibling
`<label>d` — 29.8% weighted by citation count. The rest would have to be
generated, which is possible (the `d` form of a theorem is derivable from the
plain form by `a1i` and `syl`) but is exactly the 2,965-variant duplication of
§2.3, mechanised rather than removed.

### 3.3 First-order: yes, but the provisos are load-bearing

The deduction theorem is unrestricted only in propositional logic. At first order
the rule that introduces `∀` carries an eigenvariable condition, and `set.mm`
writes it explicitly:

```
${
  $d x ph $.
  alrimiv.1 $e |- ( ph -> ps ) $.
  alrimiv  $p |- ( ph -> A. x ps ) $.
$}
```

`$d x ph` — *x is not free in the context* — is the sequent calculus's `∀R`
proviso, in a corpus that has no sequents. A rewrite that dropped it would be
unsound.

This is the part Edifyce is already equipped for. A Metamath `$d` imports as a
`disjoint` side condition, and D5 verified that such a proviso still refuses a
capturing instantiation after crossing two layer boundaries — the same machinery
a sequent `∀R` would need. Nothing new is required to carry the condition; what
would be new is the rule that consumes it.

---

## 4. Would the result be simpler? The honest answer

**The library: unambiguously yes.** 181 hand-written structural theorems become
3 rules. `simp-11l`, `ad10antlr` and their 100-odd siblings stop existing. The
2,965 form-variants lose their reason to exist. That is a large, real
simplification, and it is the one `set.mm`'s own authors would recognise, since
they wrote every one of those theorems on purpose.

**The proofs: only if the matcher is associative-commutative.** This is the catch,
and it is worth stating sharply because it inverts the naive expectation.

The roadmap already warns (§6.2) that a syntactic list context is not a set, so
exchange, weakening and contraction must be declared as rules and **cited by
hand**. Under a plain sequent calculus, a proof needing the fifth assumption of
its context cites exchange four times — where `set.mm` today cites `simp-5l`
once. The bureaucracy does not disappear; it is *relocated* from the library into
the proof text, and by the citation count of §2.2 it might well get worse.

`set.mm`'s `simp-11l` is therefore not evidence of a badly designed corpus. It is
what a working library does when it needs an AC context and does not have one:
it pre-computes every position it will need and gives each a name. The 181
theorems are a hand-built substitute for associative-commutative matching.

So the two halves of the answer are:

- rewriting to sequents **with** an AC context sort: simpler library *and*
  simpler proofs;
- rewriting to sequents **without** one: simpler library, and proofs that trade
  `simp-11l` for eleven exchanges.

---

## 5. What this says about S4 — and what I did not do

The roadmap lists **S4** (an associative-commutative matcher for the context
sort) as its only open item, conditional, and records that S3's measurements
removed *performance* as its justification. What remained was ergonomics, and the
roadmap says the evidence should come from "someone actually writing sequent
proofs".

**`set.mm` is that someone.** It is a 47,000-theorem corpus that hand-rolled a
sequent calculus over a conjunction-encoded context, without AC matching, and
paid for it with 181 structural theorems, position-indexed names to depth 12, and
a quarter of its logical citations. That is the strongest ergonomic evidence for
S4 available anywhere, and it was sitting in the corpus already imported.

It does not by itself justify building S4 — Edifyce has no large sequent corpus
of its own, and a rewrite of `set.mm` is not on any track. What it does is settle
the *shape* of the question: S4 is not an optimisation of a sequent calculus, it
is the thing that makes one worth having.

---

## 6. So will the proofs be shorter? Measured

The sections above were written from `(proof, label)` pairs, which invites the
reading "a quarter of every proof is bureaucracy, so proofs get a quarter
shorter". That reading is wrong twice over. This section decodes every compressed
proof into actual steps — computing Metamath frames, so step counts are real —
and the answer is much smaller than §2.2 suggests.

### 6.1 Most of a Metamath proof is not reasoning at all

Across 47,599 proofs, **9,713,929 decoded steps**:

| | steps | share |
|---|---|---|
| formula construction | 8,090,245 | **83.3%** |
| logical inference | 1,623,684 | 16.7% |

The 83.3% is Metamath building the *statements* — `wcel` (∈) alone is 10.5% of
it, then `co` (operations), `cfv` (function value), `wceq` (=), and bare variable
references at 26.2%. Reorganising the logic does not touch any of it: `A e. B`
has to be constructed whether the proof around it is Hilbert or sequent. Only
7.1% of syntax steps are `wa`/`wi` — the connectives that build contexts — so
even generous assumptions about implicit contexts recover little here.

**Whatever a sequent rewrite saves, it is bounded by that remaining 16.7%.**

### 6.2 Of the logical steps, what actually vanishes

Step-weighted, over the 1,623,684 logical steps:

| family | step-weighted | (label-weighted, §2.2) | survives a rewrite? |
|---|---|---|---|
| `syl*` — cut | 10.3% | 8.6% | **yes** — a real inference |
| `ad*ant*`/`a1*` — weakening | 10.2% | 5.3% | no |
| `simp*`/`id` — assumption rule | 6.3% | 5.9% | partly |
| `mp*` — modus ponens | 3.4% | 4.0% | **yes** — a real inference |
| `imp*`/`exp*` — deduction theorem | 1.4% | 1.9% | partly |
| total | 31.5% | 25.6% | |

Step-weighting raises the bureaucracy share from 25.6% to 31.5%, as §5 predicted
it would. But cut and modus ponens are 13.7 of those 31.5 points and they do not
go away — a sequent calculus still has cut. What a real context sort removes is:

- **conservative** (weakening only, which an AC/set context makes free):
  **10.3%** of logical steps;
- **optimistic** (weakening + assumption positioning + deduction-theorem
  shuffling): **15.5%**.

As a share of the *whole* proof, that is **1.7% to 2.6%**.

### 6.3 How many proofs, and by how much

| | conservative | optimistic |
|---|---|---|
| proofs losing ≥1 step | 19,632 (**41.2%**) | 23,737 (**49.9%**) |
| proofs unaffected | 27,967 (58.8%) | 23,862 (50.1%) |
| **median proof, whole corpus** | **0%** | **0%** |
| mean, whole corpus | 5.9% | 10.3% |

**More than half of `set.mm` contains no structural step at all** and would come
out byte-for-byte the same length. The median proof is 12 logical steps; the
median saving across the corpus is zero.

Among the proofs that *are* affected:

| reduction in logical steps | conservative | optimistic |
|---|---|---|
| median | 11.6% | 17.1% |
| mean | 14.2% | 20.5% |
| p90 | 25.3% | 37.5% |
| 0–5% shorter | 14.4% | 7.0% |
| 5–10% | 26.5% | 15.6% |
| 10–20% | 38.3% | 34.9% |
| 20–40% | 16.7% | 33.5% |
| >40% | 4.1% | 9.1% |

### 6.4 The verdict, restated

**No, the majority of proofs will not be shorter.** Roughly half are untouched.
The affected half loses a median 12–17% of its *visible reasoning* steps and
about 2% of its total size. A handful — 4–9% of affected proofs — lose 40% or
more, and those are exactly the deep-context proofs that today spend their steps
on `ad2antrr` and `simp-11l`.

This does not change §4's conclusion, but it relocates it. **The win was never
proof length; it is the library.** 181 structural theorems become 3 rules, 2,965
form-variants lose their reason to exist, and the corpus stops needing a name for
"the eleventh assumption from the left". A quarter of a proof's *reasoning* steps
being bookkeeping is a real cost to a reader even when it is 2% of the file, and
that is the case for sequents — not a shorter corpus.

---

## 7. What I did not do

Stated plainly, because several of the numbers above are easy to over-read:

- **Nothing was implemented.** I measured the corpus and reasoned about the
  algorithms; I did not write a translator or rewrite a single proof. §6 measures
  what a rewrite would *remove*, assuming it removes exactly the structural steps
  and adds nothing. A real translator would add steps back — explicit exchanges
  without an AC matcher (§4), or reconstructed deduction-form variants (§3.2) —
  so **§6's figures are an upper bound on the saving, not an estimate of it.**
- The theoretical size argument in §3.1 remains unmeasured: I did not translate a
  single Hilbert proof through combinators to compare.
- **A backreference counts as one step.** Metamath's `Z` tags share a subproof;
  I count the shared subtree once, which is the right model for proof *effort*
  but understates the fully expanded proof.
- **The family classification is prefix matching**, so it is approximate in both
  directions. The curated lower bound (17.9%) and the prefix sweep (25.3%) are
  given together for that reason.
- **"Deduction form" is a syntactic test** — all hypotheses and the conclusion
  sharing one antecedent. It will catch a few theorems that are not deduction
  forms in intent, and miss forms with a non-uniform context.
- The reader strips comments and tracks `${ $}` scoping for `$e`, but is not a
  validating Metamath parser; it was written for counting, and the statement
  counts it produces (3,004 `$a`, 47,621 `$p`) are the only cross-check it got.

The probes live in the session scratchpad and are not committed; the measurements
above are reproducible from a `set.mm` checkout with a few dozen lines of parsing.
