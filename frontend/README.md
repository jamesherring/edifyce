# Edifyce frontend

A [SvelteKit](https://svelte.dev/docs/kit) single-page app (Svelte 5) styled with
[Tailwind CSS](https://tailwindcss.com) v4 and [shadcn-svelte](https://shadcn-svelte.com)
components. It talks to the Edifyce FastAPI backend to browse, build and verify
formal systems.

## Pages

| Route                   | Purpose                                                                        |
| ----------------------- | ------------------------------------------------------------------------------ |
| `/`                     | Landing page                                                                   |
| `/systems`              | Master list of published systems (+ a "My systems" view) → `GET /api/formal-systems{,/public}` |
| `/systems/new`          | Create a system → `POST /api/formal-systems`                                       |
| `/systems/[id]`         | Read-only detail: contents and validation → `GET /api/formal-systems/{id}` + `POST …/validate` |
| `/systems/[id]/edit`    | Owner editor: settings, publish, and per-part CRUD → `PATCH`/`DELETE` + `…/{sorts,productions,…}` |
| `/systems/[id]/verify`  | Verify a proof against the system, line by line → `POST /api/formal-systems/[id]/verify` |
| `/login`                | Log in → `POST /api/auth/login`                                                     |
| `/register`             | Create an account → `POST /api/auth/register`                                       |
| `/account`              | Manage the signed-in user → `GET`/`PATCH /api/users/me`                             |

Auth state is held in `src/lib/auth.svelte.ts` (a reactive store fed by
`GET /api/users/me`); the session itself lives in an httponly cookie the browser
sends automatically. Requests go through `src/lib/api.ts` with
`credentials: 'include'`.

`/login` and `/register` also render GitHub/Google buttons
(`components/oauth-buttons.svelte`) for whichever providers the backend reports
from `GET /api/auth/providers`; clicking one sends the browser to the provider's
authorization URL and the backend completes the flow on its callback.

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

The app makes same-origin (relative) API requests, all under the `/api` prefix.
In development the dev server proxies `/api` to the backend at
`http://localhost:8000`, so the two servers work together with no extra
configuration. Override the proxy target with `VITE_API_PROXY_TARGET`, or
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

## Testing

Unit and component tests run under [Vitest](https://vitest.dev/) in a jsdom
environment, with [@testing-library/svelte](https://testing-library.com/docs/svelte-testing-library/intro/)
for rendering components.

```bash
npm run test          # run once (CI)
npm run test:watch    # watch mode
```

Test files live beside the code they cover (`*.test.ts`; component tests use
`*.svelte.test.ts`). The Vitest config is a `test` project inside
`vite.config.ts`, so `$lib` / `$app` aliases resolve exactly as in the app.

## Adding more shadcn-svelte components

The project is configured for the shadcn-svelte CLI (`components.json`). Add
further components with:

```bash
npx shadcn-svelte@latest add <component>
```
