"""Bridge between a proviso's surface form and the side-condition rows.

``build_side_condition_rows`` parses a definition's declarative ``where`` proviso
(``"not occurs(x, phi) ; disjoint(x, y, setvar)"``) into a
:class:`~app.db.side_conditions.SideConditionRow` tree attached to that
definition; ``build_rule_side_conditions`` does the same for a rule's
``side_conditions`` block (a list of one-predicate lines). ``*_string`` /
``*_list`` render the stored tree back to the same surface form, so
``systems_mapping``'s spec round trip is unchanged behind structured storage.

The grammar mirrors the engine's
:mod:`website.logical.formal_system.side_condition_syntax` (a closed vocabulary:
``occurs`` / ``equal`` / ``disjoint`` / ``atom``, optional leading ``not``, lines
joined by ``;`` as an implicit conjunction). It is re-implemented here — rather
than imported — because that parser resolves a sort argument to a live
``Pattern`` via a compiled context, whereas storage resolves it to a
``SymbolRow`` and needs no engine. A test cross-checks that the two accept the
same strings so they cannot drift.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db.side_conditions import (
    SIDE_KIND_AND,
    SIDE_KIND_ATOM,
    SIDE_KIND_DISJOINT,
    SIDE_KIND_EQUAL,
    SIDE_KIND_MEMBER,
    SIDE_KIND_NOT,
    SIDE_KIND_OCCURS,
    SIDE_KIND_OR,
    SideConditionRow,
)
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.systems import DefinitionRow, RuleRow, SymbolRow

# Leaf predicate -> (kind, allowed arg counts, arg-index of the sort or None).
_PREDICATES = {
    "occurs": (SIDE_KIND_OCCURS, (2,), None),
    "equal": (SIDE_KIND_EQUAL, (2,), None),
    "disjoint": (SIDE_KIND_DISJOINT, (2, 3), 2),
    "atom": (SIDE_KIND_ATOM, (1, 2), 1),
    "member": (SIDE_KIND_MEMBER, (2,), 1),
}

# Predicates whose *second* argument is a sort, not a right-hand metavariable.
_SORT_AT_ARG_1 = (SIDE_KIND_ATOM, SIDE_KIND_MEMBER)


@dataclass(frozen=True)
class _Leaf:
    kind: str
    left: str
    right: str | None
    sort: str | None  # a sort *name*, resolved to a SymbolRow at build time


@dataclass(frozen=True)
class _Combinator:
    kind: str
    children: tuple[_Leaf | _Combinator, ...]


def _parse_leaf(text: str) -> _Leaf | _Combinator:
    negated = text.startswith("not ")
    if negated:
        text = text[4:].strip()

    open_paren = text.find("(")
    if open_paren == -1 or not text.endswith(")"):
        raise ValueError(f"Malformed side-condition: {text!r}.")
    name = text[:open_paren].strip()
    inner = text[open_paren + 1 : -1].strip()
    args = _split_args(inner)
    if any(not arg for arg in args):
        raise ValueError(f"Malformed side-condition arguments: {text!r}.")

    spec = _PREDICATES.get(name)
    if spec is None or len(args) not in spec[1]:
        raise ValueError(f"Unknown or misapplied side-condition: {text!r}.")
    kind, _, sort_index = spec
    sort = args[sort_index] if sort_index is not None and len(args) > sort_index else None
    right = args[1] if len(args) >= 2 and kind not in _SORT_AT_ARG_1 else None
    leaf = _Leaf(kind=kind, left=args[0], right=right, sort=sort)
    return _Combinator(SIDE_KIND_NOT, (leaf,)) if negated else leaf


_OPENERS = "([{⟨"
_CLOSERS = ")]}⟩"


def _split_args(inner: str) -> list[str]:
    """Split a predicate's argument list on top-level (bracket-depth-0) commas.

    Mirrors ``side_condition_syntax._split_args`` so a compound term argument such
    as ``f(a, b)`` is one argument in both parsers, not split on its inner comma.
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

    Mirrors ``side_condition_syntax._split_or`` so the two parsers accept the same
    disjunctions; an ``or`` inside a predicate's args is left untouched.
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


def _parse_disjunction(text: str) -> _Leaf | _Combinator:
    """Parse one segment/line into a disjunction of (optionally negated) leaves."""
    disjuncts = [_parse_leaf(part.strip()) for part in _split_or(text)]
    if len(disjuncts) == 1:
        return disjuncts[0]
    return _Combinator(SIDE_KIND_OR, tuple(disjuncts))


def _parse(condition: str) -> _Leaf | _Combinator | None:
    condition = condition.strip()
    if not condition:
        return None
    conjuncts = [_parse_disjunction(part.strip()) for part in condition.split(";") if part.strip()]
    if not conjuncts:
        return None
    if len(conjuncts) == 1:
        return conjuncts[0]
    return _Combinator(SIDE_KIND_AND, tuple(conjuncts))


def _parse_lines(lines: list[str]) -> _Leaf | _Combinator | None:
    """Parse a rule's proviso lines into one tree (implicit conjunction).

    A rule stores its provisos as a list of already-split lines (one disjunction
    each), whereas a definition's ``where`` is a single ``;``-joined string — so
    rules skip the ``;`` split ``_parse`` does. Two or more lines combine into an
    ``and``, matching how the engine treats the ``side_conditions:`` block; a line
    may itself be an ``or`` disjunction.

    A blank line is a malformed proviso, not a no-op: it is rejected (an empty
    ``lines`` list, meaning "no proviso at all", is the only empty case allowed).
    """
    conjuncts = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            raise ValueError("Empty side-condition line.")
        conjuncts.append(_parse_disjunction(stripped))
    if not conjuncts:
        return None
    if len(conjuncts) == 1:
        return conjuncts[0]
    return _Combinator(SIDE_KIND_AND, tuple(conjuncts))


def build_side_condition_rows(
    definition: DefinitionRow,
    condition: str | None,
    symbols: dict[str, SymbolRow],
    metavars: set[str],
) -> None:
    """Parse ``condition`` and attach its proviso tree to ``definition`` (unsaved).

    A sort argument is resolved to a symbol in ``symbols``; an unknown sort name
    is a malformed proviso (it could not have compiled) and raises. A predicate's
    metavariable arguments must be among ``metavars`` (the owner's declared
    binding names) — a proviso over an undeclared name has no binding to check
    against and would raise deep in the kernel, so it is rejected here.
    """
    if condition is None:
        return
    tree = _parse(condition)
    if tree is not None:
        _materialise(tree, symbols, metavars, parent=None, position=0, definition=definition)


def build_rule_side_conditions(
    rule: RuleRow,
    provisos: list[str],
    symbols: dict[str, SymbolRow],
    metavars: set[str],
) -> None:
    """Parse a rule's proviso ``lines`` and attach the tree to ``rule`` (unsaved).

    Mirrors :func:`build_side_condition_rows` for the rule owner; an empty list
    (axioms, unconditioned rules) attaches nothing. ``metavars`` are the rule's
    declared binding names; a predicate over any other name is rejected.
    """
    tree = _parse_lines(provisos)
    if tree is not None:
        _materialise(tree, symbols, metavars, parent=None, position=0, rule=rule)


def build_theorem_side_conditions(
    theorem: PromotedTheoremRow,
    provisos: list[str],
    symbols: dict[str, SymbolRow],
    metavars: set[str],
) -> None:
    """Parse a promoted theorem's provisos and attach the tree to it (unsaved).

    The library owner of :func:`build_rule_side_conditions`. An imported ``$d``
    arrives as one ``disjoint(...)`` line per constrained pair, which lowers to the
    same ``and`` root a rule's proviso block does — so a theorem's provisos are
    stored, queried and rendered exactly as a rule's are, and the storage learns
    nothing new about the library.
    """
    tree = _parse_lines(provisos)
    if tree is not None:
        _materialise(
            tree, symbols, metavars, parent=None, position=0, promoted_theorem=theorem
        )


def build_definition_provisos(
    definition: DefinitionRow,
    provisos: list[str],
    symbols: dict[str, SymbolRow],
    metavars: set[str],
) -> None:
    """Parse a definition's proviso ``lines`` and attach the tree to it (unsaved).

    The structured (list-of-lines) analogue of :func:`build_side_condition_rows`,
    which takes a single ``;``-joined ``where`` string: this gives a definition the
    same full-vocabulary, multi-line proviso surface a rule has via
    :func:`build_rule_side_conditions`. The two produce the same tree — a list of
    ``n`` lines and a ``;``-joined string of the same ``n`` clauses both lower to
    one ``and`` root — so the storage and every reader are unchanged.
    """
    tree = _parse_lines(provisos)
    if tree is not None:
        _materialise(tree, symbols, metavars, parent=None, position=0, definition=definition)


def _require_metavar(name: str | None, metavars: set[str]) -> None:
    """Raise unless ``name`` (a leaf predicate's metavariable) is declared.

    ``None`` is the combinator/absent case (e.g. ``atom``'s missing right arg) and
    is always allowed; a real name outside ``metavars`` has no binding to check
    against and would raise in the kernel, so it is rejected here.
    """
    if name is not None and name not in metavars:
        raise ValueError(
            f"Side-condition metavariable {name!r} is not a declared binding."
        )


def validate_side_condition_metavars(
    nodes: list[SideConditionRow], metavars: set[str]
) -> None:
    """Check an already-stored proviso tree against a (possibly new) binding set.

    The build helpers validate on the way in; this re-checks the flat node list of
    an *unchanged* proviso when its owner's bindings change, so dropping a binding
    a stored *metavariable* argument still names is caught here rather than in the
    kernel. Term arguments (``*_is_term``) reference the grammar, not the binding
    set, and may embed metavariables the storage layer can't introspect — those are
    left to compile-time validation. Combinators carry no names and are skipped.
    """
    for node in nodes:
        if not node.left_is_term:
            _require_metavar(node.left_name, metavars)
        if not node.right_is_term:
            _require_metavar(node.right_name, metavars)


def _materialise(
    node: _Leaf | _Combinator,
    symbols: dict[str, SymbolRow],
    metavars: set[str],
    parent: SideConditionRow | None,
    position: int,
    definition: DefinitionRow | None = None,
    rule: RuleRow | None = None,
    promoted_theorem: PromotedTheoremRow | None = None,
) -> SideConditionRow:
    # The owner (definition, rule or promoted theorem) is carried on *every* node —
    # root and children alike — so a leaf predicate joins back to its owner without
    # walking the tree; the CHECK requires exactly one owner set on each row.
    row = SideConditionRow(
        definition=definition, rule=rule, promoted_theorem=promoted_theorem,
        parent=parent, position=position, kind=node.kind,
    )
    if isinstance(node, _Leaf):
        # A leaf's left/right are argument positions (the sort argument is separate
        # and resolved below). An argument that is a declared metavariable is stored
        # as a name; anything else is a literal term expression, flagged as such and
        # validated when the system compiles (storage can't parse terms).
        row.left_name = node.left
        row.right_name = node.right
        row.left_is_term = node.left is not None and node.left not in metavars
        row.right_is_term = node.right is not None and node.right not in metavars
        if node.sort is not None:
            if node.sort not in symbols:
                raise ValueError(
                    f"Side-condition sort {node.sort!r} is not a symbol of the system."
                )
            row.sort_symbol = symbols[node.sort]
    else:
        for i, child in enumerate(node.children):
            _materialise(
                child, symbols, metavars, parent=row, position=i,
                definition=definition, rule=rule, promoted_theorem=promoted_theorem,
            )
    return row


def _owner_tree(
    nodes: list[SideConditionRow],
) -> tuple[SideConditionRow, dict[uuid.UUID, list[SideConditionRow]]] | None:
    """Rebuild the proviso tree from an owner's flat node collection.

    Groups children by ``parent_id`` (rather than walking the self-referential
    ``children`` relationship) so only the flat collection needs eager loading on
    the async read path. Returns ``(root, children_by_parent)``, or ``None`` when
    the owner has no proviso.
    """
    if not nodes:
        return None
    children: dict[uuid.UUID, list[SideConditionRow]] = {}
    root: SideConditionRow | None = None
    for node in nodes:
        if node.parent_id is None:
            root = node
        else:
            children.setdefault(node.parent_id, []).append(node)
    for group in children.values():
        group.sort(key=lambda row: row.position)
    if root is None:
        raise ValueError("Side-condition rows present but no root.")
    return root, children


def definition_condition_string(definition: DefinitionRow) -> str | None:
    """Render a definition's proviso tree back to its ``where`` surface string."""
    tree = _owner_tree(list(definition.side_conditions))
    if tree is None:
        return None
    root, children = tree
    return _render(root, children)


def rule_side_conditions_list(rule: RuleRow) -> list[str]:
    """Render a rule's proviso tree back to its ``side_conditions`` lines.

    The inverse of :func:`build_rule_side_conditions`: an ``and`` root becomes one
    line per conjunct (the block's implicit conjunction); any other root is a
    single line. Empty when the rule has no proviso.
    """
    return _proviso_lines(list(rule.side_conditions))


def theorem_side_conditions_list(theorem: PromotedTheoremRow) -> list[str]:
    """Render a promoted theorem's proviso tree back to its ``distinct`` lines."""
    return _proviso_lines(list(theorem.side_conditions))


def definition_provisos_list(definition: DefinitionRow) -> list[str]:
    """Render a definition's proviso tree back to a ``provisos`` list.

    The inverse of :func:`build_definition_provisos`, and the list-shaped analogue
    of :func:`definition_condition_string`: an ``and`` root becomes one line per
    conjunct, any other root a single line. Empty when the definition has no
    proviso. Same node collection as ``definition_condition_string`` reads, so the
    ``;``-joined string and this list stay in agreement.
    """
    return _proviso_lines(list(definition.side_conditions))


def _proviso_lines(nodes: list[SideConditionRow]) -> list[str]:
    # Shared by the rule and definition list readers: an ``and`` root is the
    # implicit conjunction of one line per child; any other root is a single line.
    tree = _owner_tree(nodes)
    if tree is None:
        return []
    root, children = tree
    if root.kind == SIDE_KIND_AND:
        return [_render(child, children) for child in children.get(root.id, [])]
    return [_render(root, children)]


def _render(row: SideConditionRow, children: dict[uuid.UUID, list[SideConditionRow]]) -> str:
    if row.kind in (SIDE_KIND_OCCURS, SIDE_KIND_EQUAL):
        return f"{row.kind}({row.left_name}, {row.right_name})"
    if row.kind == SIDE_KIND_DISJOINT:
        if row.sort_symbol is not None:
            return f"disjoint({row.left_name}, {row.right_name}, {row.sort_symbol.name})"
        return f"disjoint({row.left_name}, {row.right_name})"
    if row.kind == SIDE_KIND_ATOM:
        if row.sort_symbol is not None:
            return f"atom({row.left_name}, {row.sort_symbol.name})"
        return f"atom({row.left_name})"
    if row.kind == SIDE_KIND_MEMBER:
        # The sort is required for `member`, so it is always present.
        return f"member({row.left_name}, {row.sort_symbol.name})"
    kids = children.get(row.id, [])
    if row.kind == SIDE_KIND_NOT:
        return f"not {_render(kids[0], children)}"
    if row.kind == SIDE_KIND_AND:
        return " ; ".join(_render(child, children) for child in kids)
    if row.kind == SIDE_KIND_OR:
        # A disjunction within one line/`;`-clause; `and` stays the level above, so
        # no grouping parens are needed to round-trip unambiguously.
        return " or ".join(_render(child, children) for child in kids)
    raise ValueError(f"Unknown side-condition kind: {row.kind!r}.")
