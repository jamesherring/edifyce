"""What a Metamath comment says about the statement it precedes.

Metamath has no description keyword. A statement is documented by the ``$( … $)``
comment immediately before it, and that convention is the whole of the
association - :func:`~.parser.parse` records it as ``Assertion.comment`` and this
module reads it.

Two things come out. The **description** is prose, and is left close to verbatim:
Metamath comments carry their own light markup (``~ label`` cross-references,
`` ` math ` `` spans, ``[Author]`` bibliography keys) which a renderer will want
and a reader should not destroy.

Whitespace is normalised, because a comment is hard-wrapped in the file and the
wrapping is not content - but a **blank line is**, being how a comment marks a
paragraph. 470 of `set.mm`'s assertion comments have one, `df-sb`'s among them, and
flattening those turns a structured explanation into a run-on blob with the breaks
unrecoverable. So paragraphs survive as ``\n\n`` and only the wrapping inside them
goes.

The **attributions** are the `(Contributed by …)` clauses. `set.mm` carries 60,826
of them across 55,742 comments, and they are the file's authorship record.

Recognising them by *shape* rather than by a list of kinds
---------------------------------------------------------
The obvious reading is to look for the three kinds one sees - `Contributed`,
`Revised`, `Proof shortened`. Measured over `set.mm`, that misses `Proposed` (39),
`Suggested` (6), `Shortened` (6) and `Proof revised` (2), and it would go on
missing whatever a future revision adds.

Matching any ``(Something by …)`` instead goes wrong the other way, because comment
prose says things like *"(This can be seen by substituting …)"* and *"(The order is
not respected by the operations …)"*.

So the rule is the *shape of the whole clause*: a kind, a name, and something
date-like, which is what an attribution has and a sentence does not. That admits
all 60,826 and none of the prose.

``kind`` and ``when`` are kept **verbatim**, deliberately. `set.mm` spells four of
them wrong (`Resised`, `Revisd`, `Prove shortened`, `Proof Shortened`) and 22 of
its dates are malformed (`25-Jan-20178`, `XX-May-2017`, and the template
`dd-Mmm-yyyy` left in twice). Normalising either would mean choosing what an
upstream typo *meant*, which is not a reader's job; a consumer that cares can
canonicalise, and one that cannot is better off seeing the file as it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# How long each part of an attribution may be. These are the widths of the
# columns it is stored into (`app/db/descriptions.py`), restated as part of the
# *recogniser* rather than enforced as a truncation downstream: an over-long
# capture is prose that happened to fit the shape, not a genuine attribution, so
# refusing to recognise it is the honest answer and truncating it would be a
# quiet lie about who wrote what. `set.mm`'s longest are 48 / 53 / 11, so this
# admits all 60,661 of them with room to spare.
KIND_MAX, WHO_MAX, WHEN_MAX = 64, 128, 64

# A kind, a name, and a date-like tail, delimited by the clause's own parentheses.
# The hyphen is what separates an attribution from a sentence: every date in the
# corpus has one, and no prose "… by X, Y." does.
_ATTRIBUTION = re.compile(
    rf"\((?P<kind>[A-Z][A-Za-z ]{{0,{KIND_MAX - 1}}}?) by "
    rf"(?P<who>[^,()]{{1,{WHO_MAX}}}?), "
    rf"(?P<when>[^()]{{0,{WHEN_MAX // 2 - 1}}}?-[^()]{{0,{WHEN_MAX // 2 - 1}}}?)\.?\)"
)

# A blank line, which is a paragraph break rather than wrapping.
_PARAGRAPH = re.compile(r"\n[ \t]*\n")

# A cross-reference: a lone `~` and the whitespace-delimited run after it.
#
# Delimited by whitespace and nothing else, which is measured rather than
# assumed. Stripping trailing punctuation off a target resolves **zero** further
# labels across `set.mm`'s 21,787 references, and four of its labels genuinely end
# in a `.` — so a stripping rule would cost accuracy and buy nothing.
#
# `~~` is Metamath's escape for a literal tilde and opens no reference: 84 of
# set.mm's are, every one inside a URL. Matching a lone `~` with a doubled tilde
# on neither side is what keeps `…/~~hirstjl/primer` one target rather than a
# reference to `hirstjl`.
_REFERENCE = re.compile(r"(?<!~)~(?!~)\s*(?P<target>\S+)")

# `(New usage is discouraged.)` and `(Proof modification is discouraged.)`.
#
# Bounded in length and confined to letters and spaces, because the loose reading
# — anything parenthesised containing "is discouraged" — also matches set.mm's
# one prose aside, `(TODO: ~ dral2 depends on ~ ax-13 , hence its usage during
# minimizing is discouraged. Check in the long run …)`, which is a note about a
# dependency rather than a marker on this statement. Requiring `.)` immediately
# after excludes it, and the charset excludes anything else of that shape.
#
# Loose enough to admit the corpus's own typo (`New usaged`, once) for the same
# reason the attribution recogniser matches by shape: the output here is a flag
# rather than a verbatim string, so there is nothing to preserve by refusing it,
# and a marker the file plainly meant should count.
_DISCOURAGED = re.compile(r"\((?P<what>[A-Z][A-Za-z ]{0,40}?) is discouraged\.\)")


@dataclass(frozen=True)
class Attribution:
    """One ``(Contributed by NM, 5-Apr-1994.)``-style clause, verbatim.

    ``kind`` is the phrase as written, so a consumer switching on it must not
    assume the set is closed - see the module docstring on why it is not
    normalised.
    """

    kind: str
    who: str
    when: str


@dataclass(frozen=True)
class Reference:
    """One ``~ label`` cross-reference, and the span of the prose it occupies.

    ``start``/``end`` index :attr:`Description.text` — the prose as it will be
    stored, after unwrapping and after the attributions come out — so a reader can
    render the reference as a link **without parsing the prose again**. That is
    the point of carrying them: the markup rule is Metamath's, it lives here, and
    a second implementation of it in the API or the browser is a second thing to
    get wrong. A consumer slices.

    ``target`` is the reference as it resolves, which for the 84 URLs carrying
    Metamath's ``~~`` escape is not the text on the page: the span still reads
    ``…/~~hirstjl/…`` and the target is the link that works.
    """

    target: str
    start: int
    end: int


@dataclass(frozen=True)
class Description:
    """A statement's comment, split into prose and authorship."""

    text: str
    attributions: tuple[Attribution, ...] = ()
    # Where the prose points, in order of appearance. `set.mm` writes 21,787 of
    # these across 12,389 comments and they are its "see also" graph — 21,336 name
    # another statement, the rest a URL or a page of the Metamath website.
    references: tuple[Reference, ...] = ()
    # `(New usage is discouraged.)` — this statement exists and should not be
    # built on. 5,169 of set.mm's carry it.
    discouraged_usage: bool = False
    # `(Proof modification is discouraged.)` — the proof is the way it is on
    # purpose. 1,744 carry it.
    discouraged_modification: bool = False

    @property
    def contributors(self) -> tuple[str, ...]:
        """Who the comment credits with *contributing* it, in order of appearance.

        The common question, and the one worth a name: `Revised`, `Shortened` and
        the rest are real but answer something else.
        """
        return tuple(a.who for a in self.attributions if a.kind == "Contributed")

    @property
    def title(self) -> str:
        """The first sentence, which is a statement's title in all but name.

        Metamath declares no title. What it has is the convention that a comment
        opens with a one-line summary - *"The square root of 2 is irrational."*,
        *"Define the union of two classes."* - and over `set.mm` that convention
        holds well enough to use: a median of 53 characters and 107 at the 90th
        percentile, which is a title rather than a paragraph.

        Derived rather than stored because it is a *reading* of the prose, and the
        prose is what the file wrote. A consumer wanting something else is free to
        take the first paragraph, or the label.

        The sentence ends at the first ``.``/``!``/``?`` that is outside a math
        span and outside a parenthetical, and both exclusions are measured rather
        than guessed.

        A `` ` … ` `` span is ASCII Metamath, and ASCII Metamath is full of stops -
        ``-.``, ``e.``, ``A.``, ``T.``. Splitting through one cuts 613 of `set.mm`'s
        titles mid-span, leaving *"If ` ph ` is a wff, so is ` -."*. A doubled
        backtick is Metamath's escape for a literal one and does not open a span.

        A parenthetical carries the abbreviations - *"the bound variable (i.e. the
        substituted one)"* - and stopping inside one costs a further 131 titles.
        Balancing brackets is cheaper than a list of abbreviations and does not go
        stale. It lengthens the tail (the longest runs to 707 characters against
        438 without), which is the right way round: a long title is readable and a
        truncated one is not.
        """
        inside = False
        depth = 0
        index = 0
        while index < len(self.text):
            char = self.text[index]
            if char == "`":
                if self.text[index + 1: index + 2] == "`":
                    index += 2  # An escaped backtick; the span is unaffected.
                    continue
                inside = not inside
                index += 1
                continue
            if not inside and char == "(":
                depth += 1
            elif not inside and char == ")" and depth:
                # `and depth` so a stray closer - prose does have them - cannot
                # drive the count negative and suppress every stop after it.
                depth -= 1
            elif not inside and depth == 0 and char in ".!?":
                if index + 1 == len(self.text) or self.text[index + 1].isspace():
                    return self.text[: index + 1]
            index += 1
        return self.text


def unwrap(text: str) -> str:
    """Prose with the file's hard wrapping gone and its paragraph breaks kept.

    A `.mm` comment is wrapped to a column and the wrapping is not content — but a
    blank line **is**, being the only way a comment marks a paragraph. Flattening
    both turns a structured explanation into a run-on blob with the breaks
    unrecoverable, which is why :func:`read_comment` has always kept them and why
    :mod:`~.sections` reads a section's introduction through here too.
    """
    paragraphs = (" ".join(part.split()) for part in _PARAGRAPH.split(text))
    return "\n\n".join(part for part in paragraphs if part)


def read_comment(raw: str) -> Description:
    """Split a raw ``$( … $)`` body into its prose, authorship and markup."""
    attributions: list[Attribution] = []
    paragraphs: list[str] = []
    discouraged: list[str] = []
    for part in _PARAGRAPH.split(raw):
        # Unwrap first: an attribution is hard-wrapped like everything else, and
        # 20,875 of set.mm's are split across a line break mid-clause.
        flat = " ".join(part.split())
        attributions.extend(
            Attribution(kind=m["kind"], who=m["who"], when=m["when"])
            for m in _ATTRIBUTION.finditer(flat)
        )
        discouraged.extend(m["what"].lower() for m in _DISCOURAGED.finditer(flat))
        # Both come out of the prose for the same reason: they are markers about
        # the statement rather than sentences about the mathematics, and leaving
        # them in would put them in the title of the 64 comments that open with
        # one. What they said is kept — as rows, and as the two flags below.
        prose = _DISCOURAGED.sub(" ", _ATTRIBUTION.sub(" ", flat))
        prose = " ".join(prose.split())
        if prose:
            paragraphs.append(prose)

    text = "\n\n".join(paragraphs)
    return Description(
        text=text,
        attributions=tuple(attributions),
        # Read off the assembled prose rather than the raw comment, so the offsets
        # index what is stored. Anything else would need the reader to redo the
        # unwrapping to make sense of them.
        references=_references(text),
        discouraged_usage=any("usage" in what for what in discouraged),
        discouraged_modification=any("modification" in what for what in discouraged),
    )


def _references(text: str) -> tuple[Reference, ...]:
    """Every ``~ target`` in ``text``, with the span each occupies."""
    return tuple(
        Reference(
            # `~~` is a literal tilde, so a target carrying one resolves with it
            # collapsed — every one of set.mm's is inside a URL, where the doubled
            # form is a link that 404s.
            target=match["target"].replace("~~", "~"),
            start=match.start(),
            end=match.end(),
        )
        for match in _REFERENCE.finditer(text)
    )
