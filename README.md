# Edifyce

A web-based formal proof assistant API built with FastAPI. Edifyce lets clients compile formal systems, write proofs, and have them mechanically verified.

## Features

- Compile custom formal systems from Edifyce source code
- Verify formal proofs step-by-step and return structured line-level diagnostics
- OpenAPI schema + interactive docs via Swagger UI

## Tech Stack

- **Backend:** FastAPI
- **ASGI Server:** Uvicorn
- **Validation:** Pydantic v2
- **Core Logic Engine:** Existing Edifyce formal-system compiler/proof checker

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

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
