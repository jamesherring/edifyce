// Atlas configuration — schema-as-code for the Edifyce database.
//
// The desired schema is loaded straight from the SQLAlchemy models via the
// atlas-provider-sqlalchemy program (see tools/atlas/schema.py). Atlas diffs
// that against the current migration state on a throwaway "dev" database to plan
// new migrations.
//
// Usage:
//   atlas migrate diff <name> --env local   # plan a new migration from the models
//   atlas migrate apply --env local --url "$DATABASE_URL"   # apply to a real DB
//   atlas migrate lint --env local          # CI: check migrations for safety
//
// The dev database MUST have the pgvector extension available (the schema issues
// CREATE EXTENSION vector). Override the default with ATLAS_DEV_URL — e.g. a Neon
// dev branch, or a local Postgres that has pgvector installed.

data "external_schema" "sqlalchemy" {
  program = [
    "sh", "-c",
    "PYTHONPATH=. uv run atlas-provider-sqlalchemy --path ./tools/atlas --dialect postgresql",
  ]
}

env "local" {
  src = data.external_schema.sqlalchemy.url

  // Atlas's built-in pgvector image so the dev DB has the extension (the
  // "pgvector" driver resolves to pgvector/pgvector:pg16); override for CI/Neon.
  dev = getenv("ATLAS_DEV_URL") != "" ? getenv("ATLAS_DEV_URL") : "docker://pgvector/pg16/dev"

  migration {
    dir = "file://migrations"
  }

  format {
    migrate {
      diff = "{{ sql . \"  \" }}"
    }
  }
}
