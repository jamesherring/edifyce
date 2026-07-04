import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.schemas import (
    CompileRequest,
    CompileResponse,
    HealthResponse,
    VerifyProofRequest,
    VerifyProofResponse,
)
from website.logical.compiler import compile as compile_formal_system

app = FastAPI(
    title="Edifyce API",
    version="2.0.0",
    description="FastAPI backend for compiling formal systems and verifying proofs.",
)

# Cross-origin access for the Svelte frontend. During development the SvelteKit
# dev server (default http://localhost:5173) and the preview server
# (http://localhost:4173) run on a different origin from this API, so the
# browser needs an explicit CORS allowance. Override the allowed origins with a
# comma-separated EDIFYCE_CORS_ORIGINS environment variable in other setups.
_default_origins = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:4173,http://127.0.0.1:4173"
)
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("EDIFYCE_CORS_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse()


@app.post("/formal-systems/compile", response_model=CompileResponse)
def compile_system(payload: CompileRequest) -> CompileResponse:
    result = compile_formal_system(payload.code)

    if "errors" in result:
        return CompileResponse(success=False, errors=result["errors"])

    system = result["system"]
    system_name = system.name if system.name else None

    return CompileResponse(
        success=True,
        system_name=system_name,
        line_type_count=len(system.line_types),
        inference_rule_count=len(system.inference_rules),
    )


@app.post("/proofs/verify", response_model=VerifyProofResponse)
def verify_proof(payload: VerifyProofRequest) -> VerifyProofResponse:
    compile_result = compile_formal_system(payload.system_code)

    if "errors" in compile_result:
        raise HTTPException(status_code=400, detail=compile_result["errors"])

    system = compile_result["system"]

    # The proof checker raises on malformed proofs against otherwise valid
    # systems (e.g. a line type whose context edit targets a missing key).
    # Mirror the old Django validation path: return a structured error
    # instead of letting the exception escape as a 500.
    try:
        proof = system.parse(payload.proof_text)
    except Exception as e:
        return VerifyProofResponse(success=False, errors=[str(e)])

    return VerifyProofResponse(success=proof.valid, proof=proof.data())


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
#
# When the Svelte app has been built (`cd frontend && npm run build`), serve the
# resulting single-page app from this same server so the whole thing runs from
# one origin. If the build is absent — e.g. a fresh checkout or an API-only
# deployment — these routes are simply not registered and the API is unaffected.

FRONTEND_BUILD = Path(__file__).resolve().parent.parent / "frontend" / "build"

if FRONTEND_BUILD.is_dir():
    _index = FRONTEND_BUILD / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str) -> FileResponse:
        # Serve a real build asset when the path maps to one; otherwise fall
        # back to index.html so client-side routing handles the URL. The API
        # routes above are registered first and take precedence, so this only
        # catches non-API GET requests.
        candidate = (FRONTEND_BUILD / path).resolve()
        if (
            path
            and FRONTEND_BUILD in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(_index)
