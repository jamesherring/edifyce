"""A system's named notations, stored and read back.

A grammar fixes how a term is *written*; a notation is how it may be *read*, and
a system may carry several at once. They persist as render-step rows so that a
reader — who has a database and no grammar — can show a proof in any of them
without rebuilding the system, which on a corpus-sized grammar is seconds.

The load-bearing test here is the last one: the storage-side fold and the
engine's own fold must agree, since they are the same operation over two shapes.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db.metamath_store import import_corpus
from app.db.notations_mapping import render_stored, store_notation
from app.db.proof_lines import ProofLineRow
from app.db.systems import NotationPieceRow
from app.db.terms_mapping import prefetch_terms
from website.logical.declarative import build_system
from website.logical.metamath import build_spec, parse
from website.logical.metamath.definitions import statement_of
from website.logical.metamath.display import notation_constructors, unicode_projection
from website.logical.metamath.typesetting import typesetting_of
from website.logical.rendering import Projection, render, total_projection

# A `.mm` carrying its own readable spellings, which is the case notations exist
# for: without somewhere to put a `$t` block, an imported corpus reads as ASCII
# for ever.
SOURCE = r"""
$( $t
  althtmldef "e." as ' &isin; ';
  althtmldef "->" as ' &rarr; ';
  althtmldef "RR" as '&#8477;';
  althtmldef "A." as '&forall;';
$)
$c |- wff class setvar ( ) -> e. A. RR $.
$v ph ps x A B $.
wph $f wff ph $.
wps $f wff ps $.
vx $f setvar x $.
cA $f class A $.
cB $f class B $.
cr $a class RR $.
cv $a class x $.
wi $a wff ( ph -> ps ) $.
wcel $a wff A e. B $.
wal $a wff A. x ph $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""


def database() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_an_import_stores_the_files_own_notation() -> None:
    # The motivating case. A `$t` block is the only machine-readable notation a
    # `.mm` has, and deriving it needs the file *and* the grammar it built — which
    # is why an import stores it rather than a reader deriving it.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        assert report.notation > 0
        rows = session.scalars(
            select(NotationPieceRow)
            .where(NotationPieceRow.constructor == "wcel")
            .order_by(NotationPieceRow.position)
        ).all()
        assert [(r.kind, r.text) for r in rows] == [
            ("slot", "A"), ("lit", " ∈ "), ("slot", "B")
        ]
        assert {r.notation for r in rows} == {"unicode"}


def test_a_database_with_no_typesetting_stores_none() -> None:
    # Optional, and silently so: a `.mm` written for checking rather than
    # publishing carries no `$t`, and that is not a failed import.
    with database() as session:
        report = import_corpus(session, parse(SOURCE.split("$)")[1]), name="t")
        session.commit()

        assert report.notation == 0
        assert session.scalars(select(NotationPieceRow)).all() == []


def test_storing_a_notation_replaces_the_one_before_it() -> None:
    # A notation is derived wholesale from a source that knows the whole grammar,
    # so a re-derivation dropping a constructor must drop its rows. Merging would
    # leave the old spelling behind and make the stored notation a history.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_notation(
            session,
            report.system_id,
            Projection(templates={"wcel": (("lit", "IN"),)}, name="unicode"),
        )
        session.commit()

        rows = session.scalars(select(NotationPieceRow)).all()
        assert {r.constructor for r in rows} == {"wcel"}


def test_two_notations_coexist() -> None:
    # The point of naming them: one checked term, read several ways, with no
    # second copy of the term and no re-parse.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        store_notation(
            session,
            report.system_id,
            Projection(
                templates={"wcel": (("slot", "A"), ("lit", " \\in "), ("slot", "B"))},
                name="latex",
            ),
        )
        session.commit()

        found = session.scalars(select(NotationPieceRow.notation).distinct()).all()
        assert sorted(found) == ["latex", "unicode"]


def test_a_constructor_the_notation_does_not_name_renders_empty() -> None:
    # Why a *stored* notation is completed against the grammar
    # (`total_projection`): a reader has rows and no system, so a constructor the
    # notation skips has no source template to fall back to. The gap shows as a
    # hole rather than failing the page — but it is a hole, which is what makes
    # completing a derived notation part of storing it rather than a nicety.
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        graph = prefetch_terms(session, [r.term_id for r in rows])
        partial = Projection(templates={"wcel": (("lit", "IN"),)}, name="partial")
        assert render_stored(graph, rows[0].term_id, partial) == ""


def test_the_stored_fold_agrees_with_the_engines_own() -> None:
    """The two folds must not drift.

    `rendering.render` walks rebuilt kernel terms; `render_stored` walks the rows,
    so that showing a proof costs a query rather than a system rebuild. They are
    the same operation over two shapes, and nothing but this checks that they stay
    the same answer.
    """
    parsed = parse(SOURCE)
    engine = build_system(build_spec(parsed, name="t"))
    typesetting = typesetting_of(parsed.comments)
    projection = total_projection(
        notation_constructors(engine.build_context),
        unicode_projection(engine, typesetting),
    )

    with database() as session:
        import_corpus(session, parsed, name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        assert rows, "the fixture's proof should store at least one formula"
        graph = prefetch_terms(session, [r.term_id for r in rows])

        for row in rows:
            # The engine's answer, from the term the grammar rebuilds.
            term = statement_of(parsed.assertions["ax-1"], engine)
            assert render_stored(graph, row.term_id, projection) == render(
                term, projection
            )
        # And it is genuinely the projected spelling, not the source one.
        assert render_stored(graph, rows[0].term_id, projection) == (
            "( ph → ( ps → ph ) )"
        )
