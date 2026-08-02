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
labels that are not proofs at all. An import fills both from one parse, and they
diverge from there.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

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

    system: Mapped["FormalSystem"] = relationship(back_populates="label_descriptions")
    attributions: Mapped[list["LabelAttributionRow"]] = relationship(
        back_populates="description",
        cascade="all, delete-orphan",
        order_by="LabelAttributionRow.position",
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
