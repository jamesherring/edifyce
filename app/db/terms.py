"""Term graph storage: kernel terms decomposed into shared, indexable rows.

The kernel's parse-once :class:`~website.logical.kernel.terms.Term` is a
hash-consed DAG — a statement's structure with maximal sharing between equal
subterms. These tables persist that DAG as rows (PR #23's follow-up replacing
the old ``theorems.pattern`` JSONB blob): one ``terms`` row per distinct
subterm, one ``term_children`` row per parent→child edge, so statement
structure is queryable in plain SQL — "top constructor is ``implication``",
"mentions the ``membership`` production", "which statements share this
subterm" — with no JSON scans and no recompiling.

Sharing carries over: rows are interned per system by a structural ``digest``,
so the subterm ``(z ∈ x)`` is stored once no matter how many theorems use it.
The bridge back to live kernel terms is :mod:`app.db.terms_mapping`.

Row kinds mirror the kernel's term kinds, plus one storage distinction:

* ``node`` — a production applied to child terms (or a ground leaf via
  ``literal``). ``constructor`` is the production's *name*, resolvable in the
  compiled system's namespace. Defined notation is a production too, named
  ``<sort>:<template>`` (e.g. ``formula:x ⊆ y``); a declared production's name
  cannot contain ``:``, so one lookup covers both and no separate row kind is
  needed. Such a node also carries ``sort``, because its constructor is not
  itself a member of the sort it inhabits.
* ``var`` / ``bound`` — a schematic variable / an abstract bound variable.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem

# `kind` values. A closed set, but deliberately a plain string column rather
# than a DB enum: adding a kind must not need a migration.
TERM_KIND_NODE = "node"
TERM_KIND_VAR = "var"
TERM_KIND_BOUND = "bound"


class TermRow(Base):
    __tablename__ = "terms"
    __table_args__ = (
        # The interning key: one row per distinct subterm per system.
        Index("uq_terms_system_digest", "formal_system_id", "digest", unique=True),
        # Structural search: statements by constructor within a system.
        Index("ix_terms_system_constructor", "formal_system_id", "constructor"),
        # "Same statement up to variable renaming" search: many exact terms map
        # to one alpha class, so this is non-unique (contrast the digest index).
        Index("ix_terms_system_alpha_digest", "formal_system_id", "alpha_digest"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    # node: production name / defined: the definition's higher template string.
    constructor: Mapped[str | None] = mapped_column(String(512))
    # Ground-leaf surface token (a Node with no children), e.g. the atom "a".
    literal: Mapped[str | None] = mapped_column(String(512), index=True)
    # Sort *name*: a var/bound's sort; for a defined node, the sort it inhabits.
    sort: Mapped[str | None] = mapped_column(String(128))
    var_name: Mapped[str | None] = mapped_column(String(128))
    bound_index: Mapped[int | None] = mapped_column(Integer)
    # Structural hash over (kind, constructor, literal, sort, child digests) —
    # see terms_mapping.digest_term. Scoped per system by the unique index.
    digest: Mapped[str] = mapped_column(String(64))
    # Structural hash invariant under consistent renaming of free variables —
    # see terms_mapping.alpha_digest. Non-unique: the "same statement up to
    # variable names" key. Nullable only to allow backfilling rows that predate
    # this column; store_term always populates it.
    alpha_digest: Mapped[str | None] = mapped_column(String(64))

    # Many-to-one only: no term collection on FormalSystem — a system's term
    # graph can be arbitrarily large, and must never be loaded as one list.
    formal_system: Mapped[FormalSystem] = relationship()
    children: Mapped[list[TermChildRow]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="TermChildRow.position",
        foreign_keys="TermChildRow.parent_id",
    )


class TermChildRow(Base):
    __tablename__ = "term_children"

    # One edge per (parent, slot). `position` is the slot's template order, so
    # reading children back in `position` order matches the surface notation.
    parent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Deliberately NOT ondelete=CASCADE: an edge must never outlive its child,
    # but deleting a shared child out from under other parents must fail. The
    # default NO ACTION checks at statement end, so a whole-system cascade
    # (which removes parents, edges, and children together) still passes.
    child_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terms.id"), index=True
    )

    parent: Mapped[TermRow] = relationship(
        back_populates="children", foreign_keys=parent_id
    )
    child: Mapped[TermRow] = relationship(foreign_keys=child_id)
