"""What a formal statement claims to be a formalization *of*.

§4.3 of docs/informal-source-ingestion-roadmap.md, and the last of the three
claims an informal source adds that the checker cannot settle. The kernel
certifies that a proof establishes a term in a system; it has no opinion whatever
on whether that term is Theorem 3.2 of the paper someone was reading. Nothing
mechanical decides that, and a mis-formalised statement that checks is a green
proof of something else — the worst failure in autoformalisation, precisely
because it is invisible.

So this does not try to check it. It makes the claim **explicit, attributed and
queryable**, and makes its absence visible, which is the same discipline
`assumptions` applies to unproved prerequisites.

Why this is not a closure
-------------------------
An assumption's debt propagates: cite something unproved and your result is
conditional, at any depth, which is why `theorem_assumptions` exists. A fidelity
claim does **not** propagate, and the difference is worth being precise about. A
proof citing a term inherits *the term* — not anyone's claim about what the term
corresponds to. Proving a corollary from a formalized theorem gives you a formal
corollary; whether it is the paper's Corollary 3.3 is a separate claim, attested
separately by whoever reads the paper. So a formalization is a leaf annotation
rather than a graph, and there is deliberately nothing here to close over.

A version is a row
------------------
A paper's v2 may restate the theorem, and a formalization pinned to v1 must not
silently come to claim something about v2. That is structural rather than
checked: :class:`SourceDocumentRow` is unique on (kind, identifier, **version**),
so a new version is a new row and an existing formalization keeps pointing at the
one its author read. The informal statement is copied onto the formalization
verbatim besides, so even editing a document cannot rewrite what was claimed.

Attestation, not a tick
-----------------------
Who said the correspondence holds, and why, in their own words — because "this
was reviewed" is exactly the shape of claim this whole layer exists to refuse. An
attestation carries an author, the agent that acted (a model identifier, where a
model is driving), and required prose. A **review** is a second person's verdict
on it, and a review by the attestor is refused: the entire value of the word is
independence, and a self-review that reads as reviewed is the silent
overstatement again.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk_column

if TYPE_CHECKING:
    from app.db.terms import TermRow


class SourceDocumentRow(TimestampMixin, Base):
    """An external work something here claims to formalize."""

    __tablename__ = "source_documents"
    __table_args__ = (
        # A version is a row (see the module docstring), so this is what makes
        # "pinned to v1" structural: two people formalizing the same paper share
        # the row, and a revision cannot reach the claims made about its
        # predecessor.
        Index(
            "uq_source_documents_identity",
            "kind",
            "identifier",
            "version",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    # How the source is named. A plain string rather than an enum, for the reason
    # `label_attributions.kind` is one: a corpus of external work will meet a
    # kind nobody listed, and refusing to record it is worse than recording it
    # loosely. `SourceDocumentCreate` closes the set for a *caller*, to guide
    # one; `SourceDocument` deliberately does not, so a row written by an import
    # or a fixture cannot fail a read on its way out.
    kind: Mapped[str] = mapped_column(String(16))
    # The identifier within that kind — `2401.01234`, a DOI, a URL. Verbatim: a
    # normalisation here would be this layer deciding what an upstream identifier
    # meant, which is the thing it must never do.
    identifier: Mapped[str] = mapped_column(String(512))
    # Empty rather than null for "the caller named none", so the unique index
    # above treats two unversioned registrations of one paper as one row —
    # NULLs do not compare equal, and two would defeat the point of the index.
    version: Mapped[str] = mapped_column(String(64), server_default="")
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    # The bytes the author actually read, where they have them. Optional because
    # a DOI often reaches a paywall rather than a file, and a claim about a paper
    # nobody can hash is still worth recording — it is simply worth less, and the
    # difference is visible.
    content_hash: Mapped[str | None] = mapped_column(String(128))
    licence: Mapped[str | None] = mapped_column(String(128))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who registered it. SET NULL: losing the account must not take the document
    # down with it, since other people's formalizations point at it.
    registered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    formalizations: Mapped[list[FormalizationRow]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class FormalizationRow(Base, TimestampMixin):
    """One claim: *this* term is *that* result of *that* document."""

    # "What has been formalized from this paper" and "what does this proof claim
    # to be" are the two directions anyone reads this from, and both are served
    # by the column indexes below rather than by a second set beside them: a
    # single-column `Index` next to `index=True` is two indexes for one question
    # (found in review).
    __tablename__ = "formalizations"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    # Which result of it — "Theorem 3.2", "Lemma 4.1(b)". The paper's own
    # numbering, not ours.
    claim: Mapped[str] = mapped_column(String(256))
    # The paper's statement, verbatim, as it stood when this was claimed. Copied
    # rather than referenced so that nothing — not a document edit, not a
    # revision — can rewrite what the attestation was about.
    informal_statement: Mapped[str] = mapped_column(Text)

    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # The term the claim says it is. Required: a formalization with no formal
    # side is a note, and this table is for claims that can be checked *against*
    # something. NO ACTION, as `theorems.statement_term_id` is — a term row must
    # not be deletable out from under a claim about it.
    statement_term_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terms.id"), index=True
    )
    # The proof attempting it, once there is one. Null is the ordinary early
    # state — the point of §4.4 is that a goal is stateable before it is proved —
    # and SET NULL so deleting a proof withdraws the attempt, not the claim.
    proof_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proofs.id", ondelete="SET NULL"), index=True
    )

    # The attestation. `attested_by_id` is also who may edit this row.
    attested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # The agent that actually did the reading, where it was not a person — a
    # model identifier and version. Recorded beside the account rather than
    # instead of it: an account is accountable and a model is not, so the human
    # who ran it stays named.
    attested_as: Mapped[str | None] = mapped_column(String(128))
    # Why this term is that result, in the attestor's own words. Required, and
    # the whole point: a claim with no argument is a tick, and a tick is what
    # this layer exists to refuse.
    reasoning: Mapped[str] = mapped_column(Text)

    # A second person's verdict, or nothing. Nothing is the ordinary state and is
    # meant to be visible as such.
    review_verdict: Mapped[str | None] = mapped_column(String(16))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[SourceDocumentRow] = relationship(
        back_populates="formalizations"
    )
    statement_term: Mapped[TermRow] = relationship()
    glossary: Mapped[list[GlossaryEntryRow]] = relationship(
        back_populates="formalization",
        cascade="all, delete-orphan",
        order_by="GlossaryEntryRow.position",
    )


class GlossaryEntryRow(Base):
    """One of the paper's notions, and what it was read as here.

    The **alignment** claim, at the granularity a disagreement actually happens
    at. A formalization's reasoning argues that the whole statement corresponds;
    a glossary entry says what a single word or symbol was taken to mean, which
    is where a mis-formalisation usually starts and the level at which a reviewer
    can disagree without rejecting everything.
    """

    __tablename__ = "glossary_entries"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formalization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formalizations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # The paper's word or symbol — "measurable", "⊆", "the integral".
    notion: Mapped[str] = mapped_column(String(256))
    # What it was read as: a label the library resolves, a production the grammar
    # declares, or a term. At least one is required, and the route enforces it —
    # an entry naming nothing records only that somebody thought about it.
    label: Mapped[str | None] = mapped_column(String(128))
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("terms.id", ondelete="SET NULL"), index=True
    )
    reasoning: Mapped[str | None] = mapped_column(Text)

    formalization: Mapped[FormalizationRow] = relationship(back_populates="glossary")
