"""The outline a `.mm` file draws with comments.

Metamath declares no sections. A comment of the shape rule / title / rule marks
where one starts, and which punctuation drew the rule says how deep it is. These
tests cover the recognition (which must not read prose as structure), the nesting
(a header closes every open section at its level or deeper) and the placement
(which section a statement falls in).
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.sections import (
    Placement,
    Section,
    outline,
    read_header,
    tree,
)

PART = "#" * 40
SECTION = "#*" * 20
SUBSECTION = "=-" * 20
SUBSUB = "-." * 20

SOURCE = f"""
$( {PART}
              LOGIC
   {PART}
   The first part, with a note about what it contains. $)
$c |- wff ( ) -> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
$( {SECTION}
   Implication
   {SECTION} $)
wi $a wff ( ph -> ps ) $.
$( {SUBSECTION}
   Axioms
   {SUBSECTION} $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( {SUBSUB}
   The identity
   {SUBSUB} $)
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
$( {SECTION}
   Afterwards
   {SECTION} $)
id2 $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""


def test_each_rule_names_its_level() -> None:
    for rule, level in ((PART, 1), (SECTION, 2), (SUBSECTION, 3), (SUBSUB, 4)):
        header = read_header(f"{rule}\nA title\n{rule}")
        assert header is not None
        assert header[0] == level, rule[:4]


def test_a_hyphen_rule_is_told_from_an_equals_rule_by_its_prefix() -> None:
    # The reason recognition keys on the prefix and not the character set: a line
    # of bare hyphens is a subset of both `=-=-` and `-.-.`, and reading one as
    # the other silently reshuffles the tree.
    assert read_header(f"{SUBSECTION}\nA title\n{SUBSECTION}")[0] == 3
    assert read_header(f"{SUBSUB}\nA title\n{SUBSUB}")[0] == 4


def test_prose_is_not_a_header() -> None:
    # What tight recognition is for. None of these opens a section, and reading
    # any of them as one would invent structure the file does not have.
    assert read_header("Just a description of a theorem.") is None
    assert read_header("A comment\nover two lines\nand a third.") is None
    assert read_header(f"{PART}\nNo closing rule at all") is None
    assert read_header(f"{PART}\n{PART}") is None  # no title between the rules


def test_a_wrapped_title_survives_whole() -> None:
    # set.mm writes every title on one line, but nothing says it must, and joining
    # beats truncating: a title cut at the wrap would name the section wrongly.
    header = read_header(f"{PART}\nA title that runs\non to a second line\n{PART}")
    assert header[1] == "A title that runs on to a second line"


def test_the_prose_after_the_closing_rule_is_kept() -> None:
    level, title, text = read_header(f"{PART}\nA title\n{PART}\nWhy this part exists.")
    assert (level, title) == (1, "A title")
    assert text == "Why this part exists."


def test_an_outline_reads_every_header_in_file_order() -> None:
    sections = outline(parse(SOURCE))
    assert [(s.level, s.title) for s in sections] == [
        (1, "LOGIC"),
        (2, "Implication"),
        (3, "Axioms"),
        (4, "The identity"),
        (2, "Afterwards"),
    ]
    assert sections[0].text == "The first part, with a note about what it contains."


def test_a_header_is_positioned_by_the_statements_before_it() -> None:
    # `at` is an index into `order`: which statement the section starts at. The
    # part header precedes every statement, so it is 0; `Afterwards` opens after
    # the four before it.
    sections = outline(parse(SOURCE))
    assert [s.at for s in sections] == [0, 0, 1, 2, 3]


def test_nesting_closes_every_open_section_at_that_level_or_deeper() -> None:
    roots = tree(outline(parse(SOURCE)))
    assert [r.section.title for r in roots] == ["LOGIC"]
    (part,) = roots
    # `Afterwards` is a section, so it closes the subsection and subsubsection
    # under `Implication` and sits beside it rather than inside it.
    assert [c.section.title for c in part.children] == ["Implication", "Afterwards"]
    implication = part.children[0]
    assert [c.section.title for c in implication.children] == ["Axioms"]
    assert [c.section.title for c in implication.children[0].children] == ["The identity"]


def test_a_level_that_skips_one_nests_under_what_is_open() -> None:
    # Nothing in Metamath forbids a subsection with no section before it. Dropping
    # it would lose a real header and promoting it would misplace everything under
    # it, so it attaches to the deepest thing still open.
    sections = [
        Section(level=1, title="Part", text="", at=0),
        Section(level=3, title="Orphan", text="", at=0),
    ]
    (part,) = tree(sections)
    (child,) = part.children
    assert child.section.title == "Orphan"


def test_a_statement_falls_in_the_deepest_section_before_it() -> None:
    sections = outline(parse(SOURCE))
    place = Placement(sections)
    # `wi` is at 0, under `Implication` — the deeper of the two headers sharing
    # that position, which is what "deepest section before it" means.
    assert place.covering(0).title == "Implication"
    assert place.covering(1).title == "Axioms"
    assert place.covering(2).title == "The identity"
    assert place.covering(3).title == "Afterwards"


def test_a_statement_before_every_header_falls_nowhere() -> None:
    # A file may declare statements before it draws its first rule. They belong to
    # no section, and inventing one for them would be a lie about the file.
    database = parse(f"""
$c |- wff $.
$v ph $.
wph $f wff ph $.
early $a wff ph $.
$( {PART}
   Later
   {PART} $)
late $a |- ph $.
""")
    place = Placement(outline(database))
    assert place.covering(database.position("early")) is None
    assert place.covering(database.position("late")).title == "Later"


def test_a_file_with_no_headers_has_no_outline() -> None:
    assert outline(parse("$c |- wff $.\n$v ph $.\nwph $f wff ph $.\n")) == []


def test_the_prose_keeps_its_paragraphs_and_loses_its_wrapping() -> None:
    # The same rule a statement's description gets. A `.mm` comment is wrapped to
    # a column and the wrapping is not content; a blank line is, being the only
    # way a comment marks a paragraph. 141 of set.mm's 308 header prose blocks
    # have one, and flattening them would make each a run-on blob.
    _level, _title, text = read_header(
        f"{PART}\nA title\n{PART}\n"
        "A first paragraph that the file\nwrapped across two lines.\n"
        "\n"
        "And a second one."
    )
    assert text == (
        "A first paragraph that the file wrapped across two lines.\n\nAnd a second one."
    )
