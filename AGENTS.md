# AGENTS.md

Guidance for AI coding agents (and humans skimming for orientation) working in
this repository. For end-user setup and API usage, see [README.md](README.md).

## What Edifyce is

Edifyce is a **formal proof assistant**. Users define a *formal system* — its
line types, notation, and inference rules — in Edifyce source code, then write
*proofs* in that system and have them mechanically verified, line by line.

The project began as a server-rendered Django site and has been rebuilt as:

- a stateless **FastAPI** backend (`app/`) that wraps the existing proof engine, and
- a standalone **SvelteKit** single-page frontend (`frontend/`) that talks to it.

The proof engine itself (`website/logical/`) predates the migration and is the
heart of the project. Treat it as the source of truth; the API layer is a thin
adapter over it, and the frontend is a thin client over the API.

## Layout

| Path | What lives here |
|---|---|
| `app/` | FastAPI application. `main.py` = routes (and static-SPA serving); `schemas.py` = Pydantic request/response models. Thin — it delegates to the engine. |
| `app/auth/` | Email/password authentication (fastapi-users): httponly-cookie + JWT backend, user manager, and the register/login/logout/`users` routers mounted in `main.py`. Needs `DATABASE_URL`. |
| `app/db/` | Persistence layer: SQLAlchemy 2.0 (async) models + session wiring. Beside the engine, not inside it. The `users` table is wired into `app/auth/`; the rest is not yet used by routes. See `app/db/README.md`. |
| `migrations/` | Atlas versioned SQL migrations (`atlas.sum`). Config in `atlas.hcl`; models loaded via `tools/atlas/schema.py`. |
| `website/logical/` | The proof engine. This is where the real logic is. |
| `website/logical/compiler.py` | Parses Edifyce source into a `FormalSystem` (AST → system). |
| `website/logical/formal_system/` | `FormalSystem`, `Proof`, `ProofLine`, line types, inference rules — the compiled system and proof-checking. |
| `website/logical/matching/` | Pattern-matching engine (patterns, conditions, contexts, matches) that inference rules are checked against. |
| `frontend/` | SvelteKit (Svelte 5) SPA styled with Tailwind CSS v4 + shadcn-svelte. Static build talks to the API. `src/routes/` = pages, `src/lib/api.ts` = the API client. See `frontend/README.md`. |
| `tests/` | pytest suite covering the API, compiler, engine, and matching. |
| `deprecated/` | Legacy Django frontend, kept **only** as reference. Superseded by `frontend/`. Not imported or served. Don't wire it back in. |

The two public entry points into the engine are `compiler.compile(code)` and
`FormalSystem.parse(text)` — start there when tracing behaviour.

## Working in this repo

The **backend** requires **Python 3.13+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                      # install deps (incl. dev group)
uv run pytest                                # run the test suite
uv run uvicorn app.main:app --reload         # run the dev server (docs at /docs)
```

The **frontend** requires **Node 20+** and lives in `frontend/`.

```bash
cd frontend
npm install
npm run dev            # dev server on :5173, proxies API paths to the backend on :8000
npm run build          # static bundle written to frontend/build
npm run check          # svelte-check type checking
```

Run both dev servers together: the Vite dev server proxies the API paths
(`/health`, `/formal-systems`, `/proofs`) to `uvicorn` on :8000, so no CORS or
extra config is needed. Alternatively, after `npm run build` the FastAPI app
serves the static bundle from `/`, so a single `uvicorn` process serves both the
API and the UI (see the static-frontend block at the bottom of `app/main.py`).

- **Run the tests before and after any change to the engine.** The engine is
  large, largely untyped in its internals, and interconnected — tests are the
  safety net. CI runs `uv run pytest -v` on every PR.
- **Keep the API layer thin.** New behaviour belongs in `website/logical/`;
  `app/` should stay a translation layer between HTTP/Pydantic and the engine.
- **Keep the frontend a thin client.** It renders and calls the API; proof and
  compile logic stays in the engine, not the browser. The API contract lives in
  `app/schemas.py` (backend) and `frontend/src/lib/api.ts` (client) — change both
  together.
- **Preserve public engine signatures** unless you intend to update every caller
  and test. `matching/__init__.py` deliberately re-exports the old flat API after
  a package split — respect that contract.
- **Prefer dataclasses and explicit `raise`s** over dict-records and bare
  `assert`s. Recent history has been steadily moving the codebase that way; match
  the direction it's already going.
- **Type new code fully.** The engine's older internals are largely untyped, but
  all new code — and any function you meaningfully rewrite — must carry parameter
  and return-type annotations (including `-> None`). Use `from __future__ import
  annotations` and a `TYPE_CHECKING` block for engine types to keep annotations
  runtime-free and avoid import cycles. See `website/logical/kernel/terms.py` for
  the pattern to follow.
- **Lean on types; fail loudly.** When an object's type is known, access its
  attributes directly (`obj.attr`) rather than `getattr(obj, "attr", default)`.
  A defaulting `getattr` hides both the type and a genuine bug — a missing
  attribute should raise, not silently fall back. If some instances of a type may
  or may not carry a field, that field belongs in the class as a declared
  attribute with a default (so every instance has it and callers stay typed), not
  as something attached ad hoc and probed with `getattr`. Reserve `getattr`/
  `setattr` for genuinely dynamic keys not known until runtime (e.g. the
  `add_context` edits in `ProofLine.edit_context`).
- **Import at module top.** Put imports at the top of the module, not inside
  functions. A function-local import is only justified to break a real import
  cycle or to defer a heavy/optional dependency — and when you use one, say why in
  a comment (see `matching/paths.py`, which imports its siblings function-locally
  on purpose). The kernel depends on `matching`, and `formal_system`/`compiler`
  depend on the kernel, so those directions import freely at the top; `matching`
  must never import the kernel or `formal_system`.

## On comments

Keep comments **brief and forward-looking**. Explain **why**, not **how** — the
code already says how. Good comments capture the reasoning, constraint, or
gotcha that the code can't: why a path is disabled, why an exception is caught
and reshaped, why an edge case is handled the way it is. See `app/main.py`'s note
on the proof-checker raising for the tone to aim for. If a comment merely
restates the line below it, delete it.

## For Claude Code on the web

**Do not set up scheduled check-ins, cron triggers, or self-scheduled wake-ups**
in Claude Code web sessions for this repo. Web sessions run in ephemeral
containers and recurring triggers are not wanted here — do the work in the
session and finish. If a task seems to call for polling or a delayed follow-up,
surface it to the user instead of scheduling it.
