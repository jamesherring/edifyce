"""Structured storage for definition side-conditions (provisos).

A definition may carry a proviso — "``x`` and ``y`` share no variable", "``x``
does not occur in ``φ``" — drawn from the kernel's closed side-condition algebra
(:mod:`website.logical.kernel.side_conditions`). The decomposition used to keep
that as an opaque ``definitions.condition`` string; this table stores it as the
algebra tree it actually is, so a proviso's shape is queryable in plain SQL —
"which definitions have a disjoint-variable proviso", "which mention the
``setvar`` sort" — with no parsing.

Each row is one algebra node, mirroring the kernel vocabulary:

* leaf predicates — ``occurs``, ``equal``, ``disjoint``, ``atom`` — reference the
  definition's metavariables by name (``left_name`` / ``right_name``) and, for
  ``disjoint`` / ``atom``, an optional sort via ``sort_symbol_id`` (a real FK into
  the symbol namespace, not a name string);
* combinators — ``not`` (one child), ``and`` / ``or`` (ordered children).

Structure is a tree: ``parent_id`` is null on the root and set on children;
``definition_id`` is carried on *every* node (so a leaf predicate is found and
joined back to its definition without walking the tree). One root per definition
is enforced by a partial unique index.

The bridge to the kernel/surface syntax is :mod:`app.db.side_conditions_mapping`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.systems import DefinitionRow, SymbolRow

# `kind` values — a closed set mirroring the kernel algebra. Plain string column
# (not a DB enum) so extending the vocabulary needs no migration.
SIDE_KIND_OCCURS = "occurs"
SIDE_KIND_EQUAL = "equal"
SIDE_KIND_DISJOINT = "disjoint"
SIDE_KIND_ATOM = "atom"
SIDE_KIND_NOT = "not"
SIDE_KIND_AND = "and"
SIDE_KIND_OR = "or"


class SideConditionRow(Base):
    __tablename__ = "side_conditions"
    __table_args__ = (
        # A definition has at most one proviso tree, so at most one root node.
        # Partial on the root: every node shares a definition_id, so the predicate
        # must reach both dialects (Postgres for the migration, SQLite for tests) —
        # without it SQLite would make it a full unique and reject the tree.
        Index(
            "uq_side_conditions_definition_root",
            "definition_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
            sqlite_where=text("parent_id IS NULL"),
        ),
        # "which definitions have an <X> proviso" — search by predicate kind.
        Index("ix_side_conditions_definition_kind", "definition_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("definitions.id", ondelete="CASCADE"), index=True
    )
    # Null on the root; the parent node otherwise. Self-FK within the tree.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("side_conditions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    kind: Mapped[str] = mapped_column(String(16))
    # Metavariable arguments of a leaf predicate, by role:
    #   occurs(needle, haystack) -> (left_name, right_name)
    #   equal(left, right)       -> (left_name, right_name)
    #   disjoint(left, right)    -> (left_name, right_name)
    #   atom(name)               -> (left_name, -)
    # Null on the not/and/or combinators.
    left_name: Mapped[str | None] = mapped_column(String(128))
    right_name: Mapped[str | None] = mapped_column(String(128))
    # The optional sort of a disjoint/atom predicate — a reference into the
    # symbol namespace (same symbols the grammar is built from), not a name.
    sort_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )

    definition: Mapped[DefinitionRow] = relationship(back_populates="side_conditions")
    sort_symbol: Mapped[SymbolRow | None] = relationship()
    parent: Mapped[SideConditionRow | None] = relationship(
        remote_side="SideConditionRow.id", back_populates="children"
    )
    children: Mapped[list[SideConditionRow]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="SideConditionRow.position",
    )
