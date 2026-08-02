"""Storing and loading a system's named notations.

A :class:`~website.logical.rendering.Projection` is the engine's view — a map from
constructor name to render steps. This is the same thing as rows, so a notation
persists with its system and every reader of every proof written against that
system can ask for it.

The direction of travel matters. A notation is *derived* — from a `.mm` file's
``$t`` block, or from an author's overrides — and then stored, because deriving it
needs the source the system was built from and a reader has only the database.
Nothing here re-derives.

Reading is **layered**, as the system is. A system inheriting from another is
built from its ancestors' parts in front of its own, so their constructors are its
constructors and their spellings are readings of it; a child's own rows win per
constructor. Storing is not layered — a notation is stored against the one system
it was derived for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.db.models import FormalSystem
from app.db.systems import NotationPieceRow
from website.logical.rendering import Projection

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from app.db.terms_mapping import TermGraph
    from website.logical.kernel.constructors import Piece


def store_notation(
    session: Session,
    system_id: uuid.UUID,
    projection: Projection,
) -> int:
    """Replace ``system_id``'s notation named by ``projection``, returning its size.

    Synchronous, because the one thing that derives a notation is an import, and
    an import is synchronous - deriving needs the source a system was built from,
    which a reader does not have. Reading is async, beside the API that does it.

    Replaces rather than merges: a notation is derived wholesale from a source that
    knows the whole grammar, so a re-derivation that dropped a constructor should
    drop its rows too. Merging would leave the old spelling behind and make the
    stored notation a history of every derivation rather than the current one.
    """
    session.execute(
        delete(NotationPieceRow).where(
            NotationPieceRow.formal_system_id == system_id,
            NotationPieceRow.notation == projection.name,
        )
    )
    rows = [
        NotationPieceRow(
            formal_system_id=system_id,
            notation=projection.name,
            constructor=constructor,
            position=position,
            kind=kind,
            text=text,
        )
        for constructor, pieces in projection.templates.items()
        for position, (kind, text) in enumerate(pieces)
    ]
    session.add_all(rows)
    return len(projection.templates)


# The same bound `systems.MAX_INHERITANCE_DEPTH` applies on the spine, restated
# here rather than imported: this module is the persistence layer and must not
# depend on a router (as `system_relations_mapping` already records). A cycle is
# refused when the edge is stored, so the `seen` set below is a backstop against
# data that predates that check.
_MAX_DEPTH = 32


async def notation_layers(
    session: AsyncSession, system_id: uuid.UUID
) -> list[uuid.UUID]:
    """``system_id`` and its ancestors, **root first**.

    A notation belongs to a grammar, and a system inheriting from another is built
    from its ancestors' parts concatenated in front of its own (``layered_spec``),
    so the ancestors' constructors are this system's constructors and their
    spellings are readings of it. Without this, building on an imported corpus
    would silently cost you the corpus's own notation — which, since a corpus is
    where a `$t` block comes from, is every notation there is.

    Ids only. The chain is walked here rather than through
    ``systems.load_chain`` because that eagerly loads whole systems, and a
    corpus-sized one is seconds — far more than a *reading* should cost.
    """
    layers = [system_id]
    seen = {system_id}
    current = system_id
    while len(layers) < _MAX_DEPTH:
        parent = await session.scalar(
            select(FormalSystem.inherits_from_id).where(FormalSystem.id == current)
        )
        if parent is None or parent in seen:
            break
        seen.add(parent)
        layers.insert(0, parent)
        current = parent
    return layers


async def notation_names(session: AsyncSession, system_id: uuid.UUID) -> list[str]:
    """Every notation this system can be read in, in name order.

    Its own and its ancestors' (:func:`notation_layers`). The source spelling is
    not among them: it is the grammar, not a notation, and is what a reader gets
    by asking for none.
    """
    found = await session.scalars(
        select(NotationPieceRow.notation)
        .where(
            NotationPieceRow.formal_system_id.in_(
                await notation_layers(session, system_id)
            )
        )
        .distinct()
        .order_by(NotationPieceRow.notation)
    )
    return list(found)


async def load_notation(
    session: AsyncSession, system_id: uuid.UUID, notation: str
) -> Projection | None:
    """The notation of that name for ``system_id``, or None if there is none.

    Layered like the system itself: the ancestors' rows first, then this system's
    over the top, so a child re-spelling a constructor wins and everything it did
    not mention keeps the parent's reading. That is what makes a notation useful
    on a child of an imported corpus — the child adds a handful of productions and
    inherits the spellings of the thousands it did not write.

    None rather than an empty projection, so a caller can tell "no layer has such
    a notation" from "this notation re-spells nothing" — the first is worth
    reporting to whoever asked for it, the second renders as the source and is
    unremarkable.
    """
    layers = await notation_layers(session, system_id)
    rows = (
        await session.scalars(
            select(NotationPieceRow)
            .where(
                NotationPieceRow.formal_system_id.in_(layers),
                NotationPieceRow.notation == notation,
            )
            .order_by(NotationPieceRow.constructor, NotationPieceRow.position)
        )
    ).all()
    if not rows:
        return None

    depth = {layer: index for index, layer in enumerate(layers)}
    templates: dict[str, list[Piece]] = {}
    winner: dict[str, int] = {}
    for row in rows:
        at = depth[row.formal_system_id]
        if winner.get(row.constructor, -1) > at:
            continue
        if winner.get(row.constructor, -1) < at:
            # A nearer layer re-spells this constructor, so the ancestor's steps
            # are replaced rather than appended to.
            winner[row.constructor] = at
            templates[row.constructor] = []
        templates[row.constructor].append((row.kind, row.text))
    return Projection(
        templates={name: tuple(pieces) for name, pieces in templates.items()},
        name=notation,
    )


def render_stored(
    graph: TermGraph, term_id: uuid.UUID | None, projection: Projection
) -> str | None:
    """Render a stored term through a stored notation, from rows alone.

    The storage-side twin of :func:`website.logical.rendering.render`, and the
    same fold — but over the row graph rather than over rebuilt
    :class:`~website.logical.kernel.terms.Term`s, because a display should not
    cost a system rebuild. Rebuilding is what a *check* is for, and it is seconds
    on a corpus-sized grammar.

    That is why a stored notation is completed to name every constructor
    (:func:`~website.logical.rendering.total_projection`): with no grammar to hand,
    a constructor the notation does not name has nothing to fall back to. A name
    still missing renders as its literal or as nothing, which is a gap in the
    notation rather than a reason to fail a page.

    ``tests/test_notations_store.py`` pins this against the engine's own fold on a
    real system, which is what keeps the two from drifting apart.
    """
    if term_id is None:
        return None
    return _render_row(graph, term_id, projection.templates, set())


def _render_row(
    graph: TermGraph,
    term_id: uuid.UUID,
    templates: Mapping[str, tuple[Piece, ...]],
    seen: set[uuid.UUID],
) -> str:
    row = graph.node(term_id)
    if row is None or term_id in seen:
        # A term graph is a DAG, so a repeat is sharing rather than a cycle - but
        # rendering shared structure twice is right, and only a *cycle* would not
        # terminate. Guard the path, not the visit.
        return ""
    children = dict(graph.children_of(term_id))
    pieces = templates.get(row.constructor or "")
    if pieces is None:
        if row.literal is not None:
            return row.literal
        if row.var_name is not None:
            return row.var_name
        if row.bound_index is not None:
            # `Bound.to_string`'s placeholder, spelled again because there is no
            # kernel term here to ask. Debugging only either way: an unfold
            # instantiates every bound variable before anyone reads the result.
            return f"⟨{row.bound_index}⟩"
        if len(children) == 1:
            return _render_row(graph, next(iter(children.values())), templates, seen | {term_id})
        return ""
    out: list[str] = []
    for kind, text in pieces:
        if kind == "lit":
            out.append(text)
            continue
        child = children.get(text)
        out.append(
            _render_row(graph, child, templates, seen | {term_id})
            if child is not None
            else text
        )
    return "".join(out)
