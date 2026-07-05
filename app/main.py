import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.routing import APIRoute

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

# Cross-origin access for the Svelte frontend. The app is served same-origin in
# most setups (dev proxies to this API; production serves the built bundle from
# here), but a cross-origin frontend needs an explicit CORS allowance. The dev
# and preview server origins are allowed by default; override with a
# comma-separated EDIFYCE_CORS_ORIGINS environment variable for other setups.
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
_env_origins = os.environ.get("EDIFYCE_CORS_ORIGINS")
_cors_origins = (
    [origin.strip() for origin in _env_origins.split(",") if origin.strip()]
    if _env_origins is not None
    else _default_origins
)

# No credentials: the API is stateless and uses no cookies or auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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
# Override the location with EDIFYCE_FRONTEND_BUILD (e.g. in a container where
# the bundle is copied elsewhere).

FRONTEND_BUILD = Path(
    os.environ.get(
        "EDIFYCE_FRONTEND_BUILD",
        Path(__file__).resolve().parent.parent / "frontend" / "build",
    )
).resolve()

if (FRONTEND_BUILD / "index.html").is_file():
    # The SPA shell is immutable after the build; read it once.
    _index_html = (FRONTEND_BUILD / "index.html").read_bytes()

    # Paths owned by the JSON API. The catch-all below fully matches every GET,
    # which would otherwise shadow FastAPI's native 405 for a wrong-method hit
    # on an existing (e.g. POST-only) endpoint. Derived from the routes defined
    # above so it stays in sync automatically.
    _api_paths = {
        route.path.strip("/") for route in app.routes if isinstance(route, APIRoute)
    }

    @app.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str, request: Request) -> Response:
        # A GET that reaches here for a known API path is a wrong-method
        # request to an existing endpoint; preserve the API's 405 rather than
        # masking it with the SPA shell.
        if path.strip("/") in _api_paths:
            raise HTTPException(status_code=405, detail="Method Not Allowed")

        # Serve a real build asset when the path maps to one. resolve() both
        # sides so the containment check holds even under symlinked deploy paths.
        candidate = (FRONTEND_BUILD / path).resolve()
        if path and FRONTEND_BUILD in candidate.parents and candidate.is_file():
            return FileResponse(candidate)

        # Otherwise fall back to the SPA shell for browser navigations, so
        # client-side routing can handle the URL. For non-navigation requests
        # (API clients, missing assets) return a real 404 instead of masking it
        # as a 200 HTML response — this preserves the API's error contract for
        # mistyped endpoints.
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(_index_html)
        raise HTTPException(status_code=404, detail="Not Found")
