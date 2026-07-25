# Plan: proof-to-proof references & first-class definitions

> **Status: delivered.** Kept as a record of the design, not a description of
> the code. One thing it says is now false: the engine-side import machinery it
> surveys under "What already exists" — `import_path`, `reference_proofs`,
> `proofs_used`, `dependency_order`, `circular_dependency` — has been **deleted**.
> The plan chose pre-seeding `reference_context` over import lines, so that
> machinery was never wired up, and the reference graph now lives only in
> `proof_references` with the sort and cycle checks in `app/routers/proofs.py`.

A proposed sequence of small, additive PRs to deliver three capabilities:

- **(a)** proofs that reference other proofs — transitively, with circular
  references rejected;
- **(b)** a good import/reference UX for building proofs on earlier lemmas;
- **(c)** definitions as a first-class, top-level entity (scoped to a system)
  that can build on other definitions and use the full proviso vocabulary.

The guiding finding of the design review: **most of the hard engine work already
exists.** The gaps are persistence wiring, the API/verify path, and UI — plus one
genuine engine wrinkle for definition provisos. This plan is scoped to *wire up
and surface* existing engine capability rather than reinvent it.

---

## What already exists (do not rebuild)

**Proof references — the engine is done.** `website/logical/formal_system/proof.py`:
- `import_path` resolves a reference via `reference_proofs` (a `path -> {"target",
  "errorMessage"}` dict) or a pre-seeded `reference_context`, binds it under a
  label, and records the dependency in `proofs_used`.
- Cycle detection is **transitive**: `_dependency_graph()` walks the full
  `proofs_used` closure over `Proof` vertices; `circular_dependency()` runs a
  `graphlib` topological sort (`find_cycle`). `import_path` tentatively adds the
  edge, checks, and **rolls back the edge and any shadowed label** on a cycle
  (`proof.py:821-846`). `dependency_order()` gives a ground-up checking order.
- Cross-proof citation already works: a line cites imported material as
  `[<Label>.<line>]` (or `[MP, <Label>.<line>, 2]`); `line_is_accessible`
  bypasses the scope tree for a cited line from another proof.
- Covered end-to-end by `tests/test_bipartite_checking.py` (driving the engine
  directly).

**Definitions — grammar, layering, and proviso storage are done.**
- Definitions **already layer**: a later definition's `lower` form may use notation
  from an earlier one. Realised at build time — definitions finalise in
  `position` order and each resolved one is added back to `context.definitions`
  (`declarative.build_system` step 8), so the next one's match sees it. The
  dependence is positional and not recorded relationally.
- Definition provisos use the **same `SideConditionRow` algebra as rules** — same
  closed vocabulary (`occurs`/`equal`/`disjoint`/`atom`/`member` + `not`/`and`/
  `or`), same `_materialise`, same either-or owner table (`app/db/side_conditions.py`).
  `_assign_definition` already builds proviso *rows* (not an opaque string).
- Full definitions CRUD exists (`api.parts.definitions`), and a
  `DefinitionsSection.svelte` already renders in the system editor.

**What is NOT wired:**
- `proof_references` (M2M on `proofs`, cascade) exists but is **never read or
  written** by any `app/` code; no endpoint touches references; every `parse()`
  call omits `reference_proofs`, so imports are unreachable via the API.
- The declarative model has **no import line type** (`LineSpec` has no behaviour;
  `SystemSpec.line` is a single logical line) — so DB-built systems can't emit
  `behaviour: import`. *We avoid this by pre-seeding `reference_context` from
  stored references instead of emitting import lines.*
- Definition provisos are surfaced in the API/UI as a **single `condition`
  string** (vs rules' structured `side_conditions: list`), and the
  `DefinitionsSection` condition field is one bare text box.
- ~~Definition provisos (`kernel_condition`) are enforced only on the kernel
  definitional-step path; the string-application path refuses a proviso-carrying
  definition.~~ **Closed by D2** — the string-application path is gone, so there
  is only the kernel path to enforce them on.
- No frontend primitive for a searchable picker (no `Select`/`Combobox`/`Command`
  wrapper; `bits-ui` is a dep but only `dialog`/`sheet` are wrapped).

---

## Track R — proof-to-proof references

Goal: a proof can cite lemmas proven in other proofs of the **same system**,
transitively, with cycles rejected, and a clean picker UX.

### R0 — reference persistence + write-time cycle rejection (backend)
- Read/write `proof_references`. New endpoints on the proof:
  `GET/PUT /proofs/{id}/references` (set the full set) and/or
  `POST/DELETE /proofs/{id}/references/{refId}`.
- **Decision — how a citation names a reference:** either cite by the referenced
  proof's `slug` (no schema change) or add an `alias` column to `proof_references`
  for stable, user-chosen labels (`[HS.7]`). *Recommended: add `alias`* — slugs
  change on rename and aren't ergonomic in proof source. (Requires a migration.)
- Guards, all returning 422/409:
  - **same-system**: a proof may only reference proofs in its own system;
  - **same-owner**: keep proof + references in one ownership domain (mirrors
    `inherits_from_id`);
  - **write-time cycle rejection**: reject an edge that would make the stored
    `proof_references` graph cyclic (topological check — the DB-level analogue of
    the engine's `circular_dependency`).
- Schema: `ProofDetail.references: [{id, name, slug, alias}]` (+ optionally
  `referenced_by` for a "used by" view).
- No verify change yet — references are stored, not yet consulted in checking.
- Tests: set/replace, self-reference rejected, 3-hop cycle rejected,
  cross-system rejected.

### R1 — wire references into verification (backend)
- In `_verify` (`app/routers/proofs.py`), load the **transitive** reference
  closure from `proof_references`, compile each referenced proof in
  `dependency_order`, and **pre-seed the citing proof's `reference_context`**
  (keyed by alias/slug) with the compiled `Proof` objects before `parse()`. This
  makes `[<alias>.<line>]` citations resolve and check — reusing the engine's
  existing import/cycle machinery, and deliberately **avoiding the declarative
  import-line-type gap**.
- **Dependent invalidation**: when a proof's source changes or it is unpublished,
  re-verify (or mark stale) the proofs that reference it. Reuse the
  `_require_publishable` re-verification path.
- **Publish invariant**: a published proof's references must themselves be
  published (a published proof is world-readable and exposes its references) —
  mirror the existing "published proof needs a published system" gate.
- Tests: a proof citing a lemma verifies; a 2-hop lemma chain verifies; a cycle
  is still caught at verify; unpublishing/breaking a referenced proof invalidates
  its dependents.

### R2 — reference picker + display (frontend)
- `api.proofs.references` client methods (set/list).
- **New reusable primitive**: a `Combobox`/`Command` wrapper over `bits-ui` (none
  exists today) — a searchable picker. Reused later by definitions (D1/D3).
- Proof editor: a "Lemmas" panel to add/remove references (search proofs in the
  same system, assign an alias) and a one-click "insert citation" into the source.
- Proof detail/results: turn `line.reference` into an interactive link when it
  targets another proof; add "References" and "Used by" sections that link across
  proofs.
- Tests: picker component, lemmas panel.

**Order:** R0 → R1 → R2 (backend can land before UI).

---

## Track D — first-class, proviso-powered definitions

Goal: definitions are a top-level entity (still system-scoped), build on other
definitions, and use the full proviso.

### D0 — definition proviso parity with rules (backend, small)
- Change the definition API surface from `condition: str | None` to
  `provisos: list[str]` (structured, like rules' `side_conditions`), backed by the
  existing `build_rule_side_conditions` + list rendering. **Storage is unchanged**
  (already `SideConditionRow`); this only upgrades the surface encoding, unlocking
  multi-line, full-vocabulary provisos in the API.
- Keep a compatibility read (`condition` derivable from the tree) during the
  transition. Tests mirroring the rule-proviso API tests.

### D1 — structured definition proviso editor + layering awareness (frontend)
- Replace the single "Condition" input in `DefinitionsSection.svelte` with the
  multi-row proviso editor already used by `RulesSection.svelte` (`RepeatableRows`
  + grammar guidance).
- Surface layering: an autocomplete (the R2 combobox) of existing defined
  notation, so a definition's `lower` can visibly build on earlier definitions.

### D2 — honor definition provisos consistently (engine, foundational) — **done**
Resolved by making definitions kernel-native rather than by teaching the string
path about provisos. The asymmetry existed because there were two checkers; there
is now one.

- A definition's kernel counterpart is built when the **system** is built
  (`declarative._finalise_definition` → `formal_system.build_kernel_definition`),
  and a definition with no sound kernel reading — an undeclared binder — fails the
  build, naming the variable and the fix. The string-application path
  (`Definition.check_application` / `get_lower`, `Match.equivalent_under_definitions`
  / `maps_to_up_to_definition`) is deleted, along with the lazy
  `kernel_definition` cache and `follows_from_definition`'s `mapping` argument.
- Measured before removing: across the whole suite the fallback was reached twice
  and returned False both times, from two tests written to exercise it. It
  verified no step.
- `matching.Definition` remains as *parser* state — it is what makes defined
  notation grammatical — but no longer applies anything.
- The capture rule lives in the kernel, over the term graph: `unbound_parameters`
  and `introduced_leaves` report the leaves a defining form introduces from
  nowhere. It is one property — **an unfold must preserve free variables**, so the
  step means the same thing wherever it is taken. Deciding which introduced leaves
  are benign (a constant of the object language) is a grammar question, so
  `formal_system/definitions.py` supplies that predicate and the matching layer
  supplies neither: patterns parse, and nothing else.
- This also closes the occurrence-site capture hole the first pass left open
  (`∀a. S → ∀a. a` for a nullary `S ≝ a`), by refusing such a definition at build
  time. What remains untreated is conservativity — that a defined symbol is fresh
  and the definition non-circular.
- **Follow-up, done:** that grammar predicate was a heuristic reading the leaf's
  constructor, and it had a third hole — an atom constant declared a *member of
  the variable sort* (`setvar ::= [A-Z] | c`) was excused, so `T ≝ (c ∈ c)` built
  and `∀c.T ⟶ ∀c.(c ∈ c)` captured. Nothing about a production's shape decides
  the question, so productions now **declare** it (`denotes_constant`), as
  Metamath declares `$c` vs `$v`. The heuristic and its reachability probe are
  gone. The declaration is authoritative and its default (variable-like) is the
  safe one; validating a wrong declaration needs binding slots on productions,
  which would also let `fresh` be inferred and open abbreviations return. See
  AGENTS.md.

### D3 — definitions as a top-level surface (backend + frontend)
- `api.definitions` namespace and a **per-system definitions page** (list +
  detail), mirroring the proofs surface, keeping system scoping. Note the existing
  `PartCrud`/`createSectionController` pattern is hard-wired to a `systemId`
  thunk — a per-system definitions page fits it; a global `/definitions` route
  would need a lightly generalized client.
- **Optional hardening — first-class layering**: model definition→definition
  dependencies explicitly (which defined notations a definition uses) for
  dependency-aware ordering/validation, replacing the implicit positional
  dependence. Improves reordering safety and UX.

**Order:** D2 (done) → D0 (done) → D1 (done); D3 is the larger elevation and can
follow.

---

## Recommended overall sequencing

1. ~~**R0** and **D2 spike** (independent; start both).~~
2. ~~**R1** (references verify) and **D0** (definition proviso parity) — backend.~~
3. ~~Build the **Combobox/Command primitive**, then **R2** and **D1** — frontend.~~
4. **D3** — definitions top-level surface (+ optional explicit layering).

Cross-cutting principles: every PR small and additive; migrations
backward-compatible (expand/contract — add columns before code needs them);
engine changes (D2) gated by the full `pytest` suite; the searchable picker built
once (R2) and reused (D1/D3).

## Open decisions to confirm before starting
- **Reference labels**: `alias` column vs cite-by-slug (recommend `alias`).
- **Top-level definitions scope**: stay system-scoped and inherit the system's
  publication (recommend), vs. definitions with independent ownership/publishing.
- ~~**D2 approach**: enforce provisos on the string path vs. kernel-path-by-default.~~
  **Decided**: neither — definitions are kernel-native, built and validated with
  the system, and the string path is deleted.
- **Explicit definition-dependency modeling** (D3): worth the added schema, or keep
  the positional/implicit layering that already works?
