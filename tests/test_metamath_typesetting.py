"""The ``$t`` block — a `.mm` file's own notation map, and its own little language.

`$t` is not Metamath's token stream. It has its own comments, its own quoting, and
statements terminated by `;` rather than by whitespace, so it needs scanning
rather than splitting. Each case below is one this module got wrong first or would
have: they are drawn from what `set.mm`'s block actually contains.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.parser import MetamathError
from website.logical.metamath.typesetting import (
    as_text,
    parse_typesetting,
    typesetting_of,
)

BLOCK = r"""$t
/* A comment inside the block, which may sit anywhere a space may. */
latexdef "e." as "\in";
althtmldef "e." as ' &isin; ';
htmldef "e." as ' &isin; ';

/* Concatenation across lines: 44 of set.mm's althtmldef entries use it. */
althtmldef "U." as '<FONT SIZE="+1">' +
    '&cup;' +
    '</FONT>';

/* A token containing a double quote must be single-quoted — set.mm has 65. */
althtmldef '"' as " &ldquo; ";

/* Not notation, and its value is a stylesheet full of semicolons and braces. */
htmlcss '<STYLE TYPE="text/css">' +
    '  .setvar { color: red; }' +
    '</STYLE>';
htmltitle "Metamath Proof Explorer";
"""


def test_the_three_maps_are_read() -> None:
    typesetting = parse_typesetting(BLOCK)

    assert typesetting.latex["e."] == r"\in"
    assert typesetting.unicode["e."] == " &isin; "
    assert typesetting.html["e."] == " &isin; "


def test_values_concatenated_with_plus_are_joined() -> None:
    assert parse_typesetting(BLOCK).unicode["U."] == '<FONT SIZE="+1">&cup;</FONT>'


def test_a_single_quoted_token_may_contain_a_double_quote() -> None:
    assert parse_typesetting(BLOCK).unicode['"'] == " &ldquo; "


def test_a_directive_whose_value_contains_semicolons_does_not_derail_the_scan() -> None:
    # The bug this pins: skipping an unrecognised directive by seeking the next
    # `;` stops inside `htmlcss`'s stylesheet, and every directive after it is
    # then read from the middle of a string. Found against the real block.
    typesetting = parse_typesetting(BLOCK)

    assert set(typesetting.unicode) == {"e.", "U.", '"'}
    assert "htmlcss" not in typesetting.unicode


def test_a_doubled_quote_escapes_itself() -> None:
    typesetting = parse_typesetting('$t latexdef "x" as "a""b";')

    assert typesetting.latex["x"] == 'a"b'


def test_an_unterminated_string_is_an_error() -> None:
    with pytest.raises(MetamathError, match="unterminated string"):
        parse_typesetting('$t latexdef "x" as "never closed;')


def test_a_directive_with_no_terminator_is_an_error() -> None:
    with pytest.raises(MetamathError, match="no terminating ';'"):
        parse_typesetting('$t latexdef "x" as "y"')


def test_the_block_is_found_among_a_database_s_comments() -> None:
    source = f"$( {BLOCK} $)\n$c |- wff $.\n$v ph $.\nwph $f wff ph $.\nax $a |- ph $.\n"
    typesetting = typesetting_of(parse(source).comments)

    assert typesetting is not None
    assert typesetting.latex["e."] == r"\in"


def test_a_database_with_no_block_has_no_typesetting() -> None:
    # Optional: a `.mm` written for checking rather than publishing carries none.
    assert typesetting_of(parse("$c |- $.\n$( just prose $)\n").comments) is None


def test_as_text_turns_a_rendering_into_the_characters_it_denotes() -> None:
    # `althtmldef` is *HTML that renders as* Unicode, not Unicode: 719 of set.mm's
    # 1,794 values carry markup, and only 149 of the rest are non-ASCII once
    # unescaped. Deriving a Unicode source is this function, not a substitution.
    assert as_text(" &isin; ") == "∈"
    assert as_text('<SPAN CLASS=wff STYLE="color:blue">&#x1D711;</SPAN>') == "𝜑"
    assert as_text("wff ") == "wff"
