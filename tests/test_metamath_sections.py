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
from website.logical.metamath.corpus import theorems
from website.logical.metamath.sections import (
    Layer,
    Layering,
    Placement,
    Section,
    outline,
    read_header,
    tree,
)
from website.logical.metamath.setmm import LAYERS

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


# ---------------------------------------------------------------------------
# The layer plan (D1/D2)
# ---------------------------------------------------------------------------

LAYERED = f"""
$c |- wff class ( ) -> A. e. $.
$v ph ps x A $.
wph $f wff ph $.
wps $f wff ps $.
vx $f class x $.
cA $f class A $.
$( {SECTION}
   Pre-logic
   {SECTION} $)
wi $a wff ( ph -> ps ) $.
$( {SECTION}
   Propositional calculus
   {SECTION} $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( {SUBSECTION}
   A subsection inside the first layer
   {SUBSECTION} $)
pc-thm $a |- ( ph -> ph ) $.
$( {SECTION}
   Predicate calculus with equality:  Tarski's system S2
   {SECTION} $)
wal $a wff A. x ph $.
ax-4 $a |- ( A. x ph -> ph ) $.
$( {SECTION}
   ZF Set Theory - start with the Axiom of Extensionality
   {SECTION} $)
wcel $a wff A e. A $.
ax-ext $a |- A e. A $.
"""


def test_a_plan_partitions_the_file_into_contiguous_layers() -> None:
    # §7.1's mechanism, on a fixture shaped like the file it was measured
    # against. Every statement falls in exactly one layer, the layers open in the
    # plan's order, and a *subsection* inside a layer does not open a new one —
    # which is the case that matters, since `set.mm` draws 1,115 of them.
    database = parse(LAYERED)
    layering = Layering(outline(database), LAYERS)

    assert layering.starts == [
        ("Propositional calculus", 0),
        ("First-order logic", 3),
        ("ZF set theory", 5),
    ]
    assert [
        layering.covering(position) for position in range(len(database.order))
    ] == [
        "Propositional calculus",   # wi
        "Propositional calculus",   # ax-1
        "Propositional calculus",   # pc-thm, under a subsection
        "First-order logic",        # wal
        "First-order logic",        # ax-4
        "ZF set theory",            # wcel
        "ZF set theory",            # ax-ext
    ]


def test_the_shipped_plan_is_the_one_set_mm_draws() -> None:
    # A guard on the data rather than on the code. The prefixes below are what
    # `set.mm`'s own section titles begin with, and the measurement recorded in
    # `setmm.LAYERS` was taken through exactly these — so a prefix edited to
    # something the file does not draw would silently produce a layer that holds
    # nothing, and every number in that table would stop being about this plan.
    assert [(layer.name, layer.starts_with) for layer in LAYERS] == [
        ("Propositional calculus", "Pre-logic"),
        ("First-order logic", "Predicate calculus with equality"),
        ("ZF set theory", "ZF Set Theory"),
    ]


def test_a_layer_the_file_does_not_open_simply_holds_nothing() -> None:
    # A fragment, or a variant that stops before ZFC. Not an error: the plan is
    # offered to whatever file is being read, and `BINDERS` takes the same line
    # for a label a variant lacks.
    trimmed = LAYERED[: LAYERED.index("$( " + SECTION + "\n   Predicate")]
    layering = Layering(outline(parse(trimmed)), LAYERS)

    assert layering.starts == [("Propositional calculus", 0)]
    assert layering.covering(2) == "Propositional calculus"


def test_a_plan_whose_layers_open_out_of_order_is_refused() -> None:
    # The one thing that *is* an error, because it is a plan about a different
    # file: every position it reported afterwards would be wrong, and silently.
    reversed_plan = (
        Layer(name="Set theory", starts_with="ZF Set Theory"),
        Layer(name="Logic", starts_with="Pre-logic"),
    )
    with pytest.raises(ValueError, match="must open in that order"):
        Layering(outline(parse(LAYERED)), reversed_plan)


def test_a_statement_before_the_first_layer_falls_outside_them() -> None:
    # The same answer `Placement` gives for a statement before every header, and
    # for the same reason: a file may open with declarations nobody sectioned.
    layering = Layering(
        outline(parse(LAYERED)),
        (Layer(name="Late", starts_with="ZF Set Theory"),),
    )
    assert layering.covering(0) is None
    assert layering.covering(6) == "Late"


def test_two_layers_may_open_at_one_position_and_the_later_wins() -> None:
    # **From review.** The out-of-order guard first compared each layer's
    # *position*, and two headers may share one — a part followed straight away
    # by a section, with no statement between, which is how `set.mm` opens every
    # part. So a reversed plan naming both passed the check and then attributed
    # the whole file to the wrong layer. Order is compared on the section now.
    #
    # The pair: the reversed plan is refused, and the forward one is not — since
    # sharing a position is legal and the later layer wins it, on the same
    # nearest-wins rule the rest of the spine follows.
    sections = [
        Section(level=2, title="Pre-logic", text="", at=0),
        Section(level=2, title="ZF Set Theory", text="", at=0),
    ]
    logic = Layer(name="Logic", starts_with="Pre-logic")
    theory = Layer(name="Set theory", starts_with="ZF Set")

    with pytest.raises(ValueError, match="must open in that order"):
        Layering(sections, (theory, logic))

    layering = Layering(sections, (logic, theory))
    assert layering.starts == [("Logic", 0), ("Set theory", 0)]
    assert layering.covering(0) == "Set theory"


# A layer plan over a file that has *proved* statements as well as axioms, so
# the two units a boundary can be quoted in come apart.
MIXED = f"""
$c |- wff ( ) -> A. $.
$v ph ps x $.
wph $f wff ph $.
wps $f wff ps $.
vx $f class x $.
$( {SECTION}
   Pre-logic
   {SECTION} $)
wi $a wff ( ph -> ps ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
pc-one $p |- ( ph -> ( ps -> ph ) ) $= ( wi ) A $.
pc-two $p |- ( ph -> ( ps -> ph ) ) $= ( wi ) A $.
$( {SECTION}
   Predicate calculus with equality:  Tarski's system S2
   {SECTION} $)
wal $a wff A. x ph $.
fol-one $p |- ( ph -> ( ps -> ph ) ) $= ( wi ) A $.
$( {SECTION}
   ZF Set Theory - start with the Axiom of Extensionality
   {SECTION} $)
ax-ext $a |- ( ph -> ( ps -> ph ) ) $.
zf-one $p |- ( ph -> ( ps -> ph ) ) $= ( wi ) A $.
"""


def test_a_layer_boundary_is_two_different_numbers_in_two_units() -> None:
    # **From review.** D1's table indexes `Database.order`, which holds every
    # `$a` and `$p`; a walk's `limit` counts what `corpus.theorems` yields, which
    # is provable `$p` alone. So a layer boundary is one number as a position and
    # a *smaller* one as a theorem ordinal, and the milestone figure was first
    # recorded in the wrong unit — passing it as a `limit` would have overshot by
    # the axioms in between.
    #
    # Asserted on a fixture rather than on `set.mm`'s own figures, which move:
    # what has to hold is that the two units differ, and differ by exactly the
    # assertions a walk does not check.
    database = parse(MIXED)
    layering = Layering(outline(database), LAYERS)
    position = {label: index for index, label in enumerate(database.order)}

    # As a position: every `$a` and `$p` before ZF opens.
    boundary = next(
        index
        for index in range(len(database.order))
        if layering.covering(index) == "ZF set theory"
    )

    # As a theorem ordinal: only the proved ones, 1-based, as `limit` counts.
    walked = theorems(database)
    ordinal = next(
        number
        for number, assertion in enumerate(walked, start=1)
        if layering.covering(position[assertion.label]) == "ZF set theory"
    )

    assert [assertion.label for assertion in walked] == [
        "pc-one", "pc-two", "fol-one", "zf-one"
    ]
    assert boundary == 6 and ordinal == 4
    # The gap is the axioms and syntax the walk skips — here `wi`, `ax-1` and
    # `wal`, which is exactly why one number cannot stand in for the other.
    assert boundary - (ordinal - 1) == 3
