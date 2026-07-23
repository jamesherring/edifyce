"""Normalised formal-system storage, built on one unified symbol table.

A system's grammar is a namespace of **symbols** — named patterns. A *sort*
(``formula``, ``term``) is a symbol of kind ``union``; a *production*
(``variable``, ``membership: s ∈ t``) is a symbol of kind ``regex`` or
``template`` that belongs to a union via ``member_of_union_id``. This mirrors
the engine, where sorts and productions live in one pattern namespace.

Every reference to the grammar is a **foreign key into symbols**, not a name
string: a binding's type, a definition's attach-point, a line type's logical
sort. So renaming a symbol updates one row and all references follow — there is
no free-text name to leave dangling (the failure the old sorts/productions split
allowed). ``app.db.systems_mapping`` projects these rows to and from the
declarative ``SystemSpec`` (whose sorts/bindings are still names), so the engine
round-trip is unchanged behind the mapping.

Ordering that matters carries an explicit ``position`` column, replayed via
``order_by``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from app.db.side_conditions import SideConditionRow


def _system_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True)


def _position() -> Mapped[int]:
    return mapped_column(Integer, server_default=text("0"))


def _symbol_fk() -> Mapped[uuid.UUID]:
    # A reference into the symbol namespace (a binding's type, a definition's
    # attach-point). CASCADE keeps the DB consistent on whole-system / symbol
    # deletion; the API blocks deleting a still-referenced symbol (409) so the
    # cascade never silently removes a live reference in normal use.
    return mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"), index=True)


# ---------------------------------------------------------------------------
# Symbols: sorts (unions) and productions (leaves/composites) in one namespace
# ---------------------------------------------------------------------------


class SymbolRow(Base):
    __tablename__ = "symbols"
    __table_args__ = (Index("uq_symbols_system_name", "system_id", "name", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128), index=True)
    # "union" (a sort), or a production: "regex", "composite", or "atom".
    kind: Mapped[str] = mapped_column(String(16))
    template: Mapped[str | None] = mapped_column(String(512))
    regex: Mapped[str | None] = mapped_column(String(512))
    # For kind="atom": the constant's literal token (`atom_value`) XOR the
    # indexed family's base (`atom_base`, e.g. "p" for the p_# family).
    atom_value: Mapped[str | None] = mapped_column(String(512))
    atom_base: Mapped[str | None] = mapped_column(String(128))
    # The union (sort) this symbol belongs to — "membership is a formula". Null
    # for a top-level sort. Self-FK within symbols.
    member_of_union_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )

    system: Mapped[FormalSystem] = relationship(back_populates="symbols")
    union: Mapped[SymbolRow | None] = relationship(
        remote_side="SymbolRow.id", back_populates="members"
    )
    members: Mapped[list[SymbolRow]] = relationship(
        back_populates="union", order_by="SymbolRow.position", viewonly=True
    )
    # A production's bindings (`with s as term`). Empty for a union.
    bindings: Mapped[list[ProductionBindingRow]] = relationship(
        back_populates="production",
        cascade="all, delete-orphan",
        order_by="ProductionBindingRow.position",
        foreign_keys="ProductionBindingRow.production_id",
    )


class ProductionBindingRow(Base):
    __tablename__ = "production_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    symbol_id: Mapped[uuid.UUID] = _symbol_fk()

    production: Mapped[SymbolRow] = relationship(
        foreign_keys=[production_id], back_populates="bindings"
    )
    symbol: Mapped[SymbolRow] = relationship(foreign_keys=[symbol_id])


# ---------------------------------------------------------------------------
# Notation
# ---------------------------------------------------------------------------


class BracketRow(Base):
    __tablename__ = "notation_brackets"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    opening: Mapped[str] = mapped_column(String(16))
    closing: Mapped[str] = mapped_column(String(16))

    system: Mapped[FormalSystem] = relationship(back_populates="brackets")


# ---------------------------------------------------------------------------
# Line types
# ---------------------------------------------------------------------------


class LineRow(Base):
    __tablename__ = "line_types"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128))
    shape: Mapped[str] = mapped_column(String(256))
    # The subproof scope this line opens, orthogonal to its logical behaviour:
    # NULL (a plain line), "assumption" or "variable". Mirrors LineType.scope /
    # declarative LineSpec.scope.
    scope: Mapped[str | None] = mapped_column(String(16))
    # Which sort the logical placeholder ranges over (a symbol reference).
    logical_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )

    system: Mapped[FormalSystem] = relationship(back_populates="lines")
    logical_symbol: Mapped[SymbolRow | None] = relationship()
    parts: Mapped[list[LinePartRow]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="LinePartRow.position"
    )


class LinePartRow(Base):
    __tablename__ = "line_parts"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("line_types.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128))
    regex: Mapped[str] = mapped_column(String(512))

    line: Mapped[LineRow] = relationship(back_populates="parts")


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


class DefinitionRow(Base):
    __tablename__ = "definitions"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    # The symbol (usually a sort) this abbreviation attaches to.
    symbol_id: Mapped[uuid.UUID] = _symbol_fk()
    name: Mapped[str] = mapped_column(String(128), index=True)
    higher: Mapped[str] = mapped_column(String(512))
    lower: Mapped[str] = mapped_column(String(512))

    system: Mapped[FormalSystem] = relationship(back_populates="definitions")
    symbol: Mapped[SymbolRow] = relationship()
    bindings: Mapped[list[DefinitionBindingRow]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="DefinitionBindingRow.position",
    )
    # The proviso (`where` clause), stored as the kernel side-condition algebra
    # tree rather than an opaque string. All nodes of the tree, flat; the root is
    # the parent-less one. Defined in app/db/side_conditions.py.
    side_conditions: Mapped[list["SideConditionRow"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class DefinitionBindingRow(Base):
    __tablename__ = "definition_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("definitions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    symbol_id: Mapped[uuid.UUID] = _symbol_fk()

    definition: Mapped[DefinitionRow] = relationship(back_populates="bindings")
    symbol: Mapped[SymbolRow] = relationship()


# ---------------------------------------------------------------------------
# Axioms
# ---------------------------------------------------------------------------


class AxiomRow(Base):
    __tablename__ = "axioms"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    label: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    formula: Mapped[str] = mapped_column(String(512))

    system: Mapped[FormalSystem] = relationship(back_populates="axioms")
    bindings: Mapped[list[AxiomBindingRow]] = relationship(
        back_populates="axiom", cascade="all, delete-orphan", order_by="AxiomBindingRow.position"
    )


class AxiomBindingRow(Base):
    __tablename__ = "axiom_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    axiom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("axioms.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    symbol_id: Mapped[uuid.UUID] = _symbol_fk()

    axiom: Mapped[AxiomRow] = relationship(back_populates="bindings")
    symbol: Mapped[SymbolRow] = relationship()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    label: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    deduction: Mapped[str] = mapped_column(String(512))
    # How steps are checked against this rule: "structural" (term unification,
    # the default) or "string" (associative matching for a string-rewriting
    # rule). Mirrors InferenceRule.matching / declarative Rule.matching.
    matching: Mapped[str] = mapped_column(String(16), server_default=text("'structural'"))

    system: Mapped[FormalSystem] = relationship(back_populates="rules")
    antecedents: Mapped[list[RuleAntecedentRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleAntecedentRow.position"
    )
    bindings: Mapped[list[RuleBindingRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleBindingRow.position"
    )
    # Soundness provisos, stored as the kernel side-condition algebra (flat; the
    # root is the parent-less node). Defined in app/db/side_conditions.py.
    side_conditions: Mapped[list["SideConditionRow"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class RuleAntecedentRow(Base):
    __tablename__ = "rule_antecedents"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    pattern: Mapped[str] = mapped_column(String(512))

    rule: Mapped[RuleRow] = relationship(back_populates="antecedents")


class RuleBindingRow(Base):
    __tablename__ = "rule_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    symbol_id: Mapped[uuid.UUID] = _symbol_fk()

    rule: Mapped[RuleRow] = relationship(back_populates="bindings")
    symbol: Mapped[SymbolRow] = relationship()
