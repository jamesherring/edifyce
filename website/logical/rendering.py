"""Rendering a term through a display projection.

A term is stored as a DAG and carries no notation of its own: a
:class:`~website.logical.kernel.constructors.Constructor` holds the *source*
template it was parsed from, and ``Node.to_string`` folds that template over the
children to rebuild the surface string. This module is the same fold with the
templates swapped, which is what lets one checked term be shown as ASCII,
Unicode, LaTeX or anything else without a second copy of it.

Why fold the term rather than substitute tokens
-----------------------------------------------
Metamath ships a per-*token* map (:mod:`~.metamath.typesetting`), and applying one
directly to a statement's tokens gives soup - ``( \\surd \\` 2 ) \\in \\mathbb{R}``.
The structure is in the tree, so folding per-*production* templates over the tree
keeps it: brackets, nesting and argument order come from the term, and only the
notation comes from the projection. A production may then render quite unlike its
source (``( sqrt \\` A )`` as ``\\sqrt{A}``), which per-token substitution can
never do.

The fold also reaches everything, which a `Match`-based renderer would not: a rule
schema, a promoted theorem's statement and a definition's two forms are all terms
with no match behind them.

Outside the kernel, deliberately
--------------------------------
The kernel hard-codes no logic and stays small; display is not its business. It
exposes what a renderer needs - ``Constructor.pieces``, the same steps
``to_string`` walks - and nothing here reaches back in.

Canonical, not verbatim
-----------------------
A term is what the parse *meant*, so rendering it normalises: redundant brackets
the author typed are gone, and sort coercions collapse. Anyone needing the
author's own keystrokes back must keep the source string; this is not that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .kernel.terms import Node, Term

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .kernel.constructors import Piece


@dataclass(frozen=True)
class Projection:
    """Display templates for a rendering, by constructor name.

    ``templates`` maps a production's name to the render steps to use in place of
    its own - the same ``("lit", text)`` / ``("slot", label)`` shape
    ``Constructor.pieces`` holds, so a projection is a *substitute template*
    rather than a different kind of thing. A constructor the projection does not
    name renders from its own template, so a partial projection is useful and an
    empty one renders exactly as the source does.

    ``name`` labels the projection for reporting ("unicode", "latex"); nothing
    dispatches on it.
    """

    templates: Mapping[str, tuple[Piece, ...]] = field(default_factory=dict)
    name: str = "source"


def render(term: Term, projection: Projection | None = None) -> str:
    """``term`` as a string, through ``projection`` where it has an opinion.

    With no projection this is ``term.to_string()`` exactly - which is a property
    worth relying on, since it means a projection can be introduced without
    changing what an unprojected caller sees.
    """
    if projection is None or not projection.templates:
        return term.to_string()
    return _render(term, projection.templates)


def _render(term: Term, templates: Mapping[str, tuple[Piece, ...]]) -> str:
    if not isinstance(term, Node):
        # A `Var` (and so a `Bound`) renders as its own name: it stands for a term
        # rather than naming a production, so a projection has nothing to say about
        # it. Substituting metavariable *spellings* is a separate question from
        # notation and is not this map's job.
        return term.to_string()

    pieces = templates.get(term.constructor.name)
    if pieces is None:
        # Mirrors `Node.to_string`. An atom carries its own text and has no
        # template; a bare regex or an abstract sort has neither, and stands for
        # its single child.
        if term.literal is not None:
            return term.literal
        pieces = term.constructor.pieces
    if not pieces:
        if len(term.children) == 1:
            return _render(next(iter(term.children.values())), templates)
        return ""

    out: list[str] = []
    for kind, text in pieces:
        if kind == "lit":
            out.append(text)
            continue
        child = term.children.get(text)
        # A slot with no child means the template names something this term does
        # not carry - a projection written against a different production. Emit
        # the label, as `to_string` does, rather than raising in a renderer.
        out.append(_render(child, templates) if child is not None else text)
    return "".join(out)
