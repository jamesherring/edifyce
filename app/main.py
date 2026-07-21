import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import (
    auth_backend,
    fastapi_users,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.auth.config import AUTH_COOKIE_SECURE, AUTH_SECRET
from app.auth.oauth import (
    enabled_oauth_clients,
    oauth_backend,
    redirect_url_for,
)
from app.routers.system_parts import router as system_parts_router
from app.routers.systems import router as systems_router
from app.schemas import (
    CompileRequest,
    CompileResponse,
    HealthResponse,
    OAuthProvidersResponse,
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

# Auth uses an httponly cookie, so the browser must be allowed to send it on
# cross-origin API calls (allow_credentials). Credentials with a "*" origin is a
# footgun — Starlette then echoes *any* Origin back with
# Access-Control-Allow-Credentials, granting every site credentialed access — so
# only enable credentials when the origins are an explicit list (the default).
_allow_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
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
# Authentication
# ---------------------------------------------------------------------------
#
# Email/password auth backed by the `users` table, via fastapi-users. Mounts:
#   POST /auth/login, POST /auth/logout   (cookie session)
#   POST /auth/register                   (create account)
#   GET/PATCH /users/me, .../{id}         (current user + admin management)
# Social login (OAuth) mounts /auth/<provider>/authorize + /callback for each
# configured provider (see app/auth/oauth.py); GET /auth/providers lists them.
# These need a database (DATABASE_URL); the compile/verify routes do not.

_auth_router = fastapi_users.get_auth_router(auth_backend)
_register_router = fastapi_users.get_register_router(UserRead, UserCreate)
_users_router = fastapi_users.get_users_router(UserRead, UserUpdate)

app.include_router(_auth_router, prefix="/auth", tags=["auth"])
app.include_router(_register_router, prefix="/auth", tags=["auth"])
app.include_router(_users_router, prefix="/users", tags=["users"])

# Owner-scoped CRUD for formal systems (stored as normalised rows, not .edi
# text). Like the fastapi-users routers, an included router mounts as a nested
# router rather than flat APIRoutes on `app`, so it's registered with the SPA
# guard below (its routes already carry the /formal-systems prefix).
app.include_router(systems_router)
# Per-object CRUD for a system's parts. Every route is under
# /formal-systems/{system_id}/... (fully parameterized), so there's nothing for
# the SPA path guard to add.
app.include_router(system_parts_router)

# fastapi-users' routers mount as nested routers, so their concrete paths are
# not APIRoute entries on `app` — the SPA fallback's API-path guard can't find
# them by iterating app.routes. Record their non-parameterized paths here so a
# wrong-method browser GET to e.g. /auth/login still gets the API's 405 instead
# of being masked by the SPA shell.
_MOUNTED_API_ROUTERS: list[tuple[str, object]] = [
    ("/auth", _auth_router),
    ("/auth", _register_router),
    ("/users", _users_router),
    # systems_router already carries its /formal-systems prefix on each route.
    ("", systems_router),
]

# Social login: one router per configured provider. `is_verified_by_default`
# trusts the provider's verified email for accounts it creates. `associate_by_email`
# is requested, but UserManager.oauth_callback only actually links to a
# pre-existing local account when that account is itself verified — otherwise an
# unverified pre-registration of the victim's email could hijack their OAuth
# identity (account pre-hijacking).
for _provider, _client in enabled_oauth_clients:
    _oauth_router = fastapi_users.get_oauth_router(
        _client,
        oauth_backend,
        AUTH_SECRET,
        redirect_url=redirect_url_for(_provider),
        associate_by_email=True,
        is_verified_by_default=True,
        # The OAuth CSRF cookie must be storable in the same contexts as the
        # session cookie (e.g. local HTTP), so mirror its Secure flag.
        csrf_token_cookie_secure=AUTH_COOKIE_SECURE,
    )
    app.include_router(_oauth_router, prefix=f"/auth/{_provider}", tags=["auth"])
    _MOUNTED_API_ROUTERS.append((f"/auth/{_provider}", _oauth_router))


@app.get("/auth/providers", response_model=OAuthProvidersResponse, tags=["auth"])
def oauth_providers() -> OAuthProvidersResponse:
    return OAuthProvidersResponse(
        providers=[name for name, _ in enabled_oauth_clients]
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> Response:
    # A failed OAuth callback is reached by a full-page browser navigation, so the
    # default raw-JSON error would strand the user on the /auth/<provider>/callback
    # URL. Redirect browsers back to /login with an error code the SPA can turn
    # into a friendly message (e.g. the same-email account case, which every
    # password user hits since there's no email-verification flow). Every other
    # error — and non-browser clients — keep the default JSON response.
    path = request.url.path
    is_oauth_callback = path.startswith("/auth/") and path.endswith("/callback")
    wants_html = "text/html" in request.headers.get("accept", "")
    if is_oauth_callback and wants_html and 400 <= exc.status_code < 500:
        code = exc.detail if isinstance(exc.detail, str) else "oauth_error"
        return RedirectResponse(f"/login?error={code}", status_code=302)
    return await http_exception_handler(request, exc)


def _mounted_api_paths() -> set[str]:
    paths: set[str] = set()
    for prefix, router in _MOUNTED_API_ROUTERS:
        for route in router.routes:
            # Skip parameterized paths (e.g. /users/{id}): the router serves them
            # for every method that reaches them, so they never fall through to
            # the SPA catch-all where this guard matters.
            if isinstance(route, APIRoute) and "{" not in route.path:
                paths.add(f"{prefix}{route.path}".strip("/"))
    return paths


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
    } | _mounted_api_paths()

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
