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
class Description:
    """A statement's comment, split into prose and authorship."""

    text: str
    attributions: tuple[Attribution, ...] = ()

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


def read_comment(raw: str) -> Description:
    """Split a raw ``$( … $)`` body into its prose and its attributions."""
    attributions: list[Attribution] = []
    paragraphs: list[str] = []
    for part in _PARAGRAPH.split(raw):
        # Unwrap first: an attribution is hard-wrapped like everything else, and
        # 20,875 of set.mm's are split across a line break mid-clause.
        flat = " ".join(part.split())
        attributions.extend(
            Attribution(kind=m["kind"], who=m["who"], when=m["when"])
            for m in _ATTRIBUTION.finditer(flat)
        )
        prose = " ".join(_ATTRIBUTION.sub(" ", flat).split())
        if prose:
            paragraphs.append(prose)
    return Description(text="\n\n".join(paragraphs), attributions=tuple(attributions))
