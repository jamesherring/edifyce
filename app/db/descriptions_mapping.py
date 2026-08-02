"""Storing and loading what a system says about its labels.

The write side is synchronous and the read side async, for the reason
:mod:`app.db.notations_mapping` records: the one thing that *produces* a
description is an import, and an import is synchronous; a reader has rows.

Nothing here parses. :func:`website.logical.metamath.comments.read_comment` is
what turns a ``$( … $)`` body into prose and attributions, and it needs Metamath's
comment syntax to do it — so the parse happens where the file is, and these rows
are the result.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import selectinload

from app.db.descriptions import LabelAttributionRow, LabelDescriptionRow

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from website.logical.metamath.comments import Description


def store_descriptions(
    session: Session,
    system_id: uuid.UUID,
    descriptions: Mapping[str, Description],
) -> int:
    """Replace ``system_id``'s descriptions with these, returning how many.

    Replaces rather than merges, as a notation does and for the same reason: a
    corpus's documentation is derived wholesale from one file, so a re-import that
    dropped a label should drop its prose too rather than leave the old text
    behind under a label the file no longer has.

    A comment that said nothing at all is skipped, but an *attribution-only* one
    is not: two of `set.mm`'s comments are nothing but a ``(Contributed by …)``,
    and authorship with no prose is still authorship.

    Written as two Core inserts rather than through the ORM, with the ids minted
    here so the children can point at their parents without a round trip. `set.mm`
    lands 50,550 descriptions and 60,661 attributions in one call, and building
    111,000 ORM instances at the end of a run would undo the care
    :func:`~app.db.metamath_store.import_corpus` takes to keep memory flat.
    """
    session.execute(
        delete(LabelDescriptionRow).where(
            LabelDescriptionRow.formal_system_id == system_id
        )
    )

    rows: list[dict[str, object]] = []
    attributions: list[dict[str, object]] = []
    for label, description in descriptions.items():
        if not description.text and not description.attributions:
            continue
        description_id = uuid.uuid4()
        rows.append(
            {
                "id": description_id,
                "formal_system_id": system_id,
                "label": label,
                # Empty prose means an attribution-only comment; the title is then
                # the whole of nothing, and null says that better than "".
                "title": description.title or None,
                "text": description.text,
            }
        )
        attributions.extend(
            {
                "id": uuid.uuid4(),
                "description_id": description_id,
                "position": position,
                "kind": attribution.kind,
                "who": attribution.who,
                "dated": attribution.when,
            }
            for position, attribution in enumerate(description.attributions)
        )

    if rows:
        session.execute(insert(LabelDescriptionRow), rows)
    if attributions:
        session.execute(insert(LabelAttributionRow), attributions)
    return len(rows)


async def load_description(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> LabelDescriptionRow | None:
    """One label's description, attributions loaded, or None if it has none.

    Not layered through the inheritance chain, unlike a notation: a description is
    about a label *this* system declares, and a child that redeclares nothing
    inherits the ancestor's labels along with the ancestor's rows — which
    :func:`load_descriptions` reaches by system id, the id the label was stored
    against. A child cannot describe a label it does not declare.
    """
    return await session.scalar(
        select(LabelDescriptionRow)
        .where(
            LabelDescriptionRow.formal_system_id == system_id,
            LabelDescriptionRow.label == label,
        )
        .options(selectinload(LabelDescriptionRow.attributions))
    )


async def load_descriptions(
    session: AsyncSession, system_id: uuid.UUID, labels: Iterable[str]
) -> dict[str, LabelDescriptionRow]:
    """Those of ``labels`` this system describes, by label.

    One query for a page's worth, so listing proofs beside their titles does not
    become a query per row.
    """
    wanted = list(dict.fromkeys(labels))
    if not wanted:
        return {}
    found = await session.scalars(
        select(LabelDescriptionRow)
        .where(
            LabelDescriptionRow.formal_system_id == system_id,
            LabelDescriptionRow.label.in_(wanted),
        )
        .options(selectinload(LabelDescriptionRow.attributions))
    )
    return {row.label: row for row in found}


async def contributions(
    session: AsyncSession, system_id: uuid.UUID, who: str, kind: str | None = None
) -> list[tuple[str, str]]:
    """``(label, kind)`` for everything ``who`` is credited with in this system.

    The question rows exist to answer — a string column would make it a scan. See
    :class:`~app.db.descriptions.LabelAttributionRow` on why ``kind`` is matched
    verbatim: the corpus misspells four of them, and this does not second-guess it.
    """
    query = (
        select(LabelDescriptionRow.label, LabelAttributionRow.kind)
        .join(LabelAttributionRow.description)
        .where(
            LabelDescriptionRow.formal_system_id == system_id,
            LabelAttributionRow.who == who,
        )
        .order_by(LabelDescriptionRow.label)
    )
    if kind is not None:
        query = query.where(LabelAttributionRow.kind == kind)
    return [(label, found) for label, found in await session.execute(query)]
