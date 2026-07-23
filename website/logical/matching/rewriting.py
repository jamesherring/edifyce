"""All-solutions associative matching for string-rewriting inference rules.

The default rule checker unifies kernel *terms* — first-order matching, where a
schema variable binds a whole grammatical subterm. That is the wrong tool for a
string-rewriting system (a semi-Thue system such as Hofstadter's MIU), whose
rules split and concatenate flat strings: ``Mx -> Mxx``, ``xIIIy -> xUy``. This
module supplies the matching those rules need, entirely in the string world:
given a rule-schema :class:`~website.logical.matching.patterns.StringPattern`
(literals interleaved with sort-typed variables) and a concrete string,
enumerate *every* consistent variable -> substring assignment.

It lives in ``matching``, never the kernel, on purpose. ``matching`` must not
import the kernel, and word/associative matching is a matching-layer concern.
``StringPattern`` already decomposes a template into ``variable_locations`` and
``non_variable_locations``; this walks that decomposition and searches the split
points the term unifier structurally cannot.

Semantics: a variable ranges over a possibly-empty substring (the "gap" either
side of ``III`` in ``xIIIy`` may be empty); every *non-empty* binding must match
the variable's own sort, so an ``x : term`` cannot capture text the grammar
rejects. A repeated variable — the two ``x``s of ``Mxx`` — is forced to agree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .patterns import StringPattern

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .context import Context
    from .patterns import Pattern

    # A rewriting substitution: schematic variable name -> the substring it binds.
    Binding = dict[str, str]
    # An ordered (kind, text, sort) template token; sort is None for a literal.
    Token = tuple[str, str, Pattern | None]


def _tokens(pattern: StringPattern) -> list[Token]:
    """Decompose a template into ordered ``(kind, text, sort)`` tokens.

    ``kind`` is ``"lit"`` (``text`` the literal, ``sort`` None) or ``"var"``
    (``text`` the variable label, ``sort`` its sub-pattern). A template's
    ``variable_locations`` and ``non_variable_locations`` partition it exactly,
    so one left-to-right scan reconstructs the token sequence.
    """
    tokens: list[Token] = []
    template = pattern.pattern
    i = 0
    while i < len(template):
        if i in pattern.variable_locations:
            location = pattern.variable_locations[i]
            tokens.append(("var", location["label"], location["pattern"]))
            i += len(location["label"])
        elif i in pattern.non_variable_locations:
            literal = pattern.non_variable_locations[i]
            tokens.append(("lit", literal, None))
            i += len(literal)
        else:
            # The two location maps are built to tile the template with no gaps;
            # a gap means the pattern was constructed inconsistently.
            raise ValueError(f"Gap in template decomposition of {template!r} at {i}.")
    return tokens


def iter_bindings(
    pattern: StringPattern, s: str, context: Context, binding: Binding | None = None
) -> Iterator[Binding]:
    """Yield every assignment under which ``pattern`` instantiates to ``s``.

    An incoming ``binding`` is respected — already-bound variables must consume
    their value — which is how several patterns are matched under one shared
    substitution (see :func:`iter_joint`).
    """
    tokens = _tokens(pattern)
    subject = pattern.pre_format_apply(s)
    start: Binding = {} if binding is None else dict(binding)

    def admits(sort: Pattern | None, value: str) -> bool:
        # An empty value is always an admissible gap; a non-empty one must be of
        # the variable's sort. `.match` returns None when the sort rejects it.
        # (The sort's own regex is anchored, so this is a whole-string test.)
        return value == "" or sort is None or sort.match(value, context) is not None

    def rec(ti: int, si: int, current: Binding) -> Iterator[Binding]:
        if ti == len(tokens):
            if si == len(subject):
                yield dict(current)
            return

        kind, text, sort = tokens[ti]

        if kind == "lit":
            if subject.startswith(text, si):
                yield from rec(ti + 1, si + len(text), current)
            return

        # A variable. If it is already bound, it must consume exactly its value.
        if text in current:
            value = current[text]
            if subject.startswith(value, si):
                yield from rec(ti + 1, si + len(value), current)
            return

        # A free variable: try every split point, including the empty binding.
        for end in range(si, len(subject) + 1):
            value = subject[si:end]
            if not admits(sort, value):
                continue
            current[text] = value
            yield from rec(ti + 1, end, current)
            del current[text]

    yield from rec(0, 0, start)


def iter_joint(
    pairs: list[tuple[StringPattern, str]], context: Context, binding: Binding | None = None
) -> Iterator[Binding]:
    """Yield every binding consistent across all ``(pattern, string)`` pairs.

    Threads one substitution through the pairs, so a variable shared between two
    antecedents (or an antecedent and the deduction) is forced to a single value.
    """
    start: Binding = {} if binding is None else dict(binding)
    if not pairs:
        yield start
        return

    (pattern, s), rest = pairs[0], pairs[1:]
    for extended in iter_bindings(pattern, s, context, start):
        yield from iter_joint(rest, context, extended)


def joint_binding_exists(
    pairs: list[tuple[StringPattern, str]], context: Context, binding: Binding | None = None
) -> bool:
    """Whether one substitution satisfies every ``(pattern, string)`` pair.

    This is the string-rewriting counterpart of the term unifier's
    ``match_all`` — the existence of a consistent binding is exactly what makes a
    rewriting step valid.
    """
    for _ in iter_joint(pairs, context, binding):
        return True
    return False
