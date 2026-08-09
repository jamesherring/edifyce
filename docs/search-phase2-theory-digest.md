# Design: Phase 2, the theory-aware canonical digest

**Status:** analysed, **not built**. This note is the design
[search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md) §Phase 2
describes in thirty-one lines and does not specify. Three conclusions, in
descending order of how much they change the plan:

1. The phase is really **two** phases with very different readiness, and the
   equational one has a **prerequisite nobody has designed** — a system cannot say
   which of its productions means equality.
2. **Congruence is not free.** A congruence closure merges `f(a)` with `f(b)`
   whenever `a = b`, by construction; in an arbitrary declared logic that step is a
   *theorem schema*, not a given, and set.mm proves it one position at a time. An
   e-graph would assume for free what a corpus spends its bulk establishing.
3. The definitional half is nearly buildable but is blocked on a smaller thing the
   roadmap does not mention: the definitional rewrite relation is acyclic but
   **not confluent**.

Phase 1 shipped ([search-phase1-fingerprint.md](search-phase1-fingerprint.md)).
This is what comes next, and what has to be settled first.

## The proposal, as the roadmap states it

Normalise a term to a canonical representative of its equivalence class under the
system's *known* equalities — definitions' higher↔lower and proven equational
lemmas — then hash it. That gives a `theory_digest` extending the
`digest → alpha_digest` ladder one step, and merges the pairs syntactic search
keeps apart:

```
x ⊆ y            and   ∀z (z ∈ x → z ∈ y)      by df-ss
a + b            and   b + a                    once commutativity is proven
```

Phase 1's boundary note is the motivation: a `⊆` goal retrieves the 141
`⊆`-headed theorems and none of the 22 `∀`-form ones, though some are
definitionally equivalent. Phase 1 is right to refuse them — the filter and the
confirm must stay in lockstep — so the way to merge them is to move *both*, which
is this phase.

## What is already here

More than the roadmap credits, and unevenly distributed between the two halves.

**Definitions are already a structured, oriented rewrite.** A
`kernel.definitions.Definition` carries `higher` and `lower` as term schemas over
shared variables, plus `fresh` binders and an optional `condition`; `unfold`
applies one to a redex in the defined→defining direction. Nothing has to be parsed
and nothing has to be inferred — the orientation is in the data.

**Termination of the definitional half is already proven, by something that
shipped for another reason.** `_require_a_non_circular_definition`
(`declarative.py`) refuses a cycle in the "is defined using" relation, as the
non-circularity half of conservativity. A rewrite system whose relation is acyclic
over a finite set of definitions terminates. The conservativity work bought the
termination argument this phase needs, which is worth recording because it is not
obvious from either doc.

**Binder naming is already canonical.** Unfolding introduces bound variables whose
names the caller chooses (`unfold(..., names=...)`), which looks like it makes the
rewrite non-deterministic. It does not: in `lower` each binder is stored as an
indexed `Bound` node, and `alpha_digest` records that "bound variables carried as
`Bound` are already index-canonical". So the canonical form of an unfolding is the
one that leaves the binders abstract, and the existing α-machinery hashes it. No
new representation is needed for this.

**The equational half has none of the above** — see the next section.

## The prerequisite: a system cannot say what equality is

Phase 2's input is "the system's *known* equalities". For definitions that input
exists. For **equational lemmas it does not exist at all**, and the gap is not an
oversight to patch but a design question nobody has posed.

A `SystemSpec` has no field naming the production that means equality or
equivalence, and no table stores one. The only such concept anywhere in the tree
is in the Metamath importer:

```python
# website/logical/metamath/setmm.py
EQUIVALENCES = frozenset({"wb", "wceq"})
```

— a hardcoded pair for set.mm, whose own comment states the reason it must be
hardcoded:

> Arity and slot sorts do not distinguish `↔` from `→`, and reading a one-way
> implication as a definition would licence the reverse rewrite, so this is named
> rather than inferred.

That is the whole problem in two lines. Edifyce's premise is that a formal system
is whatever the author declares; there is no privileged `=`. Nothing structural
tells an equivalence from an implication — same arity, same slot sorts — so a
theorem's *shape* cannot say whether it is an equation. Until a system can declare
this, "the system's proven equational lemmas" names an empty set for every system
that is not set.mm, and even for set.mm it is knowledge the importer holds and the
stored system does not.

### The precedent says exactly how to fix it

This repo has met this problem before and solved it well. `denotes_constant` on a
`Production` decides whether a production's tokens name one fixed thing or stand
for variables a binder can bind — Metamath's `$c` vs `$v` — and CLAUDE.md records
the lesson:

> like Metamath's it is **declared, not inferred** — nothing about a production's
> shape settles it … The engine once guessed from the constructor's shape and had
> holes.

So the shape of the answer is settled by precedent: **a declared property on a
production**, defaulted to the safe value, validated against the grammar where the
grammar can contradict it (`_validate_constant_declarations` is the model — it
refuses a `denotes_constant` the binding slots disprove). The open questions are
which property, and what it licenses:

- *Which relation is being declared.* "Is an equivalence" (`↔` between formulas)
  and "is an equality" (`=` between terms of a sort) are different declarations
  with the same consequence for rewriting. set.mm needs both (`wb`, `wceq`), which
  suggests one declaration parameterised by the sort it relates, not two flags.
- *What it licenses.* A declared equivalence makes a proven theorem over it usable
  as a **bidirectional rewrite**. That is a strictly stronger claim than the
  importer's current use (classifying a `$a` as a definition), and it is the claim
  that must be true for a merge to be sound. An author ticking the box on `→` by
  mistake would licence the reverse rewrite — which is precisely the failure the
  set.mm comment names.
- *Whether it can be validated.* Partly. A binary production whose two slots have
  different sorts is not an equivalence, and can be refused. Genuine symmetry
  cannot be checked without proving it, so this stays a trusted declaration in the
  same sense `denotes_constant` is — with the same mitigation: the default is off,
  and turning it on is a positive act.

**Until this is designed, the equational half cannot start.** That is the single
most important finding in this note.

## What rolls in automatically, and what does not

A natural question once the declaration exists: as a library grows and proves
associativity, commutativity, reflexivity, transitivity for its operators, do those
facts fold into the digest on their own, or does each need handling? They separate
into three kinds, and only the first is digest material.

**Equations between terms — automatic, with no per-property code.** Commutativity,
associativity, idempotence, unit laws, distributivity: each is a theorem whose two
sides are terms related by the declared equality. The canonicaliser never learns
the word "commutative"; it ingests `a + b = b + a` exactly as it ingests any other
proven equation. So the answer for this whole family is that recognising an
equation is the only step that needs designing, and it is the declaration above.
Naming comm and assoc *specifically* is worth doing — both are cheap to detect by
matching `f(x, y) = f(y, x)` and `f(f(x, y), z) = f(x, f(y, z))` over distinct
metavariables — but the reason is **performance, not semantics**: AC is the
pathological case for e-class growth, and knowing an equation is AC lets a
saturating structure use AC-matching instead of exploding. Nothing about
correctness turns on it.

**Reflexivity and transitivity of other relations — not digest material at all.**
This is a category error, and it is worth writing down so nobody attempts it. `x ≤
x` is a *theorem*, not an equation: it does not assert that two terms are equal, so
there is nothing to merge and no class to form. Transitivity is an implication, not
an equation. These are valuable — for proof search and for ranking a retrieved
candidate — but they belong to Phase 4, and a canonical form is the wrong place to
look for them. The distinction is that an equation relates two *terms*, while
reflexivity and transitivity are properties of a *relation*; only the first
partitions the term space.

**Reflexivity, symmetry and transitivity of the declared equality itself — neither
of the above.** They are not content to roll in; they are the preconditions that
make the declaration meaningful. Merging on a relation that is not an equivalence
is unsound before any term is hashed. Which raises the question of what evidence
the engine should want for them, and that is the next section, because the same
question has a much sharper form.

## The second prerequisite: congruence is not free

Everything above assumes that knowing `a = b` licenses replacing `a` by `b`
*anywhere*. That is the congruence property, and a congruence closure provides it
by construction — merging `f(a)` with `f(b)` the moment `a` and `b` land in one
class is not an extra feature of the algorithm, it is the algorithm.

In a system whose logic is declared rather than built in, that step is a **theorem
schema, not a given**. The repo has already measured what it costs to have it
spelled out: [metamath-import-roadmap.md](metamath-import-roadmap.md) lists among
the reasons a set.mm proof is long —

> **Congruence spelled out** — Rewriting inside a term needs a position-specific
> lemma: `oveq1d`, `oveq2d`, `fveq2d`, `breq2`, `eleq1d`, plus `eqtr*` glue

So set.mm establishes congruence one operator and one position at a time, by hand,
and the glue is a visible fraction of the corpus. An e-graph dropped on top of that
library would assume for free precisely what the library spends its bulk proving —
and, worse, would assume it for operators nobody has proved it for. Terms would
merge that the system cannot prove equal. That is an unsound digest feeding dedup,
which is the consequence the next section argues is the expensive one.

Three ways to supply congruence, and this is a decision:

1. **Trust it.** One global declaration that the equality is a congruence, in the
   `denotes_constant` idiom. Cheap, and wrong invisibly.
2. **Discharge it per operator, as a proof obligation.** The repo already has this
   machinery and this idiom: `SystemRelationObligationRow` records one obligation
   per source primitive, discharged either by a target primitive or by *a theorem
   the target has proved*, with a `status` saying whether it has been. Declaring
   congruence for `f` would incur an obligation discharged by citing `f`'s
   congruence lemma. Nothing new is invented; an existing pattern gains a second
   caller.
3. **Restrict propagation to operators that have one.** The closure pushes equality
   through a constructor only where the library supplies the lemma, and declines
   elsewhere.

**Prefer 3, mechanised by 2.** It fails closed, it needs no global act of trust,
and it has a property worth stating plainly: the theory then **grows as the library
proves congruence lemmas**. Retrieval merges exactly what the corpus has earned and
never more. That is the "evolving" character the roadmap wants from Phase 3's
embedding, arriving here instead — and arriving as a soundness argument rather than
an aspiration.

Note what this does *not* touch. An unfold is licensed by the kernel's own
definitional step at a specific position, not by congruence propagation, so the
**definitional half needs none of this**. That is a third independent reason the
split below is the right shape.

## Not confluent: the definitional half's real blocker

The roadmap treats definitional normalisation as straightforward. It nearly is,
and there is one obstacle it does not mention.

The "is defined using" relation is acyclic, so unfolding terminates. It is **not a
function**: two definitions may share a defined form. `_require_a_non_circular_definition`
says so explicitly —

> Sharing a defined form stays legal — two definitions may attach to one form,
> each its own citable axiom, as in Metamath. What is refused is the *cycle*.

So a defined form `S` with definitions `S ≝ A` and `S ≝ B` has two right-hand
sides. Unfolding `S` may reach `A` or `B`; unless `A` and `B` themselves normalise
to a common form, the term has **two normal forms and therefore two
`theory_digest`s** — and a digest that depends on which rewrite fired is not a
canonical key. Terminating is not confluent, and the roadmap conflates them.

Three ways out, and the choice is a decision rather than a consequence:

1. **Fold rather than unfold.** Normalise toward the *defined* form (`lower` →
   `higher`) instead of away from it. Attractive because it is the direction that
   shrinks a term, and because the shared-form case merges rather than diverges —
   `A` and `B` both fold to `S`, which is the answer we wanted. But folding is not
   terminating for free: the relation's acyclicity was established in the
   unfolding direction, and a `lower` that contains its own `higher` as a subterm
   is exactly what non-circularity permits when the defined form is a declared
   production.
2. **Confluence as a check, not an assumption.** Keep unfolding, and *refuse* (or
   simply decline to merge) where a shared defined form's definitions do not
   join. This is the conservative option and fits the repo's habit of failing
   closed. It needs the joinability test, which for the definitional half alone is
   decidable — both sides normalise, compare.
3. **An e-graph, which is what the roadmap actually proposed.** A congruence
   closure does not pick a winner: `S`, `A` and `B` inhabit one e-class, and the
   canonical key is the class, not a representative term. This dissolves the
   problem rather than solving it, and is the reason the roadmap named e-graphs in
   the first place — but it makes the "normalise then hash" framing wrong in a way
   worth stating, because the key is then an e-class id and e-class ids are not
   stable across rebuilds unless something makes them so.

Option 3 is probably right and has two unstated consequences: the extraction
problem immediately below, and the cost of a false merge two sections down.

## Extraction: a digest needs a representative

"Normalise to a canonical class representative before hashing" hides a step. A
congruence closure yields **e-classes**, not terms; turning one into a digest means
choosing a member, which is *extraction*, and extraction needs a total order or
cost function that does not fall out of the structure. Nor can it be dodged by
hashing the class itself: e-class ids are allocation artefacts and are not stable
across a rebuild, so a digest keyed on one would change when nothing about the
theory did.

For the AC case — the one that makes extraction sound hard — there is a clean
answer already in the codebase. An AC-normal form is "the arguments in a canonical
order", and a canonical order is available for free: **sort by the children's
existing `digest`.** Those are computed bottom-up over the interned DAG, are
already stored, and are stable by construction. So AC normalisation needs no term
order invented for it, and no Knuth-Bendix-style orientation machinery — which is
the usual reason this looks expensive.

The general case is harder and should be scoped separately; the point here is that
"then hash it" is not the trivial tail of the sentence it reads as.

## What a false merge costs, and why the bar went up

Phase 1's soundness argument had a comfortable shape: the filter could only ever
be wrong in the direction of extra work.

> a wrong fingerprint costs a redundant unify, never a bad proof

Phase 2 does not have that shape. It changes what the system *believes two
statements are*, and the roadmap lists **dedup** ("do we already have this, in any
equivalent form?") among its unlocks. A false merge there is not a slow query; it
is a claim that a theorem already exists when it does not, or that two distinct
statements are one. The roadmap's own criterion is right —

> two terms share a `theory_digest` **only if** they are provably equal under the
> recorded equalities

— but it is stated as a *test plan* (generate equal pairs and near-miss unequal
pairs, assert zero false merges on the negatives) where Phase 1 had a *proof*: a
position-local argument that compatibility holds for every unifiable pair. A
sampled test cannot establish an "only if". **This phase needs a soundness
argument of the same kind Phase 1 had, and none has been written.**

The argument is available for the definitional half, and it is the reason to build
that half first: each merge is witnessed by a chain of `unfold` steps, and `unfold`
already refuses a step whose capture proviso or side-condition fails. A merge that
is *derivable by the kernel's own definitional step* is sound by construction, and
the canonicaliser is then an optimisation of something the checker could verify —
not a second, weaker authority. That framing is what makes the definitional half
defensible; nothing analogous exists yet for the equational half, where a merge
rests on a declaration (above) that nothing checks.

Two known ways the definitional argument is not automatic, both already present in
the engine:

- **A definition may carry a `condition`.** `Definition.condition` is an optional
  proviso checked against the binding an application produces. A normaliser that
  unfolds unconditionally would merge terms whose equality holds only under a
  proviso that may not hold at the point of use. The e-graph must either carry the
  condition or refuse to use conditional definitions — decide it.
- **A definition may discard a parameter.** `F(x) ≝ ⊥` is admissible today (noted
  in [scope-aware-definitional-steps.md](scope-aware-definitional-steps.md)), so
  merging `F(a)` with `F(b)` is *correct* — both equal `⊥` — while being exactly
  the kind of collapse a "no false merges" test would be written to catch. The
  test oracle has to be the definitional theory, not intuition.

## The half nobody costed: making a match usable

Phase 1's doc is careful about this and Phase 2's section is silent on it.

> Crossing a definition is therefore a **step**, not a match: an author applies the
> definition … and *then* retrieval finds the `∀`-form theorems.

That sentence is what makes Phase 1's refusal to merge synonyms *acceptable* — the
capability is reachable, just manual. Phase 2 removes the manual step from
retrieval, and the question it raises is what the user is handed. A citation that
matches only up to the definitional theory **will not check** as a bare citation:
the proof still has to cross the gap with real definitional steps. So there are two
quite different products hiding behind "Phase 2":

- *Retrieval merges, the proof does not.* The user is offered `⊆`-form theorems for
  a `∀`-form goal and must work out the `df-ss` steps themselves. Cheap, and
  arguably worse than nothing — a proposal that does not apply is a false lead.
- *Retrieval merges and returns the bridge.* The match arrives with the chain of
  definitional steps that connects it to the goal, which the author inserts (or the
  UI inserts) before the citation. This is the useful product, and it is more work:
  the normaliser must retain *why* two terms merged, not merely that they did. An
  e-graph gives this — the explanation is the proof-producing half of congruence
  closure, and egg calls it exactly that.

**This decides the data structure.** A canonicaliser that only hashes can be a
fold; one that must explain a merge needs the e-graph with proof reconstruction.
Choosing "normalise then hash" for the digest and discovering later that the
product needs explanations is the expensive order to find out in.

## Storage and invalidation

Unspecified in the roadmap, and this session's Phase 1 experience argues for
settling it on paper. `alpha_digest` is the model to follow or to deliberately
diverge from: a nullable `String(64)` on `terms`, indexed per system
(`ix_terms_system_alpha_digest`), computed on the write path.

`theory_digest` cannot simply copy that, because unlike the other two it is **not a
function of the term alone** — it depends on the system's current theory. Proving
commutativity changes the digest of terms already stored. So:

- *What invalidates.* A new definition, a newly proven equational lemma, or an
  imported theorem changes the equivalence classes. The roadmap discusses re-folding
  for Phase 3's embedding and says nothing about re-hashing stored digests.
- *What scope.* Narrower than it first looks, and the existing storage is why. A new
  definition can only change the digest of terms that **mention its defined form**,
  and a new equation only terms mentioning that operator — so the question is
  "which stored terms contain constructor `X`", which the interned DAG answers as a
  query rather than a scan: `term_children` is the edge table the subgraph sweep
  already walks downward, and its `child_id` is indexed, so the upward closure
  invalidation wants is the same table recursed the other way. Incremental
  invalidation is therefore tractable, which matters most for the *common* case —
  introducing notation is frequent, proving commutativity is rare and has the wider
  blast radius.
- *Whether it persists at all.* The alternative is to hold the e-graph in memory per
  request and never store a theory digest — sound and always current, but paying
  saturation on the retrieval path. Given the invalidation point above, storing it
  now looks the better bet rather than the risky one; either way Phase 1's
  measurements are the precedent, since the candidate-set numbers are what justified
  W7 and an equivalent number should justify this.

A stored digest also needs the "which generation" guard Phase 1's fingerprint has
(`POSITIONS_KEY`, refusing a comparison across a change to the position set). The
analogous key here is the identity of the theory a digest was computed under, and
it is more volatile than a position set: it changes whenever anyone proves
anything.

## Decisions to take before any code

1. **How a system declares equality, and how congruence is evidenced.** The blocking
   one, and it is two halves rather than one. The declaration follows
   `denotes_constant`: a declared property on a production, parameterised by the
   sort it relates (set.mm needs `wb` *and* `wceq`), defaulted off, validated where
   the grammar can contradict it. The congruence half is separate and should not be
   folded into the same tick — prefer per-operator obligations over a global act of
   trust, per that section. Settle both against the Metamath importer as first
   caller: it already holds the equality knowledge in `EQUIVALENCES`, and set.mm
   already contains the congruence lemmas an obligation would cite.
2. **Fold, refuse, or e-graph** for the shared-defined-form case, per the
   non-confluence section. This decides whether the canonical key is a term or an
   e-class.
3. **How a representative is extracted**, given that e-class ids are not stable.
   Sorting AC arguments by the children's existing `digest` handles the case that
   looks hardest; the general case needs scoping.
4. **Whether a match must explain itself.** If retrieval returns the definitional
   bridge, the structure must be proof-producing, which is a stronger requirement
   than hashing and should be chosen up front.
5. **Conditional definitions.** Carry the proviso into the merge, or exclude
   conditional definitions from normalisation. The safe default is to exclude.
6. **Whether `theory_digest` is stored at all**, and if so what invalidates it and
   what guards a stale one.

## Recommendation

**Split the phase, and build the definitional half first.**

The two halves are presented as one and are not comparable. The definitional half
has its input in structured form — a `Definition` **is** an oriented equation in
the data, so it needs no equality declaration at all — its termination argument
already proven by the conservativity check, its binder canonicalisation already
solved by `Bound` and `alpha_digest`, no dependence on congruence (an unfold is
licensed at a position by the kernel's own definitional step), a soundness argument
available in those same terms, and it delivers the roadmap's own motivating example
(`df-ss`, the `⊆`/`∀` merge that Phase 1's boundary section holds up as the thing
syntactic search cannot do). Its blockers are decisions 2 and 4 — non-confluence
and whether a match explains itself — neither of which needs a new engine concept.

The equational half needs two prerequisites the tree does not have: a way for a
system to declare what equality is, and evidence that the equality is a congruence
for the operators being merged through. It also has no termination without a
saturation budget. It is a phase of its own and its first deliverable is decision 1,
not code.

Doing them together means the definitional merge — the valuable, defensible,
nearly-ready piece — waits on an unsolved representation question it does not need.

**What would change this recommendation:** a caller that wants `a + b` and `b + a`
merged specifically. The set.mm corpus is the obvious one to check, and the check
is cheap — two counts over theorems whose root is a declared equivalence (`wb`,
`wceq`, which the importer already knows):

- how many have two sides differing only by argument order, which sizes the *demand*
  for the equational half;
- how many are **congruence lemmas** — one side an application whose arguments are
  related by the equality (`oveq1`, `fveq2`, `eleq1` and their kin) — which sizes
  the *evidence available* to discharge decision 1's second half, and says whether
  obligation-based congruence would be mostly auto-dischargeable on a real corpus or
  mostly undischarged.

If the first number is large the equational half earns its own priority; if it is
small, the definitional half is Phase 2 and the rest is Phase 2b. Take both
measurements **before** decision 1: together they say how much the declaration has
to support and whether the obligation route is viable rather than merely principled.

## What I could not settle

Both of the findings that changed the plan arrived the same way, and neither came
from reasoning about the design. Non-confluence came from reading the
non-circularity check's docstring. Congruence came from being asked a question this
note had not thought to ask — *what happens when a library later proves
associativity, or reflexivity, for an operator?* — which is how the category split
above got written and how the assumption underneath congruence closure became
visible at all. That is the same lesson
[scope-aware-definitional-steps.md](scope-aware-definitional-steps.md) records
about `IsAtom`: the gaps are found by enumerating cases rather than by reasoning
from the design. Two passes have now each found something, which is evidence that a
third would too, not that the enumeration is complete.

The enumeration that would most likely repay a third pass is over the rest of the
**algebraic vocabulary** an author might expect to matter — idempotence, units,
absorption, distributivity, involution. Each is an equation and so should fall out
automatically by the section above, but "should fall out" is exactly the claim the
congruence finding punctured once already.

The specific enumeration still owed is over the **side-condition vocabulary**,
which that note shows is where definitional transparency goes wrong. `Occurs`
answers differently either side of a definitional equality, by design and soundly
under today's trust model. A canonicaliser that merges across that equality is a
second reader of the same divergence, and whether it inherits the problem depends
on whether a proviso is ever checked against a normalised term. It should not be —
normalisation is for the *index*, and the checker sees the term the author wrote —
but that is an invariant to state and test, not one to assume, and it is the first
thing to write down when this phase starts.
