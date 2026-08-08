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

## Reading a proof

`/proofs/[id]` shows **one** view of a proof, not a source pane beside a
verification pane: browsing a proof, the two said the same thing. The rows come
from the proof's *stored structure* (`GET /api/proofs/{id}/structure`) rather
than from the cached verification payload, because that is where a term
re-spelled through a notation lives — so the notation switch changes the very
lines the checker's verdicts are attached to. A proof with no stored structure
(never verified, or verified before the store existed) falls back to showing its
source as written. The editor keeps the two-pane layout, where the panes are an
editable source and its results and genuinely differ.

Each row reads **statement left, justification right**: a proof is a column of
statements, and putting the citation under each one doubles the height of every
row to say what a reader scans for in a second column. Browsing shows a marker
only where something is off — a tick on every line of a valid proof repeats what
the card's own badge already says — while the editor keeps one per line, where a
tick appearing as you type *is* the feedback. An open goal (`failure.code ===
'hole'`) gets a mark of its own rather than a cross: it is work left, not a
mistake. And the line-type badge is suppressed for the system's *primary* line
type, since every ordinary line carries it; `assume`, `fresh` and comment lines
keep theirs, which is where the type is the interesting thing.

The citation itself expands (`components/JustificationCard.svelte`), from **one
of two sources**, because only half of what it shows costs anything.

What the citation *says* — the rule the label resolved to, its own schemas, the
corpus's note about it, and where its proof is — is rows, so
`GET /api/formal-systems/{id}/library/{label}` answers it with no build at all,
for anyone who may read the system. That is what a signed-out reader of a
published corpus gets.

**What the metavariables stood for on this step** is not stored: it is derived by
the match, so `GET /api/proofs/{id}/lines/{n}/justification` re-checks the proof
for it, and a re-check is signed-in only (see the note above `verify_stored_proof`
in `app/routers/proofs.py`). A signed-in reader gets that record instead — the
same card with its *Here* section, the premises tied to the lines that filled
them, and the provisos.

Either way it is fetched on open and once: asking up front would be one request
per line for cards nobody may open.

A notation named `latex` is **typeset** rather than shown as source
(`components/Typeset.svelte`, KaTeX). The name is the whole of the judgement, and
it is the same one the importer makes when it derives a projection from a `.mm`
file's `$t` block. A reading KaTeX will not parse falls back to its source: the
projection is derived per production from a token map nobody checked against a
TeX parser, so a miss is expected rather than exceptional.

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
