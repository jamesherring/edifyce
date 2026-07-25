"""Round trip between kernel :class:`Term` DAGs and the flat term rows.

``store_term`` writes a term into ``terms`` / ``term_children`` rows, interning
by structural digest so equal subterms share one row per system (the relational
mirror of the kernel's hash-consing). ``load_term`` rebuilds a live, interned
kernel term from a stored row, resolving constructor names against a compiled
system's context — the same "rows are canonical, the engine is rebuilt on
demand" contract as :mod:`app.db.systems_mapping`.

Uses a synchronous :class:`~sqlalchemy.orm.Session` (as ``systems_mapping``'s
tests do); the async route wraps it with ``AsyncSession.run_sync`` when a write
path lands.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.terms import (
    TERM_KIND_BOUND,
    TERM_KIND_NODE,
    TERM_KIND_VAR,
    TermChildRow,
    TermRow,
)
from website.logical.kernel import Bound, Node, Term, Var, constructor_for, intern

if TYPE_CHECKING:
    from collections.abc import Callable

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


def load_term(row: TermRow, context: Context) -> Term:
    """Rebuild an interned kernel term from its stored row.

    Constructor names resolve against ``context`` (a compiled system's proof
    context): productions and sorts by name in ``context.variables``, defined
    defined notations by name among ``context.definitions``. An
    unresolvable name raises — a stored term that no longer matches its system
    is data corruption, not something to paper over.
    """
    return intern(_load(row, context, {}))


def _constructor_named(name: str, context: Context) -> Constructor:
    """The constructor a stored name denotes: a declared production, or the
    defined notation of that name.

    One lookup covers both because a notation's name carries a ``:``, which a
    declared production's name never can (see ``DefinedNotation``) - so the two
    namespaces cannot collide and a row needs no kind to tell them apart.
    """
    pattern = context.variables.get(name)
    if pattern is None:
        pattern = next(
            (n.template for n in context.definitions if n.template.name == name), None
        )
    if pattern is None:
        raise LookupError(f"No production or defined notation named {name!r} in context")
    return constructor_for(pattern)


def _load(row: TermRow, context: Context, memo: dict[object, Term]) -> Term:
    key = row.id if row.id is not None else id(row)
    cached = memo.get(key)
    if cached is not None:
        return cached

    term: Term
    if row.kind == TERM_KIND_VAR:
        term = Var(row.var_name, context.variables[row.sort])
    elif row.kind == TERM_KIND_BOUND:
        term = Bound(row.bound_index, context.variables[row.sort])
    elif row.kind == TERM_KIND_NODE:
        term = Node(
            constructor=_constructor_named(row.constructor, context),
            children={
                edge.slot: _load(edge.child, context, memo) for edge in row.children
            },
            literal=row.literal,
            sort=context.variables[row.sort] if row.sort is not None else None,
        )
    else:
        raise ValueError(f"Unknown term row kind: {row.kind!r}")

    memo[key] = term
    return term
