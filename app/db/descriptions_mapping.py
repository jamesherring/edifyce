"""Storing and loading what a system says about its labels.

The write side is synchronous and the read side async, for the reason
:mod:`app.db.notations_mapping` records: the one thing that *produces* a
description is an import, and an import is synchronous; a reader has rows.

Nothing here parses. :func:`website.logical.metamath.comments.read_comment` is
what turns a ``$( … $)`` body into prose, attributions and markup, and it needs
Metamath's comment syntax to do it — so the parse happens where the file is, and
these rows are the result. A cross-reference is stored with the *span* it occupies
in the prose for the same reason: so that rendering it as a link is a slice rather
than a second parser.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, distinct, func, insert, select
from sqlalchemy.orm import selectinload

from app.db.lineage import spine_ids
from app.db.descriptions import (
    LabelAttributionRow,
    LabelDescriptionRow,
    LabelReferenceRow,
)

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

    A comment that said nothing at all is skipped, but one that said nothing *in
    prose* is not. Two of `set.mm`'s are only a ``(Contributed by …)``, and
    authorship with no prose is still authorship — and since the discouragement
    markers come out of the prose too, a comment that was only
    ``(New usage is discouraged.)`` would otherwise be dropped along with the
    warning it exists to carry (found in review).

    Written as Core inserts rather than through the ORM, with the ids minted here
    so the children can point at their parents without a round trip. `set.mm` lands
    50,550 descriptions, 60,661 attributions and 21,787 references in one call, and
    building 133,000 ORM instances at the end of a run would undo the care
    :func:`~app.db.metamath_store.import_corpus` takes to keep memory flat.
    """
    session.execute(
        delete(LabelDescriptionRow).where(
            LabelDescriptionRow.formal_system_id == system_id
        )
    )

    rows: list[dict[str, object]] = []
    attributions: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    for label, description in descriptions.items():
        if not (
            description.text
            or description.attributions
            or description.references
            or description.discouraged_usage
            or description.discouraged_modification
        ):
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
                "discouraged_usage": description.discouraged_usage,
                "discouraged_modification": description.discouraged_modification,
            }
        )
        references.extend(
            {
                "id": uuid.uuid4(),
                "description_id": description_id,
                "position": position,
                "target": reference.target,
                "start_offset": reference.start,
                "end_offset": reference.end,
            }
            for position, reference in enumerate(description.references)
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
    if references:
        session.execute(insert(LabelReferenceRow), references)
    return len(rows)


async def load_description(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> LabelDescriptionRow | None:
    """One label's description, its attributions and references, or None.

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
        .options(
            selectinload(LabelDescriptionRow.attributions),
            selectinload(LabelDescriptionRow.references),
        )
    )


async def load_descriptions(
    session: AsyncSession, system_id: uuid.UUID, labels: Iterable[str]
) -> dict[str, LabelDescriptionRow]:
    """Those of ``labels`` this system describes, by label.

    One query for a page's worth, so listing proofs beside their titles does not
    become a query per row.

    Attributions come along; **references do not**. A listing wants a title and an
    author, and an imported corpus averages nearly half a reference per label —
    fetching 21,787 spans to render 20 rows of titles is work for nothing. The
    single-label read is where they are wanted, and where they are loaded.
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


async def mentions_of(
    session: AsyncSession, system_id: uuid.UUID, target: str, limit: int
) -> tuple[list[str], int]:
    """The labels whose prose points at ``target``, and how many there are.

    The reverse of a reference, and the reason they are rows rather than
    punctuation: "what builds on this" is the question a reader of a foundational
    theorem actually has, and `set.mm` answers it 656 times for ``ax-13``.

    Asked of the whole **spine**, because a layered corpus files each statement
    against the layer its own section falls in — so `ax-1` sits on the
    propositional root and almost everything citing it sits above. Scoped to one
    id, a root statement reports a fraction of its mentions and says nothing about
    the omission (found in review).

    Capped, with the true count beside it, because that distribution has a long
    head: returning every mention would put hundreds of labels on the page for the
    handful that matter most, and a count says "and 600 more" in one integer.
    Ordered by label so the cap takes the same slice twice.
    """
    where = (
        LabelDescriptionRow.formal_system_id.in_(
            await spine_ids(session, system_id)
        ),
        LabelReferenceRow.target == target,
    )
    # Distinct: a comment may point at the same label twice (set.mm's `idi` and
    # `a1ii` each reference the other from two sentences), and a reader wants the
    # statement once.
    labels = (
        await session.scalars(
            select(LabelDescriptionRow.label)
            .join(LabelReferenceRow.description)
            .where(*where)
            .distinct()
            .order_by(LabelDescriptionRow.label)
            .limit(limit)
        )
    ).all()
    if len(labels) < limit:
        return list(labels), len(labels)
    total = await session.scalar(
        select(func.count(distinct(LabelDescriptionRow.label)))
        .select_from(LabelReferenceRow)
        .join(LabelReferenceRow.description)
        .where(*where)
    )
    return list(labels), total or 0
