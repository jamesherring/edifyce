"""ORM models for Edifyce.

Modernised from the original Django schema (see `website/models.py` on the
`main` branch). The shape is deliberately familiar — users own formal systems;
systems inherit from one another; proofs and folders form a tree scoped to a
system; proofs reference other proofs — with three deliberate departures:

* **No pickled engine objects.** The old app stored the compiled `FormalSystem`
  and `Proof` instances in `PickledObjectField`s. The rebuilt engine is a pure
  function of its source text, so we persist the *source* and an optional cached
  JSON snapshot (`compiled` / `result`) instead. Pickles are fragile across code
  changes and not portable; JSON is neither.
* **Auth-ready users.** Django's `auth.User` + `Profile` split is collapsed into
  a single `users` table built on fastapi-users' SQLAlchemy base, with social
  logins modelled as a linked `oauth_accounts` table (one user, many providers).
  No auth routes are wired yet — this is only the schema fastapi-users expects.
* **Search-ready theorems.** A `theorems` table carries a JSONB `pattern` (for
  structural, pattern-based search via a GIN index) and a pgvector `embedding`
  (for semantic / AI search via an HNSW index). Nothing writes to it yet; the
  columns and indexes are in place so the search work is additive later.
"""

import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DDL,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Match this to the embedding model you deploy (e.g. Voyage voyage-3 = 1024,
# OpenAI text-embedding-3-small = 1536). Changing it is a schema migration.
EMBEDDING_DIMENSIONS = 1536

# pgvector lives in an extension. Emit its creation as part of the schema so the
# `vector` type and HNSW index resolve; `IF NOT EXISTS` keeps re-runs safe.
event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS vector"),
)


class User(SQLAlchemyBaseUserTableUUID, TimestampMixin, Base):
    __tablename__ = "users"

    # The base contributes id, email, hashed_password, is_active, is_superuser,
    # is_verified. We override id to a DB-side default so every table generates
    # ids the same way (the base defaults to a client-side uuid4).
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    display_name: Mapped[str | None] = mapped_column(String(256))

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        # Eager-loaded: fastapi-users reads linked accounts alongside the user.
        lazy="joined",
        cascade="all, delete-orphan",
    )
    formal_systems: Mapped[list["FormalSystem"]] = relationship(
        back_populates="owner"
    )


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, TimestampMixin, Base):
    __tablename__ = "oauth_accounts"

    # The base contributes oauth_name, access_token, expires_at, refresh_token,
    # account_id, account_email. It hardcodes the user FK to "user.id"; repoint it
    # at our "users" table and index it for the join fastapi-users does on login.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class FormalSystem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "formal_systems"
    __table_args__ = (
        # A user's own systems are addressable by a unique slug.
        Index("uq_formal_systems_owner_slug", "owner_id", "slug", unique=True),
    )

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), index=True)
    # The Edifyce source; the engine recompiles from this on demand.
    source: Mapped[str] = mapped_column(Text, server_default="")
    description: Mapped[str | None] = mapped_column(Text)
    # System inheritance (the old `inherits_from` self-FK). SET NULL so deleting a
    # base system orphans rather than cascades away its descendants.
    inherits_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="SET NULL"), index=True
    )
    # Cached compile metadata (line-type/rule summary) to avoid recompiling on read.
    compiled: Mapped[dict | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped["User | None"] = relationship(back_populates="formal_systems")
    inherits_from: Mapped["FormalSystem | None"] = relationship(
        remote_side="FormalSystem.id", back_populates="inherited_by"
    )
    inherited_by: Mapped[list["FormalSystem"]] = relationship(
        back_populates="inherits_from"
    )
    folders: Mapped[list["ProofFolder"]] = relationship(
        back_populates="formal_system", cascade="all, delete-orphan"
    )
    proofs: Mapped[list["Proof"]] = relationship(
        back_populates="formal_system", cascade="all, delete-orphan"
    )
    theorems: Mapped[list["Theorem"]] = relationship(
        back_populates="formal_system", cascade="all, delete-orphan"
    )


class ProofFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proof_folders"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # Folder tree. The old app modelled ordering/publishing through a separate
    # OrderedModel `FolderEntry`; here order is a plain `position` and publishing
    # a `published_at` timestamp directly on the node.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proof_folders.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), index=True)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    formal_system: Mapped["FormalSystem"] = relationship(back_populates="folders")
    parent: Mapped["ProofFolder | None"] = relationship(
        remote_side="ProofFolder.id", back_populates="children"
    )
    children: Mapped[list["ProofFolder"]] = relationship(back_populates="parent")
    proofs: Mapped[list["Proof"]] = relationship(back_populates="folder")


# Proof-to-proof dependency graph (the old `references` self-M2M). Directed:
# a row (proof_id -> references_id) means `proof_id` cites `references_id`.
proof_references = Table(
    "proof_references",
    Base.metadata,
    Column(
        "proof_id",
        ForeignKey("proofs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "references_id",
        ForeignKey("proofs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Proof(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proofs"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # Null folder = a root-level proof directly under the system.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proof_folders.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # The proof source text; verified against the system by the engine.
    source: Mapped[str] = mapped_column(Text, server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Cached `proof.data()` payload and last-known validity (null = never checked).
    result: Mapped[dict | None] = mapped_column(JSONB)
    valid: Mapped[bool | None] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    formal_system: Mapped["FormalSystem"] = relationship(back_populates="proofs")
    folder: Mapped["ProofFolder | None"] = relationship(back_populates="proofs")
    theorems: Mapped[list["Theorem"]] = relationship(back_populates="proof")

    references: Mapped[list["Proof"]] = relationship(
        secondary=proof_references,
        primaryjoin=lambda: Proof.id == proof_references.c.proof_id,
        secondaryjoin=lambda: Proof.id == proof_references.c.references_id,
        back_populates="referenced_by",
    )
    referenced_by: Mapped[list["Proof"]] = relationship(
        secondary=proof_references,
        primaryjoin=lambda: Proof.id == proof_references.c.references_id,
        secondaryjoin=lambda: Proof.id == proof_references.c.proof_id,
        back_populates="references",
    )


class Theorem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A searchable statement established by a proof.

    Forward-looking and currently unpopulated. Two search paths are provisioned:
    `pattern` (a canonical/normalised statement AST) for structural, pattern-based
    lookups via GIN, and `embedding` for semantic / AI similarity via HNSW — both
    queryable in the same store and joinable back to the proof that proves them.
    """

    __tablename__ = "theorems"
    __table_args__ = (
        # Structural, pattern-based search over the normalised statement AST.
        Index("ix_theorems_pattern", "pattern", postgresql_using="gin"),
        # Semantic / AI similarity search over embeddings (cosine distance).
        Index(
            "ix_theorems_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    proof_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proofs.id", ondelete="SET NULL"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    pattern: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    formal_system: Mapped["FormalSystem"] = relationship(back_populates="theorems")
    proof: Mapped["Proof | None"] = relationship(back_populates="theorems")
