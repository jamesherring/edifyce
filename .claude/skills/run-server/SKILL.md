---
name: run-server
description: >-
  Launch the Edifyce FastAPI server and optionally drive headless Playwright to
  screenshot the browsable API docs (/docs Swagger UI, /redoc). Use when asked
  to run/start/serve/boot the app, hit the API, inspect the frontend, or take
  screenshots of the running site. Encodes the sandbox-specific fixes (blocked
  doc CDNs, global-only Playwright) so they don't have to be rediscovered.
---

# Run the Edifyce server & inspect it with Playwright

Edifyce is an **API-only FastAPI service** — there is no server-rendered HTML
app. The only browser-facing pages are the auto-generated API docs:

- `GET /health` — JSON health check
- `POST /formal-systems/compile`, `POST /proofs/verify` — JSON endpoints
- `/docs` — Swagger UI (interactive), `/redoc` — ReDoc (read-only)
- `/openapi.json` — raw OpenAPI schema

(The legacy Django `website/` package is dormant — the runtime is `app.main`.
`website.logical.compiler` is imported by the API as the core engine, but the
Django views/templates are **not** served. Don't try to `runserver` it.)

## 1. Launch the server

Dependencies may not be installed in a fresh container. Install, then run:

```bash
pip install -r requirements.txt          # fastapi, uvicorn, pydantic, ...
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run it in the background so you can probe it, and confirm it's up:

```bash
(uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 3
curl -s http://127.0.0.1:8000/health          # -> {"status":"ok"}
```

Stop it with `pkill -f "uvicorn app.main"`. Add `--reload` for live-reload
during iterative work. Check `/tmp/uvicorn.log` if `/health` doesn't answer.

Exercise the endpoints directly without a browser:

```bash
curl -s -X POST http://127.0.0.1:8000/formal-systems/compile \
  -H 'content-type: application/json' -d '{"code":"..."}'
```

## 2. Screenshot / inspect the docs with Playwright

Use the bundled helper — do **not** hand-roll a Playwright script, it already
solves the two sandbox gotchas below:

```bash
node .claude/skills/run-server/scripts/screenshot.cjs <url> <out.png> [--full] [--wait=<css-selector>]

# Swagger UI (full page):
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/docs docs.png --full
# ReDoc:
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/redoc redoc.png --full --wait=h1
```

Then view the PNG with the Read tool. To surface it to the user, use
SendUserFile.

### Why the helper exists — sandbox gotchas (already handled)

1. **Playwright is installed globally, not in this repo.** A plain
   `require('playwright')` / `import 'playwright'` fails with
   `ERR_MODULE_NOT_FOUND`. Chromium is pre-installed at
   `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH`) — never run
   `playwright install`. The helper resolves the module via `npm root -g`.

2. **The doc CDN is blocked.** `/docs` and `/redoc` load their JS/CSS from
   `cdn.jsdelivr.net`, which the sandbox network policy **denies** (403 on the
   proxy CONNECT; `curl` gets `http=000`). A raw browser screenshot of `/docs`
   is therefore blank. Do **not** try to route the browser through
   `$HTTPS_PROXY` — that proxy only tunnels HTTPS CONNECT, so it mangles the
   `http://127.0.0.1` request and returns its own error page. Instead the
   helper **intercepts** requests to jsdelivr/unpkg and serves the assets from
   a local cache, vendored on demand via `npm pack` (the npm registry *is*
   allowed). First run downloads ~3 MB into `scripts/.vendor-cache/`
   (git-ignored); later runs are offline.

   Cosmetic-only: ReDoc additionally requests Google Fonts and an external
   logo that stay blocked. The page still renders fully; ignore those two
   `failed:` lines.

If a page pulls in another blocked CDN asset, add an entry to the `SOURCES`
map at the top of `screenshot.cjs` (basename → npm package + path inside it).

## Quick end-to-end recipe

```bash
pip install -r requirements.txt
(uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 3 && curl -s http://127.0.0.1:8000/health
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/docs /tmp/docs.png --full
# then Read /tmp/docs.png
```
