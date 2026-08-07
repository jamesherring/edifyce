"""``scripts/import_metamath.py --owner``: the two questions asked before a write.

An import is ownerless by default, and `app.db.metamath_store` argues for why.
`--owner` overrides that for a whole run, and both of the things that can go wrong
with it are cheap to ask about up front and expensive to discover afterwards: an
address nobody registered produces an owner who cannot sign in, and a name that
slugifies onto a system this user already owns raises an integrity error out of
the first flush. The import proper is covered by `test_metamath_layered_store`;
this is the resolution in front of it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import scripts.import_metamath as script
from app.db import Base
from app.db.models import FormalSystem, User
from tests.database import async_url, create_tables, database_url

_TABLES = [User.__table__, FormalSystem.__table__]


@pytest.fixture
def db(tmp_path) -> str:
    url = database_url(tmp_path, "owner")
    create_tables(url, _TABLES)
    return url


def _sessionmaker(url: str):
    return async_sessionmaker(create_async_engine(async_url(url)), expire_on_commit=False)


def _run(url: str, work):
    async def go():
        async with _sessionmaker(url)() as session:
            return await work(session)

    return asyncio.run(go())


def _register(url: str, email: str) -> uuid.UUID:
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            user = User(
                email=email,
                hashed_password="unused",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            session.add(user)
            # Read the id from the flush rather than after the commit: `User`
            # eagerly joins `oauth_accounts`, which this schema does not carry.
            session.flush()
            owner = user.id
            session.commit()
            return owner
    finally:
        engine.dispose()


def _own(url: str, owner: uuid.UUID, name: str, slug: str) -> None:
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.add(FormalSystem(owner_id=owner, name=name, slug=slug))
            session.commit()
    finally:
        engine.dispose()


def test_no_owner_asked_for_is_no_owner_resolved(db):
    assert _run(db, lambda session: script._owner(session, None)) is None


def test_an_address_resolves_to_the_user_who_registered_it(db):
    expected = _register(db, "ada@example.com")

    assert _run(db, lambda s: script._owner(s, "ada@example.com")) == expected


def test_the_address_is_matched_as_fastapi_users_stores_it(db):
    # Case-insensitively, and without the whitespace a shell copy-paste leaves.
    expected = _register(db, "ada@example.com")

    assert _run(db, lambda s: script._owner(s, "  ADA@Example.COM ")) == expected


def test_an_unregistered_address_is_refused_rather_than_created(db):
    # Creating the account would hand the corpus to someone who cannot sign in,
    # and nothing would say so until they went looking for it.
    with pytest.raises(LookupError, match="No registered user"):
        _run(db, lambda s: script._owner(s, "nobody@example.com"))


def test_an_ownerless_import_is_never_refused_for_a_slug(db):
    # The unique index is partial — it constrains owned rows only — so an
    # ownerless import cannot collide however many systems share the slug.
    _own(db, _register(db, "ada@example.com"), "Metamath", "metamath")

    _run(db, lambda s: script._refuse_a_slug_collision(s, None, ["Metamath"]))


def test_a_name_this_user_already_owns_is_refused_before_the_parse_is_stored(db):
    owner = _register(db, "ada@example.com")
    _own(db, owner, "ZF set theory", "zf-set-theory")

    with pytest.raises(LookupError, match="zf-set-theory"):
        _run(
            db,
            lambda s: script._refuse_a_slug_collision(
                s, owner, ["Propositional calculus", "ZF set theory"]
            ),
        )


def test_another_users_system_of_the_same_name_is_not_a_collision(db):
    # The index is scoped to the owner, so two users may each have their own.
    _own(db, _register(db, "grace@example.com"), "ZF set theory", "zf-set-theory")
    mine = _register(db, "ada@example.com")

    _run(db, lambda s: script._refuse_a_slug_collision(s, mine, ["ZF set theory"]))


def test_the_check_predicts_the_slug_the_import_would_store(db):
    # Asserted against the function that decides it, not against a literal: the
    # whole point of `system_slug` being shared is that this cannot drift.
    from app.db.systems_mapping import system_slug

    owner = _register(db, "ada@example.com")
    _own(db, owner, "whatever", system_slug("Predicate Calculus (2)"))

    with pytest.raises(LookupError):
        _run(
            db,
            lambda s: script._refuse_a_slug_collision(s, owner, ["Predicate Calculus (2)"]),
        )
