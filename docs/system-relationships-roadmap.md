# Relationships between formal systems: analysis and roadmap

**Status:** **R1 and R2 delivered**; the rest is design. `formal_systems.inherits_from_id`
used to be validated on write and read by nothing — `app/routers/systems.py` said
so in as many words ("inheritance is not resolved yet … deferred to the
inheritance phase"). It now means what §5.1 says it means: a child's effective
system is its ancestors' parts followed by its own, and every path that builds a
system builds the chain, and §5.2 as well: a citation resolves against the
system's own library and then its ancestors'. See §8's R1/R2 for what landed and
§9.9–9.14 for what they turned up.

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
proof's conclusion and sets `proofs.theorem_id`. Guards: the proof must be valid,
warning-free (`_is_usable_lemma`'s test) and owned; re-promoting after an edit
replaces the row; invalidating the proof retires it.

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

The plan says where a theorem *should* go; §3.3 says how to check that it does.

**A prediction that must be checked before the milestone is set.** On the
author's reading of `set.mm`'s ordering, propositional calculus runs to roughly
1,500 theorems — so **the first 1,000 are likely to land wholly inside the PC
layer**. If so, that slice exercises the *partition* and exercises no *transfer*
whatsoever, and it proves nothing about (a) or (b). Step D1 is therefore to
measure, and the milestone slice is "the first N theorems such that all three
layers are populated" — the first 1,000 kept as the fast regression, the wider
slice as the one that demonstrates the feature. Guessing N here would be
guessing; the walk already reports positions and the answer is one run away.

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

#### R3 — promote a proved proof into its library

**Delivers (a)/(b)** for work a person proves. Ground statements first.

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

#### R3a — schematic promotion

**Delivers** `⊢ (φ → φ)` proved once and cited at every instance.

**Tests and verification** — same module.

- *Valid:* the author nominates `φ : wff`; the entry is cited at three distinct
  instances, one of them containing a binder.
- *Invalid:* nominating a leaf at a sort the grammar does not declare;
  nominating a leaf that the proof's own axioms fixed as a constant.
- **Bound variables:** a schematic promotion over `x : setvar` where the proof
  used `x` as an eigenvariable must carry the corresponding proviso into the
  entry, and a citation violating it must be rejected. Without this, schematic
  promotion is the obvious hole through which an eigenvariable condition escapes.

#### R4 — `system_relations`

**Delivers** multiple parents, sort renames, translations.

**Tests and verification** — `tests/test_system_relations.py`.

- *Valid:* an `interpretation` edge with a sort **rename** (`prop → wff`)
  transfers a theorem; a system with two parents resolves labels from both.
- *Invalid:* transfer across a `draft` edge; transfer across an edge with an
  undischarged obligation; a sort map that **narrows** (the target's constructor
  admits less than the source's) → refused, and the refusal is asserted to come
  from `Constructor.admits` rather than a name comparison (§3.2).
- *Pinned:* an `extension` edge auto-discharges from the spine and never asks an
  author for an obligation; discharging the last obligation flips `status` and
  is what makes a previously-failing citation succeed (the same proof, re-run).

---

### Track S — sequents

#### S1 — a sequent FOL as a system

**Delivers (c)**, standalone. No engine change expected — if one *is* needed,
that is the finding.

**Tests and verification** — `tests/sequent_system.py`,
`tests/test_sequent_calculus.py`.

*Valid, and must be accepted:*
- `⊢ (A → A)` by identity + →R.
- The deduction theorem both ways on a three-assumption context.
- Weakening, exchange, contraction and cut, each in a proof that needs it.
- **∀R with an eigenvariable:** `Γ ⊢ φ[y/x]` ⟹ `Γ ⊢ ∀x φ` accepted when `Γ` is
  empty, and when `Γ` is `(z ∈ z)` — a non-empty context not mentioning `y`.

*Invalid, and must be refused:*
- **∀R when the eigenvariable is not fresh:** the same proof with
  `Γ = (y ∈ y)` → rejected. This is the phase's central test: it is only
  expressible because the context is a term the kernel's `occurs` can see into
  (§3.4), and a string-backed context would pass it by accident or fail it by
  accident.
- **→R does not reach past the rightmost assumption:** from `Γ, A, B ⊢ C`,
  concluding `Γ, A ⊢ (B → C)` is accepted and `Γ, B ⊢ (A → C)` is rejected —
  exchange must be cited.
- **∀L instantiated with a term that would capture** → rejected.
- Contraction applied to two assumptions that are *not* equal → rejected.

*Pinned properties:*
- A context is matched structurally: two contexts equal up to rendering but
  differing in nesting are not interchangeable, asserted on the term.
- `benchmarks/bench_matching` baseline taken **before** the sequent grammar is
  added and compared after (feeds S3).

#### S2 — the interpretation edge Hilbert → sequent

**Delivers** `set.mm`'s library citable inside sequent proofs. Requires R4.

**Tests and verification** — same module.

- *Valid:* each of `ax-1`, `ax-2`, `ax-3`, `ax-mp`, `ax-gen` discharged by an
  actual sequent proof; then a Hilbert theorem cited inside a sequent proof,
  wrapped as `Γ ⊢ φ`, with `Γ` instantiated non-trivially.
- *Invalid:* the same citation with one obligation withdrawn → refused. Run as
  a *pair* with the valid case, so the test shows the obligation is what carries
  the weight.
- **Bound variables:** transfer `ax-5` (with its `$d`) and cite the wrapped form
  where `Γ` mentions the constrained variable → rejected. This is the case where
  the template introduces a metavariable (`Γ`) the source theorem never had, and
  it is where a naive wrap would lose the proviso.
- *Pinned:* the wrap is a term construction — the transferred schema's term has
  the sequent constructor at its root and the source theorem's term as a subterm,
  asserted structurally.

#### S3 — benchmark the recursive context grammar

**Delivers** evidence for or against S4. Left-nested list parsing is the risk.

**Tests and verification:** `benchmarks/bench_matching --compare` against the S1
baseline, plus a stress case in `tests/test_matching_stress.py` — a
twelve-assumption context, timed, so a regression is a test failure rather than a
slow suite.

#### S4 — *conditional on S3* — an AC matcher for contexts

**Delivers** sequents without structural bookkeeping.

**Tests and verification:** every S1 test re-run with exchange and contraction
*removed from the proofs* — they must still pass, which is exactly the claim.
Plus: contraction of unequal assumptions still rejected; a matcher stress case
with a context large enough that a naive AC search would not terminate.

---

### Track D — the importer

#### D1 — keep the outline; measure

**Tests and verification** — `tests/test_metamath_layers.py` (parser half) plus
a reported measurement.

- *Valid:* section headers parse out of a fixture `.mm` with nested part /
  section / subsection markers, and every assertion gets a section path.
- *Invalid:* a malformed header does not silently swallow the following
  statements; a `$( … $)` that only *looks* like a header stays a comment.
- *Pinned:* the outline is additive — every existing metamath test passes
  unchanged, and an import naming no layer plan produces byte-identical results
  to today's.
- *Measured and reported:* where the first 1,000 theorems land (§7.1), and the
  cross-layer term-sharing figure that decides §7.3's first bullet.

#### D2/D3 — the layer plan and one spec per layer

- *Valid:* the three specs build, and each layer's spec contains only the
  productions its sections declared.
- *Invalid:* a plan assigning a production to a layer *after* a theorem that
  uses it → refused with the theorem named.
- *Pinned:* `setmm.LAYERS` empty ⇒ exactly today's single-system behaviour, which
  is the same discipline `BINDERS` follows and the same test shape
  (`test_the_set_mm_table_is_well_formed`).

#### D4/D5 — store per layer; the invariants

- *Valid:* the layered import of the measured slice produces the **same theorem
  count and the same per-theorem verdicts** as the unlayered import, and the
  emitted proof sources are **byte-identical**. This is the phase's headline
  assertion and it is a strict equality, not a summary comparison.
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
  └──▶ R4 ──▶ S2
              ▲
       S1 ────┘──▶ S3 ──▶ S4
```

S1 and D1 depend on nothing and can start immediately.

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

The six below are **findings from R1 and R2**, kept here because each is a live
constraint on the phases after it rather than a closed question.

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
