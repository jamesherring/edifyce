"""Storing and reading the ``avoids`` declarations of a corpus.

The write side synchronous and the read side async, for the reason
:mod:`app.db.descriptions_mapping` records: the one thing that produces these is
an import, and an import is synchronous; a reader has rows.

Nothing here parses. :func:`website.logical.metamath.markup.markup_of` turns the
``$j`` blocks into directives, and these rows are what one keyword of that becomes.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select

from app.db.avoidances import LabelAvoidanceRow
from app.db.lineage import spine_ids

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


def store_avoidances(
    session: Session,
    system_id: uuid.UUID,
    avoidances: Mapping[str, Sequence[str]],
) -> int:
    """Replace ``system_id``'s ``avoids`` edges with these, returning how many.

    Replaces rather than merges, as the descriptions do and for the same reason: a
    corpus's declarations are derived wholesale from one file, so a re-import that
    dropped a directive should drop its rows too.

    One Core insert, since `set.mm` lands 3,107 of these and they are three
    columns apiece.
    """
    session.execute(
        delete(LabelAvoidanceRow).where(
            LabelAvoidanceRow.formal_system_id == system_id
        )
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "formal_system_id": system_id,
            "label": label,
            "avoided": avoided,
            "position": position,
        }
        for label, targets in avoidances.items()
        for position, avoided in enumerate(targets)
    ]
    if rows:
        session.execute(insert(LabelAvoidanceRow), rows)
    return len(rows)


async def avoided_by(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> list[str]:
    """What ``label``'s proof is declared to do without, in the file's order.

    Asked of the whole spine, for the reason :mod:`app.db.lineage` gives: a
    layered corpus files each statement against the layer its section falls in, so
    a directive about a ZF theorem is stored against a system a propositional read
    has never heard of. The label is unique across the spine, so at most one
    layer answers.
    """
    return list(
        await session.scalars(
            select(LabelAvoidanceRow.avoided)
            .where(
                LabelAvoidanceRow.formal_system_id.in_(
                    await spine_ids(session, system_id)
                ),
                LabelAvoidanceRow.label == label,
            )
            .order_by(LabelAvoidanceRow.position)
        )
    )
