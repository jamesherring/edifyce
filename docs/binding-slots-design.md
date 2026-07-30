# Design: binding slots on productions

**Status:** built but for the last item — steps 1–5 below have shipped (the
declaration, its storage/API round-trip, `denotes_constant` validation, `fresh`
inference, and the editor), and step 6's *representation* prerequisite has too —
see [scope-aware-binding.md](scope-aware-binding.md). Only step 6 is open, and it
is blocked.
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

### 1. Validating `denotes_constant` — **built**

`Production.denotes_constant` is Metamath's `$c` vs `$v`, and like Metamath's it
is **declared, not inferred** — no property of a production's shape settles it,
since a one-token atom is a constant in `formula ::= ⊥` and a variable in
`setvar ::= a | b | c`. The declaration is trusted, and the unsafe direction
(marking a bindable token constant) is a positive act by the author.

With binding slots, one class of mistake becomes checkable: **a token whose sort
appears in some production's binder slot is not a constant**, whatever the author
ticked. That is exactly the hole `test_an_atom_constant_in_the_variable_sort_is_not_excused`
documents — `setvar ::= [A-Z] | c` with `c` marked constant admits
`T ≝ (c ∈ c)`, and `∀c.T ⟶ ∀c.(c ∈ c)` captures. The build used to refuse it for
a different reason (the leaf is reported as conjured); it now rejects the
*declaration* and says which binder settles it
(`declarative._validate_constant_declarations`).

The deduction is one step: a binder slot names the sort it ranges over, a sort
admits its own branches, so everything in `Constructor.admits` of a binder slot's
sort is bindable. The closure is transitive, so a constant declared in a nested
sub-sort is caught too, and the message names both the sort the binder holds and
the one the production is in.

It does not become fully inferable — a sort that no binder mentions is still the
author's call — so this narrows the trusted surface rather than removing it. It
is silent for a grammar that declares no binding slots, which is what keeps it
safe for every system authored before the field existed.

One case does *not* go through this check, and does not need to. A nullary
defined form is marked constant by the engine rather than the author
(`denotes_a_constant`), so it never appears in `spec.productions`. It cannot
reach a binder's sort anyway: a definition into that sort needs a defining form
of that sort, everything there is bindable and so refused as a conjured name, and
the only way to prime the chain is a declared constant — which is what the check
above catches. Pinned by
`test_a_notation_cannot_reach_a_binder_sort_as_a_constant`.

### 2. Inferring a definition's `fresh` clause — **built**

A definition used to declare its defining form's binders by hand:

```
Define (x ⊆ y) as ∀z.((z ∈ x) → (z ∈ y))   fresh: z → setvar
```

`fresh` is exactly "which leaves of the defining form sit in a binder slot", and
with binding slots that is derivable from the parsed term. The clause is now
optional: `kernel.definitions.bind_scoped` places the binders while walking the
parsed defining form, and for a form whose binder scopes over the whole body it
builds the same interned schemas the hand-written clause does.

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
what keeps every system authored before this field behaving as it did; and an
occurrence of a name *outside* the binder's declared scope is not bound by it.

That last one is why placement reads the "over what" half of the declaration and
not just the binder slot's label. In `(∀z.(z ∈ x) → (z ∈ y))` the right-hand `z`
is free, and binding it along with the bound one would make the definition mean
something its author did not write. It stays a ground leaf, so `introduced_leaves`
reports it and the build refuses the definition with the message that names the
remedy — the same outcome as before binding slots existed, now for the reason
that is actually true of the form. A hand-written `fresh` clause still reaches
outside the scope: it is placed by name, which is the author's positive act and
the only reading available on a grammar that declares nothing.

**One name cannot bind at two sorts** — *superseded*. This was true while a
binder was stored per *name*, and was refused at build. Binding is now per
*occurrence* ([scope-aware-binding.md](scope-aware-binding.md)), so two binder
slots of different sorts holding one name are simply two binders, each with its
slot's own sort, and `(∃z.(z ⋴ y) → ∀z.(z ∈ x))` builds correctly. The same
change retires the withheld-inference rule two paragraphs up: an occurrence
outside a binder's scope is no longer bound, so it stays the free leaf it is
rather than needing a guard to notice.

What survives is the check on a *declared* clause, which is still placed by name
and so still carries one sort into every slot its name occupies.

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
what proofs are accepted, so it wants its own soundness argument — which is now
written: [scope-aware-definitional-steps.md](scope-aware-definitional-steps.md).

**Its finding is that this is not sufficient.** Deciding capture at the redex is
the easy half and the position information now exists; the hard half is that a
defined form is a *leaf*, so `Occurs` — the predicate every freshness proviso is
built from — answers differently either side of a definitional equality. A
proviso can be satisfied by `S` and violated by `(a ∈ b)`. Admitting open
abbreviations over genuine variables therefore needs notation to be transparent
to structural predicates first — as *separate* metadata, not via `free_vars`,
which is the schema-metavariable inventory and has three callers depending on a
ground term reporting none. That is a design question of its own, so the item
stays open with a named blocker rather than a vague warning.

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

### Frontend — **built**

A production's slots are edited by `ProductionSlotsEditor`, which offers each slot
a toggle per *sibling* — press it and this slot binds over that one. Only siblings
with a name are offered, and a production with one slot offers nothing, since
there is no reading of a slot that binds over itself or over nothing.

The editor refers to a target by an **editor-local id**, not by the sibling's
name (`slots.ts`). That is what makes a rename carry the declaration with it, and
it is why the earlier drop-a-stale-target rule is gone: a target that no longer
exists is now unrepresentable rather than something to filter out on the way to
the server. Removing the slot still drops the scope, which is the one case where
dropping is the answer.

An id rather than a reference to the row object because these rows live in a
`$state` array, where the proxy and the raw object are two identities and
`includes` on a mix of them silently answers false. That is a real bug this
went through, not a hypothetical.

The build's report is surfaced beside the `fresh` clause it concerns, in the
definition editor: what the build settled on, per binder, flagged *inferred from
the grammar* or *as declared*. A definition absent from a **successful** build's
report did not layer, and the editor says so — that drop is otherwise silent.
Nothing is reported from a failed build, where the report is empty and absence
would read as "dropped" for every definition at once.

## Open questions

1. **Does `scopes_over` need to be ordered or transitive?** For `∀x phi` it is a
   single slot. A production like a set-builder `{x | phi}` is the same shape.
   Nothing obvious in the target grammars needs more, but a comprehension with
   two binders would settle it.
2. **What happens to an existing system?** Nothing — the field is optional and
   empty means "no binding information", which is exactly today's behaviour. All
   three uses above are opt-in per system, so this cannot regress a stored
   system.
3. **Should `fresh` inference be silent or explicit?** ~~Still open~~ —
   **settled**. Inference stays silent at build, and `POST /{id}/validate` reports
   what it concluded: per compiled definition, the binders it settled on, each
   flagged `inferred` (read off the grammar) or not (written in the `fresh`
   clause). `validate` is the surface because it is where the built system exists
   — the definitions read model returns stored rows, which is the *declared*
   clause by construction. The definition editor now shows that report beside the
   `fresh` field, which is what makes silent inference visible where it matters.
4. **Item 3 (scope-aware steps) needs a soundness argument** before any code. It
   widens what the checker accepts, which is the one direction that can be wrong.

## Recommended sequencing

1. ~~Engine field + build-time validation of `scopes_over`~~ — **done**.
2. ~~Storage + API round-trip, with a migration~~ — **done**.
3. ~~Use it for `denotes_constant` validation~~ — **done**. Narrow, safe, and
   catches the documented hole.
4. ~~Use it to infer/check `fresh`~~ — **done**, in the add-only form described
   above.
5. ~~Frontend editing (the per-slot "binds over" control), and surfacing the
   build's report in the editor~~ — **done**.
6. Scope-aware definitional steps — **analysed, blocked**; see
   [scope-aware-definitional-steps.md](scope-aware-definitional-steps.md).

Step 4 shipped ahead of 3 because it is the one with a caller waiting: a Metamath
import reconstructs a `fresh` clause per definition without it. Step 6 is the only
one left, and it is blocked on a kernel-representation question rather than on
effort.
