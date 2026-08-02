# Raising imported proofs to human altitude: analysis and recommendations

**Status:** review and recommendation. **No engine changes.** This note measures
where a `set.mm` proof's lines actually go, and recommends which of Edifyce's
existing mechanisms to point at them, in what order. It is the design half of the
metamath roadmap's **Tier B** ([metamath-import-roadmap.md](metamath-import-roadmap.md)
§5), written after the import reached 100% so the question can be settled on the
corpus rather than on intuition.

It has one dependency worth stating up front: the recommended first cut is
*already buildable* on what
[system-relationships-roadmap.md](system-relationships-roadmap.md) delivered in
R1/R2, and does not need R4, S1 or S2. Where it does touch that work, §7 says so.

---

## 1. The specimen, measured rather than described

The metamath roadmap §2.1 says `sqrt2irr` is "a few hundred primitive steps citing
roughly ninety distinct prior theorems". That was an estimate. Run through
`import_proof` against the real `set.mm`, the numbers are:

| | Metamath stored steps | distinct labels cited | Edifyce lines emitted |
|---|---|---|---|
| `sqrt2re` | 4 | 4 | **3** |
| `sqrt2irrlem` (the core) | 282 | 48 | **48** |
| `sqrt2irr` | 623 | 98 | **94** |
| whole corpus | — | — | **1,482,010** over 47,617 proofs (31.1 each) |

So the import is already doing better than §2.1 implies — the roadmap's estimate
of "a few hundred steps citing roughly ninety distinct theorems" is right about
`sqrt2irr`'s stored form (623 and 98) — but **about 85% of those steps emit no
proof line at all**, overwhelmingly because they are well-formedness (§2.5) and
Edifyce parses instead of proving it. 48 lines is not a few
hundred. It is still about six times what a mathematician writes.

Here is `sqrt2irrlem` exactly as the importer emits it, because the argument below
is about *these* lines:

```
 1  ( ph -> 2 e. CC )                                       [2cnd]
 2  ( ph -> ( ( sqrt ` 2 ) ^ 2 ) = 2 )                      [sqsqrtd, 1]
 3  ( ph -> ( sqrt ` 2 ) = ( A / B ) )                      [sqrt2irrlem.3]
 4  ( ph -> ( ( sqrt ` 2 ) ^ 2 ) = ( ( A / B ) ^ 2 ) )      [oveq1d, 3]
 5  ( ph -> 2 = ( ( A / B ) ^ 2 ) )                         [eqtr3d, 2, 4]
 6  ( ph -> A e. ZZ )                                       [sqrt2irrlem.1]
 7  ( ph -> A e. CC )                                       [zcnd, 6]
 8  ( ph -> B e. NN )                                       [sqrt2irrlem.2]
 9  ( ph -> B e. CC )                                       [nncnd, 8]
10  ( ph -> B =/= 0 )                                       [nnne0d, 8]
11  ( ph -> ( ( A / B ) ^ 2 ) = ( ( A ^ 2 ) / ( B ^ 2 ) ) ) [sqdivd, 7, 9, 10]
12  ( ph -> 2 = ( ( A ^ 2 ) / ( B ^ 2 ) ) )                 [eqtrd, 5, 11]
…
48  ( ph -> ( ( A / 2 ) e. ZZ /\ ( B / 2 ) e. NN ) )        [jca, 29, 47]
```

Read it and the shape is immediate. Line 1 is a typing fact. Lines 4, 5 are one
rewrite spelled as congruence-then-transitivity. Lines 7, 9, 10, 14–17, 21, 22,
40–42 are closure obligations. Every single line carries `( ph -> … )`, which is
not part of what is being said.

The mathematical content is six or seven steps: `2 = (A/B)²`, so `2B² = A²`, so
`A²/2 = B² ∈ ℕ`, so `A/2 ∈ ℤ` by `zesq`, so `(A/2)² = B²/2`, which is therefore a
positive integer, so `B/2 ∈ ℕ` by `nnesq`.

---

## 2. Where the 1.48 million lines go

Every logical `$p` in `set.mm` decoded, every emitted line classified. The
classification is priority-ordered — a line is counted once, in the first
category it matches — so the categories are disjoint and the total is exact.

| | lines | share |
|---|---|---|
| 1. natural-deduction context bookkeeping | 279,858 | **18.9%** |
| 2. congruence by argument position | 169,959 | **11.5%** |
| 3. transitivity / rewrite glue | 82,651 | **5.6%** |
| 4. well-formedness and freeness bookkeeping | 78,707 | **5.3%** |
| 5. closure / typing obligations | 440,678 | **29.7%** |
| 6. mathematical content (residue) | 430,157 | 29.0% |
| | | **71.0% mechanical** |

Two independent cross-checks, neither of which reads a label name, both of which
agree:

- **74.5% of all lines are in deduction form** — the formula is
  `( antecedent -> consequent )` — and **40.6% of all formula text in the whole
  corpus is that antecedent**, plus the brackets and arrow that carry it — 53 MB
  of 131 MB of formula text saying nothing except "still under the same
  hypothesis".
- **18.2% of all lines prove a consequent that is character-identical to a
  consequent already proved on a line they cite.** Only the antecedent changed.
  That is `adantr`/`ad2antrr`/`simpr` measured without knowing those labels exist,
  and it lands within a point of category 1.

**How categories 1–3 are decided, and why it is not our guesswork.** `set.mm`
carries `$j` annotations that name, by hand, which of its theorems realise each
natural-deduction rule:

```
$j natded_assume 'id' 'simpl' 'simpr' 'simpll' 'simplr' … ;
   natded_weak   'a1i' 'adantl' 'adantr' 'adantll' … 'ancoms' 'anassrs' … ;
   natded_cut    'mp2b' 'mp1i' 'syl' '3syl' 'syldan' 'sylan' 'syl2anc' … ;
   natded_imp 'wi' with 'ex' 'imp' 'mpd' 'ax-mp' 'syl' 'mpi' ;
   natded_and 'wa' with 'jca' 'pm3.2i' … ;  natded_or … ;  natded_not … ;
   congruence 'notbii' ; congruence 'imbi12i' ; congruence 'albii' ;
   equality 'wceq' from 'eqid' 'eqcomi' 'eqtri' ;
```

Category 1 is exactly the union of the `natded_*` label sets, transcribed. This
is the same situation the roadmap already met twice — `$j definition 'dfbi1' for
'wb'` for the `df-bi` restatement, and the absence of usable `$j free_var` data
for binding slots. The lesson recorded there holds again: **the declaration
exists upstream; read it, do not infer it.** Categories 2 and 3 are matched by
label-name family (`oveq1d`, `fveq2d`, `eqtrd`, `3bitrd`, …), which is *our*
heuristic rather than an upstream declaration, and §5's recommendation is to
replace it with a mined-and-declared table before anything depends on it.

Category 5 is decided on **shape** — the line's consequent is a membership,
non-membership, inequality or subset claim — not on a label, so it is the most
honest of the six and also the least precise: `sqrt2irr`'s own conclusion
`( sqrt \` 2 ) e/ QQ` counts as "typing". Read 29.7% as an upper bound with a
large true core, not as a target.

Category 6 is a residue, not a measurement of content. It contains everything the
five heuristics missed, including plenty that is equally mechanical.

### 2.1 What n-gram mining says, and why it is the weakest lever

The obvious idea — mine common step sequences and turn them into lemmas — was
tested. The most frequent bigrams and trigrams across all 47,617 proofs are:

```
eqid  -> eqid  -> eqid            2,918        adantr -> adantr -> adantr   1,516
oveq2d-> oveq2d-> oveq2d            490        ad2antrr ×3                    431
```

These are not composite idioms waiting to be named. They are **one mechanical
operation applied *n* times**, and a lemma cannot help: the second `adantr` is
weakening past a second conjunct, which a *different* lemma already exists for
(`ad2antrr`) and which set.mm already uses. The genuinely composite sequences —
`eqid → ovex → fvmpt` (235), `anbi12d → rspcev → syl12anc` (230) — are real but
sit four orders of magnitude below the mechanical classes.

**Recorded so it is not re-attempted:** adding derived lemmas is the cheapest
strategy to *state* and the weakest to *deploy*. `set.mm` has already been mined
this way, continuously, for twenty-five years by people optimising for exactly
this; the ~50 deduction combinators *are* the result. What is left is not a
missing lemma. It is a missing *mechanism*.

---

## 3. The five levers, and what each is worth

Each is scored on measured payoff, on whether the trusted core learns anything
(it must not), and on whether it is reversible — an author writing at the high
altitude and the system checking it.

### L1 — Fold the proof for display (Tier B4)

**Payoff:** up to the full 71%, visually. **Cost:** frontend plus one query.
**Trust:** none — it re-renders an already-checked proof.
**Reversible:** no. It is a view, not a surface.
**Scales:** trivially, and it is the *only* lever that improves all 47,546
imported proofs without rewriting any of them.

The fold rules fall straight out of §2: collapse a maximal run of
`natded_weak`/`natded_cut` steps into the line it delivers; collapse a
congruence run terminating in a transitivity step into one `calc` row; move
closure lines into a gutter. `proof_line_antecedents` already stores the
dependency DAG and `proof_lines` already stores `indent`/`opens_scope`/`scope_id`,
so this is a graph query over rows that exist.

**Recommend building first**, for a reason beyond cheapness: every other lever
needs a folded view to be worth looking at, and building the fold against
*imported* proofs — where the structure is inferred — is the strictly harder case,
so it will not need redoing when the structure becomes authored.

### L2 — A natural-deduction child system (the big one)

**Payoff:** 18.9% of lines, 74.5% of lines lose their `( ph -> … )` wrapper, and
40.6% of all proof text disappears. **Cost:** one child system, no engine change.
**Trust:** one declared rule (see the caveat). **Reversible:** *natively* — the
high-level proof is the checked object; there is nothing to elaborate and no
elaborator in the trusted path. **Scales:** one-time cost, independent of corpus
size. Every one of the 47,546 imported theorems becomes citable in it.

The insight the measurement forces: **`set.mm` is a sequent calculus implemented
in its own object language, and 18.9% of its lines are the interpreter overhead.**
`adantr` is weakening. `syl` is cut. `simpl`/`simpr` are assumption lookup. `ex`
and `imp` are the two directions of the deduction theorem. `set.mm`'s own
`$j natded_*` tables say so in as many words. The reason those steps exist is that
a Hilbert system has no notion of a proof context — so the context is carried in
the statement, by hand, on every line.

Edifyce has that notion. `LineSpec(scope="assumption")`, `Subproof(assume=…,
derive=…)`, reiteration restriction and eigenvariable freshness are all
first-class in `SystemSpec` today (`tests/zfc_systems.py`, `docs/scoped_subproofs.md`).
And since **R1 landed**, a child may inherit a parent's grammar and add its own
lines and rules, and since **R2 landed**, a citation in the child resolves against
the parent's library. So the construction is:

```
system  "set.mm (ND)"   inherits_from  "set.mm (imported)"
  lines   assume <wff>              scope: assumption
          let <setvar>              scope: variable
  rules   R    reiteration
          CP   (ph -> ps)   discharges  assume ph … derive ps
          UG   A. x ph      discharges  let x   … derive ph
```

Nothing else. The grammar, the 1,429 definitions and the 47,546 promoted theorems
arrive by inheritance; `ax-mp` is already citable and is →E. `sqrt2irrlem` written
in this system reads:

```
assume A e. ZZ
assume B e. NN
assume ( sqrt ` 2 ) = ( A / B )
    2 = ( ( A / B ) ^ 2 )                     [ … ]
    2 = ( ( A ^ 2 ) / ( B ^ 2 ) )             [sqdivd, … ]
    ( 2 x. ( B ^ 2 ) ) = ( A ^ 2 )            [ … ]
    ( ( A ^ 2 ) / 2 ) = ( B ^ 2 )             [ … ]
    ( ( A ^ 2 ) / 2 ) e. NN                   [ … ]
    ( A / 2 ) e. ZZ                           [zesq, … ]
    ( ( A / 2 ) ^ 2 ) = ( ( B ^ 2 ) / 2 )     [ … ]
    ( ( B ^ 2 ) / 2 ) e. NN                   [ … ]
    ( B / 2 ) e. NN                           [nnesq, … ]
    ( ( A / 2 ) e. ZZ /\ ( B / 2 ) e. NN )    [jca, … ]
( A e. ZZ -> ( B e. NN -> ( ( sqrt ` 2 ) = ( A / B )
              -> ( ( A / 2 ) e. ZZ /\ ( B / 2 ) e. NN ) ) ) )    [CP, CP, CP]
```

Ten surface lines against forty-eight, and every formula is shorter, because
`( ph -> … )` is gone from all of them. The remaining `[ … ]` are what L3 and L4
close.

**The caveat, stated plainly, because it is the only soundness-relevant judgement
in this note.** `CP` in the child is a *declared primitive rule of the child*, not
a checked consequence of the parent. It is admissible in the parent by the
deduction theorem, so the child is conservative over it — but that is a
metatheorem (induction over derivations), and the relationships roadmap §6.1 is
right that Edifyce has no way to state it and should not special-case it in the
kernel. Three honest positions, in increasing cost:

1. **Declare it and record the claim.** Exactly the discipline
   system-relationships §1.2 sets for conservativity: "recorded as a claim about a
   relationship, never inferred". The child is then a natural-deduction system in
   its own right, and declaring `CP` in it is no more exotic than declaring any
   other primitive rule. Nothing in the parent is weakened; a proof in the child
   is a proof in the child.
2. **Discharge it by elaboration.** The deduction theorem's *proof* is an
   algorithm: it turns a subproof under `ph` into a Hilbert derivation of
   `( ph -> … )` in `a1i`/`syl`/`ax-mp`. An elaborator emitting that chain would
   turn the declared rule into a checked one, with the parent's kernel doing the
   checking. This is the narrowest possible instance of Tier B1 — one rule, one
   textbook algorithm — and it is the **highest-value single elaborator in this
   note**, ahead of the closure solver, because it is what makes L2 fully verified
   rather than verified-modulo-one-declaration. It also blows the certificate up
   (roughly quadratically in the subproof's length), which is a cost to measure,
   not a reason to skip.
3. **The `interpretation` edge** (relationships R4/S2), with a `Γ ⊢ φ` statement
   template and one discharged obligation per Hilbert axiom. Genuinely more
   general, and the right answer when the *statement shape* has to change.

**Recommend position 1 now, position 2 as the upgrade, and explicitly not
position 3 for this purpose.** The reason is measured: an `interpretation` edge to
a sequent system needs a `context` sort, and a syntactic list context makes
exchange, weakening and contraction explicit cited steps (relationships §6.2) —
which reintroduces bookkeeping of precisely the kind this lever exists to remove,
unless S4's associative-commutative matcher lands first. Edifyce's scoped
subproofs have **no context term at all**, so they pay none of that. For the
altitude goal the scope tree beats the sequent, and the edge should be built for
the cases that actually need a translation.

### L3 — Closure / typing solver (Tier B2)

**Payoff:** the largest single class, up to 29.7%. **Cost:** a backward-chaining
solver plus a declared closure table. **Trust:** none — it emits primitive lines
the kernel re-checks. **Reversible:** the best UX of any lever, because the author
writes *nothing*; the obligation is silent and the expansion is the certificate.
**Scales:** shortens new proofs at zero corpus cost; folding it into imported
proofs is L5.

The design is the roadmap's B2 and does not need restating. What this measurement
adds is **where the table comes from**. It should not be hand-written and it
should not be guessed: a closure rule is recognisable by shape — an assertion
whose conclusion is `X e. S` and whose premises are all of the form `Y e. T` — and
the corpus can be swept for them by the same walk that classifies definitions.
That gives a table that is *data about one library*, sitting in
`website/logical/metamath/setmm.py` beside `BINDERS`, `EQUIVALENCES` and
`RESTATEMENTS`, and it keeps the solver parameterised by declaration rather than
by ℂ, which is what keeps Edifyce general.

**The alternative worth costing once and then not pursuing:** make closure a
*grammar* fact by giving the child system real sorts (`nat`, `int`, `cplx`), so
`2 ∈ ℂ` is decided by parsing. Edifyce is sorted and this is the structurally
right answer. It is also a different system from `set.mm` under a non-identity
sort map, needing an `interpretation` edge and an obligation per axiom, and
metamath roadmap A3 has already deferred richer typing on the grounds that it
risks having to re-prove things. Keep the solver.

### L4 — `calc` chains with position-driven congruence (Tier B3)

**Payoff:** 11.5% + 5.6% = 17.1%. **Cost:** one line type plus an elaborator plus
a declared congruence table. **Trust:** none. **Reversible:** fully — the `calc`
block is the surface, the emitted `oveq1d`/`eqtrd` run is the certificate.
**Scales:** as L3.

The lever Edifyce has and Metamath does not is the parse tree: given
`f(a, X) = f(a, Y)` from `X = Y`, *which slot changed* is a fact about the term,
so the congruence lemma to cite is determined rather than chosen. What has to be
declared is the witness per (production, slot): `co` slot 1 ↦ `oveq1d`, slot 2 ↦
`oveq2d`, `cfv` slot 2 ↦ `fveq2d`, and so on. Seeded from `$j congruence` and
`$j equality 'wceq' from 'eqid' 'eqcomi' 'eqtri'` — which is only six directives,
so most of the table has to be **mined**, by sweeping for assertions of shape
`( A = B -> f(…A…) = f(…B…) )` and reading the changed slot off the parse.

This is the one place where §2's classification is currently *our* heuristic
rather than an upstream declaration, so mining the table is also what puts
category 2 on the same footing as category 1.

### L5 — Idiom recognition on imported proofs (Tier B5)

**Payoff:** in principle the whole 71%, applied to proofs nobody re-authors.
**Cost:** high, and per-proof. **Trust:** none, *provided* its output is
re-checked from scratch rather than trusted. **Reversible:** it is the reverse
direction by construction. **Scales:** worst of the five — it is the only lever
whose cost is proportional to the corpus.

**Recommend last, and recommend against needing it.** With L2 in place, the right
response to "`sqrt2irr` is 94 unreadable lines" is not to transform those 94
lines. It is to write a *new* fifteen-line proof of the same theorem in the child
system, citing the imported lemmas, and keep the 94-line import as the
machine-checked record of the Hilbert derivation. Two proofs of one theorem in two
related systems, both verifying, is a truthful description of the situation;
a lossy rewrite of one into the other is not. The relationships roadmap's
provenance query (§5.5) then answers "which of these does this result actually
depend on".

Where L5 does earn its keep is as an *authoring assistant*: given an imported
proof, propose the high-level skeleton, let a human accept it, and re-check the
result. A wrong proposal is then a failed check, never an unsound proof.

### L6 — More definitions

Worth stating separately because it is the strategy the brief names first and it
is the one whose payoff is most often overestimated.

**Definitions raise the altitude of the *statement*, not of the *proof*.** Adding
`Irrational(x) ≝ x ∉ ℚ`, `Even(n)`, `Coprime(a, b)` makes `sqrt2irr` read like
mathematics and makes `[Def, n]` steps available — and removes **not one** of the
48 lines of `sqrt2irrlem`, because a definitional unfold is a step, not a
shortcut. The measurement bears this out: definitions are already 1,429 of the
imported system's 1,559 logical `$a`, and the corpus is still 31 lines per proof.

They are still worth having, for three reasons that are all downstream of the
other levers: a folded proof (L1) needs legible statements at the fold points; a
closure solver (L3) is much more useful when a defined predicate can carry its
closure facts as declared lemmas; and the human-facing statement of a theorem is
what makes a library searchable. One constraint to note:
`_require_a_fresh_defined_form` refuses a definition of a symbol the theory
already reasons about, so new definitions go in the **child** system, not into the
imported corpus — which is another reason the child of L2 is the right container
for all of this work.

---

## 4. Reversibility: two different things, kept separate

The brief asks for high-level proofs that the system can parse and verify. There
are two mechanisms for that and they should never be conflated.

**Native authoring (L2).** The high-level proof *is* the checked object. There is
no elaboration, no expansion, and nothing in the trusted path except the kernel.
"Reversing" is not a question, because nothing was transformed. This is the
strongest available answer and it is the one Edifyce is unusually well set up to
give, because systems and the relationships between them are first-class here.

**Elaboration with a stored certificate (L3, L4, and L2's upgrade path).** The
author writes a surface step; an elaborator emits primitive lines; the kernel
checks the lines. Two rules make this trustworthy and reversible:

> **The elaborator is never in the trusted path, and the surface step is never
> what is re-checked.** If a stored surface step were checked directly, the
> elaborator would have become part of the kernel.

> **Both directions are stored, not recomputed.** Down = the stored expansion.
> Up = the stored surface step. An elaborator that changes tomorrow cannot
> silently change what a proof stored today means.

Mechanically that is **one nullable column** on `proof_lines` —
`elaborated_from_id` pointing at another `proof_lines` row, plus a flag marking a
line as surface — which is the shape `scope_id` already has. `store_proof_lines`
writes it, L1's fold reads it, and `docs/verification-from-rows.md`'s property
survives unchanged: a stored proof re-verifies from its rows and its terms, with
zero trust in whatever produced them. That is the de Bruijn criterion, stated in
this codebase's own terms.

---

## 5. Recommended sequence

**0. Publish the imported corpus.** `app/db/metamath_store` writes the system with
no owner and no `published_at`, and `_require_inheritable_reference` refuses to
inherit from an unpublished draft. So *nothing in §3 is reachable* until the
imported system is published. This is a small change with a real consequence
(publishing is a one-way door and freezes the grammar), and it should be taken
deliberately rather than discovered.

Two prerequisites travel with it, both already named in the metamath roadmap:
`import_corpus` does not pass `equivalences`, so a stored import is still
all-axioms; and relationships §9.12 **refuses an inherited library entry with no
usable cached term**, which is exactly what a child citing the corpus needs — so
the corpus's promoted-theorem statement terms have to be stored and their digests
current, or every cross-layer citation refuses.

**1. `setmm.NATURAL_DEDUCTION` and `setmm.CONGRUENCE`.** Data only, no behaviour,
default-empty, same discipline and same test shape as `BINDERS`. The first is
transcribed from `$j natded_*`; the second is seeded from `$j congruence` /
`$j equality` and completed by a mining sweep. Everything downstream reads them,
and they are independently useful as a classification of the corpus.

**2. L1, the display fold.** Highest ratio of visible improvement to risk, the
only lever that reaches the 47,546 proofs that already exist, and a prerequisite
for judging the rest.

**3. L2, the ND child system.** No engine change expected. If one *is* needed,
that is the finding, and it should be reported rather than worked around. Held to
the four-part test shape relationships §8.0 sets: a realistic worked example
(`sqrt2irrlem` at ND altitude, citing imported lemmas), a complex accepted case
involving a binder, a rejection per guard, and a negative control — tamper the
discharge and require the check to fail.

**4. L3 then L4**, on the B1 elaboration substrate plus the `elaborated_from`
column. L3 first: it is the largest class and the one whose surface is *nothing at
all*.

**5. L2's upgrade** — elaborating `CP` into the parent's Hilbert steps — once
there is something to measure the blow-up against.

**6. L5**, as an assistant, last, and only if L2 has not made it unnecessary.

---

## 6. What this does not do

- It does not make the kernel cleverer. Every lever is a system, a table, a view,
  or an elaborator whose output the existing kernel checks unchanged.
- It does not hard-code anything about ZFC, ℂ or `set.mm`. Every table is *data
  about one library* in `metamath/setmm.py`, empty by default, and every solver is
  driven by declarations.
- It does not rewrite imported proofs. §3's L5 argues that it should not.
- It does not check conservativity of the ND child over the Hilbert parent. §3's
  L2 records that as a claim, with the route to checking it.

---

## 7. Interaction with the relationships roadmap

Read together with [system-relationships-roadmap.md](system-relationships-roadmap.md);
there is one agreement, one dependency, and one genuine tension.

**Agreement.** L2 is a straight consumer of **R1 and R2, both delivered**. A child
inheriting the imported corpus, adding line types and rules, and citing the
parent's 47,546 theorems by bare label is exactly what those two phases built. No
new table, no new edge kind, no engine surface. Worth saying because the altitude
work looked like it needed R4, and measured, it does not.

**Dependency.** §9.12's refusal — an inherited entry with no usable cached term
does not resolve — makes storing the corpus's promoted-theorem terms a hard
prerequisite rather than an optimisation. And `_require_owned_system` (§9.5)
means a user must own the system they write proofs against, which the child
satisfies and the imported corpus does not; that is the shape the split should
take anyway.

**Tension, and it is a real one.** Relationships §6.2 chooses a sequent system
with a syntactic list `context` sort and accepts that exchange, weakening and
contraction become explicit cited steps, with S4's associative-commutative matcher
as the escape if it hurts. For *stating* the deduction theorem and for the
Hilbert → sequent interpretation edge, that is the right call and this note does
not dispute it. But **for the altitude goal it is the wrong shape**: it trades
`adantr` for `wk`, and 18.9% of the corpus says that trade is most of what we were
trying to remove. Edifyce's scoped subproofs carry no context term and pay none of
that cost.

So the recommendation to that track is: build S1 and S2 for what they are for —
expressing the deduction theorem, and the general edge — and do **not** treat them
as the route to readable proofs. The route to readable proofs is a child system
with scope lines and discharge rules, which R1 already supports. If the two are
conflated, S4 becomes a blocker for altitude work that never needed it.

One smaller note for that track: relationships §5.5's provenance query is what
makes L5's "two proofs of one theorem" honest, by answering which system a given
result actually depends on. It is listed there as a validation of the layer plan;
it is also the thing that lets a short child-system proof and a long imported one
coexist without either being mistaken for the other.

---

## 8. Method

Everything measured here is reproducible from a `set.mm` checkout and the
importer, with no database and no system build:

```python
from website.logical.metamath import parse, import_proof
db = parse(open("set.mm").read())              # ~5 s
text = import_proof(db, "sqrt2irrlem")         # the 48 lines above
```

The whole-corpus sweep is `import_proof` over every logical `$p` — 47,617 proofs,
1,482,010 lines, about 30 seconds — followed by the classification of §2. The
category-1 label set is transcribed verbatim from `set.mm`'s `$j natded_*`
directives; categories 2–4 are label-name families and are the part of the
measurement that should be replaced by a mined table (§3, L4); category 5 is
decided on the shape of each line's consequent and reads nothing but the term.

The figures were taken against `set.mm` at `metamath/set.mm@develop`, August 2026,
and will drift with the corpus. The shares are stable enough that the ordering of
the levers is not in question; the third significant figure is.
