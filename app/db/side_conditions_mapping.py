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
    SIDE_KIND_NOT,
    SIDE_KIND_OCCURS,
    SIDE_KIND_OR,
    SideConditionRow,
)
from app.db.systems import DefinitionRow, RuleRow, SymbolRow

# Leaf predicate -> (kind, allowed arg counts, arg-index of the sort or None).
_PREDICATES = {
    "occurs": (SIDE_KIND_OCCURS, (2,), None),
    "equal": (SIDE_KIND_EQUAL, (2,), None),
    "disjoint": (SIDE_KIND_DISJOINT, (2, 3), 2),
    "atom": (SIDE_KIND_ATOM, (1, 2), 1),
}


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
    args = [arg.strip() for arg in inner.split(",")] if inner else []
    if any(not arg for arg in args):
        raise ValueError(f"Malformed side-condition arguments: {text!r}.")

    spec = _PREDICATES.get(name)
    if spec is None or len(args) not in spec[1]:
        raise ValueError(f"Unknown or misapplied side-condition: {text!r}.")
    kind, _, sort_index = spec
    sort = args[sort_index] if sort_index is not None and len(args) > sort_index else None
    right = args[1] if len(args) >= 2 and kind != SIDE_KIND_ATOM else None
    leaf = _Leaf(kind=kind, left=args[0], right=right, sort=sort)
    return _Combinator(SIDE_KIND_NOT, (leaf,)) if negated else leaf


def _parse(condition: str) -> _Leaf | _Combinator | None:
    condition = condition.strip()
    if not condition:
        return None
    conjuncts = [_parse_leaf(part.strip()) for part in condition.split(";") if part.strip()]
    if not conjuncts:
        return None
    if len(conjuncts) == 1:
        return conjuncts[0]
    return _Combinator(SIDE_KIND_AND, tuple(conjuncts))


def _parse_lines(lines: list[str]) -> _Leaf | _Combinator | None:
    """Parse a rule's proviso lines into one tree (implicit conjunction).

    A rule stores its provisos as a list of already-split lines (one kernel
    predicate each), whereas a definition's ``where`` is a single ``;``-joined
    string — so rules skip the split ``_parse`` does. Two or more lines combine
    into an ``and``, matching how the engine treats the ``side_conditions:`` block.
    """
    conjuncts = [_parse_leaf(line.strip()) for line in lines if line.strip()]
    if not conjuncts:
        return None
    if len(conjuncts) == 1:
        return conjuncts[0]
    return _Combinator(SIDE_KIND_AND, tuple(conjuncts))


def build_side_condition_rows(
    definition: DefinitionRow,
    condition: str | None,
    symbols: dict[str, SymbolRow],
) -> None:
    """Parse ``condition`` and attach its proviso tree to ``definition`` (unsaved).

    A sort argument is resolved to a symbol in ``symbols``; an unknown sort name
    is a malformed proviso (it could not have compiled) and raises.
    """
    if condition is None:
        return
    tree = _parse(condition)
    if tree is not None:
        _materialise(tree, symbols, parent=None, position=0, definition=definition)


def build_rule_side_conditions(
    rule: RuleRow,
    provisos: list[str],
    symbols: dict[str, SymbolRow],
) -> None:
    """Parse a rule's proviso ``lines`` and attach the tree to ``rule`` (unsaved).

    Mirrors :func:`build_side_condition_rows` for the rule owner; an empty list
    (axioms, unconditioned rules) attaches nothing.
    """
    tree = _parse_lines(provisos)
    if tree is not None:
        _materialise(tree, symbols, parent=None, position=0, rule=rule)


def _materialise(
    node: _Leaf | _Combinator,
    symbols: dict[str, SymbolRow],
    parent: SideConditionRow | None,
    position: int,
    definition: DefinitionRow | None = None,
    rule: RuleRow | None = None,
) -> SideConditionRow:
    # The owner (definition or rule) is carried on *every* node — root and
    # children alike — so a leaf predicate joins back to its owner without walking
    # the tree; the CHECK requires exactly one owner set on each row.
    row = SideConditionRow(
        definition=definition, rule=rule, parent=parent, position=position, kind=node.kind
    )
    if isinstance(node, _Leaf):
        row.left_name = node.left
        row.right_name = node.right
        if node.sort is not None:
            if node.sort not in symbols:
                raise ValueError(
                    f"Side-condition sort {node.sort!r} is not a symbol of the system."
                )
            row.sort_symbol = symbols[node.sort]
    else:
        for i, child in enumerate(node.children):
            _materialise(child, symbols, parent=row, position=i, definition=definition, rule=rule)
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
    tree = _owner_tree(list(rule.side_conditions))
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
    kids = children.get(row.id, [])
    if row.kind == SIDE_KIND_NOT:
        return f"not {_render(kids[0], children)}"
    if row.kind == SIDE_KIND_AND:
        return " ; ".join(_render(child, children) for child in kids)
    if row.kind == SIDE_KIND_OR:
        # The kernel has Or, but there is no `where` surface syntax for it yet;
        # nothing produces it, so hitting this is a bug, not a user error.
        raise ValueError("`or` side-conditions have no surface syntax to render to.")
    raise ValueError(f"Unknown side-condition kind: {row.kind!r}.")
