"""Which statements a theorem's proof is declared to do without.

`set.mm` writes 1,136 ``$j usage 'X' avoids 'Y' 'Z';`` directives — 3,107 edges
over 47 distinct avoided statements, headed by ``ax-12`` (435), ``ax-10`` (431),
``ax-11`` (398) and ``ax-13`` (373). It is the file's way of recording a result
that is about the *proof* rather than the theorem: this one is derivable without
that axiom.

That is real mathematical content and there is nowhere else to read it from. A
proof's own text says which lemmas it cites, not which it was written to avoid,
and the avoided statement is usually nowhere in the citation graph at all — that
being the point.

**Its own table, not a column on the description**, because it is a different
fact. A `usage` directive is about a label whether or not the file also documents
it, and hanging these off `label_descriptions` would make an undocumented label's
avoidances unstorable — `store_descriptions` drops a row with nothing in it.

**Stored as the file's claim, not as a checked one.** Metamath's own verifier
checks these against the proof's transitive dependencies; Edifyce does not, yet,
and saying so is cheaper than implying otherwise. What would check it is a closure
over `proof_lines.rule`, which is indexed for exactly that sort of question — see
the roadmap. Until then a reader is told what the corpus asserts.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem


class LabelAvoidanceRow(Base):
    """One ``avoids`` edge: ``label``'s proof does without ``avoided``."""

    __tablename__ = "label_avoidances"
    __table_args__ = (
        # "What does this theorem avoid" — the forward read, one label at a time.
        Index("ix_label_avoidances_system_label", "formal_system_id", "label"),
        # And the reverse, which is the more interesting question of the two:
        # "what is proved without `ax-11`" is a survey of the corpus, and 398 of
        # set.mm's statements answer it.
        Index("ix_label_avoidances_avoided", "avoided"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # The same width `label_descriptions.label` uses, and the same reason: these
    # are Metamath labels either side.
    label: Mapped[str] = mapped_column(String(128))
    avoided: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    system: Mapped["FormalSystem"] = relationship(back_populates="label_avoidances")
