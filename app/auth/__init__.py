"""Authentication wiring for the Edifyce API.

Connects the auth-ready `users` / `oauth_accounts` schema (see `app/db`) to
fastapi-users: an httponly-cookie + JWT backend, a user manager, and the
register / login / logout / users routers mounted in `app/main.py`.
"""

from app.auth.backend import (
    auth_backend,
    current_active_user,
    current_active_user_optional,
    fastapi_users,
)
from app.auth.schemas import UserCreate, UserRead, UserUpdate

__all__ = [
    "auth_backend",
    "current_active_user",
    "current_active_user_optional",
    "fastapi_users",
    "UserCreate",
    "UserRead",
    "UserUpdate",
]
