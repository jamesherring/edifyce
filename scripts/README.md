# `scripts/` — running Edifyce in a sandbox

| Script | Does |
|---|---|
| `edifyce-dev` | Run the whole app (Postgres, migrations, API, SPA) with one command |
| `import_metamath.py` | Import a Metamath `.mm` database — system, proofs, line graphs, terms |
| `check_layering.py` | Assert that importing a corpus as a **spine** changes nothing about the import |

## `edifyce-dev` — run the whole app with one command

Edifyce isn't just `uvicorn`: anything auth-backed (systems, proofs, login) needs
**Postgres with pgvector**, and a fresh sandbox/CI container has neither a running
database nor the env the app expects. `edifyce-dev` encapsulates all of that so a
new session doesn't have to rediscover it.

```bash
scripts/edifyce-dev up      # Postgres + migrations + built SPA + API on one server (:8000)
scripts/edifyce-dev seed    # demo user + ZFC system + a verified proof (prints login + ids)
scripts/edifyce-dev status  # what's running
scripts/edifyce-dev down    # stop backend + frontend (database stays up)
```

That's the whole happy path: `up`, then open <http://127.0.0.1:8000/>, then
`seed` if you want data. Log in with the credentials `seed` prints
(`demo@example.com` / `demopass123` by default); the seeded system and proof ids
are written to `.edifyce-dev/seed.env`.

### Other subcommands

| Command | Does |
|---|---|
| `dev` | Hot-reload mode: FastAPI **and** the Vite dev server (`:5173`). |
| `migrate` | Apply the Atlas migrations to the dev database. |
| `db up \| down \| status` | Manage just Postgres. |
| `backend up \| down` | Manage just the API. |
| `frontend build \| dev \| down` | Build the SPA, or run/stop the Vite dev server. |
| `env` | Print `DATABASE_URL` and friends (handy for one-off `curl`/`psql`). |

Everything is idempotent — re-running `up` reuses whatever is already healthy —
and every default is overridable via `EDIFYCE_DEV_*` env vars (ports, data dir,
demo credentials); see the header of `scripts/edifyce-dev`.

Logs and pid files live in `.edifyce-dev/` (git-ignored): `backend.log`,
`frontend.log`, `seed.env`.

### Which database it uses

- **`DATABASE_URL` set** → the CLI uses it as-is (migrate + run against it, no
  local cluster), so `edifyce-dev` targets the same database a bare `uvicorn`
  would — the app reads `DATABASE_URL` first (`app/db/session.py`).
- **`DATABASE_URL` unset** → the CLI self-provisions an isolated local Postgres
  (its own data dir on `:5439`, separate from the Atlas dev cluster the web
  session runs on `:5433` for `atlas migrate diff`).

`POSTGRES_URL` (e.g. a shared Neon dev DB the app would otherwise fall back to)
is **not** adopted automatically — `seed` writes demo data, which shouldn't land
in a shared remote database without an explicit `DATABASE_URL` opt-in.

### `up` vs `dev`

- **`up` (single server, production fidelity).** Builds the SPA and lets FastAPI
  serve it at `/` alongside the API on `:8000`. Rebuild (`frontend build` / `up`)
  after frontend edits.
- **`dev` (hot reload).** FastAPI on `:8000`, Vite on `:5173` proxying the `/api`
  prefix. Use this while iterating on the UI. Both modes serve every page,
  including proofs: the whole JSON API lives under `/api`, so it never collides
  with an SPA route (the `/proofs` resource vs the `/proofs` page).

## Pitfalls this script papers over

If you ever need to do it by hand, these are the traps (all handled above):

1. **Postgres won't run as root.** `initdb`/`pg_ctl` refuse; drop to the
   `postgres` user (`runuser -u postgres -- …`) and give it an owned data dir.
2. **The cluster must be UTF-8.** A default `SQL_ASCII` database rejects the
   Unicode in verification results (asyncpg `UntranslatableCharacterError`), so
   proof-verify persists silently fail. `initdb --encoding=UTF8 --locale=C.UTF-8`.
3. **pgvector is required.** The schema does `CREATE EXTENSION vector`; enable it
   in the app database.
4. **Detached processes get reaped.** A plain `cmd &` from a tool-driven shell
   dies when the call returns. A `( cmd & )` subshell double-fork survives — that's
   how the backend outlives the command that started it.
5. **Don't `pkill -f "uvicorn app.main"`.** The pattern also matches the shell
   whose command line contains that string — you kill yourself. Stop servers by
   **port** (`fuser -k 8000/tcp`) or pid file instead.
6. **Auth cookie over http.** The session cookie is `Secure`; set
   `EDIFYCE_AUTH_COOKIE_SECURE=false` so `curl` keeps it over plain http
   (browsers treat `localhost` as secure regardless, so the UI is unaffected).

## Screenshots / driving the UI

To snapshot or interact with the running app, use the bundled Playwright helper
(it resolves the globally-installed Playwright and the pre-installed Chromium):

```bash
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/ home.png --full
```

For richer interaction (fill the editor, click Verify), write a one-off script
against that same helper's module-resolution preamble.

## `import_metamath.py` — load a Metamath database

Checks each theorem of a `.mm` file with Edifyce's own kernel, in declaration
order, and stores what checked: one formal system, one proof per theorem, and the
proof's structure — its lines, the justification edges between them, and their
formulas interned into the system's shared term graph. See
`docs/metamath-import-roadmap.md` §1.3.

```bash
scripts/edifyce-dev db up && scripts/edifyce-dev migrate
curl -L -o set.mm https://raw.githubusercontent.com/metamath/set.mm/develop/set.mm

DATABASE_URL="$(scripts/edifyce-dev env | sed -n 's/^DATABASE_URL=\([^ ]*\).*/\1/p')" \
  uv run python scripts/import_metamath.py set.mm --limit 1000
```

`--limit` takes the first N theorems in file order; leave it off for the whole
corpus (slow, and see the roadmap's note on the rebuild cost). `--batch` sets how
often the run commits and empties the identity map, which is what keeps a long
import's memory flat.

`--setmm-layers` stores the corpus as a **spine of systems** — propositional
calculus, then first-order logic, then ZF set theory — rather than one, and the
run then prints a per-layer breakdown. Off by default, like `--setmm-overrides`
and for the same reason: a layer plan names one library's own section titles. See
the relationships roadmap, §7.2.

## `check_layering.py` — does layering change the import?

It must not. A layer plan says how a corpus is *filed*, never how it is
*checked*, so the same file imported flat and imported as a spine has to agree on
the verdicts, the promoted library, the derived rows — and on the **byte-identical
proof sources**, which is the whole of "preserving references": a citation is
stored as a bare label and resolves through the spine, so splitting the corpus
must not rewrite one of them.

```bash
uv run python scripts/check_layering.py set.mm --limit 2676
```

Needs no database — it imports twice into throwaway in-memory SQLite and diffs —
and exits non-zero on any difference, naming each one. `2676` is the milestone
slice: the smallest at which all three of `set.mm`'s layers hold theorems. Budget
about a minute per run.

`tests/test_metamath_layered_store.py` pins the same equality on a fixture, which
proves the mechanism; this is the corpus half, and running it is what found the
one thing the fixture could not (relationships roadmap, §8's D4).

The imported system and proofs are **ownerless**, so they do not appear in the
app and cannot be verified through it — deliberately, because a stored system
carries no promoted theorems yet and re-checking an imported proof against it
would fail and overwrite the imported structure. See the roadmap, §1.3 and §3.2.

After a run the corpus is queryable in plain SQL, with nothing recompiled:

```sql
-- the theorems these proofs lean on most
select rule, count(*) from proof_lines where rule is not null
group by rule order by 2 desc limit 10;
```

## Running the API tests against Postgres

The API suites use a throwaway SQLite database by default — fast and setup-free.
Point them at a real Postgres to exercise the dialect the deployment actually
runs on:

```bash
scripts/edifyce-dev db up
psql "$(scripts/edifyce-dev env | sed -n 's/^DATABASE_URL=\([^ ]*\).*/\1/p')" \
  -c "create database edifyce_test"

EDIFYCE_TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:5439/edifyce_test" \
  uv run pytest tests/test_proofs_api.py tests/test_systems_api.py \
                tests/test_system_parts_api.py -p no:randomly
```

Worth doing because SQLite hides what the real database enforces: it creates a
table whose foreign-key target does not exist, ignores `ON DELETE` without a
per-connection pragma, has no advisory locks, and stores UUID/JSONB as text. It
also runs the recursive CTE the term-graph sweep depends on
(`app/db/terms_mapping.prefetch_terms`) against the planner that will really see
it. Use a **separate database** — the suites drop and recreate every table.

See `tests/database.py`; it needs the dev group's `psycopg` (the app itself only
ever uses asyncpg).
