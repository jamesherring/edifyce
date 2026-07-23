# Why Metamath's √2 proof is so verbose — and what Edifyce needs before a set.mm import

**Status:** analysis / pre-import design note. No code yet.

Goal restated: import Metamath's `set.mm` while keeping **full verifiability** and
**full generality** (Edifyce must stay a *general* proof assistant — any formal
system, not a hard-wired ZFC), *and* let humans write and read proofs at the
altitude mathematicians actually use.

To know what to build, this note first dissects a concrete Metamath proof, then
maps each source of verbosity onto Edifyce's engine as it stands today.

---

## 1. The specimen: `sqrt2irr`

The mathematician's proof of "√2 is irrational" is about six lines:

> Suppose √2 = a/b with a, b integers in lowest terms, b ≠ 0. Then a² = 2b², so a²
> is even, so a is even; write a = 2c. Then 2b² = 4c², so b² = 2c², so b is even.
> But then 2 divides both a and b, contradicting lowest terms. ∎

Metamath's `set.mm` proof (`sqrt2irr`, plus its core lemma `sqrt2irrlem`) is a
flat sequence of a few hundred primitive steps. Its statement is terse —

```
sqrt2irr $p |- ( sqrt ` 2 ) e/ QQ $=
```

— but the stored proof (compressed format) cites on the order of **ninety
distinct prior theorems** just in the two blocks, among them `syl`, `zcn`,
`nncn`, `ad2antrr`, `ad2antlr`, `2cnd`, `nnne0`, `2ne0`, `a1i`, `divcan7d`,
`eqtr4d`, `oveq1d`, `oveq2d`, `fveq2d`, `breq2`, `eleq1d`, `simpl`, `simpr`,
`simpll`, `simplr`, `jca`, `ralrimdva`, `nnind`, … Reading it means scrolling
hundreds of one-substitution-per-row steps.

The gap between six lines and a few hundred steps is not sloppiness — it is the
direct consequence of a small number of deliberate design decisions. Here they
are, each with the concrete Metamath machinery it produces.

---

## 2. Anatomy of the verbosity

### 2.1 Foundational depth — everything is defined down to ZFC + FOL

`set.mm` builds on ~20 axioms. The *vocabulary of the statement itself* sits many
definitional layers above them:

| Symbol | Definition in `set.mm` |
|---|---|
| `2` | `df-2`: `2 = ( 1 + 1 )` |
| `/` | `df-div`: the `iota` z in ℂ with `( y · z ) = x` |
| `sqrt` | `df-sqrt`: an `iota` over ℂ with a `Re`/`RR+` side condition |
| `QQ` | `df-q`: the image of `/` over `ZZ × NN` |

A human treats "√2", "ℚ", "even" as atomic and already understood. The machine
must, at least once in the library, tie each back to foundations. **This cost is
mostly amortised into the library, not paid per proof** — but it sets the floor:
nothing is free, not even `2`.

### 2.2 Types encoded as propositions → "closure plumbing" *(the biggest visible cost)*

Metamath is **untyped**: one syntactic category of classes/wffs. "A is an
integer", "B ≠ 0", "2 ∈ ℂ" are not typing facts the checker knows — they are
*propositions that must be proved and then carried as hypotheses*. Hence the
swarm of closure lemmas:

```
nncn  |- ( A e. NN -> A e. CC )        ( naturals are complex )
zcn   |- ( N e. ZZ -> N e. CC )        ( integers are complex )
2cnd  |- ( ph -> 2 e. CC )
nnne0 |- ( A e. NN -> A =/= 0 )
```

Every arithmetic move (`divcan7d`, `sqdivd`, …) has closure side-goals, and each
is discharged by threading one of these through the context. In a typed system
(Lean/Coq/Isabelle) these are dispatched by the type checker, by typeclass
resolution, or by a `norm_num`/`positivity`-style tactic, and **never appear in
the proof text**. In `sqrt2irr` they are plausibly the single largest slice of
the step count.

### 2.3 Deduction form — the deduction theorem simulated by hand

Object-logic FOL has no native "assume φ, … , therefore φ → ψ" with discharge.
`set.mm`'s idiom makes essentially every line `( ph -> … )` and threads the shared
antecedent `ph` **manually**. That single convention generates a whole class of
content-free steps:

```
syl      |- ( ph -> ch )                       from ph->ps, ps->ch  ( compose )
adantr   |- ( ( ph /\ ch ) -> ps )             ( weaken: add a conjunct )
ad2antrr |- ( ( ( ph /\ ch ) /\ th ) -> ps )   ( weaken twice )
simpl/r  |- ( ( ph /\ ps ) -> ph ) / -> ps )   ( select from the context )
jca      |- ( ph -> ( ps /\ ch ) )             ( pair two results )
```

`syl`/`3syl`/`ad*ant*`/`simp*`/`jca` are pure **hypothesis-context bookkeeping**:
move, weaken, select, and recombine the assumptions. A human keeps the context in
their head ("we're assuming √2 = a/b, a,b ∈ ℤ …") and writes none of it.

### 2.4 Congruence / rewriting spelled out position by position

To rewrite `a → b` *inside* a term, Metamath invokes a congruence lemma specific
to the position:

```
oveq1d |- ( ph -> ( A F C ) = ( B F C ) )    ( rewrite operand 1 )
oveq2d |- ( ph -> ( C F A ) = ( C F B ) )    ( rewrite operand 2 )
fveq2d |- ( ph -> ( F ` A ) = ( F ` B ) )    ( rewrite a function argument )
breq2  |- ( A = B -> ( C R A <-> C R B ) )   ( rewrite a relation argument )
eleq1d |- ( ph -> ( A e. C <-> B e. C ) )    ( rewrite the left of ∈ )
```

plus the equality-chain glue `eqtr`, `eqtr4d`, `3eqtr4d`. A human writes a `=`/`↔`
chain and the reader supplies congruence ("Leibniz") silently; a tactic system
runs `rw`/`simp`/`calc`. Metamath applies Leibniz-at-position-k as an explicit
named step, once per subterm.

### 2.5 The kernel's only rule is substitution

Metamath's single primitive is: substitute into an axiom/theorem, respecting the
distinct-variable constraints. Even modus ponens is a theorem, `ax-mp`, invoked as
a step. There is **no built-in natural-deduction structure** — no ∧-intro,
→-intro/elim, ∀-intro as structural moves. This is what makes a Metamath verifier
~300 lines; the cost is that every logical move is a named theorem application and
proofs are long. A deliberate, coherent trade.

### 2.6 No automation in the *stored* object

Lean/Isabelle proof *sources* are short because `ring`, `linarith`, `norm_num`,
`omega`, `decide`, `simp`, and typeclass resolution close goals the author never
writes. Those tactics run at *elaboration* time; the kernel term they produce is
still large — but **no human writes or reads it**. Metamath makes the authored,
the checked, and the presented object one and the same fully-expanded thing.
*That conflation is the crux.*

### 2.7 No structural abstraction — no "similarly", "WLOG", "by symmetry"

The proof is a flat DAG. A human says "b is even by the same argument"; Metamath
must repeat the argument or hoist a lemma (here, `sqrt2irrlem` factors the shared
core, but the a-vs-b symmetry is still discharged explicitly). Infinite descent is
re-encoded as strong induction (`nnind`) with its full machinery. There is no
first-class "by symmetry" or case-split that expands on demand.

### 2.8 Variable / distinct-variable bookkeeping

Dummy variables (`vx vy vz vn`), `$d` distinct-variable constraints, and
bound-variable handling via schematic metavariables rather than native binders —
tokens with no mathematical content to a human reader.

### 2.9 Presentation = one primitive step per row

Even the human-facing artifact (the Metamath web renderer) is a step table with
one substitution per row and no "zoom". Reading is scrolling.

---

## 3. The one root cause

Almost everything above collapses to a single decision:

> **Metamath has no elaboration gap.** The proof a human authors, the proof the
> kernel checks, and the proof a reader sees are *the same maximally-expanded
> object*. That buys a tiny trusted verifier and total generality — at the price
> of forcing every human to work at kernel altitude.

So the design question for Edifyce is not "how do we make the kernel cleverer"
(that costs verifiability) but **"how do we open an elaboration gap without giving
up generality"** — a high-level surface that *elaborates* down to primitive,
kernel-checkable steps, where the abstractions are **defined relative to the
user's formal system**, not baked in.

---

## 4. Where Edifyce already stands — the good news

Edifyce has, by design, already broken the Metamath collapse in several of the
exact places §2 identifies. Concretely (engine facts, with the relevant docs):

| Metamath cost (§) | Edifyce today | Verdict |
|---|---|---|
| 2.1 definitional depth | First-class, **layered**, capture-avoiding definitions with provisos (`Define … as … fresh … where …`); a proof takes a *definitional step* `[Def, n]` checked over kernel terms. `docs/proof-references-and-definitions-plan.md`, `docs/side_condition_followups.md` | **Covered** — `df-*` map to definitions |
| 2.2 typing/closure | The engine is **sorted** (union-of-productions sorts; `member`/`atom` provisos test sort membership structurally). `docs/symbols-model-design.md` | Structure present; **automation absent** (see §5) |
| 2.3 deduction form | **Native scoped subproofs with discharge** — `assume/derive` blocks, `Subproof` kind `assumption`/`variable`, reiteration restriction + eigenvariable freshness enforced. `docs/scoped_subproofs.md` | **Covered for new proofs** — no `syl`/`adantr` needed |
| 2.5 substitution-only | Rules are **schematic**; substitution is *derived by unification* at check time, not written. `ax-mp` becomes an ordinary rule `MP` | **Covered** |
| 2.7 lemma reuse | Cross-proof citation `[Alias.n]` with transitive cycle-checking, API-wired | **Partly** — see §5.1 |
| 2.8 `$d` / freshness | `disjoint(x, φ, …)` proviso **is** `$d`; `fresh` atoms are dummy/eigenvariables | **Covered** — direct mapping |

The headline: **Edifyce's model is natural-deduction-native and sorted**, so the
two largest Metamath cost centres — deduction-form plumbing (§2.3) and, in
principle, typing (§2.2) — are *not* structural in Edifyce the way they are in
`set.mm`. A proof *authored* in Edifyce already reads closer to mathematics than a
Metamath proof does. What's missing is the machinery to (a) make an *imported*
proof faithful and checkable, and (b) let the automation and presentation reach
the altitude humans want.

---

## 5. Recommended enhancements

Two tiers. **Tier A** is what an import strictly requires (correctness &
coverage). **Tier B** is the human-altitude layer — the actual goal — which can
land after import but should be *designed for now* so the import doesn't foreclose
it. A guardrail runs through both: **every abstraction is parameterised by the
user's declared system**, never hard-coded, so generality is preserved.

### Tier A — prerequisites for a faithful, verifiable import

**A1. Schematic *theorem application* ("theorems as rules") — the make-or-break item.**
A `set.mm` proof is, essentially, ~90 applications of *previously proved theorems*,
each **re-instantiated** at the call site (Metamath makes no distinction between a
`$a` axiom and a `$p` theorem when citing it — both are schemes substituted into).
Edifyce today applies *inference rules* by unification (schematic ✓) but reuses a
proved lemma by **citing a specific checked line and trusting it** — which is not
obviously the same as instantiating that lemma's metavariables afresh against new
terms. **Verify precisely whether citing `[nncn.1]` lets you bind `A` to an
arbitrary term at the use site; if not, build "promotion" of a proved theorem into
a reusable schematic `InferenceRule`.** Without this, an import cannot even be
expressed. This is the first thing to prototype.

**A2. Compressed-proof decoder → primitive Edifyce proof.** Decode Metamath's
compressed proof format (the parenthesised label table + the capital-letter RPN
stream) into a stack machine, and emit each step as an Edifyce proof line citing
prior lines and the schematic theorem/rule from A1. The import's contract is:
**produce fully-primitive proofs that the existing kernel checks** — that is the
verifiability baseline and, incidentally, an excellent stress test of the kernel.

**A3. Symbol/statement mapping.** `$c`/`$v` → constants and metavariable sorts;
`$f` (floating/typing hyps) → sort bindings; `$e` (essential hyps) → rule
antecedents / proof hypotheses; `$a` → axioms **or** definitions (see A4); `$p` →
proof + promoted rule (A1); `$d` → `disjoint` provisos (already a direct fit).
Metamath's two working sorts (`wff`, `class`) plus `setvar` map onto Edifyce
sorts; **import faithfully as a 2-sorted-ish system first** (mirror Metamath),
enrich typing later — a richer type discipline risks needing to *re-prove* things
and is a generality/soundness surface best deferred.

**A4. Definition classification.** Not every `df-*` is fold/unfold-shaped, and
some `set.mm` "definitions" are effectively axioms (or rely on Metamath's external
definitional-soundness checker). Classify each `$a`: conservative
definition → Edifyce `Define` (conservativity then holds *by construction* — a
strict improvement over Metamath); otherwise → axiom. Flag the residue for review.

**A5. Scale & performance.** ~40 000 theorems, a 51 MB source, proofs hundreds of
steps deep. Two concrete risks: (i) the current notation parser is a **hand-written
backtracking string matcher** with a `certainty` heuristic — validate it at
`set.mm` grammar scale, and prefer the structured `declarative.py` build path with
**precompiled schema terms** over the text DSL for bulk import; (ii) 40 000
schematic rules must resolve fast — exercise the bipartite antecedent-assignment
and unification hot paths at library scale before committing. Budget for this;
it's easy to underestimate.

### Tier B — the human-altitude layer (design now, build alongside/after)

**B1. A tactic / elaboration framework obeying the de Bruijn criterion.** A tactic
is a program that, given a goal + context, **emits a primitive sub-proof the
kernel still checks** — so trust never leaves the existing core. This is the
missing piece that closes §2.6. Make tactics first-class citizens that produce
proof lines, and record the elaboration tree (which surface step produced which
substeps) for B4.

**B2. A closure / typing solver (kills §2.2).** Given a membership/side goal (`A ∈
ℂ`, `B ≠ 0`) and a user-declared set of closure rules (`nncn`, `zcn`, …), search
for a derivation automatically. Driven by a *declared* rule set, so it's general —
it solves closure in any system that declares closure rules, not just ZFC. This
single tactic removes the largest visible slice of `sqrt2irr`.

**B3. Equational reasoning: `calc` chains + a congruence tactic (kills §2.4).** A
surface for `a = b = c …` with one justification per step, where the elaborator
synthesises the `oveqNd`/`fveqNd`/`eqtr` congruence applications. Parameterise on a
**user-declared equivalence relation** and which operator arguments are congruent
(derivable from the notation grammar), so it generalises beyond `=` to any
declared congruence (`↔`, group equality, …).

**B4. Zoomable presentation (kills §2.9, and makes imports readable).** Because an
imported proof *is* fully expanded, the payoff is in rendering: store the
elaboration/subproof tree and let the frontend **fold to a human-altitude sketch
and drill down to primitives on demand**. Edifyce's subproof tree already gives
the scaffolding; the frontend is a thin client, so this is largely a rendering +
stored-tree task.

**B5. Idiom re-abstraction for imported proofs (stretch — the highest-value
presentation win).** A pass that *recognises* Metamath plumbing idioms in an
imported proof and folds them back to human altitude: `syl`-chains → transitivity;
`ad*ant*`/`simp*` clusters → "in this context"; `oveqNd` clusters → a `calc` step;
closure-lemma applications → hidden typing obligations. This is exactly
"presenting proofs at the higher level humans use" applied to the 40 000 proofs we
import, not just to new ones. It depends on B4's stored tree.

**B6. Structural macros — WLOG / by-symmetry / case-split (addresses §2.7).**
Elaborated macros that expand to real subproofs (e.g. "by symmetry" discharges by
instantiating a proved symmetry lemma), so authors write "similarly for b" and the
kernel still sees the full argument. General because the symmetry/exhaustiveness
justification is a cited lemma, not a built-in.

---

## 6. Suggested sequencing

1. **Prototype A1** (schematic theorem application) against a dozen hand-picked
   `set.mm` theorems — this de-risks the entire import in the cheapest possible way.
2. **A2–A4**: decoder + mapping + definition classification; get `sqrt2irr` and its
   transitive dependencies importing as primitive, kernel-checked proofs.
3. **A5** in parallel: benchmark parser and rule-resolution at scale; switch bulk
   import to the declarative/precompiled path if needed.
4. **B1 + B2** next: the tactic framework and the closure solver deliver the biggest
   readability jump for the least surface area, and are what make *new* Edifyce
   proofs (not just imports) short.
5. **B4** (zoom) and **B3** (`calc`); then the stretch items **B5/B6**.

The throughline: Edifyce should keep the property that makes Metamath trustworthy
— **a small kernel that checks a fully-primitive object** — while adding the
**elaboration gap** Metamath deliberately omitted. Every recommendation above
either produces primitive steps for that kernel to check (A1–A2, B1–B3, B6) or
only reorganises how an already-checked proof is *shown* (B4–B5). Verifiability and
generality are preserved by construction; the altitude is what we add.
