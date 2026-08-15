"""The ``$j`` blocks: a `.mm` file's declarations about itself.

``$t`` says how to spell a token. ``$j`` says the things Metamath's language has
no keyword for — which productions are primitive, which connective is a typecode's
equality, which axioms a theorem's proof avoids — and `set.mm` writes 1,221 of
them across 1,203 blocks.

One shape covers all of them (`keyword arg* (preposition arg*)* ;`), which is why
this reads rather than switching per keyword. Nothing here interprets: what a
directive *means* belongs to whoever asked for it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath.markup import (
    PREPOSITIONS,
    Directive,
    by_keyword,
    claims_of,
    markup_of,
    parse_markup,
)
from website.logical.metamath.parser import MetamathError


def test_a_bare_directive_is_a_keyword_and_its_arguments() -> None:
    (found,) = parse_markup("$j primitive 'wn';")

    assert found == Directive(keyword="primitive", arguments=("wn",))
    assert found.subject == "wn"


def test_a_preposition_opens_a_clause() -> None:
    (found,) = parse_markup("$j usage 'ax1w' avoids 'ax-2' 'ax-3';")

    assert found.keyword == "usage"
    assert found.arguments == ("ax1w",)
    assert found.clause("avoids") == ("ax-2", "ax-3")
    # And a preposition the directive does not carry is nothing, not an error.
    assert found.clause("from") == ()


def test_several_directives_share_one_block() -> None:
    # set.mm writes them this way where they belong together: the block beside
    # `wb` declares its equality and its definition in one comment.
    found = parse_markup(
        "$j equality 'wb' from 'biid' 'bicomi' 'bitri'; definition 'dfbi1' for 'wb';"
    )

    assert [d.keyword for d in found] == ["equality", "definition"]
    assert found[0].clause("from") == ("biid", "bicomi", "bitri")
    assert found[1].clause("for") == ("wb",)


def test_a_leading_marker_is_optional() -> None:
    assert parse_markup("primitive 'wn';") == parse_markup("$j primitive 'wn';")


def test_the_blocks_own_comments_are_skipped() -> None:
    found = parse_markup("$j /* why */ primitive /* which */ 'wn'; /* done */")

    assert [d.keyword for d in found] == ["primitive"]


def test_a_value_may_be_concatenated_and_quoted_either_way() -> None:
    # The `$t` block's rules, since it is the same little language: `+` joins
    # strings, and a token containing one kind of quote is written in the other.
    (found,) = parse_markup("""$j syntax 'a' + "b" + 'c';""")

    assert found.arguments == ("abc",)


def test_a_doubled_quote_is_a_literal_one() -> None:
    (found,) = parse_markup("$j syntax 'it''s';")

    assert found.arguments == ("it's",)


def test_prepositions_are_a_closed_set() -> None:
    # The reason it is closed: `garden_path` is written in bare *math* tokens, and
    # an open reading would take its `A` and `ph` for prepositions and invent
    # clauses nobody wrote.
    (found,) = parse_markup("$j garden_path ( A => ( ph ;")

    assert found.keyword == "garden_path"
    assert found.clauses == {}
    assert found.arguments == ("(", "A", "=>", "(", "ph")
    assert "ph" not in PREPOSITIONS


def test_a_directive_naming_nothing_has_no_subject() -> None:
    (found,) = parse_markup("$j type_conversions;")

    assert found.arguments == () and found.subject is None


def test_a_repeated_preposition_is_refused_rather_than_half_read() -> None:
    # Nothing in set.mm does this, and a file that did would be saying something
    # the shape here cannot hold — better refused than silently missing half.
    with pytest.raises(MetamathError, match="twice"):
        parse_markup("$j usage 'a' avoids 'b' avoids 'c';")


def test_a_directive_with_no_terminator_is_an_error() -> None:
    with pytest.raises(MetamathError, match="terminating"):
        parse_markup("$j primitive 'wn'")


def test_an_unterminated_string_is_an_error() -> None:
    with pytest.raises(MetamathError, match="unterminated string"):
        parse_markup("$j primitive 'wn;")


def test_an_unterminated_block_comment_is_an_error() -> None:
    with pytest.raises(MetamathError, match="unterminated /"):
        parse_markup("$j primitive /* forever 'wn';")


def test_only_the_j_comments_are_read() -> None:
    # A file's comments are mostly prose, and one of them is the `$t` block, which
    # is the same language and a different subject.
    found = markup_of(
        [
            "A description of a theorem.",
            "$t latexdef \"ph\" as \"\\\\varphi\";",
            "$j primitive 'wn';",
            "$j primitive 'wi';",
        ]
    )

    assert [d.subject for d in found] == ["wn", "wi"]


def test_a_file_with_no_j_block_declares_nothing() -> None:
    assert markup_of(["Just prose.", "$t latexdef \"a\" as \"b\";"]) == ()


def test_directives_can_be_taken_by_keyword() -> None:
    found = markup_of(["$j primitive 'wn'; usage 'a' avoids 'b'; primitive 'wi';"])

    assert [d.subject for d in by_keyword(found, "primitive")] == ["wn", "wi"]
    assert [d.subject for d in by_keyword(found, "usage")] == ["a"]
    assert list(by_keyword(found, "nothing")) == []


# ---------------------------------------------------------------------------
# Directives flattened to claims
#
# The shape that makes 24 kinds one table rather than 24: a subject, a kind and
# at most one object.
# ---------------------------------------------------------------------------


def test_a_directive_with_a_preposition_claims_once_per_value() -> None:
    (claims) = claims_of(parse_markup("usage 'a1i' avoids 'ax-11' 'ax-12';"))

    assert [(c.subject, c.kind, c.object) for c in claims] == [
        ("a1i", "usage_avoids", "ax-11"),
        ("a1i", "usage_avoids", "ax-12"),
    ]


def test_a_directive_with_no_preposition_claims_about_each_argument() -> None:
    # `primitive 'wn' 'wi';` says the same thing about both and names no object.
    claims = claims_of(parse_markup("primitive 'wn' 'wi';"))

    assert [(c.subject, c.kind, c.object) for c in claims] == [
        ("wn", "primitive", None),
        ("wi", "primitive", None),
    ]


def test_the_preposition_is_part_of_the_kind() -> None:
    # `equality … from` and `notfree … from` share a word and mean different
    # things, so the keyword alone would collapse two relations into one.
    claims = claims_of(
        parse_markup("equality 'wb' from 'biid'; notfree 'wnf' from 'nfcdeq';")
    )

    assert [c.kind for c in claims] == ["equality_from", "notfree_from"]


def test_a_directive_with_several_prepositions_claims_under_each() -> None:
    claims = claims_of(parse_markup("natded_true 'wtru' with 'mptru' 'tru';"))

    assert [(c.kind, c.object) for c in claims] == [
        ("natded_true_with", "mptru"),
        ("natded_true_with", "tru"),
    ]


def test_a_colour_table_claims_nothing() -> None:
    # `varcolorcode` is presentation for Metamath's own site — the same reason
    # `htmldef` is skipped — and its values are hex, not names.
    assert claims_of(parse_markup("varcolorcode 'wff' as '0000FF';")) == ()


def test_a_garden_path_hint_claims_nothing() -> None:
    # Written in bare math tokens rather than labels.
    assert claims_of(parse_markup("garden_path ( A => ( ph ;")) == ()


def test_an_unrecognised_keyword_is_still_a_claim() -> None:
    # A deny-list, not an allow-list: a keyword some future file invents lands as
    # data rather than being dropped in silence.
    claims = claims_of(parse_markup("someday 'x' of 'y';"))

    assert [(c.subject, c.kind, c.object) for c in claims] == [("x", "someday_of", "y")]
