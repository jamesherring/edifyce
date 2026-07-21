# Persistence layer

SQLAlchemy 2.0 (async / asyncpg) models plus the schema-as-code migration setup.
This layer lives *beside* the engine: `website/logical/` stays a pure function of
its input, and these models are how the application tier remembers systems,
proofs, and (in future) searchable theorems. The `users` table is wired into the
auth routes (`app/auth/`); the system/proof/theorem tables are not yet used by
any route — they are the schema and the tooling to evolve it.

## Layout

| Path | What |
|---|---|
| `app/db/base.py` | Declarative `Base`, naming convention, id/timestamp mixins |
| `app/db/models.py` | Account + proof-surface ORM models |
| `app/db/systems.py` | Normalised formal-system decomposition (grammar/rules/definitions as flat rows) |
| `app/db/systems_mapping.py` | `spec_to_system` / `system_to_spec` round trip between the declarative `SystemSpec` and the rows |
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
  hardcodes the FK to a `user` table, so we repoint it at our `users` table. The
  schema is ready; the OAuth routers aren't mounted yet (they need per-provider
  client secrets).
- **`formal_systems`** — a system's identity + surrounding concerns: `name`,
  `slug`, optional `owner`, self-referential `inherits_from_id` (system
  inheritance), and `published_at`. Its grammar/rules/definitions are **not** a
  blob here — they live in the decomposition tables below.
- **`sorts`, `productions`, `production_bindings`, `line_types`, `line_parts`,
  `definitions`, `definition_bindings`, `axioms`, `axiom_bindings`, `rules`,
  `rule_antecedents`, `rule_bindings`, `notation_brackets`** — the **normalised
  system decomposition** (`systems.py`): one row per declaration, with real FKs
  and explicit `position` ordering. This makes every part of a system a
  first-class, indexable, searchable entity — "which systems define `⊆`", "which
  rules take two premises" — answerable in plain SQL with no recompile. The
  bridge to the engine is `systems_mapping`: rows → `SystemSpec` → lower to
  `.edi` → compile.
- **`proof_folders`** / **`proofs`** — the folder/proof tree, scoped to a system.
  Ordering is a plain `position`; publishing is a `published_at` timestamp. (The
  old app modelled both through a separate `FolderEntry`/`OrderedModel`; this
  flattens that indirection.)
- **`proof_references`** — the directed proof-to-proof dependency graph.
- **`theorems`** — *forward-looking, currently unpopulated.* Carries a JSONB
  `pattern` (structural, **pattern-based** search via a GIN index) and a pgvector
  `embedding` (semantic / **AI** search via an HNSW index). Both live in the same
  store and join back to the proof that establishes them.

Deliberate departure from the Django schema (and from #13's first draft): a
formal system is stored as **normalised rows**, not an opaque `source` text +
`compiled` JSONB blob — so it is queryable without recompiling. The engine, which
still treats a system as source it recompiles, is fed by rebuilding the source
from the rows on demand (`systems_mapping`). Proofs keep their `source`/`result`
(the latter a cached JSON snapshot of the checker output).

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
- **Logged-in Atlas for `diff`/`lint`.** Extension management (the `vector` type,
  `CREATE EXTENSION`) is a logged-in Atlas feature — run `atlas login` locally,
  and in CI the `ATLAS_TOKEN` secret authenticates the CLI. Without it Atlas
  errors with "extensions are available to logged-in users only". `atlas migrate
  apply` does not need it (it just runs the migration SQL).
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
