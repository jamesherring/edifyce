"""Social login (OAuth) wiring: providers list, conditional mounting, redirect.

No real provider credentials are exercised — these check that providers mount
only when configured, that the authorize endpoint hands back a provider URL, and
that the new routes are covered by the SPA fallback guard. The app is reloaded
with the credential env vars set, since the routers are wired at import time.
"""

import asyncio
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("httpx_oauth")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient
from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import NullPool, create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.auth.oauth
import app.main
from app.auth.users import UserManager
from app.db.models import OAuthAccount, User

_CREDS = {
    "GOOGLE_OAUTH_CLIENT_ID": "gid",
    "GOOGLE_OAUTH_CLIENT_SECRET": "gsec",
    "GITHUB_OAUTH_CLIENT_ID": "hid",
    "GITHUB_OAUTH_CLIENT_SECRET": "hsec",
}


def _reload_with_env(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(app.auth.oauth)
    return importlib.reload(app.main)


@pytest.fixture
def restore_modules():
    # After a reload-with-credentials test, reset the modules to the default
    # (provider-less) state so the shared app other tests import stays clean.
    yield
    importlib.reload(app.auth.oauth)
    importlib.reload(app.main)


def test_oauth_providers_empty_by_default():
    # The default test environment sets no OAuth credentials.
    client = TestClient(app.main.app)
    assert client.get("/api/auth/providers").json() == {"providers": []}


def test_oauth_routers_mount_when_configured(monkeypatch, restore_modules):
    main = _reload_with_env(monkeypatch, _CREDS)
    client = TestClient(main.app)

    assert set(client.get("/api/auth/providers").json()["providers"]) == {"google", "github"}

    spec = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/auth/google/authorize",
        "/api/auth/google/callback",
        "/api/auth/github/authorize",
        "/api/auth/github/callback",
    ):
        assert path in spec, path

    # The SPA fallback's API-path guard must cover the new authorize/callback
    # paths, or a wrong-method browser GET would be masked by the SPA shell.
    guard = main._mounted_api_paths()
    assert {"api/auth/google/authorize", "api/auth/github/authorize"} <= guard


def test_authorize_returns_provider_url(monkeypatch, restore_modules):
    main = _reload_with_env(monkeypatch, _CREDS)
    client = TestClient(main.app)

    response = client.get("/api/auth/google/authorize")
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith(
        "https://accounts.google.com/"
    )


def test_only_configured_providers_mount(monkeypatch, restore_modules):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    main = _reload_with_env(
        monkeypatch,
        {"GITHUB_OAUTH_CLIENT_ID": "hid", "GITHUB_OAUTH_CLIENT_SECRET": "hsec"},
    )
    client = TestClient(main.app)

    assert client.get("/api/auth/providers").json()["providers"] == ["github"]
    assert "/api/auth/google/authorize" not in client.get("/openapi.json").json()["paths"]


# ---------------------------------------------------------------------------
# Account-linking safety (pre-hijacking guard)
# ---------------------------------------------------------------------------


def _sessionmaker(tmp_path):
    db_path = tmp_path / "oauth.db"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    User.metadata.create_all(
        sync_engine, tables=[User.__table__, OAuthAccount.__table__]
    )
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool
    )
    return async_sessionmaker(async_engine, expire_on_commit=False)


def _base_user(email, *, verified):
    return {
        "email": email,
        "hashed_password": "x",
        "is_active": True,
        "is_superuser": False,
        "is_verified": verified,
    }


def test_oauth_refuses_to_link_unverified_local_account(tmp_path):
    # An attacker pre-registers the victim's email as an unverified password
    # account; the victim's later OAuth sign-in must NOT attach to it.
    sessionmaker = _sessionmaker(tmp_path)

    async def run():
        async with sessionmaker() as session:
            user_db = SQLAlchemyUserDatabase(session, User, OAuthAccount)
            manager = UserManager(user_db)
            await user_db.create(_base_user("victim@example.com", verified=False))
            with pytest.raises(exceptions.UserAlreadyExists):
                await manager.oauth_callback(
                    "google",
                    "tok",
                    "acct-1",
                    "victim@example.com",
                    associate_by_email=True,
                    is_verified_by_default=True,
                )

    asyncio.run(run())


def test_oauth_links_verified_local_account(tmp_path):
    # A verified local account is safe to associate with the same-email login.
    sessionmaker = _sessionmaker(tmp_path)

    async def run():
        async with sessionmaker() as session:
            user_db = SQLAlchemyUserDatabase(session, User, OAuthAccount)
            manager = UserManager(user_db)
            verified = await user_db.create(
                _base_user("ok@example.com", verified=True)
            )
            user = await manager.oauth_callback(
                "google",
                "tok",
                "acct-2",
                "ok@example.com",
                associate_by_email=True,
                is_verified_by_default=True,
            )
            assert user.id == verified.id
            assert any(a.oauth_name == "google" for a in user.oauth_accounts)

    asyncio.run(run())


def test_oauth_creates_new_user_for_unknown_email(tmp_path):
    sessionmaker = _sessionmaker(tmp_path)

    async def run():
        async with sessionmaker() as session:
            user_db = SQLAlchemyUserDatabase(session, User, OAuthAccount)
            manager = UserManager(user_db)
            user = await manager.oauth_callback(
                "github",
                "tok",
                "acct-3",
                "fresh@example.com",
                associate_by_email=True,
                is_verified_by_default=True,
            )
            assert user.email == "fresh@example.com"
            # Created from a verified provider identity → marked verified.
            assert user.is_verified is True

    asyncio.run(run())


# ---------------------------------------------------------------------------
# OAuth callback error handling (browser gets a redirect, not raw JSON)
# ---------------------------------------------------------------------------


def _request(path, accept):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"accept", accept.encode())],
        "query_string": b"",
    }
    return Request(scope)


def test_oauth_callback_error_redirects_browser_to_login():
    from starlette.exceptions import HTTPException as SE

    from app.main import _http_exception_handler

    exc = SE(status_code=400, detail="OAUTH_USER_ALREADY_EXISTS")
    resp = asyncio.run(
        _http_exception_handler(_request("/api/auth/google/callback", "text/html"), exc)
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?error=OAUTH_USER_ALREADY_EXISTS"


def test_oauth_callback_error_stays_json_for_api_clients():
    from starlette.exceptions import HTTPException as SE

    from app.main import _http_exception_handler

    exc = SE(status_code=400, detail="OAUTH_INVALID_STATE")
    resp = asyncio.run(
        _http_exception_handler(
            _request("/api/auth/google/callback", "application/json"), exc
        )
    )
    # No Accept: text/html → the API contract's JSON error is preserved.
    assert resp.status_code == 400


def test_non_oauth_http_error_keeps_default_response():
    from starlette.exceptions import HTTPException as SE

    from app.main import _http_exception_handler

    exc = SE(status_code=404, detail="Not Found")
    resp = asyncio.run(
        _http_exception_handler(_request("/api/users/me", "text/html"), exc)
    )
    assert resp.status_code == 404


def test_redirect_url_for_uses_env_base(monkeypatch):
    monkeypatch.setenv(
        "EDIFYCE_OAUTH_REDIRECT_URL_BASE", "https://edifyce.example.com/"
    )
    oauth = importlib.reload(app.auth.oauth)
    try:
        assert (
            oauth.redirect_url_for("google")
            == "https://edifyce.example.com/api/auth/google/callback"
        )
        # Without the base set, the redirect is derived from the request instead.
        monkeypatch.delenv("EDIFYCE_OAUTH_REDIRECT_URL_BASE", raising=False)
        oauth = importlib.reload(app.auth.oauth)
        assert oauth.redirect_url_for("google") is None
    finally:
        importlib.reload(oauth)
