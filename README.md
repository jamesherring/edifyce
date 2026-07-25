# Edifyce

A web-based formal proof assistant. Edifyce lets you define formal systems,
write proofs, and have them mechanically verified — through a FastAPI backend and
a Svelte frontend.

## Features

- Define custom formal systems as structured parts — grammar productions, line
  types, definitions, axioms and rules — each individually editable and stored
- Verify formal proofs step-by-step and return structured line-level diagnostics
- Email/password user accounts (register, log in, manage profile)
- OpenAPI schema + interactive docs via Swagger UI
- A Svelte + shadcn-svelte web UI for building systems and verifying proofs

## Tech Stack

- **Backend:** FastAPI
- **ASGI Server:** Uvicorn
- **Validation:** Pydantic v2
- **Core Logic Engine:** The Edifyce formal-system builder and term-based proof kernel
- **Frontend:** SvelteKit (Svelte 5), Tailwind CSS v4, shadcn-svelte

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/jamesherring/edifyce.git
   cd edifyce
   ```

2. **Install dependencies** (requires [uv](https://docs.astral.sh/uv/))
   ```bash
   uv sync
   ```

3. **Start the development server**
   ```bash
   uv run uvicorn app.main:app --reload
   ```

4. **Open API docs**
   - Swagger UI: http://127.0.0.1:8000/docs
   - ReDoc: http://127.0.0.1:8000/redoc

## Running Tests

```bash
uv run pytest
```

## API Endpoints

- `GET /api/health` — Health check.
- `GET`/`POST /api/formal-systems` — List your systems / create one (stored as normalised rows, not source text).
- `POST /api/formal-systems/{id}/validate` — Assemble the stored system and compile it, reporting any errors.
- `POST /api/formal-systems/{id}/verify` — Verify a proof against a stored system (only the proof text is sent).
- `POST /api/auth/register` — Create a user account.
- `POST /api/auth/login` / `POST /api/auth/logout` — Start / end a session (httponly cookie).
- `GET`/`PATCH /api/users/me` — Read or update the signed-in user.

## Authentication

Email/password auth is provided by [fastapi-users](https://fastapi-users.github.io/),
backed by the `users` table. A successful login sets a stateless JWT in an
httponly cookie; the SvelteKit UI exposes `/login`, `/register`, and `/account`.

The auth routes require a database — point `DATABASE_URL` at your Postgres (see
[`app/db/README.md`](app/db/README.md)); so do the formal-system routes, since
they now read stored systems (verification included). Only `/api/health` runs
without a database. Configuration:

| Variable | Purpose | Default |
|---|---|---|
| `EDIFYCE_AUTH_SECRET` | Signs JWTs and reset/verify tokens. **Set a stable value in production.** | ephemeral per-process random (see below) |
| `EDIFYCE_AUTH_LIFETIME_SECONDS` | Session lifetime | `604800` (7 days) |
| `EDIFYCE_AUTH_COOKIE_SECURE` | `Secure` flag on the cookie. Set `false` for local HTTP. | `true` |
| `EDIFYCE_AUTH_COOKIE_NAME` | Cookie name | `edifyce_auth` |

If `EDIFYCE_AUTH_SECRET` is unset, the app signs tokens with a **fresh random
secret generated per process** rather than a checked-in value — so a forgotten
secret can never accept forged cookies. The trade-off is that sessions don't
survive a restart and aren't valid across multiple worker processes, which makes
the missing configuration obvious. Always set it in a real deployment.

### Social login (OAuth)

GitHub and Google sign-in are supported via [httpx-oauth](https://frankie567.github.io/httpx-oauth/),
linking accounts into the `oauth_accounts` table. Each provider is enabled only
when its client id/secret are set, so `GET /api/auth/providers` (and the UI) shows
just the configured ones. Set the credentials from an OAuth app on each provider,
with the callback URL `https://<your-host>/api/auth/<provider>/callback`:

| Variable | Purpose |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Enable Google sign-in |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | Enable GitHub sign-in |
| `EDIFYCE_OAUTH_REDIRECT_URL_BASE` | Pin the callback origin (e.g. `https://edifyce.example.com`) when behind a TLS-terminating proxy that would otherwise derive an `http://` redirect_uri. Optional. |
| `EDIFYCE_OAUTH_SUCCESS_REDIRECT` | Where the browser lands after a successful sign-in (default `/`). Optional. |

The flow mounts `GET /api/auth/<provider>/authorize` (returns the provider's
authorization URL) and `GET /api/auth/<provider>/callback` (creates or links the
user, sets the session cookie, and redirects back into the app). A social login
is linked to an existing account with the same email **only when that account is
already verified** — this refuses to attach to an unverified password
pre-registration of the victim's email (account pre-hijacking); such an attempt
is rejected rather than linked.

## Frontend

The web UI lives in [`frontend/`](frontend/) — a SvelteKit single-page app built
with Tailwind CSS and shadcn-svelte. It provides pages to build a formal system
and to verify a proof line by line against the API above.

```bash
cd frontend
npm install
npm run dev            # dev server on http://localhost:5173
```

Run the backend alongside it (`uv run uvicorn app.main:app --reload`); CORS is
enabled for the dev server out of the box. Alternatively, build the frontend
(`npm run build`) and the FastAPI app will serve it directly at `/`, so a single
`uvicorn` process serves both the API and the UI. See
[`frontend/README.md`](frontend/README.md) for details.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
