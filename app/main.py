import os
from math import isfinite
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
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
from app.routers.assumptions import router as assumptions_router
from app.routers.proofs import router as proofs_router
from app.routers.formalizations import router as formalizations_router
from app.routers.statements import router as statements_router
from app.routers.system_parts import router as system_parts_router
from app.routers.system_relations import router as system_relations_router
from app.routers.systems import router as systems_router
from app.schemas import (
    HealthResponse,
    OAuthProvidersResponse,
)

app = FastAPI(
    title="Edifyce API",
    version="2.0.0",
    description="FastAPI backend for compiling formal systems and verifying proofs.",
)

# Every JSON endpoint lives under this prefix so the API can never collide with a
# client-side SPA route. Without it, `/proofs` was owned by *both* the proofs API
# and the SvelteKit `/proofs` page, so a browser navigation to a proof rendered
# raw JSON (and the dev proxy couldn't tell the two apart). A single reserved
# namespace means the SPA owns every bare path and the API owns everything under
# `/api` — no per-route disambiguation, now or in the future.
API_PREFIX = "/api"

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


@app.get(f"{API_PREFIX}/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse()


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

app.include_router(_auth_router, prefix=f"{API_PREFIX}/auth", tags=["auth"])
app.include_router(_register_router, prefix=f"{API_PREFIX}/auth", tags=["auth"])
app.include_router(_users_router, prefix=f"{API_PREFIX}/users", tags=["users"])

# Owner-scoped CRUD for formal systems (stored as normalised rows, not .edi
# text). Like the fastapi-users routers, an included router mounts as a nested
# router rather than flat APIRoutes on `app`, so it's registered with the SPA
# guard below (its routes already carry the /formal-systems prefix; API_PREFIX
# puts the whole thing under /api).
app.include_router(systems_router, prefix=API_PREFIX)
# Per-object CRUD for a system's parts. Every route is under
# /api/formal-systems/{system_id}/... (fully parameterized), so there's nothing
# for the SPA path guard to add.
app.include_router(system_parts_router, prefix=API_PREFIX)
# Edges between systems, under the *target* — the system whose citations they
# widen. Fully parameterized like the parts router, so the SPA guard needs
# nothing from it.
app.include_router(system_relations_router, prefix=API_PREFIX)
# Owner-scoped CRUD for proofs (stored rows verified against their system).
# Like systems_router, its routes carry their own /proofs prefix under /api.
app.include_router(proofs_router, prefix=API_PREFIX)
# Citable statements nobody has proved, plus the public index of what rests on
# them. Two path shapes — under a system, and the cross-system `/assumptions`
# register — so the router carries its paths in full and takes no prefix of its
# own beyond /api.
app.include_router(assumptions_router, prefix=API_PREFIX)
# Stating a theorem before there is a proof to put it in. Fully parameterized
# (`/formal-systems/{id}/statements`), so the SPA guard needs nothing from it.
app.include_router(statements_router, prefix=API_PREFIX)
# What a formal statement claims to be a formalization *of* — source documents,
# claims, and the reviews of them. Reaches no engine; its `/sources` and
# `/formalizations` collection paths are non-parameterized, so the SPA guard
# needs them recorded below.
app.include_router(formalizations_router, prefix=API_PREFIX)

# fastapi-users' routers mount as nested routers, so their concrete paths are
# not APIRoute entries on `app` — the SPA fallback's API-path guard can't find
# them by iterating app.routes. Record their non-parameterized paths here so a
# wrong-method browser GET to e.g. /auth/login still gets the API's 405 instead
# of being masked by the SPA shell.
_MOUNTED_API_ROUTERS: list[tuple[str, object]] = [
    (f"{API_PREFIX}/auth", _auth_router),
    (f"{API_PREFIX}/auth", _register_router),
    (f"{API_PREFIX}/users", _users_router),
    # systems_router already carries its /formal-systems prefix on each route.
    (API_PREFIX, systems_router),
    # proofs_router likewise carries its /proofs prefix on each route.
    (API_PREFIX, proofs_router),
    # And the assumptions register, whose `/assumptions/public` is the one
    # non-parameterized path a browser GET could otherwise reach as the SPA.
    (API_PREFIX, assumptions_router),
    # The formalization record, whose `/sources` and `/formalizations` are the
    # same shape.
    (API_PREFIX, formalizations_router),
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
    app.include_router(
        _oauth_router, prefix=f"{API_PREFIX}/auth/{_provider}", tags=["auth"]
    )
    _MOUNTED_API_ROUTERS.append((f"{API_PREFIX}/auth/{_provider}", _oauth_router))


@app.get(f"{API_PREFIX}/auth/providers", response_model=OAuthProvidersResponse, tags=["auth"])
def oauth_providers() -> OAuthProvidersResponse:
    return OAuthProvidersResponse(
        providers=[name for name, _ in enabled_oauth_clients]
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """The default 422, with any non-finite number in it made serialisable.

    FastAPI echoes the offending value back under ``input``, and JSON has no
    literal for infinity or NaN — so a body carrying `1e400`, which is *valid*
    JSON and parses to `inf`, fails while the error is being rendered and the
    caller gets a 500 for input the API correctly refused (found in review of the
    embedding routes, and confirmed to be what a real client receives).

    Every float field in this API has the hole, not only the embedding ones, so
    it is closed once here rather than per route. Only the echoed value is
    touched: the location, the type and the message are the default handler's,
    since the point is to *deliver* the 422 rather than to reword it.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors(), custom_encoder={float: _finite})},
    )


def _finite(value: float) -> float | str:
    # `repr` for the values JSON cannot spell, so the caller still sees which
    # coordinate it sent rather than a hole where the input should be.
    return value if isfinite(value) else repr(value)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> Response:
    # A failed OAuth callback is reached by a full-page browser navigation, so the
    # default raw-JSON error would strand the user on the /api/auth/<provider>/callback
    # URL. Redirect browsers back to /login with an error code the SPA can turn
    # into a friendly message (e.g. the same-email account case, which every
    # password user hits since there's no email-verification flow). Every other
    # error — and non-browser clients — keep the default JSON response.
    path = request.url.path
    is_oauth_callback = (
        path.startswith(f"{API_PREFIX}/auth/") and path.endswith("/callback")
    )
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
        stripped = path.strip("/")
        if stripped in _api_paths:
            raise HTTPException(status_code=405, detail="Method Not Allowed")

        # Anything else under the reserved API namespace is a nonexistent endpoint,
        # never a client route — 404 it instead of serving the SPA shell (which
        # would turn a mistyped /api/... into a misleading 200 HTML page).
        api_ns = API_PREFIX.strip("/")
        if stripped == api_ns or stripped.startswith(f"{api_ns}/"):
            raise HTTPException(status_code=404, detail="Not Found")

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
