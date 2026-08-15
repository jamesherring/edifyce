"""The general edge between two systems: where a theorem transfers, and why.

`formal_systems.inherits_from_id` — the *spine* — is one relationship stated
well: single-parent, grammar-extending, and checkable by construction, which is
what a language tower wants (see `app/db/systems.py` and R1/R2). It cannot state
a second parent, a sort rename, a notation map, or a statement translation. This
table is those, and §5.4 of docs/system-relationships-roadmap.md is the design.

The spine is **not** folded in here. Reading it as an implicit `extension` edge
with identity maps costs nothing and keeps this table for the cases that need
it — and the case that must be checkable by construction stays the one that is.

**What an edge has to earn.** §2's rule is that a theorem transfers only when
every primitive of the source is a primitive of the target, or is discharged by
a theorem of the target with the same schematic generality. An `extension` edge
gets that for free, which is why inheritance never asks: every primitive is
present under its own name. An `interpretation` edge has to show it, one
obligation per source primitive, and `status` is the gate — a `draft` edge
resolves nothing, so a half-built edge cannot transfer a theorem on the strength
of the obligations that *are* discharged.

The sort and symbol maps are **empty for identity**, not filled with a row per
name. An edge between two systems that agree on their vocabulary is then a row
and nothing else, which is the common case and the one a second parent takes.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from app.db.promoted_theorems import PromotedTheoremRow

# What an edge claims, and therefore what it must discharge.
#
# `extension` — the target's language contains the source's and its theory
#   extends it, so every source primitive is a primitive here under the same
#   label. The degenerate case, and what the spine is.
# `interpretation` — the source's vocabulary is *translated* into the target's,
#   so each source primitive needs a theorem of the target standing in for it.
RELATION_KINDS = ("extension", "interpretation")

# `draft` transfers nothing; `discharged` is what makes a citation resolve. Kept
# as a column rather than derived from the obligation rows because an author
# builds an edge incrementally and the intermediate state is a real one — and
# because "resolves nothing" must be a single cheap read on the citation path.
RELATION_STATUSES = ("draft", "discharged")


def _relation_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        ForeignKey("system_relations.id", ondelete="CASCADE"), index=True
    )


class SystemRelationRow(Base):
    """One edge: theorems proved in ``source`` become citable in ``target``."""

    __tablename__ = "system_relations"
    __table_args__ = (
        # One edge per ordered pair. Two systems may relate in both directions —
        # that is two rows and two sets of obligations, not one symmetric edge —
        # but not twice the same way.
        Index(
            "uq_system_relations_source_target",
            "source_system_id",
            "target_system_id",
            unique=True,
        ),
        # The citation path's question: "which edges reach this system, and are
        # they discharged?" Asked on every verify in a system that has any.
        Index("ix_system_relations_target_status", "target_system_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    # CASCADE on both ends: an edge is a statement *about* two systems and means
    # nothing without either. Deleting a system that something inherits from is
    # refused (`systems.delete_system`) because the descendants' grammar would
    # change under them; an edge is not grammar, so it goes quietly.
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    target_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), server_default=text("'extension'"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # How the target restates a transferred theorem, when it states a different
    # *kind* of thing than the source does — `'G ⊢ {wff}'` for a Hilbert system
    # read into a sequent one (§5.4, §6.3). NULL is no wrap, which is what every
    # edge between two systems that agree about what a judgement is carries, and
    # what an `extension` edge carries always. Applied as a term construction:
    # see `website/logical/wrapping.py`.
    statement_template: Mapped[str | None] = mapped_column(String(512))

    source_system: Mapped[FormalSystem] = relationship(
        foreign_keys=[source_system_id]
    )
    target_system: Mapped[FormalSystem] = relationship(
        foreign_keys=[target_system_id]
    )
    sorts: Mapped[list[SystemRelationSortRow]] = relationship(
        back_populates="relation",
        cascade="all, delete-orphan",
        order_by="SystemRelationSortRow.position",
    )
    symbols: Mapped[list[SystemRelationSymbolRow]] = relationship(
        back_populates="relation",
        cascade="all, delete-orphan",
        order_by="SystemRelationSymbolRow.position",
    )
    extras: Mapped[list[SystemRelationExtraRow]] = relationship(
        back_populates="relation",
        cascade="all, delete-orphan",
        order_by="SystemRelationExtraRow.position",
    )
    obligations: Mapped[list[SystemRelationObligationRow]] = relationship(
        back_populates="relation",
        cascade="all, delete-orphan",
        order_by="SystemRelationObligationRow.position",
    )


class SystemRelationSortRow(Base):
    """One sort rename: the source's ``prop`` is the target's ``wff``.

    Absent means identity on the name, so an edge between systems that agree on
    their sorts carries no rows at all. Named rather than keyed by symbol id
    because the two systems' symbol tables are separate namespaces — the whole
    point of the map is that the names differ.
    """

    __tablename__ = "system_relation_sorts"
    __table_args__ = (
        Index(
            "uq_system_relation_sorts_source",
            "relation_id",
            "source_sort",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    relation_id: Mapped[uuid.UUID] = _relation_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    source_sort: Mapped[str] = mapped_column(String(128))
    target_sort: Mapped[str] = mapped_column(String(128))

    relation: Mapped[SystemRelationRow] = relationship(back_populates="sorts")


class SystemRelationSymbolRow(Base):
    """One notation rename, on the same contract as the sort map above."""

    __tablename__ = "system_relation_symbols"
    __table_args__ = (
        Index(
            "uq_system_relation_symbols_source",
            "relation_id",
            "source_symbol",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    relation_id: Mapped[uuid.UUID] = _relation_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    source_symbol: Mapped[str] = mapped_column(String(128))
    target_symbol: Mapped[str] = mapped_column(String(128))

    relation: Mapped[SystemRelationRow] = relationship(back_populates="symbols")


class SystemRelationExtraRow(Base):
    """One metavariable the statement template introduces — ``Γ : context``.

    A template says the target states a *different kind of thing* than the
    source, and the difference is usually something the source theorem never
    mentioned: a sequent's antecedent has no counterpart in a Hilbert formula.
    So these are not renames of anything. Each becomes a metavariable of every
    theorem that crosses the edge, which is what lets a citation instantiate `Γ`
    to whatever context the citing line happens to have.

    ``sort`` names one of the **target's** sorts, since that is the grammar the
    template is read against — after the edge's rename, not before it.
    """

    __tablename__ = "system_relation_extras"
    __table_args__ = (
        Index(
            "uq_system_relation_extras_name",
            "relation_id",
            "name",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    relation_id: Mapped[uuid.UUID] = _relation_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    name: Mapped[str] = mapped_column(String(128))
    sort: Mapped[str] = mapped_column(String(128))

    relation: Mapped[SystemRelationRow] = relationship(back_populates="extras")


class SystemRelationObligationRow(Base):
    """One source primitive, and what stands in for it in the target.

    §2's rule made into rows: a theorem transfers only when every primitive it
    could have used is available on the other side. Exactly one of the two
    discharge columns is set — a primitive of the target under some label, or a
    theorem the target has proved — and ``status`` says whether it has been.

    An `extension` edge fills these in from the spine and never asks an author:
    every primitive is present under its own name, so each obligation is
    ``discharged_by_primitive`` with the label it already has.
    """

    __tablename__ = "system_relation_obligations"
    __table_args__ = (
        Index(
            "uq_system_relation_obligations_label",
            "relation_id",
            "source_label",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    relation_id: Mapped[uuid.UUID] = _relation_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # The source's axiom or rule this obligation is about.
    source_label: Mapped[str] = mapped_column(String(128))
    # A label of the *target's* own rules, when the primitive is present there.
    discharged_by_primitive: Mapped[str | None] = mapped_column(String(128))
    # Or a theorem the target has proved. SET NULL rather than CASCADE: retiring
    # the theorem must not delete the obligation, it must leave it undischarged —
    # which is exactly what a NULL here with `status = 'draft'` says.
    discharged_by_theorem_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default=text("'draft'"))

    relation: Mapped[SystemRelationRow] = relationship(back_populates="obligations")
    theorem: Mapped[PromotedTheoremRow | None] = relationship()
