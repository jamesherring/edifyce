# Design: binding slots on productions

**Status:** partly built — steps 1, 2 and 4 below have shipped (the declaration,
its storage/API round-trip, and `fresh` inference). Steps 3, 5 and 6 are open.
**Prerequisite work:** merged (#115, #117, #118, #119, and the kernel-takes-terms
change)

> Written as the spec for the last open item in AGENTS.md's *Constants vs
> variables of the object language* section. Nothing here is a soundness fix —
> the engine is sound without it. It is a **capability** change, and the reason
> to want it is that three separate things the engine currently cannot do all
> reduce to the same missing declaration.

## The missing declaration

A production declares its slots and their sorts:

```
formula ::= ∀x phi          bindings: x → setvar, phi → formula
```

Nothing says that `x` **binds**, or that it scopes over `phi`. The engine knows
`∀x phi` has two slots of those sorts and no more. Metamath has none of this
either, and does not miss it — its `$d` provisos carry the weight instead — so
this is a deliberate gap, not an oversight.

## What it would buy

Three open problems, one cause.

### 1. Validating `denotes_constant`

`Production.denotes_constant` is Metamath's `$c` vs `$v`, and like Metamath's it
is **declared, not inferred** — no property of a production's shape settles it,
since a one-token atom is a constant in `formula ::= ⊥` and a variable in
`setvar ::= a | b | c`. The declaration is trusted, and the unsafe direction
(marking a bindable token constant) is a positive act by the author.

With binding slots, one class of mistake becomes checkable: **a token whose sort
appears in some production's binder slot is not a constant**, whatever the author
ticked. That is exactly the hole `test_an_atom_constant_in_the_variable_sort_is_not_excused`
documents — `setvar ::= [A-Z] | c` with `c` marked constant admits
`T ≝ (c ∈ c)`, and `∀c.T ⟶ ∀c.(c ∈ c)` captures. Today the build refuses it for
a different reason (the leaf is reported as conjured); with binding slots the
engine could reject the *declaration* and say why.

It does not become fully inferable — a sort that no binder mentions is still the
author's call — so this narrows the trusted surface rather than removing it.

### 2. Inferring a definition's `fresh` clause — **built**

A definition used to declare its defining form's binders by hand:

```
Define (x ⊆ y) as ∀z.((z ∈ x) → (z ∈ y))   fresh: z → setvar
```

`fresh` is exactly "which leaves of the defining form sit in a binder slot", and
with binding slots that is derivable from the parsed term. The clause is now
optional: `formal_system.definitions._resolve_binders` reads the binders off the
parsed defining form, and an inferred clause produces the same `Definition` —
same `fresh` tuple, same interned schemas — as the hand-written one.

This is the highest-value item for import work: a Metamath `$a`/`$p` carries no
`fresh` clause, so an importer would otherwise reconstruct one per definition.

**Inference only ever adds.** A binder the author declared and the grammar does
not show may still be one — the production it sits in need not have declared its
slots — so silence in the grammar is never read as denial. The one contradiction
worth refusing is a shared name at a *different sort*: the grammar puts the leaf
in a slot of one sort and the author declared another, and both cannot be true.
That is narrower than "checked when given" as first written here, and it is the
only direction that is actually decidable while the declaration is optional.

Three things are deliberately not binders. A slot holding a `Var` is a
*parameter* the defined form supplies, so an unfold substitutes it rather than
conjuring it; a production with no `scopes_over` contributes nothing, which is
what keeps every system authored before this field behaving as it did; and a name
the defining form *also* uses outside the binder's declared scope is left alone.

That last one is why inference reads the "over what" half of the declaration and
not just the binder slot's label. `bind` keys on the surface string, so
abstracting a binder rewrites the name everywhere it is spelled: for
`(∀z.(z ∈ x) → (z ∈ y))` the free `z` on the right would be renamed along with
the bound one, and the definition would mean something its author did not write.
Withholding the inference leaves `z` a name the form conjures, which
`introduced_leaves` refuses with the message that names the remedy — exactly what
happened before binding slots existed. A hand-written `fresh` clause still
reaches outside the scope: it is the author's positive act, and narrowing it
would break systems that predate the field.

**One name cannot bind at two sorts.** A binder is stored as a single indexed
`Bound` carrying one sort, and `bind` keys on the surface string, so every
occurrence of the name becomes that node. Where a grammar has two binders over
overlapping sorts — `setvar ::= [a-z]` inside `classvar ::= [a-zA-Z]`, each with
its own quantifier — `(∃z.(z ⋴ y) → ∀z.(z ∈ x))` would put a `classvar` binder
into `∀`'s `setvar` slot; renaming it to `Q` then gives `∀Q.(Q ∈ a)`, a term the
grammar cannot parse. Refused at build. Not resolved, because a `fresh` clause
maps a name to *one* sort and so cannot express it either: two binders of
different sorts are two binders, and the defining form has to spell them apart.
Representing the occurrences separately instead would need a scope-aware `bind`,
which belongs with item 3 rather than here.

This check is inside the inference walk, which is silent for a production with no
`scopes_over` — so it cannot fire for a system authored before this field, and it
covers a declared clause over such a grammar for free.

### 3. Scope-aware definitional steps

The kernel's admissibility check has two halves; only the **capture** half is
implemented (`introduced_leaves`, `unbound_parameters`). A defining form may not
mention a leaf the defined form does not supply, because an unfold would conjure
it and a binder of the same name would silently rebind it.

That rule is deliberately blunt: it refuses *every* open abbreviation, including
ones that are harmless. `S ≝ (a ∈ b)` is refused outright, when what is actually
needed is "refused **where** a binder for `a` or `b` is in scope". Deciding that
needs to know what scopes over what — i.e. binding slots — at the position the
step is taken.

This is the largest of the three and the one to do last, if at all. It changes
what proofs are accepted, so it wants its own soundness argument.

## Shape of the change

### Engine — **built**

`Production.bindings` stays `list[tuple[str, str]]` — `(slot, sort)` — and the
binding structure sits beside it as a parallel field, rather than replacing the
tuples with a `BindingSlot` dataclass as first sketched here:

```python
scopes_over: dict[str, list[str]] = field(default_factory=dict)
```

A parallel field because `bindings` means two different things in this codebase:
a production's *slots*, and a rule's or definition's *metavariables*. Only the
first can bind, so widening the shared tuple would have put the field on three
records that cannot use it.

A production is a binder iff some slot has a non-empty entry. Everything the
declaration can get wrong is decidable from the template, so
`declarative._binding_scopes` settles it at build: both sides must name slots the
template actually has, nothing scopes over itself, and an atomic production
(which has no slots at all) may not declare any.

This reaches `kernel.constructors.Constructor.scopes_over` as projected data (a
slot label → the labels it scopes over), read in `_build` rather than `_link`
because a binder slot names *siblings*, so nothing about it reaches back into the
grammar. The pattern/kernel boundary is unchanged: `constructors` reads the
production, nothing downstream holds one.

### Storage — **built**

`production_binding_scopes`: a join table whose two ends are both
`production_bindings` rows, so a binder points at the sibling *row* it scopes
over rather than at its name. The text column sketched here would have been the
one free-text grammar reference in a schema whose whole premise is that renaming
a symbol updates one row. A foreign key cannot express the *same-production*
half of the constraint, which is why the engine check above still matters.

### API — **built**

`ProductionBinding` extends `Binding` with `scopes_over: list[str]`, and only the
production payloads use it. `app/routers/system_parts.py` rejects a scope naming
a non-sibling slot (400), mirroring how it validates a binding's sort;
`app/db/systems_mapping.py` round-trips it.

### Frontend — **partly built**

The client type carries the field and the production editor round-trips it, so an
edit through the UI cannot silently drop a declared binding slot. Per-slot "binds
over" *selection* is still to do — the part that can safely lag, since the field
is optional and defaults to empty.

Round-tripping a field with no control to edit it has one sharp edge, and the
editor handles it: renaming or deleting a slot another slot scopes over would
send a target that no longer exists, which the API rejects — dead-ending an edit
the user cannot repair from that form. A stale target is dropped on save instead.
Adding the control removes the need for that, and is the reason to add it.

## Open questions

1. **Does `scopes_over` need to be ordered or transitive?** For `∀x phi` it is a
   single slot. A production like a set-builder `{x | phi}` is the same shape.
   Nothing obvious in the target grammars needs more, but a comprehension with
   two binders would settle it.
2. **What happens to an existing system?** Nothing — the field is optional and
   empty means "no binding information", which is exactly today's behaviour. All
   three uses above are opt-in per system, so this cannot regress a stored
   system.
3. **Should `fresh` inference be silent or explicit?** Currently silent: an
   omitted clause is filled from the grammar, and the built `Definition.fresh`
   carries the answer. **Still open** — the definitions API returns the *declared*
   clause (rows), not the inferred one, which needs the built system. Reporting it
   back is the remaining half of this question.
4. **Item 3 (scope-aware steps) needs a soundness argument** before any code. It
   widens what the checker accepts, which is the one direction that can be wrong.

## Recommended sequencing

1. ~~Engine field + build-time validation of `scopes_over`~~ — **done**.
2. ~~Storage + API round-trip, with a migration~~ — **done**.
3. Use it for `denotes_constant` validation — narrow, safe, and immediately
   catches the documented hole.
4. ~~Use it to infer/check `fresh`~~ — **done**, in the add-only form described
   above.
5. Frontend editing (the per-slot "binds over" control) + reporting the inferred
   clause back, per open question 3.
6. Scope-aware definitional steps — separately, with its own design note.

Step 4 shipped ahead of 3 because it is the one with a caller waiting: a Metamath
import reconstructs a `fresh` clause per definition without it. Each remaining
step is still independently shippable.
