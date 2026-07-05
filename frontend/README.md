# Edifyce frontend

A [SvelteKit](https://svelte.dev/docs/kit) single-page app (Svelte 5) styled with
[Tailwind CSS](https://tailwindcss.com) v4 and [shadcn-svelte](https://shadcn-svelte.com)
components. It talks to the Edifyce FastAPI backend to compile formal systems and
verify proofs.

## Pages

| Route      | Purpose                                                              |
| ---------- | ------------------------------------------------------------------- |
| `/`        | Landing page                                                        |
| `/compile` | Compile a formal system → `POST /formal-systems/compile`            |
| `/verify`  | Verify a proof against a system, line by line → `POST /proofs/verify` |

## Development

Requires Node 20+.

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on http://localhost:5173. Start the backend separately:

```bash
# from the repo root
uv run uvicorn app.main:app --reload
```

The app makes same-origin (relative) API requests. In development the dev
server proxies the API paths (`/health`, `/formal-systems`, `/proofs`) to the
backend at `http://localhost:8000`, so the two servers work together with no
extra configuration. Override the proxy target with `VITE_API_PROXY_TARGET`, or
point the app at a backend on a different origin with `VITE_API_BASE_URL` (that
origin must then be listed in the backend's `EDIFYCE_CORS_ORIGINS`). See
`.env.example`.

## Building

```bash
npm run build      # static bundle written to ./build
npm run preview    # preview the production build
```

The build uses [`@sveltejs/adapter-static`](https://svelte.dev/docs/kit/adapter-static)
with an `index.html` fallback, so the output is a plain static bundle that any
static host can serve.

### Served by FastAPI (single origin)

If `frontend/build` exists, the FastAPI app serves it automatically at `/`, so
one `uvicorn` process serves both the API and the UI:

```bash
cd frontend && npm run build && cd ..
uv run uvicorn app.main:app
# open http://localhost:8000
```

No configuration is needed: the app makes same-origin requests by default, so
the bundle served by FastAPI talks to the API on the same origin. (Set
`VITE_API_BASE_URL` at build time only if the API lives on a different origin.)

## Type checking

```bash
npm run check
```

## Adding more shadcn-svelte components

The project is configured for the shadcn-svelte CLI (`components.json`). Add
further components with:

```bash
npx shadcn-svelte@latest add <component>
```
