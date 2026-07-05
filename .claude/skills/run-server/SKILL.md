---
name: run-server
description: >-
  Launch the Edifyce app (FastAPI backend + SvelteKit frontend) and drive
  headless Playwright to screenshot / inspect the running UI. Use when asked to
  run/start/serve/boot the app, hit the API, inspect the frontend, or take
  screenshots of the running site. Encodes the sandbox-specific fixes (uv
  auto-provisions Python 3.13, global-only Playwright, the SPA-fallback 404
  quirk) so they don't have to be rediscovered.
---

# Run the Edifyce app & inspect the frontend with Playwright

## Layout

- **`app/`** — the **FastAPI** backend (`app.main:app`). Endpoints: `GET /health`,
  `POST /formal-systems/compile`, `POST /proofs/verify`. It **also serves the
  built Svelte SPA at `/`** when `frontend/build/` exists (see the SPA quirk
  below).
- **`website/logical/`** — the core proof engine imported by the backend. Not a
  web app despite the name.
- **`frontend/`** — the **SvelteKit** SPA (Svelte 5, Tailwind v4, shadcn-svelte;
  static adapter). Pages: `/` (landing), `/compile`, `/verify`. It makes
  same-origin relative API calls.
- **`deprecated/frontend/`** — the old Django UI, **not served**; reference only.

Python is managed by **uv** (`pyproject.toml` + `uv.lock`; no `requirements.txt`).

## 1. One-time setup (fresh container)

```bash
uv sync                                   # backend deps + Python 3.13 (see note)
cd frontend && npm install && cd ..       # frontend deps (~20s, Node 20+; here Node 22)
```

> **Python note:** the project requires Python ≥3.13 but the sandbox default is
> 3.11. `uv sync` **auto-downloads and pins Python 3.13** into the project venv —
> no pyenv/manual step. All backend commands go through `uv run` so they use that
> venv, not the system 3.11.

## 2. Launch — pick a mode

The backend is the same either way; the difference is how the frontend is served.

### Mode A — dev servers (recommended for iterating on the UI; hot reload)

Two processes: FastAPI on `:8000`, Vite dev on `:5173`. The Vite server proxies
the API paths (`/health`, `/formal-systems`, `/proofs`) to `:8000`, so the app
works with no CORS/URL config. **Inspect the UI at `:5173`.**

```bash
(uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/be.log 2>&1 &)
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/fe.log 2>&1 &)
sleep 8
curl -s http://127.0.0.1:5173/health      # -> {"status":"ok"}  (proxied to backend)
# UI: http://127.0.0.1:5173/   (also /compile, /verify)
```

Stop: `pkill -f "uvicorn app.main"; pkill -f vite`. Vite needs a few seconds to
boot — check `/tmp/fe.log` for the `ready` line if `:5173` isn't up yet.

### Mode B — single server (production fidelity; one process)

Build the SPA once; FastAPI then serves it at `/` alongside the API. **Inspect
the UI at `:8000`.**

```bash
(cd frontend && npm run build && cd ..)   # writes frontend/build/ (~5s)
(uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/be.log 2>&1 &)
sleep 4
curl -s http://127.0.0.1:8000/health      # -> {"status":"ok"}
# UI: http://127.0.0.1:8000/   (also /compile, /verify)
```

Rebuild (`npm run build`) after frontend edits — Mode B serves a static bundle,
so changes aren't picked up until you rebuild. Use Mode A while iterating.

## 3. Screenshot / inspect the UI with Playwright

Use the bundled helper — it resolves the globally-installed Playwright for you:

```bash
node .claude/skills/run-server/scripts/screenshot.cjs <url> <out.png> [--full] [--wait=<css-selector>]

# Mode A (dev):            Mode B (built):
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:5173/        home.png    --full
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/compile compile.png --full
```

The SPA renders client-side; the helper waits for network-idle, which is enough
for these pages. Pass `--wait=<selector>` if you need a specific element (e.g.
after an interaction) before the shot. Then view the PNG with the Read tool; use
SendUserFile to surface it to the user.

To drive interactions (fill the editor, click **Compile**, screenshot the
result) rather than just snapshot, write a one-off Playwright script following
`scripts/screenshot.cjs` — same global-Playwright resolution, then use
`page.fill` / `page.click` / `page.waitForSelector`.

## Sandbox gotchas (already handled / good to know)

1. **`curl http://127.0.0.1:8000/` returns 404 in Mode B — this is not a bug.**
   The SPA catch-all only returns the HTML shell for requests that
   `Accept: text/html` (browsers). `curl` sends `*/*` and gets a 404. Use
   **`/health`** for readiness checks, a **browser** (Playwright) for the UI, or
   `curl -H 'Accept: text/html' http://127.0.0.1:8000/` if you must curl it.
   (In Mode A, Vite serves `/` directly, so `curl :5173/` is 200.)

2. **Playwright is installed globally, not in this repo.** A plain
   `require('playwright')` fails with `ERR_MODULE_NOT_FOUND`. Chromium is
   pre-installed at `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH`) — **never run
   `playwright install`**. The helper resolves the module via `npm root -g`.

3. **External hosts are blocked by the network policy** (pypi, npm registry, and
   github are allowed; general CDNs / Google Fonts are not). The Vite-bundled app
   serves its own JS/CSS locally, so it renders fully; only genuinely external
   references would fail (shown as `failed:` lines in the helper output, usually
   cosmetic). Do **not** route the browser through `$HTTPS_PROXY` — it only
   tunnels HTTPS CONNECT and mangles `http://127.0.0.1` requests.

## Quick end-to-end (Mode B)

```bash
uv sync && (cd frontend && npm install && npm run build && cd ..)
(uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/be.log 2>&1 &)
sleep 4 && curl -s http://127.0.0.1:8000/health
node .claude/skills/run-server/scripts/screenshot.cjs http://127.0.0.1:8000/ /tmp/home.png --full
# then Read /tmp/home.png
```
