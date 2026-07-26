# Design: scope-aware definitional steps

**Status:** analysed, **not built** — and the analysis found a prerequisite that
was not previously identified. This note is the soundness argument
[binding-slots-design.md](binding-slots-design.md) §3 asks for before any code.
Its conclusion is that scope-awareness at the redex is *necessary but not
sufficient*, and that the missing piece is a different change.

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

For an open abbreviation to be admissible, a defined form's leaf has to report
the free variables of its definition. `S` would have to answer "`a` and `b` occur
in me", so that:

- `Occurs` and `DisjointLeaves` see through the notation;
- an eigenvariable check cannot be passed by hiding a variable behind a constant;
- `free_vars` means what its callers assume it means.

That is a change to what a *notation* carries — semantic information from the
definition it abbreviates — and it cuts across the layering this arc has spent
several changes establishing: the kernel reads no strings, a production projects
to a `Constructor`, and a `Constructor` is structural. Making a constructor carry
"the free variables of the definition whose defined form I am" is not obviously
wrong, but it is a design question in its own right, not an implementation detail
of this one.

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
