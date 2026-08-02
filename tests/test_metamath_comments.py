"""Metamath comments, and what a statement's own comment says about it.

Comments used to be stripped before tokenising, which discarded everything a
`.mm` file knows beyond its mathematics: `set.mm` has 55,742 of them, 46,976
carrying a `(Contributed by …)`, and the `$t` typesetting block is a comment too.
The parser now keeps them and attaches each statement's to it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.comments import Attribution, read_comment
from website.logical.metamath.parser import MetamathError

SOURCE = r"""
$( Front matter, attached to nothing. $)
$c |- wff ( ) -> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
$( Minor premise. $)
wi $a wff ( ph -> ps ) $.
$( Axiom _Simp_. See ~ ax-2 for the other one.
   (Contributed by NM, 5-Aug-1993.)
   (Revised by Mario Carneiro, 1-Jan-2015.) $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
"""


def test_a_statement_carries_the_comment_before_it() -> None:
    database = parse(SOURCE)

    assert "Axiom _Simp_" in database.assertions["ax-1"].comment
    assert database.assertions["wi"].comment.strip() == "Minor premise."


def test_every_comment_is_kept_including_unattached_ones() -> None:
    # The front matter belongs to no statement, and the `$t` block is exactly that
    # shape — so a reader that only kept per-statement comments would lose it.
    database = parse(SOURCE)

    assert len(database.comments) == 3
    assert "Front matter" in database.comments[0]


def test_a_statement_with_no_comment_before_it_has_none() -> None:
    database = parse("$c |- wff $.\n$v ph $.\nwph $f wff ph $.\nax $a |- ph $.\n")

    assert database.assertions["ax"].comment is None


def test_an_unterminated_comment_is_an_error() -> None:
    with pytest.raises(MetamathError, match="Unterminated comment"):
        parse("$c |- $.\n$( never closed\n")


def test_the_nearest_comment_wins() -> None:
    # Two comments with no statement between them: the second documents what
    # follows, and the first is front matter for it. Both are kept in `comments`;
    # only the nearer is attached.
    database = parse(
        "$c |- wff $.\n$v ph $.\nwph $f wff ph $.\n"
        "$( A section heading. $)\n$( The statement. $)\nax $a |- ph $.\n"
    )

    assert database.assertions["ax"].comment.strip() == "The statement."
    assert len(database.comments) == 2


def test_attributions_are_read_out_of_the_prose() -> None:
    description = read_comment(parse(SOURCE).assertions["ax-1"].comment)

    assert description.attributions == (
        Attribution(kind="Contributed", who="NM", when="5-Aug-1993"),
        Attribution(kind="Revised", who="Mario Carneiro", when="1-Jan-2015"),
    )
    assert description.contributors == ("NM",)
    # The prose is what is left, with the file's hard wrapping normalised away and
    # its own markup (`~ ax-2`) untouched — a renderer will want that.
    assert description.text == "Axiom _Simp_. See ~ ax-2 for the other one."


def test_a_kind_the_file_spells_oddly_is_kept_as_written() -> None:
    # `set.mm` has `Resised`, `Revisd`, `Prove shortened` and `Proof Shortened`,
    # and 22 of its 60,826 dates are malformed (`25-Jan-20178`, `XX-May-2017`, and
    # the template `dd-Mmm-yyyy` left in twice). Normalising either would mean
    # deciding what an upstream typo meant, which is not a reader's job.
    description = read_comment("Something. (Revisd by NM, XX-May-2017.)")

    assert description.attributions == (
        Attribution(kind="Revisd", who="NM", when="XX-May-2017"),
    )


def test_prose_that_reads_like_an_attribution_is_not_one() -> None:
    # Matching any `(Something by …)` picks up sentences: `set.mm` really says
    # "(This can be seen by substituting …)" and "(The order is not respected by
    # the operations …)". The date-like tail is what tells them apart.
    description = read_comment(
        "A theorem. (This can be seen by substituting ` A ` for alpha.)"
    )

    assert description.attributions == ()
    assert "This can be seen by" in description.text


def test_a_blank_line_is_a_paragraph_break_and_survives() -> None:
    # Hard wrapping is not content and goes; a blank line *is* content, being how a
    # Metamath comment marks a paragraph. 470 of set.mm's assertion comments have
    # one — `df-sb`'s explanation is nine paragraphs — and flattening them leaves a
    # run-on blob with the structure unrecoverable.
    description = read_comment(
        """ First paragraph, which the file
            wraps across lines.

            Second paragraph.
            (Contributed by NM, 5-Aug-1993.) """
    )

    assert description.text == (
        "First paragraph, which the file wraps across lines.\n\nSecond paragraph."
    )
    assert description.contributors == ("NM",)


def test_a_paragraph_that_is_only_an_attribution_leaves_no_empty_gap() -> None:
    description = read_comment("The prose.\n\n(Contributed by NM, 5-Aug-1993.)")

    assert description.text == "The prose."


def test_a_comment_with_no_attribution_is_all_prose() -> None:
    description = read_comment("  Just   prose,\n   hard-wrapped.  ")

    assert description.attributions == ()
    assert description.text == "Just prose, hard-wrapped."
