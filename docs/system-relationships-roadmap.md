# Relationships between formal systems: analysis and roadmap

**Status:** **Track R is delivered and complete** — R1, R2, R3, R3a, both halves
of R4, and the edge CRUD an author reaches them through. **Track S is delivered
too**, bar the conditional S4: S1 declares a sequent calculus and needed no
engine change, S2 adds the statement template and carries a Hilbert library
across into it, S2a puts a sequent calculus on top of a tower — including an
imported one — and S3 is answered by S1's measurements. **Track D has started:**
D1 and D2 are done — the outline is kept, the partition is measured against the
real `set.mm`, and `setmm.LAYERS` carries the plan those numbers justify — and
**D3 is built, both halves**: `corpus_specs` returns one `SystemSpec` per layer
and layering them back declares exactly what the unlayered spec declared, and
`import_corpus(plan=…)` stores a corpus as a spine of systems. **D4 is done** —
`--setmm-layers` runs it, the report breaks down per layer, and
`scripts/check_layering.py` holds the headline invariant against the real file:
at the milestone slice a spined import of `set.mm` produces the same verdicts and
**byte-identical proof sources** as a flat one. Running it on the corpus is what
found the one thing the fixture could not — a layer resolving a proviso's sort
through its own symbols rather than its ancestors', which had been refusing 354
of the first 2,676 promotions. D5 and D6 are still design.

One correction this note owes its reader, since §6.3 and §8's S2 both imply
otherwise: **an edge and a layer are not two ways to do the same thing.** An edge
relates systems built independently and costs a total rename, a template and an
obligation per source primitive; a layer is what a sequent calculus built *over*
an existing system is, and costs one declared rule. Only the second reaches
`set.mm`, because a total rename over 1,441 productions is not something an
author writes. §8's S2a is the finding and carries the comparison.

`formal_systems.inherits_from_id` used to be validated on write and read by
nothing — `app/routers/systems.py` said so in as many words ("inheritance is not
resolved yet … deferred to the inheritance phase"). It now means what §5.1 says
it means: a child's effective system is its ancestors' parts followed by its
own, and every path that builds a system builds the chain, and §5.2 as well: a
citation resolves against the system's own library and then its ancestors'. A
proof proved here enters that library (§5.3), schematically if its author says
so; and where the spine cannot reach, an edge does — including between two
systems that disagree about what to call things (§5.4). See §8's R1–R4 for what
landed and §9.9–9.22 for what they turned up.

The edge **CRUD** closes it: `app/routers/system_relations.py`, under the
*target* — the system whose citations an edge widens, and whose owner may
therefore say so. It is where §9.17 said a rename's check belongs, and §9.21
records what taking that escape settled, including the one thing it could not:
the resolution-time check stays, because either system may be a draft whose
grammar moves after an edge is written.

**(c) is delivered too**, and it cost the engine nothing: a sequent calculus is
an ordinary `SystemSpec` (`tests/sequent_system.py`), its contexts are terms of
an ordinary sort, and its eigenvariable condition is an ordinary proviso the
kernel's `occurs` decides. §8's S1 records the two things that turned out not to
be expressible and why each refusal is sound; §9.23 records what they have in
common.

And the two mechanisms **compose**: S2's `statement_template` is the last piece
of §5.4, so a theorem proved in a Hilbert system is citable inside a sequent
proof, wrapped as `Γ ⊢ φ` by a term construction rather than a string. What that
turned up is the sharpest thing in this note: an obligation has to hold
*uniformly in what the template introduces*, which `ax-gen` cannot — so the edge
that carries a first-order library is the **closed** one, and the shape of the
sound translation turned out to be forced by what the edge could check (§9.24).

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

The distinction that *is* mechanical arrives with (c) — see §6. A Hilbert-style
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

## 3. Terms, not strings

Edifyce already decided this once, for checking: a verified proof is checked over
interned kernel terms and a proof checked once never has its text parsed again
(`docs/verification-from-rows.md`). Relationships between systems must not
reintroduce a string layer underneath that. The rule for every phase below:

> **A decision that affects whether a proof stands is made over kernel terms.
> Strings are for input and for display.**

Seven places this bites, each of which is a design commitment and not a
preference:

**3.1 Transfer is a term-graph read, not a re-parse.** The obvious implementation
of "cite a PC theorem in ZFC" is to take the parent's statement *text* and parse
it against the child's grammar. Do not: it is the most expensive operation in the
system (a parse against the whole grammar is roughly half of building a system)
and it re-derives something already stored. The parent's statement term is a row
in the parent's term graph; `prefetch_terms` reads by root id and does **not**
filter by system, and `TermGraph.term` resolves each constructor **by name in
whatever context it is handed**. Hand it the *child's* context and the same rows
rebuild as a term over the *child's* constructors — whose slot sorts are the
child's wider unions. That is the sort widening of §1.1, performed as a graph
read.

`promote_from_source` already takes `statement_term` / `premise_terms`, and
`build_schema_pattern(cached=…)` then skips the composing parse entirely, so the
plumbing exists. Two things this depends on: the chain-wide name-uniqueness guard
(§5.1) — without it a constructor name could resolve to a different production in
the child — and the digest, which decides whether the stored term still describes
the grammar. A missing or stale term falls back to the parse, on the same
cache-not-record contract as everywhere else: a miss costs time and never a
different answer.

**3.2 Sort widening is checked over `Constructor.admits`, not sort names.** A
sort map is validated by projecting both grammars and asking whether the target's
constructor admits a superset of the source's. Comparing names would accept a
child that reuses `wff` for something else entirely.

**3.3 A layer boundary is decided by constructors and citations, not by section
headers.** The `set.mm` outline is the *declared plan*; the *check* (§7.2, D5/D6)
walks each theorem's statement term and its citation closure and asks which layer
each constructor and each cited label belongs to. That is a recursive query over
`term_children` and `proof_line_antecedents`, and it is what catches a misfiled
theorem — a string match on the section header never could.

**3.4 A sequent context is a term.** `Γ, A` is a `Node` matched by unification,
not a string split on commas. The eigenvariable condition of ∀R is
`not occurs(y, Γ)` in the kernel's side-condition algebra, evaluated over the
context term. A context implemented as text with a separator would put binding
decisions back into the parser — exactly the mistake the kernel exists to
prevent, and the one that would make (c)'s bound-variable cases unpinnable.

**3.5 Provisos travel as side conditions, not as text.** A transferred `$d` is
already `SideConditionRow`s. The transfer maps the *sort argument* through the
sort map and leaves the algebra untouched; nothing re-parses `disjoint(x, ph)`.
`app/db/side_conditions_mapping` renders the surface syntax for display only.

**3.6 Collisions are namespace facts.** A cross-layer name collision is detected
on the symbol namespace, not by diffing rendered templates. Two productions
spelling the same template in two layers are legitimate only if they are the same
symbol — which under inheritance they are, because the child does not redeclare
it.

**3.7 Where a string is still right.** The proof source (a proof *is* the text
its author wrote), a statement's display form, and the first parse of anything
newly authored. Everything downstream of that first parse is terms.

---

## 4. What already exists — do not rebuild

The pleasant finding of this survey is that the transfer mechanism is almost
entirely present, in a form that happens to be exactly right.

**A promoted theorem is already declarative and system-free.**
`promotion.TheoremSpec` is label + statement text + `{metavariable: sort name}` +
premises + `$d` provisos + a matching mode. It carries no engine object. That is
*precisely* what has to cross a system boundary: to make a PC theorem citable in
ZFC you take its `TheoremSpec`, apply the edge's sort map, and call
`promote_spec` against the **ZFC** system — with the parent's stored term handed
in, so no parse happens (§3.1).

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
(§5.2).

**Scoped subproofs with discharge already exist.** `SubproofSchema`,
assumption/variable scopes, scope-checked references, eigenvariable freshness —
`docs/scoped_subproofs.md`. This is natural deduction, and it is *not* the same
thing as sequents; §6 says why, and why it is still relevant.

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

## 5. The design

### 5.1 The spine — inheritance resolved

`inherits_from_id` finally means something: **the child's effective system is its
ancestors' parts followed by its own.**

```
effective_spec(system) = concat(spec(ancestor_n), …, spec(ancestor_1), spec(system))
```

Concretely, a `declarative.layered_spec(specs)` that concatenates `productions`,
`lines`, `definitions`, `axioms` and `rules` in ancestor-first order and merges
sorts **by name** — `SystemSpec.productions` already names its sort by string, so
a child adding `∀x φ` to `wff` needs only to say `sort="wff"`, and the union it
lands in is the one the parent declared. `build_spec` then sees one flat spec and
neither it nor the kernel learns a new concept. This is engine surface, not
persistence: it is a pure `SystemSpec → SystemSpec` operation with real rules, so
it belongs beside the declarative model. `system_to_spec` keeps its current
meaning (this system's *own* parts), because that is what the parts CRUD edits
and what the API renders.

Rules this imposes, each of which is a guard to write:

| Rule | Why |
|---|---|
| A parent must be **published** (frozen) before a child may inherit from it | A parent edit changes every descendant's grammar, invalidating every proof beneath it. Publishing is already a one-way door and already blocks edits. |
| Inheriting from an **unpublished** system is refused; inheriting from a **published** one is allowed regardless of owner | Today's owned-only rule would make the imported corpus uninheritable, which is the whole point of (d). |
| The chain must be **acyclic**, checked transitively | The current guard catches only `parent == self`. |
| A name declared by both a child and an ancestor is an **error** — except a sort union, which merges | Silent shadowing would let a child redefine a parent's `→`, and every transferred theorem would then mean something else. It is also what §3.1's term rebuild depends on. |
| A child that declares no `lines` uses its ancestors'; a duplicate line *name* is an error | Otherwise every layer must restate `\|- wff`. |
| `token_separated` is the **disjunction** over the chain | The promise is about the whole notation. A layer adding glued templates under a token-separated ancestor is then told so by `_check_token_separation`, which is where that belongs. |
| The digest covers the whole chain | `library_digest` / `schema_digest` take the layered spec, so a stale cache is a miss rather than a wrong answer. |

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

### 5.2 The library through the chain — (a) and (b)

`app/db/promoted_theorems_mapping.read_theorems` currently filters
`system_id == <one system>`. It gains the chain:

```
read_theorems(session, system_ids=[child, …, root], labels, …)
```

resolved **nearest-first** — a label defined in both a child and an ancestor
resolves to the child's. Each entry remembers which system it came from, and
`load_theorems` promotes it against the **child's** built system via
`promote_spec`, handing over the parent's stored statement and premise terms
rebuilt in the child's context (§3.1) and applying the edge's sort map (the
identity, on an `extension` edge). `cited_labels` is untouched;
`Proof.get_reference` is untouched; `app/routers/proofs.py` changes by passing a
list where it passed an id.

That is the whole of (a) and (b) for imported and promoted theorems.

**Why resolve through the edge rather than copy rows into the child.**

| | resolve through the edge | copy rows into the child |
|---|---|---|
| rows for a 3-layer set.mm | 49k, once | up to 3× |
| provenance | the row's `system_id` *is* the answer | needs a new column to not lose it |
| a parent gaining a theorem | visible immediately | needs a re-sync |
| proof source | unchanged | unchanged |
| cost per citation | one term-graph read, cached | none |

Since §3.1 makes the per-citation cost a graph read rather than a parse, the
copy's only advantage is gone.

**What is genuinely re-derived, and why it must be.** A PC term and a FOL term are
not the same kernel object even when they render identically: `wi`'s constructor
in PC has slot sorts pointing at PC's `wff` union, and in FOL at FOL's. Terms are
interned per `formal_system_id`, so a transferred statement gets its own row in
the child's graph. That is not waste — it is the sort widening, made physical.

### 5.3 Promoting a proved proof — the missing half of (a)/(b)

Today only an import writes `promoted_theorems`. For a person to reuse their own
PC lemma in ZFC, a proof must be able to *enter* its system's library:

`POST /api/proofs/{id}/promote` → writes a `promoted_theorems` row from the
proof's conclusion and sets `proofs.theorem_id`. Guards: the proof must be
**published** and owned — which subsumes valid and warning-free, and is a
stronger condition than this line first named, for reasons §9.15 gives.
Re-promoting after an edit replaces the row; anything that stops the proof
standing retires it, and retiring reaches the proofs that cited it.

The statement is taken from the conclusion line's **stored term**, not its text
(§3.1/§3.7): the row is already there from the last verification, and it is the
term the check actually ran on.

The first cut promotes the conclusion **as stated** — a ground theorem, which
`promote_from_source` already supports and documents (`2 e. RR` justifies itself
and nothing else). Schematic promotion — the author nominating which leaves are
metavariables and at which sorts, so `⊢ (φ → φ)` is proved once and cited at
every instance — is a second cut, and is where the interesting UX is. Both write
the same `TheoremSpec`, so the storage does not change between them.

### 5.4 The general edge — `system_relations`

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

### 5.5 Provenance — what a proof actually depends on

A free consequence of the split, worth building because it is the check on
whether the partition is right: for any proof, the **deepest layer it actually
uses** is a query over `proof_line_antecedents` joined to `promoted_theorems`,
following the transitive citation graph — a graph question, answered on the graph
(§3.3). A ZFC proof that touches nothing above PC *is* a PC proof, and should say
so. Run over an imported corpus it also validates (d): a theorem the layer plan
puts in FOL that depends on a ZFC axiom is a misfiled theorem, and this finds it.

---

## 6. Sequents and the deduction theorem — (c)

### 6.1 What is already there, and why it is not this

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

### 6.2 The recommendation: a sequent system is a *system*

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
theorem's semantics, decided on the term (§3.4) and not on the rendered string.
The converse direction is the same rule with the roles swapped, and both are
primitives of a sequent calculus rather than admissible rules of a Hilbert one,
so nothing is being smuggled in.

The cost, stated plainly: **a syntactic list is not a set.** `Γ, A, B ⊢ C` and
`Γ, B, A ⊢ C` are different terms, so exchange, weakening and contraction must be
declared as explicit rules and cited by hand. That is honest sequent calculus and
it is what a first version should ship. If it proves intolerable in use, the
route out is an **associative-commutative matcher for the context sort**, and
`website/logical/matching/rewriting` — the associative matcher written for
semi-Thue systems — is where it would go. That is real work in the matching layer
and should not be attempted before the plain version has shown where it hurts.

### 6.3 The bridge — and why it needs `system_relations`

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
`Γ ⊢ φ`, with the same lazy by-label resolution as §5.2 and one extra step: the
statement's term is composed through the template before it is promoted — a term
construction, not a string substitution.

> **S2 corrects the sketch above in one place, and it is the phase's finding.**
> `ax-gen` is *not* dischargeable under a template that introduces `Γ`: its image
> is ∀R without ∀R's proviso, and an obligation has to hold uniformly in what the
> template introduces. The edge that carries a Hilbert FOL is therefore the
> **closed** one, `∅ ⊢ {0}` with no extras, under which `ax-gen` discharges
> outright and reaching a non-empty context is a cited weakening. See §8's S2 and
> §9.24.

This is the payoff for building the general edge rather than only the spine, and
it is the concrete sense in which the brief's "two relationships of different
types" understates the situation: there are two logical kinds among the examples
given, but the mechanically distinct third kind is the one that makes sequents
work.

### 6.4 Deliberately deferred

**The deduction theorem as an admissible rule of the Hilbert system**, checked by
*elaborating* a subproof into primitive `syl`/`a1i`/`ax-mp` steps. This is the
"elaboration gap" the metamath roadmap §2.3 names as the central design question,
and it is a much larger piece of work than anything here: it needs a per-system
elaboration procedure, and its trusted status is the whole question. §6.2 gets
the *use* of the deduction theorem without opening it. Recorded so it is not
mistaken for an omission.

---

## 7. The layered importer — (d)

### 7.1 The partition, and what has to be measured first

`set.mm` carries its own outline in header comments (`$( #*#*# … $)` for a
section, `####` for a part), and the parser used to discard them. They are the
only statement in the file of where propositional calculus ends, so step one was
to keep them — which `metamath/sections.py` now does, reading all 1,903.

The layer plan is then **data about one library**, and belongs in
`website/logical/metamath/setmm.py` beside `BINDERS` and `EQUIVALENCES` — a map
from section prefix to layer, not engine behaviour:

| layer | opens at the section titled | assertions |
|---|---|---|
| Propositional calculus | `Pre-logic` | 1,808 |
| First-order logic | `Predicate calculus with equality…` | 926 |
| ZF set theory | `ZF Set Theory…` | 47,891 |

**Confirmed against the file** (D1), and shipped as `setmm.LAYERS`. The reading
above was right about the shape and the boundaries are where it guessed:
propositional calculus occupies positions 0–1,807, first-order logic 1,808–2,733,
and ZF everything from 2,734 to the end of a 50,625-assertion snapshot.

The plan says where a theorem *should* go; §3.3 says how to check that it does.

**A prediction that had to be checked before the milestone was set — and it
held.** The reading was that propositional calculus runs to roughly 1,500
theorems, so the first 1,000 would land wholly inside the PC layer. Measured: PC
runs to **1,808**, and the first 1,000 are **100% propositional**. That slice
therefore exercises the *partition* and no *transfer* whatsoever, and proves
nothing about (a) or (b) — so it stays as the fast regression and the milestone
slice is **N = 2,676 theorems**, the smallest slice at which all three layers are
populated, in the units `walk(database, limit)` takes. See §8's D1 for the rest
of the measurement, and for why the unit matters.

### 7.2 The walk, layered

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
   the spine (§5.2). **The emitted proof text does not change**, which is the
   whole of "preserving references".
5. **D5 — the invariants.** Three checks, each a hard failure of the run:
   - no proof cites a label from a strictly *later* layer (guaranteed by
     `set.mm`'s topological order — so a violation means the layer plan is wrong,
     not that the corpus is);
   - every citation in every stored proof resolves through the spine;
   - every theorem still verifies, at the same count as the unlayered run.
6. **D6 — the provenance report.** §5.5 run over the import: per layer, how many
   theorems actually depend on their own layer's axioms rather than a lower one.
   This is what says whether the boundaries were drawn in the right place.

### 7.3 What layering costs

- **The term graph fragments.** Today "the corpus lands in one term graph, so a
  subterm shared by two theorems is one row" (metamath roadmap §1.3). Three
  systems means three graphs, and a formula appearing in two layers gets two
  rows. **Measured in D1, and it is small:** of 43,889 distinct `|-` statements,
  43,647 are in one layer, 236 in two and 6 in all three — 0.55% duplication.
  So the escape (keying terms by the **spine root** rather than the owning
  system, resolving constructors in the deepest layer) stays unbuilt, which is a
  real change to the interning contract and was never to be made speculatively.
  What is *not* measured is subterm sharing below the statement, which is
  necessarily higher; if the row count ever surprises, that is where to look.
- **A rebuild cost per layer.** Each layer builds its own `FormalSystem`, and the
  child's build reads the ancestors' parts. Three builds instead of one. Against
  a 24-minute whole-corpus walk this is noise, but the child's build is
  proportional to the *whole* chain, so a deep tower would not be.
- **Slugs and names multiply.** Three `formal_systems` rows where there was one;
  `scripts/import_metamath.py` gains a `--setmm-layers` flag and the report gains
  a per-layer breakdown. Both built in D4.

---

## 8. Phases

Ordered so that each lands something checkable and nothing is built before the
thing it depends on. Every phase carries its **tests and verification** — not as
a coda but as the definition of done.

### 8.0 The testing discipline

The suite's existing idiom is that a green result is *evidence*, not assumption:
`test_metamath_import` checks a real proof from its verbatim `set.mm` source
**and** checks that a tampered conclusion is rejected. Every phase below is held
to the same four-part shape:

1. **A realistic worked example.** Not a two-production toy where every path is
   trivially the only path. The shared fixture is `tests/layered_systems.py`: a
   three-layer PC / FOL / ZFC tower assembled with `tests/spec_helpers.py`, with
   `→`, `¬`, `∧` (by definition) and `ax-1`/`ax-2`/`ax-3`/`ax-mp` at the bottom;
   `setvar`, `=`, `∈`, `∀` (with `scopes_over`), `ax-gen`, `ax-4`, `ax-5` and
   `df-ex` in the middle; extensionality and `⊆` at the top. Big enough that a
   wrong answer is not the only answer.
2. **At least one complex *valid* case that must be accepted.** Preferentially
   one involving binders: the failure mode of a soundness guard is
   over-refusal, and nothing else catches it.
3. **At least one *rejected* case per guard**, asserting the refusal *and* that
   the message names the offending layer. A guard with no rejection test is a
   guard that may not be running.
4. **A negative control.** Tamper the thing under test — a conclusion, a
   proviso, a sort — and require the check to fail. This is what distinguishes
   "the machinery ran and agreed" from "the machinery did not run".

Two standing rules, both consequences of §3:

- **Assert over terms where the claim is about terms.** A test that a transferred
  statement means the same thing compares `Term`s (or `digest` / `alpha_digest`),
  not rendered strings — a string comparison would pass for two terms that differ
  in constructor and so in sort.
- **Every bound-variable test states which side of the boundary the binder is
  on.** "Rejected" is only informative if it is rejected for the right reason.

---

### Track R — the relationship itself

#### R1 — resolve `inherits_from_id` — **done**

**Delivers** a child system that builds on its parent's grammar.
`declarative.layered_spec`, ancestor loading, the seven guards of §5.1, a
transitive cycle check, digests over the chain, `_require_owned_reference`
relaxed to owned-or-published.

What landed, and where: `declarative.layered_spec` (the concatenation and its
collision rules) and `SystemSpec.definition_scope` (§9.9); `app.db.effective_spec`
+ `inherited_rule_count`; `systems.load_chain` / `load_effective` /
`draft_ancestor_errors` / `_require_inheritable_reference`, with `validate`,
`publish`, both `verify` routes, the definition-reorder guard and the schema-term
cache going through the chain. Deleting a system something inherits from is
refused — `inherits_from_id` is `ON DELETE SET NULL`, so the delete would take
the descendants' grammar away while their proofs kept the verdict of a check
against it — and **repointing** the parent invalidates the child's proofs, for
the same reason every part edit does: it is a bigger grammar change than any of
them, and a verify trusts a stored lemma rather than re-checking it. Three things
it turned up on the way are recorded as §9.9–§9.11.

**Tests and verification** — `tests/layered_systems.py`,
`tests/test_layered_spec.py` (engine), `tests/test_system_inheritance.py` (API).

*Valid, and must be accepted:*
- The three-layer tower builds, and the child's `wff` union contains the
  parent's productions — asserted on `Constructor.admits`, not on names.
- A proof in ZFC written entirely in **PC notation** checks.
- A proof in FOL that applies a **parent definition** (`[df-an, n]`) checks — a
  definitional step across a layer boundary.
- A child definition whose *defining* form uses parent notation (`⊆` over `∈`)
  registers and unfolds.
- A child adds a **binder** (`∀x φ`) over a sort the parent declared, and the
  parent's productions still parse.

*Invalid, and must be refused:*
- A production name declared in two layers → `DeclarativeError` naming both.
- A cycle `A → B → A`, and the three-step `A → B → C → A` → 400.
- Inheriting from an unpublished draft → 400.
- A child redeclaring `→` with a different template → refused (this is the case
  §3.1's term rebuild depends on, so its rejection is load-bearing).
- **`denotes_constant` across the boundary:** the parent declares a token
  `denotes_constant=True` in a sort the *child's* new binder ranges over. The
  child must fail to build, and the message must say which layer introduced the
  binder.
- **Definition freshness across the boundary:** a ZFC definition of `→` — a
  symbol the *parent's* axioms are stated over — must be refused by
  `_require_a_fresh_defined_form`, which it would not have been when ZFC was
  read alone.
- **Non-circularity across the boundary:** a child definition stated in terms of
  its own new notation is still dropped.

*Pinned properties:*
- `layered_spec` is order-deterministic and associative:
  `layered_spec([a, b, c]) == layered_spec([layered_spec([a, b]), c])`.
- Editing a parent changes the child's `library_digest`, so a cached term is a
  miss — asserted directly, since this is what keeps a stale cache from being
  believed.
- `token_separated` disjoins: a token-separated parent plus a glued child
  template is a `_check_token_separation` failure, not a silent pass.

#### R2 — library resolution through the chain — **done**

**Delivers (a) and (b)** for imported and promoted theorems.

What landed: `LibraryChain` (the systems a citation may resolve in, nearest
first, each carrying its own `library_digest`), `read_theorems` over the chain,
`_nearest` for shadowing, and `effective_library` — which reads a system's spec
and its chain's digests in one pass, because a verify needs both. §9.11 and §9.12 record
what the design got wrong on paper; §9.13 a gap it surfaced.

**Tests and verification** — `tests/test_cross_system_citation.py`.

*Valid, and must be accepted:*
- A ZFC proof cites a PC theorem. A ZFC proof cites a FOL theorem that itself
  cites a PC theorem (transitivity across two edges).
- **The sort-widening case, which is the heart of the phase.** PC proves
  `⊢ (φ → φ)` schematically; a FOL proof cites it at `φ := ∀x (x ∈ y)`. Must be
  accepted — the transferred metavariable now ranges over a formula PC could not
  express.
- **Widening introduces no capture obligation.** Cite PC's
  `⊢ (φ → (ψ → φ))` at `φ := ∀x (x ∈ y)`, `ψ := (x ∈ x)`. The `x` in `ψ` is free
  and unrelated to the binder in `φ`; the theorem has no binder of its own, so
  nothing captures and the citation stands. Pinned because the tempting
  over-refusal here is to treat *any* binder in an instance as suspicious.
- **α-invariance.** A FOL theorem stated over `x` cited at a ZFC line spelled
  with `y`. Accepted by unification; the two statements share an `alpha_digest`
  and differ in `digest`, which is asserted so the test says which kind of
  sameness it means.

*Invalid, and must be refused:*
- **A `$d` survives the boundary.** FOL's `ax-5` carries `not occurs(x, ph)`.
  Cited in ZFC at `ph := (x ∈ y)` → **rejected**; at `ph := (z ∈ y)` →
  **accepted**. Both directions, in one test, because either alone is passed by a
  check that is not running.
- **A definition's `fresh` clause survives the boundary.** A ZFC `[df-ex, n]`
  step whose unfold would capture → rejected.
- **No downward transfer.** A PC proof citing a FOL theorem → the citation does
  not resolve.
- **No sideways transfer.** A proof citing a theorem of a *sibling* system (same
  parent, no edge between them) → does not resolve.
- A citation across a `draft` edge (once R4 lands) → does not resolve.

*Pinned properties:*
- **Shadowing resolves nearest-first**: a label present in both child and
  ancestor resolves to the child's, asserted by making the two say different
  things and checking which one the proof gets.
- **The transfer parses nothing.** With the parent's term cached and the digest
  current, the promotion path composes no schema term — asserted by counting
  parses (or by monkeypatching `compose_schema_term` to raise), which is the only
  way §3.1 stays true under later edits.
- **Falling back is a cost, not a difference.** Drop the parent's cached term and
  re-run: the same theorem, the same verdict, one parse more.

#### R3 — promote a proved proof into its library — **done**

**Delivers (a)/(b)** for work a person proves. Ground statements first.

What landed: `POST /proofs/{id}/promote` and its `DELETE`,
`promotion.proved_theorem` (the engine's answer to "what does this proof
establish?"), `promoted_theorems.proved_by_id`, and retirement wired into every
path by which a promoted proof stops standing. §9.15 records the two things the
design left unsaid — why the gate is *publication* rather than validity, and why
retiring an entry has to reach the proofs that cited it.

**Tests and verification** — `tests/test_proof_promotion.py`.

- *Valid:* prove a lemma in PC, promote it, cite it in a ZFC proof; the promoted
  statement's term is the one the check ran on (asserted by term identity against
  the `proof_lines` row, not by string equality).
- *Invalid:* promoting an invalid proof; promoting a proof carrying a warning;
  citing a promoted entry after the proof was edited and invalidated (the entry
  must be retired, not stale).
- *Pinned:* re-promoting replaces rather than duplicates; `proofs.theorem_id`
  points at the entry; a ground theorem justifies **exactly** its own statement —
  cited at any other instance it is rejected.

All of the above, plus what mutation testing said the first cut was missing.
Term identity against the `proof_lines` row turned out **not** to discriminate:
the graph interns by digest, so a statement re-parsed from text lands on the same
row and the assertion passes either way. What discriminates is R2's own control —
make composing fatal and promote anyway — so that is what pins §3.1 here, with
the row assertion kept for what it does say. Likewise the delete path: the entry
cascades away with the proof whatever the route does, so the test that says the
route did something is the *citing* proof's verdict being cleared.

Two guards are exercised where they live rather than through the route.
`proof.has_warnings` has no producer in the engine today — `warning_message` is
carried by the line, the row and the loader, and nothing sets it — so the warning
rejection is an engine test plus a forced test of the route's wiring, and says so.

The review round added five, four of them about the same thing: what invalidation
has to mirror in the resolver, and what it must not over-reach (§9.15). The one
that most nearly passed anyway is the rule-shadowing case — the first test of it
had the citing lines resolving to a *different* label, so it agreed with a walk
that had no shadow check at all.

#### R3a — schematic promotion — **done**

**Delivers** `⊢ (φ → φ)` proved once and cited at every instance.

What landed: `metavariables` on the promote request, and
`promotion.schematic_theorem`. The claim is **discharged rather than asserted** —
see §9.16 for why that turned out to be the cheap option as well as the sound
one, and for what the provisos have to do.

**Tests and verification** — same module.

- *Valid:* the author nominates `φ : wff`; the entry is cited at three distinct
  instances, one of them containing a binder.
- *Invalid:* nominating a leaf at a sort the grammar does not declare;
  nominating a leaf that the proof's own axioms fixed as a constant.
- **Bound variables:** a schematic promotion over `x : setvar` where the proof
  used `x` as an eigenvariable must carry the corresponding proviso into the
  entry, and a citation violating it must be rejected. Without this, schematic
  promotion is the obvious hole through which an eigenvariable condition escapes.

All three, and a fourth the design did not anticipate: a proviso restated over
leaves the nomination did **not** touch is dropped rather than stored, because it
is a closed fact the check just established and no citation can vary it. Storing
it would be an obligation with nothing to discharge it against. Both halves are
pinned, since either alone passes for a rule that is not running.

Plus the four refusals of §9.16, each with a mutation that makes its test fail.
Two of them the review found by *running* the change against fixtures already in
the suite — `tests/miu_system.py` and the scoped ZFC of `tests/zfc_systems.py` —
which is the lesson: a soundness guard written against one worked example is
tested against the systems that break it, and this suite already had them.

#### R4 — `system_relations`

**Delivers** multiple parents, sort renames, translations.

Split in three, and all three are done. The first two are the mechanism, split
because they are independently testable and the second is where §3.2 has teeth;
the third is the **CRUD** (`app/routers/system_relations.py`), which is how an
author writes one — its routes hang under the *target*, and what they refuse and
what they have to invalidate are §9.21.

**The first two.** **R4a — what an edge resolves**: the
four tables of §5.4, and `related_layers` turning the edges into a
`LibraryChain`'s extra layers, all identity on names, which is exactly what a
second parent is. **R4b — the rename**: `website/logical/translation.py`, a
`Translation` applied as a term-level constructor remap inside
`TermGraph.term`, with the narrowing refusal coming from `Constructor.admits`
rather than a name comparison. §9.17 records where that check runs and what it
costs; §9.18 what a rename turned out to have to carry besides the term.

What R4a settled that the design left open:

- **Ordering puts the spine first.** Relation layers are appended *after* the
  inheritance chain, so a label the tower already answers keeps its answer and an
  edge can only add. The spine is a claim the builder checked; an edge is a claim
  an author made, so the conservative direction is the spine's.
- **An edge's `status` is not trusted alone.** The column is a cache of the
  obligations' verdict, and it can go stale without anyone touching it — an
  obligation is undischarged by its theorem disappearing (`ON DELETE SET NULL`),
  which writes back to no edge. So the obligations are read too, and a stale
  cache fails closed.
- **An edge reaches the source's whole chain, and is reached from the target's.**
  A theorem two layers below the source is citable across the edge exactly as it
  is below the source; and an edge onto an *ancestor* reaches the descendant,
  since the ancestor's library is already citable there. Anything else would make
  an edge's reach depend on which layer of a tower it was attached to.
- **Reach and invalidation are one question asked twice** (Codex, on #162).
  Widening where a citation may resolve without widening `_citing_systems` left a
  sibling target holding `valid`, `result` and its `proof_lines` after the
  theorem they rested on was retired — and a verify trusts a lemma's stored rows,
  so a third proof would have rested on it too. The walk now follows discharged
  edges as well as the spine. §9.15's rule generalises: *any* new way for a label
  to resolve is a new way for a verdict to go stale.
- **A discharge can vanish without saying so.** An obligation discharged by a
  theorem loses it to `ON DELETE SET NULL` when that theorem is retired, and
  nothing writes back to the obligation's status — so an obligation naming
  neither a primitive nor a theorem is outstanding whatever its status says. The
  model already claimed this; only the column was doing it, not the query.

**Tests and verification** — `tests/test_system_relations.py` for what an edge
resolves, `tests/test_translation.py` for what a map has to earn. The split is
the same one the code makes: a map is a question about two grammars and needs no
row to ask it.

- *Valid:* an `interpretation` edge with a sort **rename** (`formula → wff`)
  transfers a theorem; a system with two parents resolves labels from both.
- *Invalid:* transfer across a `draft` edge; transfer across an edge with an
  undischarged obligation; a sort map that **narrows** (the target's constructor
  admits less than the source's) → refused, and the refusal is asserted to come
  from `Constructor.admits` rather than a name comparison (§3.2).
- *Pinned:* an `extension` edge auto-discharges from the spine and never asks an
  author for an obligation; discharging the last obligation flips `status` and
  is what makes a previously-failing citation succeed (the same proof, re-run).

The rename's own four-part shape (§8.0), since it is a soundness guard and its
failure mode is over-refusal:

- *The worked example* is the propositional layer **under other names** —
  identical notation, every production renamed — because a pair that also
  differed in what it could *say* would leave every refusal ambiguous between
  the rename and the difference. The map is applied to an edge that already
  exists, so the map is the only thing that changes between the two halves.
- *Valid, and the complex case:* a theorem whose statement **binds** (`(P → ∀x P)`
  with `not occurs(x, P)`) transferred through a nine-production map, and cited
  at an instance the proviso admits. The binder is what an over-eager guard
  refuses, since `scopes_over` is compared and a quantifier is the only
  production that has any. Plus a proviso carrying a **sort argument**
  (`disjoint(x, y, term)`), whose sort the target calls something else.
- *Rejected, each paired with the instance that must be accepted:* the same
  binder theorem cited where the proviso fails; the same `$d` theorem cited at
  equal variables; the narrowing map, against the identical map onto a target
  whose sort does admit the branch. And, from review (§9.19): a production the
  map leaves unmapped whose two spellings differ, against the same pair with the
  correspondence declared; a map collapsing two source names onto one; a
  definition the target spells differently, against the one it states alike; a
  proviso over a term expression, against the same theorem's proviso over a
  metavariable; and an atom family read as another base, against the constant
  relabelled from `⊥` to `bot` — whose two spellings of one theorem are the pair
  that says the statement was rewritten rather than merely accepted (§9.20).
- *The negative control* is the edge **without** its map: the same two systems,
  the same theorem, the same proof, and the citation does not resolve at all —
  which is what says the map is doing the work rather than the edge.
- *Pinned:* the transferred statement's term has the **target's** constructor at
  its root and its metavariable at the target's sort, asserted structurally; a
  rename **composes nothing** (§3.1 across an edge, pinned the way R2 pinned it
  across the spine — by making composing fatal); a rename that moves the
  *notation* renders the entry in the target's spelling.

One lesson from writing them, since it cost a false pass and would cost another:
**a refusal has to be asserted with its reason**. The first version of the
bound-variable rejection was refused because the line did not *parse* — a
formula this suite's grammar cannot spell — and it agreed with a transfer that
had dropped the proviso entirely. The three refusals in this area look identical
from a boolean and say quite different things: `does not apply` (resolved, and
the instance was refused), `Invalid reference` (the edge contributed no layer),
and a whole-verify error (a term that could not be rebuilt). Every rejection
above now names which one it means.

#### R4c — the edge CRUD — **done**

**Delivers** an edge an author can write, rather than one a test writes into its
rows. `app/routers/system_relations.py`, mounted under the **target** — the
system whose citations widen, and whose owner is therefore the one who may say
so. The source need only be *visible* (owned or published), which is the rule
inheritance follows and for the reason it follows it: the corpus this feature
exists to build on is ownerless.

What landed: list / create / patch / delete, with each of the edge's three
collections replaced whole (the shape a rule's bindings already take); the map
checked at the write, so an author gets `translation_errors`' own words (§9.17);
the obligations checked for what they may point at; and
`_invalidation.invalidate_library_reach`, which is §9.15's rule applied to a
*library* rather than a label. §9.21 records what the three of those settled.

**Tests and verification** — `tests/test_system_relations_api.py`, beside
`tests/test_system_relations.py` rather than folded into it. The two ask
different questions: what an edge *resolves* wants an edge in states the route
refuses to write, and what the route *does* wants the states an author can
actually reach.

- *Valid:* an edge written through the route makes a citation resolve, against
  the same proof failing before it existed; a draft edge is written, listed, and
  transfers nothing; discharging its last obligation through a PATCH makes the
  same proof stand.
- *Invalid, each with its message asserted:* a narrowing map (paired with the
  same map onto a target whose sort admits the branch); a map against a system
  that does not build, which says *that* rather than naming the map; an edge
  onto itself; a source that is neither owned nor published (paired with a
  published one owned by someone else, which is the case that must work); a
  second edge the same way round (paired with the reverse direction, which is a
  different edge and not a duplicate); an obligation claiming two discharges;
  an obligation naming a theorem the target cannot cite (paired with one it can).
- *Pinned:* deleting an edge clears the verdict of a proof that resolved through
  it, and leaves a proof that cited only its own system's axioms alone; a
  **published** target refuses an edit to itself and accepts an edge, which is
  the line between a frozen grammar and a library that was never frozen.

From review, seven more, each pinned by one test that fails without its guard: a
discharge naming a **primitive** the target does not have (paired with `MP`,
which it does); a collection naming one thing **twice**, on both the create and
the PATCH; a **stale** map that can still be turned off, paired with re-asserting
it and being refused; and deleting an edge's **source**, after which the target's
proof is invalidated *and* re-verifies to a failure — the second assertion being
what says the cleared verdict was the right answer rather than a cautious one.
Then, from a second round (§9.22): an **unpublished** source, paired with a
published one; an `interpretation` marked discharged with **no obligations**,
both created so and patched into it, paired with the `extension` for which an
empty list is the ordinary case; and retiring the **theorem an obligation was
discharged by**, after which what crossed that edge is invalidated.

---

### Track S — sequents

#### S1 — a sequent FOL as a system — **done**

**Delivers (c)**, standalone. No engine change expected — if one *is* needed,
that is the finding. **None was.** `tests/sequent_system.py` is an ordinary
`SystemSpec` built by `build_spec`, every proof in
`tests/test_sequent_calculus.py` is checked by the ordinary checker, and nothing
under `website/logical/` was touched. §6.2's grammar is declared as written, down
to the sort inclusion; the two-sorted formula language is `wff`/`ind` with `=`,
`¬`, `→` and `∀` (whose production declares `scopes_over={"x": ["p"]}`), and the
line type reads a whole `sequent`.

**Tests and verification** — `tests/sequent_system.py`,
`tests/test_sequent_calculus.py`.

*Valid, and accepted:*
- `⊢ (A → A)` by identity + →R.
- The deduction theorem on a three-assumption context, and its converse derived
  from →L and exchange rather than declared — which is why the calculus needs no
  rule for it.
- Weakening, exchange, contraction and cut, each in a proof that needs it. Cut
  is written twice: once through the cut, and once cut-free, so the test shows
  the rule is exercised rather than merely available.
- **∀R with an eigenvariable:** accepted when `Γ` is empty, and when `Γ` is
  `c = c` — a non-empty context not mentioning `a`.
- `∅ , A ⊢ ¬¬A` through ¬L and ¬R.

*Invalid, and refused, each with the refusal it means asserted (§9.19's rule):*
- **∀R when the eigenvariable is not fresh:** `a = a ⊢ ∀a a = a` → refused with
  `∀R does not apply`. The phase's central test, and it differs from the second
  accepted case above only in which variable the context is about. It is
  expressible only because the context is a term the kernel's `occurs` descends
  (§3.4).
- **→R does not reach past the rightmost assumption:** from `P, Q, R ⊢ R`,
  `P, Q ⊢ (R → R)` is accepted and `P, R ⊢ (Q → R)` is rejected. The price is
  then written out — the *same* target sequent, reached by citing exchange
  first. Both halves have to end on the same line for that to be the claim; a
  derivation reaching some other conclusion would show only that a longer proof
  exists, not that exchange is what the rejected step was missing.
- Contraction applied to two assumptions that are *not* equal → rejected.
- **¬R refutes only what yields falsity:** `∅ ⊢ ¬a = a` from `∅ , a = a ⊢ a = a`
  → rejected. See below — this pins a rule the fixture first got wrong.

*Pinned properties:*
- A context is matched structurally, asserted **on the term**: `A , B , C` is a
  `cons` whose right child is the literal `C`, and `∅ , A` and `A` are different
  terms — so a rule matched against one does not apply to the other.
- `benchmarks/bench_matching` grew `sequent-context-{2,4,6,8}`, the recursive
  left-nested grammar rather than the single-formula antecedent the existing
  `sequent-*` scenarios read, and `tests/test_matching_stress.py` grew a
  parse-count assertion over it. Both feed S3, which they substantially answer —
  see below.

**Two expressibility findings**, both recorded against the tests that pin them,
and both about what an author can *say* rather than what the checker will
believe. Each refuses more than a textbook calculus would, so each is sound.

- **The eigenvariable condition is stricter than the textbook one.**
  `∅ , ∀a a = a ⊢ ∀a a = a` is derivable in LK — the condition is that `a` is not
  *free* in the context, and here every occurrence is bound by the assumption's
  own quantifier — and Edifyce refuses it. `Occurs` is syntactic by design and
  says so in as many words: a condition needing binder scoping "depends on the
  object logic or on proof state and is intentionally not expressible here"
  (`kernel/side_conditions.py`). So the available proviso is a sound
  over-approximation of the one the calculus wants, in the same way Metamath's
  `$d` is. What it costs an author is generalising over a variable the context
  mentions *anywhere*, however bound; what it never costs is a wrong verdict.
  Pinned in `test_a_bound_occurrence_blocks_generalisation_too`.
- **∀L can only instantiate the bound variable with itself.** The bullet this
  section used to carry — "∀L instantiated with a term that would capture →
  rejected" — supposes a ∀L that *instantiates*, and no rule schema can be one: a
  schema is matched by unification, and `P[t/x]` is not something a pattern can
  say. The ∀L that is expressible is `Γ, P ⊢ C` ⟹ `Γ, ∀x P ⊢ C`, sound for every
  `P`, `x` and `t`, and there is therefore no capture to reject — which is why no
  test asserts one. Instantiating with an arbitrary term needs either a
  substitution operator in the schema language or ∀L stated as a *definition*,
  and neither is S1's — the second is the scope-aware definitional step
  `docs/scope-aware-definitional-steps.md` blocks. Pinned as behaviour in
  `test_universal_left_instantiates_the_binder_with_itself`.

**And one the review caught, which is the phase's sharpest methodological
lesson.** ¬R was first written as `Γ, A ⊢ B ⟹ Γ ⊢ ¬A` — →R with the conclusion
changed. `B` is unconstrained, so *every* formula was refutable and the fixture
calculus proved both `⊢ a = a` and `⊢ ¬a = a`. Nothing failed: no test cited ¬R,
and the rule-set guard only checked the label existed. The fix is the ordinary
single-succedent rule, which is why the grammar now declares `⊥`: with one
formula on the right, "assuming A proves *something*" is not a refutation of A —
the something has to be falsity. ¬L (`Γ ⊢ A ⟹ Γ, ¬A ⊢ ⊥`) comes with it, so the
pair is exercised by a proof rather than merely declared.

The lesson generalises past this fixture: **an unsound rule in a system is
invisible to every test that does not cite it**, and a guard that enumerates
*labels* is not a guard on what those labels mean. Edifyce checks proofs against
whatever system it is handed, and that is the point — the trusted core has no
opinion about whether a declared rule is sound. Which means the burden falls
entirely on the author, and a rule with no proof citing it has had no burden
discharged at all. Every rule a system declares should appear in some accepted
proof and, where it has a sound-but-weaker neighbour, in a refused one.

A third finding, smaller, worth recording because it shaped the fixture: a calculus
with `id` as its only axiom cannot supply a **non-vacuous** ∀R premise, because
`id` puts its formula into the context by construction, so every sequent it
proves mentions in `Γ` whatever it proves. The eigenvariable condition then holds
vacuously or fails trivially and the central test tests nothing. The fixture
therefore declares one axiom *of the object theory* — `refl`, `Γ ⊢ a = a` — which
is what makes `∅ ⊢ ∀a a = a` provable and `a = a ⊢ ∀a a = a` refusable for the
right reason. The general shape: **a proviso about the context is only tested by
a calculus that can prove something the context does not already contain.**

#### S2 — the interpretation edge Hilbert → sequent — **done**

**Delivers** a Hilbert library citable inside sequent proofs, wrapped. Required
R4, which it now has.

What landed: the **statement template** of §5.4, which was the one piece of that
section still unbuilt. `system_relations.statement_template` and
`system_relation_extras` are the rows; `website/logical/wrapping.py` is the
engine half — a template is target notation with the extras as ordinary
metavariables and **one hole** spelled `{<sort>}` (`G ⊢ {wff}`, extras
`G : context`), parsed at the target's *logical* sorts so a wrapped statement is
something a proof line here could say. Applying it is one `Term.substitute`, and
the route checks it at the write on §9.17's rule.

Three things about where it is built are worth carrying forward.

- **The wrap composes a term, and never renders a string.** §6.3 asked for that
  and `test_the_wrap_is_a_term_construction` asserts it on the object: the
  source's own term is a *subterm* of the wrapped one, the same object, under
  the target's `turnstile`. Rendering `Γ ⊢ ` + the statement and re-parsing would
  agree only where the two grammars agree, which is exactly what an edge may not
  assume (the `bj-0` hazard, metamath roadmap §1.4).
- **The template is carried declaratively and composed at promotion**, not built
  in `related_layers` beside the rename's check. That was the first attempt and
  it produced a schema that unified with nothing: sort admission compares
  constructors by **identity** (`Constructor.admits`), so a wrap composed against
  another build of the same grammar is a wrap against different objects. §9.24
  records the general rule, which is not confined to templates.
- **The two systems in the fixture share their whole formula language**
  (`tests/sequent_system.py`'s `wff_productions`), so the edge renames nothing.
  A rename and a wrap are independent, and a test that carried both would not say
  which half it was testing.

**Tests and verification** — `tests/test_sequent_interpretation.py`, plus four in
`tests/test_system_relations_api.py` for the write.

- *Valid:* a Hilbert theorem cited inside a sequent proof, wrapped as `Γ ⊢ φ`,
  with `Γ` instantiated non-trivially — at `∅`, at a formula, at a
  two-assumption list. Each of `ax-1`, `ax-3`'s shape and `MP` discharged by an
  actual sequent derivation, written out.
- *Invalid, each paired with its accepted twin:* the same citation with one
  obligation withdrawn; the same edge with no template (a `wff` arrives as a
  `wff`, and no line here is one); a template naming a sort this system does not
  declare; and the source theorem's own schematicity, `(A → B)` refused where
  `(¬A → ¬A)` stands.
- *Pinned:* the wrap is a term construction, asserted structurally; a wrapped
  entry re-renders in **this** system's notation; a template that will not
  compose is refused at the write with `template_errors`' own words, and can
  still be turned *off* after the grammar moves (§9.21's rule, for the wrap).

**The finding, and it is the one S1 predicted.** §6.3 sketched this edge with
`ax-gen` among the obligations, and `ax-gen` is the one obligation this
mechanism cannot discharge under a `Γ`-introducing template. An interpretation
is sound because each source primitive's *image* is derivable — and the image
has to be derivable **uniformly in whatever the template introduces**, since `Γ`
is a metavariable of every transferred theorem and a citation instantiates it
freely. `ax-gen`'s image is `Γ ⊢ P ⟹ Γ ⊢ ∀x P`, which is ∀R with its proviso
deleted: derivable exactly when `x` does not occur in `Γ`, and so not uniformly.
`test_generalisation_cannot_be_discharged_uniformly_in_the_context` is that, as
a pair — the step stands over a context about some other variable and fails over
one about `a`, and a discharge is a claim about *all* Γ.

**And the constructive half, which is why S2 is not blocked by it.** Uniformity
is demanded only because the template introduces something. A template with **no
extras** — `∅ ⊢ {wff}` — demands nothing, and `ax-gen`'s image is then
`∅ ⊢ P ⟹ ∅ ⊢ ∀x P`, which ∀R discharges outright because `occurs(x, ∅)` is
false. So the whole of a Hilbert FOL crosses, at the empty context, and reaching
a non-empty one is a cited **weakening** — the author's step rather than
something the edge claims on their behalf.
`test_a_closed_template_is_what_a_source_with_generalisation_needs` pins all
three of those.

That is the same trade §6.2 named for the calculus itself, arriving one level
up: **what a list rather than a set costs inside a sequent proof, a closed
template costs across an edge into one.** Both are one cited structural step,
and both are honest.

**From review**, four, and the first two are the same mistake in two places —
*a guard scoped to what an author declared rather than to what the code touches*,
which is §9.19's rule biting for the third time.

- **The capture guard read the wrong set.** It compared the template's extras
  against the theorem's declared **metavariables**, and promotion re-reads a
  statement's text with whatever metavariables it is given — so a name that was
  a *ground leaf* of the source theorem was silently rebound. A theorem
  `(P → G)` about a `wff` constant `G`, wrapped under `G : context`, became a
  schema whose `G`s were the antecedent; and a proviso `not occurs(P, G)` came
  out constraining the context it was never proved about, which is the half that
  changes what the theorem *claims* rather than only what it matches. The guard
  now reads the leaves of the terms being wrapped, literals included, plus the
  proviso arguments — every place a name can appear in what crosses.
- **A string-matched theorem could cross a wrap.** The refusal was written for a
  rename and not extended. It is worse across a wrap: string matching reads
  `formula_string` and never `schema_term`, so the composed wrap is built and
  thrown away, leaving exactly the surface-string substitution §6.3 exists to
  refuse. One refusal now covers both, because both end with a theorem checked
  against symbols it was not proved over.
- **A hole was "anything in braces"**, which cannot survive contact with the
  corpus this feature is for: `set.mm` spells set-builder `{ x | ph }`, so a
  template mentioning one read as a template with a spurious hole. A hole is a
  **declared sort name** in braces; braced text naming no sort is the system's
  own notation, and the error message now says so.
- **And §9.21's rule again**, in the place it was written to protect: clearing a
  template with `{"statement_template": ""}` alone was refused, because the
  extras rows survived the clear and extras without a template are refused.
  Clearing the wrap now clears what it introduced. The comment promising that
  the check never fires on the edit that turns an edge off was there before the
  code did it.

A second round found three more (Codex, on #171), and the first is the sharpest
thing S2 turned up about the *kernel* rather than about edges.

- **`substitute` places whatever it is given, and two sorts can be
  indistinguishable structurally.** Declare `[A-Z][A-Z0-9]*` in both `ind` and
  `wff` and the two constructors share a `signature`, so their nodes compare
  `equal` — verified directly before fixing. `sort_admits` is the only thing that
  separates them, and unify calls it when *binding a variable*, not for a subterm
  something else put there. So a wrap that did not check built a term the grammar
  does not generate, and it would then justify a line at the hole's sort. The
  hole now refuses a term its sort does not admit. Worth generalising: **a term
  assembled outside the matcher has had no sort check at all**, and the kernel's
  are positioned for terms that arrive from a parse or a binding.
- **A term-expression proviso could cross a wrap.** Refused across a rename since
  R4b, and the reason generalises with a twist: a rename may spell the
  expression's symbols differently, while a wrap leaves the spelling alone and
  changes what the re-parse *means* — promotion re-reads it with the extras now
  in scope, so a ground leaf inside `¬G` becomes the edge's `G`. Inventorying the
  leaves would mean parsing the expression here, which AGENTS.md records as the
  owner's parse and not cacheable; refusing costs nothing a real corpus produces,
  since `set.mm` stores no such argument at all.
- **An `extension` could carry a template**, and that was a hole rather than a
  wrinkle. §5.4 defines an extension as the degenerate edge — the target contains
  the source, every primitive present under its own label, obligations filled in
  from the spine and never asked of an author. A template says the two do not
  state the same kind of thing, which is the opposite. And because the
  empty-obligations refusal is scoped to `interpretation` while `related_layers`
  never reads `kind` at all, a discharged `extension` with a template wrapped
  every source theorem with no primitive image established anywhere: **the whole
  of §2, skipped by setting one column.** The refusal is unconditional, so it
  catches the PATCH that changes `kind` under an existing template as well as the
  create.

The three together restate §9.19 once more, and it is now the note's most
frequently relearned lesson: **a guard written for one way of reaching a place
does not cover the others**, and the ways multiply every time an edge learns to
carry something new.

#### S3 — benchmark the recursive context grammar — **substantially answered by S1**

**Delivers** evidence for or against S4. Left-nested list parsing is the risk.

**Tests and verification:** `benchmarks/bench_matching --only sequent-context` —
scenarios at 2/4/6/8 assumptions and the `-nomemo` pair at 8/12/16, so both
columns of the table below are reproducible rather than only the one the
conclusion is comfortable with. Then two parse *counts* rather than wall-clock
budgets, so a regression is a test failure and not a slow suite on a slow
machine, and it says which property moved:

- `test_a_left_nested_context_costs_one_parse_per_assumption`
  (`tests/test_matching_stress.py`) bounds a bare pattern match at 4/8/12/16
  assumptions. It installs the memo itself, so it pins the *matching layer's*
  behaviour given one.
- `test_a_proof_line_reads_its_context_once_per_assumption`
  (`tests/test_sequent_calculus.py`) checks a whole proof through the real
  system, with nothing but `LineType.parse_line` to supply the memo. That is
  what actually carries the conclusion, and the first test does not imply it:
  with `parse_line`'s memo removed the whole suite stayed green while a
  twelve-assumption line went from 26 sort-parses to 8,193.

What the measurement says, on `Γ ⊢ p` with `Γ` an `n`-assumption left-nested
context (best-of, one machine, quote the ratios and not the microseconds):

| assumptions | with a fresh parse memo | with the memo off |
|---|---|---|
| 4 | 69 µs | 183 µs |
| 8 | 150 µs | 2.4 ms |
| 12 | 266 µs | 40 ms |
| 16 | 416 µs | 755 ms |
| 20 | 607 µs | 18 s |

**The memo is the whole story, and `LineType.parse_line` gives every proof line a
fresh one.** Without it the recursive context is exponential — roughly ×4 per two
assumptions, and a 24-assumption context took ≈4.8 minutes to parse once. With
it, cost grows smoothly and at low polynomial degree: doubling the assumptions
rather less than triples the time, and a 32-assumption context parses in under
2 ms. So a real proof gets the left-hand column, and no realistic sequent proof
is anywhere near the cliff.

That removes **performance** as the argument for S4. What is left of the case for
an AC matcher is *ergonomic* — §6.2's "if it proves intolerable in use" — and S1
shows what that costs concretely: reaching an assumption that is not rightmost
takes an explicitly cited exchange, which
`test_implication_right_reaches_only_the_rightmost_assumption` writes out in
full. That is a judgement about authoring, to be made against real proofs, and it
is no longer a judgement about the matching layer. **S4 stays conditional, on a
different condition.**

The other thing the measurement pins is what the memo is *for*, which the
existing `-nomemo` scenarios only hinted at: a grammar whose sort recurses into
itself on the left of an ambiguous separator re-reads the same prefix once per
candidate split, and the memo is what collapses that. Any future change that
narrows where a memo is installed — a new parse entry point, say — should be read
against this table first, and the second of the two counts above is what will
notice.

#### S2a — the sequent tower, and the arrangement `set.mm` forces — **done**

**Delivers** a sequent calculus as a **layer of a tower** rather than a system
beside one, and with it the answer to whether Track S's architecture reaches an
imported corpus. Not in the original plan: it exists because the question "what
would a sequent PC/FOL/ZFC look like" turned out to have a different answer from
the one S1 and S2 imply.

**Tests and verification** — `tests/sequent_tower.py`,
`tests/test_sequent_tower.py`.

**The finding: for a sequent calculus over a system that already exists, the
spine does what S2's edge does and asks for none of what the edge asks for.** No
rename, because the child's `formula` *is* the parent's rows. No template,
because the child can state a parent line itself — a line type is inherited like
everything else, so a child of a Hilbert system has *both* line types and can
write `φ` as well as `Γ ⊢ φ`. No obligations, because the parent's rules are the
child's. What replaces all three is one declared rule:

```
lift    antecedent:  P          (read at the parent's logical sort)
        deduction:   ∅ ⊢ P
```

— the interpretation stated as a primitive of the combined system instead of as a
claim about two of them, and sound for exactly the reason §9.24's closed template
is. `lift` concludes `∅ ⊢ P` and never `Γ ⊢ P`, which is that finding restated as
a rule: a schema is read for *all* instances of its metavariables, so lifting
onto an arbitrary context would claim the uniformity only weakening earns.

**Why this matters rather than being a second way to do the same thing.** An
edge between siblings requires the sequent system to *have* the grammar it
reasons about. `set.mm` declares 1,441 productions, and `translation_errors`
holds a rename to **totality** — every name of the source's grammar must have an
image — so the sibling arrangement demands either 1,441 redeclarations or a
1,441-entry map, neither of which an author writes. A child declares four
productions and inherits the rest.
`test_a_sequent_layer_sits_on_an_imported_grammar` is the same layer, unmodified
except for the name of its parent's logical sort, on a grammar
`metamath.importer.build_spec` produced from a `.mm` file.

So the two arrangements are **not** alternatives, and the roadmap should not have
implied they were:

| | an edge (S2) | a layer (S2a) |
|---|---|---|
| when | the two systems were built independently; neither contains the other | the sequent calculus is being built *over* a system that already exists |
| costs | a rename (total), a template, one obligation per source primitive | one declared rule |
| reaches `set.mm` | no — the rename cannot be written | yes |

**What is parent-agnostic, and it is more than expected.** `sequent_core` — the
context sort, the turnstile, `id`/`WL`/`XL`/`CL`, `cut` and `lift` — names its
parent's *logical sort* and no production of it, so it sits unchanged on this
repository's `formula` tower and on an imported `wff` one. Only the logical rules
(→R, →L, ∀R) spell connectives and are written per parent. Stated as a rule:
**the part of a sequent calculus that does not mention a connective is the part
that transfers to any parent**, and it is the majority of the machinery.

*Pinned, besides the above:* both calculi check in one system and neither leaks
into the other (a Hilbert axiom does not justify a sequent line, and the lift is
therefore not optional); the eigenvariable proviso is asked about **inherited**
notation and `occurs` descends across the layer boundary, which is what §5.1's
"one flat grammar" means in practice; and an imported theorem promoted the way a
walk promotes it lifts into a sequent.

*From review*, two of which are worth carrying past this phase. The
`turnstile=` parameter reached the turnstile production and `lift` and nothing
else — every structural rule spelled `⊢` directly, so an alternative token built
cleanly and left `id`, `WL`, `XL`, `CL` and `cut` silently dead. **The worst
shape a parameter can have is one whose misuse the build accepts**, and the fix
is not the threading but the test that *uses* the knob. And the test asserting
what the core mentions inspected its productions and not its rules, so a rule
smuggling a connective in would have left the claim false with everything green;
it now checks every schema's tokens against the layer's own three, which refuses
a connective nobody thought to look for.

It also answers S1's third finding — that `id` alone cannot supply a *non-vacuous*
∀R premise, so S1 had to declare an axiom of the object theory to test the
proviso at all. Here the **parent** supplies it: `lift` brings in a Hilbert
theorem about `x` that the context does not contain. The bridge does real work.

#### S4 — *conditional on S3* — an AC matcher for contexts

**Delivers** sequents without structural bookkeeping.

**Tests and verification:** every S1 test re-run with exchange and contraction
*removed from the proofs* — they must still pass, which is exactly the claim.
Plus: contraction of unequal assumptions still rejected; a matcher stress case
with a context large enough that a naive AC search would not terminate.

---

### Track D — the importer

#### D1 — keep the outline; measure — **done**

The parser half landed separately, in the Metamath track: `metamath/sections.py`
reads the 1,903 headers `set.mm` draws and `Placement.covering` answers which
section covers a statement. What was left was **the measurement**, which §7.1
said was one run away and which is what this phase actually delivers — plus
`setmm.LAYERS`, the plan the numbers justify, since a measurement with nothing
to hold it is a paragraph nobody re-runs.

**Tests and verification** — `tests/test_metamath_sections.py` (the plan, on a
fixture shaped like the file), and the measurement below, taken against the real
`set.mm` at a 50,625-assertion snapshot. The file grows: earlier figures in this
repository were taken at 50,550 assertions and 1,559 logical `$a`, and the same
counts read 50,625 and 1,561 today. What that moves is the last digit of each
row, not the partition — so read the table for the shape and the boundaries, and
re-run the measurement rather than trusting a year-old total.

| layer | assertions | opens at | `$a |-` (its primitives) |
|---|---|---|---|
| Propositional calculus | 1,808 | 0 | 17 |
| First-order logic | 926 | 1,808 | 16 |
| ZF set theory | 47,891 | 2,734 | 1,528 |

**§7.1's prediction holds exactly.** The first 1,000 theorems are **100%
propositional** — so that slice exercises the partition and *no transfer
whatsoever*, and would prove nothing about (a) or (b). The smallest slice
populating all three layers is **N = 2,676**, which is the milestone figure §7.1
said should replace a guess.

**And the unit is part of the figure** (found in review). The table above indexes
`Database.order`, which holds every `$a` and `$p`; a walk's `limit` counts what
`corpus.theorems` yields, which is provable `$p` alone — 47,617 of the 50,625, so
1,773 / 902 / 44,942 per layer. The ZF boundary is position **2,734** in one unit
and theorem **2,676** in the other, and passing the first where the second is
meant would overshoot the milestone by the 59 axioms between them. The 1,000
prediction survives in both units, since propositional calculus has 1,773
theorems; N does not.

**A second milestone, which D3 is what made visible.** At 2,676 all three layers
hold theorems, but the third declares no *notation*: `set.mm` opens ZF with
`ax-ext` and five theorems (`axexte`, `axextg`, `axextb`, `axextmo`, `nulmo`)
before its first new syntax axiom, `cab`. So a ZF spec built at N holds no
productions at all, and a slice meant to exercise one spec **per layer** — rather
than one spine across layers — wants **2,681**. Both are real and they answer
different questions: 2,676 says the spine is exercised, 2,681 says the split is.

**The partition holds at the grammar level**, checked rather than assumed: no
`|-` statement anywhere in the file uses a constant first declared in a *later*
layer. That is precisely what D3 needs in order to build one spec per layer, and
it is now a fact about the file rather than a hope. (The syntax constants split
18 / 8 / 1,401 across the three layers.)

**§7.3's first bullet is answered, and the news is good.** Of 43,889 distinct
`|-` statements, **43,647 appear in exactly one layer**, 236 in two and 6 in all
three — 0.55% cross-layer duplication at statement level. So fragmenting the term
graph across three systems costs very little, and §7.3's escape (keying terms by
the spine root) stays unbuilt, which is what it wanted.

**And one consequence nobody was looking for, which reaches back into Track S.**
§9.24 left obligation-completeness open because an interpretation onto `set.mm`
would owe an obligation per primitive, and the corpus has **1,561** of them (the
1,559 this note quotes elsewhere, on an older snapshot).
Per *layer* it owes 17 (propositional) or 33 (cumulative through FOL). So
**layering is what makes the completeness check affordable** — and the layers a
sequent interpretation actually targets are exactly the two small ones. The
question §9.22 deferred to Track D turns out to have been waiting on this
measurement rather than on a design decision.

*Pinned:* the plan is data (`setmm.LAYERS`), on the same contract as `BINDERS`
and `EQUIVALENCES` — a file that opens no layer of it simply has none, since a
variant `.mm` may stop before ZFC. What *is* refused is a plan whose layers open
out of file order, because that is a plan about a different file and every
position it then reports would be silently wrong.

*From review*, two worth carrying. The milestone figure **was in the wrong
unit** — 2,735 is a position in `Database.order`, and a walk's `limit` counts
theorems, so the planned D4/D5 experiment would have run a horizon 59 axioms too
wide. The numbers are the deliverable here, and a number whose unit is not stated
is not a measurement; both are now given, with the gap between them named.
`test_a_layer_boundary_is_two_different_numbers_in_two_units` is the guard.

And that order check first compared each layer's
**position**, and two headers may share one — a part followed straight away by a
section, with no statement between, which is how `set.mm` opens every one of its
21 parts. So a reversed plan naming both passed the check and then attributed
the whole file to the wrong layer. Order is compared on the *section* now, and
sharing a position stays legal with the later layer winning it, on the same
nearest-wins rule the rest of the spine follows. The general shape is one this
note keeps meeting: **a guard that compares derived values instead of the thing
being ordered is a guard with a tie it does not see.**

#### D2/D3 — the layer plan and one spec per layer — **done**

D2 landed with D1: `setmm.LAYERS` is the plan, justified by the measurement
rather than asserted. D3's **spec** half is `corpus_specs(database, limit, plan)`
in `metamath/corpus.py` — one `SystemSpec` per layer, root first — and its
**store** half is `layered_systems` plus `import_corpus(plan=…)` in
`app/db/metamath_store.py`: one `formal_systems` row per layer, wired by
`inherits_from_id`, with each theorem, proof and promoted entry stored against
the layer its own section falls in.

**Tests and verification** — `tests/test_metamath_layered_specs.py`, on a fixture
shaped like the file, plus a run against the real `set.mm` at the milestone
slice.

*The contract, and it is the whole phase:* layering the pieces back declares
exactly what the unlayered spec declares — `layered_spec(corpus_specs(…))`
against `corpus_spec(…)`, same names and the notation in the same order. The
partition moves where a production is *stored*; it moves nothing about what the
grammar is. Verified on `set.mm` at N: 48 productions either way, 34 / 14 / 0
across the layers, and 34 / 14 / 1 at 2,681 where ZF's notation begins.

*Pinned:* the layers are **deltas after the first** — only the root carries the
line type and the brackets, because `layered_spec` refuses a redeclared name
across a chain and that is the shape `tests/layered_systems.py` writes by hand.
An empty plan, or one the file opens no layer of, is exactly today's single spec,
which is the discipline `BINDERS` and `EQUIVALENCES` already follow. A limit
short of a layer drops it; a layer with theorems and **no notation** is kept,
since dropping it would put its theorems in the layer below, which is the one
thing the partition exists to prevent.

*One thing the split found that the measurement could not.* Splitting per layer
made a second milestone visible: at N = 2,676 every layer holds theorems, but ZF
declares no notation until 2,681, because the file opens it with `ax-ext` and
five theorems before `cab`. §8's D1 carries both figures and what each answers.

*From review*, and the first was wrong on the real file rather than only in
principle. `build_spec` reads `before` **exclusively** and `variable_scope`
**inclusively** — deliberately, so an ordered walk's leaves do not lag behind the
theorem being checked — and passing one label as both makes the windows differ by
an assertion. At a *boundary* that assertion is the next layer's first, so a
`$f` typed there was declared by the layer below: **five of `set.mm`'s
productions were in the wrong layer**, which is the one thing the partition
exists to prevent. The fixture could not catch it, since its own variables all
sit in the preamble.

And the contract had a second hole, in the one field only the root carries.
`_logical_sort` reads the sort a `|-` statement is written in off the productions
it can see, so a root built at the *first boundary* can settle on a different
sort from the one the whole file settles on — a corpus whose `wff` typecode
arrives in a later layer gives the chain a line type reading at some earlier
fallback, and the layered grammar then parses proof statements differently from
the unlayered one. The root's productions stay boundary-scoped; its **line type
is the horizon's**, because there is nowhere else for it to live. `set.mm` is not
shaped this way — `wi` is in its first section — so this needed a fixture of its
own, which is the second time in this phase that the file being well behaved hid
a hole in the general case.

Three more: two plan layers sharing a start emitted a wholly empty layer (a part
header and its section share a position — how the file opens each of its 21
parts); the single-reached-layer fallback stored it under the *corpus's* name, so
the same slice came back as "Metamath" at `limit=1` and "Propositional calculus"
at `limit=2`; and `plan` had taken the third positional slot `corpus_spec` gives
to `name`, so the obvious call died inside `Layering`.

**The store half**, and the two things it settled that the spec half could not.

*Publication is not a step, it is a consequence.* §7.2 sketched each layer as
"published on completion, which is what lets the next one inherit it", and
completion turns out to be too late: a child's terms intern against its own chain
from the first theorem stored, so the chain has to exist and be readable before
the walk reaches the child at all. Publishing at creation costs nothing, because
an imported layer's grammar is fixed by the file the moment it is written — there
is no draft period during which it could move, which is the thing the flag
protects against. And the rule that falls out is §5.1's own rather than a new
one: **a layer is published exactly when something inherits from it**. The
deepest is not, which is also what makes an unlayered import — one system, no
children — behave precisely as it did before.

*A digest is per layer, not per corpus.* A layer's stored terms are guarded by
its **effective** digest — its own parts behind its ancestors' — which is what
`LibraryChain` reads on the citation path (§3.1). One `library_digest(spec)`
would be right for the root and silently wrong for everything under it, and the
failure would not appear until something cited across a layer.

*Pinned:* a layered run and an unlayered run of the same file agree on the
theorem count, the per-theorem verdicts and the **byte-identical proof sources** —
asserted against each other rather than against remembered numbers, which is
§7.2's "the emitted proof text does not change" and the shape D5's headline
invariant will take. A batched run files every theorem in the same layer as an
unbatched one, which is the case a checkpoint could break: it empties the
identity map and re-attaches the system, and a spine has several to re-attach.

*From review, and the general rule it produced.* The store half's mistakes were
all one mistake: **everything a read path reaches by system id has to follow the
split**, and the first cut moved only the proofs and the library. So
`_link_proofs_to_theorems` still filtered on the deepest layer, and linked that
layer's proofs while leaving every other layer's `theorem_id` null; the outline
was stored whole against the leaf, so each ancestor listed no folders while the
leaf reported nought proofs in each of its own (the folder route is
system-scoped at both ends); and the descriptions went to the leaf, which
`load_description` — deliberately unlayered, since a child cannot describe a
label it does not declare — could then never find for an ancestor's proof. Each
now partitions by the boundaries that decided which specs exist.

**Notation is the one exception, and it goes on the root.** A `$t` block is a
single declaration about the whole file rather than something each layer has its
own of, and a notation is read *root-first up the chain*
(`notations_mapping.notation_layers`), so the root is the one place every layer
can see it from. On the leaf it would be invisible to all of its ancestors —
which, for an imported corpus, is every notation there is.

*And one regression on the path that was already shipping.* Rebinding after a
checkpoint by **rebuilding** the routing object reattaches nothing the walk can
see: `walk` is handed one `store` callable before the first checkpoint and holds
it for the whole run, so every later assertion was written through a
`FormalSystem` that `expunge_all` had detached — and the label→id map went with
it, leaving the proofs unlinked besides. A real import is batched
(`scripts/import_metamath.py` defaults to `--batch 50`) and **unlayered**, so
this cost the entire promoted-theorem library of every corpus import, plan or no
plan. A rebind has to mutate in place. The existing batched test filed proofs
correctly throughout and never looked at the library, which is why it passed.

*And one in the derivation both halves read.* `corpus_layers` paired the
boundaries back with their opening positions through a dict keyed on the layer's
**name** — and a `Layer`'s name is a display name that nothing prohibits two
layers from sharing. A plan calling three layers `Logic` therefore kept one
position, and while `corpus_specs` still emitted all three systems, every layer
but the last routed its theorems into the *root*: filed under a grammar that does
not declare their notation, which a row-based reload cannot rebuild. The
boundaries already carried the positions by occurrence, so they are read off
them (`_Boundary`) rather than re-derived — which is what "one function rather
than two" was supposed to mean in the first place.

*Still to do here:* the invalid case the original plan named
— a plan assigning a production to a layer *after* a theorem that uses it. D1
established that `set.mm` presents no such case (no `|-` statement uses a
constant first declared later), so the check has nothing to catch on this file
and belongs with whatever first reads a plan it did not measure.

#### D4 — store each theorem in its layer — **done**

The *mechanism* landed with D3's store half; what D4 is, is running it on the
corpus and giving an operator a way to. Three things:

`scripts/import_metamath.py` gains **`--setmm-layers`**, off by default and for
the reason `--setmm-overrides` is: a layer plan names one library's own section
titles. The report gains a **per-layer breakdown** (`ImportReport.layers`),
counted as the run goes rather than derived by a reader — a stored row keeps the
system it landed in, not the section that put it there. One entry for an
unlayered import, so nothing has to ask whether a plan was given before reading
it.

`scripts/check_layering.py` is the **headline invariant**, run against a real
`.mm` at any slice: import the file twice, flat and spined, and assert a strict
equality on the counters, the promoted library label-for-label, the folder
titles, the documented labels, and the **byte-identical proof sources**. A script
rather than a test because `set.mm` is not in the repository and the claim is
about `set.mm`; `tests/test_metamath_layered_store.py` pins the same equality on
a fixture, which proves the mechanism and not the corpus.

**Measured at the milestone slice, N = 2,676:** 2,676 checked, 2,676 verified, 0
rejected, 0 failed; 2,710 promoted (34 primitive, 0 refused); 78 folders; 2,736
documented labels — and **every proof source byte-identical** between the two
runs. The partition is **1,773 / 902 / 1**, which is D1's milestone confirmed
from the other end: 2,676 is the smallest slice at which ZF holds a theorem, and
it holds exactly one. Roughly 90s per run, so the whole check is a few minutes.

*What the corpus found that the fixture could not, and it is the phase's real
result.* A promoted theorem's side conditions name a sort, which
`side_conditions_mapping` resolves to a real `symbols` **FK** — and each layer's
library was resolving that through its *own* `symbols` rows. `wff_var` is
declared wherever the `$f` for a `wff` is, which on `set.mm` is the propositional
layer, while the theorems carrying a `$d` over a `wff` metavariable run to the
top of the file. So **354 of the first 2,676 promotions were refused** under a
spine — `ax-5`, `nfv`, `19.21v` and everything downstream of them — and every
proof citing one lost its library entry, silently, because a refused promotion is
counted apart from a failed proof.

The fix is the same sentence as every other one in this track: a layer's
effective view is its ancestors' plus its own (`_effective_symbols`). The FK
points at the **ancestor's** row rather than a copy, which is §5.1's guarantee
being cheap for the reason §5.1 gives.

Why the fixture missed it is worth recording, because it is the third instance of
one pattern: every `$f` in the shared fixture sits in the preamble, so every
variable production lands in the root and each layer's own table happens to
suffice. `tests/test_metamath_layered_store.py::SCOPED_VARIABLES` is a second
fixture shaped the way the file actually is — variables declared *inside* a layer,
and a `$d` stated one layer up.

And the counters alone would not have shown it. `theorems_failed` is deliberately
counted apart from `failed` — a theorem that would not *store* against a proof
that would not *check* — so a run promoting 354 fewer theorems still reported the
same checked, verified and rejected. What caught it was comparing the promoted
labels **as a set**; the counter comparison was added afterwards, so the next one
is caught by both.

*From review, and it is the harness's own version of the same lesson — twice
over.* The script compared two runs without ever asking whether the second one
**was a spine**. A plan whose section titles the file does not open — or a
`--limit` short of the second boundary — collapses it to one system, and then
every equality holds because the two runs are the same run: at `--limit 1`
against the repository's own fixture it printed "Layering changed nothing" and
exited 0 having compared nothing.

The first cut of that guard was itself too weak, which is the part worth
recording. Requiring that *some two* layers carry proofs, with the counts summing
correctly, passes a run that filed every ZF theorem under first-order logic —
two non-empty shares is all such a check ever asks, and **every other comparison
in the script is blind to which system a row landed in**. So the partition is now
compared element by element against `expected_owners`, which derives from the
file and the plan rather than reading the answer back from the run: a regression
anywhere between the boundaries and the stored row — `_layer_of_label`,
`_Routed`, `index_of`, the checkpoint rebind — shows up as a disagreement.
Verified by misfiling the deepest layer on purpose, which the weak guard passed
and this one names. Vacuity is now asked of the *expected* partition too, so a
run that wrongly collapsed is a failure rather than an excuse.

`compare` is a pure function over two summaries and the expected partition, so
`tests/test_check_layering.py` pins all of it without needing the corpus.

The other review finding was latent rather than live: `_Library` is unusable
until it holds a system, and `_Layers` was publishing the routed `store` before
binding them. Nothing reaches it in that window today — the walk has not started
— but `_Routed.store` swallows what goes wrong into `theorems_failed`, so
anything that ever did would lose promotions silently rather than raise. Bound
before publishing now.

#### D5 — the invariants

- *Invalid, each a hard failure of the run:* a deliberately misfiled plan
  (`ax-mp` assigned to ZFC) must fail loudly rather than quietly dropping the
  theorems that cite it; a synthesised forward-layer citation must be caught;
  a citation that resolves to nothing must fail the run.
- **Bound variables at corpus scale:** spot-check that a `$d`-carrying theorem
  imported into FOL still refuses a capturing citation from ZFC — the R2 test,
  run against real `set.mm` data rather than a fixture.
- *Pinned:* the same slice imported twice gives the same partition (determinism);
  re-verifying a stored layered proof from its rows gives the same verdict as the
  import did.
- The **valid** case is already met — see D4's measurement — and
  `scripts/check_layering.py` is where D5's additions belong, since a hard
  failure is a difference between two runs like any other.

#### D6 — the provenance report

- *Valid:* over the slice, every PC theorem reports PC as its deepest dependency.
- *Invalid:* a theorem seeded with a citation one layer up is reported as
  misfiled.
- *Pinned:* the report is computed from `proof_line_antecedents` and
  `promoted_theorems` — a graph query (§3.3) — and a test asserts it never reads
  proof *source*.

---

### Dependencies

```
R1 ──▶ R2 ──▶ R3 ──▶ R3a
  │      │
  │      └──▶ D3 ──▶ D4 ──▶ D5 ──▶ D6
  │                    ▲
  │            D1 ──▶ D2
  └──▶ R4a ─▶ R4b ─▶ R4c
        │
        └──▶ S2
             ▲
      S1 ────┘──▶ S3 ──▶ S4
```

S1 and D1 depend on nothing and can start immediately. S2 needs an edge that
resolves (R4a) rather than one an author can write (R4c).

---

## 9. Risks and open questions

1. **Digest churn across the chain.** A child's `library_digest` covers its
   ancestors, so any parent edit misses every descendant's cached terms. The
   freeze-on-publish rule (§5.1) makes this a non-event in practice, but it means
   the freeze is *load-bearing* rather than tidy — the same shift
   `proof_lines` invalidation went through in `docs/verification-from-rows.md`,
   and worth the same care.
2. **Name collisions between layers.** Refusing them is right, but `set.mm`'s
   1,441 productions across three layers is where it will first be tested. If the
   partition produces a collision, the layer plan is wrong. Note that §3.1's term
   rebuild *depends* on this guard, so a relaxation later would be a soundness
   change, not a convenience.
3. **Existing checks firing across a boundary.** `_validate_constant_declarations`
   and `_require_a_fresh_defined_form` both get stricter under inheritance
   (§5.1). Both fail safe; both need error messages that name the offending
   layer, or a failure is unreadable.
4. **Term-graph duplication.** Measured in D1, escape route in §7.3, not to be
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
8. **Over-refusal is the failure mode nothing else catches.** Every guard here
   errs safe, which means a bug in one shows up as a *valid* proof being
   rejected — invisible to a suite that only tests rejections. That is why §8.0
   requires a complex accepted case per phase, and why the bound-variable tests
   are written in accepted/rejected pairs.

The fourteen below are **findings from the phases that landed**, kept here because
each is a live constraint on the work after it rather than a closed question.

9. **The freshness check was position-blind, and a tower is not.** §5.1 predicted
   `_require_a_fresh_defined_form` getting *stricter* under inheritance, which it
   does and should. What it missed is the other direction: read flat, the chain
   also holds an *ancestor's* definition to a *descendant's* axioms. That refuses
   the ordinary tower — the propositional layer defines `∧`, ZFC's extensionality
   axiom is stated over `∧`, and the definition then looks like it is redefining
   a symbol the theory already constrains. Within one layer the whole-spec
   reading is right (every axiom is built before every definition, so there is no
   order to respect); across layers it is wrong, because publishing the parent
   *is* the order. `SystemSpec.definition_scope` records, per definition, how many
   of `axioms`/`rules` precede it; empty means the flat reading and is what a
   single-layer spec still says. Pinned both ways in `tests/test_layered_spec.py`
   — the tower builds, and the same spec with the scope flattened does not.
10. **A layer's rows must name sorts it does not declare.** ZFC's `⊆` is a
    `formula` over `term`, and neither is its own. `spec_to_system` built symbols
    from `SystemSpec.sort_names()`, which reads the *productions*, so storing such
    a layer raised `KeyError`. The fix keeps each system's rows self-contained —
    a symbol row of its own for every sort it *mentions* (`_named_sorts`), rather
    than an FK into an ancestor's namespace that the ancestor's delete would take
    with it. The row is a union with no members, which is what a declared sort of
    a layer already looks like, and `system_to_spec` emits nothing for either.
11. **An ancestor's cached term is guarded by the *ancestor's* digest.** §5.2
    said the child promotes an ancestor's entry "applying the edge's sort map",
    and left the digest unsaid — which reads as though the citing system's
    digest guards it. It cannot: the two cover different grammars by
    construction, so every cross-layer citation would miss and re-parse. Worse,
    the re-parse is the *wrong* answer, by exactly the argument
    `promoted_theorems_mapping` already makes for an imported corpus — the
    ancestor composed its statement against the grammar it was proved in, and
    the child's is wider, so re-composing can read the statement through
    notation declared later. So each layer carries its own digest, and because
    an ancestor is frozen, a cross-layer citation reliably hits. Pinned by a
    test that makes composing fatal and cites across two layers anyway.
12. **The fallback parse is unsound *across* a layer, not merely approximate.**
    §9.11 argued the cached term is the faithful one and the re-parse the
    approximation — and then left the re-parse in place as the fallback, which
    is the same mistake stated twice. For an entry of the citing system the
    fallback is right: the grammar it is re-read against is the one that owns
    it. For an *inherited* entry it is not — the citing grammar is wider, and
    notation declared later captures an earlier statement's parse (the reason
    `corpus.walk` scopes notation by position at all, metamath roadmap §1.4). So
    the theorem would mean something its own system never established, and could
    justify a step that system could not. An inherited entry with no usable
    cached term is therefore **refused**, and the citation does not resolve.
    Two ways in, because a matching digest is not on its own enough: the digest
    can be missing or stale, and — since a term FK is `ON DELETE SET NULL` and a
    NULL is documented as a *miss* rather than "composes to nothing" — an entry
    can pass the digest and still have lost the term the digest promised. The
    second is checked as the hazard itself rather than by a proxy, because
    refusing every NULL would be far too strict: a bare metavariable composes
    nothing in *any* grammar, and that is the ordinary shape of a hypothesis
    (every Metamath `$e` of the form `|- ph` stores NULL and always did). So for
    an inherited entry a schema term must have come from the cache or not exist;
    one composed *here* was composed against the wrong grammar.
    Reachable only through `store_theorem(..., promoted=None)` or a published
    system whose grammar moved, so it costs nothing today — but it is a
    difference rather than a cost, which is what decides it. The capability it
    gives up is transferring an entry stored without terms; getting that back
    means composing the statement against the *ancestor's* built system and
    re-interning the result, which is the cached path computed on demand.
13. ~~**The raw-text verify route resolves no library at all.**~~ **Closed.**
    `POST /formal-systems/{id}/verify` built the system and parsed the text but
    never resolved a citation, so a *theorem* resolved to nothing there. It is
    not a grammar check — it is the scratchpad behind `/systems/{id}/verify`,
    where a proof is typed against a stored system and checked without being
    stored. Survivable for a system whose primitives are all rules; useless for
    an imported corpus, where every logical statement is a promoted theorem
    rather than a rule, and pointed for a layered system, whose whole purpose is
    citing an ancestor's theorems. It now reads, resolves and checks — the same
    three steps `parse` is, split so the library fits between them. What it still
    does not resolve is a cited *proof*: a scratchpad proof is stored nowhere, so
    it has no references and establishes no library entry of its own.
14. **The schema-term cache is per system, and a chain has several — and it
    costs less than this entry first claimed.** A rule's composed term is a
    function of the whole chain's grammar, but `rules` carries one
    `schema_digest` column, so an ancestor's row cannot cache what its template
    composes to in a descendant. A system caches its own rules only (the
    `offset` in `app/db/schema_terms.py`), which leaves a child recomposing its
    inherited ones on every verify.

    This entry originally said that was "*not* fine for a layered set.mm, where
    the propositional layer holds the rules". That is **wrong**, and worth
    correcting rather than deleting: `metamath.importer.build_spec` constructs a
    `SystemSpec` with no `rules` and no `axioms` at all — every logical `$a` and
    `$p` becomes a *promoted theorem*, because building 1,559 axioms eagerly is
    what the metamath roadmap measured as not scaling. So a layered `set.mm`
    inherits **no** rules and recomposes nothing. The case named as the danger is
    the case that costs zero.

    What it does cost, measured on the three-layer tower: 7.3 ms to build with
    its 7 rules against 3.2 ms with them removed, so ~0.6 ms per rule at that
    grammar size, rising with the grammar as any parse does (0.4 ms at 18
    productions, 1.1 ms at 309). A deep hand-authored tower — say 30 inherited
    rules at ZFC scale — is therefore tens of milliseconds per verify, next to
    `load_effective`'s own ~24 ms. Real, and not a table's worth.

    So: **do not build the row-per-(rule, digest) table.** If it ever does bite,
    the cheaper answer is a process-level memo keyed by the chain's grammar
    digest and the rule's label — the access pattern is one system verified
    repeatedly — which needs no migration and no second invalidation contract.

15. **What promotion is gated on, and what retiring an entry has to reach.**
    §5.3 named three guards — valid, warning-free, owned — and both halves of
    that turn out to be incomplete once R2 is in place.

    The gate is **publication**, not validity. R2 makes a system's library
    resolvable from every descendant, and a descendant may be someone else's — a
    published parent is exactly the case where it is — so promoting a *draft*
    proof would hand its statement to strangers by a route that never asks who is
    reading. Publication is also what keeps the entry stable, since
    `_require_publishable` re-runs on every source edit and a published proof
    cannot be edited into not standing. And it costs nothing extra to require:
    publishing a proof already demands that it verify, so §5.3's guards are
    implied rather than dropped.

    Conveniently it aligns with §9.11: a citable entry is now exactly as frozen
    as the ancestor systems that argument depends on.

    **Retirement has to invalidate what cited the entry.** Deleting the row is
    the easy half — the citing proof then fails its *next* verify. But a proof
    that already verified keeps `valid`, `result` and its `proof_lines` rows, and
    a verify now *trusts* a lemma's stored rows rather than re-checking them
    (`docs/verification-from-rows.md`), so a third proof citing that one would
    rest on a theorem the database no longer has. Which proofs cited it is
    answerable from the rows — a promoted theorem resolves to an ephemeral rule
    carrying its label, and `proof_lines.rule` records it — so this is a query,
    not a re-parse. It walks descendants and stops at a system declaring the same
    label itself, following the resolver's own shadowing rule so it invalidates
    nothing that was never citing the entry.

    This is also the one place a route takes **more than one** system lock, which
    `_common.lock_system` had been able to say never happens — and getting that
    order right took two attempts, the second from Codex.

    Sorting the set by id is *not* a global order, because every caller arrives
    already holding the subtree root's lock: a verify takes it before reading
    anything, an invalidation before writing. So a sorted set can put a
    descendant's key ahead of one already held, and two operations at different
    levels of one tower acquire in opposite orders — Postgres detects the cycle
    and aborts one. The order that works is **(depth, id)**: a system's depth is a
    property of the tower rather than of who is asking, so any two operations
    order any two systems they share identically, and the pre-held key is
    automatically first, being the unique shallowest member of its own subtree.
    Inheritance is single-parent, so two subtrees are nested or disjoint and
    there is no third case.

    The general lesson, worth carrying to any future multi-key caller: a lock
    order has to account for the keys a caller **already holds**, not just the
    ones it is about to take.

    Two consequences worth stating. A locally-promoted entry needs a warrant
    distinguishable from an imported one, which is `promoted_theorems.proved_by_id`
    — an import leaves it NULL, so a grammar edit that invalidates every proof in
    a 49,000-theorem corpus withdraws none of its library. And a *retired* entry
    is gone rather than tombstoned: nothing records that a label used to resolve,
    so a proof invalidated this way reports an unresolved citation and not the
    reason. Recoverable from `proof_lines.rule` if it is ever worth saying.

    Review sharpened this into a general statement, which is the form to keep:
    **what a label resolves to changing at all is the event**, and retirement is
    only one way it changes. *Promoting* one an ancestor already carries is
    another — shadowing is legal, R2 resolves nearest-first, so refusing it would
    contradict that — and it silently redirects every citation at or below the
    promoting layer. So promotion invalidates the label's citers too, on exactly
    the same call.

    Three details the first cut got wrong, each worth recording because each is a
    place the *resolver's* behaviour has to be mirrored rather than approximated:

    - **Shadowing includes rules.** `Proof.get_reference` tries `rule_by_label`
      before the library, so a descendant declaring an inference rule of that
      name shadows an ancestor's theorem as thoroughly as a nearer theorem does.
      A walk that looked only for theorems wiped that subtree's verdicts for an
      entry it never reached.
    - **A citer is itself citable.** Clearing the direct citers is half the
      mechanism: a proof resting on a citer rests on the entry one hop back, and
      a verify trusts a lemma's stored rows. The invalidation follows the
      reference graph out from the citers.
    - **The reference set is part of the proof.** Dropping a lemma reference can
      leave a promoted entry standing behind a proof that no longer verifies, so
      it retires on the same rule a source edit does.

    And one that is not about resolution at all: the default label is the proof's
    *slug*, which is not a label. `slugify` produces anything URL-safe — a leading
    digit, up to the 256 characters a name may run to — while a label must be
    citable as `[label]` and must fit `String(128)`. Derived defaults get the same
    validation an explicit label does, or the two failure modes are a citation
    that never parses and a Postgres truncation 500.

16. **A nomination is a claim, and the checker can settle it.** Schematic
    promotion looked like it needed a *schematicity analysis* — deciding whether
    a proof is uniform in a leaf, which is the obligation §1.1 names and which
    reads as hard. It is not, because the claim has a direct test: abstract the
    nominated leaves in **every line** and re-check the proof. What comes back is
    a proof of the schematic statement, so the theorem is warranted rather than
    argued for, and the guards are the checker's own — a leaf a rule spells
    literally, or one nominated at the wrong sort, simply stops the step
    matching. Nothing here maintains a list of what may be generalised.

    The abstraction is `kernel.abstract` over each line's already-checked term,
    so it is §3's term-level operation and not a source rewrite: the leaves are
    replaced by *what they denote*.

    **The provisos have to travel, and `restate` already did the hard part.** A
    step may have relied on a side condition — `ax-5`'s `not occurs(x, P)` — that
    held for the concrete leaves and says nothing about an arbitrary instance.
    Each is restated over the binding that step made and carried into the entry,
    where a citation re-checks it against its own instantiation. The binding is
    the one thing that had to be added: `Inference` recorded the rule and the
    lines but discarded the match, so it now keeps it.

    One rule the design did not anticipate: a restated condition mentioning
    **none** of the theorem's metavariables is dropped. It is a closed fact about
    ground terms, settled by the check that just ran, and storing it would be an
    obligation with nothing to discharge it against. The converse trap is nearer
    than it looks — `not occurs(x, y = y)` with only `x` nominated *does* mention
    a metavariable and *is* a real constraint on the instance, so "the formula
    side is ground" is not the test. Both cases are pinned.

    **Three shapes are refused rather than generalised**, all found in review,
    and all the same failure: re-checking the abstracted proof *passes without
    having tested anything*, so accepting would mint a theorem on no evidence.

    - A **string-rewriting** step matches surface text, and a variable renders as
      its own name — so the abstracted proof is character-for-character the one
      already checked. Left to the check, MIU's `MII` promotes to a theorem whose
      whole statement is one metavariable, justifying `MU`, `MIU`, anything.
    - An **axiom-behaviour line** is granted by matching its own shape; `execute`
      short-circuits on it, so an abstracted term is never held to the axiom's
      schema and a leaf the axiom spells could be generalised away unnoticed.
    - An **eigenvariable subproof** is the sharper half of the hole R3a set out to
      close. `ax-5`'s proviso is a `SideCondition` and travels; a *discharge*
      rule's freshness is `Subproof.eigenvariable_is_fresh`, and a discharge
      builds no `Inference` — so there is no binding to restate and nothing to
      carry.
    - A **definitional step** is the same gap by a second route (Codex, on #160):
      it cites a definition rather than a rule, so it too builds no `Inference`,
      and what goes missing is a definition's own proviso *and* the binder
      freshness `fresh` generates. Unfold `a ⊆ b`, hold `a` schematic, and the
      theorem hands a citation the instance putting the bound `z` where `a` was —
      the capture the unfold itself refuses. Refused in the narrow form: a
      nomination that *changes* an unfolded line, not any proof that unfolds,
      since otherwise a system whose notation is defined could never promote
      schematically at all.

    Those last two are **the piece of R3a still open**, and they are one piece:
    both want the constraint restated over a binding that discharge and
    definitional steps do not currently record. Retaining it for them is what
    `Inference.binding` already does for ordinary rule steps.

    A fourth refusal is about the *carrying* rather than the abstraction: a
    citation binds only the metavariables its statement mentions, so a proviso
    naming anything else could never be discharged — it would raise inside every
    citation and read as "this theorem does not apply". Refused at promotion
    instead of stored uncitable.

    What this does not do is decide uniformity for a proof it *cannot* re-check —
    an imported theorem with no stored proof, say. There the nomination would
    still have to be trusted, which is an argument for keeping promotion tied to
    a proof that stands here.

17. **A rename is checked where the check can be made, not where it belongs.**
    §3.2 says a sort map is validated by projecting *both* grammars, and that is
    the whole difficulty: `Constructor.admits` exists only once a system is
    built, so the check needs the source built as well as the target. It
    therefore runs on the citation path (`related_layers`), where the source is
    a row and the target is a spec, and it builds both.

    Two things keep that honest. It runs **only for an edge that declares a
    map** — an edge with empty sort and symbol tables is the identity, has
    nothing to check, and costs exactly what it did before R4b, which is
    nothing. And it is the *conservative* placement: a stale check cannot
    outlive a grammar edit, because there is no stored verdict to go stale.

    Where it belongs is the edge's **write**: a map is a claim about two
    published grammars, neither of which moves, so checking it once as the edge
    is stored would be both cheaper and better-reported — an author would get
    `translation_errors`' actual messages rather than a citation that does not
    resolve. That waits on the edge CRUD, which is the piece of R4 still open.

    One asymmetry is deliberate. `_citing_systems` — the invalidation walk R4a's
    review added — follows a discharged edge **without** consulting its map, so
    an edge whose rename does not check out still counts as a way a label could
    reach. That over-reaches by exactly the proofs that were never resolving
    across it, which is the direction that is safe: R4a's rule is that reach and
    invalidation must agree, and they agree here in the only sense that matters —
    invalidation may reach further than resolution, never less.

    What is deliberately **not** checked is an edge whose map is empty. Two
    unrelated systems that happen to agree on their names transfer on the
    author's say-so, gated by the obligations and nothing else — which is R4a's
    shipped semantics rather than something R4b changed. Checking it would put
    a source build on every verify of every system with any edge at all, and the
    hazard it would catch (two systems whose `wff` differs) is the same one the
    obligations are there to carry.

18. **A rename has to carry three things besides the term, and only two of them
    are load-bearing.** The remap itself is a substitution in front of a name
    lookup (`TermGraph.term`), and it took one line. What took the thought is
    everything a `TheoremSpec` says in *names* rather than in structure.

    A **metavariable's sort** and a **proviso's sort argument** are both fatal
    if missed, and fail in opposite directions. The first raises immediately —
    promotion looks the sort name up in the target's grammar and finds nothing —
    so it cannot be got wrong quietly. The second is worse: a proviso whose sort
    argument does not resolve refuses *every* instance, so a suite of rejection
    tests passes with the mapping missing entirely, and only the accepted half
    of a pair catches it. That is §3.5 ("map the sort argument, leave the
    algebra untouched") turning out to have a sharp edge.

    The **statement's text** is the third, and it is hygiene rather than
    soundness: a transferred entry's string is re-rendered from its translated
    term, so it reads in the notation of the system it is cited in. A structural
    check would not have noticed a stale one — the term is what unifies — which
    is exactly why it is asserted directly rather than left to a proof standing.

    Three things a rename may **not** move, and the line between them is worth
    keeping: a production's `kind` and its `scopes_over` are refused because they
    decide what a term *is* and what binds in it, and its `slots` because a
    stored term keys its children by slot name and §5.4's tables carry no slot
    map. The first two are soundness; the third is a restriction on what an
    author may write, and would be lifted by a slot map rather than argued away.

    What is deliberately **not** compared is an atom's *value*. Renaming the
    source's `⊥` onto a target constant spelled something else is not a mistake —
    it is what an interpretation *is*, and §2's obligations are what make it
    sound. Structure is the map's business; meaning is the obligations'.

    One shape is refused outright: a **string-rewriting** theorem cannot cross a
    rename. It is checked against surface text, so what it says is a fact about
    the symbols its own system spells, and a rename is free to spell them
    differently here. Nothing in the two grammars settles whether the rewriting
    agrees — the same refusal, for the same reason, that `schematic_theorem`
    makes for a string step (§9.16).

19. **A map is not the set of names it mentions.** Four findings from review, and
    they are one: `translation_errors` validated the entries of the two tables,
    while `Translation.name` is applied to *every* name a stored term carries.
    The gap is the names nobody wrote down, and it is not a small one.

    Two of the four were **unsound transfers**, both silent. A production the two
    grammars share by name was never checked at all, so a target that kept the
    name `implication` and spelled it `(p ∨ q)` took a theorem proved as
    `(P → P)` and justified `(P ∨ P)` with it. And the map was not required to be
    **injective** — the unique index behind it is on the source side only — so
    sending both `implication` and `conjunction` to `conj` made a theorem about
    either justify a statement about the other.

    The other two **failed closed but in the wrong place**, aborting a verify
    with a message about something else. A defined form's constructor is named
    `<sort>:<template>`, which neither table can hold (a definition declares no
    symbol), so it was read whole, missed, and raised out of the term rebuild —
    against a target stating the very same definition. And a proviso argument
    that is not a metavariable is a *term expression* in the source's notation
    (AGENTS.md's one remaining parse), which reached `parse_side_condition` and
    failed as a syntax error.

    The fix is one shape for all four: **walk the source's whole grammar**, give
    every name an image, and hold an *unmapped* pair to being the same production
    down to its template — mapping a name to itself being how an author says they
    do correspond. A defined form's sort half is translated and its template is
    not, so a definition the two systems state alike crosses; one they spell
    differently is refused at the edge rather than when something cites it. The
    proviso stays a refusal, because translating that argument would mean
    re-rendering a parse this layer never made.

    The lesson generalises past this module: **whenever a substitution is applied
    more widely than it is declared, the check belongs on the application and not
    on the declaration.** The three checks R4b shipped with all read the two
    tables, which is why all three passed each of these.

20. **A permission the map gives is a debt the rebuild owes** (Codex, on #165).
    §9.18 records that a constant atom's *value* is deliberately not compared,
    because relabelling a constant is what an interpretation does. What that
    leaves unsaid is the other half: a constant's spelling belongs to the
    **production**, so a term rebuilt over the target's constructor has to carry
    the target's token. Keeping the row's — the source's `⊥` where this system
    writes `bot` — left the transferred theorem rendering as `⊥` and comparing
    unequal to everything the target can spell, so it applied to nothing at all.
    The check said yes and the transfer was dead, which is the shape of failure
    a suite of refusals is worst at seeing.

    The literal now comes from the constructor for a constant and from the row
    for everything else, which is the distinction that matters: every other
    leaf's literal is a *variable's name*, the term's own and no production's.
    That is also why an atom's **kind** is not free where its value is — a family
    (`p_#`) read as another base would put tokens into the target that its own
    grammar cannot mint, and no table describes that rewriting.

    Worth stating as a rule, since R4b has now met it twice: **every "deliberately
    not checked" is a claim about what some other code does with the difference.**
    §9.18's other two — `slots` and `scopes_over` — are checked precisely because
    nothing downstream could absorb them.

21. **Taking §9.17's escape, and what it does not buy.** The CRUD is where a
    rename's check belongs, and writing it settled three things the note left
    open.

    **The write-time check does not replace the resolution-time one.** §9.17
    called the runtime placement the price of having no route to hang the check
    on, which reads as though a route would let it go. It does not: either
    system may be a **draft**, whose grammar moves freely after an edge is
    written, so an edge checked once is not an edge that stays checked. What the
    route buys is the *report* — `translation_errors`' own words, at the moment
    the author can act on them — rather than a citation that silently does not
    resolve. Cheapness would need a stored verdict, and §9.14 already says what
    that costs.

    **A published system may be related.** Publishing freezes a *grammar*, so a
    proof checked against it stays checked against it. A system's **library** was
    never frozen — `POST /proofs/{id}/promote` writes into a published system's
    today — and an edge is library reach rather than grammar, so it belongs on
    the same side of that line. The route refuses an edit to the system and
    accepts an edge onto it, and the test asserts both halves in one place
    because the pairing *is* the claim.

    **Every field of an edge is one a verdict can rest on.** `status` is the
    gate, the obligations are what the gate reads, the maps decide whether it
    checks out at all, and `position` decides which of two edges wins a label
    both offer — so there is no partial edit that can skip the invalidation.
    Even *creating* one has to invalidate, which is not obvious: adding a
    resolution cannot make a failing proof's verdict wrong, but an edge arriving
    at a lower position silently redirects a citation that already resolved.

    The invalidation itself is §9.15's rule asked of a *library* rather than a
    label (`_invalidation.invalidate_library_reach`), and it differs from the
    label version in one way worth recording: there is no single label to be
    shadowed, so the walk stops nowhere and over-reaches by exactly the systems
    that declare some of these names themselves. That is the direction R4a
    already took for the edge half of the same walk — invalidation may reach
    further than resolution, never less — and the cost of the difference is a
    re-verify. The *proofs* are still narrowed, by joining `proof_lines.rule`
    against the source chain's labels rather than listing them: an imported
    corpus has tens of thousands, and a 49,000-item `IN` clause is not a query.

    One thing the CRUD deliberately does **not** do: repoint an edge. Changing
    its source is deleting one relationship and asserting another, and the two
    have different obligations — so it is a delete and a create, which is also
    two invalidations rather than one.

    **What review found, and the pattern across it.** Four of the five findings
    were the same mistake in different places: *a guard written for one half of
    a pair*.

    - The **theorem** half of a discharge was checked against the target's chain
      and the **primitive** half was not — so a rule label nothing declares
      discharged §2's obligation with a string, and the theorems transferred on
      it. The label is the easier of the two to mistype, which makes it the
      worse half to have missed.
    - The **duplicate-name** index was left to catch a map that says two things
      about one name, and it caught it twice wrongly: during a PATCH's autoflush,
      escaping as a 500 with a failed transaction, and on a create, through the
      same `except IntegrityError` as the (source, target) index — which then
      reported "these two systems are already related" about an edge that did not
      exist. One `except` per index, or the check before either.
    - The map's check ran on **every** PATCH rather than on the map, so once a
      grammar drifted the edge could not be edited at all — including the edit
      that turns it off, which is exactly the one its author needs. A write-time
      check belongs on *what is being written*; anything else is the
      resolution-time check's job, and it is still there.
    - And the fifth is the one this phase's own invariant should have predicted:
      an edge cascades from **either** end, so deleting a *source* takes the edge
      with it — and left the target's proofs holding a verdict resting on
      theorems that left with it. Every way an edge can disappear has to clear
      what resolved through it, and one of those ways is not in this router at
      all (`systems.delete_system`).

    Stated as a rule, since it is the same shape as §9.19's: **a guard on a
    relationship has to cover every way the relationship can end**, and the ways
    are rarely all in the module that creates it.

22. **The rule from §9.21, applied twice more — and the one claim still left to
    the author.** A second review round (Codex, on #166) found three things, and
    two of them are that same rule biting again in places the first round did not
    reach.

    **A source has to be published.** The CRUD first allowed an owned *draft*
    source, reasoning that an entry whose system moved under it already fails
    closed (§9.12). It does — on the *next* verify, while the proofs that already
    verified keep `valid`, `result` and their `proof_lines`, which a later verify
    trusts rather than re-checking. So a draft source repointed at another parent,
    or edited at all, leaves every target holding a verdict nobody would reach
    today. The alternative was to wire every source mutation into relation
    invalidation — every part edit, every repoint — and freezing is what the
    spine already chose for exactly this problem. Both now say one thing: **you
    may build on a system once it is frozen.**

    **Retiring a warrant is a way an edge stops resolving.** An obligation
    discharged by a theorem loses it to `ON DELETE SET NULL`, which leaves the
    obligation naming neither a primitive nor a theorem — outstanding, so the
    edge resolves nothing. But the proofs that crossed it cited the *source's*
    labels, not the warrant's, so the label walk that retires the theorem never
    reaches them (`_invalidation.invalidate_warranted_edges`). Together with
    §9.21's source-delete, that makes **three** ways an edge stops resolving that
    the relations router never sees.

    **And the claim left to the author.** An `interpretation` edge marked
    discharged with *no* obligations discharged the whole of §2 with a status
    column, and `related_layers` — which asks the obligations rather than the
    author — let the source's entire library across. That is refused now. What is
    deliberately **not** checked is whether the list is *complete*: one obligation
    per primitive of the source, which is what §2 actually asks for.

    **D1 has since changed the arithmetic**, and it is worth reading §8's D1
    before re-opening this. The figure this paragraph rests on — 1,559, or 1,561
    on the snapshot D1 measured — is the *whole corpus's*. Per layer the
    primitives are 17 (propositional) and 16 (first-order), because the
    remaining 1,528 are all ZF and below. So an interpretation onto the layers a
    sequent calculus actually targets owes 17 or 33 obligations rather than
    1,561, which is entirely writable and removes the objection this paragraph
    was built on.

    Left open on purpose, and the reason is worth recording so it is not
    re-litigated cheaply. The check itself is easy — the source chain's rules,
    plus its `primitive=True` promoted theorems. What is not settled is what that
    would *cost the cases this exists for*: an imported corpus's primitives are
    its 1,559 `$a` statements, so an interpretation onto `set.mm` would demand
    1,559 obligations, and §6.3 sketches S2 with nine. Either that sketch is
    wrong or "primitive" means something narrower than every `$a` — and Track S is
    where that gets decided, against a real edge rather than in the abstract. An
    `extension` edge is a separate question again: §5.4 says its obligations are
    filled in from the spine and never asked of an author, which would make
    `kind` mechanical rather than asserted.

23. **A "no engine change expected" that held, and what it cost instead.** S1 is
    the first phase whose plan predicted no engine change *and* said that needing
    one would be the finding. None was needed: a sequent calculus is a
    `SystemSpec`, and §6.2's grammar was declared as written. But the phase found
    two things all the same, and they are the same shape as each other — **the
    limits showed up in the schema language, not in the checker.**

    The eigenvariable proviso is stricter than LK's (bound occurrences count,
    because `Occurs` is syntactic), and ∀L cannot instantiate with a term
    (because a schema is matched by unification and has no substitution
    operator). S1 records both in full. What is worth keeping at this level is
    the pattern: when an expressive limit is reached, the question to ask is
    *which* language ran out — the kernel's judgements, the grammar, or the
    schema — because they fail differently and only one of them is a soundness
    surface. Both of these bottom out in the schema language, both refuse a
    superset of what a textbook calculus refuses, and neither can produce a wrong
    verdict; a limit in the kernel's judgements would have had to be argued about
    rather than merely documented.

    The practical consequence for S2: §6.3's sketch discharges `ax-4`…`ax-7` and
    `ax-gen` by sequent proofs, and `ax-gen`'s discharge will meet the stricter
    proviso head-on. Whether the over-approximation is *tolerable there* — rather
    than merely sound — is the first thing S2 finds out, and it is a better test
    of it than anything S1 could stage.

24. **A substitution has to hold uniformly in whatever it introduces — and a
    term composed against another build unifies with nothing.** Two findings
    from S2, and the first is the phase's content while the second is a rule
    about this codebase that reaches well past templates.

    **Uniformity.** §2's obligations say each source primitive has an image the
    target can derive. A *template* adds something §2 never contemplated: a
    metavariable the source theorem never had, universally quantified in every
    theorem that crosses. So the image must be derivable **for every value of
    it**, and that is a strictly stronger demand than "derivable". `ax-gen`
    passes the weak reading and fails the strong one — `Γ ⊢ P ⟹ Γ ⊢ ∀x P` is ∀R
    with the eigenvariable condition deleted — which is why §6.3's sketch of nine
    obligations was wrong about one of them.

    Stated generally: **an obligation is a claim about all instantiations of the
    template's extras, not about one.** The escape is to introduce nothing —
    a closed template — and then what the extras would have bought is bought
    instead by a structural step the author cites. That is not a workaround; it
    is the standard Hilbert-to-sequent argument (replay at the empty context,
    weaken at the end) arriving in the only form this mechanism can express.
    Which is itself worth noting: the *shape* of the sound translation was forced
    by what the edge could and could not check, and it turned out to be the
    textbook one.

    **What is deliberately still not checked** is whether an interpretation's
    obligations are **complete** — §9.22 left that to Track S to decide against a
    real edge, and this is the real edge. The evidence is now sharp and points
    one way: omit `ax-gen` from the Γ-template edge's obligations and it resolves,
    transferring every FOL theorem into a shape no discharge justifies. For an
    `interpretation`, completeness is not tidiness — **it is the whole of what
    makes the edge sound**, because the obligations are the only place the
    soundness argument lives. What has not changed is §9.22's cost: an imported
    corpus's primitives are its 1,559 `$a` statements, so requiring one
    obligation each would make an interpretation onto `set.mm` unwritable by
    hand. So the decision is between narrowing what "primitive" means and
    generating the obligations rather than asking for them, and it is a decision
    about the *importer* as much as about the edge — which puts it with Track D
    rather than here. Recorded, with the evidence it was waiting for.

    **Constructor identity.** The template was first built where the rename is
    checked, in `related_layers`, against the system that function builds to
    check maps. Every wrapped theorem then unified with nothing, silently: sort
    admission compares constructors **by identity** (`Constructor.admits`, and
    `tests/test_pattern_canonicity.py` holds the invariant), so a term built
    against one build of a grammar is unusable against another build of the same
    grammar. The rule, which is the same one §3.1 states for stored terms and is
    easy to rediscover the hard way: **a term is only ever composed against the
    system it will be checked in.** Anything an edge contributes to a promotion
    is therefore carried *declaratively* and composed at promotion time, and the
    check that it composes at all belongs on the write, where it has a request to
    report to.

25. **A line part's name is claimed chain-wide, and nothing about the grammar
    requires it.** The one thing that had to be worked around to put a sequent
    calculus on top of an imported corpus, and it is a wart rather than a rule.

    `layered_spec` claims a **line part**'s name into the same namespace as
    productions and line types, so a child adding a line type cannot call its
    citation field `reference` — which is what every Hilbert layer here calls
    theirs and, more to the point, what
    `metamath.importer.build_spec` calls the imported one's. Within a *single*
    spec two line types may share a part name freely: that builds, and both line
    types work. `test_a_layer_may_not_reuse_its_parent_s_line_part_name` asserts
    both halves, which is what makes the inconsistency the finding rather than
    the refusal.

    The check is doing something real, but not this. A shape resolves `<name>`
    against sorts *and* parts, so a part sharing a **production**'s name is
    genuinely ambiguous and must be refused. Two parts of two different line
    types are not: they are resolved within their own shape, which is why the
    flat case works. The narrower rule — a part may not collide with a
    production or sort, but parts do not collide with each other — is what the
    build already implements and what the chain check should match.

    Not changed here, deliberately. `layered_spec` is on the path of every build
    in the codebase, the workaround is a naming convention (`citation`), and the
    change belongs with a phase that has a reason to touch that function rather
    than bolted onto one that merely tripped over it. Recorded so the convention
    is not mistaken for a preference.

    The neighbouring constraint is a genuine rule and needs no fix: a layer may
    not reuse a **production name** either, so a sequent layer over `set.mm` must
    avoid 1,441 labels. `sequent_core` prefixes its own (`sequent-cons`,
    `sequent-turnstile`), which is the discipline any layer over a corpus wants.

---

## 10. What this does not do

- It does not check **conservativity**, and does not infer it (§1.2).
- It does not make transfer **downward**. A ZFC proof of a propositional
  statement does not become a PC theorem.
- It does not add an **elaboration gap** or admissible-rule machinery (§6.4).
- It does not change the **kernel**. Every construction here is a system, an
  edge, or a query; the trusted core learns nothing about relationships between
  systems, which is the property that keeps "Edifyce checks any formal system"
  true.
- It does not introduce **cross-system proof-to-proof references**.
  `proof_references` stays same-system; the library edge is the transfer
  mechanism, and a proof that wants a foreign lemma cites it as a theorem.
