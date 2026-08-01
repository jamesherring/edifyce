# Relationships between formal systems: analysis and roadmap

**Status:** design. Nothing here is built. `formal_systems.inherits_from_id`
exists, is validated on write, and is read by nothing — `app/routers/systems.py`
says so in as many words ("inheritance is not resolved yet … deferred to the
inheritance phase"). This is that phase, plus the two things it turns out to be a
prerequisite for.

Goal: express and store the relationships between formal systems well enough that

- **(a)** a theorem proved in propositional calculus is citable in a proof in
  first-order logic *and* in ZFC;
- **(b)** a theorem proved in FOL is citable in a proof in ZFC;
- **(c)** sequents and the deduction theorem are expressible in FOL/ZFC;
- **(d)** the Metamath importer can split `set.mm` across those systems and keep
  every citation resolving.

The organising claim of this note: **(a) and (b) are one mechanism, (c) is a
second, and (d) is the two of them driven from a corpus.** The two example
relationships the brief names are of different *logical* kinds but the same
*mechanical* kind; the genuinely different mechanism is the one (c) needs, and
designing for all three at once costs one extra table.

---

## 1. The two relationships, stated precisely

### 1.1 Propositional calculus ⊂ first-order logic — a **language** extension

FOL adds *syntax*: sorts (`setvar`, `class`), a binder (`∀`), predicates (`=`,
`∈`). The sort `wff` keeps its name and grows: it had `¬φ` and `(φ → ψ)`, it now
also has `∀x φ` and `x = y`. Every axiom FOL adds is *about the new vocabulary*
— `ax-4` is about `∀`, `ax-8` about `∈` — and none of them says anything new about
`→` or `¬`.

What this does to a transferred theorem is the interesting part. PC proves
`⊢ (φ → φ)` where `φ` ranges over *propositional* formulas. Re-read in FOL, the
same sentence quantifies over *more*: `φ` may now be `∀x ψ`. The transfer
therefore **strengthens** the theorem, and needs an argument:

> The PC derivation is *uniform in `φ`*. It cites `ax-1`, `ax-2`, `ax-3` and
> `ax-mp`, each of which is schematic in FOL over the whole of FOL's `wff`. So
> the derivation replays verbatim with `φ` instantiated to any FOL formula.

That is the **schematicity obligation**, and §2 is where it gets discharged.

### 1.2 First-order logic ⊂ ZFC — a **theory** extension

ZFC adds essentially no logical vocabulary. In `set.mm`'s actual layering the
class machinery (`cv`, `wceq`, `wcel`) is declared in Part 1, *with* predicate
calculus, precisely so that the set-theory part changes the grammar as little as
possible: Part 2 contributes the class abstraction `{ x | φ }` and the
definitional apparatus, and everything else it contributes is **axioms** —
extensionality, replacement, power set, union, regularity, infinity, choice.

Nothing about a FOL theorem is reinterpreted on the way in. `⊢ (∀x φ → φ)` means
in ZFC exactly what it meant in FOL. The transfer is sound by *monotonicity*:
adding axioms never removes theorems. There is no obligation to discharge.

The direction that is *not* free is the reverse one, and it is worth recording
because it is the thing the split exists to make visible: FOL ⊂ ZFC is **not
conservative**. ZFC proves `∃x ∃y (x ≠ y)` — an `∈`-free sentence — from pairing
and extensionality, and FOL does not. A syntactic test ("every added axiom
mentions a symbol the parent lacks") is *necessary* for conservativity and not
sufficient, so this note does not try to check conservativity anywhere. It is
recorded as a claim about a relationship, never inferred.

### 1.3 The difference, and what it buys

| | PC → FOL | FOL → ZFC |
|---|---|---|
| grammar | grows a lot: new sorts, a binder, predicates | grows a little: one abstraction + definitions |
| axioms over *shared* vocabulary | none | none stated, but new shared-vocabulary theorems follow |
| what a transferred statement needs | re-composition at a **wider** sort | re-composition, meaning unchanged |
| soundness argument | schematicity (§1.1) | monotonicity |
| conservative over the parent? | yes | **no** |
| reverse transfer | only for parent-vocabulary statements, and only under conservativity | never |

**Mechanically the two edges are identical**: an identity translation on notation
and sorts, under which the child's primitives contain the parent's. The
difference is metadata and risk, not code path. Inventing two mechanisms here
would be inventing a distinction the checker cannot see.

The distinction that *is* mechanical arrives with (c) — see §5. A Hilbert-style
FOL and a sequent-style FOL are related by a **translation**: `⊢ φ` becomes
`Γ ⊢ φ`. That is not the identity on statements, it needs a proof obligation per
Hilbert axiom, and it is the case that forces the general edge.

So: **two kinds, not three.**

- **`extension`** — identity translation, the child's parts *contain* the
  parent's. Covers PC → FOL and FOL → ZFC, and is what `inherits_from_id` has
  always been trying to mean.
- **`interpretation`** — a translation: a sort map, a notation map, a statement
  template, and one discharged obligation per parent primitive. Covers
  Hilbert → sequent, and any pair of systems built independently rather than by
  layering.

---

## 2. The one rule that makes transfer sound

Everything below rests on a single rule, and it is worth stating before the
design so the design can be read as serving it:

> **A theorem transfers along an edge only when every primitive of the source is
> a primitive of the target, or is discharged by a theorem of the target with the
> same schematic generality.**

For an `extension` edge this holds **by construction, not by check** — provided
the child is built by *inheriting* the parent's rows rather than by copying them.
If FOL's `ax-1` is literally PC's `ax-1` row, read into FOL's build, then a PC
derivation *is* a FOL derivation and there is nothing to verify. This is the same
shape of argument as the non-circularity of definitions in `declarative.py`: the
construction rules out the failure rather than detecting it.

The corollary is the design constraint that matters most:

> **Transfer is permitted along an inheritance edge, or along an `interpretation`
> edge whose obligations are discharged. It is never permitted between two
> systems that merely look alike.**

A child assembled by copy-paste of a parent's grammar gets no transfer. That
refusal is the point: the copy could drift, and nothing in the schema would say
so.

Two secondary obligations follow from sort widening, both of which the engine
already enforces in the right direction:

- **A metavariable's sort may only widen.** The child's sort must admit at least
  what the parent's did. Under inheritance this is automatic — the child's `wff`
  union is the parent's branches plus more, and `Constructor.admits` is a
  superset by construction.
- **A proviso keeps its sort argument.** `disjoint` is sort-restricted
  (metamath roadmap §1.2), so a `$d` transferred into a wider sort still
  constrains the leaves it was written for. Widening a sort makes a proviso
  constrain *more* instances, never fewer.

---

## 3. What already exists — do not rebuild

The pleasant finding of this survey is that the transfer mechanism is almost
entirely present, in a form that happens to be exactly right.

**A promoted theorem is already declarative and system-free.**
`promotion.TheoremSpec` is label + statement text + `{metavariable: sort name}` +
premises + `$d` provisos + a matching mode. It carries no engine object. That is
*precisely* what has to cross a system boundary: to make a PC theorem citable in
ZFC you take its `TheoremSpec`, apply the edge's sort map, and call
`promote_spec` against the **ZFC** system. `promote_from_source` parses the
statement against whatever grammar it is handed, so a widened sort is not a
special case — it is the ordinary case.

**Citations already resolve by label, lazily.** `Proof.get_reference` looks a
citation up in `formal_system.promoted_theorems`, which `app/routers/proofs.py`
fills on demand: `cited_labels` reads the labels off the proof's own lines and
`load_theorems` promotes exactly those. Nothing walks a library. Extending
lookup to a parent system is therefore a change to *one query* — the `IN` clause
gains the ancestor chain — and **no change at all to the engine's resolver**.

**The proof text does not have to change.** A ZFC proof citing `[ax-mp, 3, 4]`
cites a bare label. If `ax-mp` resolves through the edge, the source is
byte-identical to what the importer emits today. This is the single strongest
argument for resolving through the edge rather than copying rows into the child
(§4.2).

**Scoped subproofs with discharge already exist.** `SubproofSchema`,
assumption/variable scopes, scope-checked references, eigenvariable freshness —
`docs/scoped_subproofs.md`. This is natural deduction, and it is *not* the same
thing as sequents; §5 says why, and why it is still relevant.

**The staleness contract already exists.** `schema_digest` /
`library_digest` / `theorem_digest` say when a cached term still describes the
system. Widening the digest to cover the inheritance chain is a one-line change
to `library_digest`'s input, and gives correct invalidation for free.

**The corpus walk already scopes notation by position.** `corpus.walk` admits a
production at the assertion that declares it, so "checked against only what
precedes it" is enforced. Splitting the corpus into layers is a coarsening of a
scoping discipline that is already finer than it needs to be.

**What is missing:**

- `inherits_from_id` is stored and never read (`systems.py:558`).
- Its write-time guard rejects only *self*-inheritance; a longer cycle is
  accepted. `graphs.topological_order` is right there.
- There is no route that promotes a *user's* proved proof into its system's
  library. `promoted_theorems` is written only by the importer, and
  `proofs.theorem_id` only by `_link_proofs_to_theorems`. So (a)/(b) are today
  unreachable for anything a person proves.
- `_require_owned_reference` means you may only inherit from a system **you own**
  — which locks every user out of building on an imported, ownerless corpus.
- Metamath's section structure is discarded: `parser._strip_comments` throws away
  the `$( … $)` blocks that carry `set.mm`'s outline, and the outline is the only
  thing in the file that says where propositional calculus ends.

---

## 4. The design

### 4.1 The spine — inheritance resolved

`inherits_from_id` finally means something: **the child's effective system is its
ancestors' parts followed by its own.**

```
effective_spec(system) = concat(spec(ancestor_n), …, spec(ancestor_1), spec(system))
```

Concretely, a new `app.db.systems_mapping.effective_spec(system, ancestors)` that
concatenates `productions`, `lines`, `definitions`, `axioms` and `rules` in
ancestor-first order and merges sorts **by name** — `SystemSpec.productions`
already names its sort by string, so a child adding `∀x φ` to `wff` needs only to
say `sort="wff"`, and the union it lands in is the one the parent declared.
`build_spec` then sees one flat spec and neither it nor the kernel learns a new
concept. `system_to_spec` keeps its current meaning (this system's *own* parts),
because that is what the parts CRUD edits and what the API renders.

Rules this imposes, each of which is a guard to write:

| Rule | Why |
|---|---|
| A parent must be **published** (frozen) before a child may inherit from it | A parent edit changes every descendant's grammar, invalidating every proof beneath it. Publishing is already a one-way door and already blocks edits. |
| Inheriting from an **unpublished** system is refused; inheriting from a **published** one is allowed regardless of owner | Today's owned-only rule would make the imported corpus uninheritable, which is the whole point of (d). |
| The chain must be **acyclic**, checked transitively | The current guard catches only `parent == self`. |
| A name declared by both a child and an ancestor is an **error** — except a sort union, which merges | `_shadowed_grammar_names` already treats shadowing as digest-relevant; across an inheritance chain, silent shadowing would let a child redefine a parent's `→`, and every transferred theorem would then mean something else. |
| A child that declares no `lines` uses its ancestors' | Otherwise every layer must restate `|- wff`. |
| The digest covers the whole chain | `library_digest` / `schema_digest` take `effective_spec`, so a stale cache is a miss rather than a wrong answer. |

Two consequences worth predicting, because both are the engine's existing checks
firing across a boundary they have never seen:

- **`_validate_constant_declarations` may refuse a child.** A production declared
  `denotes_constant=True` in the parent, in a sort that a *child's* new binder
  ranges over, is refused when the child builds. This is correct and it fails in
  the safe direction (a refused build, not a capturing definition) — but it means
  a parent that built alone can have a child that does not build, and the error
  message needs to say which layer introduced the binder.
- **`_require_a_fresh_defined_form` gets stricter.** A child's definition must now
  be fresh with respect to the *ancestors'* axioms and rules too. Also correct,
  also a behaviour change, also needs to name the layer.

### 4.2 The library through the chain — (a) and (b)

`app/db/promoted_theorems_mapping.read_theorems` currently filters
`system_id == <one system>`. It gains the chain:

```
read_theorems(session, system_ids=[child, …, root], labels, …)
```

resolved **nearest-first** — a label defined in both a child and an ancestor
resolves to the child's. Each entry remembers which system it came from, and
`load_theorems` promotes it against the **child's** built system via
`promote_spec`, applying the edge's sort map (the identity, on an `extension`
edge). `cited_labels` is untouched; `Proof.get_reference` is untouched;
`app/routers/proofs.py` changes by passing a list where it passed an id.

That is the whole of (a) and (b) for imported and promoted theorems.

**Why re-promotion, not row-copying.** The alternative — materialise every
ancestor's `promoted_theorems` rows into the child when the edge is created — was
considered and rejected:

| | resolve through the edge | copy rows into the child |
|---|---|---|
| rows for a 3-layer set.mm | 49k, once | up to 3× |
| provenance | the row's `system_id` *is* the answer | needs a new column to not lose it |
| a parent gaining a theorem | visible immediately | needs a re-sync |
| proof source | unchanged | unchanged |
| cost per citation | one parse, cached under a digest | none |

The parse cost is the only column the copy wins, and the existing term cache
already collapses it: a cross-layer citation composes its statement against the
child's grammar **once**, and the term is stored in the child's term graph under
`theorem_digest`. The row it is stored against is the child's, so this is a
cache, not a duplicate record.

**What is genuinely re-derived, and why it must be.** A PC term and a FOL term are
not the same kernel object even when they render identically: `wi`'s constructor
in PC has slot sorts pointing at PC's `wff` union, and in FOL at FOL's. Terms are
interned per `formal_system_id`, so a transferred statement gets its own row in
the child's graph. That is not waste — it is the sort widening, made physical.

### 4.3 Promoting a proved proof — the missing half of (a)/(b)

Today only an import writes `promoted_theorems`. For a person to reuse their own
PC lemma in ZFC, a proof must be able to *enter* its system's library:

`POST /api/proofs/{id}/promote` → writes a `promoted_theorems` row from the
proof's conclusion and sets `proofs.theorem_id`. Guards: the proof must be valid,
warning-free (`_is_usable_lemma`'s test) and owned; re-promoting after an edit
replaces the row; invalidating the proof retires it.

The first cut promotes the conclusion **as stated** — a ground theorem, which
`promote_from_source` already supports and documents (`2 e. RR` justifies itself
and nothing else). Schematic promotion — the author nominating which leaves are
metavariables and at which sorts, so `⊢ (φ → φ)` is proved once and cited at
every instance — is a second cut, and is where the interesting UX is. Both write
the same `TheoremSpec`, so the storage does not change between them.

### 4.4 The general edge — `system_relations`

The spine handles layering. It cannot express: a second parent, a sort rename, a
notation map, or a statement translation. Those arrive with (c), and one table
covers all of them.

```
system_relations
  id
  source_system_id          -- where the theorems are proved
  target_system_id          -- where they become citable
  kind                      -- 'extension' | 'interpretation'
  statement_template        -- NULL = identity; else e.g. '{Γ} ⊢ {0}'
  status                    -- 'draft' | 'discharged'
  position
  unique (source, target)

system_relation_sorts       -- the sort map; empty = identity on names
  relation_id, source_sort, target_sort

system_relation_symbols     -- the notation map; empty = identity on names
  relation_id, source_symbol, target_symbol

system_relation_extras      -- metavariables the template introduces
  relation_id, name, sort   -- e.g. Γ : context

system_relation_obligations -- one per source primitive
  relation_id
  source_label              -- the axiom/rule being discharged
  discharged_by_theorem_id  -- a promoted_theorems row in the target, or
  discharged_by_primitive   -- a label of the target's own rules
  status
```

An `extension` edge is the degenerate case: no template, empty maps, and every
obligation `discharged_by_primitive` with the same label — which under
inheritance is filled in automatically and never asked of an author. `status`
gates transfer: a `draft` edge resolves nothing.

The spine stays as `inherits_from_id` rather than being folded into this table.
It is already in `app/schemas.py`, `frontend/src/lib/api.ts` and the systems UI;
it is single-parent, which is what a *grammar* tower wants; and it is the case
that must be checkable by construction. Reading it as an implicit `extension`
edge with identity maps costs nothing and keeps the general table for the cases
that need it.

### 4.5 Provenance — what a proof actually depends on

A free consequence of the split, worth building because it is the check on
whether the partition is right: for any proof, the **deepest layer it actually
uses** is a query over `proof_line_antecedents` joined to `promoted_theorems`,
following the transitive citation graph. A ZFC proof that touches nothing above
PC *is* a PC proof, and should say so. Run over an imported corpus it also
validates (d): a theorem the layer plan puts in FOL that depends on a ZFC axiom
is a misfiled theorem, and this finds it.

---

## 5. Sequents and the deduction theorem — (c)

### 5.1 What is already there, and why it is not this

Edifyce has **natural deduction**: `scope: assumption` opens a subproof, a
discharge rule consumes it whole, references are scope-checked, eigenvariables
are checked fresh. `→I` is expressible today and needs nothing new.

That is not sequents. In a subproof the assumption context is a property of the
*proof*, not of the *statement*: there is no term denoting `Γ`, so you cannot
weaken it, cite it, quantify over it, or state a theorem *about* it. The
deduction theorem, in that setting, is not a rule — it is the discharge mechanism
built into the checker.

And for a **Hilbert-style** FOL — which is what `set.mm` is, and what (d) will
import — `→I` is *not a primitive rule at all*. Adding it as one would be adding
an unjustified rule; it is admissible, by a metatheorem (induction over
derivations) that Edifyce has no way to state and, on the evidence of
`docs/scope-aware-definitional-steps.md`, should not try to state as a special
case in the kernel.

### 5.2 The recommendation: a sequent system is a *system*

Declare a sequent FOL as an ordinary Edifyce system — no engine change:

```
sort context   ::= ∅ | wff | context , wff
sort sequent   ::= context ⊢ wff
line statement : sequent
```

Then the deduction theorem is an ordinary `Rule`:

```
→R    antecedent:  G , A ⊢ B
      deduction:   G ⊢ ( A → B )
      bindings:    G : context, A : wff, B : wff
```

Unification does the rest. A concrete context is a left-nested list, so `G , A`
matches it by splitting off the rightmost assumption — exactly the deduction
theorem's semantics. The converse direction is the same rule with the roles
swapped, and both are primitives of a sequent calculus rather than admissible
rules of a Hilbert one, so nothing is being smuggled in.

The cost, stated plainly: **a syntactic list is not a set.** `Γ, A, B ⊢ C` and
`Γ, B, A ⊢ C` are different terms, so exchange, weakening and contraction must be
declared as explicit rules and cited by hand. That is honest sequent calculus and
it is what a first version should ship. If it proves intolerable in use, the
route out is an **associative-commutative matcher for the context sort**, and
`website/logical/matching/rewriting` — the associative matcher written for
semi-Thue systems — is where it would go. That is real work in the matching layer
and should not be attempted before the plain version has shown where it hurts.

### 5.3 The bridge — and why it needs `system_relations`

A sequent FOL is not an extension of Hilbert FOL: it does not contain `ax-1` as a
row, and its statements are a different shape. It relates by an
**`interpretation`** edge:

```
source: FOL (Hilbert)          target: FOL (sequent)
sort map: wff → wff, setvar → setvar, class → class
statement template: '{Γ} ⊢ {0}'      extras: Γ : context
obligations: ax-1, ax-2, ax-3, ax-mp, ax-gen, ax-4 … ax-7
```

Each obligation is discharged by an actual proof in the sequent system — nine or
so small proofs, each stating `Γ ⊢ <the Hilbert axiom>`. Once discharged, **every
one of `set.mm`'s theorems becomes citable inside a sequent proof**, wrapped as
`Γ ⊢ φ`, with the same lazy by-label resolution as §4.2 and one extra step: the
statement is composed through the template before it is promoted.

This is the payoff for building the general edge rather than only the spine, and
it is the concrete sense in which the brief's "two relationships of different
types" understates the situation: there are two logical kinds among the examples
given, but the mechanically distinct third kind is the one that makes sequents
work.

### 5.4 Deliberately deferred

**The deduction theorem as an admissible rule of the Hilbert system**, checked by
*elaborating* a subproof into primitive `syl`/`a1i`/`ax-mp` steps. This is the
"elaboration gap" the metamath roadmap §2.3 names as the central design question,
and it is a much larger piece of work than anything here: it needs a per-system
elaboration procedure, and its trusted status is the whole question. §5.2 gets
the *use* of the deduction theorem without opening it. Recorded so it is not
mistaken for an omission.

---

## 6. The layered importer — (d)

### 6.1 The partition, and what has to be measured first

`set.mm` carries its own outline in header comments (`$( #*#*# … $)` for a
section, `####` for a part), and `parser._strip_comments` currently discards
them. They are the only statement in the file of where propositional calculus
ends, so step one is to keep them.

The layer plan is then **data about one library**, and belongs in
`website/logical/metamath/setmm.py` beside `BINDERS` and `EQUIVALENCES` — a map
from section prefix to layer, not engine behaviour:

| layer | `set.mm` outline (to be confirmed against the file) |
|---|---|
| Propositional calculus | Part 1 §§1.1–1.3 (pre-logic, propositional calculus, other axiomatisations) |
| First-order logic | Part 1 §§1.4–1.7 (predicate calculus, with and without distinct variables, existential uniqueness) |
| ZFC | Part 2 onward (ZF set theory) |

**A prediction that must be checked before the milestone is set.** On the
author's reading of `set.mm`'s ordering, propositional calculus runs to roughly
1,500 theorems — so **the first 1,000 are likely to land wholly inside the PC
layer**. If so, that slice exercises the *partition* and exercises no *transfer*
whatsoever, and it proves nothing about (a) or (b). Step D1 is therefore to
measure, and the milestone slice is "the first N theorems such that all three
layers are populated" — the first 1,000 kept as the fast regression, the wider
slice as the one that demonstrates the feature. Guessing N here would be
guessing; the walk already reports positions and the answer is one run away.

### 6.2 The walk, layered

`corpus.walk` already admits each production at the assertion that declares it
and refuses forward citations. Layering coarsens that:

1. **D1 — keep the outline.** `parser` retains header comments and attaches a
   section path to every assertion. Purely additive; nothing reads it yet.
2. **D2 — the layer plan.** `setmm.LAYERS`: section prefix → layer name, plus the
   spine order. Default empty, so an import that names no plan behaves exactly as
   today — the same discipline `BINDERS` and `EQUIVALENCES` follow.
3. **D3 — one `SystemSpec` per layer.** `corpus_spec` becomes
   `corpus_specs(database, limit, plan)`, returning a spec per layer holding only
   the productions, definitions and axioms declared *in that layer's sections*.
   `metamath_store.import_corpus` creates one `formal_systems` row per layer and
   wires `inherits_from_id` into a spine. Each layer is published on completion,
   which is what lets the next one inherit it.
4. **D4 — store each theorem in its layer.** The walk already knows each
   assertion's position; it now also knows its layer. `proofs`, `proof_lines`,
   `terms` and `promoted_theorems` are written against that layer's system.
   Citations are stored as they always were — bare labels — and resolve through
   the spine (§4.2). **The emitted proof text does not change**, which is the
   whole of "preserving references".
5. **D5 — the invariants.** Three checks, each a hard failure of the run:
   - no proof cites a label from a strictly *later* layer (guaranteed by
     `set.mm`'s topological order — so a violation means the layer plan is wrong,
     not that the corpus is);
   - every citation in every stored proof resolves through the spine;
   - every theorem still verifies, at the same count as the unlayered run.
6. **D6 — the provenance report.** §4.5 run over the import: per layer, how many
   theorems actually depend on their own layer's axioms rather than a lower one.
   This is what says whether the boundaries were drawn in the right place.

### 6.3 What layering costs

- **The term graph fragments.** Today "the corpus lands in one term graph, so a
  subterm shared by two theorems is one row" (metamath roadmap §1.3). Three
  systems means three graphs, and a formula appearing in two layers gets two
  rows. The duplication is bounded by the *cross-layer* sharing, which for
  `set.mm` should be small — a ZFC theorem's statement is rarely a PC
  theorem's — but it should be measured in D1 rather than assumed. If it turns
  out to matter, the escape is to key terms by the **spine root** rather than the
  owning system, resolving constructors in the deepest layer; that is a real
  change to the interning contract and should not be made speculatively.
- **A rebuild cost per layer.** Each layer builds its own `FormalSystem`, and the
  child's build reads the ancestors' parts. Three builds instead of one. Against
  a 24-minute whole-corpus walk this is noise, but the child's build is
  proportional to the *whole* chain, so a deep tower would not be.
- **Slugs and names multiply.** Three `formal_systems` rows where there was one;
  `scripts/import_metamath.py` gains a `--layers` flag and the report gains a
  per-layer breakdown.

---

## 7. Phases

Ordered so that each lands something checkable and nothing is built before the
thing it depends on.

### Track R — the relationship itself

| | | delivers |
|---|---|---|
| **R1** | Resolve `inherits_from_id`: `effective_spec`, ancestor loading, the six guards of §4.1, a transitive cycle check, digests over the chain. Relax `_require_owned_reference` to owned-or-published. | a child system that builds on its parent's grammar |
| **R2** | Library resolution through the chain: `read_theorems`/`load_theorems` take a chain, nearest-first; `promote_spec` against the child. | **(a)** and **(b)** for imported and promoted theorems |
| **R3** | `POST /api/proofs/{id}/promote`, `proofs.theorem_id` for user proofs, retire-on-invalidate. Ground statements first. | (a)/(b) for work a person proves |
| **R3a** | Schematic promotion: the author nominates metavariables and sorts. | `⊢ (φ → φ)` proved once, cited at every instance |
| **R4** | `system_relations` + the four side tables; `extension` edges auto-discharged from the spine; `interpretation` edges gated on `status`. | multiple parents, sort renames, translations |

### Track S — sequents

| | | delivers |
|---|---|---|
| **S1** | Author a sequent FOL in `tests/` as a spec: `context`/`sequent` sorts, structural rules, `→R`/`→L`, `∀R`/`∀L`. No engine change expected — if one *is* needed, that is the finding. | **(c)**, standalone |
| **S2** | The `interpretation` edge Hilbert-FOL → sequent-FOL: template `{Γ} ⊢ {0}`, obligations discharged by proofs. Requires R4. | `set.mm`'s library citable inside sequent proofs |
| **S3** | Benchmark the recursive `context` grammar (`benchmarks/bench_matching`, baseline before). Left-nested list parsing is the risk. | evidence for or against S4 |
| **S4** | *Conditional on S3.* An associative-commutative context matcher in `matching/rewriting`, so exchange/contraction are free. | sequents without structural bookkeeping |

### Track D — the importer

D1 → D6 as §6.2. **D1 must run before the milestone is fixed**, because it
decides whether "the first 1,000" demonstrates anything.

### Dependencies

```
R1 ──▶ R2 ──▶ R3 ──▶ R3a
  │      │
  │      └──▶ D3 ──▶ D4 ──▶ D5 ──▶ D6
  │                    ▲
  │            D1 ──▶ D2
  └──▶ R4 ──▶ S2
              ▲
       S1 ────┘──▶ S3 ──▶ S4
```

S1 and D1 depend on nothing and can start immediately.

---

## 8. Risks and open questions

1. **Digest churn across the chain.** A child's `library_digest` covers its
   ancestors, so any parent edit misses every descendant's cached terms. The
   freeze-on-publish rule (§4.1) makes this a non-event in practice, but it means
   the freeze is *load-bearing* rather than tidy — the same shift
   `proof_lines` invalidation went through in `docs/verification-from-rows.md`,
   and worth the same care.
2. **Name collisions between layers.** Refusing them is right, but `set.mm`'s
   1,441 productions across three layers is where it will first be tested. If the
   partition produces a collision, the layer plan is wrong.
3. **Existing checks firing across a boundary.** `_validate_constant_declarations`
   and `_require_a_fresh_defined_form` both get stricter under inheritance
   (§4.1). Both fail safe; both need error messages that name the offending
   layer, or a failure is unreadable.
4. **Term-graph duplication.** Measured in D1, escape route in §6.3, not to be
   pre-empted.
5. **Owned-only proof systems.** `_require_owned_system` means a proof must be
   written against a system its author owns, so nobody can write a proof against
   the imported corpus even once inheritance works. Relaxing it to
   owned-or-published has a cascade delete to think about first
   (`proofs.formal_system_id` is `ON DELETE CASCADE`, and a published system
   cannot be deleted — so the reasoning in that route's docstring may already
   have its answer).
6. **Schematic promotion is where the real UX is.** R3 without R3a gives library
   entries that justify exactly themselves. Useful for `2 ∈ ℝ`, useless for
   `φ → φ`. Do not treat R3 as closing (a)/(b) for human authors.
7. **Sequent parse performance.** A recursive left-nested `context` sort is the
   kind of grammar the matching layer is slowest on, and proof checking *is*
   parsing. S3 exists because this is a real risk, not a formality.

---

## 9. What this does not do

- It does not check **conservativity**, and does not infer it (§1.2).
- It does not make transfer **downward**. A ZFC proof of a propositional
  statement does not become a PC theorem.
- It does not add an **elaboration gap** or admissible-rule machinery (§5.4).
- It does not change the **kernel**. Every construction here is a system, an
  edge, or a query; the trusted core learns nothing about relationships between
  systems, which is the property that keeps "Edifyce checks any formal system"
  true.
- It does not introduce **cross-system proof-to-proof references**.
  `proof_references` stays same-system; the library edge is the transfer
  mechanism, and a proof that wants a foreign lemma cites it as a theorem.
