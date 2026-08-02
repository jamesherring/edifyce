# Persistence layer

SQLAlchemy 2.0 (async / asyncpg) models plus the schema-as-code migration setup.
This layer lives *beside* the engine: `website/logical/` stays a pure function of
its input, and these models are how the application tier remembers systems,
proofs, and (in future) searchable theorems. The `users`, system-decomposition,
proof, term and proof-line tables are all wired into routes (`app/auth/`,
`app/routers/`); `theorems` is not yet — it is the schema and the tooling to
evolve it.

## Layout

| Path | What |
|---|---|
| `app/db/base.py` | Declarative `Base`, naming convention, id/timestamp mixins |
| `app/db/models.py` | Account + proof-surface ORM models |
| `app/db/systems.py` | Normalised formal-system decomposition (grammar/rules/definitions as flat rows) |
| `app/db/systems_mapping.py` | `spec_to_system` / `system_to_spec` round trip between the declarative `SystemSpec` and the rows, and `effective_spec`, which layers an inheritance chain into one |
| `app/db/descriptions.py` | What a system says about the labels it names: prose, titles, and authorship |
| `app/db/descriptions_mapping.py` | Store/load a label's description and its `(Contributed by …)` clauses |
| `app/db/notations_mapping.py` | Store/load a system's named notations, and render a stored term through one from rows alone |
| `app/db/side_conditions.py` | Definition provisos as the kernel side-condition algebra, stored as rows |
| `app/db/side_conditions_mapping.py` | Parse/render a `where` proviso ↔ side-condition rows |
| `app/db/terms.py` | Term graph: kernel-term DAGs as shared `terms` / `term_children` rows |
| `app/db/terms_mapping.py` | `store_term` / `prefetch_terms` round trip between kernel `Term`s and the rows. A stored constructor resolves through the **sort unions**, not `context.variables`: that namespace is shared with lines, axioms and line parts, and a name declared twice resolves to the later one |
| `app/db/promoted_theorems.py` | The citable library: proved and imported theorems as rows, resolved by label |
| `app/db/promoted_theorems_mapping.py` | `store_theorem` / `load_theorems`: the library round trip |
| `app/db/schema_terms.py` | `store_schema_terms` / `load_schema_terms`: a rule's schema templates as composed kernel terms, so a build need not re-parse them |
| `app/db/definition_terms.py` | `store_definition_terms` / `load_definition_terms`: the same for a definition's two surface forms |
| `app/db/proof_lines.py` | Proof structure: a checked proof's lines + the justification edges between them |
| `app/db/proofs_mapping.py` | `store_proof_lines`: project a checked engine `Proof` into those rows |
| `app/db/metamath_store.py` | `import_corpus`: walk a Metamath `.mm` database and store the system, its proofs, and their line graphs |
| `app/db/session.py` | Lazy async engine + `get_session` FastAPI dependency |
| `tools/atlas/schema.py` | Single-file schema entrypoint Atlas loads the models through |
| `atlas.hcl` | Atlas config (env `local`) |
| `migrations/` | Versioned SQL migrations + `atlas.sum` |

## The schema

Modernised from the original Django app (`website/models.py` on `main`):

- **`users`** — collapses Django's `auth.User` + `Profile`, built on
  fastapi-users' `SQLAlchemyBaseUserTableUUID` (contributes `email`,
  `hashed_password`, `is_active`, `is_superuser`, `is_verified`). Wired into the
  auth routes in `app/auth/` (register / login / logout / `users/me`).
- **`oauth_accounts`** — linked social logins (fastapi-users'
  `SQLAlchemyBaseOAuthAccountTableUUID`); one user, many providers. The library
  hardcodes the FK to a `user` table, so we repoint it at our `users` table.
  Populated by the GitHub/Google social-login routers in `app/auth/oauth.py`
  (enabled per provider when its client id/secret are set).
- **`formal_systems`** — a system's identity + surrounding concerns: `name`,
  `slug`, optional `owner`, self-referential `inherits_from_id` (system
  inheritance), and `published_at`. Its grammar/rules/definitions are **not** a
  blob here — they live in the decomposition tables below.

  **`inherits_from_id` is resolved.** A system's rows are its *own* parts; what
  it is *built from* is its ancestors' parts followed by them
  (`effective_spec` → `declarative.layered_spec`), so a child adding `∀x φ` to
  `formula` says `sort="formula"` and lands in the union its ancestor declared.
  A name may be declared once down a chain — a child redeclaring an ancestor's
  `→` would change what every theorem inherited from it means — and a parent
  must be **published** before a child may build on it, since publishing is what
  freezes the grammar the descendants' proofs are checked against. A layer also
  gets a symbol row for every sort it merely *mentions* (`⊆` is a `formula` over
  `term`, neither of which ZFC declares), so no row ever references another
  system's namespace. See
  [`docs/system-relationships-roadmap.md`](../../docs/system-relationships-roadmap.md).
- **`sorts`, `productions`, `production_bindings`, `production_binding_scopes`,
  `line_types`, `line_parts`,
  `definitions`, `definition_bindings`, `axioms`, `axiom_bindings`, `rules`,
  `rule_antecedents`, `rule_bindings`, `notation_brackets`** — the **normalised
  system decomposition** (`systems.py`): one row per declaration, with real FKs
  and explicit `position` ordering. This makes every part of a system a
  first-class, indexable, searchable entity — "which systems define `⊆`", "which
  rules take two premises" — answerable in plain SQL with no recompile. The
  bridge to the engine is `systems_mapping`: rows → `SystemSpec` →
  `FormalSystem` (`declarative.build_system`). `production_binding_scopes` is
  the odd one out in referencing `production_bindings` at both ends: it records
  which sibling slot a binder scopes over (the `phi` of `∀x.phi`), which is what
  lets a definition's `fresh` clause be inferred rather than declared.

  `rules` and `rule_antecedents` also carry **schema terms**
  (`schema_terms.py`): a rule's deduction, antecedents and subproof lines are
  templates, and the build parses each against the whole grammar to get the
  nested term the checker unifies with. That parse is roughly half of building a
  system and gives the same answer every time, so a verify stores what it
  composed (`rules.deduction_term_id` and friends → `terms`) and the next one
  reads it. Unlike `proof_lines`, these rows are a **cache and not a record**:
  `rules.schema_digest` fingerprints the grammar and the rule's own templates and
  bindings, and a row whose digest no longer matches is simply not read — so a
  part edit needs no invalidation sweep, and a stale row is inert rather than
  believed. The digest also covers which grammar names a line, part or axiom
  *shadows* in the build namespace, because a rename onto a production's name
  changes nothing a template composes to and so would otherwise leave the rows
  looking current. (It is not what makes such a system *correct* — a collision
  present from the outset matches the digest at both ends. `TermGraph` resolves a
  stored constructor through the sort unions rather than that namespace, which is
  what settles it either way.) The FKs into `terms` are `ON DELETE SET NULL`:
  losing a term must cost a re-compose, never a rule. And a NULL term id is a
  *miss* even under a matching digest — never "this template composes to
  nothing" — because the same NULL is what a deleted term, and a slot that
  resolved to a declared pattern instead of a composed one, both leave behind.

  `definitions` carries the same kind of cache for its two surface forms
  (`definition_terms.py`): `higher_term_id` / `lower_term_id` hold the terms the
  build parsed them into, under `definitions.term_digest`. Two differences from a
  rule's, both forced by what a definition is. The digest is **per system**, not
  per row — a definition's forms are parsed against the grammar as extended by the
  definitions before it, and the slot key is a spec position that an insertion
  moves — so every row of a system carries one value. And the stored term stops
  **before binder placement**: `bind_scoped` binds ground leaves sitting in binder
  slots, so storing the finished `Definition.lower` would rebuild with no binders
  at all and quietly drop the definition's capture-avoidance proviso.
  `definition_fresh.term_id` rides the same digest, holding the leaf a declared
  binder's name denotes — the fallback an unfold uses when it names no binder. A
  row exists only for a *declared* binder and a declared binder always has a
  default, so a NULL there **is** a hole and the currentness check says so; what
  is not a hole is a definition with no `fresh` rows at all, which is what a
  binder the grammar places leaves behind.
- **`promoted_theorems`, `promoted_theorem_premises`,
  `promoted_theorem_bindings`** — a system's **citable library**
  (`promoted_theorems.py`): results it has proved, or imported from a corpus, and
  registered for schematic reuse. Separate from `rules` because the two differ in
  *scale* and therefore in how they are read: a system's primitives are a handful
  and are built with it, while an imported library is 49,000 entries and is
  resolved **by label, on demand** — a verify reads the citations off a proof's
  own lines and promotes only those. Both kinds of an imported library live here
  (a Metamath logical `$a` as much as a `$p`); `primitive` records which, so
  "what does this system assume?" is one query while checking stays indifferent.
  Statement and premise terms are cached beside their text under `schema_digest`,
  on the same contract as the rule schema terms above. A premise's `label` is how
  the theorem's **own** proof cites it, and the only way to reach it — a bare
  hypothesis citable by anyone would prove anything — with `proofs.theorem_id`
  saying which proof that is. `proved_by_id` points the other way and means
  something else: which proof's *standing* warrants the entry, set by
  `POST /proofs/{id}/promote` and left NULL by an import, whose warrant is the
  corpus. That is what lets an edit retire a locally-proved entry without a
  grammar change taking a 49,000-theorem import down with it.
- **`notation_pieces`** — how a system's terms may be *read*, as against the
  grammar they are written in. One row per render step of one constructor in one
  named notation (`unicode`, `latex`), the same `("lit", …)` / `("slot", …)` shape
  `Constructor.pieces` holds — steps rather than a template string, because no
  delimiter is safe (set.mm makes braces notation). A stored notation names
  *every* constructor: a reader has rows and no grammar, so anything unnamed has
  no source template to fall back to. `render_stored` folds it over the term rows,
  which is why showing a proof in a notation costs a query and not a system
  rebuild. Derived where the source is — a Metamath import reads the file's `$t`
  block — never re-derived on the read path. **Read** through the inheritance
  chain (a child inherits its ancestors' notations and overrides them per
  constructor, as its grammar layers on theirs); **stored** against the one system
  it was derived for.
- **`label_descriptions`** / **`label_attributions`** — what a system records
  about the labels it names. Keyed by `(system, label)` rather than by an FK into
  the thing described, because one label lands in one of four row types depending
  on what the importer made of its statement — a production (a syntax `$a`), a
  definition (`df-un`), a primitive theorem (`ax-ext`), or a proof and its theorem
  (a `$p`). Four description columns would be four migrations for one concept.
  `title` is the prose's first sentence, which is a title in all but name:
  Metamath declares none. Attributions are rows, not a string, because an
  authorship record is asked aggregate questions — set.mm credits 131 people
  across 60,661 clauses — and every field is verbatim (the corpus misspells four
  kinds and malforms 22 dates, so `dated` is a string and `kind` is not an enum).
  Distinct from `proofs.title`/`proofs.description`, which are the proof's own
  and editable. An import copies the *title* across — short, and a listing wants
  it — and leaves `proofs.description` alone, because `description` rides on every
  `ProofSummary` and a corpus comment runs to paragraphs. The prose is read from
  here, on the single proof.
- **`side_conditions`** — a definition's proviso (`where` clause) stored as the
  kernel's closed side-condition algebra (`side_conditions.py`) rather than an
  opaque string: one row per algebra node (`occurs`/`equal`/`disjoint`/`atom`/
  `member` leaves referencing the definition's metavariables + an optional sort
  FK; `not`/`and`/`or` combinators), a tree via `parent_id`. So "which definitions
  have a disjoint-variable proviso" or "which constrain the `setvar` sort" are
  plain SQL. `side_conditions_mapping` parses the `where` surface syntax to rows
  and renders it back (the grammar mirrors the engine's `side_condition_syntax`,
  cross-checked by a test so the two can't drift).
- **`proof_folders`** / **`proofs`** — the folder/proof tree, scoped to a system.
  Ordering is a plain `position`; publishing is a `published_at` timestamp. (The
  old app modelled both through a separate `FolderEntry`/`OrderedModel`; this
  flattens that indirection.)
- **`proof_references`** — the directed proof-to-proof dependency graph (an
  association object, `ProofReference`): each edge carries the citation `alias`
  the citing proof uses to name the lemma in its source (`[alias.line]`) and a
  display `position`. The graph is kept acyclic; the API rejects an edge that
  would close a cycle. This is the only place the dependency graph lives — the
  engine tracks no proof-to-proof edges of its own.
- **`proof_lines`** / **`proof_line_antecedents`** — the **proof decomposition**
  (`proof_lines.py`): what `proofs.source` says, as structure. One row per source
  line carrying what the checker determined about it (line type, behaviour,
  citation `number`, verdict, the scope it opens or sits in) and, for a
  formula-bearing line, a `term_id` into the `terms` graph below — so a proof's
  statements are the *same* interned kernel-term DAG the theorem search indexes,
  and "which proofs state a membership formula" is one query rather than a
  recompile. `proof_line_antecedents` is the justification graph: the lines a line
  was actually derived from, as edges rather than as a reference string to
  re-parse (a bare `[MP]` records the two lines the checker *inferred*). Finer
  than `proof_references`, which is the proof-to-proof edge; a citation reaching
  into a cited lemma is recorded by that proof's id and citation number, since the
  lemma owns its own line rows. Written by `proofs_mapping.store_proof_lines` when
  a proof is verified or published, and **dropped whenever `proofs.valid` is** —
  the snapshot is derived from a check, so it never outlives one. That includes
  editing the *system*: a part edit changes the grammar a proof was checked
  against, so it invalidates every proof in the system
  (`proofs_mapping.discard_system_checks`, called from every part route; a
  published system is frozen, so this only ever runs for a draft). Read back at
  `GET /api/proofs/{id}/structure` — and by **verify**, which reads both the
  proof's *own* lines and those of every lemma it cites from here rather than
  parsing anything (`proofs_mapping.load_proof_for_check` and
  `load_proof_lines`). A proof checked once never has its text parsed again;
  `proofs.source` is parsed only when there are no rows, which is exactly when
  there is nothing to trust. That is what makes these rows load-bearing rather
  than a render, and why the invalidation above is now soundness-critical rather
  than merely tidy. What the rows never supply is a *verdict*: numbering, scope
  and justification are re-derived on every check, so a row says what a line
  states and never whether it stands. See
  [`docs/verification-from-rows.md`](../../docs/verification-from-rows.md).
- **`terms`** / **`term_children`** — the **term graph** (`terms.py`): kernel
  term DAGs stored as shared rows, interned per system by a structural
  `digest` so equal subterms are stored once. This is the structural-search
  substrate for theorems (PR #23's follow-up replacing the old JSONB
  `pattern` blob): "top constructor is `implication`", "mentions `∈`
  anywhere" (a recursive CTE over `term_children`), "uses defined notation
  `x ⊆ y`" (the `defined` kind joins against `definitions.higher`) — all in
  plain SQL. The bridge to live kernel terms is `terms_mapping`
  (`store_term` / `prefetch_terms`). Each row also carries an **`alpha_digest`**
  (`terms_mapping.alpha_digest`): a second structural hash that numbers free
  variables by first occurrence, so it is invariant under consistent renaming
  while `digest` is not. It is the "same statement up to variable names" search
  key — `a in b` and `y in z` share an `alpha_digest` but not a `digest`, while
  `a in a` (a shared variable) keeps its own — non-unique (many exact rows per
  alpha class), indexed by `(formal_system_id, alpha_digest)`. It does not cover
  partial-pattern / goal-directed search (that is a matching problem for a
  discrimination-tree index plus a kernel unification confirm, not a whole-term
  hash).
- **`theorems`** — *forward-looking, currently unpopulated.* Points at the
  statement's root in the term graph (`statement_term_id`) for structural,
  **pattern-based** search, and carries a pgvector `embedding` (semantic /
  **AI** search via an HNSW index). Both live in the same store and join back
  to the proof that establishes them.

Deliberate departure from the Django schema (and from #13's first draft): a
formal system is stored as **normalised rows**, not an opaque `source` text +
`compiled` JSONB blob — so it is queryable without recompiling. The engine, which
still treats a system as source it recompiles, is fed by rebuilding the source
from the rows on demand (`systems_mapping`). Proofs keep their `source` — a proof
*is* the text its author wrote — and their `result`, a cached JSON snapshot of the
checker output for the editor to render; the structure behind that check lives in
`proof_lines` (above), where it is queryable.

The embedding dimension is `EMBEDDING_DIMENSIONS` in `models.py` (default 1536).
Match it to the embedding model you deploy (e.g. Voyage voyage-3 = 1024, OpenAI
text-embedding-3-small = 1536). Changing it is a migration.

## Migrations (Atlas)

The models are the source of truth. Atlas diffs them against the recorded
migrations on a throwaway **dev database** and writes new migration SQL.

```bash
# Plan a new migration after changing the models:
atlas migrate diff <name> --env local

# Apply migrations to a real database (see the Neon note below for the URL):
atlas migrate apply --dir "file://migrations" --url "$MIGRATE_URL"

# CI safety check (destructive-change linting):
atlas migrate lint --env local
```

Requirements / gotchas:

- **Official Atlas binary.** `atlas.hcl` uses `data "external_schema"` to load the
  SQLAlchemy models via `atlas-provider-sqlalchemy` (a dev dependency). That data
  source needs the official Atlas distribution — the OSS "community" build does
  not support it. Install: `curl -sSf https://atlasgo.sh | sh`.
- **Dev database needs pgvector.** The schema issues `CREATE EXTENSION vector`, so
  the `ATLAS_DEV_URL` database must have pgvector available. `atlas.hcl` defaults
  to the `pgvector/pgvector` Docker image; override `ATLAS_DEV_URL` for a local
  Postgres or a Neon dev branch.
- **Logged-in Atlas for `diff`/`lint`/`apply`.** Extension management (the
  `vector` type, `CREATE EXTENSION`) is a logged-in Atlas feature — run `atlas
  login` locally, and in CI the `ATLAS_TOKEN` secret authenticates the CLI.
  Without it Atlas errors with "extensions are available to logged-in users
  only". `atlas migrate apply` now needs it too: the `unify_symbols` migration
  carries **pre-migration checks** (a txtar `checks.sql` that asserts the tables
  it retires are empty before dropping them), and those run at apply time under
  the same logged-in gate — so both migration workflows pass the token.
- **The `CREATE EXTENSION "vector"` line** at the top of the initial migration was
  added by hand, because that baseline was generated by an *unauthenticated* Atlas
  (which omits extension DDL). A logged-in Atlas emits it automatically, so newly
  generated migrations don't need the hand-add — but if you ever regenerate that
  first migration without login, re-add it and run `atlas migrate hash`.
- **Applying to Neon (verified against a real Vercel-provisioned DB).** Two
  Neon-specific adjustments to the apply URL (`$MIGRATE_URL` above), neither of
  which the pooled runtime `DATABASE_URL` satisfies:
  - **Use the direct (non-pooled) endpoint** — the `DATABASE_URL_UNPOOLED` /
    `POSTGRES_URL_NON_POOLING` var, *not* the `-pooler` host. Atlas takes a
    session advisory lock and runs DDL in a transaction; PgBouncer's transaction
    pooling breaks both.
  - **Scope to the `public` schema** by appending `&search_path=public`. Vercel's
    Neon integration provisions a `neon_auth` schema; pointed at the whole
    database, Atlas reads that (and its own revision schema) as drift and refuses
    with "connected database is not clean". The migration only touches `public`.

  So in practice: `MIGRATE_URL="$DATABASE_URL_UNPOOLED&search_path=public"`.

## CI/CD

Migrations are not applied by hand in normal operation — two workflows own it,
split by event so the apply never surfaces as a skipped check on PRs:

- **`.github/workflows/migrations.yml` — on a pull request** (touching the models,
  `migrations/`, the Atlas config, or `uv.lock`): `atlas migrate validate`
  (checksum integrity), a **drift check** that fails if the models have changed
  without a matching migration (`atlas migrate diff` must be a no-op), and `atlas
  migrate lint --git-base` for unsafe changes across every migration the PR adds.
  This runs against a throwaway `pgvector/pgvector` service container, so no Neon
  branch is touched. Needs the `ATLAS_TOKEN` secret (logged-in Atlas — see the
  pgvector note above).
- **`.github/workflows/apply-migrations.yml` — on push to `develop`** → `atlas
  migrate apply` to the Neon **develop** branch (Vercel Preview). **On push to
  `main`** → apply to the Neon **main** branch (Vercel Production). The target
  URLs live in the `NEON_DEVELOP_MIGRATE_URL` / `NEON_MAIN_MIGRATE_URL` GitHub
  secrets, each already the unpooled endpoint with `&search_path=public`.

So the day-to-day loop is: change the models → `atlas migrate diff <name> --env
local` → commit the generated SQL → open a PR. CI proves it's in sync and safe;
merging applies it. The manual `atlas migrate apply` above is only for local
databases and one-off recovery.

**Deploy ordering (know this before wiring the DB into routes).** GitHub Actions
applies the migration while Vercel independently builds the new code off the same
push — they race. That's harmless today because nothing at runtime touches the
DB and every migration so far is purely additive. Once routes depend on the
schema, keep migrations **backward-compatible with the currently-deployed code**
(expand/contract: add columns/tables before the code needs them; drop only after
the code that used them is gone) so either order is safe.

## Runtime

`session.py` is lazy: importing it never opens a connection, and the app boots
fine with no `DATABASE_URL`. Set `DATABASE_URL` to the Neon **pooled** connection
string (`-pooler` host) — the engine uses `NullPool` so Neon's PgBouncer owns
pooling, which is what keeps Vercel serverless functions from exhausting
connections.
