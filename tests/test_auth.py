"""Auth routes: contract wiring plus a real register/login/me/logout flow.

The flow test runs against a throwaway SQLite database (only the auth tables are
created — the pgvector `theorems` table isn't SQLite-creatable) with the app's
`get_session` dependency overridden to point at it, so the fastapi-users routers
are exercised end to end without a Postgres.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")

from collections.abc import AsyncIterator, Iterator

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.auth.backend as backend
from app.db.models import OAuthAccount, User
from app.db.session import get_session
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    db_path = tmp_path / "auth.db"

    # DDL via a plain sync engine — trivial and free of async event-loop affinity.
    sync_engine = create_engine(f"sqlite:///{db_path}")
    User.metadata.create_all(
        sync_engine, tables=[User.__table__, OAuthAccount.__table__]
    )
    sync_engine.dispose()

    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool
    )
    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    # The auth cookie is Secure by default; httpx's cookie jar won't replay a
    # Secure cookie over http://testserver, so relax it for the test client.
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Wiring (no database needed)
# ---------------------------------------------------------------------------


def test_auth_routes_are_registered():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/auth/login" in paths
    assert "/api/auth/logout" in paths
    assert "/api/auth/register" in paths
    assert "/api/users/me" in paths


def test_register_rejects_malformed_email(client):
    response = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "secret123"}
    )
    assert response.status_code == 422


def test_spa_guard_covers_mounted_auth_routes():
    # The auth/users routers mount as nested routers, so their concrete paths
    # must be fed into the SPA fallback's API-path guard explicitly — otherwise a
    # wrong-method GET to /auth/login would be masked by the SPA shell (200 HTML)
    # instead of the API's 405.
    from app.main import _mounted_api_paths

    paths = _mounted_api_paths()
    assert {"api/auth/login", "api/auth/logout", "api/auth/register", "api/users/me"} <= paths
    # Parameterized paths can't be matched by the exact-set guard and are excluded.
    assert not any("{" in p for p in paths)


def test_auth_secret_is_not_a_checked_in_literal():
    # The test suite runs without EDIFYCE_AUTH_SECRET set, so this exercises the
    # fallback: it must be a fresh random secret, never a shipped constant.
    from app.auth.config import AUTH_SECRET

    assert AUTH_SECRET
    assert "insecure" not in AUTH_SECRET.lower()
    assert "change-me" not in AUTH_SECRET.lower()
    assert len(AUTH_SECRET) >= 32


# ---------------------------------------------------------------------------
# Full flow
# ---------------------------------------------------------------------------


def test_register_login_me_logout_flow(client):
    # Register.
    response = client.post(
        "/api/auth/register",
        json={
            "email": "ada@example.com",
            "password": "correct horse",
            "display_name": "Ada",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["display_name"] == "Ada"
    assert "hashed_password" not in body

    # Unauthenticated access to the current-user route is refused.
    assert client.get("/api/users/me").status_code == 401

    # Login sets the auth cookie (fastapi-users uses form fields username/password).
    response = client.post(
        "/api/auth/login",
        data={"username": "ada@example.com", "password": "correct horse"},
    )
    assert response.status_code == 204, response.text
    assert backend.cookie_transport.cookie_name in client.cookies

    # The cookie authenticates /users/me.
    response = client.get("/api/users/me")
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"

    # Profile update round-trips.
    response = client.patch("/api/users/me", json={"display_name": "Ada Lovelace"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Ada Lovelace"

    # Logout clears the session.
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/users/me").status_code == 401


def test_login_with_wrong_password_is_rejected(client):
    client.post(
        "/api/auth/register",
        json={"email": "grace@example.com", "password": "right-password"},
    )
    response = client.post(
        "/api/auth/login",
        data={"username": "grace@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 400


def test_duplicate_registration_is_rejected(client):
    payload = {"email": "dupe@example.com", "password": "password123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 400
