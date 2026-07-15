# Design: object-level CRUD for formal systems

**Status:** proposal (no code yet) · **Branch:** `claude/formal-system-object-crud`

## Goal

Today a user authors a formal system as one `.edi` (or declarative) text blob
and we compile it. This design lets users **create and edit the component parts
of a system directly** — its sorts, productions, definitions, axioms and rules —
through typed REST endpoints and a set of Svelte editors, with **no `.edi`
authoring required**. The normalised store landed in `app/systems/` is the
substrate; this work puts an API and a UI on top of it.

Scope is bounded by the phrase *"up to the limit of our current data storage"*:
we expose CRUD for exactly what the `app/systems/` models can represent, and no
more (see [Storage limits](#storage-limits)).

## What is CRUD-able

The aggregate root is a **formal system**; everything else is a child owned by
it. One row per part (already the shape of `app/systems/models.py`):

| Resource | Table | Notes |
|---|---|---|
| Formal system | `formal_systems` | name, slug, description, `inherits_from_id` |
| Bracket pair | `notation_brackets` | the only notation currently stored |
| Sort | `sorts` | e.g. `term`, `formula` |
| Production (+ bindings) | `productions`, `production_bindings` | grammar rule + typed slots |
| Line type (+ parts) | `line_types`, `line_parts` | the logical statement shape |
| Definition (+ bindings) | `definitions`, `definition_bindings` | layered abbreviations |
| Axiom (+ bindings) | `axioms`, `axiom_bindings` | asserted formulae |
| Rule (+ antecedents, bindings) | `rules`, `rule_antecedents`, `rule_bindings` | inference rules |

The bridge already exists: `app/systems/mapping.py` turns these rows into a
`SystemSpec`, and `declarative.build_spec(spec)` compiles it. So the API never
touches `.edi` text — it reads/writes rows, and validates by assembling the spec
and compiling it.

### Storage limits (what CRUD deliberately does *not* cover)

Being honest about the "current data storage" boundary:

- **Code-mode side-conditions / pattern functions** (`.each(...)`, `return
  self.f`) are not modelled — only a single `condition` string per definition
  and rule. Systems that need the code-mode escape hatch can't be fully built
  through objects yet.
- **General notation** beyond a bracket pair (symbol table, fixity, precedence)
  isn't stored. Notation CRUD is limited to bracket pairs.
- **Proofs, folders, theorems, users/ownership** live outside `app/systems/`
  (PR #13 territory) and are out of scope here.
- **Multiple/loose line types**: the store carries one logical line spec plus
  parts; axioms become axiom-behaviour line types at lowering time, not stored
  line rows.

These are noted as future extensions, not silently dropped.

## Backend design

### Prerequisite: a database session

`app/systems/models.py` exists, but develop has **no engine/session layer** —
that infrastructure is in the un-merged PR #13 (`app/db/session.py`, async
SQLAlchemy + asyncpg on Neon). CRUD cannot land without a session. Options:

1. **Add a small session module in this branch** (sync SQLAlchemy + SQLite for
   dev/tests, Postgres via `DATABASE_URL`), and let the #13 rework reconcile it.
2. **Depend on PR #13 merging first** and build on its async session.

**Recommendation: option 1**, a minimal `app/systems/session.py` that boots on
SQLite with no config (so tests and local dev need nothing) and honours
`DATABASE_URL` when set. It keeps this branch self-contained and independently
mergeable; the #13 follow-up already has to reconcile `app/systems/` with
`app/db/`, and folding one session module in is trivial. This does mean choosing
**sync** SQLAlchemy for now (simpler; the CRUD endpoints are light) — flagged as
an open decision since #13 chose async.

### API resource model

Resource-oriented, nested under the system, mirroring the route style already in
`app/main.py` (`/formal-systems/...`). A **hybrid** of full-document read and
per-object writes:

```
GET    /formal-systems                      list (summaries)
POST   /formal-systems                      create (name, description, inherit)
GET    /formal-systems/{id}                 full structured system (all children)
PATCH  /formal-systems/{id}                 update system-level fields
DELETE /formal-systems/{id}                 delete (cascades to children)
POST   /formal-systems/{id}/validate        assemble + compile; return errors/summary
GET    /formal-systems/{id}/source          read-only lowered .edi (transparency/export)

# child collections (same pattern for each part type)
GET    /formal-systems/{id}/productions
POST   /formal-systems/{id}/productions
PATCH  /formal-systems/{id}/productions/{pid}
DELETE /formal-systems/{id}/productions/{pid}
PUT    /formal-systems/{id}/productions/order      reorder (positions)
# …and likewise for sorts, definitions, axioms, rules, line, brackets
```

Why hybrid:

- `GET /{id}` returns the whole system so the editor loads in one request.
- Per-object `POST/PATCH/DELETE` give true object CRUD ("edit the component
  parts") and map one-to-one onto the Svelte section editors.
- `validate` recomputes compilability on demand (the editor calls it after
  edits), so we never force a re-compile inside every write.

Bindings/antecedents are edited as part of their parent object's payload (they
are value lists, not independently addressable), keeping the endpoint surface
manageable.

### Schemas (`app/schemas.py` additions)

Pydantic models mirroring the rows and the `SystemSpec` records — e.g.
`ProductionIn`/`ProductionOut` with a nested `bindings: list[BindingModel]`, a
`FormalSystemOut` aggregating every child list, and a `ValidateResponse`
(`success`, `errors`, `system_name`, counts) reusing the `CompileResponse`
shape. Keep the layer **thin**: routes translate HTTP ⇄ Pydantic, call
`app/systems/mapping` + `build_spec`, and persist — no engine logic in `app/`.

### Validation strategy

A system is often **temporarily invalid mid-edit** (you add a production that
references a sort you haven't created yet). Two policies:

- **A. Reject any write that breaks compilation.** Simple, but hostile to
  editing — you can't save work in progress.
- **B. Allow saving invalid drafts; expose validity separately.** Store the
  rows regardless; `POST /{id}/validate` (and the `compiled`-style summary)
  reports whether the assembled system compiles and lists errors.

**Recommendation: B.** Writes persist structurally-valid rows (FKs, required
fields); *semantic* validity (does it compile?) is surfaced by `validate` and
shown as a live indicator in the UI, not enforced on every keystroke. Publishing
(a later concern) can gate on validity.

### Keeping it thin (per AGENTS.md)

`app/` stays a translation layer: it owns HTTP, Pydantic, persistence, and calls
into `app/systems/mapping.py` (rows ⇄ spec) and `website.logical.declarative`
(spec → compiled system). No proof/compile logic moves into `app/`.

## Frontend design

### Types & client (`frontend/src/lib/`)

- Extend `api.ts` (or add `api/systems.ts`) with TS interfaces mirroring the new
  Pydantic schemas — `FormalSystemSummary`, `FormalSystem`, `Production`,
  `Binding`, `Definition`, `Axiom`, `Rule`, `LineType`, `ValidateResult` — and a
  resource-grouped client: `api.systems.list/get/create/update/remove`, plus
  `api.productions.create/update/remove(...)` etc., built on the existing
  `request<T>` / `ApiError` helpers. Convention preserved: interfaces "mirror
  app/schemas.py".

### Routes

- `/systems` — list/create systems (cards, like the existing pages).
- `/systems/[id]` — the object editor (loads `GET /{id}`), with a live validity
  badge driven by `POST /{id}/validate`.

### Component tree (`frontend/src/lib/components/systems/`)

A section editor per part, composed into the `[id]` page:

```
system-editor.svelte            orchestrates load/save/validate, holds state
  notation-editor.svelte        bracket pairs
  sorts-editor.svelte           add/rename/remove/reorder sorts
  productions-editor.svelte     list of productions
    production-row.svelte        name, sort, template/regex
      bindings-editor.svelte     shared: var : sort rows
  line-editor.svelte            shape + parts + logical sort
  definitions-editor.svelte     higher / means lower / condition (+ bindings)
  axioms-editor.svelte          label / name / formula (+ bindings)
  rules-editor.svelte           label / from … ; … / infer … (+ bindings)
  system-source.svelte          read-only lowered .edi (collapsible)
```

Built with the existing stack — Svelte 5 runes (`$state`/`$derived`),
shadcn-svelte `Card`/`Button`/`Input`/`Label`/`Alert`, lucide icons — matching
`routes/compile/+page.svelte`. `bindings-editor.svelte` is reused by every part
that has bindings.

### State & UX

- The `[id]` page loads the full system into a `$state` object; each section
  edits its slice and calls the matching object endpoint (optimistic update,
  revert on `ApiError`).
- A **debounced `validate` call** after edits drives a header badge
  ("Valid" / "N errors") and inline error surfacing — the same information the
  compile page shows, but continuous.
- The read-only **lowered `.edi`** panel keeps the text representation visible
  for transparency and copy-out, so nothing is hidden by moving to objects.
- *Optional later:* an **import** path (paste declarative/`.edi` → parse →
  objects) so existing systems can be brought into the object editor.

## Open decisions (need your call before code)

1. **Session layer** — add a minimal sync session here (recommended) vs wait for
   PR #13's async session. Affects mergeability and whether we go sync or async.
2. **Write granularity** — per-object endpoints (recommended, matches "edit
   component parts") vs a single whole-system `PUT`. Hybrid as described splits
   the difference.
3. **Validity policy** — allow invalid drafts + `validate` (recommended) vs
   reject non-compiling writes.
4. **Ownership/auth** — single-user/unauthenticated for now vs scope to an owner
   (needs the users table from #13). Suggest unauthenticated for this branch,
   with `owner_id` left nullable for later.

## Phased delivery (once decisions are settled)

1. Session module + `FormalSystem` create/list/get/delete + `validate`.
2. Pydantic schemas + child CRUD (sorts, productions, definitions, axioms,
   rules, line, brackets) + reorder.
3. `api.ts` client + TS types.
4. Svelte `/systems` list and `/systems/[id]` editor shell.
5. Section editors (one per part) + `bindings-editor`.
6. Live validation badge + read-only source panel.

Each phase is independently testable: backend with pytest (round-trip a system
through the endpoints and assert it still compiles and checks a proof), frontend
with `svelte-check` and the run/verify skill against the live app.

## Testing

- **Backend:** endpoint tests on in-memory SQLite (as `tests/test_systems_store.py`
  already does) — create a system via the API, add parts, `validate`, and assert
  the assembled system compiles and checks a known proof; assert draft-invalid
  systems persist and report errors.
- **Frontend:** `npm run check`; drive `/systems/[id]` with the run skill to
  confirm an edited system validates end-to-end.
