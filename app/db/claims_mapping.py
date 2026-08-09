"""Storing and reading what a corpus's ``$j`` markup claims.

The write side synchronous and the read side async, for the reason
:mod:`app.db.descriptions_mapping` records: the one thing that produces these is
an import, and an import is synchronous; a reader has rows.

Nothing here parses. :func:`website.logical.metamath.markup.claims_of` turns the
``$j`` blocks into triples, and these rows are what they become.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select

from app.db.claims import LabelClaimRow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from website.logical.metamath.markup import Claim


def store_claims(
    session: Session, system_id: uuid.UUID, claims: Sequence[Claim]
) -> int:
    """Replace ``system_id``'s claims with these, returning how many.

    Replaces rather than merges, as the descriptions do and for the same reason: a
    corpus's declarations are derived wholesale from one file, so a re-import that
    dropped a directive should drop its rows too.

    One Core insert, since `set.mm` lands 3,364 of these and they are four columns
    apiece.

    ``position`` is the claim's index within its subject, not within the file:
    what it orders is a reader's list of one label's claims, and a global counter
    would order that list by where in a 51 MB file each happened to be written.
    """
    session.execute(
        delete(LabelClaimRow).where(LabelClaimRow.formal_system_id == system_id)
    )
    seen: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for claim in claims:
        position = seen.get(claim.subject, 0)
        seen[claim.subject] = position + 1
        rows.append(
            {
                "id": uuid.uuid4(),
                "formal_system_id": system_id,
                "subject": claim.subject,
                "kind": claim.kind,
                "object": claim.object,
                "position": position,
            }
        )
    if rows:
        session.execute(insert(LabelClaimRow), rows)
    return len(rows)


async def claims_about(
    session: AsyncSession, spine: Sequence[uuid.UUID], subject: str
) -> list[tuple[str, str | None]]:
    """What this spine's markup claims about ``subject``, as ``(kind, object)``.

    ``spine`` rather than one system id for the reason
    `descriptions_mapping.mentions_of` takes one: a layered import files each
    statement against the layer its own section falls in, and a `$j` block sits
    beside the statement it talks about — so a claim about `ax-11` is stored
    against whichever layer that fell in, which is not the layer being read.

    Not capped. A label's own claims are few — set.mm's busiest subject carries a
    few dozen — and it is the *reverse* direction that has the long head.
    """
    return [
        (kind, found)
        for kind, found in await session.execute(
            select(LabelClaimRow.kind, LabelClaimRow.object)
            .where(
                LabelClaimRow.formal_system_id.in_(spine),
                LabelClaimRow.subject == subject,
            )
            .order_by(LabelClaimRow.position, LabelClaimRow.kind)
        )
    ]
