# Design: scope-aware binding in a definition's defining form

**Status:** built. **Scope:** the *representation* — how a defining form stores
its binders. This is the prerequisite the "scope-aware definitional steps" item
in [binding-slots-design.md](binding-slots-design.md) needs, and **not** that item
itself: an open abbreviation like `S ≝ (a ∈ b)` is still refused, exactly as
before.

> Written because that item says a change here "wants its own soundness
> argument". What follows is that argument: what widened, what did not, and why
> each is safe.

## What was wrong

A binder was stored as one indexed `Bound` per *name*, and
`kernel.terms.bind` keys on the surface string — so every leaf spelled `z`
became the same node. That is right only when every occurrence of `z` happens to
be in the binder's scope and every binder slot holding `z` has the same sort.
Where it isn't, the representation silently loses the difference:

- **`(∀z.(z ∈ x) → (z ∈ y))`** — the right-hand `z` is free, but was abstracted
  along with the bound one. Renaming the binder renamed the free variable too.
- **`(∃z.(z ⋴ y) → ∀z.(z ∈ x))`** with `setvar ::= [a-z]` inside
  `classvar ::= [a-zA-Z]` — one `Bound` was stored, carrying whichever sort came
  first, and the other slot received it. Renaming to `Q` gave `∀Q.(Q ∈ a)`, a
  term the grammar cannot parse.

Both were found in review, and both were patched with *guards* — refuse the
inference, refuse the definition — because the representation could not express
the distinction. This replaces the guards with the distinction.

## What it does

`kernel.definitions.bind_scoped` walks the parsed defining form carrying a
lexical environment, using the grammar's `Constructor.scopes_over`. At a node
with a binder slot holding a name, it allocates a `Bound` and makes it visible
in that slot and in the slots the binder was declared to scope over — and
nowhere else. So there is **one binder per binding occurrence**, not per name,
and an occurrence outside every scope stays the ground leaf it is.

`FreshBinder` gains two fields. `enclosing` lists, by index, the binders whose
scope contains this one; `scoped` says whether the binder was placed by scope at
all.

One consequence reaches the `unfold` API. Several binders may now share a
spelling, so `names` — which keyed renames by the binder's name — cannot always
say which one is meant, and where the two have different sorts it cannot succeed
at all (no single leaf is of both). `names` therefore accepts a binder's reserved
index label as well, and prefers it; naming by spelling still works and still
renames every binder of that spelling together, which is what a caller asking for
one consistent rename means. The path a proof actually takes,
`check_definitional_step`, is unaffected: it recovers each binder's name from the
target rather than being told.

## What is unchanged

**A declared `fresh` clause still binds by name, across the whole form.** This
is not a concession — it is the only reading available on a grammar that declares
no binding slots, which is every grammar written before `scopes_over` existed. A
declared binder keeps `scoped=False`, keeps the blanket pairwise freshness rule,
and produces bit-identical terms. Nothing about a stored system changes.

The consequence is that the two defects above are still *possible* through a
declared clause, and the check that refuses a declared sort the grammar
contradicts is retained for that reason. Only the inferred path gains the
faithful representation, and only a grammar that declares binding slots has one.

## What widened, and why each is sound

The checker accepts three things it did not before. Each is a term it was wrong
to reject.

### 1. Independent binders may be named apart

`(∀z.P(z) → ∀z.Q(z))` was one binder, so a step had to spell both occurrences
the same. It is now two, and `(∀w.P(w) → ∀v.Q(v))` checks.

*Sound because* the two scopes are disjoint, so the two terms are alpha-variants:
renaming a binder within its own scope, where the new name is fresh for that
scope, preserves meaning. That is the same justification the single-binder
renaming already rested on, applied per binder instead of per name.

### 2. Two binder slots of different sorts may share a name

Previously refused outright (there was no way to store it). Now each occurrence
carries its own slot's declared sort.

*Sound because* it is strictly more faithful: the resulting term is well-sorted
by construction, where the old representation produced an ill-sorted one and the
guard existed only to stop it being built. Nothing is accepted that was
previously *correctly* rejected — the rejection was of a term the engine could
not represent, not of a term that was wrong.

### 3. Binders in disjoint scopes need not differ

The freshness proviso used to require every pair of binders to be spelled
differently. It now requires that only of a binder and the binders whose scope
contains it.

*Sound because* capture requires an occurrence of one variable to fall inside
the other's scope. If neither binder encloses the other, their scopes are
disjoint — see the invariant below — so no occurrence of either lies in the
other's scope and spelling them alike captures nothing.

Note this is also *required*, not merely permitted: `(∀z.P → ∀z.Q)` is one
binder under the old representation and two under the new one, so a blanket
pairwise rule would newly reject a term that has always checked. Scope-sensitivity
is what keeps this change from being a regression.

**The invariant it rests on.** `enclosing` records the binders whose scope
contains this binder's *position*, **plus every binder opened at the same node**.
If `B ∉ A.enclosing` and `A ∉ B.enclosing`, their scopes are disjoint: a binder's
scope lies entirely within its own node's children, so if `B`'s position is
outside `A`'s scope then `B`'s node — and therefore all of `B`'s scope — is
outside `A`'s scope too.

The sibling clause is not decoration; without it the invariant is false. A
production may declare *two* binder slots over one body — a comprehension
`⟪u,v⟫.phi` — and then neither binder is inside the other while both scope over
the same slot. Nesting alone would call them disjoint and let a step spell both
`q`, merging two binders into one. Siblings are therefore treated as mutually
enclosing, blanket rather than restricted to those whose targets actually
overlap: two binders on one production are meant to be distinct, and refusing a
hypothetical grammar that wanted otherwise is the safe direction. This is open
question 1 of [binding-slots-design.md](binding-slots-design.md) — "a
comprehension with two binders would settle it" — settled conservatively.

Sibling slots raise a second question the nesting rule cannot answer: what if the
defining form puts *the same leaf* in both, as `⟪s,s⟫.P(s)`? They are
simultaneous rather than nested, so neither shadows the other and the `s` in `P`
belongs to neither in particular. Binding it to whichever slot the grammar lists
second would make the form's meaning depend on declaration order — reversing an
otherwise identical `scopes_over` flips which renaming the checker accepts. That
form is refused.

## What did not widen

**Capture against a parameter is still refused, for every binder.** A parameter's
substitution is whatever the redex supplied, and the unfold places it wherever
that parameter occurs; a binder spelled the same would capture it. Every binder
is still required to be disjoint from every parameter — deliberately blanket,
rather than restricted to the parameters that actually occur in that binder's
scope, because the blanket rule is the conservative one and is what has always
been applied.

**Shadowing is still refused.** `∀z.∀z.P` nests, so the two must differ.

**Open abbreviations are still refused.** `S ≝ (a ∈ b)` introduces `a` and `b`
from nowhere; `introduced_leaves` reports them and the build rejects the
definition. Admitting those is the separate item, and it is the one that would
genuinely widen what a *proof* may do rather than what a definition may be. This
change is a prerequisite for it and does not attempt it.

**Nothing is accepted where the grammar declares no binding slots.** `bind_scoped`
allocates only at a slot listed in `scopes_over`, so on such a grammar it is the
identity and allocates nothing.

## Where the argument is checked

`tests/test_binding_slots.py` pins each claim: that a disjoint-scope pair may
share a name and a nested pair may not; that a binder colliding with an argument
is still refused; that two sorts give two binders and a step may name them apart;
that an out-of-scope occurrence stays free and is reported as conjured; and that
a declared clause still binds by name and still produces the same term as before.
