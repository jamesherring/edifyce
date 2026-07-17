# Design: object-level CRUD for formal systems

**Status:** proposal (no code yet) · **Branch:** `claude/formal-system-object-crud`

> **Prerequisites (PR #13 now merged):** the normalised store, the **async**
> SQLAlchemy session (`app.db.get_session`), and the **users** table
> (`app.db.User`) are all in `develop`. One gap remains for owner-scoping:
> fastapi-users **authentication is not wired yet** (no `current_active_user`
> dependency) — see [Prerequisites](#prerequisite-persistence-is-in-auth-is-not).

## Goal

Today a user authors a formal system as one `.edi` (or declarative) text blob
and we compile it. This design lets users **create and edit the component parts
of a system directly** — its sorts, productions, definitions, axioms and rules —
through typed REST endpoints and a set of Svelte editors, with **no `.edi`
authoring required**. The normalised store (now in `app/db/`) is the substrate;
this work puts an API and a UI on top of it.

Scope is bounded by the phrase *"up to the limit of our current data storage"*:
we expose CRUD for exactly what the `app/db/systems.py` models can represent, and
no more (see [Storage limits](#storage-limits)).

## What is CRUD-able

The aggregate root is a **formal system** (`app.db.models.FormalSystem`);
everything else is a child owned by it (`app.db.systems`). One row per part:

| Resource | Table | Notes |
|---|---|---|
| Formal system | `formal_systems` | `owner_id`, name, slug, description, `inherits_from_id`, `published_at` |
| Bracket pair | `notation_brackets` | the only notation currently stored |
| Sort | `sorts` | e.g. `term`, `formula` |
| Production (+ bindings) | `productions`, `production_bindings` | grammar rule + typed slots |
| Line type (+ parts) | `line_types`, `line_parts` | the logical statement shape |
| Definition (+ bindings) | `definitions`, `definition_bindings` | layered abbreviations |
| Axiom (+ bindings) | `axioms`, `axiom_bindings` | asserted formulae |
| Rule (+ antecedents, bindings) | `rules`, `rule_antecedents`, `rule_bindings` | inference rules |

The bridge already exists: `app.db.system_to_spec` /
`spec_to_system` (in `app/db/systems_mapping.py`) convert these rows to and from
a `SystemSpec`, and `declarative.build_spec(spec)` compiles it. So the API never
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
- **Proofs, folders, theorems** live alongside the system tables in `app/db/`
  but are out of scope here (this branch is systems only).
- **Multiple/loose line types**: the store carries one logical line spec plus
  parts; axioms become axiom-behaviour line types at lowering time, not stored
  line rows.

These are noted as future extensions, not silently dropped.

## Backend design

### Prerequisite: persistence is in, auth is not

PR #13 is merged, so the persistence pieces this design assumed now exist in
`develop`:

- **Async session** — `app.db.get_session` is a FastAPI dependency yielding an
  `AsyncSession` (asyncpg, `NullPool`, PgBouncer-safe). Lazy: importing it opens
  no connection, and the app boots with no `DATABASE_URL`.
- **Row models + mapping** — `app.db.systems` (the `*Row` classes),
  `app.db.models.FormalSystem` (aggregate root, **no `source`/`compiled`
  blob**), and `spec_to_system` / `system_to_spec`.
- **Users** — `app.db.User` (fastapi-users SQLAlchemy base) for `owner_id`.

CRUD routes are therefore `async def`, take `session: AsyncSession =
Depends(get_session)`, and use async SQLAlchemy. Reads of the aggregate must
`selectinload` the child collections (async has no lazy load). Building a
`FormalSystem` graph with `spec_to_system` and `session.add()` + `await
session.commit()` works unchanged (it is plain in-memory ORM construction).

**Remaining gap — authentication.** #13 landed the `users` *table* but "no auth
routes are wired yet": there is no fastapi-users authentication backend and so
no `current_active_user` dependency to identify the owner. Owner-scoping
(decision 4) needs one. Two ways forward, to confirm:

1. **Wire minimal fastapi-users auth first** (JWT backend + user manager +
   `current_active_user`) — a small, self-contained addition this branch can
   include, or a sibling branch it depends on.
2. **Stub the current-user dependency** (a single dev user / `X-User-Id` header)
   behind one `get_current_user` function, and swap in real auth later.

Recommendation: **option 1**, scoped to just the authentication backend (not
registration/OAuth flows), so `owner_id` is real from day one. Either way the
owner is resolved through **one** dependency, so the CRUD routes don't change
when real auth arrives.

### API resource model

Resource-oriented, nested under the system, mirroring the route style already in
`app/main.py` (`/formal-systems/...`). A **hybrid** of full-document read and
per-object writes:

All routes are **owner-scoped** (decided): they depend on a single
`get_current_user` (see the auth gap above), and every query filters on
`owner_id` so a user sees and edits only their own systems. `owner_id` is the FK
to `app.db.User`.

```
GET    /formal-systems                      list current user's systems (summaries)
POST   /formal-systems                      create (name, description, inherit); owner = caller
GET    /formal-systems/{id}                 full structured system (all children), if owned
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
`app.db` mapping (`spec_to_system` / `system_to_spec`) + `build_spec`, and
persist — no engine logic in `app/`.

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
into `app/db/systems_mapping.py` (rows ⇄ spec) and `website.logical.declarative`
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

## Decisions (resolved)

1. **Session layer** — build on **PR #13's async session** (`app.db.get_session`,
   now merged). Routes are async; no second persistence stack.
2. **Write granularity** — **hybrid**: full-system `GET /{id}` + per-object
   `POST/PATCH/DELETE` + reorder. Matches "edit the component parts".
3. **Validity policy** — **allow drafts + on-demand `validate`**. Writes persist
   structurally-valid rows; compilability is surfaced, not enforced per write.
4. **Ownership** — **owner-scoped** to `app.db.User`; all routes require the
   current user and filter on `owner_id`. (Needs the auth backend wired — see
   the prerequisites gap.)

## Phased delivery

Phase 0 (prerequisites): PR #13 is **merged** — async session, row models, and
`users` table are in `develop`. The one outstanding piece is the fastapi-users
**authentication backend** feeding a `get_current_user` dependency (see
Prerequisites). Then:

1. Wire minimal authentication → `get_current_user` (or the agreed stub).
2. Pydantic schemas (rows ⇄ spec) + `FormalSystem` create/list/get/delete +
   `validate`, all owner-scoped and async.
3. Child CRUD (sorts, productions, definitions, axioms, rules, line, brackets) +
   reorder.
4. `api.ts` client + TS types.
5. Svelte `/systems` list and `/systems/[id]` editor shell.
6. Section editors (one per part) + `bindings-editor`; live validation badge +
   read-only source panel.

Everything the endpoints depend on now exists in `develop`; the frontend phases
depend only on the endpoints, not on the DB directly.

Each phase is independently testable: backend with pytest (round-trip a system
through the endpoints and assert it still compiles and checks a proof), frontend
with `svelte-check` and the run/verify skill against the live app.

## Testing

- **Backend:** the round-trip test (`tests/test_systems_store.py`) already
  exercises `spec_to_system` / `system_to_spec` against SQLite via a **sync**
  session. Endpoint tests hit `async def` routes, so they need an async driver
  — either add **`aiosqlite`** as a dev dependency and point a test
  `get_session` override at `sqlite+aiosqlite://`, or override `get_session`
  with a sync-backed session in the test app. Create a system via the API, add
  parts, `validate`, and assert the assembled system compiles and checks a known
  proof; assert draft-invalid systems persist and report errors. Note only the
  system-decomposition tables are SQLite-creatable (the `theorems` pgvector
  table is Postgres-only), so tests create just those tables — the existing
  round-trip test already does this via a `_SYSTEM_TABLES` list.
- **Frontend:** `npm run check`; drive `/systems/[id]` with the run skill to
  confirm an edited system validates end-to-end.
