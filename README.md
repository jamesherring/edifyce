# Edifyce

A web-based formal proof assistant. Edifyce lets you compile formal systems,
write proofs, and have them mechanically verified — through a FastAPI backend and
a Svelte frontend.

## Features

- Compile custom formal systems from Edifyce source code
- Verify formal proofs step-by-step and return structured line-level diagnostics
- OpenAPI schema + interactive docs via Swagger UI
- A Svelte + shadcn-svelte web UI for compiling systems and verifying proofs

## Tech Stack

- **Backend:** FastAPI
- **ASGI Server:** Uvicorn
- **Validation:** Pydantic v2
- **Core Logic Engine:** Existing Edifyce formal-system compiler/proof checker
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

- `GET /health` — Health check.
- `POST /formal-systems/compile` — Compile system code and return summary metadata.
- `POST /proofs/verify` — Compile a system and verify a proof against it.

## Frontend

The web UI lives in [`frontend/`](frontend/) — a SvelteKit single-page app built
with Tailwind CSS and shadcn-svelte. It provides pages to compile a formal system
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
