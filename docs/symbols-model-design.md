# Design: unify sorts and productions into one symbol model

**Status:** proposal (no code yet) · **Branch:** `claude/unified-symbols-model`

> Follow-up to the object-CRUD work (PRs #28, #30). Best done now, before any
> data or frontend exists, because it restructures the storage.

## Motivation

Two problems, one root cause:

1. **The rename/delete footgun (review finding #2).** `production.sort` is a real
   foreign key, but a binding's `sort` and a definition's attach-point are stored
   as **free-text names**. Renaming a sort (or a production) updates the row but
   leaves those text references dangling, silently breaking a system that
   compiled a moment ago. There's no referential integrity where it matters most.
2. **Storage doesn't match the engine.** The engine has *one* namespace of
   patterns; a "sort" is just a `UnionPattern` and a "production" is a
   `StringPattern`/`RegexPattern` in that same namespace. The DB artificially
   splits them into `sorts` and `productions` tables, which is why references
   have to be strings in the first place.

Both dissolve if sorts and productions live in **one table of symbols**, with
every reference an FK into it.

## Background: sorts and productions are the same kind of thing

- A **sort** (`term`, `formula`) is a *category* of expression — a nonterminal.
  It is exactly *the union of the productions that build it*.
- A **production** (`variable`, `membership: s ∈ t`) is *one constructor* of some
  sort — a leaf (regex) or a composite (template).
- A **binding** names a category a metavariable ranges over: `s : term` names a
  sort; `x : variable` names a production. The engine resolves both with the same
  lookup — they're both just *named patterns*.

So the reference target is always "a named pattern," whether it's a broad union
(sort) or a single constructor (production). Storing one kind of reference as an
FK and the other as a string is the accident behind finding #2.

## The change: one `symbols` table + membership + reference FKs

Replace the `sorts` / `productions` / `production_bindings.sort` split with:

**`symbols`** — every named pattern in a system (a sort *or* a production):

| column | notes |
|---|---|
| `id` | uuid PK |
| `system_id` | FK → formal_systems |
| `position` | display order |
| `name` | unique per system |
| `kind` | `union` (= a sort) · `regex` · `template` (= productions) |
| `template` | for `template` kind, else null |
| `regex` | for `regex` kind, else null |

**`symbol_members`** — which symbols a union contains (replaces
`production.sort_id`, and also lets a union contain sub-unions — nested sorts,
which the engine already allows):

| column | notes |
|---|---|
| `union_id` | FK → symbols (the sort) |
| `member_id` | FK → symbols (a production or sub-union) |
| `position` | order within the union |

**Reference FKs** — every place that currently stores a sort/production *name*
becomes `symbol_id` FK → `symbols`:

- `*_binding.sort` (production/definition/axiom/rule bindings) → `symbol_id`
- `definition.sort` (attach-point) → `symbol_id`
- `line_type.logical_sort` → `symbol_id`

Brackets, line parts, axiom/rule text fields (`formula`, `deduction`,
`antecedents`) are unchanged.

### What maps to what

| Today | Becomes |
|---|---|
| `SortRow` | a `symbols` row with `kind=union` |
| `ProductionRow` (regex/composite) | a `symbols` row with `kind=regex`/`template` |
| `production.sort_id` | a `symbol_members` edge (production ∈ its sort's union) |
| `binding.sort` (text) | `binding.symbol_id` (FK) |
| `definition.sort` (text) | `definition.symbol_id` (FK) |

Rename any symbol → update one row; every FK reference follows automatically,
and lowering/serialization render the new name. Delete → the DB knows exactly
what references it, so we block with a clear message (or cascade with intent)
instead of silently orphaning. **Finding #2 is gone by construction**, for
sort *and* production renames alike.

## API stays familiar — projections over symbols

The unified storage does **not** force a more abstract API. Keep the current
surface by projecting:

- `GET /formal-systems/{id}` still returns separate `sorts` and `productions`
  lists — derived by filtering symbols (`kind=union` → sorts; leaf/composite →
  productions) and reading `symbol_members` for each production's sort.
- `POST /sorts` creates a `symbols` row (`kind=union`).
- `POST /productions` creates a leaf/composite symbol **and** a `symbol_members`
  edge to its sort's union.
- Bindings are still authored by **name** in the request (`{"var": "s", "sort":
  "term"}`); the server resolves the name to a `symbol_id`.

So the frontend still sees "sorts" and "productions" as separate editable lists;
only the storage underneath is unified and rename-safe.

## The one open decision: strict FK vs. draft tolerance

A binding references a symbol. Two ways to store it:

- **A — strict FK (recommended).** `symbol_id` NOT NULL, must reference an
  existing symbol; the name is always *derived* from that symbol. Referencing a
  not-yet-created sort → 400. Full integrity; rename is trivially safe. The
  editor smooths the "reference before it exists" case by creating the symbol on
  the fly when you type a new name.
- **B — name + nullable resolved FK.** Store the text name *and* a nullable
  `symbol_id` resolved when the symbol exists. Preserves free-form drafting
  (reference a sort before creating it), but reintroduces staleness unless we
  treat the FK as authoritative and the name as derived — at which point it's
  basically A with extra columns.

**Recommendation: A.** It's the only option that fully removes finding #2, and
the drafting concern is a UI affordance (auto-create the symbol), not a storage
problem.

## Mapping and migration

- `systems_mapping.py`: `spec_to_system` builds symbols + membership from a
  `SystemSpec`'s sorts/productions and resolves binding sort-names to symbol ids;
  `system_to_spec` reads them back. The `SystemSpec` shape (sorts as names,
  bindings as `(var, sort-name)`) is unchanged, so the declarative front-end and
  its round-trip tests are untouched — this is purely a storage-shape change
  behind the mapping.
- Migration: the merged schema created the `sorts`/`productions`/`*_binding`
  tables but **nothing is populated**, so Atlas can diff the new models into a
  clean replacement (drop the old sort/production tables, add `symbols` +
  `symbol_members`, repoint the FK columns). No data migration.

## Delivery plan

1. New models (`symbols`, `symbol_members`, reference FKs) in
   `app/db/systems.py` + Atlas migration.
2. `systems_mapping.py` rewritten to the symbol shape (round-trip test is the
   guard — it must stay byte-identical through `lower`).
3. CRUD layer: serializers + `system_parts.py` project sorts/productions from
   symbols and resolve binding names to FKs; API surface unchanged.
4. Add referential-integrity behaviour: rename propagates (free via FK);
   delete-when-referenced returns a clear 409 (or a `?cascade=true`), replacing
   the silent-orphan hazard — with tests that a rename keeps a system compiling.

## Non-goals (separate follow-ups)

- Multiple line types (still one per system).
- System inheritance resolution in validate/source.
