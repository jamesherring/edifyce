"""Normalised formal-system storage: a system decomposed into indexable rows.

Every declaration in a system becomes its own row with real foreign keys and no
nested documents or serialised blobs. Short strings such as a production template
(``s ∈ t``) or a definition's notation (``x ⊆ y``) are *atoms of the object
language* — the searchable leaf values — not opaque structure.

These rows are the canonical form of a system's grammar/rules/definitions: they
replace the old ``formal_systems.source`` text + ``compiled`` JSONB blob (dropped
in this revision). The bridge back to the engine is `app.db.systems_mapping`,
which rebuilds a `SystemSpec` from these rows; the spec lowers to ``.edi`` and
compiles. Adapted from the standalone `app/systems/` draft (PR #23) onto this
package's `Base`, UUID keys, and naming convention.

Ordering that matters (productions within a system, antecedents within a rule) is
carried by an explicit ``position`` column and replayed via ``order_by``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem


def _system_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )


def _position() -> Mapped[int]:
    return mapped_column(Integer, server_default=text("0"))


class BracketRow(Base):
    __tablename__ = "notation_brackets"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    opening: Mapped[str] = mapped_column(String(16))
    closing: Mapped[str] = mapped_column(String(16))

    system: Mapped[FormalSystem] = relationship(back_populates="brackets")


class SortRow(Base):
    __tablename__ = "sorts"
    __table_args__ = (Index("uq_sorts_system_name", "system_id", "name", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128), index=True)

    system: Mapped[FormalSystem] = relationship(back_populates="sorts")
    productions: Mapped[list[ProductionRow]] = relationship(back_populates="sort")


class ProductionRow(Base):
    __tablename__ = "productions"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    sort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sorts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128), index=True)
    # "composite" (a notation template with variable slots) or "regex" (a leaf).
    kind: Mapped[str] = mapped_column(String(16))
    template: Mapped[str | None] = mapped_column(String(512))
    regex: Mapped[str | None] = mapped_column(String(512))

    system: Mapped[FormalSystem] = relationship(back_populates="productions")
    sort: Mapped[SortRow] = relationship(back_populates="productions")
    bindings: Mapped[list[ProductionBindingRow]] = relationship(
        back_populates="production",
        cascade="all, delete-orphan",
        order_by="ProductionBindingRow.position",
    )


class ProductionBindingRow(Base):
    __tablename__ = "production_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    production_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    production: Mapped[ProductionRow] = relationship(back_populates="bindings")


class LineRow(Base):
    __tablename__ = "line_types"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    name: Mapped[str] = mapped_column(String(128))
    shape: Mapped[str] = mapped_column(String(256))
    logical_sort: Mapped[str | None] = mapped_column(String(128))

    system: Mapped[FormalSystem] = relationship(back_populates="lines")
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


class DefinitionRow(Base):
    __tablename__ = "definitions"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    # The pattern this abbreviation attaches to (e.g. "formula").
    sort: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    higher: Mapped[str] = mapped_column(String(512))
    lower: Mapped[str] = mapped_column(String(512))
    condition: Mapped[str | None] = mapped_column(String(512))

    system: Mapped[FormalSystem] = relationship(back_populates="definitions")
    bindings: Mapped[list[DefinitionBindingRow]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="DefinitionBindingRow.position",
    )


class DefinitionBindingRow(Base):
    __tablename__ = "definition_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("definitions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = _position()
    var: Mapped[str] = mapped_column(String(64))
    sort: Mapped[str] = mapped_column(String(128), index=True)

    definition: Mapped[DefinitionRow] = relationship(back_populates="bindings")


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
    sort: Mapped[str] = mapped_column(String(128), index=True)

    axiom: Mapped[AxiomRow] = relationship(back_populates="bindings")


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = _system_fk()
    position: Mapped[int] = _position()
    label: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    deduction: Mapped[str] = mapped_column(String(512))

    system: Mapped[FormalSystem] = relationship(back_populates="rules")
    antecedents: Mapped[list[RuleAntecedentRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleAntecedentRow.position"
    )
    bindings: Mapped[list[RuleBindingRow]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="RuleBindingRow.position"
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
    sort: Mapped[str] = mapped_column(String(128), index=True)

    rule: Mapped[RuleRow] = relationship(back_populates="bindings")
