"""Auth configuration read once from the environment.

Kept in its own module so the user manager and the authentication backend can
both read the same values without importing each other (which would cycle).
"""

from __future__ import annotations

import os

# Secret used to sign JWTs and the password-reset / email-verification tokens.
# MUST be overridden in any real deployment — the fallback is deliberately
# obvious so an unset production secret is caught in review, not shipped quietly.
AUTH_SECRET: str = os.environ.get(
    "EDIFYCE_AUTH_SECRET", "dev-insecure-secret-change-me-0000000000000000"
)

# Session lifetime for both the JWT and its cookie (seconds). One week.
AUTH_LIFETIME_SECONDS: int = int(
    os.environ.get("EDIFYCE_AUTH_LIFETIME_SECONDS", str(60 * 60 * 24 * 7))
)

# Whether the auth cookie carries the `Secure` flag. On by default so production
# (HTTPS) is safe without configuration; set EDIFYCE_AUTH_COOKIE_SECURE=false for
# local HTTP development, where a browser will otherwise refuse to store it.
AUTH_COOKIE_SECURE: bool = (
    os.environ.get("EDIFYCE_AUTH_COOKIE_SECURE", "true").lower() != "false"
)

# Name of the auth cookie.
AUTH_COOKIE_NAME: str = os.environ.get("EDIFYCE_AUTH_COOKIE_NAME", "edifyce_auth")
