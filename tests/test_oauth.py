"""Social login (OAuth) wiring: providers list, conditional mounting, redirect.

No real provider credentials are exercised — these check that providers mount
only when configured, that the authorize endpoint hands back a provider URL, and
that the new routes are covered by the SPA fallback guard. The app is reloaded
with the credential env vars set, since the routers are wired at import time.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("httpx_oauth")

from fastapi.testclient import TestClient

import app.auth.oauth
import app.main

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
    assert client.get("/auth/providers").json() == {"providers": []}


def test_oauth_routers_mount_when_configured(monkeypatch, restore_modules):
    main = _reload_with_env(monkeypatch, _CREDS)
    client = TestClient(main.app)

    assert set(client.get("/auth/providers").json()["providers"]) == {"google", "github"}

    spec = client.get("/openapi.json").json()["paths"]
    for path in (
        "/auth/google/authorize",
        "/auth/google/callback",
        "/auth/github/authorize",
        "/auth/github/callback",
    ):
        assert path in spec, path

    # The SPA fallback's API-path guard must cover the new authorize/callback
    # paths, or a wrong-method browser GET would be masked by the SPA shell.
    guard = main._mounted_api_paths()
    assert {"auth/google/authorize", "auth/github/authorize"} <= guard


def test_authorize_returns_provider_url(monkeypatch, restore_modules):
    main = _reload_with_env(monkeypatch, _CREDS)
    client = TestClient(main.app)

    response = client.get("/auth/google/authorize")
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

    assert client.get("/auth/providers").json()["providers"] == ["github"]
    assert "/auth/google/authorize" not in client.get("/openapi.json").json()["paths"]


def test_redirect_url_for_uses_env_base(monkeypatch):
    monkeypatch.setenv(
        "EDIFYCE_OAUTH_REDIRECT_URL_BASE", "https://edifyce.example.com/"
    )
    oauth = importlib.reload(app.auth.oauth)
    try:
        assert (
            oauth.redirect_url_for("google")
            == "https://edifyce.example.com/auth/google/callback"
        )
        # Without the base set, the redirect is derived from the request instead.
        monkeypatch.delenv("EDIFYCE_OAUTH_REDIRECT_URL_BASE", raising=False)
        oauth = importlib.reload(app.auth.oauth)
        assert oauth.redirect_url_for("google") is None
    finally:
        importlib.reload(oauth)
