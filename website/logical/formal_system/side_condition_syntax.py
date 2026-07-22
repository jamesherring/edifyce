"""Source syntax for rule side-conditions - the kernel's SideCondition algebra.

A rule's ``side_conditions:`` block lists one proviso per line, drawn from a
closed, total vocabulary that maps directly onto
:mod:`website.logical.kernel.side_conditions`. The block is the *conjunction* of
its lines; within a line, ``or`` forms a *disjunction* and a leading ``not``
negates a single predicate (``not`` binds tighter than ``or``)::

    side_conditions:
        not occurs(x, phi)              # x does not occur in phi   (freshness)
        disjoint(x, phi, setvar)        # x shares no setvar leaf with phi   ($d)
        atom(x, setvar)                 # x stands for a variable, not a compound
        equal(p, q)                     # p and q are the same formula
        atom(x) or equal(x, y)          # x is atomic, or it equals y

So the grammar is two levels of boolean structure: ``and`` across lines (or a
definition's ``;``-separated ``where`` clauses), ``or`` across the ``or``-
separated predicates within one line. There is no parenthesised grouping, so a
line is a flat disjunction of (optionally negated) predicates — enough for the
provisos real systems use without giving the trusted kernel an arbitrary
boolean-expression parser.

This is deliberately *not* the old condition mini-language: there are no
arbitrary path expressions, proof-state lookups, or user-defined functions -
only the fixed predicates the trusted kernel can check structurally over a
rule's term binding. Conditions that need those capabilities live outside the
kernel and are intentionally not expressible here.

The predicates and their arities::

    occurs(needle, haystack)          -> Occurs
    equal(left, right)                -> Equal
    disjoint(left, right [, sort])    -> DisjointLeaves
    atom(name [, sort])               -> IsAtom

Names are the rule's metavariables; a ``sort`` argument is a pattern name
resolved in the compile context. A line may combine predicates with ``or`` (each
optionally ``not``-negated); ``and`` is the level above (across lines / ``;``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..kernel import DisjointLeaves, Equal, IsAtom, Not, Occurs, Or, SideCondition
from ..matching.patterns import Pattern

if TYPE_CHECKING:
    from ..matching.context import Context


def parse_side_condition(text: str, context: Context) -> SideCondition:
    """Parse one side-condition line into a :class:`SideCondition`.

    A line is a disjunction: predicates joined by top-level ``or`` (each
    optionally ``not``-negated). A single predicate parses to itself; two or more
    to an :class:`~website.logical.kernel.side_conditions.Or`. Raises
    :class:`ValueError` on anything outside the closed grammar - an unknown
    predicate, the wrong argument count, or a sort name that is not a pattern - so
    a malformed proviso is rejected at compile time rather than silently ignored.
    """
    disjuncts = [_parse_disjunct(part, context) for part in _split_or(text)]
    return disjuncts[0] if len(disjuncts) == 1 else Or(tuple(disjuncts))


def _split_or(text: str) -> list[str]:
    """Split ``text`` on top-level ``or`` (paren depth 0).

    An ``or`` inside a predicate's argument list is left untouched, so only the
    disjunction *between* predicates is split. The disjuncts are stripped by the
    caller (``_parse_disjunct``).
    """
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith(" or ", i):
            parts.append(text[start:i])
            i += 4
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


def _parse_disjunct(text: str, context: Context) -> SideCondition:
    """Parse one ``or``-separated predicate, with an optional leading ``not``."""
    text = text.strip()

    negated = text.startswith("not ")
    if negated:
        text = text[4:].strip()

    open_paren = text.find("(")
    if open_paren == -1 or not text.endswith(")"):
        raise ValueError(f"Malformed side-condition: '{text}'.")

    name = text[:open_paren].strip()
    inner = text[open_paren + 1 : -1].strip()
    args = [arg.strip() for arg in inner.split(",")] if inner else []
    if any(not arg for arg in args):
        raise ValueError(f"Malformed side-condition arguments: '{text}'.")

    condition = _build(name, args, text, context)
    return Not(condition) if negated else condition


def _build(name: str, args: list[str], text: str, context: Context) -> SideCondition:
    if name == "occurs" and len(args) == 2:
        return Occurs(args[0], args[1])
    if name == "equal" and len(args) == 2:
        return Equal(args[0], args[1])
    if name == "disjoint" and len(args) in (2, 3):
        sort = _sort(args[2], context) if len(args) == 3 else None
        return DisjointLeaves(args[0], args[1], sort)
    if name == "atom" and len(args) in (1, 2):
        sort = _sort(args[1], context) if len(args) == 2 else None
        return IsAtom(args[0], sort)
    raise ValueError(f"Unknown or misapplied side-condition: '{text}'.")


def _sort(sort_name: str, context: Context) -> Pattern:
    pattern = context.variables.get(sort_name)
    if not isinstance(pattern, Pattern):
        raise ValueError(f"Side-condition sort '{sort_name}' is not a pattern.")
    return pattern
