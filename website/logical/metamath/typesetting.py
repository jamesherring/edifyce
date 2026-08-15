"""The ``$t`` typesetting block: a Metamath file's own notation map.

A `.mm` file is written in ASCII (`e.`, `A.`, `->`, `RR`) because that was the
1990s constraint, and it carries the readable spellings separately - in a ``$t``
block, which is a comment and so was discarded along with every other comment
until :mod:`~.parser` began keeping them.

`set.mm`'s block is 305 KB and defines all three maps over the same **1,794**
tokens:

======================  ==========================================
``latexdef``            LaTeX (``\\in``, ``\\mathbb{R}``, ``\\surd``)
``htmldef``             HTML with entities (``&rarr;``, ``&not;``)
``althtmldef``          HTML, but chosen to spell Unicode symbols
======================  ==========================================

(Counting occurrences of the keywords instead gives 1,818 / 1,867 / 1,882, which
is wrong in the way this module is built to avoid: the surplus is directives
commented out inside the block's own ``/* … */``.)

Note what these are **not**, since both mistakes are easy to make.

They are per-*token* substitutions, so applying one naively yields token soup -
``( \\surd \\` 2 ) \\in \\mathbb{R}``. Edifyce has the parse tree, so a display
projection folds per-*production* templates over the term graph instead and can
render ``\\sqrt{2} \\in \\mathbb{R}``. This map seeds those templates; it does not
replace them.

And ``althtmldef`` is not Unicode text. It is *HTML that renders as* Unicode, which
is a different thing: 719 of its 1,794 values carry ``<SPAN>`` markup, including
every variable (``ph`` is ``<SPAN CLASS=wff STYLE="color:blue">&#x1D711;</SPAN>``,
the colour encoding its typecode). Of the 1,075 that are entity-only, just 149
unescape to a non-ASCII character; the rest are ASCII already. So deriving a
Unicode *source* from it - which is what the roadmap's §4.2 proposes - needs
:func:`as_text`, and needs a policy for the markup rather than a substitution.

``htmldef`` is likewise not MathML - it is HTML with entities and ``<SPAN>``
wrappers. MathML wants generating from the term structure, not transcribing.

The little language
-------------------
``$t`` is not Metamath's token stream and cannot be read with ``split()``:

- directives end at ``;``, not at whitespace;
- values are strings concatenated with ``+``, across line breaks (44 of `set.mm`'s
  `althtmldef` entries use it);
- strings are double- *or* single-quoted, since a token containing ``"`` must be
  written ``'"'`` - 65 of them are;
- and the block has 330 ``/* … */`` comments of its own inside it.

So this scans rather than pattern-matches. Directives it does not recognise
(``htmltitle``, ``htmlcss``, ``exthtmlhome``, …) are read and skipped rather than
tripped over, since the block is documentation as much as data.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .directives import read_value, read_word, skip_space
from .parser import MetamathError

_WHERE = "$t block"

if TYPE_CHECKING:
    from collections.abc import Sequence

# An HTML tag in a `$t` value. Only `<SPAN>`/`<FONT>`-style presentation appears
# there, so dropping tags leaves the text they wrap - see `as_text`.
_TAG = re.compile(r"<[^>]*>")

# The directives that map one token to one rendering. Everything else in a `$t`
# block configures a website (titles, stylesheets, bibliography links) and is not
# notation, so it is skipped rather than stored.
_DEFINITIONS = ("latexdef", "htmldef", "althtmldef")


@dataclass
class Typesetting:
    """The notation maps a ``$t`` block declares, by directive.

    Keyed by the Metamath token, so ``latex["e."]`` is ``"\\in"``. Values are
    **verbatim**, markup included, because that is what the file declares and a
    LaTeX consumer and an HTML one want different things from it; :func:`as_text`
    is the derivation, kept separate so its policy is visible.

    `set.mm` happens to define all three over the same token set, but nothing
    requires that of a `.mm` file and a token may be absent from any of them.
    """

    latex: dict[str, str] = field(default_factory=dict)
    html: dict[str, str] = field(default_factory=dict)
    unicode: dict[str, str] = field(default_factory=dict)

    def map_for(self, directive: str) -> dict[str, str]:
        return {
            "latexdef": self.latex,
            "htmldef": self.html,
            "althtmldef": self.unicode,
        }[directive]


def as_text(rendering: str) -> str:
    """An ``htmldef``/``althtmldef`` value as plain text.

    Entities become the characters they name (``&isin;`` -> ``∈``) and tags are
    dropped, leaving what the markup wrapped. That last step is a *policy*, not a
    conversion, and it is why this is a function rather than something the parser
    does: `set.mm` uses the tags to colour a variable by its typecode, so dropping
    them discards a distinction the HTML makes and plain text cannot. For a
    Unicode source that is the right trade - the typecode is recoverable from the
    grammar - but it is a choice, and a caller wanting the colours should read the
    raw value instead.
    """
    return html.unescape(_TAG.sub("", rendering)).strip()


def parse_typesetting(block: str) -> Typesetting:
    """Read a ``$t`` comment body into its notation maps.

    ``block`` is the comment's text, with or without the leading ``$t``.
    """
    typesetting = Typesetting()
    index = skip_space(block, 0, _WHERE)
    if block.startswith("$t", index):
        index += 2

    while True:
        index = skip_space(block, index, _WHERE)
        if index >= len(block):
            return typesetting

        directive, index = read_word(block, index)
        if not directive:
            raise MetamathError(
                f"$t block: expected a directive at offset {index}, "
                f"found {block[index]!r}."
            )

        # Read the whole directive uniformly, whatever it is: a run of values and
        # bare words up to the terminating `;`. Skipping an unrecognised directive
        # by seeking `;` does not work, because `htmlcss`'s value is a stylesheet
        # and is full of them - inside strings, where they are not terminators.
        values: list[str] = []
        while True:
            index = skip_space(block, index, _WHERE)
            if index >= len(block):
                raise MetamathError(f"$t block: {directive!r} has no terminating ';'.")
            if block[index] == ";":
                index += 1
                break
            if block[index] in "\"'":
                value, index = read_value(block, index, _WHERE)
                values.append(value)
                continue
            # A bare word - `as`, which separates a `*def`'s two halves.
            word, index = read_word(block, index)
            if not word:
                raise MetamathError(
                    f"$t block: unexpected {block[index]!r} in {directive!r} "
                    f"at offset {index}."
                )

        if directive not in _DEFINITIONS:
            # Website configuration - titles, stylesheets, bibliography links -
            # rather than notation. Read so as to get past it, then dropped.
            continue
        if len(values) != 2:
            raise MetamathError(
                f"$t block: {directive} takes a token and a rendering, "
                f"got {len(values)} values."
            )
        typesetting.map_for(directive)[values[0]] = values[1]


def typesetting_of(comments: Sequence[str]) -> Typesetting | None:
    """The typesetting declared by whichever comment is the ``$t`` block, if any.

    A `.mm` file may have none - the block is optional, and a database written for
    checking rather than publishing will not carry one.
    """
    for body in comments:
        if body.lstrip().startswith("$t"):
            return parse_typesetting(body)
    return None
