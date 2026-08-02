"""What a system says about its labels, stored and read back.

Metamath declares no description keyword and no title. A statement is documented
by the ``$( … $)`` comment before it, and that convention is the whole of the
association — so this covers what the convention yields once it is rows: prose,
authorship, and the first sentence that serves as a title.

The key is ``(system, label)`` rather than a foreign key into the thing described,
because one label lands in one of four row types depending on what the importer
made of it. The first test here is the one that says so.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db.descriptions import LabelAttributionRow, LabelDescriptionRow
from app.db.descriptions_mapping import store_descriptions
from app.db.metamath_store import import_corpus
from app.db.models import Proof
from tests.database import enable_foreign_keys
from website.logical.metamath import parse
from website.logical.metamath.comments import read_comment

# One of each kind of documented label, which is the point: `wi` is a syntax `$a`
# that becomes a production, `df-neg` a definition, `ax-1` a primitive theorem,
# and `id` a `$p` that becomes a proof. All four are described the same way.
SOURCE = r"""
$c |- wff ( ) -> -. $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
$( Wff builder for implication.  (Contributed by NM, 5-Aug-1993.) $)
wi $a wff ( ph -> ps ) $.
$( Wff builder for negation. $)
wn $a wff -. ph $.
$( Define negation as implying a falsehood.  This is a definition rather
   than an axiom.

   It carries a second paragraph, which survives.
   (Contributed by NM, 1-Jan-1990.)  (Revised by Mario Carneiro, 2-Feb-2015.) $)
df-neg $a |- ( -. ph <-> ( ph -> ps ) ) $.
$( Axiom _Simp_.  Axiom A1 of [Margaris] p. 49.  (Contributed by NM, 3-Jan-1993.) $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( Principle of identity.  (Contributed by NM, 4-Apr-1994.)
   (Proof shortened by Wolf Lammen, 8-Sep-2012.) $)
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""


def database() -> Session:
    engine = create_engine("sqlite://")
    # An attribution is removed by its parent's `ON DELETE CASCADE`, which is the
    # FK doing the work rather than the ORM: `store_descriptions` clears a system
    # with one Core delete and never loads the rows. Postgres honours that
    # unasked; SQLite needs telling, per connection.
    enable_foreign_keys(engine)
    Base.metadata.create_all(engine)
    return Session(engine)


def described(session: Session) -> dict[str, LabelDescriptionRow]:
    return {row.label: row for row in session.scalars(select(LabelDescriptionRow))}


def test_a_label_of_every_kind_is_described() -> None:
    # Why the table is keyed by label. A production, a definition, a primitive
    # theorem and a proof are four row types with four id columns; the comment
    # that documents them is one concept, and the label is what all four carry.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        assert set(described(session)) == {"wi", "wn", "df-neg", "ax-1", "id"}
        assert report.described == 5


def test_the_first_sentence_is_kept_as_a_title() -> None:
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        rows = described(session)
        assert rows["ax-1"].title == "Axiom _Simp_."
        assert rows["wi"].title == "Wff builder for implication."


def test_the_prose_keeps_its_paragraphs_and_drops_its_attributions() -> None:
    # A comment is hard-wrapped in the file and the wrapping is not content, but a
    # blank line is — it is how a comment marks a paragraph.
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        text = described(session)["df-neg"].text
        assert text.count("\n\n") == 1
        assert "Contributed by" not in text
        assert text.startswith("Define negation as implying a falsehood.")


def test_attributions_are_stored_in_order_with_their_kinds() -> None:
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        row = described(session)["id"]
        assert [(a.kind, a.who, a.dated) for a in row.attributions] == [
            ("Contributed", "NM", "4-Apr-1994"),
            ("Proof shortened", "Wolf Lammen", "8-Sep-2012"),
        ]


def test_an_imported_proof_carries_the_title_and_keeps_the_label_as_its_name() -> None:
    # The label is what a citation spells, so it stays the name and the slug. The
    # title is the sentence a reader wants, and it is a separate field precisely
    # so neither has to give way to the other.
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        proof = session.scalars(select(Proof)).one()
        assert (proof.name, proof.slug) == ("id", "id")
        assert proof.title == "Principle of identity."
        assert proof.description == "Principle of identity."


# The same grammar with every comment removed, which is a legitimate `.mm`:
# documentation is a convention, not a requirement.
UNDOCUMENTED = r"""
$c |- wff ( ) -> -. $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""


def test_a_database_with_no_comments_describes_nothing() -> None:
    # A `.mm` written for checking rather than publishing carries none, and that
    # is not a failed import.
    with database() as session:
        report = import_corpus(session, parse(UNDOCUMENTED), name="t")
        session.commit()

        assert report.described == 0
        assert session.scalars(select(LabelDescriptionRow)).all() == []


def test_storing_replaces_what_was_there_before() -> None:
    # A corpus's documentation is derived wholesale from one file, so a re-import
    # that drops a label must drop its prose rather than leave it behind under a
    # label the file no longer has.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_descriptions(
            session,
            report.system_id,
            {"ax-1": read_comment("Only this one now.  (Contributed by AV, 1-Jan-2020.)")},
        )
        session.commit()

        assert set(described(session)) == {"ax-1"}
        # And the children went with it, rather than orphaning.
        assert len(session.scalars(select(LabelAttributionRow)).all()) == 1


def test_an_attribution_only_comment_is_still_stored() -> None:
    # Two of set.mm's comments are nothing but a `(Contributed by …)`. Authorship
    # with no prose is still authorship, so what is skipped is a comment that said
    # nothing at all — not one that said only who wrote it.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_descriptions(
            session,
            report.system_id,
            {
                "ax-1": read_comment("(Contributed by NM, 3-Jan-1993.)"),
                "wi": read_comment("   "),
            },
        )
        session.commit()

        rows = described(session)
        assert set(rows) == {"ax-1"}
        assert rows["ax-1"].title is None
        assert rows["ax-1"].text == ""
        assert [a.who for a in rows["ax-1"].attributions] == ["NM"]
