"""The outline a `.mm` file draws with comments.

Metamath declares no sections. What it has — like descriptions, and like titles —
is a convention: a comment whose first line is a rule of repeated punctuation, a
title, and the same rule again, marks the start of a section, and the depth is
which punctuation was used. `set.mm` uses all four levels the Metamath book
describes and draws **1,903** of them:

======  ==============  =====  ============================================
Rule    Level           Count  Example title
======  ==============  =====  ============================================
``####``  part             21  CLASSICAL FIRST-ORDER LOGIC WITH EQUALITY
``#*#*``  section         163  Pre-logic
``=-=-``  subsection    1,115  Inferences for assisting proof development
``-.-.``  subsubsection   604  Universal quantifier for use by df-tru
======  ==============  =====  ============================================

A header says where a section *starts* and nothing about where it ends: the next
header of the same or a shallower level closes it. So an outline is a flat list
in file order plus a level, and the tree is recovered by a stack — which is what
:func:`tree` does.

Recognising a rule
------------------
Tightly, because the alternative is reading prose as structure. A rule line must
**begin with the four-character motif** and contain nothing but that motif's own
characters, which no sentence does. Matching on the charset alone would not do:
a line of hyphens is a subset of both ``=-=-`` and ``-.-.``, and the prefix is
what tells them apart.

The prose that follows
----------------------
308 of `set.mm`'s headers carry explanatory text after the closing rule, and the
part-level ones carry a great deal of it — one runs to 20,783 characters. It is
kept: a section's introduction is content, and the alternative is discarding the
only prose a `.mm` file has about its own structure.

It is read through :func:`~.comments.unwrap`, the same rule a *statement's*
description gets: the file's hard wrapping is not content and goes, and a blank
line is — being the only way a comment marks a paragraph — and stays. 141 of the
308 are multi-paragraph, and all 141 survive; flattening them would turn a
structured introduction into a run-on blob with the breaks unrecoverable.

Nothing here reads a statement. A header is positioned by
:class:`~.parser.Commentary`'s ``at``, which is where the file put it.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .comments import unwrap

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .parser import Database

# The four rules the Metamath book describes, deepest level last. A header's
# level *is* which motif it drew, so this table is the whole of the vocabulary.
RULES: tuple[tuple[str, int], ...] = (
    ("####", 1),
    ("#*#*", 2),
    ("=-=-", 3),
    ("-.-.", 4),
)

# How deep the outline can go, which is how many rules there are.
MAX_LEVEL = len(RULES)


@dataclass(frozen=True)
class Section:
    """One header: where a section starts, how deep it is, and what it says."""

    level: int
    title: str
    # The prose after the closing rule, paragraphs preserved; "" for a header
    # that carries none, which is most of them.
    text: str
    # Index into ``Database.order``: the first assertion this section covers. A
    # section with no assertions after it (a header at the end of a file) has
    # ``at == len(order)`` and covers nothing, which is not an error.
    at: int


@dataclass
class Node:
    """A section and the sections nested under it."""

    section: Section
    children: list[Node] = field(default_factory=list)


def _rule_level(line: str) -> int | None:
    """The level of a rule line, or None if it is not one.

    The motif must be the *prefix* and the whole alphabet of the line. Charset
    alone would confuse ``=-=-`` with ``-.-.`` on a line of bare hyphens, and
    prefix alone would let a sentence starting with punctuation through.
    """
    for motif, level in RULES:
        if line.startswith(motif) and set(line) <= set(motif):
            return level
    return None


def read_header(body: str) -> tuple[int, str, str] | None:
    """``(level, title, text)`` if ``body`` is a section header, else None.

    The shape is rule / title / rule / optional prose. The title is everything
    between the rules — one line in all 1,903 of `set.mm`'s, but joined rather
    than assumed, so a wrapped one survives instead of being truncated.
    """
    lines = [line.strip() for line in body.splitlines()]
    # The structural scan ignores blank lines, but the *prose* must not: a blank
    # line is the only way a comment marks a paragraph. So the rules are found by
    # their index into the original lines rather than into a compacted copy.
    filled = [index for index, line in enumerate(lines) if line]
    if len(filled) < 3:
        return None

    level = _rule_level(lines[filled[0]])
    if level is None:
        return None
    closing = next(
        (
            position
            for position in range(1, len(filled))
            if _rule_level(lines[filled[position]]) == level
        ),
        None,
    )
    # A rule with no matching rule after it is decoration, not a header: there is
    # no title between them because there is no second one.
    if closing is None or closing == 1:
        return None

    title = " ".join(lines[filled[position]] for position in range(1, closing))
    return level, title, unwrap("\n".join(lines[filled[closing] + 1:]))


def outline(database: Database) -> list[Section]:
    """Every section ``database`` declares, in file order."""
    found: list[Section] = []
    for entry in database.commentary:
        header = read_header(entry.body)
        if header is None:
            continue
        level, title, text = header
        found.append(Section(level=level, title=title, text=text, at=entry.at))
    return found


def tree(sections: Iterable[Section]) -> list[Node]:
    """The outline as nesting, from the flat list.

    A header opens a section and closes every open one at its level or deeper;
    the roots are what is left. A level that skips one — a subsection with no
    section before it — nests under the deepest thing still open rather than
    being dropped or promoted, so a file's own structure survives its own
    irregularity. `set.mm` skips none, but nothing in Metamath forbids it.
    """
    roots: list[Node] = []
    stack: list[Node] = []
    for section in sections:
        node = Node(section=section)
        while stack and stack[-1].section.level >= section.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


class Placement:
    """Which section covers a given statement, asked many times.

    A section runs from its own position to the next header at its level or
    shallower, so the deepest section covering a statement is simply the last
    header at or before it — every shallower one it belongs to is an ancestor of
    that, and every deeper one starts later.

    A class rather than a function because the question is asked once per
    *statement*: `set.mm` is 1,903 sections and 50,550 assertions, and rebuilding
    the index per lookup would be 96 million comparisons for an answer that is
    three each once the starts are laid out.
    """

    def __init__(self, sections: Sequence[Section]) -> None:
        self._sections = tuple(sections)
        self._starts = [section.at for section in self._sections]

    def covering(self, at: int) -> Section | None:
        """The deepest section covering position ``at``, or None if none does."""
        index = self.covering_index(at)
        return None if index is None else self._sections[index]

    def covering_index(self, at: int) -> int | None:
        """:meth:`covering` as an index into the sections, or None.

        The index rather than the section, for a caller that has something of its
        own per section to look up. Two headers may share an ``at`` — a part
        followed straight away by a section, with no statement between — so a
        section is not identified by its position in the file, and a caller keying
        on that would silently collapse the pair.
        """
        index = bisect_right(self._starts, at)
        return index - 1 if index else None


@dataclass(frozen=True)
class Layer:
    """One layer of the spine an import splits a corpus into.

    ``starts_with`` is a **prefix of a section's title**, and the layer runs from
    that section to wherever the next layer starts. Contiguity is not a
    simplification: a `.mm` file is topologically ordered, so a layer that is a
    contiguous range of file positions cannot cite a later one, which is D5's
    first invariant obtained by construction rather than by checking (§7.2).

    A prefix rather than the whole title because `set.mm`'s run long and carry
    their own punctuation — "Predicate calculus with equality:  Tarski's system
    S2 (1 rule, 6 schemes)", double space and all — and a plan that had to
    reproduce one exactly would break on a reformatting that changed nothing.
    """

    name: str
    starts_with: str


class Layering:
    """Which layer of a plan covers a given statement.

    The same shape as :class:`Placement` and for the same reason — the question
    is asked once per statement, and `set.mm` has 50,625 of them — but over a
    handful of boundaries rather than 1,903 sections.

    A plan whose layers do not all match is **not** an error here: a `.mm` file
    may be a fragment, or a variant that stops before ZFC, and a layer with no
    section to open it simply has no statements. What is refused is a plan whose
    layers match *out of order*, since that is a plan describing a different file
    and every position it then reports would be wrong.
    """

    def __init__(self, sections: Sequence[Section], plan: Sequence[Layer]) -> None:
        self._names: list[str] = []
        self._starts: list[int] = []
        for layer in plan:
            at = next(
                (
                    section.at
                    for section in sections
                    if section.title.startswith(layer.starts_with)
                ),
                None,
            )
            if at is None:
                continue
            if self._starts and at < self._starts[-1]:
                raise ValueError(
                    f"Layer {layer.name!r} starts at position {at}, before "
                    f"{self._names[-1]!r} at {self._starts[-1]}. A layer plan is "
                    "the spine's order, so its layers must open in that order."
                )
            self._names.append(layer.name)
            self._starts.append(at)

    @property
    def starts(self) -> list[tuple[str, int]]:
        """Each layer that matched, and the position it opens at."""
        return list(zip(self._names, self._starts))

    def covering(self, at: int) -> str | None:
        """The layer covering position ``at``, or None if it precedes them all."""
        index = bisect_right(self._starts, at)
        return self._names[index - 1] if index else None
