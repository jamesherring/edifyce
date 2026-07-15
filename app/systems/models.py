"""Flat ORM models: a formal system decomposed into indexable rows.

Every declaration in a system becomes its own row with real foreign keys and no
nested documents. Short strings such as a production template (``s ∈ t``) or a
definition's notation (``x ⊆ y``) are *atoms of the object language*, not
serialised structure -- they are the searchable leaf values, and none is an
opaque blob.

Ordering that matters (productions within a system, antecedents within a rule)
is carried by an explicit ``position`` column and replayed via ``order_by`` so a
reload reproduces declaration order exactly.

Design notes for the persistence layer that will adopt this (PR #13 follow-up):

* ``owner_id`` / publishing / timestamps are intentionally omitted here -- they
  live on the surrounding tables in the app schema. These models cover only the
  *formal-system decomposition*, the part that replaces the ``source`` /
  ``compiled`` blob.
* A production's own sort is a first-class :class:`SortRow` (hard FK). A
  *binding* or definition target names a pattern in the system's namespace,
  which may be either a sort (``formula``) or a production (``variable``); those
  references are stored as short name strings rather than over-constrained FKs.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FormalSystemRow(Base):
    __tablename__ = "formal_systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    slug: Mapped[str] = mapped_column(String(256), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # System inheritance (the engine's `inherit`): a system's effective grammar
    # is its own rows plus its ancestors', resolved by walking this self-FK.
    inherits_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="SET NULL"), index=True
    )

    brackets: Mapped[list[BracketRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="BracketRow.position"
    )
    sorts: Mapped[list[SortRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="SortRow.position"
    )
    productions: Mapped[list[ProductionRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="ProductionRow.position"
    )
    lines: Mapped[list[LineRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="LineRow.position"
    )
    definitions: Mapped[list[DefinitionRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="DefinitionRow.position"
    )
    axioms: Mapped[list[AxiomRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="AxiomRow.position"
    )
    rules: Mapped[list[RuleRow]] = relationship(
        back_populates="system", cascade="all, delete-orphan", order_by="RuleRow.position"
    )


class BracketRow(Base):
    __tablename__ = "notation_brackets"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    opening: Mapped[str] = mapped_column(String(16))
    closing: Mapped[str] = mapped_column(String(16))

    system: Mapped[FormalSystemRow] = relationship(back_populates="brackets")


class SortRow(Base):
    __tablename__ = "sorts"
    __table_args__ = (
        Index("uq_sorts_system_name", "system_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128), index=True)

    system: Mapped[FormalSystemRow] = relationship(back_populates="sorts")
    productions: Mapped[list[ProductionRow]] = relationship(back_populates="sort")


class ProductionRow(Base):
    __tablename__ = "productions"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    sort_id: Mapped[int] = mapped_column(ForeignKey("sorts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128), index=True)
    # "composite" (a notation template with variable slots) or "regex" (a leaf).
    kind: Mapped[str] = mapped_column(String(16))
    template: Mapped[str | None] = mapped_column(String(512))
    regex: Mapped[str | None] = mapped_column(String(512))

    system: Mapped[FormalSystemRow] = relationship(back_populates="productions")
    sort: Mapped[SortRow] = relationship(back_populates="productions")
    bindings: Mapped[list[ProductionBindingRow]] = relationship(
        back_populates="production",
        cascade="all, delete-orphan",
        order_by="ProductionBindingRow.position",
    )


class ProductionBindingRow(Base):
    __tablename__ = "production_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    production_id: Mapped[int] = mapped_column(
        ForeignKey("productions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    production: Mapped[ProductionRow] = relationship(back_populates="bindings")


class LineRow(Base):
    __tablename__ = "line_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128))
    shape: Mapped[str] = mapped_column(String(256))
    logical_sort: Mapped[str | None] = mapped_column(String(128))

    system: Mapped[FormalSystemRow] = relationship(back_populates="lines")
    parts: Mapped[list[LinePartRow]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="LinePartRow.position"
    )


class LinePartRow(Base):
    __tablename__ = "line_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("line_types.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128))
    regex: Mapped[str] = mapped_column(String(512))

    line: Mapped[LineRow] = relationship(back_populates="parts")


class DefinitionRow(Base):
    __tablename__ = "definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    # The pattern this abbreviation attaches to (e.g. "formula").
    sort: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    higher: Mapped[str] = mapped_column(String(512))
    lower: Mapped[str] = mapped_column(String(512))
    condition: Mapped[str | None] = mapped_column(String(512))

    system: Mapped[FormalSystemRow] = relationship(back_populates="definitions")
    bindings: Mapped[list[DefinitionBindingRow]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="DefinitionBindingRow.position",
    )


class DefinitionBindingRow(Base):
    __tablename__ = "definition_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("definitions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    definition: Mapped[DefinitionRow] = relationship(back_populates="bindings")


class AxiomRow(Base):
    __tablename__ = "axioms"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    formula: Mapped[str] = mapped_column(String(512))

    system: Mapped[FormalSystemRow] = relationship(back_populates="axioms")
    bindings: Mapped[list[AxiomBindingRow]] = relationship(
        back_populates="axiom", cascade="all, delete-orphan", order_by="AxiomBindingRow.position"
    )


class AxiomBindingRow(Base):
    __tablename__ = "axiom_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    axiom_id: Mapped[int] = mapped_column(ForeignKey("axioms.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    axiom: Mapped[AxiomRow] = relationship(back_populates="bindings")


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    deduction: Mapped[str] = mapped_column(String(512))

    system: Mapped[FormalSystemRow] = relationship(back_populates="rules")
    antecedents: Mapped[list[RuleAntecedentRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleAntecedentRow.position"
    )
    bindings: Mapped[list[RuleBindingRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleBindingRow.position"
    )


class RuleAntecedentRow(Base):
    __tablename__ = "rule_antecedents"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    pattern: Mapped[str] = mapped_column(String(512))

    rule: Mapped[RuleRow] = relationship(back_populates="antecedents")


class RuleBindingRow(Base):
    __tablename__ = "rule_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    rule: Mapped[RuleRow] = relationship(back_populates="bindings")
