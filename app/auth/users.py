"""The fastapi-users database adapter and user manager.

`get_user_db` bridges the ORM `User`/`OAuthAccount` models to fastapi-users;
`UserManager` hooks the lifecycle events. Both are FastAPI dependencies resolved
per request, so importing this module opens no database connection.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin, exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.auth.config import AUTH_SECRET
from app.db.models import OAuthAccount, User
from app.db.session import get_session

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("edifyce.auth")


async def get_user_db(
    session: "AsyncSession" = Depends(get_session),
) -> "AsyncIterator[SQLAlchemyUserDatabase]":
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Both token flows sign with the shared auth secret.
    reset_password_token_secret = AUTH_SECRET
    verification_token_secret = AUTH_SECRET

    async def on_after_register(
        self, user: User, request: "Request | None" = None
    ) -> None:
        logger.info("User registered: %s", user.email)

    async def on_after_forgot_password(
        self, user: User, token: str, request: "Request | None" = None
    ) -> None:
        # No mail transport is wired yet: log the token so password reset can be
        # exercised in development. Replace with an email send before relying on
        # the reset flow in production.
        logger.info("Password reset requested for %s (token: %s)", user.email, token)

    async def on_after_request_verify(
        self, user: User, token: str, request: "Request | None" = None
    ) -> None:
        logger.info("Verification requested for %s (token: %s)", user.email, token)

    async def oauth_callback(  # type: ignore[override]
        self,
        oauth_name: str,
        access_token: str,
        account_id: str,
        account_email: str,
        expires_at: int | None = None,
        refresh_token: str | None = None,
        request: "Request | None" = None,
        *,
        associate_by_email: bool = False,
        is_verified_by_default: bool = False,
    ) -> User:
        # Guard against account pre-hijacking: refuse to link a social login to an
        # existing *unverified* local account. An attacker could otherwise
        # pre-register the victim's email as an unverified password account and
        # have the victim's later OAuth sign-in attach to it. The provider proves
        # its own email; the local row's email ownership is unproven until
        # is_verified. A verified local account (or a returning OAuth user, which
        # is always verified) associates normally; a brand-new email is created.
        if associate_by_email:
            try:
                existing = await self.get_by_email(account_email)
            except exceptions.UserNotExists:
                existing = None
            if existing is not None and not existing.is_verified:
                raise exceptions.UserAlreadyExists()

        return await super().oauth_callback(
            oauth_name,
            access_token,
            account_id,
            account_email,
            expires_at,
            refresh_token,
            request,
            associate_by_email=associate_by_email,
            is_verified_by_default=is_verified_by_default,
        )


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> "AsyncIterator[UserManager]":
    yield UserManager(user_db)
