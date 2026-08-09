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
  The email/password auth routes are wired in `app/auth/`; the OAuth routers are
  not mounted yet (they need per-provider client secrets).
* **Search-ready theorems.** A `theorems` table points at the statement's
  kernel-term DAG in the `terms` graph (`app/db/terms.py`) for structural,
  pattern-based search in plain SQL, and carries a pgvector `embedding` (for
  semantic / AI search via an HNSW index). Nothing writes to it yet; the
  tables and indexes are in place so the search work is additive later.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, uuid_pk_column

if TYPE_CHECKING:
    from app.db.promoted_theorems import PromotedTheoremRow
    from app.db.proof_lines import ProofLineRow
    from app.db.avoidances import LabelAvoidanceRow
    from app.db.descriptions import LabelDescriptionRow
    from app.db.systems import NotationPieceRow, NotationRuleRow
    from app.db.terms import TermRow

# JSONB on Postgres (the real deployment), generic JSON elsewhere so a SQLite
# test database can create the table. Same `jsonb` DDL on Postgres, so no drift.
_JSON = JSON().with_variant(JSONB(), "postgresql")

# Match this to the embedding model you deploy (e.g. Voyage voyage-3 = 1024,
# OpenAI text-embedding-3-small = 1536). Changing it is a schema migration.
EMBEDDING_DIMENSIONS = 1536

# pgvector lives in an extension. Emitting its creation on `before_create` puts
# it into the schema the Atlas provider dumps (which runs metadata.create_all on
# a mock engine), so the `vector` type and HNSW index resolve. Guarded to
# Postgres so a non-PG create_all (e.g. a future SQLite test) doesn't choke on it.
# **pgvector 0.8 or later** is required in a real deployment, not merely the
# extension. `label_embeddings` searches an HNSW index under a `formal_system_id`
# filter, and before 0.8 the approximate scan produces its candidates before the
# filter runs — so a search comes back short, or empty, with matching rows sitting
# right there. `hnsw.iterative_scan` (0.8+) is what makes that recall correct, and
# `app.db.label_embeddings._iterative_scan` sets it per query. An older server
# still runs: the setting is probed rather than assumed, and its absence costs
# recall under a filter rather than raising.
event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS vector").execute_if(dialect="postgresql"),
)

# Trigram indexes, for the same reason and by the same mechanism. What they cover
# is the prose search (`app/db/label_search.py`): a `%word%` pattern is unanchored,
# so no btree can serve it and the planner reads every row of the largest text
# table in the schema. Measured on a 50,550-row corpus, a selective query is
# 419 ms unindexed and 10 ms indexed — and it is the *unbounded* half that
# decides this rather than the ratio, since the route is one an anonymous caller
# may hit and every other public listing here is bounded by an index.
#
# Postgres-only, like `vector` and for the same reason: a SQLite test database
# has neither the extension nor the access method, and its `LIKE` reads every row
# regardless. The indexes are declared with `postgresql_using`, which a non-PG
# `create_all` skips.
event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS pg_trgm").execute_if(dialect="postgresql"),
)


def _trigram_index(table: str, column: str) -> Index:
    """A GIN trigram index over one searchable text column.

    One per column rather than one composite, because the search's predicate is
    an `OR` across the three and Postgres answers that with a `BitmapOr` of three
    index scans — a composite would serve none of the arms. All three have to
    exist or the planner falls back to scanning for the whole predicate, so they
    are a set rather than three independent decisions.

    A pattern shorter than three characters has no trigram and falls back to a
    scan whatever is indexed. That is a real hole and a narrow one: it is a query
    of one or two letters, which on a corpus matches most of it anyway.
    """
    return Index(
        f"ix_{table}_{column}_trgm",
        column,
        postgresql_using="gin",
        postgresql_ops={column: "gin_trgm_ops"},
    )


class User(SQLAlchemyBaseUserTableUUID, TimestampMixin, Base):
    __tablename__ = "users"

    # The base contributes id, email, hashed_password, is_active, is_superuser,
    # is_verified. We override id to a DB-side default so every table generates
    # ids the same way (the base defaults to a client-side uuid4), and give the
    # boolean flags DB-side defaults too — the base declares them NOT NULL with
    # only a Python-side default, which leaves the column with no server default
    # (unsafe for non-ORM inserts and for adding the column to a populated table).
    id: Mapped[uuid.UUID] = uuid_pk_column()
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
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
    id: Mapped[uuid.UUID] = uuid_pk_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class FormalSystem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "formal_systems"
    __table_args__ = (
        # A user's own systems are addressable by a unique slug. Scoped to owned
        # rows: owner_id is nullable and Postgres treats NULLs as distinct, so an
        # unqualified unique index would not constrain public (ownerless) systems
        # anyway — the partial predicate makes that explicit rather than accidental.
        Index(
            "uq_formal_systems_owner_slug",
            "owner_id",
            "slug",
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
    )

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Where the system came from, when it was not authored here — one sentence,
    # recorded by whatever built it. On the system rather than on its proofs
    # because it is a fact about the corpus: an import writes it once instead of
    # copying it onto 47,000 rows, and every proof filed against the system (or
    # against a layer of its spine) reads the same one. Null for anything a user
    # wrote themselves.
    provenance: Mapped[str | None] = mapped_column(Text)
    # System inheritance (the old `inherits_from` self-FK). SET NULL so deleting a
    # base system orphans rather than cascades away its descendants.
    inherits_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="SET NULL"), index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Whether the system's notation is written with every token whitespace-
    # separated (see declarative.SystemSpec.token_separated). A promise about how
    # proofs are written, so it is stored with the system rather than derived.
    token_separated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

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
    # How this system's terms may be *read*, as against how they are written. Each
    # named notation is a set of substitute templates; the grammar is unaffected.
    notation_pieces: Mapped[list["NotationPieceRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan",
        order_by="NotationPieceRow.position",
    )
    # The other half of a notation: spellings matched by *shape* rather than by
    # production name, which is what reaches `( sqrt ` 2 )` as `\sqrt{2}`.
    notation_rules: Mapped[list["NotationRuleRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan",
        order_by="NotationRuleRow.position",
    )
    # What this system says about the labels it names — prose and authorship, for
    # productions, definitions, theorems and proofs alike (app/db/descriptions.py).
    label_descriptions: Mapped[list["LabelDescriptionRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan",
        order_by="LabelDescriptionRow.label",
    )
    # What the file declares a statement's proof does *without* — its `$j usage
    # … avoids …` directives (app/db/avoidances.py). Nothing should read it as a
    # collection: an imported corpus has thousands, and `avoided_by` asks for one
    # label's at a time.
    #
    # `passive_deletes` because the FK already says `ON DELETE CASCADE`, so the
    # database removes them and the ORM never loads them to do it itself. Without
    # it, deleting a system pulls 3,107 rows into memory to delete them one by one
    # — and a `lazy="raise"` collection is *still* loaded by the cascade, so the
    # declaration alone does not prevent it.
    label_avoidances: Mapped[list["LabelAvoidanceRow"]] = relationship(
        back_populates="system",
        cascade="all, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )
    proofs: Mapped[list["Proof"]] = relationship(
        back_populates="formal_system", cascade="all, delete-orphan"
    )
    theorems: Mapped[list["Theorem"]] = relationship(
        back_populates="formal_system", cascade="all, delete-orphan"
    )

    # The system's grammar/rules/definitions, decomposed into indexable rows (the
    # canonical form — there is no `source`/`compiled` blob). Defined in
    # app/db/systems.py; the engine is rebuilt from these via systems_mapping.
    brackets: Mapped[list["BracketRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="BracketRow.position"
    )
    symbols: Mapped[list["SymbolRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="SymbolRow.position"
    )
    lines: Mapped[list["LineRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="LineRow.position"
    )
    definitions: Mapped[list["DefinitionRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="DefinitionRow.position"
    )
    axioms: Mapped[list["AxiomRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="AxiomRow.position"
    )
    rules: Mapped[list["RuleRow"]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="RuleRow.position"
    )
    # The system's citable library — proved and imported theorems. Deliberately
    # *not* loaded with the rest of a system: an imported corpus has tens of
    # thousands, and a verify resolves only the labels its proof cites (see
    # app/db/promoted_theorems.py). Declared so the cascade reaches them; nothing
    # should read it as a collection.
    promoted_theorems: Mapped[list["PromotedTheoremRow"]] = relationship(
        back_populates="system",
        cascade="all, delete-orphan",
        order_by="PromotedTheoremRow.position",
        lazy="raise",
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
    # What the folder is *about*. An imported corpus fills it from the prose a
    # section header carries after its title — 308 of set.mm's do, and the
    # part-level ones run to hundreds of lines, so it is unbounded like every
    # other body of prose here.
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    formal_system: Mapped["FormalSystem"] = relationship(back_populates="folders")
    parent: Mapped["ProofFolder | None"] = relationship(
        remote_side="ProofFolder.id", back_populates="children"
    )
    children: Mapped[list["ProofFolder"]] = relationship(back_populates="parent")
    proofs: Mapped[list["Proof"]] = relationship(back_populates="folder")


# Proof-to-proof dependency graph (the old `references` self-M2M). Directed:
# a row (proof_id -> references_id) means `proof_id` cites `references_id` as a
# lemma. An association object rather than a bare M2M, because the edge carries
# attributes: the citation `alias` a proof uses to name the reference in its
# source (`[alias.line]`), and a `position` for display order.
class ProofReference(Base):
    __tablename__ = "proof_references"
    __table_args__ = (
        # The citation alias must be unique within the citing proof so
        # `[alias.line]` resolves to exactly one referenced proof.
        Index("uq_proof_references_proof_alias", "proof_id", "alias", unique=True),
    )

    proof_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proofs.id", ondelete="CASCADE"), primary_key=True
    )
    references_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proofs.id", ondelete="CASCADE"), primary_key=True
    )
    # The label the citing proof uses for this reference in its source.
    alias: Mapped[str] = mapped_column(String(64), server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    # Two FKs to the same table, so each relationship names its own.
    proof: Mapped["Proof"] = relationship(
        foreign_keys=[proof_id], back_populates="reference_links"
    )
    referenced: Mapped["Proof"] = relationship(
        foreign_keys=[references_id], back_populates="referenced_by_links"
    )


class Proof(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proofs"
    __table_args__ = (
        # The second haystack of the prose search: a proof authored here carries
        # its own title and description and gets no `label_descriptions` row, so
        # searching only those would answer with the imported half of a system.
        # An imported corpus is 47,589 proofs, so this side needs the index for
        # the same reason the first does.
        _trigram_index("proofs", "name"),
        _trigram_index("proofs", "title"),
        _trigram_index("proofs", "description"),
    )

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
    # A human sentence for the proof, beside `name`, which is its identity. The
    # two coincide for a hand-authored proof and part ways on an import, where
    # `name` is the Metamath label a citation must spell (`sqrt2irr`) and the
    # title is what the file's comment opens with ("The square root of 2 is
    # irrational."). Unbounded: `set.mm`'s longest runs to 438 characters.
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # The proof source text; verified against the system by the engine.
    source: Mapped[str] = mapped_column(Text, server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Cached `proof.data()` payload and last-known validity (null = never checked).
    result: Mapped[dict | None] = mapped_column(_JSON)
    valid: Mapped[bool | None] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The library entry this proof *establishes*, when it establishes one — set by
    # a corpus import, where a proof and a promoted theorem are two views of one
    # Metamath `$p`. What it buys is scope: the theorem's own `$e` hypotheses are
    # citable from this proof and nowhere else, and this is the link that says
    # which proof "this one" is (see app/db/promoted_theorems_mapping.py).
    # SET NULL rather than CASCADE — losing the library entry must not delete the
    # proof that established it.
    theorem_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="SET NULL"), index=True
    )

    # One-directional to the owning user (single FK, so no back_populates needed).
    # A relationship adds no column, so this needs no migration.
    owner: Mapped["User | None"] = relationship()
    formal_system: Mapped["FormalSystem"] = relationship(back_populates="proofs")
    folder: Mapped["ProofFolder | None"] = relationship(back_populates="proofs")
    theorems: Mapped[list["Theorem"]] = relationship(back_populates="proof")
    # The library entry above, as an object — so a read can say whether this
    # proof has been promoted without a second query. `foreign_keys` because the
    # two tables now reference each other: this side says which entry the proof
    # establishes, `promoted_theorems.proved_by_id` says which proof warrants the
    # entry, and only the first is this column. One-directional, so neither
    # relationship has to declare an overlap with the other.
    theorem: Mapped["PromotedTheoremRow | None"] = relationship(
        foreign_keys=[theorem_id]
    )

    # Outgoing reference edges (the lemmas this proof cites), owned by this proof
    # so editing/deleting them cascades. Ordered for stable display.
    reference_links: Mapped[list["ProofReference"]] = relationship(
        foreign_keys="ProofReference.proof_id",
        back_populates="proof",
        cascade="all, delete-orphan",
        order_by="ProofReference.position",
    )
    # Incoming edges (the proofs that cite this one) — read-only, for a future
    # "used by" surface. Not owned here, so no cascade.
    referenced_by_links: Mapped[list["ProofReference"]] = relationship(
        foreign_keys="ProofReference.references_id",
        back_populates="referenced",
        viewonly=True,
    )

    # The proof decomposed into structural rows — one per source line, each
    # formula interned into the term graph (see app/db/proof_lines.py). Derived
    # from `source` by the last verification and dropped whenever `valid` is, so
    # it is never loaded to decide anything the engine owns.
    line_rows: Mapped[list["ProofLineRow"]] = relationship(
        back_populates="proof",
        cascade="all, delete-orphan",
        order_by="ProofLineRow.position",
        foreign_keys="ProofLineRow.proof_id",
    )


class Theorem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A searchable statement established by a proof.

    Forward-looking and currently unpopulated. Two search paths are provisioned:
    `statement_term_id` — the root of the statement's kernel-term DAG in the
    `terms` graph (see `app/db/terms.py`) — for structural, pattern-based lookups
    in plain SQL, and `embedding` for semantic / AI similarity via HNSW. Both
    live in the same store and join back to the proof that proves them.
    """

    __tablename__ = "theorems"
    __table_args__ = (
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
    # Root of the statement's structure in the terms graph. Not CASCADE/SET NULL:
    # a term row must not be deletable out from under a theorem. Deleting the
    # system removes both, but in an order it has to set itself — see
    # `terms_mapping.delete_system_terms`.
    statement_term_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("terms.id"), index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    formal_system: Mapped["FormalSystem"] = relationship(back_populates="theorems")
    proof: Mapped["Proof | None"] = relationship(back_populates="theorems")
    statement_term: Mapped["TermRow | None"] = relationship()
