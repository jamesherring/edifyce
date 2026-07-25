# Plan: proof-to-proof references & first-class definitions

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
- Definition provisos (`kernel_condition`) are enforced **only on the kernel
  definitional-step path**; the string-application path *refuses* a
  proviso-carrying definition (`matching/definitions.py:110-117, 246-250`). This
  is the one real behavioural limit.
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

### D2 — honor definition provisos consistently (engine, foundational)
- Resolve the behavioural asymmetry: today a proviso-carrying definition works
  only on the kernel definitional-step path; the string-application path refuses
  it. Options: (i) enforce provisos on the string path too, or (ii) route
  proviso-carrying definitions through the kernel path by default and gate/clearly
  error otherwise. **Recommend a short spike first** — this is the deepest unknown,
  and D0/D1 are only fully meaningful once a full-proviso definition is usable
  wherever definitions are used. Lean hard on the engine test suite.

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

**Order:** D2 spike early → D0 → D1; D3 is the larger elevation and can follow.

---

## Recommended overall sequencing

1. **R0** and **D2 spike** (independent; start both).
2. **R1** (references verify) and **D0** (definition proviso parity) — backend.
3. Build the **Combobox/Command primitive**, then **R2** and **D1** — frontend.
4. **D3** — definitions top-level surface (+ optional explicit layering).

Cross-cutting principles: every PR small and additive; migrations
backward-compatible (expand/contract — add columns before code needs them);
engine changes (D2) gated by the full `pytest` suite; the searchable picker built
once (R2) and reused (D1/D3).

## Open decisions to confirm before starting
- **Reference labels**: `alias` column vs cite-by-slug (recommend `alias`).
- **Top-level definitions scope**: stay system-scoped and inherit the system's
  publication (recommend), vs. definitions with independent ownership/publishing.
- **D2 approach**: enforce provisos on the string path vs. kernel-path-by-default.
- **Explicit definition-dependency modeling** (D3): worth the added schema, or keep
  the positional/implicit layering that already works?
