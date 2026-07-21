"""Bridge between a definition's proviso string and the side-condition rows.

``build_side_condition_rows`` parses the declarative ``where`` proviso
(``"not occurs(x, phi) ; disjoint(x, y, setvar)"``) into a
:class:`~app.db.side_conditions.SideConditionRow` tree attached to a definition;
``side_condition_to_string`` renders that tree back to the same surface string,
so ``systems_mapping``'s spec round trip is unchanged behind structured storage.

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
from app.db.systems import DefinitionRow, SymbolRow

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
        _materialise(tree, definition, symbols, parent=None, position=0)


def _materialise(
    node: _Leaf | _Combinator,
    definition: DefinitionRow,
    symbols: dict[str, SymbolRow],
    parent: SideConditionRow | None,
    position: int,
) -> SideConditionRow:
    row = SideConditionRow(
        definition=definition, parent=parent, position=position, kind=node.kind
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
            _materialise(child, definition, symbols, parent=row, position=i)
    return row


def definition_condition_string(definition: DefinitionRow) -> str | None:
    """Render a definition's proviso tree back to its ``where`` surface string.

    Reads the flat ``definition.side_conditions`` collection and rebuilds the tree
    in Python (grouping by ``parent_id``) rather than walking the self-referential
    ``children`` relationship — so only that one collection needs eager loading on
    the async read path.
    """
    nodes = list(definition.side_conditions)
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
        raise ValueError("Definition has side-condition rows but no root.")
    return _render(root, children)


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
