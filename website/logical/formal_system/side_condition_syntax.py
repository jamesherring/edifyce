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
    member(name, sort)                -> IsMember

An argument (``needle``/``haystack``/``left``/``right``/``name``) is either a
declared metavariable of the owner — resolved against the match binding — or a
literal term expression parsed against the grammar (productions and resolved
definitions; it may embed the owner's metavariables, substituted at check time).
A ``sort`` argument is a pattern name resolved in the compile context. A line may
combine predicates with ``or`` (each optionally ``not``-negated); ``and`` is the
level above (across lines / ``;``).
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from ..kernel import (
    And,
    DisjointLeaves,
    Equal,
    IsAtom,
    IsMember,
    Not,
    Occurs,
    Or,
    SideCondition,
    abstract,
    from_match,
)
from ..kernel.constructors import constructor_for, project_sorts
from ..matching.definitions import DefinedNotation
from ..matching.patterns import Pattern, UnionPattern

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..matching.context import Context
    from ..kernel import Term
    from ..kernel.constructors import Constructor


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


_OPENERS = "([{⟨"
_CLOSERS = ")]}⟩"


def _split_args(inner: str) -> list[str]:
    """Split a predicate's argument list on top-level commas.

    A comma inside brackets belongs to a compound term argument (e.g.
    ``equal(p, f(a, b))``), so only depth-0 commas separate arguments. Mirrored in
    ``app.db.side_conditions_mapping`` so the storage parser splits identically.
    """
    if not inner:
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    for i, char in enumerate(inner):
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
    parts.append(inner[start:])
    return [part.strip() for part in parts]


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
    args = _split_args(inner)
    if any(not arg for arg in args):
        raise ValueError(f"Malformed side-condition arguments: '{text}'.")

    condition = _build(name, args, text, context)
    return Not(condition) if negated else condition


def _build(name: str, args: list[str], text: str, context: Context) -> SideCondition:
    if name == "occurs" and len(args) == 2:
        return Occurs(_arg(args[0], context), _arg(args[1], context))
    if name == "equal" and len(args) == 2:
        return Equal(_arg(args[0], context), _arg(args[1], context))
    if name == "disjoint" and len(args) in (2, 3):
        sort = _sort(args[2], context) if len(args) == 3 else None
        return DisjointLeaves(_arg(args[0], context), _arg(args[1], context), sort)
    if name == "atom" and len(args) in (1, 2):
        sort = _sort(args[1], context) if len(args) == 2 else None
        return IsAtom(_arg(args[0], context), sort)
    if name == "member" and len(args) == 2:
        # The sort is required: `member(x, R)` asks "is x of sort R", so R must be
        # named (unlike `atom`, where the sort is an optional extra guard).
        return IsMember(_arg(args[0], context), _sort(args[1], context))
    raise ValueError(f"Unknown or misapplied side-condition: '{text}'.")


def _sort(sort_name: str, context: Context) -> Constructor:
    pattern = context.variables.get(sort_name)
    if not isinstance(pattern, Pattern):
        raise ValueError(f"Side-condition sort '{sort_name}' is not a pattern.")
    # A proviso's sort is kernel data; the name is resolved through the grammar
    # here and projected, so nothing downstream carries the production.
    return constructor_for(pattern)


def _arg(text: str, context: Context) -> str | Term:
    """Resolve a predicate argument to a metavariable name or a literal term.

    A declared metavariable of the rule/definition (``context.string_variables``)
    stays a bare name, resolved against the match binding at check time — every
    existing proviso takes this path unchanged. Anything else is parsed as a term
    expression against the grammar (and may use defined notation), keeping the
    owner's metavariables schematic as ``Var`` nodes so they substitute later.
    """
    if text in context.string_variables:
        return text
    term = _parse_term(text, context)
    if term is None:
        raise ValueError(
            f"Side-condition argument '{text}' is neither a declared metavariable "
            "nor a parseable term."
        )
    return term


def _parse_term(text: str, context: Context) -> Term | None:
    """Parse ``text`` as a term against the grammar's sorts (unions).

    Tries each sort in declaration order and takes the first that matches, then
    lifts any leaf that is a declared metavariable to a ``Var`` (via ``abstract``)
    so it stays schematic. Returns ``None`` when nothing parses.

    Defined notation is allowed: the parse may use any notation already
    registered. Mid-build ``context.definitions`` can also hold the *spec* records
    a system is being assembled from, which are not notations and cannot parse
    anything, so they are dropped first. Rule and definition provisos are parsed
    once definitions have resolved (step 9 of ``build_system``), so a proviso
    there sees the real ones.
    """
    parse_context = copy(context)
    parse_context.definitions = [
        d for d in context.definitions if isinstance(d, DefinedNotation)
    ]
    for candidate in context.variables.values():
        if not isinstance(candidate, UnionPattern):
            continue
        matched = candidate.match(text, parse_context)
        if matched is not None:
            return abstract(from_match(matched), project_sorts(context.string_variables))
    return None


def render_side_condition(condition: SideCondition, sorts: Mapping[Constructor, str]) -> str:
    """Write a :class:`SideCondition` back as one line of the surface syntax.

    The inverse of :func:`parse_side_condition`, and it exists for one caller: a
    schematic promotion restates the provisos its steps relied on over the
    theorem's own metavariables (`promotion.schematic_theorem`), and a
    ``TheoremSpec`` carries provisos as the lines an import would have written.
    Rendering here rather than building rows directly keeps one path into
    storage — the entry a promotion writes and the entry a Metamath ``$d`` writes
    are the same rows, parsed by the same parser.

    ``sorts`` names a constructor, for the predicates that carry one; a
    constructor absent from it renders its own name, which is the production's
    and so is what the grammar spells anyway.

    A term argument renders through the term (``Var`` to its name, a compound to
    its surface form), so the round trip back through ``_arg`` reads a bare
    metavariable as a name and anything else as a term expression — the same
    split it made on the way in.

    Exhaustive over the algebra, raising on an unknown member for the reason
    :func:`~website.logical.kernel.side_conditions.restate` does: a condition
    that fell through silently would be a proviso dropped, and dropping one reads
    as "this theorem has no proviso".
    """
    if isinstance(condition, Not):
        return f"not {render_side_condition(condition.inner, sorts)}"
    if isinstance(condition, Or):
        return " or ".join(render_side_condition(p, sorts) for p in condition.parts)
    if isinstance(condition, And):
        # `and` is the line separator rather than an infix, so a nested one has no
        # single-line spelling. It only arises from a restated proviso block, and
        # the caller splits those into lines before reaching here.
        raise ValueError("An `and` of side-conditions has no single-line rendering.")
    if isinstance(condition, Occurs):
        return f"occurs({_argument(condition.needle)}, {_argument(condition.haystack)})"
    if isinstance(condition, Equal):
        return f"equal({_argument(condition.left)}, {_argument(condition.right)})"
    if isinstance(condition, DisjointLeaves):
        args = [_argument(condition.left), _argument(condition.right)]
        if condition.sort is not None:
            args.append(_sort_name(condition.sort, sorts))
        return f"disjoint({', '.join(args)})"
    if isinstance(condition, IsAtom):
        args = [_argument(condition.name)]
        if condition.sort is not None:
            args.append(_sort_name(condition.sort, sorts))
        return f"atom({', '.join(args)})"
    if isinstance(condition, IsMember):
        return f"member({_argument(condition.name)}, {_sort_name(condition.sort, sorts)})"
    raise ValueError(
        f"Cannot render a side-condition of type {type(condition).__name__}."
    )


def conjuncts(condition: SideCondition) -> list[SideCondition]:
    """Flatten an ``and`` into the lines it was written as.

    A proviso *block* is a conjunction of lines, so an `And` is the block and its
    parts are the lines — which is the shape `TheoremSpec.distinct` wants, and
    the one :func:`render_side_condition` can spell.
    """
    if isinstance(condition, And):
        return [part for inner in condition.parts for part in conjuncts(inner)]
    return [condition]


def _argument(arg: str | Term) -> str:
    return arg if isinstance(arg, str) else arg.to_string()


def _sort_name(sort: Constructor, sorts: Mapping[Constructor, str]) -> str:
    return sorts.get(sort, sort.name)
