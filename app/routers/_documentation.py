"""Serving a label's documentation, cross-references resolved.

Shared by the proof and system routers because both answer the same question
about the same rows — ``GET /proofs/{id}`` carries a proof's own record and
``GET /formal-systems/{id}/labels/{label}`` reaches the ones that are not proofs
at all (``df-un``, ``ax-ext``). It lives here rather than in either because
`proofs` already imports `systems`, so the other direction would close a cycle.

What this adds beyond the stored rows is **resolution**: a stored reference is a
target string, and what a reader wants is a link. Which of a corpus's targets name
a proof, and which of those the viewer may open, are questions about the database
and about who is asking — so they are answered here, per read, rather than frozen
into a column that a later import would falsify.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from app.db.descriptions_mapping import mentions_of
from app.db.lineage import spine_ids
from app.db.models import Proof
from app.schemas import Attribution, LabelDescription, LabelMention, LabelReference

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.descriptions import LabelDescriptionRow
    from app.db.models import User

# How many back-references a read carries. `set.mm`'s distribution has a long
# head — `ax-13` is pointed at by 656 statements — and a page showing all of them
# is a page about nothing else. The total rides alongside, so a client can say
# "and 640 more" without asking again.
MENTION_LIMIT = 20


async def _linkable(
    session: AsyncSession,
    system_id: uuid.UUID,
    names: Iterable[str],
    viewer: User | None,
) -> Mapping[str, tuple[uuid.UUID, str | None]]:
    """Which of ``names`` are proofs of this system the viewer may open.

    One query for the whole set rather than one per reference: a single comment
    can carry a dozen, and a corpus read that costs a round trip apiece would make
    the documentation the expensive half of the page.

    Searched across the whole **spine**, not just this system: a layered corpus
    files a proof against the layer its section falls in, so a ZF statement
    referencing `ax-mp` points at the propositional root and a root comment saying
    "see ~ sqrt2irr" points at the leaf. Scoped to one id, every cross-layer
    reference on a `--setmm-layers` import renders as dead text (found in review).
    A sibling system is still out of reach, which is right: what it happens to call
    `ax-mp` is not this one's.

    Scoped by the same predicate a single proof read applies — published, or the
    viewer's own — so a reference to someone's draft resolves to nothing rather
    than handing out its id. The reference itself still shows; it is the *link*
    that is withheld, which is the truthful rendering: the corpus does say the
    word, and the reader cannot follow it.
    """
    wanted = list(dict.fromkeys(names))
    if not wanted:
        return {}
    readable = [Proof.published_at.is_not(None)]
    if viewer is not None:
        readable.append(Proof.owner_id == viewer.id)
    chain = await spine_ids(session, system_id)
    rows = await session.execute(
        select(Proof.formal_system_id, Proof.name, Proof.id, Proof.title).where(
            Proof.formal_system_id.in_(chain),
            Proof.name.in_(wanted),
            or_(*readable),
        )
    )
    # Nearest layer wins where two of them declare the label: a system's own proof
    # is what its own prose meant. `Proof.name` is unique per system but not per
    # spine, so the tie is real — and sorted here rather than left to the `IN`,
    # which returns rows in no order the chain knows about.
    depth = {found: index for index, found in enumerate(chain)}
    resolved: dict[str, tuple[uuid.UUID, str | None]] = {}
    for owner, name, found, title in sorted(rows, key=lambda row: depth[row[0]]):
        resolved.setdefault(name, (found, title))
    return resolved


async def documentation_out(
    session: AsyncSession,
    system_id: uuid.UUID,
    row: LabelDescriptionRow | None,
    viewer: User | None,
) -> LabelDescription | None:
    """One label's record, with its references pointed at something.

    None when the system keeps no record, which is every hand-authored proof: a
    system describes the labels it was *imported* with, and a proof created
    through the API carries its own title and description instead.
    """
    if row is None:
        return None

    mentioned, total = await mentions_of(session, system_id, row.label, MENTION_LIMIT)
    # One lookup for both directions, since a label mentioning this one is as
    # likely to be a proof as a label this one mentions.
    linkable = await _linkable(
        session,
        system_id,
        [*(reference.target for reference in row.references), *mentioned],
        viewer,
    )

    def link(name: str) -> tuple[uuid.UUID | None, str | None]:
        return linkable.get(name, (None, None))

    return LabelDescription(
        label=row.label,
        title=row.title,
        text=row.text,
        attributions=[
            Attribution(kind=a.kind, who=a.who, dated=a.dated) for a in row.attributions
        ],
        references=[
            LabelReference(
                target=reference.target,
                start=reference.start_offset,
                end=reference.end_offset,
                proof_id=link(reference.target)[0],
                title=link(reference.target)[1],
            )
            for reference in row.references
        ],
        mentioned_by=[
            LabelMention(label=label, proof_id=link(label)[0], title=link(label)[1])
            for label in mentioned
        ],
        mentioned_by_total=total,
        discouraged_usage=row.discouraged_usage,
        discouraged_modification=row.discouraged_modification,
    )
