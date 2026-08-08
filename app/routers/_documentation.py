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

from app.db.avoidances_mapping import avoided_by
from app.db.descriptions_mapping import mentions_of
from app.db.label_search import proofs_named
from app.db.lineage import spine_ids
from app.schemas import Attribution, LabelDescription, LabelMention, LabelReference

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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
    spine: Sequence[uuid.UUID],
    names: Iterable[str],
    viewer: User | None,
) -> Mapping[str, tuple[uuid.UUID, str | None]]:
    """Which of ``names`` are proofs of this system the viewer may open.

    ``spine`` is the whole chain, not just this system: a layered corpus
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

    The resolution itself is :func:`app.db.label_search.proofs_named`, which grew
    out of this function and now serves the label search too — nearest layer wins,
    since a system's own proof is what its own prose meant. Kept as a wrapper
    rather than called directly at both sites so this file stays the place the
    linking policy is explained.
    """
    return await proofs_named(session, spine, list(names), viewer)


async def documentation_out(
    session: AsyncSession,
    system_id: uuid.UUID,
    label: str,
    row: LabelDescriptionRow | None,
    viewer: User | None,
) -> LabelDescription | None:
    """One label's record, with its references pointed at something.

    None when the system records *nothing* about the label, which is every
    hand-authored proof: a system describes the labels it was imported with, and a
    proof created through the API carries its own title and description instead.

    Nothing is not the same as no prose, which is why ``label`` is an argument
    rather than read off ``row``. A `$j usage … avoids …` names a label whether or
    not the file also comments on it — that being why `label_avoidances` is a
    separate table — so a record with avoidances and no description is a record,
    and returning None for it would put the two facts back together (found in
    review).
    """
    # Once for the whole read. Three questions below want the same chain, and
    # each walking it themselves cost a dozen sequential round trips per proof
    # page on a layered corpus (found in review).
    spine = await spine_ids(session, system_id)
    avoids = await avoided_by(session, spine, label)
    if row is None:
        if not avoids:
            return None
        return LabelDescription(label=label, avoids=avoids)

    mentioned, total = await mentions_of(session, spine, row.label, MENTION_LIMIT)
    # One lookup for both directions, since a label mentioning this one is as
    # likely to be a proof as a label this one mentions.
    linkable = await _linkable(
        session,
        spine,
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
        avoids=avoids,
        discouraged_usage=row.discouraged_usage,
        discouraged_modification=row.discouraged_modification,
    )
