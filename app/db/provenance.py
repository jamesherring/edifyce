"""What a stored proof actually depends on, and which layer that puts it in.

The check on whether a partition is *right* (docs/system-relationships-roadmap.md
§5.5, §7.2's D6). A layer plan decides where a theorem is filed; this asks where
it belongs — by following the citation graph transitively and reporting the
deepest layer it reaches. A ZFC proof that touches nothing above propositional
calculus **is** a PC theorem, and should say so; a theorem the plan puts in FOL
that depends on a ZFC axiom is misfiled, and this finds it.

**Three questions, not one**, because they come apart and each answers something
the others do not:

- what it **cites** pins it, since re-filing it below a lemma would leave that
  lemma behind (:attr:`Provenance.deepest_cited`);
- what its citations **assume** says whether the layer is doing logical work — a
  ZF proof citing a first-order lemma that itself bottoms out in PC assumes
  nothing first-order (:attr:`Provenance.deepest_axiom`);
- and what it is **written in** pins it too, independently of both: a theorem
  stating something first-order and proving it propositionally still needs `A.`
  wherever it is filed (:attr:`Provenance.deepest_grammar`).

The conjunction of the first and the last is :attr:`could_be_filed_lower`, the
one to read as "this could be moved".

*And the grammar half is what disproved the guess that motivated it.* `set.mm`'s
`sptruw` is `( A. x ph -> ph )` proved from `a1i` alone, which looked like a
theorem the citation graph would wrongly call movable — first-order notation, so
surely pinned. It is not: `set.mm` declares `wal` in the *syntax* material that
falls in the propositional layer and only the quantifier **axioms** in the
first-order one, so `A.` is grammatical in PC and `sptruw` really can move. Of
the corpus's 10 exceptions the grammar half binds none. What a layer declares is
a fact about the file, and reading "∀ is first-order notation" off what the
symbol *means* got it wrong — which is the whole reason this is measured.

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

from app.db.assumptions import AssumptionRow
from app.db.models import FormalSystem, Proof
from app.db.proof_lines import ProofLineRow
from app.db.promoted_theorems import PromotedTheoremPremiseRow, PromotedTheoremRow
from app.db.systems import DefinitionRow, RuleRow, SymbolRow
from app.db.terms import TermChildRow, TermRow

if TYPE_CHECKING:
    from collections.abc import AbstractSet, Iterable, Mapping, Sequence

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
    #
    # An **assumption** is a primitive too — asserted with no warrant, which is
    # what the traversal reads — but it is a debt rather than a foundation, so it
    # is reported apart (`app/db/assumptions.py`). The two partition the
    # primitives reached: a label appears in exactly one of them, and a corpus
    # that adopts no assumptions has `axioms` exactly as it did before this
    # existed.
    axioms: tuple[str, ...]
    # The deepest layer declaring a production its own lines are *written* in.
    # A second way to be pinned, and independent of the first: a theorem stating
    # something first-order and proving it propositionally needs `A.` to exist
    # wherever it is filed, whatever its citations say.
    deepest_grammar: str | None
    grammar_depth: int | None
    # The deepest layer declaring an inference **rule** or **definition** it
    # cites. A third pin, and neither of the other two: a rule is not a library
    # entry (a citation of one resolves to no `promoted_theorems` row, which is
    # why `_cited` drops it) and not notation, and yet a proof cannot be checked
    # in a layer that does not declare it (found in review).
    deepest_rule: str | None
    rule_depth: int | None
    # The unproved *debts* it rests on, by label. Non-empty means this proof
    # establishes a conditional, whatever its own lines say. Defaulted, and so
    # placed after the pins above, which are not.
    assumes: tuple[str, ...] = ()
    # Did the closure touch an entry this proof's own chain cannot resolve? The
    # defect :attr:`misfiled` reports, carried as a fact rather than inferred
    # from a depth comparison that only means anything down a single spine.
    unreachable: bool = False
    # The same, for the machinery rather than the citations: notation, a rule or
    # a definition the proof needs and its chain does not reach. Separate from
    # `unreachable` only in provenance; :attr:`misfiled` is their disjunction.
    unreachable_machinery: bool = False

    @property
    def rests_on_assumptions(self) -> bool:
        """Does it depend on something nobody has proved anywhere?"""
        return bool(self.assumes)

    @property
    def misfiled(self) -> bool:
        """Is anything it needs out of reach of the layer it was filed in?

        Impossible for a positional plan over a corpus in dependency order — and
        impossible to *verify*, since the proof would not rebuild — so a true
        here means the rows disagree with the plan. The same fact
        `scripts/check_layering.unreachable_citations` reports, in the vocabulary
        of provenance.

        Reachability and not depth. "Deeper than the layer that filed it" is the
        right test down one spine and says nothing across two branches of a tree,
        where the sibling holding the citation may sit at any depth at all —
        including a shallower one, which read as a clean *could be filed lower*
        (found in review).

        **Citations and machinery both.** A proof filed above the layer declaring
        its own notation cannot be rebuilt there either, and reporting that only
        by suppressing `could_be_filed_lower` left the run exiting 0 on a proof
        that does not stand where it sits (also found in review).
        """
        return self.unreachable or self.unreachable_machinery

    @property
    def depends_only_on_shallower(self) -> bool:
        """Is every one of its citations reachable from a shallower layer?

        §5.5's headline, and the measurement that says whether a boundary was
        drawn where the mathematics actually divides. Not a defect: a corpus is
        filed by subject matter and this reads it by dependency.

        **Citations only, and deliberately so.** A theorem is pinned by the
        *grammar* it is written in as well as by what it cites, and the two are
        different facts about it. :attr:`could_be_filed_lower` is the
        conjunction — the one to read as "could be moved".

        False at the root whatever it cites, since there is no shallower layer at
        all. Without that, a root theorem citing nothing counted here and the
        root's column read 2 on a `set.mm` slice whose right answer is 0.

        False for a misfiled proof too: what it cites is not reachable from
        anywhere on its chain, shallower least of all. **Misfiled** and not merely
        unreachable — a proof stranded by its *machinery* is as unable to stand
        where it sits, and guarding on the narrower of the two let one count as
        both misfiled and only-shallower, with an off-chain depth then making
        `could_be_filed_lower` true (found in review).
        """
        if self.filed == 0 or self.misfiled:
            return False
        return self.cited_depth is None or self.cited_depth < self.filed

    @property
    def could_be_filed_lower(self) -> bool:
        """Is *everything* it needs — citations and notation both — shallower?

        The honest "this could be moved". A theorem needs two things where it
        sits: every entry it cites, and every production its own lines are
        written in. Either alone can overstate — though on `set.mm` at the
        milestone slice the two agree, since the corpus declares its notation
        well before the axioms governing it (see the module docstring).

        The notation of a *cited* theorem is not asked about, and does not need
        to be: it is available wherever that theorem is, and being able to reach
        the theorem at all is what :attr:`depends_only_on_shallower` already
        settles.
        """
        if not self.depends_only_on_shallower:
            return False
        return all(
            depth is None or depth < self.filed
            for depth in (self.grammar_depth, self.rule_depth)
        )

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
    # Reaches no *primitive* — cites only derived entries whose proofs this
    # database does not hold, its own hypotheses, or nothing at all. Counted
    # apart rather than folded into `lower_axioms`, since "rests on no
    # assumption we can see" and "rests on a shallower one" are different facts.
    # (It is not "cites nothing": a citation resolving to a derived entry with no
    # stored proof lands here too, and the comment used to say otherwise.)
    no_axioms: int
    # Every citation reachable from somewhere shallower — nothing it *cites*
    # needs this layer. A superset of `lower_axioms` by construction, and of
    # `could_be_lower`: a theorem is pinned by its notation too.
    only_shallower: int
    # And everything it needs is shallower, notation included — the count of
    # theorems that could really be moved.
    could_be_lower: int
    # Depends on something its chain cannot reach. Always zero on a run worth
    # trusting; see :attr:`Provenance.misfiled`. Its own bucket rather than a
    # fourth reading of the axiom columns, because a citation off the chain has
    # no comparable depth — and because with nowhere to put them, a misfiled
    # proof fell through all three and the columns stopped summing to `proofs`
    # (found in review, on this module's own misfiled test).
    misfiled: int


@dataclass(frozen=True)
class _Entry:
    """A library row as the traversal needs it."""

    system_id: uuid.UUID
    label: str
    primitive: bool
    # A primitive that is a *debt* rather than a foundation. Never true without
    # `primitive`, since an assumption is stored as one.
    assumed: bool
    # The stored proof warranting it, if the corpus proved it here. `None` for a
    # primitive, and for an entry imported without its proof — both of which end
    # the traversal, which is why they are not distinguished.
    proof_id: uuid.UUID | None


@dataclass(frozen=True)
class _Citation:
    """One resolved citation, and whether the citing proof could reach it.

    Reachability belongs here rather than on :class:`_Entry` because it is a
    fact about the *pair*: the same library row is in reach of one proof's chain
    and out of another's, and `library` interns each row once.
    """

    entry: _Entry
    reachable: bool


@dataclass(frozen=True)
class _Reach:
    """The closure below one proof, as system ids rather than depths.

    Ids, because a depth is an index into a *chain* and an out-of-reach
    dependency sits in no chain the citing proof has — the one case this exists
    to report is exactly the one an index could not name.
    """

    cited: uuid.UUID | None
    axioms: uuid.UUID | None
    axiom_labels: tuple[str, ...]
    assumed_labels: tuple[str, ...]
    unreachable: bool


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
    assumed = set(session.scalars(select(AssumptionRow.theorem_id)))
    return {
        (row.system_id, row.label): _Entry(
            system_id=row.system_id,
            label=row.label,
            primitive=row.primitive,
            assumed=row.id in assumed,
            proof_id=proofs_by_theorem.get(row.id),
        )
        for row in session.scalars(select(PromotedTheoremRow))
    }


def _cited(
    labels: Iterable[str],
    chain: Sequence[uuid.UUID],
    library: Mapping[tuple[uuid.UUID, str], _Entry],
    elsewhere: Mapping[tuple[uuid.UUID, str], _Entry],
    explained: AbstractSet[str],
) -> tuple[_Citation, ...]:
    """The entries a proof in ``chain`` means by those labels.

    Nearest first, matching `LibraryChain`: a label declared twice down a chain
    resolves to the closest system that has it, and an ancestor's entry is
    shadowed rather than ambiguous. A label naming nothing resolves to nothing
    and is dropped — it is a rule of the system, or one of the theorem's own
    hypotheses, and neither is a dependency on a *layer*.

    A label the chain cannot reach, but which some system **of the same tree**
    declares, falls back to ``elsewhere`` and is marked unreachable. That
    fallback is what makes :attr:`Provenance.misfiled` reportable at all:
    chain-relative resolution alone drops exactly the citation that proves a
    proof was filed away from its dependency, so the check would have been one
    that cannot fail — found by the test written to make it fail.

    **Keyed by the tree's root, and only for a label the chain cannot otherwise
    explain.** ``proof_lines.rule`` holds whatever justified the line, which for
    an ordinary inference rule is a name like ``MP`` that any system may declare.
    Two rounds of review on that:

    - a *database-wide* index resolved one corpus's rule name to another
      corpus's theorem, inventing a dependency out of a coincidence of spelling.
      Hence the root;
    - the root alone still lets two **siblings** collide, since a proof in one
      branch citing its own rule ``R`` found a promoted ``R`` in the other and
      was called misfiled for it. Hence ``explained`` — the labels the proof's
      own chain accounts for as something that is *not* a library entry: a rule
      it declares, or a hypothesis of the theorem being proved. Those resolve to
      no layer and drop out, rather than falling through to a stranger.

    What is left for the fallback is a label the citing chain explains in no way
    at all, which is the shape a misfiled proof has and nothing else does.
    """
    root = chain[0]
    found: list[_Citation] = []
    for label in labels:
        for system_id in reversed(chain):
            entry = library.get((system_id, label))
            if entry is not None:
                found.append(_Citation(entry, reachable=True))
                break
        else:
            stray = None if label in explained else elsewhere.get((root, label))
            if stray is not None:
                found.append(_Citation(stray, reachable=False))
    return tuple(found)


def _declared_in(
    session: Session, chains: Mapping[uuid.UUID, Sequence[uuid.UUID]]
) -> dict[uuid.UUID, dict[str, uuid.UUID]]:
    """Per system, which layer first declares each grammar name it can see.

    The **shallowest** system on the chain carrying a row for a name, which is
    the one that declares it. A production has exactly one row and so one answer;
    a *sort* has a row in every layer that mentions it (`⊆` is a `formula` over
    `term`, and a layer declaring neither still needs rows for both, so no row
    ever references another system's namespace) — and a layer can only mention a
    sort that already exists, so the shallowest occurrence is the declaration
    there too. One rule, all three cases, definitions included.
    """
    held: dict[uuid.UUID, set[str]] = {}
    for system_id, name in session.execute(select(SymbolRow.system_id, SymbolRow.name)):
        held.setdefault(system_id, set()).add(name)

    # Notation a **definition** introduces, which no symbol row spells. A defined
    # form's constructor is `f"{sort}:{higher}"` and the `:` is deliberate — a
    # declared production's name is forced to `[A-Za-z0-9_]+`, so the pair keeps
    # defined notation out of the productions' namespace
    # (`matching/definitions.py`). Which means a lookup against `symbols` alone
    # can never match one, and the walk fell back to the *sort* — declared at the
    # root — so a proof written in a deep layer's own abbreviation reported as
    # movable to the root. Exactly the class the grammar half exists to catch,
    # failing silently (found in review).
    for system_id, sort, higher in session.execute(
        select(DefinitionRow.system_id, SymbolRow.name, DefinitionRow.higher).join(
            SymbolRow, DefinitionRow.symbol_id == SymbolRow.id
        )
    ):
        held.setdefault(system_id, set()).add(f"{sort}:{higher}")

    found: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for system_id, chain in chains.items():
        where: dict[str, uuid.UUID] = {}
        for ancestor in chain:
            for name in held.get(ancestor, ()):
                where.setdefault(name, ancestor)
        found[system_id] = where
    return found


def _grammar_systems(
    session: Session,
    declared_in: Mapping[uuid.UUID, Mapping[str, uuid.UUID]],
    depths: Mapping[uuid.UUID, int],
) -> dict[uuid.UUID, uuid.UUID]:
    """Per stored term, the deepest layer declaring anything its tree is built from.

    A system **id** and not a depth, for the reason :class:`_Reach` carries ids:
    a depth is an index into a chain, and a term interned against one system can
    be read by a proof filed in another — a misfiled one — whose chain is shorter
    than that index. Returning a depth walked off the end of it.

    Memoised over the shared DAG rather than walked per proof: `set.mm`'s corpus
    interns to a few tens of thousands of terms, and a per-proof walk would
    revisit the same subterm once per theorem mentioning it. Sound to memoise by
    term id because a term is interned **per system**
    (``uq_terms_system_digest``) and so are its children, so every node below a
    term resolves its names through that term's own chain.
    """
    nodes: dict[uuid.UUID, tuple[uuid.UUID, str | None, str | None]] = {
        term_id: (system_id, constructor, sort)
        for term_id, system_id, constructor, sort in session.execute(
            select(
                TermRow.id, TermRow.formal_system_id, TermRow.constructor, TermRow.sort
            )
        )
    }
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for parent_id, child_id in session.execute(
        select(TermChildRow.parent_id, TermChildRow.child_id)
    ):
        children.setdefault(parent_id, []).append(child_id)

    found: dict[uuid.UUID, uuid.UUID | None] = {}
    for root in nodes:
        if root in found:
            continue
        # Iterative for the same reason `_reach` is: a corpus term tree is
        # usually shallow, and a statement that nests deeply is not worth
        # gambling the interpreter's stack on.
        stack: list[tuple[uuid.UUID, bool]] = [(root, False)]
        # And guarded like `_reach` too. `store_term` interns by digest, so a
        # term cannot become its own subterm and a cycle is unreachable — but a
        # walk that assumes that and is wrong grows the stack without bound
        # rather than failing, and this one cited `_reach` as its model while
        # leaving the guard out (found in review).
        open_: set[uuid.UUID] = set()
        while stack:
            current, expanded = stack.pop()
            if current in found:
                continue
            if not expanded:
                open_.add(current)
                stack.append((current, True))
                stack.extend(
                    (child, False)
                    for child in children.get(current, ())
                    if child not in found and child not in open_
                )
                continue
            open_.discard(current)
            system_id, constructor, sort = nodes[current]
            where = declared_in.get(system_id, {})
            deepest: uuid.UUID | None = None
            # A node names its production; a variable or bound leaf names only
            # its sort. Both are grammar the term cannot be written without.
            for name in (constructor, sort):
                if name is not None and name in where:
                    deepest = _deeper(deepest, where[name], depths)
            for child in children.get(current, ()):
                deepest = _deeper(deepest, found.get(child), depths)
            found[current] = deepest
    return {term: system for term, system in found.items() if system is not None}


def _rule_labels(session: Session) -> dict[uuid.UUID, set[str]]:
    """Per system, every spelling by which a citation could name one of its rules.

    Both ``label`` and ``name``, because a rule citation resolves through either
    and the cost of over-collecting is nil here: everything this set holds is
    dropped from the provenance graph, and a rule is not a dependency on a
    *layer* whichever of its two names was written.
    """
    found: dict[uuid.UUID, set[str]] = {}
    for system_id, label, name in session.execute(
        select(RuleRow.system_id, RuleRow.label, RuleRow.name)
    ):
        found.setdefault(system_id, set()).update({label, name})
    return found


def _premise_labels(session: Session) -> dict[uuid.UUID, set[str]]:
    """Per promoted theorem, the labels its *own* proof cites its hypotheses by.

    A `$e` is citable only from inside the block that declares it, so it is a
    column on the theorem rather than a library entry — and a proof citing one is
    not depending on any layer. Excluded for the same reason a rule is.
    """
    found: dict[uuid.UUID, set[str]] = {}
    for theorem_id, label in session.execute(
        select(PromotedTheoremPremiseRow.theorem_id, PromotedTheoremPremiseRow.label)
        .where(PromotedTheoremPremiseRow.label.is_not(None))
    ):
        found.setdefault(theorem_id, set()).add(label)
    return found


def _deeper(
    left: uuid.UUID | None, right: uuid.UUID | None, depths: Mapping[uuid.UUID, int]
) -> uuid.UUID | None:
    """Whichever of two systems sits further from its root.

    Meaningful down one spine, which is what a corpus import builds. Across two
    branches of a tree it is arbitrary, and so is only ever a *label* on the
    report — :attr:`Provenance.misfiled` is decided by reachability, not by the
    depth this returns.
    """
    if left is None:
        return right
    if right is None:
        return left
    return left if depths[left] >= depths[right] else right


def _reach(
    proof_id: uuid.UUID,
    depths: Mapping[uuid.UUID, int],
    deps: Mapping[uuid.UUID, Sequence[_Citation]],
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
            for citation in deps.get(current, ()):
                below = citation.entry.proof_id
                if below is not None and below not in open_:
                    stack.append((below, False))
            continue

        cited: uuid.UUID | None = None
        axioms: uuid.UUID | None = None
        labels: set[str] = set()
        debts: set[str] = set()
        unreachable = False
        for citation in deps.get(current, ()):
            entry = citation.entry
            unreachable |= not citation.reachable
            cited = _deeper(cited, entry.system_id, depths)
            if entry.primitive:
                axioms = _deeper(axioms, entry.system_id, depths)
                # Partitioned: a debt is a primitive the report names apart, not
                # a second reading of the same label.
                (debts if entry.assumed else labels).add(entry.label)
            # A missing memo entry is a cycle's back-edge, already on the stack
            # above us. Skipping it is what breaks the loop; the closure it would
            # have contributed is the one being computed here.
            below = memo.get(entry.proof_id) if entry.proof_id is not None else None
            if below is not None:
                cited = _deeper(cited, below.cited, depths)
                axioms = _deeper(axioms, below.axioms, depths)
                labels |= set(below.axiom_labels)
                debts |= set(below.assumed_labels)
                # A cited proof that cannot reach its own dependencies makes this
                # one's provenance unreadable too: the closure it contributes is
                # missing whatever it could not resolve.
                unreachable |= below.unreachable
        memo[current] = _Reach(
            cited,
            axioms,
            tuple(sorted(labels)),
            tuple(sorted(debts)),
            unreachable,
        )
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

    # Ordered, because callers compare whole reports for equality — the "reads no
    # source" assertion here and in `scripts/check_provenance.py` both do. An
    # unordered scan happens to be stable on SQLite's rowid and is not on
    # Postgres, where a bulk UPDATE between two reads reorders the seq scan and
    # the comparison fails for a reason that has nothing to do with the claim
    # (found in review).
    #
    # By `position` rather than by id, since it costs the same and a report a
    # person reads should come back in the order the corpus declares things. The
    # id breaks ties, so the order is total for rows that carry no position of
    # their own (an authored proof rather than an imported one).
    rows = list(
        session.execute(
            select(
                Proof.id, Proof.name, Proof.formal_system_id, Proof.theorem_id
            ).order_by(Proof.position, Proof.id)
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

    # The deepest declarer of each label *within each tree*, for the fallback in
    # `_cited`. Keyed by the root so a rule name shared by two unrelated corpora
    # cannot resolve across them; deepest within the tree because the fallback
    # only runs for a citation no chain reaches, and the finding is how far out
    # of reach it is.
    elsewhere: dict[tuple[uuid.UUID, str], _Entry] = {}
    for entry in library.values():
        key = (chains[entry.system_id][0], entry.label)
        held = elsewhere.get(key)
        if held is None or depths[entry.system_id] > depths[held.system_id]:
            elsewhere[key] = entry

    rules = _rule_labels(session)
    premises = _premise_labels(session)
    deps = {
        proof_id: _cited(
            cited_labels.get(proof_id, ()),
            chains[system_id],
            library,
            elsewhere,
            # What this proof's own chain accounts for without any library entry:
            # a rule any of its systems declares, and the hypotheses of the very
            # theorem it proves.
            {name for system in chains[system_id] for name in rules.get(system, ())}
            | premises.get(theorem_id, set()),
        )
        for proof_id, _, system_id, theorem_id in rows
    }

    # The grammar half, keyed by the *line* rather than the citation: what a
    # proof is written in pins it where its citations may not.
    written_in = _grammar_systems(session, _declared_in(session, chains), depths)
    grammar: dict[uuid.UUID, uuid.UUID] = {}
    for proof_id, term_id in session.execute(
        select(ProofLineRow.proof_id, ProofLineRow.term_id).where(
            ProofLineRow.term_id.is_not(None)
        )
    ):
        system_id = written_in.get(term_id)
        if system_id is not None:
            grammar[proof_id] = _deeper(grammar.get(proof_id), system_id, depths)

    # And the machinery half. A rule and a definition are each a justification
    # the *layer* supplies and no `promoted_theorems` row holds, so `_cited`
    # drops both — correctly, since neither is a citation — and neither was
    # pinning anything until review pointed out that a proof cannot be checked
    # in a layer that does not declare them.
    filed_in = {proof_id: system_id for proof_id, _, system_id, _ in rows}
    machinery: dict[uuid.UUID, uuid.UUID] = {}
    for proof_id, label in session.execute(
        select(ProofLineRow.proof_id, ProofLineRow.rule).where(
            ProofLineRow.rule.is_not(None)
        )
    ):
        # The **shallowest** declaring layer, since that is the shallowest the
        # proof could move to and still resolve the rule — the question this
        # feeds. (`_cited` reads nearest-first instead, because that is what the
        # checker did.)
        for system_id in chains.get(filed_in[proof_id], ()):
            if label in rules.get(system_id, ()):
                machinery[proof_id] = _deeper(
                    machinery.get(proof_id), system_id, depths
                )
                break
    for proof_id, definition_system in session.execute(
        select(ProofLineRow.proof_id, DefinitionRow.system_id).join(
            DefinitionRow, ProofLineRow.definition_id == DefinitionRow.id
        )
    ):
        machinery[proof_id] = _deeper(
            machinery.get(proof_id), definition_system, depths
        )

    memo: dict[uuid.UUID, _Reach] = {}
    found: list[Provenance] = []
    for proof_id, name, system_id, _ in rows:
        reach = _reach(proof_id, depths, deps, memo)
        written, needs = grammar.get(proof_id), machinery.get(proof_id)
        # Machinery its chain does not hold is the same defect an unreachable
        # citation is — the proof does not rebuild where it sits — and saying so
        # only by suppressing `could_be_filed_lower` let a run exit 0 on it.
        chain = chains[system_id]
        stranded = any(
            held is not None and held not in chain for held in (written, needs)
        )
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
                assumes=reach.assumed_labels,
                deepest_grammar=names[written] if written is not None else None,
                grammar_depth=depths[written] if written is not None else None,
                deepest_rule=names[needs] if needs is not None else None,
                rule_depth=depths[needs] if needs is not None else None,
                unreachable=reach.unreachable,
                unreachable_machinery=stranded,
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
        tally = counts.setdefault(
            (report.filed, report.filed_in), [0, 0, 0, 0, 0, 0, 0]
        )
        tally[0] += 1
        # Exhaustive, and in this order: a misfiled proof's axiom depth is not
        # comparable with its own, so it is counted here rather than measured
        # against a chain it is not on.
        if report.misfiled:
            tally[5] += 1
        elif report.axiom_depth is None:
            tally[3] += 1
        elif report.needs_its_own_axioms:
            tally[1] += 1
        else:
            tally[2] += 1
        if report.depends_only_on_shallower:
            tally[4] += 1
        if report.could_be_filed_lower:
            tally[6] += 1
    return tuple(
        LayerProvenance(
            name=name,
            depth=depth,
            proofs=tally[0],
            own_axioms=tally[1],
            lower_axioms=tally[2],
            no_axioms=tally[3],
            only_shallower=tally[4],
            could_be_lower=tally[6],
            misfiled=tally[5],
        )
        for (depth, name), tally in sorted(counts.items())
    )
