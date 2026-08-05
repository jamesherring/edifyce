"""What a stored proof actually depends on, and which layer that puts it in.

The check on whether a partition is *right* (docs/system-relationships-roadmap.md
§5.5, §7.2's D6). A layer plan decides where a theorem is filed; this asks where
it belongs — by following the citation graph transitively and reporting the
deepest layer it reaches. A ZFC proof that touches nothing above propositional
calculus **is** a PC theorem, and should say so; a theorem the plan puts in FOL
that depends on a ZFC axiom is misfiled, and this finds it.

**Two questions, not one**, because they come apart and only one of them is the
one you want. Reaching a *derived* theorem of a layer is enough to pin a proof
there — re-filing it lower would leave the lemma behind — while reaching that
layer's *axioms* is what says the layer is doing logical work. A ZF proof citing
a first-order lemma that itself bottoms out in PC cannot move to PC, and yet
assumes nothing first-order. So each proof reports both:
:attr:`Provenance.deepest_cited` is the shallowest layer it could be filed in,
and :attr:`Provenance.deepest_axiom` the shallowest whose assumptions it uses.

**Read from rows, never from source.** Every edge here is a column: a line's
resolved rule label (``proof_lines.rule`` — what the *checker* used, not what the
author typed), the library entry that label names (``promoted_theorems``), and
the proof warranting it (``proofs.theorem_id``). Nothing parses, and nothing
reads ``proofs.source``; ``tests/test_provenance.py`` pins that by blanking it
and requiring the same report back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import FormalSystem, Proof
from app.db.proof_lines import ProofLineRow
from app.db.promoted_theorems import PromotedTheoremRow

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Provenance:
    """Where one proof was filed, and where its dependencies say it belongs.

    Depths are distances from the root of the proof's own chain, so ``filed`` and
    the two reaches are comparable. A ``None`` reach means the proof touched
    nothing of that kind — a proof citing only its own hypotheses depends on no
    library entry at all, which is not the same as depending on the root's.
    """

    proof: str
    # Names rather than ids throughout: an id differs between two imports of the
    # same file by construction, and a report is read by a person.
    filed_in: str
    filed: int
    # The deepest layer holding anything it transitively cites.
    deepest_cited: str | None
    cited_depth: int | None
    # The deepest layer holding a *primitive* it transitively cites.
    deepest_axiom: str | None
    axiom_depth: int | None
    # Those primitives, by label. Carried rather than recomputed because "which
    # axioms does this theorem rest on" is the question a provenance report
    # exists to answer; bounded by the corpus's axiom count.
    axioms: tuple[str, ...]

    @property
    def misfiled(self) -> bool:
        """Does it depend on a layer *deeper* than the one it was filed in?

        Impossible for a positional plan over a corpus in dependency order — and
        impossible to *verify*, since the citation would not resolve — so a true
        here means the rows disagree with the plan. The reachability half of the
        same fact is `scripts/check_layering.unreachable_citations`; this is the
        provenance half, and states it in the vocabulary of depth.
        """
        return self.cited_depth is not None and self.cited_depth > self.filed

    @property
    def depends_only_on_shallower(self) -> bool:
        """Is every one of its citations reachable from a shallower layer?

        §5.5's headline, and the measurement that says whether a boundary was
        drawn where the mathematics actually divides. Not a defect: a corpus is
        filed by subject matter and this reads it by dependency.

        **Not the same as "could be moved there", and deliberately narrower.** A
        theorem is also pinned by the *grammar* it is stated in, which this does
        not look at: `set.mm`'s `sptruw` is `( A. x ph -> ph )` proved from `a1i`
        alone, so no citation holds it in the first-order layer while `A.` does.
        Reported as movable it would have overstated 3 of the 10 this finds. What
        it says is exactly what it measures — nothing it cites needs its layer.

        False at the root whatever it cites, since there is no shallower layer at
        all. Without that, a root theorem citing nothing counted here and the
        root's column read 2 on a `set.mm` slice whose right answer is 0.
        """
        if self.filed == 0:
            return False
        return self.cited_depth is None or self.cited_depth < self.filed

    @property
    def needs_its_own_axioms(self) -> bool:
        """Does it use the assumptions of the layer it was filed in?"""
        return self.axiom_depth == self.filed


@dataclass(frozen=True)
class LayerProvenance:
    """One layer's theorems, counted by where their dependencies put them."""

    name: str
    depth: int
    proofs: int
    # Uses its own layer's axioms.
    own_axioms: int
    # Bottoms out in the axioms of a strictly shallower layer.
    lower_axioms: int
    # Reaches no promoted entry at all — cites only its own hypotheses, or
    # nothing. Counted apart rather than folded into `lower`, since "depends on
    # nothing" and "depends on something shallower" are different facts.
    no_axioms: int
    # Every citation reachable from somewhere shallower — nothing it cites needs
    # this layer. A superset of `lower_axioms` by construction, and *not* a count
    # of theorems that could be moved: see `Provenance.depends_only_on_shallower`
    # for the grammar that pins some of them anyway.
    only_shallower: int
    # Depends on something the plan filed *deeper*. Always zero on a run worth
    # trusting; see :attr:`Provenance.misfiled`.
    misfiled: int


@dataclass(frozen=True)
class _Entry:
    """A library row as the traversal needs it."""

    system_id: uuid.UUID
    label: str
    primitive: bool
    # The stored proof warranting it, if the corpus proved it here. `None` for a
    # primitive, and for an entry imported without its proof — both of which end
    # the traversal, which is why they are not distinguished.
    proof_id: uuid.UUID | None


@dataclass(frozen=True)
class _Reach:
    """The closure below one proof, as system ids rather than depths.

    Ids, because a depth is an index into a *chain* and a misfiled dependency
    sits in no chain the citing proof has — the one case this exists to report
    is exactly the one an index could not name.
    """

    cited: uuid.UUID | None
    axioms: uuid.UUID | None
    axiom_labels: tuple[str, ...]


def _chains(
    session: Session,
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, list[uuid.UUID]]]:
    """Every system's name, and its inheritance chain root-first.

    Root-first because a chain's *index* is the depth the whole report is stated
    in, and only that order makes an index mean "distance from the root".
    """
    parent: dict[uuid.UUID, uuid.UUID | None] = {}
    names: dict[uuid.UUID, str] = {}
    for system_id, name, inherits in session.execute(
        select(FormalSystem.id, FormalSystem.name, FormalSystem.inherits_from_id)
    ):
        names[system_id] = name
        parent[system_id] = inherits

    chains: dict[uuid.UUID, list[uuid.UUID]] = {}
    for system_id in names:
        chain: list[uuid.UUID] = []
        current: uuid.UUID | None = system_id
        # A cycle is not expressible through the API — a parent must be published
        # before a child may build on it — but a walk that trusts that and is
        # wrong hangs rather than fails, so it is bounded here.
        while current is not None and current not in chain:
            chain.append(current)
            current = parent[current]
        chains[system_id] = list(reversed(chain))
    return names, chains


def _library(
    session: Session, proofs_by_theorem: Mapping[uuid.UUID, uuid.UUID]
) -> dict[tuple[uuid.UUID, str], _Entry]:
    """Every promoted entry, keyed by the system that declares it and its label.

    Keyed by the pair because that is the table's own unique index: a label is
    unique per *system*, not per database, and a chain may declare one twice.
    Which of them a citation means is the chain's business, settled in
    :func:`_cited`.
    """
    return {
        (row.system_id, row.label): _Entry(
            system_id=row.system_id,
            label=row.label,
            primitive=row.primitive,
            proof_id=proofs_by_theorem.get(row.id),
        )
        for row in session.scalars(select(PromotedTheoremRow))
    }


def _cited(
    labels: Iterable[str],
    chain: Sequence[uuid.UUID],
    library: Mapping[tuple[uuid.UUID, str], _Entry],
    elsewhere: Mapping[str, _Entry],
) -> tuple[_Entry, ...]:
    """The entries a proof in ``chain`` means by those labels.

    Nearest first, matching `LibraryChain`: a label declared twice down a chain
    resolves to the closest system that has it, and an ancestor's entry is
    shadowed rather than ambiguous. A label naming nothing anywhere resolves to
    nothing and is dropped — it is a rule of the system, or one of the theorem's
    own hypotheses, and neither is a dependency on a *layer*.

    A label the chain cannot reach but some *other* system declares falls back to
    ``elsewhere``, and that fallback is what makes :attr:`Provenance.misfiled`
    reportable at all. Chain-relative resolution alone drops exactly the citation
    that proves a proof was filed above its dependency, so the check would have
    been one that cannot fail — found by the test written to make it fail.
    """
    found: list[_Entry] = []
    for label in labels:
        for system_id in reversed(chain):
            entry = library.get((system_id, label))
            if entry is not None:
                found.append(entry)
                break
        else:
            unreachable = elsewhere.get(label)
            if unreachable is not None:
                found.append(unreachable)
    return tuple(found)


def _deeper(
    left: uuid.UUID | None, right: uuid.UUID | None, depths: Mapping[uuid.UUID, int]
) -> uuid.UUID | None:
    """Whichever of two systems sits further from its root.

    Compares across chains, which a spine makes meaningful and a forest would
    not. A corpus import builds one spine, and the only cross-chain comparison
    this ever makes is against a *misfiled* dependency — where "deeper than the
    layer that cites it" is precisely the finding.
    """
    if left is None:
        return right
    if right is None:
        return left
    return left if depths[left] >= depths[right] else right


def _reach(
    proof_id: uuid.UUID,
    depths: Mapping[uuid.UUID, int],
    deps: Mapping[uuid.UUID, Sequence[_Entry]],
    memo: dict[uuid.UUID, _Reach],
) -> _Reach:
    """The transitive closure below one proof, memoised across the corpus.

    Iterative rather than recursive: a `set.mm` citation chain runs thousands of
    theorems deep and would exhaust the interpreter's stack long before the
    corpus ran out of theorems.

    Memoised **per proof**, not per label, because resolution is chain-relative:
    the entries a cited theorem means are the ones *its own* chain resolves, and
    that is what its row already records. A proof reached from two layers
    therefore contributes the same closure to both, which is what makes the memo
    sound.
    """
    stack: list[tuple[uuid.UUID, bool]] = [(proof_id, False)]
    # Guards a cycle — impossible in a corpus stored in dependency order, but a
    # traversal that assumes that and is wrong loops rather than reports.
    open_: set[uuid.UUID] = set()
    while stack:
        current, expanded = stack.pop()
        if not expanded:
            if current in memo:
                continue
            open_.add(current)
            stack.append((current, True))
            for entry in deps.get(current, ()):
                if entry.proof_id is not None and entry.proof_id not in open_:
                    stack.append((entry.proof_id, False))
            continue

        cited: uuid.UUID | None = None
        axioms: uuid.UUID | None = None
        labels: set[str] = set()
        for entry in deps.get(current, ()):
            cited = _deeper(cited, entry.system_id, depths)
            if entry.primitive:
                axioms = _deeper(axioms, entry.system_id, depths)
                labels.add(entry.label)
            # A missing memo entry is a cycle's back-edge, already on the stack
            # above us. Skipping it is what breaks the loop; the closure it would
            # have contributed is the one being computed here.
            below = memo.get(entry.proof_id) if entry.proof_id is not None else None
            if below is not None:
                cited = _deeper(cited, below.cited, depths)
                axioms = _deeper(axioms, below.axioms, depths)
                labels |= set(below.axiom_labels)
        memo[current] = _Reach(cited, axioms, tuple(sorted(labels)))
        open_.discard(current)
    return memo[proof_id]


def provenance(session: Session) -> tuple[Provenance, ...]:
    """Where every stored proof's dependencies say it belongs.

    One pass over the corpus: the rows arrive in four bulk queries and the
    closure is memoised, so the cost is linear in citations rather than in
    citations × proofs.
    """
    names, chains = _chains(session)
    depths = {system_id: chain.index(system_id) for system_id, chain in chains.items()}

    rows = list(
        session.execute(
            select(Proof.id, Proof.name, Proof.formal_system_id, Proof.theorem_id)
        )
    )
    proofs_by_theorem = {
        theorem_id: proof_id
        for proof_id, _, _, theorem_id in rows
        if theorem_id is not None
    }
    library = _library(session, proofs_by_theorem)

    # `rule` and not `reference`: the resolved label is what the checker used,
    # while the reference is what the author typed, and the two differ wherever
    # the checker filled anything in. Over-collecting from the reference — which
    # is right for a *reachability* guard, where a missed label costs a citation
    # — would be wrong here, since a label the resolver never used is not a
    # dependency and reporting it as one invents a deeper provenance than the
    # proof has.
    cited_labels: dict[uuid.UUID, list[str]] = {}
    for proof_id, rule in session.execute(
        select(ProofLineRow.proof_id, ProofLineRow.rule).where(
            ProofLineRow.rule.is_not(None)
        )
    ):
        cited_labels.setdefault(proof_id, []).append(rule)

    # The deepest declarer of each label, for the fallback in `_cited`. Deepest
    # because the fallback only ever runs for a citation no chain reaches, and
    # the finding there is how far out of reach it is.
    elsewhere: dict[str, _Entry] = {}
    for entry in library.values():
        held = elsewhere.get(entry.label)
        if held is None or depths[entry.system_id] > depths[held.system_id]:
            elsewhere[entry.label] = entry

    deps = {
        proof_id: _cited(
            cited_labels.get(proof_id, ()), chains[system_id], library, elsewhere
        )
        for proof_id, _, system_id, _ in rows
    }

    memo: dict[uuid.UUID, _Reach] = {}
    found: list[Provenance] = []
    for proof_id, name, system_id, _ in rows:
        reach = _reach(proof_id, depths, deps, memo)
        found.append(
            Provenance(
                proof=name,
                filed_in=names[system_id],
                filed=depths[system_id],
                deepest_cited=names[reach.cited] if reach.cited is not None else None,
                cited_depth=depths[reach.cited] if reach.cited is not None else None,
                deepest_axiom=names[reach.axioms] if reach.axioms is not None else None,
                axiom_depth=depths[reach.axioms] if reach.axioms is not None else None,
                axioms=reach.axiom_labels,
            )
        )
    return tuple(found)


def by_layer(reports: Sequence[Provenance]) -> tuple[LayerProvenance, ...]:
    """The same, counted per layer — the shape §7.2's D6 asks for.

    Root first, so reading down the table follows the spine. A layer with no
    proofs does not appear: this counts what was stored, and a plan opening an
    empty layer is `check_layering.py`'s business rather than this one's.
    """
    counts: dict[tuple[int, str], list[int]] = {}
    for report in reports:
        tally = counts.setdefault((report.filed, report.filed_in), [0, 0, 0, 0, 0, 0])
        tally[0] += 1
        if report.axiom_depth is None:
            tally[3] += 1
        elif report.needs_its_own_axioms:
            tally[1] += 1
        elif report.axiom_depth < report.filed:
            tally[2] += 1
        if report.depends_only_on_shallower:
            tally[4] += 1
        if report.misfiled:
            tally[5] += 1
    return tuple(
        LayerProvenance(
            name=name,
            depth=depth,
            proofs=tally[0],
            own_axioms=tally[1],
            lower_axioms=tally[2],
            no_axioms=tally[3],
            only_shallower=tally[4],
            misfiled=tally[5],
        )
        for (depth, name), tally in sorted(counts.items())
    )
