# Design: object-level CRUD for formal systems

**Status:** proposal (no code yet) · **Branch:** `claude/formal-system-object-crud`

> **Prerequisites — all met.** The normalised store, the **async** session
> (`app.db.get_session`), the **users** table, and now **authentication**
> (`app.auth.current_active_user`, cookie+JWT, with login/register/account UI)
> are all in `develop`. Nothing blocks implementation — see
> [Prerequisites](#prerequisites-everything-is-in).

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

### Prerequisites: everything is in

Every dependency this design assumed now exists in `develop`:

- **Async session** — `app.db.get_session` is a FastAPI dependency yielding an
  `AsyncSession` (asyncpg, `NullPool`, PgBouncer-safe). Lazy: importing it opens
  no connection, and the app boots with no database URL.
- **Row models + mapping** — `app.db.systems` (the `*Row` classes),
  `app.db.models.FormalSystem` (aggregate root, **no `source`/`compiled`
  blob**), and `spec_to_system` / `system_to_spec`.
- **Users + authentication** — `app.auth.current_active_user` is the
  fastapi-users dependency that yields the signed-in `User` (httponly-cookie +
  JWT backend; `/auth/login`, `/auth/register`, `/users/me` mounted in
  `app/main.py`), with login / register / account UI already in the frontend.

CRUD routes are therefore `async def` and take **two dependencies**:

```python
async def create_production(
    payload: ProductionIn,
    user: User = Depends(current_active_user),      # owner-scoping
    session: AsyncSession = Depends(get_session),   # persistence
): ...
```

Reads of the aggregate must `selectinload` the child collections (async has no
lazy load). Building a `FormalSystem` graph with `spec_to_system` and
`session.add()` + `await session.commit()` works unchanged (plain in-memory ORM
construction). Owner-scoping is now a direct filter — no stub, no gap.

### API resource model

Resource-oriented, nested under the system, mirroring the route style already in
`app/main.py` (`/formal-systems/...`). A **hybrid** of full-document read and
per-object writes:

All routes are **owner-scoped** (decided): they depend on
`current_active_user`, and every query filters on `owner_id == user.id` so a user
sees and edits only their own systems (404, not 403, for another owner's id, so
ids don't leak). `owner_id` is the FK to `app.db.User`.

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

**Known limitation (deferred): inheritance is not resolved in `validate` /
`source`.** `inherits_from_id` is stored and its reference validated on write,
but phase-1 `validate` and `source` compile each system in isolation
(`system_to_spec` describes one system; the declarative pipeline has no
`inherit` directive and no parent `system_dict` is supplied). Resolving a
system against its ancestors — emitting `inherit <slug>` and compiling the
parent chain into a `system_dict` — is its own phase spanning the declarative
front-end and the engine wiring, not just this router. Until then, a system that
relies on a parent's grammar/rules will report errors from `validate`.

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
  `request<T>` / `ApiError` helpers. The client already sends the auth cookie
  (`credentials: 'include'`), so no per-call auth wiring is needed.
- **Auth is already wired**: `frontend/src/lib/auth.svelte.ts` exposes the
  reactive `auth.user` / `auth.ready`. The systems routes gate on it — redirect
  to `/login` when signed out (mirroring `account/+page.svelte`) — and the
  `401 → signed-out` handling in `api.ts` already exists.

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
4. **Ownership** — **owner-scoped** to `app.db.User` via
   `app.auth.current_active_user`; all routes filter on `owner_id`.

## Phased delivery

Phase 0 (prerequisites): **complete** — async session, row models, `users`
table, and authentication (`current_active_user` + auth UI) are all in
`develop`. No blockers remain. Then:

1. Pydantic schemas (rows ⇄ spec) + `FormalSystem` create/list/get/delete +
   `validate`, all owner-scoped and async.
2. Child CRUD (sorts, productions, definitions, axioms, rules, line, brackets) +
   reorder.
3. `api.ts` client + TS types.
4. Svelte `/systems` list and `/systems/[id]` editor shell (gated on `auth.user`).
5. Section editors (one per part) + `bindings-editor`; live validation badge +
   read-only source panel.

The frontend phases depend only on the endpoints, not on the DB directly.

Each phase is independently testable: backend with pytest (round-trip a system
through the endpoints and assert it still compiles and checks a proof), frontend
with `svelte-check` and the run/verify skill against the live app.

## Testing

- **Backend:** the round-trip test (`tests/test_systems_store.py`) already
  exercises `spec_to_system` / `system_to_spec` against SQLite via a sync
  session. Endpoint tests hit `async def` routes; **`aiosqlite` is now a dev
  dependency** (added with the auth work), so a test `get_session` override
  points at `sqlite+aiosqlite://`, and `current_active_user` is overridden via
  `app.dependency_overrides` to inject a fixed test user (see
  `tests/test_auth.py` for the pattern). Create a system via the API, add parts,
  `validate`, and assert the assembled system compiles and checks a known proof;
  assert draft-invalid systems persist and report errors; assert another user's
  system is not reachable. Only the system-decomposition tables are
  SQLite-creatable (the `theorems` pgvector table is Postgres-only), so tests
  create just those tables — the round-trip test already does this via a
  `_SYSTEM_TABLES` list.
- **Frontend:** `npm run check`; drive `/systems/[id]` with the run skill to
  confirm an edited system validates end-to-end.
