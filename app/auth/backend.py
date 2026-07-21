"""The authentication backend: httponly cookie transport + JWT strategy.

A cookie backend (rather than a bearer token) is used because the SPA is served
same-origin by this app: the browser holds the JWT in an httponly cookie the
JavaScript can never read, so a stolen-token XSS class is closed off. The JWT is
stateless — no server-side session store — which suits the serverless target.
"""

from __future__ import annotations

import uuid

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)

from app.auth.config import (
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_SECURE,
    AUTH_LIFETIME_SECONDS,
    AUTH_SECRET,
)
from app.auth.users import get_user_manager
from app.db.models import User

cookie_transport = CookieTransport(
    cookie_name=AUTH_COOKIE_NAME,
    cookie_max_age=AUTH_LIFETIME_SECONDS,
    cookie_secure=AUTH_COOKIE_SECURE,
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=AUTH_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Dependency for routes that require a signed-in, active user.
current_active_user = fastapi_users.current_user(active=True)

# Optional variant: the active user when signed in, else None (no 401). Read
# routes that serve published systems to anyone but drafts only to their owner
# use this to tell "signed out" from "signed in as someone else".
current_active_user_optional = fastapi_users.current_user(active=True, optional=True)
