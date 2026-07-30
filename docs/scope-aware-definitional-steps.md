# Design: scope-aware definitional steps

**Status:** analysed and scoped, **not built**, and **held** — the work is
decomposed under *Scope* below, and no caller wants the capability. This note is
the soundness argument [binding-slots-design.md](binding-slots-design.md) §3 asks
for before any code. Its conclusion is that scope-awareness at the redex is
*necessary but not sufficient*, that the missing piece is a different change, and
that the change is not currently worth making.

## The proposal

`build_kernel_definition` refuses any defining form that names a leaf the defined
form does not supply (`introduced_leaves`). So an **open abbreviation** —

```
S ≝ (a ∈ b)
```

— is refused outright. The rule is deliberately blunt: what is actually wanted is
"refused **where** a binder for `a` or `b` is in scope", which needs to know what
scopes over what at the position the step is taken.

With binding slots that position information now exists. `_rewrites_once`
descends through the term to find the redex, so it could carry the binders
enclosing it and refuse the step exactly where one of them binds an introduced
name. That is the whole of the proposal, and it is straightforward.

## Why it is not enough

The argument above accounts for **capture**: an introduced `a` falling under a
binder for `a`. It does not account for what the abbreviation does to every
*other* reader of the term's variables.

`Occurs` is the structural predicate the proviso vocabulary is built from, and
what an eigenvariable-style freshness condition ultimately asks. Given a system
where `S ≝ (a ∈ b)` is admissible — today that needs `a` and `b` declared
constants, which is the trusted direction — it answers:

```
Occurs('x', 'phi')  with phi := S          ->  False
Occurs('x', 'phi')  with phi := (a ∈ b)    ->  True
```

The two terms are definitionally equal. A proviso saying "`a` does not occur in
`phi`" is therefore **satisfied by the notation and violated by its meaning**. A
proof can establish the proviso against `S`, then unfold `S` and carry on with a
term the proviso was never true of.

Capture at the redex is one way an open abbreviation goes wrong. This is another,
and it is not positional: it does not matter *where* the step is taken, because
the proviso was checked somewhere else entirely — possibly on a different line,
under a rule that never sees the definition.

Note what this is *not*. It is not an argument against the existing trusted path:
if `a` really is a constant of the object language, no rule should be quantifying
over it and no freshness proviso is about it, so the declaration being true makes
the divergence harmless. The hazard appears exactly when the introduced leaf is a
genuine **variable** — which is what admitting open abbreviations would mean.

## The prerequisite

For an open abbreviation to be admissible, a defined form's leaf has to carry the
object-language variables its definition mentions, so that `Occurs`,
`DisjointLeaves` and the eigenvariable machinery see through the notation instead
of stopping at the leaf.

**Not by way of `free_vars`.** That was the first draft of this note and it was
wrong. `Term.free_vars` is the inventory of *schema metavariables* — what a match
has yet to bind — and a ground term like `(a ∈ b)` correctly reports none. Three
callers depend on exactly that reading, and each would break in a different way:

| caller | what it does with `free_vars` | breakage |
|---|---|---|
| `rules._term_for_occurrence` | renames every entry to `name\x00occurrence` | ground notation gets renamed |
| `side_conditions._resolve` | raises if any entry remains after substitution | a proviso naming `S` is rejected as malformed |
| `definitions.unbound_parameters` | `lower` minus `higher` | `a`, `b` reported as introduced parameters |

The two notions are genuinely distinct and the conflation was the error: a
*schema metavariable* is something a match may still bind, an *object-language
variable* is something a binder may capture. A definition's parameters are the
first; the leaves an open abbreviation hides are the second.

So the prerequisite is **separate metadata** — a defined form's constructor
recording the object-language leaves of its defining form — plus `Occurs` and
`DisjointLeaves` consulting it. That is a change to what a *notation* carries:
semantic information from the definition it abbreviates. It cuts across the
layering this arc has spent several changes establishing — the kernel reads no
strings, a production projects to a `Constructor`, and a `Constructor` is
structural — so it is a design question in its own right, not an implementation
detail of this one.

**So this item stays open, now with a named blocker rather than a vague warning.**
The position-tracking half is ready whenever the transparency half is settled.

## What was checked

`tests/test_definitions.py` pins the divergence as a characterisation test, so
the boundary is visible in the suite rather than only here. It asserts today's
behaviour — `Occurs` disagreeing across a definitional equality — which is sound
under the current trust model and would not be under the proposed one. If a later
change makes notation transparent to `Occurs`, that test is the one that should
fail and be rewritten.

## What this leaves in the binding-slots roadmap

Step 6's first half — position tracking through `_rewrites_once` — is designed and
cheap. Its second half is the transparency question above. Nothing else in
[binding-slots-design.md](binding-slots-design.md) depends on either, so the rest
of that roadmap is unaffected.

---

# Scope

What follows sizes the work rather than doing it. Read the sections above first:
they say *what* is missing, this says what building it would cost, in what order,
and what has to be decided before any of it.

## The acceptance criterion

One sentence, because everything below is in service of it:

> A term containing defined notation must answer every **leaf-occurrence**
> predicate exactly as its full unfolding would, and a definitional step must be
> refused at any position where unfolding it would put an introduced leaf under a
> binder for that leaf.

The first clause is the transparency half, the second the positional half. The
criterion is testable directly, and that property test is the deliverable that
matters most — see *What I could not settle*.

## The work, in shippable pieces

Ordered so that **nothing changes observable behaviour until the last one**. That
is the point of the ordering: the risky act is a single relaxation at the end,
sitting on three pieces that can each land, be reviewed and be reverted alone.

### 1. Position tracking through `_rewrites_once` — small

`_rewrites_once` already descends child by child to find the redex. It would carry
a set of the binders enclosing the current position, extended at each `Node` from
`Constructor.scopes_over`: for a binder slot whose targets include the child being
descended into, the concrete leaf sitting in that slot is in scope below.

The walk is the one `bind_scoped` already performs, against concrete leaves rather
than `Bound` nodes — a proof line spells its binders out, the abstraction exists
only inside `Definition.lower`. So this is a second reader of `scopes_over`,
written against the same shape.

Alone it computes a set nothing consults. Land it with a test that asserts the set,
not a behaviour.

### 2. A hidden-leaf inventory per defined form — small, with one wrinkle

What a notation conceals is the **free object-language leaves of its defining
form**: `S ≝ (a ∈ b)` conceals `a` and `b`. Constructor-level, not node-level,
because it is fixed per definition — a defined form's *arguments* are real children
and every structural walk already descends into them. Only the conjured leaves are
invisible.

Three properties, each verified against the engine rather than assumed:

- **Transitive.** `S ≝ (a ∈ b)` then `T ≝ (S → S)` builds today, and
  `introduced_leaves` reports `T` hiding `S` and `S` hiding `a`, `b`. So the
  inventory is a fixpoint over the definitions, not a per-definition read.
- **Terminating**, because the "is defined using" relation is acyclic — which is
  exactly what [the conservativity check](binding-slots-design.md) established. The
  fixpoint is well-defined *because* that shipped; before it, a cycle would have
  made this diverge.
- **Unioned over shared defined forms.** Two definitions may attach to one form,
  so the form conceals what either of them conceals.

The wrinkle is *free*: a binder declared `fresh` is stored as a `Bound` and must
not count, since a bound variable is not one a proviso is about. `_ground_leaves`
already excludes `Bound`, so the existing traversal is the right one — but this is
a **third** notion of "the variables of a term", beside `Term.free_vars` (schema
metavariables) and `side_conditions._leaves` (sort-restricted surface strings).
Conflating the first two is the error this note already records. Name the third
carefully or it will be conflated in turn.

Derived at build from the definitions, so **nothing persists and no migration**.

### 3. Transparency in the predicates — small, and the one to argue over

`_occurs` and `_leaves` consult the inventory when they reach a node whose
constructor has one. Both already walk terms; both gain a branch.

Which predicates change is a **decision, not a consequence** — see below.

### 4. Relax `introduced_leaves` — the behaviour change

`build_kernel_definition` stops refusing an open abbreviation outright, and
`_rewrites_once` refuses the *step* where piece 1 says a binder is in scope. This
is the only piece that widens what the checker accepts, and it is one condition
moved from build time to step time.

### 5. Rewrite the characterisation test, and say so

`test_a_defined_form_is_opaque_to_a_structural_proviso` asserts today's divergence
and was written to fail here. Its replacement asserts the criterion above.

## Decisions to take before any code

1. **Which predicates see through.** Not all of them, and this is the subtlety the
   analysis above understates. `Occurs` and `DisjointLeaves` must — they are what
   freshness is built from. `Equal` must **not**: it is syntactic identity, and
   making it see through would make every definitional step invisible to the very
   checker that verifies it. That leaves `IsAtom`, which today answers True for a
   nullary notation `S` because it is a childless node, though `S` means a compound.
   A rule using `IsAtom` without a sort to mean "this slot is a variable" would be
   satisfied by notation that is not one. Decide it deliberately; do not let it
   fall out.
2. **Whether constants stay in the inventory.** The criterion says "as its full
   unfolding would", which puts `⊥` in — an unrestricted `Occurs` on the unfolding
   finds it. That is the consistent answer and it changes results for provisos
   written without a sort restriction. The alternative (hide only bindable leaves)
   is narrower and cheaper to adopt, and breaks the one-sentence criterion.
3. **Where the inventory hangs.** `Constructor` is the natural home and the
   uncomfortable one: it is *structural* data projected from a production, and this
   is *semantic* data from a definition the production knows nothing about. The
   alternative is a side table on the system, consulted by the predicates — which
   means threading it through `SideCondition.check`, whose signature is
   `(binding, context)` today. `Context` may already be the carrier. Settle this
   first; it decides how invasive the rest is.

## What I could not settle

I found one divergence the original analysis missed (`IsAtom`), by enumerating the
vocabulary rather than by reasoning about it. That is weak evidence that the
enumeration is now complete and no evidence at all that the *criterion* is.

The way to find the rest is the property test, and it should be written before the
implementation: generate a term containing defined notation, unfold it fully, and
assert every predicate in the closed vocabulary agrees across the pair — with
`Equal` and the matcher explicitly excluded and the exclusion argued. Anything that
disagrees is either a bug or a decision, and it is better to meet them all at once
than one per review round.

## Whether to do it at all

**No caller has been identified, and one was expected.** The obvious consumer is the
Metamath import, and it does not want this. `metamath/definitions.py` refuses a
`$a` whose defining side introduces a **metavariable** the defined side does not
supply, and its own comment says that refusal "lifts the moment the importer can
declare binding slots". The set.mm breakdown in
[metamath-import-roadmap.md](metamath-import-roadmap.md) bears it out: of the 310
non-binding refusals, 119 are a root that is not a declared equivalence, 9 a defined
side already in use, 2 a bare metavariable. None is an open abbreviation over free
object-language leaves.

So the capability this unlocks — admitting `S ≝ (a ∈ b)` where `a` and `b` are
genuine variables — is wanted by nothing currently in the tree. Against that: the
change reaches into the trusted core, adds a third notion of "the variables of a
term" next to two that were conflated once already, and widens what the proof
checker accepts, which is the one direction that can be wrong.

The recommendation is therefore to **hold it** until something asks for it, and to
treat that ask as part of the specification when it comes — a caller would say
which predicates it needs transparent, and decisions 1 and 2 above would stop being
guesses. Pieces 1 and 2 are independently harmless and could land early if a reason
appears to want the position set or the inventory for something else; neither is
worth doing on its own account.
