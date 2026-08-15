"""A `.mm` file's section outline, stored as the folder tree it already is.

`proof_folders` is a per-system tree with a parent, a name and an ordering, which
is exactly what a Metamath outline is
(:mod:`website.logical.metamath.sections`) — so an import needs no new table, and
a corpus arrives browsable by the structure its authors gave it rather than as
47,000 proofs in one flat list.

Synchronous, like the rest of the import path. Nothing here recognises a header:
that is the engine's job, and this stores what it read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert

from app.db.models import ProofFolder
from app.db.slugs import unique_slug
from website.logical.metamath.sections import Placement

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from website.logical.metamath.sections import Section


@dataclass(frozen=True)
class StoredOutline:
    """The folders an outline became, and where a statement belongs among them.

    ``folder_for`` takes a position in ``Database.order`` — not a walk index —
    because a section covers *statements*, and the walk visits only the provable
    ones. The two diverge by thousands on `set.mm`, where a whole subsection may
    be nothing but syntax axioms.
    """

    placement: Placement
    # Parallel to the sections, not keyed by their position in the file: two
    # headers may share one — a part followed straight away by a section — and a
    # dict keyed on that would keep only the deeper of the pair.
    ids: list[uuid.UUID]

    def folder_for(self, at: int) -> uuid.UUID | None:
        """The folder a statement at position ``at`` belongs in, deepest first."""
        index = self.placement.covering_index(at)
        return None if index is None else self.ids[index]

    def __len__(self) -> int:
        return len(self.ids)


def store_outline(
    session: Session, system_id: uuid.UUID, sections: Sequence[Section]
) -> StoredOutline:
    """Replace ``system_id``'s folders with ``sections``, returning the placement.

    Replaces rather than merges, as an import's other derived rows do: the outline
    comes wholesale from one file, so a re-import that dropped a section should
    drop its folder. The cascade takes the children with it; a proof's
    ``folder_id`` is ``ON DELETE SET NULL``, so a proof outlives its folder rather
    than going with it.

    Written as one Core insert with the ids minted here, so the parent links are
    known without a round trip per row. `set.mm` is 1,903 folders four deep, and
    the tree is walked in file order — a header's parent is always already made,
    since it is the nearest shallower one before it.
    """
    session.execute(
        delete(ProofFolder).where(ProofFolder.formal_system_id == system_id)
    )

    rows: list[dict[str, object]] = []
    ids: list[uuid.UUID] = []
    # The open sections, deepest last: a header closes every one at its level or
    # deeper, and its parent is whatever is still open. `taken` and `count` are
    # per parent, since a slug need only be unique among siblings and a position
    # is an ordering among them.
    stack: list[tuple[int, uuid.UUID]] = []
    taken: dict[uuid.UUID | None, set[str]] = {}
    count: dict[uuid.UUID | None, int] = {}

    for section in sections:
        while stack and stack[-1][0] >= section.level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        folder_id = uuid.uuid4()
        rows.append(
            {
                "id": folder_id,
                "formal_system_id": system_id,
                "parent_id": parent,
                "name": section.title,
                "slug": unique_slug(
                    section.title, taken.setdefault(parent, set()), "section"
                ),
                "description": section.text or None,
                "position": count.get(parent, 0),
            }
        )
        count[parent] = count.get(parent, 0) + 1
        ids.append(folder_id)
        stack.append((section.level, folder_id))

    if rows:
        session.execute(insert(ProofFolder), rows)
    return StoredOutline(placement=Placement(sections), ids=ids)
