"""Round trip between kernel :class:`Term` DAGs and the flat term rows.

``store_term`` writes a term into ``terms`` / ``term_children`` rows, interning
by structural digest so equal subterms share one row per system (the relational
mirror of the kernel's hash-consing). ``prefetch_terms`` reads them back as a
:class:`TermGraph`, which rebuilds live, interned kernel terms on demand,
resolving constructor names against a compiled system's context — the same "rows
are canonical, the engine is rebuilt on demand" contract as
:mod:`app.db.systems_mapping`.

Uses a synchronous :class:`~sqlalchemy.orm.Session` (as ``systems_mapping``'s
tests do); the async route wraps it with ``AsyncSession.run_sync`` when a write
path lands.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, or_, select
from sqlalchemy.orm import Session

from app.db.terms import (
    TERM_KIND_BOUND,
    TERM_KIND_NODE,
    TERM_KIND_VAR,
    TermChildRow,
    TermRow,
)
from website.logical.kernel import Bound, Node, Term, Var, constructor_for, intern
from website.logical.matching import Pattern, UnionPattern
from website.logical.translation import IDENTITY, Translation

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence

    from sqlalchemy import CTE, Select

    from app.db.models import FormalSystem
    from website.logical.kernel.constructors import Constructor
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.matching.context import Context

    # Decides whether a leaf is a renameable free variable, and if so its
    # identity (see _free_identity). Callers pass one to alpha_digest/store_term
    # to override the default regex-leaf heuristic per system.
    FreeIdentity = Callable[[Term], "tuple[str, ...] | None"]


def _slot_order(constructor: Constructor, children: dict[str, Term]) -> list[str]:
    """Child slot labels in template (reading) order, deduped per label.

    Any child label absent from the template (not expected, but kept
    deterministic) sorts to the end.
    """
    ordered: list[str] = []
    for label in constructor.slots:
        if label in children and label not in ordered:
            ordered.append(label)
    ordered.extend(sorted(label for label in children if label not in ordered))
    return ordered


def _row_fields(term: Term) -> dict[str, str | int | None]:
    """The storable identity of one term node (everything except its edges)."""
    if isinstance(term, Bound):
        return {
            "kind": TERM_KIND_BOUND,
            "bound_index": term.index,
            "sort": term.sort.name,
        }
    if isinstance(term, Var):
        return {"kind": TERM_KIND_VAR, "var_name": term.name, "sort": term.sort.name}
    if not isinstance(term, Node):
        raise TypeError(f"Unsupported term kind: {type(term).__name__}")

    if not term.constructor.name:
        raise ValueError(
            f"Cannot store a term whose constructor has no name: {term.constructor!r}"
        )

    fields: dict[str, str | int | None] = {
        "kind": TERM_KIND_NODE,
        "constructor": term.constructor.name,
        "literal": term.literal,
    }
    if term.sort is not None:
        # The constructor is not itself a member of the sort it inhabits - a
        # defined form, whose template is an ad-hoc production no union lists.
        # Record the sort so admission still resolves on the way back.
        fields["sort"] = term.sort.name
    return fields


def digest_term(term: Term, _memo: dict[int, str] | None = None) -> str:
    """A structural sha256 for interning rows: equal storable structure, equal
    digest. Computed over the row fields plus child digests keyed by slot, so
    it is independent of Python object identity and of template internals."""
    if _memo is None:
        _memo = {}
    cached = _memo.get(id(term))
    if cached is not None:
        return cached

    fields = _row_fields(term)
    edges = (
        sorted(
            (slot, digest_term(child, _memo))
            for slot, child in term.children.items()
        )
        if isinstance(term, Node)
        else []
    )
    canon = [
        fields["kind"],
        fields.get("constructor"),
        fields.get("literal"),
        fields.get("sort"),
        fields.get("var_name"),
        fields.get("bound_index"),
        edges,
    ]
    digest = hashlib.sha256(
        json.dumps(canon, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    _memo[id(term)] = digest
    return digest


def _free_identity(term: Term) -> tuple[str, ...] | None:
    """The renameable identity of a free-variable leaf, or ``None``.

    Two leaf shapes are treated as free (renameable) variables:

    * a kernel :class:`Var` — a schematic metavariable (``p``, ``x``); and
    * a *regex-leaf* :class:`Node` — an object-language variable token like the
      ``a`` in ``a ∈ b``, which parses to ``Node(<variable regex>, literal="a")``
      rather than a ``Var``.

    A :class:`Bound` is already index-canonical (De Bruijn), so it is not free
    here; constant atoms, compound nodes and defined nodes are fixed structure.
    The returned tuple's last element is the variable's *name* (forgotten by the
    canonical form); its prefix is the variable's *class* (its sort/production),
    which is preserved so a ``formula`` variable never collapses onto a ``term``
    one.

    Note the regex-leaf rule is a heuristic: it assumes a ``matches <regex>``
    production denotes variables, true for every current system but wrong for a
    regex that spells constants (e.g. numerals). A context-aware policy can
    refine this when such a system appears; it would only change which leaves
    are renamed, not the surrounding canonicalisation.
    """
    if isinstance(term, Bound):
        return None
    if isinstance(term, Var):
        return ("var", term.sort.name, term.name)
    if (
        isinstance(term, Node)
        and not term.children
        and term.literal is not None
        and term.constructor.kind == "regex"
    ):
        return ("leaf", term.constructor.name, term.literal)
    return None


def _assign_free_indices(
    term: Term,
    resolve: FreeIdentity,
    numbering: dict[tuple[str, ...], int],
    visited: set[int],
) -> None:
    # Number distinct free variables by first occurrence in a fixed template-order
    # pre-order walk. Memoised over the shared DAG (`visited`): a subterm reachable
    # by many paths is descended once — without this a heavily-shared term DAG
    # would expand exponentially. Skipping an already-visited node never drops a
    # variable's *first* occurrence: every variable it contains was numbered when
    # the node was first reached, so a later, shallower path cannot precede it.
    if id(term) in visited:
        return
    visited.add(id(term))
    identity = resolve(term)
    if identity is not None:
        numbering.setdefault(identity, len(numbering))
        return
    if isinstance(term, Node) and term.children:
        for slot in _slot_order(term.constructor, term.children):
            _assign_free_indices(term.children[slot], resolve, numbering, visited)


def _alpha_hash(
    term: Term,
    resolve: FreeIdentity,
    numbering: dict[tuple[str, ...], int],
    memo: dict[int, str],
) -> str:
    # A per-node sha256 whose canon embeds the *child hashes* (fixed-size), not
    # the children's full structure — a Merkle hash, exactly as digest_term. This
    # is what keeps it O(distinct subterms): a shared canon of full structures
    # would serialise exponentially under json.dumps. Free variables carry their
    # pre-assigned first-occurrence index (name forgotten, class kept); the
    # numbering is fixed before this runs, so a shared subterm's hash is
    # position-independent and the id-memo is valid. Field extraction mirrors
    # digest_term via _row_fields; keep the two consistent.
    cached = memo.get(id(term))
    if cached is not None:
        return cached

    identity = resolve(term)
    if identity is not None:
        # identity[:-1] is the class (sort/production); the name is dropped. json
        # renders the tuple as an array, so no list() wrapper is needed.
        canon: list = ["free", identity[:-1], numbering[identity]]
    elif isinstance(term, Bound):
        canon = ["bound", term.index, term.sort.name]
    elif isinstance(term, Node):
        fields = _row_fields(term)
        # A ground leaf (no children) has no slots to order — and its pattern may
        # be a Regex/Atom with no `variable_locations`, so guard as store_term does.
        child_hashes = (
            [
                [slot, _alpha_hash(term.children[slot], resolve, numbering, memo)]
                for slot in _slot_order(term.constructor, term.children)
            ]
            if term.children
            else []
        )
        canon = [
            "node",
            fields["kind"],
            fields.get("constructor"),
            fields.get("literal"),
            fields.get("sort"),
            child_hashes,
        ]
    else:
        raise TypeError(f"Unsupported term kind: {type(term).__name__}")

    digest = hashlib.sha256(
        json.dumps(canon, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    memo[id(term)] = digest
    return digest


def alpha_digest(term: Term, is_free: FreeIdentity | None = None) -> str:
    """A structural sha256 invariant under consistent renaming of free variables.

    Unlike :func:`digest_term` (which keys leaves by their exact name, so
    ``a ∈ b`` and ``y ∈ z`` differ), this numbers every free variable by first
    occurrence, so terms equal *up to a bijective renaming* share one digest —
    the substrate for "same statement up to variable names" search. Variable
    *sharing* is preserved (``a ∈ a`` and ``a ∈ b`` still differ), and bound
    variables carried as :class:`Bound` are already index-canonical.

    Which leaves count as free variables is decided by ``is_free`` (default
    :func:`_free_identity`): pass a custom resolver to override the regex-leaf
    heuristic for a system whose ``matches`` productions denote constants (e.g.
    numerals) rather than variables.

    Two memoised passes over the shared DAG: number the free variables
    (:func:`_assign_free_indices`), then compose a Merkle hash bottom-up
    (:func:`_alpha_hash`). Both are ``O(distinct subterms)``, so a heavily-shared
    term — which the naive whole-structure serialisation blew up exponentially —
    stays linear.
    """
    resolve = is_free if is_free is not None else _free_identity
    numbering: dict[tuple[str, ...], int] = {}
    _assign_free_indices(term, resolve, numbering, set())
    return _alpha_hash(term, resolve, numbering, {})


def store_term(
    session: Session,
    system: FormalSystem,
    term: Term,
    is_free: FreeIdentity | None = None,
) -> TermRow:
    """Persist ``term``'s DAG for ``system`` and return the root's row.

    Interned per system: a subterm whose digest already has a row (from this
    call or an earlier one) is reused, not duplicated — so storage stays a
    shared DAG. New rows are added to ``session`` unflushed.

    Each new row also gets its ``alpha_digest`` (see :func:`alpha_digest`);
    ``is_free`` overrides which leaves are treated as renameable variables.
    Computing it per row is ``O(rows × subterm)``; bounded and fine for
    statement-sized terms, and the alternative — root-only — is available if a
    profile ever shows it matters (subterm α-search would then need a backfill).

    One term, one lookup. A caller with several in hand should use
    :func:`store_terms` instead — the lookup is a round trip, and it is the same
    round trip whether it asks about one digest or a hundred.
    """
    return store_terms(session, system, [term], is_free)[0]


def store_terms(
    session: Session,
    system: FormalSystem,
    terms: Sequence[Term],
    is_free: FreeIdentity | None = None,
) -> list[TermRow]:
    """Persist several terms' DAGs at once, returning a row per term in order.

    Identical to :func:`store_term` in what it writes; the difference is that the
    "which of these digests do we already have" question is asked **once** for the
    whole set rather than once per term. That question is a `SELECT`, and a
    `SELECT` is a round trip, so an import storing a proof's lines one at a time
    pays one per line for an answer that is the same size either way.

    The interning itself is unchanged and has to be: a subterm shared between two
    of ``terms`` must still resolve to one row, which it does because they are
    collected into a single digest-keyed postorder before anything is created.
    """
    digest_memo: dict[int, str] = {}

    # One representative Term per digest, in bottom-up (children-first) order —
    # across every root, so a subterm two of them share is collected once.
    postorder: dict[str, Term] = {}

    def collect(t: Term) -> None:
        digest = digest_term(t, digest_memo)
        if digest in postorder:
            return
        if isinstance(t, Node):
            for child in t.children.values():
                collect(child)
        postorder[digest] = t

    for term in terms:
        collect(term)

    # The dedup lookup needs the system's id, and needs earlier (possibly
    # pending) rows visible: flush an unsaved system so its id exists, and let
    # the session's autoflush push pending term rows before the SELECT. Without
    # this, two store_term calls against an unflushed system would re-create
    # the same digests and trip the unique index at commit.
    session.add(system)
    if system.id is None:
        session.flush()
    rows: dict[str, TermRow] = {
        row.digest: row
        for row in session.scalars(
            select(TermRow).where(
                TermRow.formal_system_id == system.id,
                TermRow.digest.in_(postorder),
            )
        )
    }

    for digest, t in postorder.items():
        if digest in rows:
            continue
        row = TermRow(
            formal_system=system,
            digest=digest,
            alpha_digest=alpha_digest(t, is_free),
            **_row_fields(t),
        )
        if isinstance(t, Node) and t.children:
            for position, slot in enumerate(_slot_order(t.constructor, t.children)):
                row.children.append(
                    TermChildRow(
                        slot=slot,
                        position=position,
                        child=rows[digest_term(t.children[slot], digest_memo)],
                    )
                )
        session.add(row)
        rows[digest] = row

    return [rows[digest_term(term, digest_memo)] for term in terms]


@dataclass(frozen=True)
class StoredTerm:
    """One ``terms`` row as flat data — no ORM instance, no identity map.

    Public because a reader that only wants to *display* a term walks these rows
    directly rather than rebuilding kernel terms (see
    :func:`app.db.notations_mapping.render_stored`), and rebuilding needs a system.
    """

    kind: str
    constructor: str | None
    literal: str | None
    sort: str | None
    var_name: str | None
    bound_index: int | None


class TermGraph:
    """Every stored row reachable from a set of roots, ready to rebuild terms.

    Read as **Core rows rather than ORM instances**, which is two things at once.
    It is faster — hydrating a `TermRow` object graph and walking its
    relationships was the bulk of what a check spent on terms, and none of that
    machinery earns its keep for data that is immutable, never written back and
    read once.

    And it removes a hazard rather than documenting it. The ORM version handed
    back instances the caller had to *keep alive*, because a session's identity
    map holds weak references: a row nothing referred to was collected, and the
    lookup that was meant to hit memory went back to the database — silently
    slower, or a greenlet error outside the session. That caught this codebase
    three times (P1, P3, P4). Flat rows in a plain dict cannot be collected out
    from under a caller, so the rule no longer exists to be broken.
    """

    def __init__(
        self,
        rows: dict[uuid.UUID, StoredTerm],
        children: dict[uuid.UUID, list[tuple[str, uuid.UUID]]],
    ) -> None:
        self._rows = rows
        self._children = children
        # Shared across every root, so a subterm two statements have in common is
        # rebuilt once. Interning means that is the usual case, not the exception.
        # Keyed by the translation too, because one graph is read for a whole
        # chain and two of its layers can rename the same row differently (see
        # `Translation.key`, whose identity value is empty — an unrenamed chain
        # memoises exactly as it did before).
        self._memo: dict[tuple[str, uuid.UUID], Term] = {}
        # Name -> grammar pattern, built once on first use. A stored constructor
        # cannot be resolved through `context.variables` alone (see `_grammar_of`),
        # and the alternative — searching the sort unions per node — is O(grammar)
        # on a path that runs once per *node*: 68x a dict lookup at 400
        # productions, and set.mm declares 1,441. This is the same lesson
        # `build_context._GrammarIndex` records for the build side.
        self._grammar: dict[str, Pattern] | None = None

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def ids(self) -> set[uuid.UUID]:
        """Every row id in the graph — the roots and everything below them."""
        return set(self._rows)

    def node(self, term_id: uuid.UUID) -> StoredTerm | None:
        """The stored row for ``term_id``, or ``None`` if the sweep did not find it.

        The rows themselves, for a caller that wants the stored shape rather than
        a rebuilt term — rendering, which needs no grammar and should not pay for
        one. Everything that *checks* goes through :meth:`term`.
        """
        return self._rows.get(term_id)

    def children_of(self, term_id: uuid.UUID) -> tuple[tuple[str, uuid.UUID], ...]:
        """``(slot, child id)`` edges below ``term_id``, in stored order."""
        return tuple(self._children.get(term_id, ()))

    def term(
        self,
        term_id: uuid.UUID | None,
        context: Context,
        translation: Translation = IDENTITY,
    ) -> Term | None:
        """Rebuild the term rooted at ``term_id``, or ``None`` if it is not here.

        ``None`` back is not an error: a nullable term reference means "nothing
        stored", and a root the sweep did not find means the row is gone. Both
        are misses for the caller to handle, which is what every caller of this
        wants (see app/db/schema_terms.py for the contract).

        Constructor names resolve against ``context`` (a compiled system's proof
        context): productions and sorts by name in ``context.variables``, defined
        notations by name among ``context.definitions``. An unresolvable name
        *raises* — a stored term that no longer matches its system is data
        corruption, not something to paper over, and the digest guards above this
        are what decide whether a term is current.

        ``translation`` renames each stored name before it is looked up, which is
        the whole of a term-level constructor remap: a theorem proved in a system
        that calls the sort ``prop`` rebuilds here over *this* system's ``wff``,
        against its constructors and its slot sorts (R4b of
        docs/system-relationships-roadmap.md). Absent, nothing is renamed and
        this is the read it always was.

        One graph is meant for one context — the grammar index
        (:meth:`_grammar_of`) is built from the first context handed in — which
        holds for every caller, since a build's contexts are copies sharing one
        ``variables``. Several *translations* of that one context are fine, and
        the memo distinguishes them.
        """
        if term_id is None or term_id not in self._rows:
            return None
        return intern(self._build(term_id, context, translation))

    def _grammar_of(self, context: Context) -> dict[str, Pattern]:
        """``name -> grammar pattern`` for ``context``, built once per graph.

        Why the grammar and not ``context.variables``: that namespace is shared
        with lines, line parts, axioms and the system itself, which are registered
        into it *after* the productions (``declarative.build_system`` steps 5 and
        6), and a name declared twice resolves to the later one. A production
        named ``implication`` and an axiom of that name leave the axiom's
        ``LineType`` under the key; a line *part* of that name leaves a
        ``RegexPattern``, which is worse, because it is a pattern and so passes
        for an answer.

        Composing never noticed — it parses against the sort unions, which hold
        the production objects themselves. A stored term names its constructors by
        name and comes back through here, so before this a system with such a
        collision verified once and then failed on every later verify: an
        ``AttributeError`` for the axiom case, a silently wrong term for the
        line-part one.

        The unions are the authority: a grammar name is unique within a system
        (``uq_symbols_system_name``), a declared production is always a member of
        its sort's union, and a sort included in another is a member of that one.
        Built here rather than looked up per node because it is O(grammar) and
        ``_build`` runs per node — the mistake ``build_context._GrammarIndex``
        already records. One graph is one context, so one index serves it.
        """
        if self._grammar is None:
            grammar: dict[str, Pattern] = {}
            for candidate in context.variables.values():
                if not isinstance(candidate, UnionPattern):
                    continue
                for member in candidate.patterns:
                    if isinstance(member, Pattern):
                        grammar.setdefault(member.name, member)
            self._grammar = grammar
        return self._grammar

    def _constructor(
        self, name: str, context: Context, translation: Translation
    ) -> Constructor:
        """The constructor a stored ``name`` denotes: a production, or a notation.

        One lookup covers both because a notation's name carries a ``:``, which a
        declared production's name never can (see ``DefinedNotation``) — so the
        two namespaces cannot collide and a row needs no kind to tell them apart.

        Grammar first, then the registered notations, then the build namespace for
        a top-level sort — which is the one grammar pattern no union contains.
        """
        name = translation.name(name)
        pattern = self._grammar_of(context).get(name)
        if pattern is None:
            pattern = next(
                (n.template for n in context.definitions if n.template.name == name),
                None,
            )
        if pattern is None:
            pattern = _in_namespace(name, context)
        if pattern is None:
            raise LookupError(
                f"No production or defined notation named {name!r} in context"
            )
        return constructor_for(pattern)

    def _sort(
        self, name: str, context: Context, translation: Translation
    ) -> Constructor:
        """The constructor a stored *sort* name denotes.

        Narrower than :meth:`_constructor`: a sort is always a declared union of
        the grammar, never an ad-hoc defined form, so a miss is a genuine mismatch
        between the stored rows and the system rather than something to search
        for. Same order and the same reason — a sort name is as shadowable as a
        production's.
        """
        name = translation.name(name)
        pattern = self._grammar_of(context).get(name) or _in_namespace(name, context)
        if pattern is None:
            raise LookupError(f"No sort named {name!r} in context")
        return constructor_for(pattern)

    def _build(
        self, term_id: uuid.UUID, context: Context, translation: Translation
    ) -> Term:
        memo_key = (translation.key, term_id)
        cached = self._memo.get(memo_key)
        if cached is not None:
            return cached

        row = self._rows[term_id]
        term: Term
        if row.kind == TERM_KIND_VAR:
            term = Var(row.var_name, self._sort(row.sort, context, translation))
        elif row.kind == TERM_KIND_BOUND:
            term = Bound(row.bound_index, self._sort(row.sort, context, translation))
        elif row.kind == TERM_KIND_NODE:
            constructor = self._constructor(row.constructor, context, translation)
            term = Node(
                constructor=constructor,
                children={
                    slot: self._build(child, context, translation)
                    for slot, child in self._children.get(term_id, ())
                },
                literal=_literal(row, constructor),
                sort=(
                    self._sort(row.sort, context, translation)
                    if row.sort is not None
                    else None
                ),
            )
        else:
            raise ValueError(f"Unknown term row kind: {row.kind!r}")

        self._memo[memo_key] = term
        return term


def _reachable_edges() -> CTE:
    """The transitive closure of ``term_children`` below an expanding ``roots``.

    Every edge whose parent is reachable from a root — which, since each closure
    node is either a root or something's child, is *every edge of the closure*.
    So this answers both halves of a sweep: the nodes are its ``child_id``s plus
    the roots, and the edges are its rows.

    It carries ``slot`` and ``position`` for that second use. They also widen
    what `union` dedups on, which is the point: a node reaching one child through
    two slots is one reachability fact but two edges, and collapsing them would
    lose a slot.

    `union`, emphatically not `union_all`. A term graph is a DAG with heavy
    sharing — that is what interning is for — and `union_all` enumerates every
    root-to-node *path* rather than every reachable edge, which is exponential in
    depth. Measured on a chain of 21 nodes whose children are shared two ways:
    4,194,302 rows and 2.5 s, against 21 rows and no measurable time. Dedup on
    the wider tuple is still bounded by the number of stored edges, so the shape
    of that guarantee is unchanged.
    """
    columns = (
        TermChildRow.parent_id,
        TermChildRow.child_id,
        TermChildRow.slot,
        TermChildRow.position,
    )
    edges = (
        select(*columns)
        .where(TermChildRow.parent_id.in_(bindparam("roots", expanding=True)))
        .cte("reachable_terms", recursive=True)
    )
    return edges.union(
        select(*columns).join(edges, TermChildRow.parent_id == edges.c.child_id)
    )


def _sweep_statement() -> Select:
    """The whole sweep as one query, built once — the roots are its only parameter.

    Every reachable node left-joined to its edges, so a node comes back once per
    child and a leaf once with nulls. One statement rather than two because the
    closure is the expensive half and this way it is computed once; the repeated
    node columns cost far less than a second evaluation of the CTE.

    Constructing it is not cheap either: a recursive CTE has to have its column
    collection set up before ``edges.c.child_id`` can name one, and that was a
    tenth of a re-check when it happened per call. With the roots bound rather
    than inlined the statement is a constant, so SQLAlchemy compiles it once and
    expands the ``IN`` list at execution.

    Binding *only* the roots is also what keeps the parameter count bounded by
    what the caller asked for rather than by what the closure turns out to be.
    An earlier version passed the closure's parents back as a second ``IN`` list,
    which a large enough graph would have pushed past the driver's parameter
    limit: a 5,000-theorem set.mm slice already sweeps to 8,190 nodes, so the
    whole corpus would clear both Postgres's 65,535 and SQLite's 32,766.

    Ordered by ``position`` within a parent, which is template (reading) order —
    the order ``store_term`` wrote the edges in, and the one a ``Node``'s slot
    dict must carry.
    """
    edges = _reachable_edges()
    return (
        select(
            TermRow.id,
            TermRow.kind,
            TermRow.constructor,
            TermRow.literal,
            TermRow.sort,
            TermRow.var_name,
            TermRow.bound_index,
            TermChildRow.slot,
            TermChildRow.child_id,
        )
        .join(TermChildRow, TermChildRow.parent_id == TermRow.id, isouter=True)
        .where(
            or_(
                TermRow.id.in_(bindparam("roots", expanding=True)),
                TermRow.id.in_(select(edges.c.child_id)),
            )
        )
        .order_by(TermRow.id, TermChildRow.position)
    )


_SWEEP = _sweep_statement()


@dataclass(frozen=True)
class SubgraphNode:
    """One node of a term subgraph, as a reader of the *shape* wants it.

    ``truncated`` says this node has children the walk did not descend into
    (a ``depth`` bound), which is different from having none — a reader must be
    able to tell a leaf from a horizon, or it will believe a formula ended where
    the request did.
    """

    id: uuid.UUID
    row: StoredTerm
    children: tuple[tuple[str, uuid.UUID], ...]
    depth: int
    truncated: bool


def walk_subgraph(
    graph: TermGraph, root: uuid.UUID, depth: int | None = None
) -> list[SubgraphNode]:
    """The nodes reachable from ``root``, breadth-first, each visited once.

    **Once**, which is the whole point: a term is an interned DAG, so a subterm
    two positions share is one node with one id. Emitting it once and letting
    both positions reference it is what lets a caller — a person or a model —
    say "that subterm" instead of restating it. A nested rendering would
    duplicate it and lose exactly the structure sharing the storage exists for.

    ``depth`` bounds how far below the root the walk descends; None is the whole
    subgraph. It bounds the *output* rather than the read: the sweep that built
    ``graph`` already fetched the closure in one query, so a shallow request
    costs the same and simply says less.

    Empty when ``root`` is not in the graph, which is a caller asking about a term
    of another system rather than an error here.
    """
    if graph.node(root) is None:
        return []
    visited: list[tuple[uuid.UUID, StoredTerm, int]] = []
    seen: set[uuid.UUID] = {root}
    frontier: list[tuple[uuid.UUID, int]] = [(root, 0)]
    while frontier:
        term_id, at = frontier.pop(0)
        row = graph.node(term_id)
        if row is None:
            # A dangling edge: the sweep returns a closed set, so this is a
            # defensive skip rather than something a caller can provoke.
            continue
        visited.append((term_id, row, at))
        if depth is not None and at >= depth:
            continue
        for _slot, child in graph.children_of(term_id):
            if child in seen:
                continue
            seen.add(child)
            frontier.append((child, at + 1))

    # `truncated` is decided once the walk is done, against what it *emitted* —
    # not against whether this node was at the horizon. In a DAG a child beyond
    # one node's bound is often reachable within another's and already present,
    # and reporting the response incomplete when it is complete costs a caller a
    # wasted deeper request. `R→A, R→X, A→X` at depth 1 is the case.
    emitted = {term_id for term_id, _row, _at in visited}
    return [
        SubgraphNode(
            id=term_id,
            row=row,
            # Reported whether or not this node was descended into: knowing which
            # slots are missing is what makes a second request targeted.
            children=graph.children_of(term_id),
            depth=at,
            truncated=any(
                child not in emitted for _slot, child in graph.children_of(term_id)
            ),
        )
        for term_id, row, at in visited
    ]


def term_digests(
    session: Session, ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None]]:
    """``id -> (digest, alpha_digest)`` for these rows.

    A second query rather than more columns on :class:`StoredTerm`, deliberately.
    The sweep runs on every proof view and every check-from-rows, and the digests
    are needed by neither — widening it would put two more columns per node on
    the hot path to serve a reader that asks for them rarely.
    """
    wanted = list(ids)
    if not wanted:
        return {}
    rows = session.execute(
        select(TermRow.id, TermRow.digest, TermRow.alpha_digest).where(
            TermRow.id.in_(wanted)
        )
    )
    return {row.id: (row.digest, row.alpha_digest) for row in rows}


def term_context(system: EngineSystem) -> Context:
    """The context a *stored* term is rebuilt against, for a compiled system.

    The proof context (which carries the defined notations) plus the build
    context's productions, which is what :meth:`TermGraph.term` resolves a
    constructor name in. Lives here rather than in a router because every caller
    of :func:`prefetch_terms` needs exactly this and there is only one right
    answer.
    """
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return context


def prefetch_terms(session: Session, root_ids: Sequence[uuid.UUID]) -> TermGraph:
    """Read every row reachable from ``root_ids`` in one query.

    Walking the term relationships one node at a time is a query *per node*,
    which made rebuilding a statement cost several times what re-parsing it did
    — the one thing that would have made verifying from rows slower than the
    text path it replaces. So the closure is computed in the database and the
    rows come back flat: one round trip for a whole proof's terms, whatever
    their size or depth.
    """
    roots = list(dict.fromkeys(rid for rid in root_ids if rid is not None))
    if not roots:
        return TermGraph({}, {})

    rows: dict[uuid.UUID, StoredTerm] = {}
    children: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = {}
    for row in session.execute(_SWEEP, {"roots": roots}):
        if row.id not in rows:
            rows[row.id] = StoredTerm(
                kind=row.kind,
                constructor=row.constructor,
                literal=row.literal,
                sort=row.sort,
                var_name=row.var_name,
                bound_index=row.bound_index,
            )
        # Null for a leaf, which the outer join returns exactly once.
        if row.slot is not None:
            children.setdefault(row.id, []).append((row.slot, row.child_id))

    return TermGraph(rows, children)


def _literal(row: StoredTerm, constructor: Constructor) -> str | None:
    """The surface token a rebuilt leaf carries, in *this* system's spelling.

    A **constant** atom's literal is its constructor's value — the production
    names one fixed thing (`⊥`, `∅`) and that thing's spelling is the
    production's, not the term's. So after a rename it has to come from the
    constructor the term was rebuilt over: a translation may send the source's
    `⊥` to a target atom spelled `F` (deliberately — relabelling a constant is
    what an interpretation does), and a node carrying the source's token would
    then render as `⊥` and compare unequal to every `F` the target can write.
    The theorem would apply to nothing at all. Found in review.

    Every **other** leaf's literal is a variable's *name* — a regex token, an
    atom family's member — which is the term's own and which no rename touches,
    so it survives verbatim. Under the identity this is a no-op either way: a
    constant atom's stored literal is the value its constructor already carries.
    """
    if constructor.atom_value is not None:
        return constructor.atom_value
    return row.literal


def _in_namespace(name: str, context: Context) -> Pattern | None:
    """What ``name`` denotes in the build namespace, if it denotes a pattern.

    The fallback for what :meth:`TermGraph._grammar_of` cannot see — a top-level
    sort union, which is nobody's member. Still filtered to patterns, so a name
    bound only by a line type or an axiom reads as absent rather than as an answer.
    """
    found = context.variables.get(name)
    return found if isinstance(found, Pattern) else None


