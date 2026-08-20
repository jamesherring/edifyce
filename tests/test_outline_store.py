"""A `.mm` file's outline, stored as the folder tree it already is.

`proof_folders` is a per-system tree with a parent, a name and an ordering, which
is what a Metamath outline is — so the import needs no new table, and the test is
that the tree it writes is the one the file drew, with each proof filed under the
deepest section covering it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.metamath_store import import_corpus
from app.db.models import Proof, ProofFolder
from app.db.outline_mapping import store_outline
from tests.database import enable_foreign_keys, throwaway_database
from tests.test_metamath_sections import SOURCE
from website.logical.metamath import parse
from website.logical.metamath.sections import Section, outline


@contextmanager
def database() -> Iterator[Session]:
    engine = create_engine(throwaway_database())
    # A folder's children go with it via `ON DELETE CASCADE`, which is the FK
    # doing the work: `store_outline` clears a system with one Core delete and
    # never loads the rows. Postgres honours that unasked; SQLite needs telling.
    enable_foreign_keys(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        # A context manager rather than a bare `Session`, so the engine behind it
        # is closed too. On SQLite that only tidied up; against a real database an
        # engine left open per test holds a connection until the run ends.
        engine.dispose()


def folders(session: Session) -> dict[str, ProofFolder]:
    return {row.name: row for row in session.scalars(select(ProofFolder))}


def test_an_import_builds_the_tree_the_file_drew() -> None:
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        assert report.sections == 5
        found = folders(session)
        assert set(found) == {"LOGIC", "Implication", "Axioms", "The identity", "Afterwards"}
        assert found["LOGIC"].parent_id is None
        assert found["Implication"].parent_id == found["LOGIC"].id
        assert found["Axioms"].parent_id == found["Implication"].id
        assert found["The identity"].parent_id == found["Axioms"].id
        # A section closes the subsection and subsubsection under its sibling, so
        # `Afterwards` sits beside `Implication` rather than inside it.
        assert found["Afterwards"].parent_id == found["LOGIC"].id


def test_siblings_are_ordered_by_where_the_file_puts_them() -> None:
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        found = folders(session)
        assert (found["Implication"].position, found["Afterwards"].position) == (0, 1)


def test_a_header_keeps_its_prose_as_the_folders_description() -> None:
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        found = folders(session)
        assert found["LOGIC"].description == (
            "The first part, with a note about what it contains."
        )
        # Most headers carry none, and null says that better than "".
        assert found["Axioms"].description is None


def test_a_proof_is_filed_under_the_deepest_section_covering_it() -> None:
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        found = folders(session)
        filed = {p.name: p.folder_id for p in session.scalars(select(Proof))}
        assert filed["id"] == found["The identity"].id
        assert filed["id2"] == found["Afterwards"].id


def test_a_file_with_no_headers_makes_no_folders() -> None:
    # An outline is a convention, not a requirement: a `.mm` written for checking
    # draws none, and every proof then sits at the system's root.
    bare = """
$c |- wff ( ) -> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""
    with database() as session:
        report = import_corpus(session, parse(bare), name="t")
        session.commit()

        assert report.sections == 0
        assert session.scalars(select(ProofFolder)).all() == []
        assert session.scalars(select(Proof)).one().folder_id is None


def test_two_sections_of_one_name_get_distinct_slugs() -> None:
    # set.mm repeats a title freely — several parts have a "Basic properties"
    # subsection. A slug is a handle, so siblings must not collide; the *names*
    # stay as the file wrote them.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_outline(
            session,
            report.system_id,
            [
                Section(level=1, title="Basics", text="", at=0),
                Section(level=2, title="Same", text="", at=0),
                Section(level=2, title="Same", text="", at=0),
            ],
        )
        session.commit()

        rows = session.scalars(select(ProofFolder).order_by(ProofFolder.position)).all()
        assert [r.name for r in rows] == ["Basics", "Same", "Same"]
        assert sorted(r.slug for r in rows) == ["basics", "same", "same-2"]


def test_storing_an_outline_replaces_the_one_before_it() -> None:
    # The outline comes wholesale from one file, so a re-import that dropped a
    # section must drop its folder rather than leave it behind.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_outline(
            session, report.system_id, [Section(level=1, title="Only", text="", at=0)]
        )
        session.commit()

        assert [r.name for r in session.scalars(select(ProofFolder))] == ["Only"]
        # The proofs outlive their folders — `folder_id` is ON DELETE SET NULL,
        # so losing an outline must never cost a proof.
        assert session.scalars(select(Proof)).all()


def test_a_limited_import_files_only_the_sections_it_reached() -> None:
    # The same horizon the grammar and the descriptions stop at: a section opening
    # past the last walked theorem covers nothing this import contains.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t", limit=1)
        session.commit()

        assert "Afterwards" not in folders(session)
        assert report.sections == len(folders(session))


def test_the_stored_tree_is_the_engines_tree() -> None:
    # The rows and `sections.tree` must agree: they are one nesting derived twice,
    # and nothing else checks that the stack the store walks matches the one the
    # engine walks.
    parsed = parse(SOURCE)
    with database() as session:
        import_corpus(session, parsed, name="t")
        session.commit()

        by_id = {row.id: row for row in session.scalars(select(ProofFolder))}
        parent_names = {
            row.name: (by_id[row.parent_id].name if row.parent_id else None)
            for row in by_id.values()
        }

    expected: dict[str, str | None] = {}

    def walk(nodes, parent: str | None) -> None:
        for node in nodes:
            expected[node.section.title] = parent
            walk(node.children, node.section.title)

    from website.logical.metamath.sections import tree

    walk(tree(outline(parsed)), None)
    assert parent_names == expected
