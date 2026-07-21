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
    TERM_KIND_DEFINED,
    TERM_KIND_NODE,
    TERM_KIND_VAR,
    TermChildRow,
    TermRow,
)
from website.logical.kernel import Bound, Node, Term, Var, intern

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from website.logical.matching.context import Context
    from website.logical.matching.patterns import Pattern


def _slot_order(pattern: Pattern, children: dict[str, Term]) -> list[str]:
    """Child slot labels in template (reading) order, deduped per label.

    Any child label absent from the template (not expected, but kept
    deterministic) sorts to the end.
    """
    ordered: list[str] = []
    for offset in sorted(pattern.variable_locations):
        label = pattern.variable_locations[offset]["label"]
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

    if term.sort is not None:
        # A definition-backed node: its constructor is the definition's ad-hoc
        # higher form, which has no name in the system namespace. Store the
        # higher *template* string — the same string as the decomposition's
        # definitions.higher column — and the inhabited sort's name.
        return {
            "kind": TERM_KIND_DEFINED,
            "constructor": term.pattern.pattern,
            "literal": term.literal,
            "sort": term.sort.name,
        }

    if not term.pattern.name:
        raise ValueError(
            f"Cannot store a term whose constructor has no name: {term.pattern!r}"
        )
    return {
        "kind": TERM_KIND_NODE,
        "constructor": term.pattern.name,
        "literal": term.literal,
    }


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


def store_term(session: Session, system: FormalSystem, term: Term) -> TermRow:
    """Persist ``term``'s DAG for ``system`` and return the root's row.

    Interned per system: a subterm whose digest already has a row (from this
    call or an earlier one) is reused, not duplicated — so storage stays a
    shared DAG. New rows are added to ``session`` unflushed.
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
        row = TermRow(formal_system=system, digest=digest, **_row_fields(t))
        if isinstance(t, Node) and t.children:
            for position, slot in enumerate(_slot_order(t.pattern, t.children)):
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
    constructors by higher-template string among ``context.definitions``. An
    unresolvable name raises — a stored term that no longer matches its system
    is data corruption, not something to paper over.
    """
    return intern(_load(row, context, {}))


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
            pattern=context.variables[row.constructor],
            children={
                edge.slot: _load(edge.child, context, memo) for edge in row.children
            },
            literal=row.literal,
        )
    elif row.kind == TERM_KIND_DEFINED:
        # Match on the stored sort too: two definitions may share a higher
        # template across different sorts, and context.definitions is a set,
        # so template alone would pick one arbitrarily.
        definition = next(
            (
                defn
                for defn in context.definitions
                if defn.higher.pattern == row.constructor
                and defn.pattern.name == row.sort
            ),
            None,
        )
        if definition is None:
            raise LookupError(
                f"No definition of {row.sort!r} with higher form "
                f"{row.constructor!r} in context"
            )
        term = Node(
            pattern=definition.higher,
            children={
                edge.slot: _load(edge.child, context, memo) for edge in row.children
            },
            literal=row.literal,
            sort=definition.pattern,
        )
    else:
        raise ValueError(f"Unknown term row kind: {row.kind!r}")

    memo[key] = term
    return term
