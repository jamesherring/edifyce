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

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy import CTE, Select

    from app.db.models import FormalSystem
    from website.logical.kernel.constructors import Constructor
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
    """
    digest_memo: dict[int, str] = {}
    root_digest = digest_term(term, digest_memo)

    # One representative Term per digest, in bottom-up (children-first) order.
    postorder: dict[str, Term] = {}

    def collect(t: Term) -> None:
        digest = digest_term(t, digest_memo)
        if digest in postorder:
            return
        if isinstance(t, Node):
            for child in t.children.values():
                collect(child)
        postorder[digest] = t

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

    return rows[root_digest]


@dataclass(frozen=True)
class _TermRow:
    """One ``terms`` row as flat data — no ORM instance, no identity map."""

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
        rows: dict[uuid.UUID, _TermRow],
        children: dict[uuid.UUID, list[tuple[str, uuid.UUID]]],
    ) -> None:
        self._rows = rows
        self._children = children
        # Shared across every root, so a subterm two statements have in common is
        # rebuilt once. Interning means that is the usual case, not the exception.
        self._memo: dict[uuid.UUID, Term] = {}

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def ids(self) -> set[uuid.UUID]:
        """Every row id in the graph — the roots and everything below them."""
        return set(self._rows)

    def term(self, term_id: uuid.UUID | None, context: Context) -> Term | None:
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

        One graph is meant for one context — the memo is keyed by row id alone —
        which holds for every caller, since a build's contexts are copies sharing
        one ``variables``.
        """
        if term_id is None or term_id not in self._rows:
            return None
        return intern(self._build(term_id, context))

    def _build(self, term_id: uuid.UUID, context: Context) -> Term:
        cached = self._memo.get(term_id)
        if cached is not None:
            return cached

        row = self._rows[term_id]
        term: Term
        if row.kind == TERM_KIND_VAR:
            term = Var(row.var_name, _sort_named(row.sort, context))
        elif row.kind == TERM_KIND_BOUND:
            term = Bound(row.bound_index, _sort_named(row.sort, context))
        elif row.kind == TERM_KIND_NODE:
            term = Node(
                constructor=_constructor_named(row.constructor, context),
                children={
                    slot: self._build(child, context)
                    for slot, child in self._children.get(term_id, ())
                },
                literal=row.literal,
                sort=_sort_named(row.sort, context) if row.sort is not None else None,
            )
        else:
            raise ValueError(f"Unknown term row kind: {row.kind!r}")

        self._memo[term_id] = term
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

    rows: dict[uuid.UUID, _TermRow] = {}
    children: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = {}
    for row in session.execute(_SWEEP, {"roots": roots}):
        if row.id not in rows:
            rows[row.id] = _TermRow(
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


def _in_grammar(name: str, context: Context) -> Pattern | None:
    """The grammar pattern called ``name``, found through the sort unions.

    **The authority for a stored constructor name, and consulted before
    ``context.variables``.** That namespace is shared: lines, line parts, axioms
    and the system itself are registered into it *after* the grammar
    (``declarative.build_system`` steps 5 and 6), and a name declared twice
    resolves to the later one. So a production named ``implication`` and an axiom
    of that name leave the axiom's ``LineType`` under the key, and a line *part*
    of that name leaves a ``RegexPattern`` there — which is worse, because it is
    a pattern and so passes for an answer.

    Composing never noticed: it parses against the sort unions, which hold the
    production objects themselves and are indifferent to what the name now means.
    A *stored* term names its constructors by name and comes back through here,
    so before this a system with such a collision verified once and then failed on
    every later verify — with an ``AttributeError`` for the axiom case, and with a
    silently wrong term for the line-part one.

    Searching the unions is not a fallback but the correct lookup: a grammar name
    is unique within a system (``uq_symbols_system_name``), a declared production
    is always a member of its sort's union, and a sort that is included in another
    is a member of that one. Only what nothing includes — a top-level sort — is
    absent here, which is why the callers still fall back to the namespace.
    """
    for candidate in context.variables.values():
        if not isinstance(candidate, UnionPattern):
            continue
        for member in candidate.patterns:
            if isinstance(member, Pattern) and member.name == name:
                return member
    return None


def _in_namespace(name: str, context: Context) -> Pattern | None:
    """What ``name`` denotes in the build namespace, if it denotes a pattern.

    The fallback for what :func:`_in_grammar` cannot see — a top-level sort union,
    which is nobody's member. Still filtered to patterns, so a name bound only by
    a line type or an axiom reads as absent rather than as an answer.
    """
    found = context.variables.get(name)
    return found if isinstance(found, Pattern) else None


def _constructor_named(name: str, context: Context) -> Constructor:
    """The constructor a stored name denotes: a declared production, or the
    defined notation of that name.

    One lookup covers both because a notation's name carries a ``:``, which a
    declared production's name never can (see ``DefinedNotation``) - so the two
    namespaces cannot collide and a row needs no kind to tell them apart.

    Grammar first, then the registered notations, then the build namespace for a
    top-level sort — see :func:`_in_grammar` for why that order and not the
    reverse.
    """
    pattern = _in_grammar(name, context)
    if pattern is None:
        pattern = next(
            (n.template for n in context.definitions if n.template.name == name), None
        )
    if pattern is None:
        pattern = _in_namespace(name, context)
    if pattern is None:
        raise LookupError(f"No production or defined notation named {name!r} in context")
    return constructor_for(pattern)


def _sort_named(name: str, context: Context) -> Constructor:
    """The constructor a stored *sort* name denotes.

    Narrower than :func:`_constructor_named`: a sort is always a declared union of
    the grammar, never an ad-hoc defined form, so a miss is a genuine mismatch
    between the stored rows and the system rather than something to search for.
    Same order and the same reason — a sort name is as shadowable as a
    production's.
    """
    pattern = _in_grammar(name, context) or _in_namespace(name, context)
    if pattern is None:
        raise LookupError(f"No sort named {name!r} in context")
    return constructor_for(pattern)
