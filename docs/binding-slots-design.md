# Design: binding slots on productions

**Status:** proposal (no code yet) · **Prerequisite work:** merged (#115, #117,
#118, #119, and the kernel-takes-terms change)

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

### 2. Inferring a definition's `fresh` clause

A definition currently declares its defining form's binders by hand:

```
Define (x ⊆ y) as ∀z.((z ∈ x) → (z ∈ y))   fresh: z → setvar
```

`fresh` is exactly "which leaves of the defining form sit in a binder slot", and
with binding slots that is derivable from the parsed term. The clause becomes
optional — inferred when omitted, and *checked* when given, so an author who
writes a wrong one is told.

This is the highest-value item for import work: a Metamath `$a`/`$p` carries no
`fresh` clause, so today an importer has to reconstruct one per definition.

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

### Engine

`Production.bindings` is `list[tuple[str, str]]` — `(slot, sort)`. The natural
extension is a third, optional element or a parallel field:

```python
@dataclass
class BindingSlot:
    name: str
    sort: str
    # Slots this one binds *over*. Empty for an ordinary argument slot; for the
    # `x` of `∀x phi`, `["phi"]`.
    scopes_over: list[str] = field(default_factory=list)
```

A production is a binder iff some slot has a non-empty `scopes_over`. The
constraint worth enforcing at build: a name in `scopes_over` must be another slot
of the same production.

This reaches `kernel.constructors.Constructor` as projected data (a slot label →
the labels it scopes over), which keeps the pattern/kernel boundary as it now
stands: `constructors` reads the production, nothing downstream holds one.

### Storage

`app/db/systems.py`'s production row gains the relation. Two options:

- a `scopes_over` text column on the existing binding row, holding a slot name —
  simplest, and a binder over several slots is rare enough to encode as a list;
- a join table, if a slot binding several slots is expected to be common.

Either way it is an Atlas migration (`atlas migrate diff`), and the models are
the source of truth — see AGENTS.md.

### API

`app/schemas.py` production payloads gain the field; `app/routers/system_parts.py`
validates that `scopes_over` names sibling slots, mirroring how it already
validates a binding's sort. `app/db/systems_mapping.py` round-trips it.

### Frontend

The production editor gains per-slot "binds over" selection. This is the part
that can lag: the field is optional and defaults to empty, so a system authored
without it behaves exactly as today.

## Open questions

1. **Does `scopes_over` need to be ordered or transitive?** For `∀x phi` it is a
   single slot. A production like a set-builder `{x | phi}` is the same shape.
   Nothing obvious in the target grammars needs more, but a comprehension with
   two binders would settle it.
2. **What happens to an existing system?** Nothing — the field is optional and
   empty means "no binding information", which is exactly today's behaviour. All
   three uses above are opt-in per system, so this cannot regress a stored
   system.
3. **Should `fresh` inference be silent or explicit?** Inferring it changes what
   an omitted clause means. Safer: infer, and *report* the inferred clause back
   through the API so an author sees what the engine concluded.
4. **Item 3 (scope-aware steps) needs a soundness argument** before any code. It
   widens what the checker accepts, which is the one direction that can be wrong.

## Recommended sequencing

1. Engine field + build-time validation of `scopes_over` (no behaviour change).
2. Storage + API round-trip, with a migration.
3. Use it for `denotes_constant` validation — narrow, safe, and immediately
   catches the documented hole.
4. Use it to infer/check `fresh`.
5. Frontend editing.
6. Scope-aware definitional steps — separately, with its own design note.

Steps 1–2 are mechanical; step 3 is where the value starts. Stopping after 4
would already be worthwhile, and each step is independently shippable.
