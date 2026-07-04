---
name: run-server
description: >-
  Launch the Edifyce FastAPI server and (once it exists) drive headless
  Playwright to screenshot the frontend. Use when asked to run/start/serve/boot
  the app, hit the API, inspect the frontend, or take screenshots of the
  running site. Encodes the sandbox-specific fixes (global-only Playwright,
  blocked external CDNs) so they don't have to be rediscovered.
---

# Run the Edifyce server & inspect the frontend with Playwright

## What Edifyce is right now

- **`app/`** — a stateless **FastAPI** API over the proof engine. This is the
  runtime (`uvicorn app.main:app`). Endpoints: `GET /health`,
  `POST /formal-systems/compile`, `POST /proofs/verify`.
- **`website/logical/`** — the core proof engine (`compiler.py`,
  `formal_system.py`, `matching.py`), imported by `app.main`. **Not** a web
  app despite the `website` name; the Django parts were removed.
- **`deprecated/frontend/`** — the **old Django UI, deprecated and not served**.
  Kept purely as reference (see `deprecated/README.md`): Django HTML templates
  under `templates/` and client assets under `static/` (per-page CSS/JS + the
  vendored Ace editor). Do not try to run or import any of it.

### The frontend this skill targets

There is **no live browser frontend yet.** The plan (per
`deprecated/README.md`) is a standalone **Svelte** app that talks to the FastAPI
endpoints, porting the design/behaviour of the deprecated Django UI. **This
skill's Playwright screenshot capability exists for that Svelte frontend once
it's built.** The FastAPI auto-docs (`/docs` Swagger, `/redoc`) are **out of
scope** for this skill — don't screenshot them as "the frontend."

When the Svelte app lands, revisit this skill: fill in its dev-server launch
command (likely `npm install && npm run dev` → a Vite server on e.g.
`http://127.0.0.1:5173`) in the section below.

## 1. Launch the backend server

Dependencies may not be installed in a fresh container. Install, then run:

```bash
pip install -r requirements.txt          # fastapi, uvicorn, pydantic, ...
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

(If the repo has since migrated to uv — `pyproject.toml` + `uv.lock` present —
use `uv sync` and prefix commands with `uv run`.)

Run it in the background so you can probe it, and confirm it's up:

```bash
(uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 3
curl -s http://127.0.0.1:8000/health          # -> {"status":"ok"}
```

Stop it with `pkill -f "uvicorn app.main"`. Add `--reload` for live-reload.
Check `/tmp/uvicorn.log` if `/health` doesn't answer. Exercise endpoints
directly without a browser:

```bash
curl -s -X POST http://127.0.0.1:8000/formal-systems/compile \
  -H 'content-type: application/json' -d '{"code":"..."}'
```

## 2. Launch the Svelte frontend  *(to be filled in when it exists)*

Once the Svelte app is added to the repo, start its dev server here and point
Playwright at it. Expected shape (update with the real paths/ports):

```bash
# cd <svelte-app-dir>
# npm install
# npm run dev -- --host 127.0.0.1 --port 5173
```

## 3. Screenshot / inspect a page with Playwright

Use the bundled helper — it resolves the globally-installed Playwright for you:

```bash
node .claude/skills/run-server/scripts/screenshot.cjs <url> <out.png> [--full] [--wait=<css-selector>]

# e.g. once the Svelte dev server is up:
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:5173/ home.png --full
```

Then view the PNG with the Read tool; use SendUserFile to surface it to the user.

### Sandbox gotchas (already handled / good to know)

1. **Playwright is installed globally, not in this repo.** A plain
   `require('playwright')` / `import 'playwright'` fails with
   `ERR_MODULE_NOT_FOUND`. Chromium is pre-installed at `/opt/pw-browsers`
   (`PLAYWRIGHT_BROWSERS_PATH`) — **never run `playwright install`**. The helper
   resolves the module via `npm root -g`.

2. **External hosts are blocked by the network policy.** The sandbox allows
   pypi, the npm registry, and github, but denies general CDNs / Google Fonts
   etc. (403 on the proxy CONNECT). A Vite-bundled Svelte app serves its own
   JS/CSS locally, so it renders fine — only genuinely external references
   (web fonts, third-party widgets) fail; those show up as `failed:` lines in
   the helper output and are usually cosmetic. **Do not** route the browser
   through `$HTTPS_PROXY` to reach them — that proxy only tunnels HTTPS
   CONNECT, so it mangles `http://127.0.0.1` requests and returns its own error
   page. If a page genuinely needs a blocked asset, vendor it from the npm
   registry (`npm pack <pkg>`, which *is* allowed) and serve it locally.
