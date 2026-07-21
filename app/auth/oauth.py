"""Social login (OAuth2) for GitHub and Google, via fastapi-users + httpx-oauth.

Each provider is wired only when its client id/secret are present in the
environment, so a deployment opts in per provider and the rest of the app is
unaffected when none are configured. The linked accounts land in the
`oauth_accounts` table the schema already provides.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi.responses import RedirectResponse
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from httpx_oauth.clients.github import GitHubOAuth2
from httpx_oauth.clients.google import GoogleOAuth2

from app.auth.backend import get_jwt_strategy
from app.auth.config import (
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_SECURE,
    AUTH_LIFETIME_SECONDS,
)

if TYPE_CHECKING:
    from fastapi.responses import Response
    from httpx_oauth.oauth2 import BaseOAuth2

# Where the browser lands after a successful OAuth callback. The SPA picks up the
# freshly-set session cookie on load, so home is enough.
OAUTH_SUCCESS_REDIRECT = os.environ.get("EDIFYCE_OAUTH_SUCCESS_REDIRECT", "/")

# Explicit base for the OAuth redirect_uri (e.g. https://edifyce.example.com).
# Behind a TLS-terminating proxy the auto-derived redirect_uri can come out as
# http:// and mismatch the provider's registered callback; set this to pin it.
# When unset, fastapi-users derives the callback URL from the incoming request.
OAUTH_REDIRECT_URL_BASE = os.environ.get("EDIFYCE_OAUTH_REDIRECT_URL_BASE")


class RedirectCookieTransport(CookieTransport):
    """Cookie transport whose login response redirects back into the SPA.

    The OAuth callback is reached by a full-page browser navigation, so the
    default 204 login response would strand the user on a blank
    `/auth/<provider>/callback` page. Set the session cookie and 302 to the app.
    """

    async def get_login_response(self, token: str) -> "Response":
        response = RedirectResponse(url=OAUTH_SUCCESS_REDIRECT, status_code=302)
        return self._set_login_cookie(response, token)


# A dedicated backend for the OAuth routers: same JWT strategy and cookie as the
# password flow (so the session is interchangeable), only the login *response*
# differs (redirect vs 204).
oauth_backend = AuthenticationBackend(
    name="oauth-cookie",
    transport=RedirectCookieTransport(
        cookie_name=AUTH_COOKIE_NAME,
        cookie_max_age=AUTH_LIFETIME_SECONDS,
        cookie_secure=AUTH_COOKIE_SECURE,
        cookie_httponly=True,
        cookie_samesite="lax",
    ),
    get_strategy=get_jwt_strategy,
)


def _make_client(
    env_prefix: str, factory: "type[BaseOAuth2]"
) -> "BaseOAuth2 | None":
    client_id = os.environ.get(f"{env_prefix}_CLIENT_ID")
    client_secret = os.environ.get(f"{env_prefix}_CLIENT_SECRET")
    if client_id and client_secret:
        return factory(client_id, client_secret)
    return None


# Enabled provider clients, keyed by the URL segment they mount under. GitHub's
# default scopes already include `user:email`; Google's include profile + email.
_ALL_PROVIDERS = (
    ("google", _make_client("GOOGLE_OAUTH", GoogleOAuth2)),
    ("github", _make_client("GITHUB_OAUTH", GitHubOAuth2)),
)

enabled_oauth_clients: list[tuple[str, "BaseOAuth2"]] = [
    (name, client) for name, client in _ALL_PROVIDERS if client is not None
]


def redirect_url_for(provider: str) -> str | None:
    """The pinned redirect_uri for a provider, or None to derive from the request."""
    if OAUTH_REDIRECT_URL_BASE:
        return f"{OAUTH_REDIRECT_URL_BASE.rstrip('/')}/auth/{provider}/callback"
    return None
