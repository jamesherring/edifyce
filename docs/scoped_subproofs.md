# Scoped subproofs and discharge rules

This note records a rework of how Edifyce handles *proof context that applies by
line* — the mechanism behind Python‑like indentation for assumptions. It grew
out of the observation that line types are one of the more awkward parts of the
engine, and that indentation‑as‑assumptions is welded to first‑order/ZFC‑style
systems rather than being a general facility.

The scoped system that replaces it lives in [`tests/zfc_systems.py`](../tests/zfc_systems.py)
and is exercised by [`tests/test_zfc_scoped.py`](../tests/test_zfc_scoped.py).

> **Historical note.** The "legacy" mechanism described in the next section — the
> `given` `MatchSet` plus a rule `condition:` proviso — has since been **removed
> from `develop`**: the string-based rule-condition interpreter was replaced by
> the kernel's closed side-condition algebra, and `condition:` blocks now raise
> at compile time. The before/after below is kept as motivation; the "before"
> is no longer expressible, which only reinforces the point.

---

## The problem, in the legacy engine

Before this change, opening a scope was a *behaviour* — `behaviour: indent` —
mutually exclusive with `logical`, `axiom`, `definition`, and the rest. To carry
an assumption you needed **three coupled pieces**:

1. a `ProofContext` slot, `given: MatchSet()`;
2. a **content‑free** `behaviour: indent` line that adds its formula to `given`
   (`context.given: add: formula()`); and
3. a `HYP` inference rule whose condition is `deduction.formula() in given`.

```
LineType assume:
    pattern: assume_pattern      # matches "assume φ:"
    behaviour: indent
    context.given:
        add: formula()

InferenceRule hypothesis:        # HYP
    deduction:
        p
    condition:
        deduction.formula() in given
```

Beyond the ceremony, three real defects:

- **Scope‑opening can't coexist with being a logical line.** The assumption is
  not itself a citable proof line; it's a side effect on `given`.
- **`given` plumbing is fragile.** The obvious spelling `union: formula()`
  silently clobbers the set to `None` (`MatchSet.add` returns `None`, and
  `edit_context` assigns that back); you have to know to use `add:`. Naming the
  assumption variable `a` also breaks matching, because the token `a` collides
  with the letter `a` inside the keyword `assume`.
- **References are not scope‑checked — so the system is unsound.** Indentation
  only affects `previous_formulae()` and context copying; it never constrains
  which lines a citation may reach. Conditional proof (`→I`) is therefore faked
  by citing two *individual* lines, and nothing stops a line from reaching into
  a **closed sibling** subproof.

That last point is not theoretical. In the legacy system this is accepted:

```
assume a ∈ b:
    a ∈ b [HYP]
assume b ∈ c:
    a ∈ b [R, 2]            ← line 2 is a discharged hypothesis of the CLOSED block
(b ∈ c → a ∈ b) [CP, 3, 4]  ← "proves" a non‑theorem
```

`(b ∈ c → a ∈ b)` is not a theorem for arbitrary `a, b, c`. The old checker said
it was. The scoped system rejects it — see
`test_zfc_scoped.py::test_bogus_theorem_is_rejected`.

---

## The rework

Three changes, each matching a recommendation from the original review, plus the
soundness fix that ties them together.

### A. `scope` is orthogonal to `behaviour`

`LineType` gains a `scope` attribute (`"assumption"`, `"variable"`, or `None`),
independent of `behaviour`. One line can now be **both** a formula‑bearing
logical line **and** a scope opener:

```
LineType assume:
    pattern: assumption_pattern     # matches "assume φ"
    behaviour: logical
    scope: assumption

LineType introduce:
    pattern: variable_pattern       # matches "let x"
    behaviour: logical
    scope: variable
```

No `given`, no `HYP` rule, no content‑free opener. The assumption *is* a proof
line; it is valid by fiat inside its own subproof.

### B. First‑class subproofs, built during parsing

A [`Subproof`](../website/logical/formal_system/proof.py) is created **only** by a
`scope` line; its extent is the following more‑indented block (indentation stays
the default delimiter). Every line records its `scope`, and each subproof knows
its opener, its `conclusion` (last logical line), its parent, and — for
`variable` scopes — its `eigenvariable`. Systems that declare no `scope` lines
keep a single root subproof and are completely unaffected (the full pre‑existing
suite is untouched).

### C. Scope‑checked references — the soundness core

`line_is_accessible(citing, cited)` enforces the natural‑deduction reiteration
restriction: a line may cite only its own subproof or an enclosing one, never
the interior of a closed sibling. With no subproofs everything is in the root
scope, so this is a no‑op for legacy systems.

### D. Discharge rules

An inference rule may declare a `subproof:` it consumes as a **unit** rather than
citing individual lines. `→I` and `∀I` become ordinary, in‑language rules:

```
InferenceRule conditional_proof:      # →I / CP
    subproof:
        assume:
            p
        derive:
            q
    deduction:
        (p → q)

InferenceRule universal_generalisation:  # ∀I / UG
    subproof:
        fresh:
            x
        derive:
            p
    deduction:
        ∀x p
```

### E. Freshness for `∀I`, via the kernel

`UG` needs the eigenvariable to be genuinely arbitrary. This is
[kernel step 3](../website/logical/kernel/terms.py) — a structural side‑condition
over terms — implemented in
[`kernel/side_conditions.py`](../website/logical/kernel/side_conditions.py): the eigenvariable
must not `occur` in any hypothesis still in force around the subproof, checked on
the parse‑once `Term` tree rather than by string search.

---

## The same theorems, checked soundly

```
# (a ∈ b → a ∈ b)  — conditional proof as a first‑class subproof
assume a ∈ b
    a ∈ b [R, 1]
(a ∈ b → a ∈ b) [CP, 1]            ✓ valid

# ∀x (x ∈ c → x ∈ c)  — generalisation over a fresh variable
let x
    assume x ∈ c
        x ∈ c [R, 2]
    (x ∈ c → x ∈ c) [CP, 2]
∀x (x ∈ c → x ∈ c) [UG, 1]         ✓ valid
```

And the defects are closed:

```
# the legacy bogus proof — now REJECTED
assume a ∈ b
    a ∈ b [R, 1]
assume b ∈ c
    a ∈ b [R, 2]      ✗ "Line 2 is out of scope (it is inside a closed subproof)."
(b ∈ c → a ∈ b) [CP, 3]

# unsound ∀I — REJECTED by freshness
assume x ∈ c
    let x
        x ∈ c [R, 1]
    ∀x x ∈ c [UG, 2]  ✗ x occurs in the enclosing hypothesis, so it is not arbitrary
```

Freshness constrains only the eigenvariable itself, so a genuinely fresh (if
vacuous) generalisation is still allowed:

```
assume y ∈ c
    let x
        y ∈ c [R, 1]
    ∀x y ∈ c [UG, 2]  ✓ x does not occur in the hypothesis about y
```

---

## Why this is better

| | Legacy (`indent` + `given`) | Scoped subproofs |
|---|---|---|
| Assumptions | 3 coupled pieces (slot + opener + rule) | 1 line type: `scope: assumption` |
| Opener as a proof line | no (side effect on `given`) | yes (`behaviour: logical`) |
| Delimiter/inheritance/discharge | fused, hard‑coded in `parse` | separated; discharge is a rule |
| `→I` | faked by citing two lines | `subproof: assume/derive` |
| Cross‑scope citation | **accepted (unsound)** | rejected |
| Bogus `(b∈c → a∈b)` | **accepted** | rejected |
| `∀I` eigenvariable freshness | not checked | checked structurally (kernel) |
| Adding `¬I`/RAA, `∃E`, … | new bespoke plumbing each time | another discharge rule |

## Alignment with the internal graph (term) representation

The kernel is migrating the engine off string back‑tracking onto a parse‑once
**graph of terms** (`kernel/terms.py`), with matching (`kernel/unify.py`) and a
closed side‑condition algebra (`kernel/side_conditions.py`) built on it. Where do
these changes sit relative to that?

- **Freshness — on the graph.** The `∀I` eigenvariable check is expressed as
  `Not(Occurs("eigenvariable", "hypothesis"))` from the kernel's closed algebra,
  evaluated over `Term` trees projected with `from_match`. It is the algebra's
  own worked example.
- **Scope structure — correctly *not* in the kernel.** Subproofs, accessibility,
  and "which hypotheses are in force" are *proof‑state*, not formula structure.
  `kernel/side_conditions.py` says so explicitly: "membership in a proof‑context
  set (`x ∈ Γ` over the assumptions) … depend on proof state and are
  intentionally not expressible here; they belong in the elaboration layer." So
  the eigenvariable check is split the right way — the elaboration layer
  (`Subproof`) decides *which* terms are in force; the kernel decides *occurrence*
  structurally.
- **Discharge matching — now on the graph.** Binding a discharge rule's schema
  to proof‑line formulae runs on `unify.match_all` over `Term`s: `from_pattern`
  projects the schema (`(p → q)`, `∀x p`, `¬p`, `⊥`), `from_match` projects the
  proof‑line formulae, and one substitution is derived across deduction,
  conclusion and assumption. This is the first live consumer of the term‑based
  checker (`InferenceRule.check` for ordinary rules is still string‑based; that
  is the rest of step 4).
- **What unblocked it — `AtomPattern`.** Moving discharge onto `unify` used to
  fail on a ground‑literal conclusion (a falsum `⊥`): the schema was a
  `StringPattern` literal while the proof line matched a `RegexPattern`, two
  different constructors under `terms._signature`. The fix was to give atoms a
  first‑class primitive — `AtomPattern`, a constant or an infinite base+index
  family (`p_i`) declared with no regex — whose term‑signature is *what the atom
  denotes* (`('atom', 'const', '⊥')`), not the pattern object. A rule's literal
  and the system's declared atom are then one constructor by construction. See
  `tests/test_atom_pattern.py` for a propositional system whose entire term
  algebra is regex‑free, discharge‑checked via `unify`.

Net: freshness and discharge both live on the graph representation now; the
remaining string‑based matcher is `InferenceRule.check`, the rest of the
checker‑wide step 4.

---

The general move is to stop fusing three separate concerns — *scope structure*,
*context inheritance*, and *discharge* — into one `behaviour` slot plus a
convention on a `MatchSet`. Structure is now declared (`scope`), discharge is a
rule (`subproof:`), and the side‑conditions that make discharge sound
(reiteration scoping, eigenvariable freshness) are enforced by the engine rather
than left to the author to get right. `→I`, `∀I`, and the next discharge rule a
system needs are all the same mechanism.
