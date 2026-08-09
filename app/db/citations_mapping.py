"""Which theorems a stored proof cites, and which proofs cite it.

Distinct from ``proof_references``, and the distinction is the point. That table
is the *alias-lemma* mechanism: a hand-authored proof names another proof under an
alias and cites one of its lines as ``[alias.line]``, which is why a verify walks
the whole transitive closure and re-parses it (``proofs._verify_with_references``).

A citation of a **theorem** is not that. It names a statement, resolves through
``promoted_theorems``, and is recorded on the line that used it — the label in
``proof_lines.rule``. An imported corpus is built entirely of these, so its
``proof_references`` is empty and correctly so; materialising one row per Metamath
citation would both overload the alias semantics and put a corpus-sized transitive
closure in front of every verify.

So the graph is queried rather than stored. ``ix_proof_lines_rule`` is the index
it runs on, and exists for exactly this ("which proofs use this rule" over a whole
corpus, per its own note on the model).

Both directions resolve a citation to a proof through ``promoted_theorems`` rather
than by matching the label against ``Proof.name``. A label and a name are not the
same string: promotion defaults to the proof's *slug* (`proofs._label_from_slug`),
so a proof called "My Lemma" is cited as ``my-lemma``. Matching on name works only
for an imported corpus, where the importer sets the two alike — and silently
answers nothing for everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select

from app.db.models import Proof
from app.db.proof_lines import ProofLineRow
from app.db.promoted_theorems import PromotedTheoremRow

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from app.db.models import User


@dataclass(frozen=True)
class Citation:
    """One end of a citation edge: what it names, and the page to open.

    ``proof_id`` is None when the label has no proof behind it — a primitive
    nobody proved — or when the proof behind it is one this viewer may not read.
    """

    label: str
    proof_id: uuid.UUID | None = None
    title: str | None = None


def _readable(viewer: User | None) -> ColumnElement[bool]:
    """The predicate a proof read applies: published, or the viewer's own.

    The same one `label_search.proofs_named` uses, and it belongs on **both**
    directions of this graph. Forward it withholds a link, which is cosmetic.
    Backward it withholds the row, which is not: a dependent is a `Proof`, and
    its ``name`` is a string someone typed into their own draft. Listing that
    under a published proof's dependents would publish it (found in review). The
    documentation read this mirrors cannot make the same mistake — its back-
    references come from system-owned corpus rows, never from a proof.
    """
    readable = [Proof.published_at.is_not(None)]
    if viewer is not None:
        readable.append(Proof.owner_id == viewer.id)
    return or_(*readable)


async def cited_theorems(
    session: AsyncSession,
    proof_id: uuid.UUID,
    spine: Sequence[uuid.UUID],
    viewer: User | None,
) -> list[Citation]:
    """The theorems this proof's lines cite, in the order they first appear.

    Not capped: a proof cites what it cites, and the distribution has no head to
    speak of — `set.mm`'s longest proof names a few hundred distinct statements
    where the reverse direction runs to five figures for a single axiom.

    Restricted to labels a ``promoted_theorems`` row in this spine actually names,
    which is what makes it a citation of a *theorem* rather than of a rule: a
    hand-authored proof's ``rule`` is as often ``MP`` — a rule of the system, with
    no entry and no page to open — and listing those under "cites" would answer a
    question about the library with the name of an inference rule.

    Outer-joined to the proving proof, so an entry nobody proved (half a corpus)
    or one the viewer may not read still *shows*, with nothing to open. The
    citation is real either way; it is the link that is withheld.
    """
    labels = (
        await session.scalars(
            select(ProofLineRow.rule)
            .join(
                PromotedTheoremRow,
                and_(
                    PromotedTheoremRow.label == ProofLineRow.rule,
                    PromotedTheoremRow.system_id.in_(spine),
                ),
            )
            .where(
                ProofLineRow.proof_id == proof_id,
                ProofLineRow.rule.is_not(None),
            )
            .group_by(ProofLineRow.rule)
            # By first use, which is the proof's own order and the one a reader
            # following it down the page expects. Alphabetical would scatter a
            # proof's own structure.
            .order_by(func.min(ProofLineRow.position))
        )
    ).all()
    if not labels:
        return []

    # Resolved in a second query rather than an outer join with the first. Folding
    # them together needs the proof's columns under the `GROUP BY` — and there is
    # no `max(uuid)` in Postgres, so that form passes every SQLite test in this
    # repo and 500s in production (found in review; `tests/database.py` says
    # exactly why it runs against both).
    #
    # Joined through ``proofs.theorem_id``, not ``promoted_theorems.proved_by_id``:
    # the two point opposite ways and mean different things, and only the first is
    # set by an import — a *promoted* entry carries both, an imported one carries
    # only `theorem_id` (see the note on the column). Keyed on `proved_by_id`,
    # every citation in an imported corpus resolves to nothing, which is every
    # citation this exists for.
    pages = {
        label: (found, title)
        for label, found, title in await session.execute(
            select(PromotedTheoremRow.label, Proof.id, Proof.title)
            .join(Proof, Proof.theorem_id == PromotedTheoremRow.id)
            .where(
                PromotedTheoremRow.system_id.in_(spine),
                PromotedTheoremRow.label.in_(labels),
                _readable(viewer),
            )
        )
    }
    return [
        Citation(label=label, proof_id=pages.get(label, (None, None))[0],
                 title=pages.get(label, (None, None))[1])
        for label in labels
    ]


async def citing_proofs(
    session: AsyncSession,
    spine: Sequence[uuid.UUID],
    label: str,
    viewer: User | None,
    limit: int,
) -> tuple[list[Citation], int]:
    """The proofs whose lines cite ``label``, and how many there are.

    The direction a corpus cannot be read in any other way: nothing in the file
    says what builds on `ax-mp`, and the answer is most of it. Capped with the
    true count beside it for the same reason `descriptions_mapping.mentions_of`
    is — the distribution's head is enormous, and a page listing every one of
    24,000 dependents is a page about nothing else.

    Spine-wide rather than per system, because a layered import files each proof
    against the layer its own section falls in: nearly everything citing a
    propositional axiom sits in a layer above it, so scoping to the axiom's own
    system would report almost none of its dependents.

    An ``EXISTS`` rather than a join and a ``DISTINCT``. A proof cites a lemma
    once per step that used it, so the join multiplies — `set.mm` leans on
    `ax-mp` from millions of lines — and de-duplicating that is a sort of the
    whole multiplied set before the limit can apply. ``EXISTS`` stops at the
    first matching line per proof and lets the ordering run on `proofs` (found in
    review).

    Keyed by proof id, never by name: ``Proof.name`` is unique per *system* and
    this reads a whole spine, so two layers may each hold a `1p1e2` and
    collapsing them would both undercount the total and point the entry at
    whichever row sorted first.
    """
    cites = (
        select(ProofLineRow.id)
        .where(ProofLineRow.proof_id == Proof.id, ProofLineRow.rule == label)
        .exists()
    )
    where = (Proof.formal_system_id.in_(spine), _readable(viewer), cites)
    rows = (
        await session.execute(
            select(Proof.id, Proof.name, Proof.title)
            .where(*where)
            # By name so the cap takes the same slice twice; by id after it, since
            # a name repeats across layers and the pair is what is unique.
            .order_by(Proof.name, Proof.id)
            .limit(limit)
        )
    ).all()
    citations = [
        Citation(label=name, proof_id=found, title=title) for found, name, title in rows
    ]
    if len(citations) < limit:
        return citations, len(citations)
    total = await session.scalar(
        select(func.count()).select_from(Proof).where(*where)
    )
    return citations, total or 0
