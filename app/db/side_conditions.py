"""Structured storage for side-conditions (provisos).

A definition or an inference rule may carry a proviso — "``x`` and ``y`` share no
variable", "``x`` does not occur in ``φ``" — drawn from the kernel's closed
side-condition algebra (:mod:`website.logical.kernel.side_conditions`). Rather
than an opaque string, this table stores it as the algebra tree it actually is,
so a proviso's shape is queryable in plain SQL — "which rules have a freshness
proviso", "which mention the ``setvar`` sort" — with no parsing.

Each row is one algebra node, mirroring the kernel vocabulary:

* leaf predicates — ``occurs``, ``equal``, ``disjoint``, ``atom`` — reference the
  owner's metavariables by name (``left_name`` / ``right_name``) and, for
  ``disjoint`` / ``atom``, an optional sort via ``sort_symbol_id`` (a real FK into
  the symbol namespace, not a name string);
* combinators — ``not`` (one child), ``and`` / ``or`` (ordered children).

A node belongs to exactly one owner — a definition *or* a rule — via the
``definition_id`` / ``rule_id`` either-or FK (a CHECK enforces exactly one). The
owner id is carried on *every* node, so a leaf predicate is found and joined back
to its owner without walking the tree. Structure is a tree: ``parent_id`` is null
on the root and set on children; a partial unique index keeps one root per owner.

The bridge to the kernel/surface syntax is :mod:`app.db.side_conditions_mapping`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.systems import DefinitionRow, RuleRow, SymbolRow

# `kind` values — a closed set mirroring the kernel algebra. Plain string column
# (not a DB enum) so extending the vocabulary needs no migration.
SIDE_KIND_OCCURS = "occurs"
SIDE_KIND_EQUAL = "equal"
SIDE_KIND_DISJOINT = "disjoint"
SIDE_KIND_ATOM = "atom"
SIDE_KIND_MEMBER = "member"
SIDE_KIND_NOT = "not"
SIDE_KIND_AND = "and"
SIDE_KIND_OR = "or"


class SideConditionRow(Base):
    __tablename__ = "side_conditions"
    __table_args__ = (
        # Exactly one owner: a definition or a rule, never both/neither. Written
        # so it holds on both Postgres and SQLite (no num_nonnulls()).
        # The convention prepends ``ck_<table>_``; name only the discriminator so
        # the constraint lands as ``ck_side_conditions_one_owner``, not doubled.
        CheckConstraint(
            "(definition_id IS NULL) <> (rule_id IS NULL)",
            name="one_owner",
        ),
        # One proviso tree per owner, so at most one root node per owner. Partial
        # on the root: the owner id is on every node, so the predicate must reach
        # both dialects (Postgres for the migration, SQLite for tests) — without it
        # SQLite would make it a full unique and reject the tree. NULLs are
        # distinct, so a rule-owned root (definition_id NULL) is exempt from the
        # definition index, and vice versa.
        Index(
            "uq_side_conditions_definition_root",
            "definition_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
            sqlite_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_side_conditions_rule_root",
            "rule_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
            sqlite_where=text("parent_id IS NULL"),
        ),
        # "which definitions/rules have an <X> proviso" — search by predicate kind.
        Index("ix_side_conditions_definition_kind", "definition_id", "kind"),
        Index("ix_side_conditions_rule_kind", "rule_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    # Either-or owner (see the CHECK above). Both nullable; exactly one is set.
    definition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("definitions.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), index=True
    )
    # Null on the root; the parent node otherwise. Self-FK within the tree.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("side_conditions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    kind: Mapped[str] = mapped_column(String(16))
    # Arguments of a leaf predicate, by role:
    #   occurs(needle, haystack) -> (left_name, right_name)
    #   equal(left, right)       -> (left_name, right_name)
    #   disjoint(left, right)    -> (left_name, right_name)
    #   atom(name)               -> (left_name, -)
    # Null on the not/and/or combinators. An argument is either a metavariable
    # *name* or a literal *term* expression (its surface string, possibly using
    # defined notation and the owner's metavariables); the `*_is_term` flags record
    # which — set once at write time so that dropping a binding a stored *metavar*
    # argument still names is caught, while a term argument is validated on compile.
    left_name: Mapped[str | None] = mapped_column(String(512))
    right_name: Mapped[str | None] = mapped_column(String(512))
    left_is_term: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    right_is_term: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # The optional sort of a disjoint/atom predicate — a reference into the
    # symbol namespace (same symbols the grammar is built from), not a name.
    sort_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )

    definition: Mapped[DefinitionRow | None] = relationship(back_populates="side_conditions")
    rule: Mapped[RuleRow | None] = relationship(back_populates="side_conditions")
    sort_symbol: Mapped[SymbolRow | None] = relationship()
    parent: Mapped[SideConditionRow | None] = relationship(
        remote_side="SideConditionRow.id", back_populates="children"
    )
    children: Mapped[list[SideConditionRow]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="SideConditionRow.position",
    )
