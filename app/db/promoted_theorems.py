"""A system's citable library: proved and imported theorems, as rows.

An inference rule is a *primitive* the author declared, and a system has a
handful; `rules` holds them and `build_system` builds every one. A **promoted
theorem** is a result the system has established — or imported from a corpus —
and registered for schematic reuse. set.mm contributes 49,000 of them, so the two
cannot be stored the same way, and this table is what the difference costs.

**Both kinds live here, and both are resolved lazily.** The metamath roadmap's
§3.2 proposed splitting an imported library by kind — logical ``$a`` into `rules`,
``$p`` into a table of its own — so that an imported system's axioms would be real
`inference_rules`. Measurement says that does not scale: `build_system` builds
every rule eagerly, and set.mm's 1,559 axioms add seconds to a build that a
verify performs. So the split here is by *provenance* rather than by kind — the
handful an author declared against a library that arrived whole — and
``primitive`` records which of a library entry's two kinds it is, so "what are
this system's axioms?" is still one query.

Laziness is the point of the table. A proof cites a few dozen labels; promoting
one costs a parse of its statement against the grammar (0.4 ms at 18 productions,
1.1 ms at 309, and rising with the grammar as any parse does), so a verify loads
the labels its proof actually names and no more. See
``app/db/promoted_theorems_mapping.py`` and docs/verification-from-rows.md, P4.

The statement and premise **terms** are cached beside their text, exactly as a
rule's schema terms are (P3): a theorem whose digest still matches is rebuilt
with no parse at all, which is what "re-checks from rows alone" means.

For an imported corpus the cached term is also the *more faithful* of the two.
A walk promotes each theorem against the grammar as of its own position, while
the stored system is the union over the whole walk — so re-composing a statement
against that union can read it through notation declared later, which is the
capture the ordering exists to prevent (metamath roadmap §1). The digest covers
that union, so an unedited import always hits the cache and gets the term the
walk composed. It is the *fallback* that is approximate, and only for a system
whose grammar has since moved — where nothing else about the import is current
either.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from app.db.side_conditions import SideConditionRow
    from app.db.systems import SymbolRow


def _theorem_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        ForeignKey("promoted_theorems.id", ondelete="CASCADE"), index=True
    )


def _term_fk() -> Mapped[uuid.UUID | None]:
    # The composed kernel term of a statement, cached so promotion need not parse
    # it again. SET NULL, and a NULL is a *miss* rather than "composes to
    # nothing" — the same contract, and for the same reasons, as the schema-term
    # FKs on `rules` (see app/db/schema_terms.py).
    return mapped_column(
        ForeignKey("terms.id", ondelete="SET NULL"), index=True, nullable=True
    )


class PromotedTheoremRow(Base):
    __tablename__ = "promoted_theorems"
    __table_args__ = (
        # A citation names a theorem by label, so a label must resolve to one.
        Index("uq_promoted_theorems_system_label", "system_id", "label", unique=True),
        # "What are this system's axioms?" — the question the primitive/derived
        # split exists to answer, now that both live in one table.
        Index("ix_promoted_theorems_system_primitive", "system_id", "primitive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # The label a proof cites this theorem by.
    label: Mapped[str] = mapped_column(String(128), index=True)
    # The conclusion, in the system's own grammar. Unbounded: a set.mm statement
    # runs to hundreds of tokens, and Postgres stores a bounded and an unbounded
    # varchar identically.
    statement: Mapped[str] = mapped_column(Text)
    # Whether this is a *primitive* of its system (a Metamath logical `$a`) or a
    # derived result (`$p`). Read by nothing in checking — a citation of either is
    # checked identically, which is why one table serves both — and everything in
    # describing: it is what lets an imported system say what it assumes.
    primitive: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # How a citation is checked: "structural" or "string" (mirrors
    # InferenceRule.matching / PromotedTheorem.matching).
    matching: Mapped[str] = mapped_column(String(16), server_default=text("'structural'"))
    # The composed conclusion term, and the digest that says whether it — and
    # every premise term below — still means anything. See schema_terms.py for
    # the contract; this is the same one.
    statement_term_id: Mapped[uuid.UUID | None] = _term_fk()
    schema_digest: Mapped[str | None] = mapped_column(String(64))
    # The proof whose standing *warrants* this entry, for one promoted from a
    # proof stored here. NULL for an imported entry, whose warrant is the corpus
    # it came from — and that difference is the whole point of the column, since
    # retirement has to tell them apart: an edit that stops a local proof
    # standing withdraws what it established, while the same edit to an imported
    # proof withdraws nothing (the import is not re-derived from it).
    #
    # Distinct from `proofs.theorem_id`, which points the other way and means
    # something else: *that* says which entry's hypotheses a proof may cite, and
    # an import sets it too. A promoted entry has both; an imported one only the
    # latter. CASCADE, because an entry cannot outlive its only warrant.
    proved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proofs.id", ondelete="CASCADE"), index=True
    )

    system: Mapped[FormalSystem] = relationship(back_populates="promoted_theorems")
    premises: Mapped[list[PromotedTheoremPremiseRow]] = relationship(
        back_populates="theorem",
        cascade="all, delete-orphan",
        order_by="PromotedTheoremPremiseRow.position",
    )
    bindings: Mapped[list[PromotedTheoremBindingRow]] = relationship(
        back_populates="theorem",
        cascade="all, delete-orphan",
        order_by="PromotedTheoremBindingRow.position",
    )
    # The theorem's provisos, as the same side-condition algebra a rule's are
    # stored in — a Metamath `$d` becomes a `disjoint` leaf. Flat; the root is the
    # parent-less node.
    side_conditions: Mapped[list["SideConditionRow"]] = relationship(
        back_populates="promoted_theorem", cascade="all, delete-orphan"
    )


class PromotedTheoremPremiseRow(Base):
    __tablename__ = "promoted_theorem_premises"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    theorem_id: Mapped[uuid.UUID] = _theorem_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # A hypothesis of the theorem (a Metamath `$e`), in the system's grammar.
    statement: Mapped[str] = mapped_column(Text)
    # The label the theorem's *own proof* cites this hypothesis by (`mp2.1`).
    # Null for a premise that has none — a theorem promoted from anywhere but a
    # Metamath `${ … $}` block.
    #
    # A hypothesis is citable only from inside that block, which is why it is a
    # column here and not a library entry of its own: a `$e` registered as a
    # theorem would be a bare `|- ph` that proves anything, for anyone. The walk
    # enforces that by promoting them for the length of one check and withdrawing
    # them (`corpus._givens`); storage enforces it by making them reachable only
    # through the theorem that owns them (`load_theorems`'s `hypotheses_of`).
    label: Mapped[str | None] = mapped_column(String(128))
    term_id: Mapped[uuid.UUID | None] = _term_fk()

    theorem: Mapped[PromotedTheoremRow] = relationship(back_populates="premises")


class PromotedTheoremBindingRow(Base):
    __tablename__ = "promoted_theorem_bindings"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    theorem_id: Mapped[uuid.UUID] = _theorem_fk()
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # A metavariable of the theorem (a Metamath `$f`), re-instantiated at each
    # citation by unification.
    var: Mapped[str] = mapped_column(String(128))
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), index=True
    )

    theorem: Mapped[PromotedTheoremRow] = relationship(back_populates="bindings")
    symbol: Mapped[SymbolRow] = relationship()
