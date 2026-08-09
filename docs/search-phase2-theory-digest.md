# Design: Phase 2, the theory-aware canonical digest

**Status:** analysed, **not built**. This note is the design
[search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md) §Phase 2
describes in thirty-one lines and does not specify. Three conclusions, in
descending order of how much they change the plan:

1. The phase is really **two** phases with very different readiness, and the
   equational one has a **prerequisite nobody has designed** — a system cannot say
   which of its productions means equality.
2. **Congruence is not free — for the equational half.** A congruence closure merges
   `f(a)` with `f(b)` whenever `a = b`, by construction; in an arbitrary declared
   logic that step is a *theorem schema*, not a given, and set.mm proves it one
   position at a time. An e-graph would assume for free what a corpus spends its
   bulk establishing. Two things follow, and they cut in opposite directions: the
   **definitional half already has congruence granted** — `_rewrites_once` descends
   through arbitrary constructors today, licensed metatheoretically and guarded by
   the conservativity checks — while the equational half must **derive** it, by
   harvesting congruence lemmas from what the library has proved rather than asking
   an author to declare it.
3. The definitional half is nearly buildable but is blocked on a smaller thing the
   roadmap does not mention: the definitional rewrite relation is acyclic but
   **not confluent**.

The first of those makes the definitional half's soundness argument *settled*
rather than merely available: a definitional merge is sound **iff** the checker
would accept the corresponding chain of definitional steps, discharged by reading
code that exists.

**Then seven experiments were run against the corpus** ("Measured", below), and
they moved the recommendation rather than confirming it. In short:

- The `definitions` table is **empty deployment-wide** — the definitional half has
  no input on the only substantial corpus, whose definitional content is 152
  primitive *axioms*, and those are **cyclic**. That forces decision 2 to the
  e-graph and undercuts "build the definitional half first".
- **Congruence is 99.84% harvestable**, so decision 1's hard half is derivation
  rather than declaration.
- A **definition-aware compositional fold works** as a construction — exact
  invariance on 147 definitions, α-invariant, nesting free, discrimination intact —
  **but loses to the unranked Phase 1 bucket at citation search** (E8). Cosine
  similarity ranks *general* schemas last, and generality is what makes a citation
  useful: similarity is not subsumption. It belongs to dedup and related-lemma
  browsing, not goal-directed retrieval.
- **Definitional reach is worth 40% more matches** (E8), so the phase's premise
  holds — collected by **bounded expansion** over the shipped index, which is exact,
  costs 2.5 ms, and keeps the subsumption semantics.
- The intended use is **retrieval, not dedup**, which removes the need for a stored
  canonical digest and the three decisions that come with it.

The recommendation was revised twice by measurement — first away from the
definitional half (E3), then away from the fold (E8). What it lands on is in
"Recommendation": extend Phase 1 with bounded definitional expansion, then build
**forward search** — the dual question, *where could this result be used*, whose
substrate (15,900 antecedent and hypothesis terms) already exists unindexed.

Phase 1 shipped ([search-phase1-fingerprint.md](search-phase1-fingerprint.md)).
This is what comes next.

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

### For definitions it is already granted, and already guarded

The definitional half is exempt, and for a better reason than "it happens not to
need it". `_rewrites_once` does not only match at the root:

> **(2) The rewrite happens strictly inside:** source and target must share a
> constructor and differ in exactly one child, where the rewrite recurses.

So a definitional step **already rewrites at arbitrary depth, through arbitrary
constructors, with no lemma required**. The checker grants itself full congruence
for definitional replacement today, and has done since before any of this was
contemplated.

That is sound for a reason worth stating precisely, because it is the whole
asymmetry between the two halves. A definition is *notational abbreviation*: the
defined form and its expansion denote the same object by fiat, so replacing one
with the other inside any context preserves meaning. The justification is
**metatheoretic**, not a claim about some object-language predicate being a
congruence — which is exactly why the conservativity work carries the weight it
does. Non-circularity and freshness are what make "it is only notation" true, and
therefore what license the unrestricted descent above.

Two consequences. The first is that the definitional half needs nothing from this
section — a third independent reason the split below is the right shape. The
second is sharper, and it settles the gap the next section opens:

> A definitional merge is sound **iff** the checker would accept the corresponding
> chain of `_rewrites_once` steps.

The canonicaliser is then an *optimisation of a decision the kernel already makes*,
not a second and weaker authority — which is the soundness argument of the kind
Phase 1 had and this note otherwise lacks. Nothing has to be built to earn it; it
is discharged by reading code that exists.

### For the declared equality: derive it, do not declare it

The equational half has no such exemption, and the useful question is what supplies
congruence with the least authoring burden. The answer is a **harvester**, and the
infrastructure for it already exists.

Scan the library for theorems of the congruence shape, per (operator, position):

```
x = y  ⊢  f(…, x, …) = f(…, y, …)
```

For set.mm that picks up `oveq1`, `oveq2`, `fveq2`, `eleq1`, `breq1` and the rest
of the family automatically — **no authoring burden at all**, and the result is
grounded in what the corpus has actually proved rather than in a tick-box. It is
the same species of classifier as `metamath/definitions.py`, which already
recognises a `$a` as a definition by its shape plus a declared equivalence.

It can also run **from rows, without parsing**: premise terms are cached beside
conclusions under `schema_digest` — `promoted_theorems.py` says the digest is what
tells whether the conclusion "and every premise term below" still means anything —
so the harvester is a structural query over stored terms. That is the
verification-from-rows arc paying off again.

**Why per-position, and not one universal rule.** The attractive alternative is to
detect a Leibniz rule — `a = b, φ(a) ⊢ φ(b)` — and get congruence everywhere from a
single check. It is not available here: `unify` is **first-order**, so a
metavariable stands for a term rather than a function, and `φ(a)` is not
expressible as a rule schema. Per-position congruence is therefore not a Metamath
quirk being inherited; it is a structural consequence of first-order schemas, and
it is why set.mm has the `oveq` family in the first place. Harvesting is not the
easier mechanism, it is the only one.

### The resulting order

1. **Harvest.** Derive congruence per (operator, position) from proven theorems.
   Free to the author, grounded in the corpus, and it is where any real library's
   evidence already is.
2. **Obligation, as the fallback.** Where harvesting finds nothing and someone wants
   the merge anyway, `SystemRelationObligationRow` is the existing idiom: one
   obligation, discharged by a theorem the system has proved, with a `status`
   saying whether it has been. An existing pattern gains a second caller rather
   than a new mechanism being invented.
3. **Global trust, only if someone argues for it.** One declaration that the
   equality is a congruence everywhere, in the `denotes_constant` idiom. Cheap, and
   wrong invisibly; listed for completeness rather than recommended.

Propagate only where evidence exists. That **fails closed** and degrades
gracefully: an operator with no congruence lemma is simply not propagated through,
and the digest is coarser rather than unsound. It also gives the phase a property
the roadmap wanted from Phase 3 — the theory **grows as the library earns it** —
except that here it arrives as a soundness argument rather than an aspiration, and
without asking anyone to write a declaration.

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
   `higher`) instead of away from it. Attractive because the shared-form case
   merges rather than diverges — `A` and `B` both fold to `S`, which is the answer
   we wanted.

   Folding still needs its own termination argument, and cannot borrow the one
   above. Acyclicity bounds *unfolding*, where each step replaces a defined form
   with material strictly earlier in the "is defined using" DAG — a descending
   measure. Folding runs those edges backwards and inherits no measure, because it
   *introduces* a defined form. (An earlier draft of this note claimed the gap was
   a `lower` containing its own `higher`; that is wrong, and
   `_require_a_non_circular_definition` refuses exactly that — found in review on
   #211.)

   The measure folding actually wants is **term size**, and it works precisely
   when every definition's `higher` is strictly smaller than its `lower` — which
   is what "a definition abbreviates" means informally. Nothing in `declarative.py`
   enforces it: a definition whose defined form is *larger* than its defining form
   would fold forever, each fold creating a new site. So the fold option is viable
   and its termination reduces to one checkable condition nobody currently checks.
   That is a much better place to be than a vague warning, and if this option is
   taken, the size condition is the first thing to add.
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
sampled test cannot establish an "only if". **The equational half needs a soundness
argument of the same kind Phase 1 had, and none has been written.**

For the definitional half the argument is not merely available but **settled**, and
it is the reason to build that half first. Each merge is witnessed by a chain of
`unfold` steps; `unfold` already refuses a step whose capture proviso or
side-condition fails; and `_rewrites_once` already licenses the descent through
arbitrary constructors that makes such a chain reach a subterm at all (above). So a
merge is sound exactly when the checker would accept the corresponding chain, and
the canonicaliser is an optimisation of a decision the kernel already makes rather
than a second, weaker authority. Nothing analogous exists yet for the equational
half, where a merge rests on congruence that has to be evidenced first.

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
analogous key here is the identity of the theory a digest was computed under.

**It must advance only on facts that change the equivalence relation** — a new
definition, a newly accepted equation, a newly harvested congruence fact — and not
on every proof. An ordinary non-equational theorem (a typing lemma, a closure
condition: most of any corpus) adds no rewrite and moves no class, so bumping the
generation for it would invalidate every stored digest on every insert and turn a
corpus import into repeated system-wide rehashing (found in review on #211). The
earlier phrasing here said the key "changes whenever anyone proves anything",
which was both wrong and inconsistent with the invalidation scope directly above:
the two must agree that the *only* interesting events are theory-changing ones.

## Measured: seven experiments against the corpus

Everything below was measured against the layered set.mm import in the deployment
database — **10,101 indexed theorems**, 207k terms — read-only, over Neon's
SQL-over-HTTPS endpoint (port 5432 is closed to the sandbox). It reproduces the
Phase 1 figures exactly (`wi` 63.7% of conclusions, 141 `wss`-headed), so the
numbers are comparable to that work.

### E1. Demand — what the equational half would buy

| | count |
|---|---|
| equational-rooted conclusions (`wb` / `wceq`) | 2,605 |
| **commutativity laws proven** (`ancom`, `orcom`, `uncom`, `incom`, …) | **13** |
| **associativity laws proven** | **8** |
| interned subterm pairs that are argument-swaps | **2,217** |
| **theorem-conclusion pairs that are root-level swaps** | **57** (0.56%) |

The 57 are real near-duplicates the corpus keeps deliberately — `bitri`/`bitr2i`,
set.mm's `r`-suffix reversed-conclusion convention.

### E2. Supply — congruence is harvestable

| | count |
|---|---|
| congruence lemmas, closed form (`oveq1`, `fveq2`, `ineq1`) | **157** |
| congruence lemmas, inference form (`oveq1i`, `fveq2i`) | **91** |
| operators covered | **99 / 110 (90%)** |
| **coverage weighted by node usage** | **99.84%** |

Every high-frequency operator is covered — `wi` (85,753 uses), `wb`, `wceq`, `wa`,
`wcel`, `wss`, `wex`, `wn`, `wal`, `cfv`, `co`, `wo`. The uncovered tail is ten
rare operators totalling ~250 uses (0.12%).

### E3. The definitional graph — and a finding that reshapes the phase

**The `definitions` table is empty across the entire deployment.** No stored system
uses the `Definition` machinery at all. set.mm's definitional content is **152
primitive axioms** rooted at an equivalence (99 `wceq`, 52 `wb`), e.g.
`df-ss  ( A ⊆ B ↔ ∀x ( x ∈ A → x ∈ B ) )`.

That matters because axioms get none of the guarantees a `Definition` row gets. And
the corpus's own content violates them:

| | |
|---|---|
| definitional axioms with a compound defined form | 151 over 150 heads |
| **cyclic heads** | **3** — `wcel`, `wceq`, `wsb` |
| cycles found | `wceq → wcel → wceq`, `wceq → wcel → wsb → wceq`, `wcel → wcel` |
| defined heads carrying two axioms | `wcel` (`df-clab`, `df-clel`) |
| **acyclic heads that fold** | **147 (147 axioms)** |

It is set.mm's class bootstrap: `df-cleq` defines `=` via `∈`, `df-clel` defines
`∈` via `=` and `∈`. Mutually recursive, sound by a metatheoretic virtual-class
argument rather than a structural one — and `_require_a_non_circular_definition`
would refuse it outright, which is very likely *why* this content lives as axioms.

**Consequence for decision 2.** Rewriting-based normalisation is blocked on the
real corpus: fold and refuse both assume an acyclicity the data violates. Only a
congruence closure is unbothered by cycles — it merges classes to a fixpoint and
never orients a rewrite. The shared-head case (`wcel`) dissolves the same way.

The containment is small: **3 heads opaque out of 150**, and they are membership,
equality and substitution — exactly the primitives one would want atomic anyway.

### E4. Bounded query expansion — tractable, and priced

Phase 1's key samples seven positions, so a rewrite below depth 2 cannot change it.
Expansion for indexing therefore only branches at those positions:

| | mean variants | p99 | worst |
|---|---|---|---|
| **cyclic heads opaque** | **7.59** | 64 | 128 |
| cyclic heads included | 20.90 | 144 | 324 |

The opacity fix is a ~3× branching reduction as well as a correctness necessity,
because `wcel` (3,986) and `wceq` (3,410) are the 2nd and 3rd most common heads at
sampled positions. 14% of goals have *no* rewritable position at all.

Server-side cost, via `EXPLAIN ANALYZE`: one Phase 1-shaped lookup is **0.33 ms**
warm, so mean expansion is **2.5 ms**, p99 **21 ms**, worst **43 ms**. Negligible
next to model latency. **Naive enumeration of equivalent whole terms is
exponential; this is not, because the index key is shallow.**

One caveat the numbers surfaced: unfolding moves a goal *toward primitives*, and
primitives are the crowded buckets. `df-or` expands a `wo` goal (43 theorems) into
`wi` (6,433 — 63.7% of the corpus). Reach is gained and head selectivity is lost,
so "expand everything" is the wrong policy; a bucket-size threshold is the knob.

### E5. The definition-aware embedding — it works

A deterministic compositional fold where an acyclic defined head's combiner returns
the embedding of its *defining* form (the roadmap's Phase 3 mechanism, applied for
Phase 2's purpose). Cyclic heads stay opaque per E3.

| | definitions | invariance |
|---|---|---|
| propositional + FOL | 16 | **16/16 at cos = 1.000** |
| ZF (700-conclusion sample, 2,976-term closure) | 131 | **131/131 at cos = 1.000** |

Including the flagship: `df-ss` scores **−0.112 blind, +1.000 aware**. And
discrimination survives — random ZF theorem pairs sit at median **+0.011**, p99
+0.789, with only **0.376%** above 0.9 (definition-blind: 0.125%). Signal 1.000
against noise 0.011.

**A methodological finding worth more than the numbers.** The first run showed
total collapse — 50% of random pairs above 0.9 — which read as "the approach does
not discriminate". It was the combiner: an unnormalised constructor bias with norm
~√D times the child contributions, so every embedding degenerated into a function
of its head symbol alone. Norm-preserving binding (permute + sign-flip) with a
small bias fixed it completely. **Collapse is the default failure mode of a
compositional fold and it fails silently** — plausible vectors encoding almost
nothing. Any implementation needs a discrimination test from day one.

### E6. α-invariance and nesting

Variable leaves numbered by first occurrence in a canonical walk, as `alpha_digest`
does. Tested against the corpus's own ground truth — 94 groups of conclusions the
`alpha_digest` column marks as α-variants:

```
worst similarity within an alpha-variant group:   +1.0000
groups failing (<0.999):                           0
definitional invariance, still:                    16/16
```

**Nesting is free, and proven rather than argued.** Building the fully unfolded
tree in memory for each conclusion and folding it definition-*blind*:

```
aware-fold(T) == blind-fold(fully-unfolded T):   1200 match, 0 differ
```

and for the `(a → X)` shape specifically, with `X` a defined form at depth 1:
`pm3.22`, `ancomd`, `jca`, `jca31`, `jca32`, `jcai` all at **cos = +1.0000**. This
is compositionality doing the work: once `emb(b ⊆ c) == emb(∀z(…))`, every
enclosing context sees identical inputs, at any depth and in any number of
positions at once. It is exactly the combinatorial cost expansion pays and the fold
does not.

One production cost this exposes: the α-numbering is *statement-relative*, so a
shared subterm carries different indices under different roots and **the memo
cannot be shared across statements**. Sharing survives within a statement, not
across the corpus — which the roadmap's "O(#distinct subterms)" claim assumes.

### E7. Forward search — the substrate already exists

"Where could this result be *used*?" is the dual of Phase 1's question, and the
rows to index are already there:

| | count |
|---|---|
| explicit hypotheses carrying a term (`promoted_theorem_premises.term_id`) | **9,453 / 9,639 (98%)** |
| implication-rooted conclusions, each with an antecedent | **6,433** |
| distinct α-shapes among those antecedents | 1,428 (mean 4.5 theorems per shape) |

Worked example — `pm3.2i` establishes `( φ ∧ ψ )`:

| | |
|---|---|
| antecedents sharing its head (`wa`) — the head filter | 1,690 |
| **antecedents α-identical to it** — the α-digest key | **123** |

So a proved result finds the 123 theorems whose antecedent it discharges exactly,
by one indexed lookup on machinery that already shipped. See "Forward search"
below.

### E8. Retrieval quality against a matching oracle — and the fold fails it

The oracle has to be chosen carefully. A *syntactic* match oracle is the wrong
ground truth: Phase 1's filter achieves 100% recall against it by construction, and
the definitional matches this phase exists to find are not in it at all. So the
oracle is **match after full definitional unfolding**:

```
GT(goal) = { thm : match(unfold*(thm.conclusion), unfold*(goal)) }
```

matching one-directionally, as a citation is checked — the theorem's conclusion is
the schema whose variables bind, the goal is rigid. 60 sampled goals against all
2,656 conclusions.

**First, the premise is confirmed.** Definitional unfolding adds **40% more
matches** (1,883 syntactic → 2,631 up-to-definitions). The value this phase is
chasing is real.

**Second, the fold does not deliver it.** Precision at k — of what you would put in
front of a model, how much actually applies:

| | embedding-ranked | Phase 1 head bucket, unranked | random |
|---|---|---|---|
| @10 | 38.7% | **46.3%** | 6.2% |
| @25 | 35.9% | **40.3%** | 7.0% |

And ranking *within* the Phase 1 bucket — the only way the fold could earn a place
in goal-directed retrieval — does not help either:

| | embedding-ranked | unranked |
|---|---|---|
| precision@5 | 43.1% | 39.0% |
| precision@10 | 39.2% | **46.3%** |
| rank of first applicable theorem | median 0, **mean 42.0** | median 4, **mean 2.5** |

**Third, the diagnostic says why, and it is structural rather than a tuning
problem:**

```
least general quartile (few variables / size):   mean rank    509
most  general quartile (many variables / size):  mean rank  1,555
```

**Generality pushes a true match down the ranking threefold — and generality is
exactly what makes a citation useful.** A schema like `( φ → ψ )` applies to a huge
number of goals precisely because its metavariables stand for anything; in the fold
those metavariables contribute *random vectors*, so the schema is structurally
dissimilar to any particular goal. The embedding is bimodal: rank 0 when a
near-identical statement exists, buried when the useful citation is a general
schema.

The root cause in one line: **similarity is not subsumption.** Goal-directed
retrieval asks which theorem's conclusion *generalises* my goal — an asymmetric,
order-theoretic relation. Cosine distance is symmetric and measures likeness. The
fingerprint gets this right by construction (a variable at a sampled position is
compatible with *everything*), which is why it beats the fold on its own task.

If an embedding is ever wanted for subsumption, the fix is not a better combiner
but a different geometry: **asymmetric embeddings** — order, box, or cone
embeddings — are designed for entailment hierarchies. Cosine is the wrong tool and
no amount of combiner tuning repairs it.

### What the eight settle

- **Congruence is harvestable** (E2), so decision 1's second half is derivation, not
  declaration, and obligations demote to a 0.12% formality.
- **The equality declaration is two entries**, not one per operator (E1/E2).
- **Decision 2 is forced to the e-graph** (E3) — the corpus is cyclic, and fold and
  refuse both assume otherwise.
- **The cyclic containment is cheap and helps twice** (E3/E4): 3 heads opaque, and a
  3× branching reduction.
- **Bounded expansion is affordable** (E4), so the exponential objection does not
  apply at this index depth — but it lands in crowded buckets.
- **The embedding delivers exactly the invariance hypothesised** (E5/E6), is
  α-invariant, handles nesting for free, and keeps discrimination — **and is still
  the wrong mechanism for goal-directed retrieval** (E8), because similarity is not
  subsumption. It belongs to the similarity tasks: dedup, "have we got this",
  related-lemma browsing.
- **Definitional reach is worth 40% more matches** (E8), so the phase's premise
  holds; what changes is which mechanism collects it — bounded expansion, which
  preserves subsumption semantics, rather than the fold, which inverts them.
- **The equational half's demand is thin on set.mm** (E1) — 57 conclusion pairs —
  though that is corpus-specific and mathlib would very likely differ.
## The shape the measurements suggest: retrieval, not a stored digest

The phase has been framed around producing one canonical form per statement, which
serves **dedup** — "do we already have this?". The stated use is different:
LLM-driven ingestion, authoring on top of an imported corpus, and search over it.
That is **retrieval**, and retrieval wants recall: a model can discard an
irrelevant suggestion, but cannot recover a lemma it was never shown.

Under that reading the design changes shape:

> Use the theory at **query time**, and let the Phase 1 index stay the lookup
> layer. Do not compute and store a canonical digest for every theorem.

That dissolves three of the open questions below rather than answering them —
extraction has nothing to extract for, nothing new is stored, and nothing goes
stale when someone proves something. It also suits a corpus under constant
LLM-driven growth, where a stored digest would be re-hashing continuously.

Two mechanisms could serve it, and E4–E6 measured both — then **E8 settled which**:

- **Bounded query expansion (E4)** — exact, 2.5 ms at mean branching, and it keeps
  the subsumption semantics goal-directed retrieval depends on, because a variable
  at a sampled position is fingerprint-compatible with everything. Inherits the
  crowded-bucket skew, so it wants a size threshold. **This is the one to build.**
- **The definition-aware fold (E5/E6)** — linear, α-invariant, nesting-free, exact
  invariance on 147 definitions. But E8 measured it against a matching oracle and it
  **loses to the unranked Phase 1 bucket** (39.2% vs 46.3% precision@10), because
  cosine similarity ranks *general* schemas last and generality is what makes a
  citation useful. It belongs to similarity tasks, not citation search.

## General equations: the ceiling, and the ways round it

The fold absorbs definitions because a definition is a **local edit to one
combiner**: `f(a,b) ≝ RHS` is served by redefining `C_f` to fold the RHS. Nothing
else changes, which is why nesting is free (E6).

A general equation is not a redefinition but a **constraint**. Distributivity
`A ∪ (B ∩ C) = (A ∪ B) ∩ (A ∪ C)` would require

```
C_∪(a, C_∩(b,c))  =  C_∩(C_∪(a,b), C_∪(a,c))     for all a, b, c
```

a functional equation binding two combiners jointly, with `∪` on both sides in
different arrangements. There is no substitution for `C_∪` that satisfies it.

And the general case is not merely hard. The equivalence generated by an arbitrary
equational theory is **undecidable**; a fold is a total, terminating, local
function that decides equality by computing a value. A total computable function
cannot decide an undecidable relation, so **exact coverage is impossible in
principle**.

The boundary is crisp, and worth designing against:

> A fold can absorb a law that is a property of **one** operator. It cannot absorb
> a law relating the **arrangement of two**.

| law | achievable | how |
|---|---|---|
| definitions | ✓ *measured* | redefine that combiner (E5) |
| commutativity | ✓ | symmetric combiner (sum/max pooling) |
| associativity | ✓ | flatten to n-ary, associative combiner |
| AC together | ✓ | multiset pooling |
| idempotence | ✓ | dedupe before pooling |
| unit laws | ✓ | combiner drops the identity argument |
| distributivity, absorption, De Morgan | ✗ | no local rule exists |
| most of mathlib's `simp` set | ✗ | same reason |

Five ways round it, in rough order of cost:

1. **Restrict scope honestly.** Cover definitions + AC + units exactly; document the
   rest as out of scope. Given E1 (13 commutativity, 8 associativity laws on
   set.mm), this may be sufficient until another corpus arrives.
2. **Hybrid.** Fold for recall, exact machinery beside it. Uncovered equations
   simply do not improve recall; nothing breaks. Costs nothing extra.
3. **Bounded equation-aware expansion.** Rewrite the goal a few `simp`-style steps
   and embed each variant. Partial coverage, bounded cost, composes with the fold.
4. **Normalise, then embed.** An e-graph handles the global theory; the fold
   vectorises its representative. Principled, and reintroduces the e-graph's cost
   and its extraction decision.
5. **Learned combiners under a hard invariance constraint.** Keep the proven
   invariances architecturally and *learn* the residual, contrastively — **the
   corpus self-labels**, since every `wb`/`wceq` theorem is a positive pair. This is
   realistically the only route by which thousands of heterogeneous `simp` rules
   ever reach the geometry; nobody hand-encodes those into combiners.

**Recommended: 1 now, 2 always, 5 when a curated rewrite corpus (mathlib) lands.**

## Forward search: where could an established result be used?

Phase 1 answers *backward* — which theorems could conclude my goal. The **forward**
question is the one an author or an agent asks after proving something: *I have
established a formula of this shape; where does it get me?* It matters for the
stated intent, because attacking an open problem is forward chaining, and "what
does this unlock" is how a proved lemma earns its place.

**It is the same machinery pointed at a different column**, and E7 shows the rows
are already there: 9,453 explicit hypotheses carry a term (98% of them), and 6,433
implication-rooted conclusions each carry an antecedent. Together that is ~15,900
indexable *input* positions beside the 10,101 output positions Phase 1 indexes.

The three layers already built or designed answer three strengths of the question:

| question | mechanism | status |
|---|---|---|
| which theorems take **exactly** this, up to renaming? | `alpha_digest` on the antecedent | Phase 0, shipped |
| which take something this is an **instance** of? | fingerprint filter + `match` confirm, on antecedents | Phase 1 machinery, new column |
| which take something this is **definitionally** equal to? | the definition-aware fold (E5) | this phase |

E7's worked example makes the middle column concrete. `pm3.2i` proves `( φ ∧ ψ )`;
1,690 antecedents share its head, and **123 are α-identical to it** — one indexed
lookup finds the theorems it discharges outright. Across the corpus the α-key is
selective: 6,433 antecedents fall into 1,428 distinct shapes, 4.5 theorems apiece.

Two cautions the measurement raises. **27.5% of antecedents are a bare
metavariable** — they match anything, so they are in every candidate set and rank
last on informativeness. And the forward direction wants *matching*, not equality:
the theorem's antecedent must be **more general than** the established result, a
one-directional test `unify.match` already performs and the fingerprint already
filters soundly for.

Nothing here needs a new index type — it needs the existing fingerprint written for
antecedent and hypothesis terms, and a route that reads it. That makes forward
search a materially cheaper follow-on than the rest of this phase, and arguably the
highest-value one for an agent-driven workflow.

## Decisions to take before any code

1. ~~**How a system declares equality, and how congruence is evidenced.**~~
   **Settled by the measurements above.**

   *The declaration:* a declared property on a production, `denotes_constant`
   idiom, parameterised by the sort it relates, defaulted off. It cannot be derived
   — nothing structural separates `↔` from `→`, and the measurement does not rescue
   inference, since `wi` heads congruence lemmas too (as the implication of the
   closed form). But it is **two entries** for the whole set.mm import, so the
   burden is trivial. Validate what can be validated: binary, both slots the same
   sort, and — newly available — **cross-check against the harvest**, since a
   production declared an equivalence should head some congruence lemmas, and one
   heading none is a mis-tick worth warning about. The Metamath importer is the
   first caller and stops needing its hardcoded `EQUIVALENCES`.

   *Congruence:* **harvest it**, per (operator, position), from proven theorems in
   both the closed and inference shapes — 99.84% coverage by node usage, zero
   authoring burden. Keep the obligation route as the documented fallback for the
   0.12% tail, and drop global trust entirely; the data makes it unnecessary.

   Both are cheap and independently useful — the harvester in particular is a
   standalone classifier answering "which operators does this system have
   congruence for", which proof search will want and an importer can validate
   against. Neither commits to building the equational half, which the demand
   figures argue against doing yet.
2. ~~**Fold, refuse, or e-graph**~~ **Settled by E3: e-graph, and it is forced.**
   The corpus's definitional axioms are genuinely cyclic (`wceq → wcel → wceq`), so
   fold and refuse both assume an acyclicity the data violates; only a congruence
   closure is indifferent to cycles. The shared-head case (`wcel`, two axioms)
   dissolves the same way. **With one containment that does most of the work:**
   leave the 3 cyclic heads opaque — cheap (3 of 150), defensible (they are
   membership, equality, substitution), and worth a 3× branching reduction on top
   (E4). If the scope ever narrows to authored systems with `Definition` rows, the
   engine enforces acyclicity there and the cheaper options return.
3. **How a representative is extracted** — *deferred, and possibly moot.* It only
   arises if a canonical digest is stored, which the retrieval framing above
   argues against. Should a digest be wanted, sorting AC arguments by the
   children's existing `digest` handles the case that looks hardest.
4. **Whether a match must explain itself.** If retrieval returns the definitional
   bridge, the structure must be proof-producing, which is a stronger requirement
   than hashing and should be chosen up front. Still open, and now the *first*
   question for whichever mechanism is built: the fold gives a similarity with no
   witness, so if an agent needs the connecting steps, that is an argument for
   expansion over embedding on those queries.
5. **Conditional definitions.** Carry the proviso into the merge, or exclude
   conditional definitions from normalisation. The safe default is to exclude.
6. ~~**Whether `theory_digest` is stored at all**~~ — *recommend not*, per the
   retrieval framing. Query-time use keeps the theory always-current and removes
   invalidation entirely. Revisit only if exact dedup becomes a requirement.

## The option that makes congruence moot

Worth naming before the recommendation, because it is not merely a smaller version
of the phase and might be the right permanent answer.

**Never merge on object-language equality at all.** `theory_digest` is the
definitional normal form and nothing else; proven equations feed *ranking* — a
candidate whose conclusion is an equational variant of the goal sorts higher —
rather than identity. Under that design:

- congruence never arises, because the only merges are definitional and those are
  already licensed (above);
- the equality declaration is not needed either, since a `Definition` carries its
  own orientation;
- the `⊆`/`∀` merge still lands, which is the roadmap's own motivating example and
  the thing Phase 1's boundary section holds up as what syntactic search cannot do;
- and dedup keeps a meaning that is defensible — "already proved, up to notation"
  — rather than one resting on an unevidenced congruence.

What is given up is `a + b` merging with `b + a` *as one statement*. Whether that
is a loss depends entirely on how often a real corpus contains such pairs, which is
the measurement the recommendation asks for. If the answer is "rarely", this is not
a stepping stone toward the equational half — it is the finished feature, and the
equational half is a Phase 3 idea that should be argued for on its own evidence.

## Recommendation

**Extend Phase 1 with bounded definitional expansion, and build forward search
beside it. Do not use the embedding for citation search.**

This is the second revision, and the second one the data forced. The note first
recommended building the definitional half; E3 undercut that (no `Definition` rows
exist). It then recommended the definition-aware fold as the retrieval mechanism;
**E8 refutes that too** — the fold loses to the unranked Phase 1 bucket on the very
task it was proposed for. What survives:

1. **The premise holds.** Definitional reach is worth **40% more matches** (E8), so
   there is real value here and it is worth collecting.
2. **Bounded expansion collects it and the fold does not** (E4/E8). Expansion is
   exact, costs 2.5 ms at mean branching, and preserves the subsumption semantics
   citation search depends on. The fold inverts them: cosine ranks general schemas
   last, and general schemas are the useful citations.
3. **The fold is still worth having — for other work.** Its measured invariance
   (E5/E6) is real: exact on 147 definitions, α-invariant, nesting free. That makes
   it right for **dedup, "have we got this", clustering, related-lemma browsing** —
   symmetric similarity tasks — and wrong for asymmetric subsumption.
4. **Forward search is cheap and unbuilt** (E7): 15,900 indexable input positions
   already carry terms, and the α-key alone finds 123 exact consumers for a sample
   result. For an agent-driven workflow this is plausibly the highest value per unit
   of work anywhere in the phase.
5. **Retrieval, not dedup, is the use** — so a stored canonical digest, and the
   three decisions it drags in, remain avoidable.

Order: bounded expansion over the Phase 1 index (cyclic heads opaque, bucket-size
threshold), then forward search over antecedents and hypotheses, then the harvester
(E2) whenever the equational path is taken up. The e-graph is settled as the
*structure* for that path (decision 2) but is not the first thing to build. The
fold is a separate, later feature aimed at similarity, and if it is ever wanted for
subsumption it needs an asymmetric geometry (order/box embeddings), not a better
combiner.

The original split argument follows, for the authored-systems case where it still
holds.

**Split the phase, and build the definitional half first.**

The two halves are presented as one and are not comparable. Everything the
definitional half needs, it already has:

| what it needs | where it already is |
|---|---|
| an oriented equation | a `Definition` **is** one in the data — no equality declaration |
| termination | the conservativity check's acyclic "is defined using" relation |
| binder canonicalisation | `Bound` is index-canonical; `alpha_digest` hashes it |
| congruence | `_rewrites_once` already descends through arbitrary constructors, licensed metatheoretically and guarded by conservativity |
| a soundness argument | sound **iff** the checker accepts the corresponding chain of definitional steps |

And it delivers the roadmap's own motivating example — `df-ss`, the `⊆`/`∀` merge
that Phase 1's boundary section holds up as the thing syntactic search cannot do.
Its remaining blockers are decisions 2 and 4, non-confluence and whether a match
explains itself, neither of which needs a new engine concept.

The equational half needs one prerequisite the tree does not have and one it can
derive: a way for a system to **declare** what equality is, which nothing
structural can supply, and **evidence of congruence** for the operators being
merged through, which a harvester can. It also has no termination without a
saturation budget. It is a phase of its own, its first deliverable is decision 1
rather than code, and the section above argues it may not be wanted at all.

Doing them together means the definitional merge — the valuable, defensible,
nearly-ready piece — waits on an unsolved representation question it does not need.

**Both measurements have now been taken** (see above), and they sharpen this rather
than overturning it. The equational half's demand is thin — 57 conclusion pairs in
a 10,101-theorem corpus — so it does not earn priority over the definitional half.
The congruence half of its prerequisite turned out to be cheap rather than
blocking, at 99.84% harvestable coverage, which is a good reason to build the
*harvester* early but not a reason to build the e-graph that would consume it.

**What would still change the recommendation:** a direct measurement of *retrieval*
rather than dedup. The 2,217 subterm swap-pairs say a goal written the other way
round can miss, but nobody has measured how often that actually happens to an
author. If it is common, the equational half is a usability fix rather than a dedup
feature, and should be argued on that ground.

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
