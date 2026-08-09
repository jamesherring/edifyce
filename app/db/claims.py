"""What a corpus's ``$j`` markup asserts about the labels it names.

Metamath's language has keywords for grammar, statements and proofs, and nothing
else. Everything a library wants to say *about* a statement beyond its prose goes
in a ``$j`` block — machine-readable markup inside a comment — and `set.mm`
writes **1,222 directives across 1,203 blocks**.

Flattened to triples (:func:`website.logical.metamath.markup.claims_of`), those
are **3,364 claims of 24 kinds over 1,329 labels**, of which 3,359 are stored —
the five left out name sorts rather than labels, and
:func:`app.db.metamath_store._claims_of` says why. The distribution is lopsided
and the head is one kind:

- ``usage_avoids`` (3,109) — this theorem's proof does without that axiom. Real
  mathematical content with nowhere else to read it from: a proof's text says
  which lemmas it *cites*, and an avoided statement is by construction absent
  from the citation graph, that being the point. Headed by ``ax-12`` (435).
- ``restatement_of`` (29) — ``ax-sep`` restates ``axsep``. The pairing between an
  axiom and the theorem deriving it, which nothing else in the file records.
- ``natded_*`` (175 across seven kinds) — which theorems play which role in a
  natural-deduction reading (``natded_weak`` names 63).
- ``primitive`` (11), ``congruence`` (6), ``equality_from`` (6),
  ``condcongruence`` (9), ``justification_for``, ``definition_for``,
  ``notfree_from``, ``free_var_with``, ``bound``, ``syntax`` — the definitional
  soundness and binding metadata a checker like mmj2 reads.

**One table rather than one per keyword**, because they are one shape: a subject,
a kind, and at most one object. This began as `label_avoidances`, which was that
shape with the kind implied by the table's name — and a second table of identical
columns for `restatement` would have been the drift `tests/database.py` warns
about in the small. The kind is stored as the file spells it (keyword joined to
preposition) rather than mapped to a vocabulary of ours, for the reason an
attribution's ``kind`` is kept verbatim: a closed set here would have to be
maintained against a file free to add to it.

**Its own table, not a column on the description**, because a claim is about a
label whether or not the file also documents it. Hanging these off
`label_descriptions` would make an undocumented label's claims unstorable —
`store_descriptions` drops a row with nothing in it.

**Stored as the file's claim, not as a checked one.** Metamath's own verifier
checks `usage … avoids` against a proof's transitive dependencies; Edifyce does
not, and saying so is cheaper than implying otherwise. What would check it is a
closure over `proof_lines.rule`, which is indexed for exactly that sort of
question — see the roadmap. Until then a reader is told what the corpus asserts.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk_column

if TYPE_CHECKING:
    from app.db.models import FormalSystem


class LabelClaimRow(Base):
    """One ``$j`` assertion: ``subject`` is *kind* ``object``."""

    __tablename__ = "label_claims"
    __table_args__ = (
        # "What does this label claim" — the forward read, one label at a time,
        # which is what a proof page makes.
        Index("ix_label_claims_system_subject", "formal_system_id", "subject"),
        # And the reverse, which is the more interesting question of the two:
        # "what is proved without `ax-11`" is a survey of the corpus, and 398 of
        # set.mm's statements answer it. Keyed by object *and* kind, since the
        # same name appears as the object of different relations.
        Index("ix_label_claims_object_kind", "object", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk_column()
    formal_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("formal_systems.id", ondelete="CASCADE"), index=True
    )
    # The same width `label_descriptions.label` uses, and the same reason: these
    # are Metamath labels either side.
    subject: Mapped[str] = mapped_column(String(128))
    # The keyword, joined to its preposition where it has one (`usage_avoids`,
    # `restatement_of`). The preposition is part of the relation's identity —
    # `equality … from` and `notfree … from` share a word and mean different
    # things — so it is not dropped.
    kind: Mapped[str] = mapped_column(String(64))
    # Null for a directive with no preposition, where every argument asserts the
    # same thing about itself: `primitive 'wn' 'wi';` is two claims and no object.
    object: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    system: Mapped["FormalSystem"] = relationship(back_populates="label_claims")
