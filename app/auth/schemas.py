"""Pydantic read/create/update models for the auth routes.

Thin extensions of fastapi-users' base schemas: they contribute the standard
fields (id, email, the is_* flags) and we add Edifyce's optional `display_name`.
These are the request/response contract for /auth/register and /users/me.
"""

from __future__ import annotations

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    display_name: str | None = None


class UserCreate(schemas.BaseUserCreate):
    display_name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None
