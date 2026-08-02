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

# A kind, a name, and a date-like tail, delimited by the clause's own parentheses.
# The hyphen is what separates an attribution from a sentence: every date in the
# corpus has one, and no prose "… by X, Y." does.
_ATTRIBUTION = re.compile(
    r"\((?P<kind>[A-Z][A-Za-z ]*?) by (?P<who>[^,()]+?), (?P<when>[^()]*?-[^()]*?)\.?\)"
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
