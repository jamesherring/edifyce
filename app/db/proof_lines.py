"""Proof structure: a checked proof decomposed into indexable rows.

A ``proofs`` row stores the proof as its author typed it — one ``source`` blob —
plus ``result``, a cached JSON snapshot of ``Proof.data()`` for the editor to
render. Neither is *structure*: the source is text the engine must re-parse, and
``result`` holds display strings, so "which proofs apply ``MP`` to a membership
formula" is unanswerable without recompiling every system and re-checking every
proof.

These tables are that structure, written when a proof is verified
(:mod:`app.db.proofs_mapping`). They are to a proof what ``app/db/systems.py``
is to a formal system and ``app/db/terms.py`` is to a statement — the same
"rows are canonical, the engine is rebuilt on demand" contract, extended to the
last thing still held only as text:

* **``proof_lines``** — one row per physical source line, carrying what the
  checker determined about it (its line type and behaviour, the citation number
  a reference names it by, its verdict) and, for a formula-bearing line, a
  ``term_id`` into the shared term graph. That FK is the point of the exercise:
  a proof's statements become the *same* interned kernel-term DAG the theorem
  search indexes, so a line and a theorem are searched by one mechanism.
* **``proof_line_antecedents``** — the justification graph: which lines a line
  was actually derived from, as edges rather than as a reference string to be
  re-parsed. Distinct from ``proof_references``, which is the coarser
  proof-to-proof edge; this is line-to-line, *within* one proof (a citation
  reaching into a cited lemma is recorded by proof id and citation number, since
  that proof owns its own line rows).

These rows are written when a proof is verified and dropped whenever its verdict
is invalidated, so they can never disagree with ``source``. They are no longer
only a *record* of that check: a verify reads its lines from here — the proof's
own and every cited lemma's — rather than parsing anything
(``proofs_mapping.load_proof_for_check``, ``load_proof_lines``). That is what
makes the invalidation soundness-critical rather than merely tidy. What a row
never supplies is a verdict: numbering, scope and justification are re-derived on
every check, so a row says what a line states and never whether it stands. See
``docs/verification-from-rows.md``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import Proof
    from app.db.terms import TermRow

# `role` values on an antecedent edge. A closed set, but a plain string column
# for the same reason as `terms.kind`: adding a role must not need a migration.
#
# `antecedent` — the line filled one of the rule's declared antecedent slots.
# `extra`      — a surplus cited line an `allow_extra_antecedents` rule tolerated.
# `subproof`   — the edge points at the *opener* of the subproof a discharge rule
#                consumed, since a discharge cites a block rather than a line.
ANTECEDENT_ROLE_ANTECEDENT = "antecedent"
ANTECEDENT_ROLE_EXTRA = "extra"
ANTECEDENT_ROLE_SUBPROOF = "subproof"


class ProofLineRow(Base):
    """One physical line of a checked proof."""

    __tablename__ = "proof_lines"
    __table_args__ = (
        # Source order is the row identity within a proof: `position` is the
        # line's index in the source, so it addresses blank and comment lines too
        # (which carry no citation `number`).
        Index("uq_proof_lines_proof_position", "proof_id", "position", unique=True),
        # "Which proofs cite this rule", "which lines failed" — in plain SQL.
        Index("ix_proof_lines_proof_number", "proof_id", "number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    proof_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proofs.id", ondelete="CASCADE"), index=True
    )
    # Index into the proof source's lines, blanks and commentary included.
    position: Mapped[int] = mapped_column(Integer)
    # The number a citation names this line by, or null for a line no citation
    # can reach (a blank line, commentary). Not derivable from `position`.
    number: Mapped[int | None] = mapped_column(Integer)
    indent: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # The line as rendered (the source line, stripped) — `indent` carries the
    # rest, so the pair reconstructs the source line exactly.
    display: Mapped[str] = mapped_column(Text, server_default="")
    # The matched line type's name and behaviour, or null when the line matched
    # none (an unparseable line is still stored — with its error — because a
    # draft is allowed not to check).
    line_type: Mapped[str | None] = mapped_column(String(256))
    behaviour: Mapped[str | None] = mapped_column(String(32))
    # The label this line declares (`[label]`), which its own proof cites it by.
    label: Mapped[str | None] = mapped_column(String(256))
    # The citation as written (`MP, 1, 2`). Retained alongside the resolved rule
    # and edges below because it is what the author typed; those are what it
    # meant — the two differ whenever the checker filled anything in.
    reference: Mapped[str | None] = mapped_column(Text)
    # The label of the rule that actually justified this line. Null when nothing
    # did: an unjustified line, a scope opener or axiom line (valid by fiat), or
    # a definitional step (which cites a definition, not a rule). Not derivable
    # from `reference` — a promoted theorem resolves to an ephemeral rule that
    # appears in no system's rule list.
    rule: Mapped[str | None] = mapped_column(String(256))
    # The definition a definitional step applied, for the same reason: a generic
    # `[Def, n]` citation names no definition at all — the checker searches those
    # in scope — so which one was used is recoverable from nowhere else. SET NULL
    # rather than CASCADE: losing the attribution must not delete the line. (A
    # part edit invalidates the whole snapshot anyway; this is the backstop.)
    definition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("definitions.id", ondelete="SET NULL"), index=True
    )

    # The line's formula as a kernel term, interned into the system's shared term
    # graph. Null for a line that bears no formula (blank, commentary, or a line
    # that did not parse). Not CASCADE/SET NULL, matching `theorems`: a term row
    # must not be deletable out from under a line that cites it.
    term_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("terms.id"), index=True)

    valid: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    invalid_message: Mapped[str | None] = mapped_column(Text)
    warning_message: Mapped[str | None] = mapped_column(Text)

    # The subproof structure, as the openers that bound it. `opens_scope` is the
    # scope kind this line opens ("assumption" / "variable") or null; `scope_id`
    # points at the opener of the subproof this line sits in (null at the proof
    # root). Together they are the scope tree — which is what makes discharge
    # soundness auditable from the rows.
    opens_scope: Mapped[str | None] = mapped_column(String(32))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proof_lines.id", ondelete="CASCADE"), index=True
    )

    proof: Mapped[Proof] = relationship(back_populates="line_rows")
    term: Mapped[TermRow | None] = relationship()
    scope: Mapped[ProofLineRow | None] = relationship(
        remote_side="ProofLineRow.id", foreign_keys=scope_id
    )
    antecedents: Mapped[list[ProofLineAntecedentRow]] = relationship(
        back_populates="line",
        cascade="all, delete-orphan",
        order_by="ProofLineAntecedentRow.position",
        foreign_keys="ProofLineAntecedentRow.line_id",
    )


class ProofLineAntecedentRow(Base):
    """One edge of the justification graph: a line and a line it was derived from."""

    __tablename__ = "proof_line_antecedents"

    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proof_lines.id", ondelete="CASCADE"), primary_key=True
    )
    # Slot order, so reading the edges back matches the rule's antecedent order.
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(
        String(32), server_default=ANTECEDENT_ROLE_ANTECEDENT
    )

    # The cited line, when it is in this proof. CASCADE (unlike `terms`): the two
    # lines are always written and dropped together as one proof's snapshot, so an
    # edge outliving its target is impossible rather than merely guarded against.
    antecedent_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proof_lines.id", ondelete="CASCADE"), index=True
    )
    # A citation reaching into a lemma (`[alias.3]`) instead names that proof and
    # the number within it: the cited proof owns its own line rows, and they are
    # written when *it* is verified, so pointing at them from here would make one
    # proof's snapshot depend on another's freshness.
    antecedent_proof_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proofs.id", ondelete="CASCADE"), index=True
    )
    antecedent_number: Mapped[int | None] = mapped_column(Integer)

    line: Mapped[ProofLineRow] = relationship(
        back_populates="antecedents", foreign_keys=line_id
    )
    antecedent_line: Mapped[ProofLineRow | None] = relationship(
        foreign_keys=antecedent_line_id
    )
