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

from app.db.descriptions import (
    LabelAttributionRow,
    LabelDescriptionRow,
    LabelCitationRow,
    LabelReferenceRow,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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
    50,550 descriptions, 60,661 attributions, 21,787 references and 5,271 citations
    in one call, and building 138,000 ORM instances at the end of a run would undo
    the care
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
    citations: list[dict[str, object]] = []
    for label, description in descriptions.items():
        if not (
            description.text
            or description.attributions
            or description.references
            or description.citations
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
        citations.extend(
            {
                "id": uuid.uuid4(),
                "description_id": description_id,
                "position": position,
                "work": citation.work,
                "page": citation.page,
                "start_offset": citation.start,
                "end_offset": citation.end,
            }
            for position, citation in enumerate(description.citations)
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
    if citations:
        session.execute(insert(LabelCitationRow), citations)
    return len(rows)


async def load_description(
    session: AsyncSession, system_id: uuid.UUID, label: str
) -> LabelDescriptionRow | None:
    """One label's description, its attributions, references and citations, or None.

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
            selectinload(LabelDescriptionRow.citations),
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
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    target: str,
    limit: int,
) -> tuple[list[str], int]:
    """The labels whose prose points at ``target``, and how many there are.

    The reverse of a reference, and the reason they are rows rather than
    punctuation: "what builds on this" is the question a reader of a foundational
    theorem actually has, and `set.mm` answers it 656 times for ``ax-13``.

    ``spine`` is the systems to look in — `app.db.lineage.spine_ids` of the one
    being read, and the whole spine rather than that one id because a layered
    corpus files each statement against the layer its own section falls in: `ax-1`
    sits on the propositional root and almost everything citing it sits above.
    Taken as an argument rather than derived here, so a caller asking several of
    these questions about one system walks the chain once (both found in review).

    Capped, with the true count beside it, because that distribution has a long
    head: returning every mention would put hundreds of labels on the page for the
    handful that matter most, and a count says "and 600 more" in one integer.
    Ordered by label so the cap takes the same slice twice.
    """
    where = (
        LabelDescriptionRow.formal_system_id.in_(spine),
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


async def works_cited(
    session: AsyncSession, spine: Sequence[uuid.UUID]
) -> list[tuple[str, int]]:
    """Every work this spine's prose cites, most-cited first.

    The question a bibliography key exists to answer and a single description
    cannot: *what does this library rest on?* `set.mm` names 135 works and leans on
    a handful of them heavily — `[Crawley]` 520 times, `[TakeutiZaring]` 445 — and
    that distribution is itself a description of the corpus.

    Counted over citations rather than over labels, so a statement citing one work
    from two places counts twice. That is the honest reading of "how much does this
    library use this book", and the alternative — distinct labels — answers a
    question nobody asked.

    Spine-wide for the reason `mentions_of` is: a layered import files each
    statement against the layer its own section falls in, so a corpus's sources are
    spread across its layers and any one of them sees a fraction.
    """
    return [
        (work, count)
        for work, count in await session.execute(
            select(LabelCitationRow.work, func.count().label("citations"))
            .join(LabelCitationRow.description)
            .where(LabelDescriptionRow.formal_system_id.in_(spine))
            .group_by(LabelCitationRow.work)
            # By count then name: ties are common in the tail — 40 of set.mm's
            # works are cited once — and an unordered tie makes two reads of the
            # same corpus disagree about a list nothing has changed.
            .order_by(func.count().desc(), LabelCitationRow.work)
        )
    ]


async def citing_labels(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    work: str,
    limit: int,
) -> tuple[list[str], int]:
    """The labels whose prose cites ``work``, and how many there are.

    "What else came from this book" — the direction that makes a citation a row
    rather than punctuation, exactly as `mentions_of` is for a cross-reference.
    Capped with the true count beside it for the same reason: `[Crawley]` is cited
    from 520 statements.
    """
    where = (
        LabelDescriptionRow.formal_system_id.in_(spine),
        LabelCitationRow.work == work,
    )
    # Distinct: a comment may cite two places in one book (`[Fremlin1] p. 13` and
    # `p. 35`), and this lists statements rather than citations.
    labels = (
        await session.scalars(
            select(LabelDescriptionRow.label)
            .join(LabelCitationRow.description)
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
        .select_from(LabelCitationRow)
        .join(LabelCitationRow.description)
        .where(*where)
    )
    return list(labels), total or 0
