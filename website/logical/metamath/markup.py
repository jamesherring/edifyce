"""The ``$j`` blocks: what a `.mm` file declares about itself.

``$t`` says how to *spell* a token; ``$j`` says things the language has no keyword
for — which productions are primitive, which connective is the equality of a
typecode, which axioms a theorem's proof avoids. Metamath's own verifier checks
some of them and ignores the rest; either way they are declarations, and a `.mm`
file is the only place they are written down.

`set.mm` carries **1,203 blocks and 1,221 directives**, and the distribution is
lopsided enough to be worth stating before reading any of it:

==================  =====  ==================================================
``usage``           1,136  ``usage 'ax1w' avoids 'ax-2' 'ax-3';``
``restatement``        29  ``restatement 'bicomi' of 'bicom';``
``primitive``          11  ``primitive 'wn';``
``congruence``          6  and then a long tail of ones and twos —
``syntax``              4  ``equality``, ``definition``, ``bound``,
``garden_path``         4  ``free_var``, ``justification``, ``notfree``,
``varcolorcode``        3  ``condequality``, the nine ``natded_*`` …
==================  =====  ==================================================

**One shape for all of them**, which is what makes a general reader worth having
rather than a switch per keyword::

    keyword arg* (preposition arg*)* ;

A quoted string is an argument; a bare word is the keyword, or a preposition from
a **closed** set (`as`, `avoids`, `for`, `from`, `of`, `with`). Closed matters:
``garden_path`` is written in *bare math tokens* — ``garden_path ( A => ( ph ;`` —
and an open reading would take its `A` and `ph` for prepositions and invent
clauses nobody wrote. It is a hint to Metamath's own grammar tooling and nothing
Edifyce needs, so its tokens are read as arguments and the scan carries on, the
way :mod:`~.typesetting` reads and drops the website-configuration directives.

Nothing here interprets. A :class:`Directive` is the file's sentence in structure,
and what any keyword *means* belongs to whoever asked — `setmm` checks its own
tables against them, and an import stores the one with mass.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from .directives import read_value, read_word, skip_space
from .parser import MetamathError

_WHERE = "$j block"

# The prepositions a directive may carry, which is a **closed** set: `set.mm` uses
# exactly these six. Closed rather than "any bare word", because `garden_path`'s
# arguments are bare math tokens and `A` or `ph` among them would otherwise read
# as a clause nobody wrote.
PREPOSITIONS = frozenset({"as", "avoids", "for", "from", "of", "with"})


def _opaque(text: str, index: int) -> tuple[str, int]:
    """One bare token that is not a word — `(`, `=>`, `{`, `<.`.

    Only `garden_path` and `type_conversions` are written in these, and neither
    says anything Edifyce needs; what this buys is getting past them intact rather
    than refusing a file that carries one.
    """
    start = index
    while index < len(text) and not text[index].isspace() and text[index] not in ";\"'":
        index += 1
    if index == start:
        raise MetamathError(f"{_WHERE}: unexpected {text[index]!r} at offset {index}.")
    return text[start:index], index


@dataclass(frozen=True)
class Directive:
    """One ``$j`` sentence: a keyword, its arguments, and its clauses.

    ``usage 'ax1w' avoids 'ax-2' 'ax-3';`` is ``keyword='usage'``,
    ``arguments=('ax1w',)`` and ``clauses={'avoids': ('ax-2', 'ax-3')}``.

    ``clauses`` is a mapping rather than a list of pairs because no directive in
    `set.mm` uses the same preposition twice — and one that did would be saying
    something this shape cannot express, which is better refused than silently
    half-read.
    """

    keyword: str
    arguments: tuple[str, ...] = ()
    clauses: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def clause(self, preposition: str) -> tuple[str, ...]:
        """The arguments after ``preposition``, or none if it carries no such clause."""
        return self.clauses.get(preposition, ())

    @property
    def subject(self) -> str | None:
        """The label or typecode the directive is *about* — its first argument.

        Every keyword in `set.mm` that says anything about a named thing says it
        first: `primitive 'wn'`, `equality 'wb' from …`, `usage 'ax1w' avoids …`.
        None for the two that name nothing (`type_conversions`, and a
        `garden_path` whose tokens are bare).
        """
        return self.arguments[0] if self.arguments else None


def parse_markup(block: str) -> tuple[Directive, ...]:
    """Read one ``$j`` comment body into its directives.

    ``block`` is the comment's text, with or without the leading ``$j``.
    """
    found: list[Directive] = []
    index = skip_space(block, 0, _WHERE)
    if block.startswith("$j", index):
        index += 2

    while True:
        index = skip_space(block, index, _WHERE)
        if index >= len(block):
            return tuple(found)

        keyword, index = read_word(block, index)
        if not keyword:
            raise MetamathError(
                f"{_WHERE}: expected a directive at offset {index}, "
                f"found {block[index]!r}."
            )

        arguments: list[str] = []
        clauses: dict[str, tuple[str, ...]] = {}
        # Which list the next argument joins: the directive's own until a
        # preposition appears, then that preposition's.
        current = arguments
        while True:
            index = skip_space(block, index, _WHERE)
            if index >= len(block):
                raise MetamathError(f"{_WHERE}: {keyword!r} has no terminating ';'.")
            if block[index] == ";":
                index += 1
                break
            if block[index] in "\"'":
                value, index = read_value(block, index, _WHERE)
                current.append(value)
                continue
            word, index = read_word(block, index)
            if word in PREPOSITIONS:
                if word in clauses:
                    raise MetamathError(
                        f"{_WHERE}: {keyword!r} uses {word!r} twice, which this "
                        "reader has no shape for."
                    )
                current = []
                clauses[word] = current  # type: ignore[assignment]
                continue
            # A bare token rather than a preposition. `garden_path` is written in
            # them — `garden_path ( A => ( ph ;` — so this reads one and keeps
            # going rather than tripping on a directive nothing here interprets.
            if not word:
                word, index = _opaque(block, index)
            current.append(word)

        found.append(
            Directive(
                keyword=keyword,
                arguments=tuple(arguments),
                clauses={word: tuple(args) for word, args in clauses.items()},
            )
        )


def markup_of(comments: Sequence[str]) -> tuple[Directive, ...]:
    """Every directive from every ``$j`` block, in file order.

    Unlike ``$t`` — of which a file has one — the ``$j`` blocks are scattered
    through the source, each sitting beside what it talks about. `set.mm` has
    1,203, so a caller wants them as one sequence rather than as blocks.
    """
    return tuple(
        directive
        for body in comments
        if body.lstrip().startswith("$j")
        for directive in parse_markup(body)
    )


def by_keyword(directives: Sequence[Directive], keyword: str) -> Iterator[Directive]:
    """Those of ``directives`` with this keyword, in order."""
    return (directive for directive in directives if directive.keyword == keyword)
