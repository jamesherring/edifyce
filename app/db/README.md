# Persistence layer

SQLAlchemy 2.0 (async / asyncpg) models plus the schema-as-code migration setup.
This layer lives *beside* the engine: `website/logical/` stays a pure function of
its input, and these models are how the application tier remembers systems,
proofs, and (in future) searchable theorems. Nothing here is wired into the API
routes yet — this is the schema and the tooling to evolve it.

## Layout

| Path | What |
|---|---|
| `app/db/base.py` | Declarative `Base`, naming convention, id/timestamp mixins |
| `app/db/models.py` | The ORM models (the schema) |
| `app/db/session.py` | Lazy async engine + `get_session` FastAPI dependency |
| `tools/atlas/schema.py` | Single-file schema entrypoint Atlas loads the models through |
| `atlas.hcl` | Atlas config (env `local`) |
| `migrations/` | Versioned SQL migrations + `atlas.sum` |

## The schema

Modernised from the original Django app (`website/models.py` on `main`):

- **`users`** — collapses Django's `auth.User` + `Profile`. Nullable
  `hashed_password` (null = external/OAuth auth). Auth itself isn't built yet.
- **`formal_systems`** — Edifyce `source`, optional `owner`, self-referential
  `inherits_from_id` (system inheritance), a cached `compiled` JSONB snapshot,
  and `published_at`.
- **`proof_folders`** / **`proofs`** — the folder/proof tree, scoped to a system.
  Ordering is a plain `position`; publishing is a `published_at` timestamp. (The
  old app modelled both through a separate `FolderEntry`/`OrderedModel`; this
  flattens that indirection.)
- **`proof_references`** — the directed proof-to-proof dependency graph.
- **`theorems`** — *forward-looking, currently unpopulated.* Carries a JSONB
  `pattern` (structural, **pattern-based** search via a GIN index) and a pgvector
  `embedding` (semantic / **AI** search via an HNSW index). Both live in the same
  store and join back to the proof that establishes them.

Deliberate departure from the Django schema: the old app pickled compiled
`FormalSystem`/`Proof` objects into the DB. The rebuilt engine recompiles from
source, so we store the **source text** plus optional cached **JSON** snapshots
(`compiled` / `result`) instead — portable and not fragile across code changes.

The embedding dimension is `EMBEDDING_DIMENSIONS` in `models.py` (default 1536).
Match it to the embedding model you deploy (e.g. Voyage voyage-3 = 1024, OpenAI
text-embedding-3-small = 1536). Changing it is a migration.

## Migrations (Atlas)

The models are the source of truth. Atlas diffs them against the recorded
migrations on a throwaway **dev database** and writes new migration SQL.

```bash
# Plan a new migration after changing the models:
atlas migrate diff <name> --env local

# Apply migrations to a real database:
atlas migrate apply --env local --url "$DATABASE_URL"

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
- **The `CREATE EXTENSION "vector"` line** at the top of the initial migration was
  added by hand — Atlas doesn't always emit extension creation. If you regenerate
  the first migration, re-add it and run `atlas migrate hash`.

## Runtime

`session.py` is lazy: importing it never opens a connection, and the app boots
fine with no `DATABASE_URL`. Set `DATABASE_URL` to the Neon **pooled** connection
string (`-pooler` host) — the engine uses `NullPool` so Neon's PgBouncer owns
pooling, which is what keeps Vercel serverless functions from exhausting
connections.
