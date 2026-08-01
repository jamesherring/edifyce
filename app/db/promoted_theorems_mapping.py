"""Round trip between a system's citable library and its rows.

``store_theorem`` writes one promoted theorem — its statement, premises,
metavariables and provisos, plus the composed terms a build would otherwise have
to parse for. ``load_theorems`` reads back **only the labels asked for** and
promotes them against a compiled system.

**Loading is by label, never wholesale.** That is the difference between this and
every other mapping here. A system's grammar, rules and definitions are loaded
entire because a system has a bounded number of each; its library is not bounded —
set.mm contributes 49,000 theorems — and promoting one costs a parse of its
statement against the grammar. So a verify collects the labels its proof actually
cites and loads those, exactly as P1 loads the lemmas a proof references rather
than every proof in the system.

**The terms are a cache; the strings are the record.** A theorem is rebuilt from
its stored text whatever happens, and the stored statement/premise terms only let
that rebuild skip the parse. ``schema_digest`` says whether they still describe
the system, on the same contract as ``app/db/schema_terms.py``: a NULL or a stale
digest is a *miss*, which costs a parse and never a difference.

See docs/verification-from-rows.md, P4.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, or_, select
from sqlalchemy.orm import Session

from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import build_theorem_side_conditions, proviso_lines
from app.db.systems import SymbolRow
from app.db.terms_mapping import prefetch_terms, store_term
from website.logical.matching import StringPattern
from website.logical.promotion import TheoremSpec, promote_spec

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from sqlalchemy import Select

    from app.db.models import FormalSystem
    from app.db.terms_mapping import TermGraph
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system import PromotedTheorem
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context
    from website.logical.matching.patterns import Pattern


def theorem_digest(library: str, spec: TheoremSpec) -> str:
    """What determines the terms ``spec``'s statement and premises compose to.

    ``library`` is :func:`~website.logical.declarative.library_digest` — the
    system half, computed once for a whole import or verify. This adds the
    theorem's own half: its statement, its premises, and the metavariables that
    decide which of their tokens are schematic rather than literal.

    Its *label* is absent, and its provisos are too: neither reaches the parse
    that composes the terms, so a renamed or re-constrained theorem keeps them.
    """
    return hashlib.sha256(
        json.dumps(
            [
                library,
                spec.statement,
                list(spec.premises),
                sorted(spec.metavariables.items()),
                spec.matching,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


def store_theorem(
    session: Session,
    system: FormalSystem,
    spec: TheoremSpec,
    symbols: Mapping[str, SymbolRow],
    *,
    position: int,
    primitive: bool,
    digest: str | None = None,
    promoted: PromotedTheorem | None = None,
    premise_labels: Sequence[str] = (),
) -> PromotedTheoremRow:
    """Write one promoted theorem's rows and return them (unsaved).

    ``symbols`` resolves a metavariable's sort name to its symbol row; the caller
    holds it because a library import resolves the same handful of sorts tens of
    thousands of times. ``promoted`` is the engine object the caller already
    built, whose composed terms are cached beside the text — omit it and the
    theorem stores its strings alone, which a later load then parses.
    ``digest`` must be :func:`theorem_digest` for ``spec``, and is required
    whenever ``promoted`` is given: it is what says the cached terms are current.
    ``premise_labels`` names each premise as the theorem's *own proof* cites it
    (a Metamath ``$e`` label), positionally; see
    :class:`~app.db.promoted_theorems.PromotedTheoremPremiseRow.label`.
    """
    if promoted is not None and digest is None:
        raise ValueError(
            "store_theorem needs the digest that guards the terms it is caching."
        )

    row = PromotedTheoremRow(
        system_id=system.id,
        position=position,
        label=spec.label,
        statement=spec.statement,
        primitive=primitive,
        matching=spec.matching,
        schema_digest=digest if promoted is not None else None,
        statement_term_id=(
            None if promoted is None
            else _term_id(session, system, promoted.deduction)
        ),
    )
    for index, premise in enumerate(spec.premises):
        row.premises.append(
            PromotedTheoremPremiseRow(
                position=index,
                statement=premise,
                label=(
                    premise_labels[index]
                    if index < len(premise_labels) else None
                ),
                term_id=(
                    None
                    if promoted is None or index >= len(promoted.antecedents)
                    else _term_id(session, system, promoted.antecedents[index])
                ),
            )
        )
    for index, (var, sort) in enumerate(spec.metavariables.items()):
        symbol = symbols.get(sort)
        if symbol is None:
            raise LookupError(
                f"Theorem {spec.label!r} binds {var!r} to sort {sort!r}, which the "
                "system declares no symbol for."
            )
        row.bindings.append(
            PromotedTheoremBindingRow(position=index, var=var, symbol=symbol)
        )

    build_theorem_side_conditions(
        row, list(spec.distinct), symbols, set(spec.metavariables)
    )
    session.add(row)
    return row


def _term_id(
    session: Session, system: FormalSystem, pattern: Pattern | None
) -> uuid.UUID | None:
    # Only a `StringPattern` carries a composed term; a schema that resolved to a
    # declared grammar pattern has none and needs none (see schema_terms._term_id
    # for the same reasoning on the rule side).
    if not isinstance(pattern, StringPattern) or pattern.schema_term is None:
        return None
    stored = store_term(session, system, pattern.schema_term)
    if stored.id is None:
        session.flush()
    return stored.id


@dataclass(frozen=True)
class _Premise:
    """One ``promoted_theorem_premises`` row as flat data."""

    statement: str
    label: str | None
    term_id: uuid.UUID | None


@dataclass(frozen=True)
class _Proviso:
    """One of a theorem's ``side_conditions`` rows, its sort already named.

    Satisfies :class:`~app.db.side_conditions_mapping.ProvisoNode`, which is what
    lets the renderer read this and an ORM row alike.
    """

    id: uuid.UUID
    parent_id: uuid.UUID | None
    position: int
    kind: str
    left_name: str | None
    right_name: str | None
    sort_name: str | None


@dataclass(frozen=True)
class StoredTheorem:
    """One library entry as flat data — no ORM instance, no identity map.

    A theorem is read to be promoted and never written back, so hydrating four
    tables into an object graph buys nothing: the instrumented attributes are
    never assigned to, the identity map is never consulted twice, and the unit of
    work has nothing to flush. Reading it as Core rows was 36% of a re-check
    (docs/verification-from-rows.md, P2a) and is the same argument that moved
    term rows off the ORM — see :class:`~app.db.terms_mapping.TermGraph`, which
    also records why *holding* the rows stops being something a caller can get
    wrong.
    """

    id: uuid.UUID
    # Which system's library this entry belongs to — its own or an ancestor's.
    # What says whose digest guards its cached terms, and how near it is when two
    # systems of one chain share a label (see :class:`LibraryChain`).
    system_id: uuid.UUID
    label: str
    statement: str
    matching: str
    statement_term_id: uuid.UUID | None
    schema_digest: str | None
    premises: tuple[_Premise, ...]
    metavariables: tuple[tuple[str, str], ...]
    provisos: tuple[_Proviso, ...]

    @property
    def term_ids(self) -> list[uuid.UUID]:
        """Every cached term this entry names, for seeding one sweep."""
        return [
            term_id
            for term_id in (
                self.statement_term_id,
                *(premise.term_id for premise in self.premises),
            )
            if term_id is not None
        ]


def theorem_spec(theorem: StoredTheorem) -> TheoremSpec:
    """The declarative form a stored theorem round-trips to.

    Named for what it takes now: a :class:`StoredTheorem` rather than an ORM row,
    so the whole read path from query to `TheoremSpec` touches no instrumented
    attribute.
    """
    return TheoremSpec(
        label=theorem.label,
        statement=theorem.statement,
        metavariables=dict(theorem.metavariables),
        premises=tuple(premise.statement for premise in theorem.premises),
        distinct=tuple(proviso_lines(theorem.provisos)),
        matching=theorem.matching,
    )


@dataclass(frozen=True)
class LibraryChain:
    """Where a citation may resolve, and what guards each system's stored terms.

    A system's library is its own entries **and its ancestors'** — that is what
    makes a theorem proved in propositional calculus citable in a proof written
    in ZFC (docs/system-relationships-roadmap.md §5.2). ``layers`` is the
    inheritance chain **nearest first**, so a label declared twice resolves to
    the closest system that has it; an ancestor's entry is shadowed, never
    ambiguous.

    Each layer carries its **own** ``library_digest``, and that is the subtle
    part. A stored term is guarded by the digest of the system it was composed
    against, which for an ancestor's entry is the *ancestor's*, not the citing
    system's. Checking it against the child's would miss every time and re-parse
    every cross-layer citation — and the re-parse would be the *worse* answer:
    the ancestor composed its statement against the grammar it was proved in,
    while the child's is wider, so re-composing can read the statement through
    notation declared later. That is the same argument this module's docstring
    makes for an imported corpus, where the union grammar is the approximation
    and the stored term is the faithful one.

    An ancestor is frozen (a parent must be published before a child may build on
    it), so its digest does not move and a cross-layer citation reliably hits.
    """

    layers: tuple[tuple[uuid.UUID, str], ...]

    @classmethod
    def of(cls, system_id: uuid.UUID, library: str) -> LibraryChain:
        """The one-system case — a system that inherits from nothing."""
        return cls(((system_id, library),))

    @property
    def system_ids(self) -> list[uuid.UUID]:
        return [system_id for system_id, _ in self.layers]

    def rank(self, system_id: uuid.UUID) -> int:
        """How near ``system_id`` is; lower wins a label."""
        return self._layer(system_id)[0]

    def digest(self, system_id: uuid.UUID) -> str:
        """The digest guarding ``system_id``'s own stored terms."""
        return self._layer(system_id)[1]

    def _layer(self, system_id: uuid.UUID) -> tuple[int, str]:
        # Raised rather than defaulted. Every entry comes from a query over
        # `system_ids`, so a system not in the chain is a mis-wired chain rather
        # than a case to tolerate — and tolerating it would substitute a digest
        # that matches nothing, turning the defect into a silent re-parse, which
        # is the *wrong* answer for a cross-layer citation and not merely a
        # slower one (see this class's own note).
        for index, (candidate, library) in enumerate(self.layers):
            if candidate == system_id:
                return index, library
        raise LookupError(
            f"Library entry from system {system_id} is outside the chain it was "
            f"read for ({', '.join(str(s) for s, _ in self.layers)})."
        )


@dataclass(frozen=True)
class PendingLibrary:
    """A proof's library, read and digest-checked, waiting only on its terms.

    The half of :func:`load_theorems` that needs a database, split from the half
    that needs a :class:`~app.db.terms_mapping.TermGraph` — because which terms
    it wants is decided *here*, by rows and digests alone, and a caller with a
    sweep of its own can therefore fold this one into it. That is what
    ``load_proof_for_check`` does: a proof's lines and the theorems they cite are
    one sweep rather than two, which is only possible because a citation is a
    plain column and settles the whole question before any term is loaded.

    Nothing here is a verdict. The entries are what the rows say and ``fresh``
    is which of them a build may skip re-parsing; promoting still runs in full.
    """

    cited: tuple[StoredTheorem, ...]
    owner: StoredTheorem | None
    specs: Mapping[str, TheoremSpec]
    # The cited entries whose cached terms still describe the system that owns
    # them. For an entry of the citing system a miss costs a parse and never a
    # difference; for an *inherited* one it is fatal — see :meth:`promote`.
    fresh: Mapping[str, StoredTheorem]
    # The chain the entries were read from, so `promote` can tell an inherited
    # entry from one of the citing system's own.
    chain: LibraryChain = LibraryChain(())

    @property
    def term_ids(self) -> list[uuid.UUID]:
        """Every cached term worth loading — the roots this contributes to a sweep."""
        ids = [term_id for entry in self.fresh.values() for term_id in entry.term_ids]
        if self.owner is not None:
            # A hypothesis's term is guarded by nothing of its own — it is the
            # owner's premise, and the owner's digest is what says whether the
            # owner's terms are current.
            ids += [p.term_id for p in self.owner.premises if p.term_id is not None]
        return ids

    def promote(
        self, built: EngineSystem, context: Context, graph: TermGraph
    ) -> dict[str, PromotedTheorem]:
        """Build the citable theorems, taking cached terms from ``graph``.

        ``graph`` need only *contain* :attr:`term_ids`; it may hold anything else
        besides, since a root it does not have is a miss and a miss is a parse.
        That is what lets a caller pass the sweep it did for its own reasons.
        """

        def term(term_id: uuid.UUID | None) -> Term | None:
            return graph.term(term_id, context)

        promoted: dict[str, PromotedTheorem] = {}
        for entry in self.cited:
            current = self.fresh.get(entry.label)
            if current is None and self.chain.rank(entry.system_id) > 0:
                # An *inherited* entry with no usable cached term. Falling back to
                # the parse would compose its statement against the citing
                # system's grammar, which is wider than the one it was proved in —
                # and notation declared later can capture an earlier statement's
                # parse (metamath roadmap §1.4, `bj-0`). The theorem would then
                # mean something its own system never established, and could
                # justify a step that system could not. So this is refused rather
                # than approximated: unlike the same-system fallback, a miss here
                # is a difference and not a cost.
                #
                # Reached only by an entry stored without its terms
                # (`store_theorem(..., promoted=None)`) or one whose own system's
                # grammar has moved — which publishing is supposed to prevent. The
                # citation simply does not resolve, so the proof fails on it.
                raise LookupError(
                    f"Theorem {entry.label!r} is inherited from another system and "
                    "its stored terms are missing or stale, so it cannot be cited "
                    "here: re-reading its statement against this system's grammar "
                    "could give it a different meaning from the one it was proved "
                    "with. Re-verify the system that owns it."
                )
            promoted[entry.label] = promote_spec(
                built,
                self.specs[entry.label],
                statement_term=(
                    None if current is None else term(current.statement_term_id)
                ),
                premise_terms=(
                    () if current is None
                    else [term(premise.term_id) for premise in current.premises]
                ),
            )

        if self.owner is not None:
            promoted.update(_hypotheses(self.owner, built, term))
        return promoted


_NOTHING_PENDING = PendingLibrary(cited=(), owner=None, specs={}, fresh={})


def read_library(
    session: Session,
    chain: LibraryChain,
    labels: Iterable[str],
    hypotheses_of: uuid.UUID | None = None,
) -> PendingLibrary:
    """Read and digest-check everything one proof may cite, without its terms.

    Labels with no row are simply absent: a citation may name a rule, a line of a
    cited proof, or nothing at all, and it is the caller's job to over-collect
    rather than this function's to know which is which.

    ``hypotheses_of`` is the theorem this proof proves, when it proves one. A
    theorem proves *under* its ``$e`` hypotheses and its proof states them as
    lines citing their labels, so re-checking needs them registered — exactly as
    the walk registers them for one check and withdraws them
    (``corpus._givens``). They are reached only through the theorem that owns
    them, which is what keeps a bare ``|- ph`` from being citable by anybody
    else, and each becomes a zero-premise theorem over the owner's
    metavariables. A hypothesis wins a name clash with a cited theorem, matching
    the walk, where `_givens` promotes into the same namespace last.

    Both halves are one call because they are one query and, more to the point,
    one term sweep: done separately they each paid a recursive closure over
    `term_children` and a row fetch, which was a third of a re-check.

    ``chain`` is where a label may resolve and what guards each layer's terms;
    see :class:`LibraryChain` for why an ancestor's entry is checked against the
    ancestor's own digest rather than the citing system's.
    """
    wanted = list(dict.fromkeys(labels))
    if not wanted and hypotheses_of is None:
        return _NOTHING_PENDING

    entries = read_theorems(session, chain.system_ids, wanted, hypotheses_of)
    if not entries:
        return _NOTHING_PENDING

    # The owner is read for *its hypotheses*, not to be citable: a theorem's own
    # statement is what its proof is establishing.
    owner = next((e for e in entries if e.id == hypotheses_of), None)
    asked_for = set(wanted)
    cited = _nearest(chain, (entry for entry in entries if entry.label in asked_for))

    specs = {entry.label: theorem_spec(entry) for entry in cited}
    fresh = {
        entry.label: entry
        for entry in cited
        if entry.schema_digest is not None
        and entry.schema_digest
        == theorem_digest(chain.digest(entry.system_id), specs[entry.label])
    }
    return PendingLibrary(
        cited=cited, owner=owner, specs=specs, fresh=fresh, chain=chain
    )


def _nearest(
    chain: LibraryChain, entries: Iterable[StoredTheorem]
) -> tuple[StoredTheorem, ...]:
    """One entry per label: the nearest system in ``chain`` that has it.

    A label is a citation, and a citation must resolve to exactly one theorem. A
    chain can offer several — a child may prove its own `id` over an ancestor's —
    and the child's is the answer, on the same rule the rest of inheritance
    follows: what the nearer layer says about a name is what that name means.
    Order is otherwise the query's, which is stable for a given ask.
    """
    best: dict[str, StoredTheorem] = {}
    for entry in entries:
        held = best.get(entry.label)
        if held is None or chain.rank(entry.system_id) < chain.rank(held.system_id):
            best[entry.label] = entry
    return tuple(best.values())


def load_theorems(
    session: Session,
    chain: LibraryChain,
    labels: Iterable[str],
    built: EngineSystem,
    context: Context,
    hypotheses_of: uuid.UUID | None = None,
) -> dict[str, PromotedTheorem]:
    """Promote everything one proof may cite, sweeping for its terms as it goes.

    :func:`read_library` then :meth:`PendingLibrary.promote`, with a sweep of
    exactly the terms between them. For the caller that has no sweep of its own
    to share — the *parse* path, whose lines already carry their terms because
    they were just parsed. A caller reading its lines from rows should use the
    two halves and sweep once for both (see ``proofs_mapping``).
    """
    pending = read_library(session, chain, labels, hypotheses_of)
    graph = prefetch_terms(session, pending.term_ids)
    return pending.promote(built, context, graph)


def _hypotheses(
    owner: StoredTheorem,
    built: EngineSystem,
    term: Callable[[uuid.UUID | None], Term | None],
) -> dict[str, PromotedTheorem]:
    # Each labelled premise of `owner`, as the zero-premise theorem `_givens`
    # builds — including its *default* `matching` rather than the owner's.
    # Inheriting would arguably be better, but only arguably: what matters is
    # that a hypothesis promoted from rows and one promoted by the walk are the
    # same object, and a divergence between those two paths is the bug class P2
    # shipped twice.
    metavariables = dict(owner.metavariables)
    return {
        premise.label: promote_spec(
            built,
            TheoremSpec(
                label=premise.label,
                statement=premise.statement,
                metavariables=metavariables,
            ),
            statement_term=term(premise.term_id),
        )
        for premise in owner.premises
        if premise.label is not None
    }


def _statements() -> tuple[Select, Select, Select, Select]:
    """The four library queries, built once — everything varying is bound.

    Constructing a statement is not free, and at four per verify it showed:
    hoisting the term sweep's was worth a third of it (P2a).

    **The children take the ids the first query found**, which is worth being
    explicit about, because the term sweep next door had to stop doing exactly
    that (P2a): an ``IN`` list that grows with the *answer* rather than with the
    ask will eventually pass the driver's parameter limit. It is not the same
    situation here, and the difference is amplification. A sweep's closure is
    unboundedly larger than its roots — 269 nodes from a proof's six, 8,190 from
    a 5,000-theorem library — whereas the ids here are *at most* one per label
    asked for, and that ``IN`` list is already in the first query. So the
    children add no order of magnitude the caller was not already spending: if
    the ids overflow, the labels overflowed first.

    Re-asking instead was tried, and costs 19%: repeating the label lookup three
    more times is dearer than the ids it saves. `selectinload`'s 500-per-query
    chunking was incidental to how it works, not a guarantee this relied on.
    """
    theorems = select(
        PromotedTheoremRow.id,
        PromotedTheoremRow.system_id,
        PromotedTheoremRow.label,
        PromotedTheoremRow.statement,
        PromotedTheoremRow.matching,
        PromotedTheoremRow.statement_term_id,
        PromotedTheoremRow.schema_digest,
    ).where(
        # The whole inheritance chain, not one system: a citation resolves
        # against an ancestor's library too (see `LibraryChain`).
        PromotedTheoremRow.system_id.in_(bindparam("system_ids", expanding=True)),
        or_(
            PromotedTheoremRow.label.in_(bindparam("labels", expanding=True)),
            # `NULL` is the "no owner" case: `id = NULL` is never true, so a
            # caller with no owning theorem needs no second statement. An empty
            # `labels` needs no special case either — an expanding `IN` over
            # nothing renders as a false expression, which is what
            # `load_theorems` means by a proof that cites no library entry.
            # `test_a_degenerate_ask_reads_no_library_at_all` pins both.
            PromotedTheoremRow.id == bindparam("owner"),
        ),
    )
    wanted = bindparam("ids", expanding=True)

    premises = (
        select(
            PromotedTheoremPremiseRow.theorem_id,
            PromotedTheoremPremiseRow.statement,
            PromotedTheoremPremiseRow.label,
            PromotedTheoremPremiseRow.term_id,
        )
        .where(PromotedTheoremPremiseRow.theorem_id.in_(wanted))
        .order_by(
            PromotedTheoremPremiseRow.theorem_id, PromotedTheoremPremiseRow.position
        )
    )

    # The symbol is joined rather than fetched: a binding's sort and a proviso's
    # are *many-to-one*, so each is one more column on a query already being
    # issued rather than a round trip of its own.
    bindings = (
        select(
            PromotedTheoremBindingRow.theorem_id,
            PromotedTheoremBindingRow.var,
            SymbolRow.name,
        )
        .join(SymbolRow, PromotedTheoremBindingRow.symbol_id == SymbolRow.id)
        .where(PromotedTheoremBindingRow.theorem_id.in_(wanted))
        .order_by(
            PromotedTheoremBindingRow.theorem_id, PromotedTheoremBindingRow.position
        )
    )

    provisos = (
        select(
            SideConditionRow.promoted_theorem_id,
            SideConditionRow.id,
            SideConditionRow.parent_id,
            SideConditionRow.position,
            SideConditionRow.kind,
            SideConditionRow.left_name,
            SideConditionRow.right_name,
            SymbolRow.name,
        )
        # Outer: most provisos carry no sort, and one that does not must still be
        # read. An inner join here would silently drop every `occurs`.
        .join(SymbolRow, SideConditionRow.sort_symbol_id == SymbolRow.id, isouter=True)
        .where(SideConditionRow.promoted_theorem_id.in_(wanted))
    )
    return theorems, premises, bindings, provisos


_THEOREMS, _PREMISES, _BINDINGS, _PROVISOS = _statements()


def read_theorems(
    session: Session,
    system_ids: Sequence[uuid.UUID],
    labels: Sequence[str],
    hypotheses_of: uuid.UUID | None = None,
) -> list[StoredTheorem]:
    """Read the named library entries as flat data, in four queries.

    One per table rather than one statement joining all four: a theorem has three
    independent child collections, so a single join would be their cartesian
    product — the reason SQLAlchemy's own `selectinload` issues a query per
    collection. This is the same four queries it issued, without the ORM
    machinery on top of them (see :class:`StoredTheorem`).

    The first query is parameterised by the ask; the three child queries by the
    ids it found — see :func:`_statements` for why that way round, given the term
    sweep next door had to go the other.

    A label with no row is simply absent, which is the contract
    :func:`load_theorems` documents.
    """
    rows = list(
        session.execute(
            _THEOREMS,
            {
                "system_ids": list(system_ids),
                "labels": list(labels),
                "owner": hypotheses_of,
            },
        )
    )
    if not rows:
        return []

    ids = {"ids": [row.id for row in rows]}
    premises: dict[uuid.UUID, list[_Premise]] = {}
    for row in session.execute(_PREMISES, ids):
        premises.setdefault(row.theorem_id, []).append(
            _Premise(statement=row.statement, label=row.label, term_id=row.term_id)
        )

    bindings: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for row in session.execute(_BINDINGS, ids):
        bindings.setdefault(row.theorem_id, []).append((row.var, row.name))

    provisos: dict[uuid.UUID, list[_Proviso]] = {}
    for row in session.execute(_PROVISOS, ids):
        provisos.setdefault(row.promoted_theorem_id, []).append(
            _Proviso(
                id=row.id,
                parent_id=row.parent_id,
                position=row.position,
                kind=row.kind,
                left_name=row.left_name,
                right_name=row.right_name,
                sort_name=row.name,
            )
        )

    return [
        StoredTheorem(
            id=row.id,
            system_id=row.system_id,
            label=row.label,
            statement=row.statement,
            matching=row.matching,
            statement_term_id=row.statement_term_id,
            schema_digest=row.schema_digest,
            premises=tuple(premises.get(row.id, ())),
            metavariables=tuple(bindings.get(row.id, ())),
            provisos=tuple(provisos.get(row.id, ())),
        )
        for row in rows
    ]


def cited_labels(references: Iterable[str | None]) -> list[str]:
    """The theorem labels a set of citation strings could be naming.

    A citation is ``<label>`` or ``<label>, <line>, …`` — but it may equally name
    an inference rule, a definition, or a line of a cited proof, and which it is
    only the resolver knows (``Proof.get_reference``). So this over-collects on
    purpose: a label with no row costs one entry in an ``IN`` clause, while one
    missed costs the citation.
    """
    labels: list[str] = []
    for reference in references:
        if not reference:
            continue
        for candidate in (reference, reference.split(", ", 1)[0]):
            if candidate and candidate not in labels:
                labels.append(candidate)
    return labels
