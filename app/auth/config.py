"""Auth configuration read once from the environment.

Kept in its own module so the user manager and the authentication backend can
both read the same values without importing each other (which would cycle).
"""

from __future__ import annotations

import logging
import os
import secrets

_logger = logging.getLogger("edifyce.auth")

# Secret used to sign JWTs and the password-reset / email-verification tokens.
# Set EDIFYCE_AUTH_SECRET to a stable value in any real deployment. If it is
# unset we fall back to a fresh per-process random secret rather than a
# checked-in literal: cookies are then unforgeable even by omission (no public
# signing key exists), at the cost of sessions not surviving a restart or
# spanning multiple worker processes — which surfaces the missing config loudly
# instead of silently accepting forged tokens. We deliberately do *not* raise at
# import: that would also take down the DB-free /health, compile, and verify
# routes, which need no auth.
_env_secret = os.environ.get("EDIFYCE_AUTH_SECRET")
if _env_secret:
    AUTH_SECRET: str = _env_secret
else:
    AUTH_SECRET = secrets.token_urlsafe(32)
    _logger.warning(
        "EDIFYCE_AUTH_SECRET is not set; signing auth tokens with an ephemeral "
        "per-process secret. Set it to a stable value in any real deployment."
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
