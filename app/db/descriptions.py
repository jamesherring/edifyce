"""What a system says about the things it names: prose, and who wrote them.

A formal system's parts carry documentation, and Metamath is the case that makes
it worth storing: a ``$( … $)`` comment before a statement *is* its description
(:mod:`website.logical.metamath.comments`), and `set.mm` documents all 50,550 of
its assertions and credits 131 people across 60,661 ``(Contributed by …)``
clauses. Parsed but discarded until now.

Keyed by ``(system, label)``, not by a foreign key into the thing described. That
is the design decision worth recording. A Metamath label lands in one of four
places depending on what its statement turned out to be — a **production** (a
syntax ``$a``), a **definition** (``df-un``), a **primitive theorem** (``ax-ext``)
or a **proof** and its theorem (a ``$p``) — and the classification is the
importer's, not the file's. Four description columns would be four migrations and
four join paths for one concept; one label-keyed table is one of each, and the
label is what a reader cites anyway.

A label is unique within a system (``uq_promoted_theorems_system_label``, and the
grammar namespace besides), so the key is a key.

What this is *not* is the proof's own description. ``proofs.title`` and
``proofs.description`` are this installation's, editable by whoever owns the
proof; these rows are the corpus's record of what the file said, and they cover
labels that are not proofs at all. An import copies the *title* across, since it
is short and a listing wants it, and leaves ``proofs.description`` alone — a
corpus comment runs to paragraphs, ``description`` rides on every
``ProofSummary``, and 47,000 of them do not belong in a list view. The prose is
read from here, on the single proof, where there is somewhere to put it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column
from app.db.models import _trigram_index

if TYPE_CHECKING:
    from app.db.models import FormalSystem


class LabelDescriptionRow(Base):
    """The prose a system carries about one of its labels."""

    __tablename__ = "label_descriptions"
    __table_args__ = (
        # A label names one thing in a system, so it is described once.
        Index(
            "uq_label_descriptions_system_label", "formal_system_id", "label", unique=True
        ),
        # What makes `app.db.label_search` a lookup rather than a scan of the
        # whole corpus. See `models._trigram_index` for why there are three and
        # why they are Postgres-only.
        _trigram_index("label_descriptions", "label"),
        _trigram_index("label_descriptions", "title"),
        _trigram_index("label_descriptions", "text"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(128))
    # The first sentence, as a title. Derived on the way in rather than on the way
    # out (`Description.title`) because deriving it needs Metamath's comment
    # syntax — a `.` inside a ` ... ` math span does not end a sentence — and a
    # reader has rows and no idea what wrote them.
    title: Mapped[str | None] = mapped_column(Text)
    # The prose with the attributions taken out, paragraphs preserved. Unbounded
    # for the reason `promoted_theorems.statement` is: some run to thousands of
    # characters, and Postgres stores a bounded and an unbounded varchar the same.
    text: Mapped[str] = mapped_column(Text, server_default="")
    # `(New usage is discouraged.)` and `(Proof modification is discouraged.)`,
    # as flags rather than as sentences in the prose. They are markers about the
    # statement, not statements about the mathematics: a reader wants "do not
    # build on this" as a badge, and an authoring tool wants to filter on it —
    # neither is served by a phrase buried in a paragraph. `set.mm` carries 5,169
    # and 1,787.
    #
    # Columns rather than rows, unlike an attribution: there are exactly two, they
    # are booleans, and nothing about them is verbatim.
    # `false()` rather than `text("false")`: the column named `text` two lines up
    # shadows the imported helper inside this class body, and it renders per
    # dialect besides (`false` on Postgres, `0` on SQLite).
    discouraged_usage: Mapped[bool] = mapped_column(Boolean, server_default=false())
    discouraged_modification: Mapped[bool] = mapped_column(
        Boolean, server_default=false()
    )

    system: Mapped["FormalSystem"] = relationship(back_populates="label_descriptions")
    attributions: Mapped[list["LabelAttributionRow"]] = relationship(
        back_populates="description",
        cascade="all, delete-orphan",
        order_by="LabelAttributionRow.position",
    )
    references: Mapped[list["LabelReferenceRow"]] = relationship(
        back_populates="description",
        cascade="all, delete-orphan",
        order_by="LabelReferenceRow.position",
    )
    citations: Mapped[list["LabelCitationRow"]] = relationship(
        back_populates="description",
        cascade="all, delete-orphan",
        order_by="LabelCitationRow.position",
    )


class LabelReferenceRow(Base):
    """One ``~ target`` cross-reference out of a label's prose.

    Metamath's comments carry a "see also" graph and it is a large one: `set.mm`
    writes 21,787 references across 12,389 comments, 21,336 of them naming another
    statement. Left in the prose it is punctuation — a reader sees ``~ ax-13`` and
    can do nothing with it — and the *reverse* question, "what points at this
    theorem", cannot be asked at all. As rows it is both a link and an index.

    **The span is stored, not just the target.** ``start_offset``/``end_offset``
    index :attr:`LabelDescriptionRow.text`, so a renderer slices the prose and
    substitutes a link without knowing what a Metamath comment is. The alternative
    is re-parsing the markup in the API and again in the browser, which is two more
    implementations of a rule that belongs in one place
    (:class:`website.logical.metamath.comments.Reference` carries the argument).

    ``target`` is what the reference *resolves to*, which for a URL carrying
    Metamath's ``~~`` escape differs from the text in the span. Whether it names
    something this system has is deliberately not stored: it is a join, it can
    change as a corpus grows, and a column would go stale.
    """

    __tablename__ = "label_references"
    __table_args__ = (
        # "What points at this label" — the reverse direction, and the reason
        # these are rows. set.mm's most-referenced label is cited 656 times.
        Index("ix_label_references_target", "target"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    description_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("label_descriptions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # A label, a URL, or a page of the Metamath website. Unbounded, like the prose
    # it was cut out of: a target is whatever ran between a `~` and the next space,
    # and a bound would turn some future file's long URL into an integrity error
    # thrown at the end of a twenty-minute import (found in review). set.mm's
    # longest is 118 characters, which is exactly the kind of headroom that stops
    # being true. Postgres stores a bounded and an unbounded varchar the same.
    target: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)

    description: Mapped["LabelDescriptionRow"] = relationship(
        back_populates="references"
    )


class LabelCitationRow(Base):
    """One ``[Monk1] p. 22`` bibliography citation out of a label's prose.

    Where a cross-reference points *inside* the corpus, this points outside it —
    at the literature a statement was taken from. `set.mm` writes 5,271 of these
    across 4,901 comments and they are the only record of provenance it has: which
    of its theorems come from Takeuti–Zaring, what a formalisation is a
    formalisation *of*. Left in the prose it is punctuation; as rows it answers
    "what does this library rest on" and "what else came from this book".

    **Only the key is stored, because only the key is in the file.** The
    bibliography itself lives in whatever page the ``$t`` block's
    ``htmlbibliography`` names — `mmset.html` for `set.mm` — which an import does
    not have. So there is no title, author or year here, and inventing a lookup
    table for one library's keys is exactly the presumption
    `metamath_store`'s display overrides are careful not to make.

    ``page`` is a string: `set.mm` cites Roman-numbered front matter (``p. ix``)
    beside ordinary pages, and a page is a locator rather than a quantity.

    The span is stored for the reason :class:`LabelReferenceRow`'s is — a renderer
    slices the prose rather than re-implementing Metamath's markup rule.
    """

    __tablename__ = "label_citations"
    __table_args__ = (
        # "What else cites this work" — the direction that makes these rows rather
        # than punctuation. `set.mm` cites `[Crawley]` from 520 statements.
        Index("ix_label_citations_work", "work"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    description_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("label_descriptions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Bounded, unlike a reference's target: a key is a named anchor in an HTML
    # page, not a URL. These are the widths `comments.WORK_MAX`/`PAGE_MAX` restate,
    # and the recogniser refuses an over-long capture rather than truncating it
    # here — a bracket that long is prose that happened to fit the shape. set.mm's
    # longest key is 22 characters and its longest page 4.
    work: Mapped[str] = mapped_column(String(64))
    page: Mapped[str] = mapped_column(String(32))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)

    description: Mapped["LabelDescriptionRow"] = relationship(
        back_populates="citations"
    )


class LabelAttributionRow(Base):
    """One ``(Contributed by NM, 5-Apr-1994.)`` clause, as its three parts.

    Rows rather than a string because this is an authorship record and the
    questions asked of one are aggregate: who contributed what, what a revision
    changed, what a person's first entry was.

    Every field is **verbatim**, which is deliberate and is
    :mod:`website.logical.metamath.comments`'s reasoning carried into storage:
    `set.mm` spells four kinds wrong (``Resised``, ``Prove shortened``) and 22 of
    its dates are malformed (``25-Jan-20178``, ``XX-May-2017``). Normalising either
    would mean deciding what an upstream typo meant. So ``dated`` is a string, not
    a date, and ``kind`` is not an enum — a consumer that wants to canonicalise
    can, and one that cannot is better off seeing the file as it is.
    """

    __tablename__ = "label_attributions"

    id: Mapped[uuid.UUID] = uuid_pk_column()
    description_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("label_descriptions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # "Contributed", "Revised", "Proof shortened" — and whatever a later revision
    # adds, which is why the set is open. Indexed: "what did this person
    # contribute" is the question, and it is a filter on kind and who together.
    kind: Mapped[str] = mapped_column(String(64), index=True)
    who: Mapped[str] = mapped_column(String(128), index=True)
    dated: Mapped[str] = mapped_column(String(64))

    description: Mapped["LabelDescriptionRow"] = relationship(
        back_populates="attributions"
    )
