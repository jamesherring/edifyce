# `scripts/` — running Edifyce in a sandbox

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
| `dev` | Hot-reload mode: FastAPI **and** the Vite dev server (`:5173`). See the proofs caveat below. |
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

### `up` vs `dev` — and the proofs caveat

- **`up` (single server, recommended for inspection).** Builds the SPA and lets
  FastAPI serve it at `/` alongside the API on `:8000` — production fidelity, and
  the proofs pages load. Rebuild (`frontend build` / `up`) after frontend edits.
- **`dev` (hot reload).** FastAPI on `:8000`, Vite on `:5173` proxying API paths.
  Great for iterating on the **systems** UI. **The proofs pages are broken in this
  mode** — the Vite proxy doesn't forward `/proofs`, and even if it did, the
  `/proofs` prefix is shared by the JSON API and the SPA router, so navigations
  render raw JSON. This is a real app bug (root-caused in
  [`docs/editor-ux-audit.md`](../docs/editor-ux-audit.md), §0 — fix: namespace the
  API under `/api`). Until that lands, inspect proofs via `up`.

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
