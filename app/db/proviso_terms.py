"""Round trip between a proviso's term arguments and their stored kernel terms.

A proviso is a closed vocabulary over an owner's metavariables — ``not occurs(x,
phi)``, ``disjoint(x, y, setvar)`` — and all of that is already rows
(``app/db/side_conditions.py``). One thing in it is not: an argument that is *not*
a declared metavariable is a **term expression** parsed against the grammar, and
may use defined notation (``equal(t, ∅)``). That parse is the only grammar read a
proviso makes, and these two functions move it off the read path.

Rare, and deliberately so: no `$d`-derived proviso has one (a Metamath distinct-
variable constraint names variables, which are metavariables), so an imported
corpus stores nothing here. It is the last text-to-term derivation on the build
path all the same.

**The stored term is the raw parse, before abstraction.** Which leaves become
``Var``s depends on the *owner's* metavariables, so an abstracted term would
belong to one rule or definition and would need a per-owner key and a per-owner
guard. The raw parse depends only on the grammar and the notations in scope — one
thing, one digest, shared by every owner, and the abstraction is reapplied per
owner on the way out for nothing (see
``formal_system.side_condition_syntax.ProvisoTerms``). Same rule as
``definition_terms``: store what the parse produced, not what the build did
with it.

**The digest is the definition block's.** ``declarative.definition_digest``
fingerprints the grammar and every definition's forms and bindings, which is
exactly what a term argument parses against. A rule's ``schema_digest`` could not
serve, even for a rule's own proviso: it does not cover the definitions, and
``equal(t, ∅)`` resolves through one.

**A missing term is a miss, never an answer** — the same contract the other two
caches keep, and for the same reason: ``ON DELETE SET NULL`` leaves the identical
NULL behind.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.side_conditions import SideConditionRow
from app.db.terms_mapping import prefetch_terms, store_term
from website.logical.declarative import definition_digest
from website.logical.formal_system.side_condition_syntax import ProvisoTerms

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context


def load_proviso_terms(
    session: Session, system: FormalSystem, spec: SystemSpec
) -> ProvisoTerms:
    """Every usable stored proviso term of ``system``, keyed by argument text.

    ``spec`` must be the one about to be built — the digest is computed from it.
    Always returns a :class:`ProvisoTerms`, holding nothing when nothing stored is
    still current; hand the same one to the build and read its ``derived``
    afterwards.

    Resolution is **deferred**: the rows are swept now, because the build happens
    outside the session, but a stored constructor is turned back into a term only
    when the build asks — which is the first moment a context naming that grammar
    exists at all.
    """
    digest = definition_digest(spec)
    by_text: dict[str, uuid.UUID] = {}
    for row in _proviso_rows(system):
        if row.term_digest != digest:
            continue
        for name, term_id, is_term in (
            (row.left_name, row.left_term_id, row.left_is_term),
            (row.right_name, row.right_term_id, row.right_is_term),
        ):
            if is_term and name is not None and term_id is not None:
                by_text[name] = term_id

    if not by_text:
        return ProvisoTerms()

    graph = prefetch_terms(session, list(by_text.values()))
    present = {text: i for text, i in by_text.items() if i in graph.ids}

    def source(text: str, context: Context) -> Term | None:
        return graph.term(present.get(text), context)

    return ProvisoTerms(source)


def store_proviso_terms(
    session: Session,
    system: FormalSystem,
    built: EngineSystem,
    spec: SystemSpec,
) -> int:
    """Persist the proviso terms ``built`` derived, returning how many rows changed.

    Idempotent once the system has settled: a row already holding the term for its
    argument under the current digest is left alone.

    A row is written only when the build actually *derived* that argument — which
    a warm build does not, having been served it. That is why the digest is
    recomputed here rather than taken from the cache: unlike the other two stores,
    this one is not paired with a load that already holds it, and the cache is a
    plain mapping with nowhere to keep it.
    """
    derived = built.proviso_terms.derived
    if not derived:
        return 0

    digest = definition_digest(spec)
    written = 0
    for row in _proviso_rows(system):
        changed = False
        for side in ("left", "right"):
            if not getattr(row, f"{side}_is_term"):
                continue
            term = derived.get(getattr(row, f"{side}_name"))
            if term is None:
                continue
            stored = store_term(session, system, term)
            if stored.id is None:
                session.flush()
            if getattr(row, f"{side}_term_id") != stored.id:
                setattr(row, f"{side}_term_id", stored.id)
                changed = True
        if changed or (row.term_digest != digest and _has_term(row)):
            row.term_digest = digest
            written += 1
    return written


def _proviso_rows(system: FormalSystem) -> list[SideConditionRow]:
    """Every proviso node of ``system``, whatever owns it.

    Gathered through the owners rather than by a column of their own: a
    ``SideConditionRow`` belongs to a definition, a rule or a promoted theorem and
    reaches the system only through one of them. The cache is keyed by argument
    text and shared across all three, so the owner is not information it needs —
    only the reach is.

    Promoted theorems are **not** included. A library entry's provisos come from a
    Metamath ``$d``, which names variables — metavariables of the theorem, never
    term expressions — so there is nothing here to cache, and reaching them would
    mean loading a library of 50,000 to find it.
    """
    rows: list[SideConditionRow] = []
    for definition in system.definitions:
        rows.extend(definition.side_conditions)
    for rule in system.rules:
        rows.extend(rule.side_conditions)
    return rows


def _has_term(row: SideConditionRow) -> bool:
    return (row.left_is_term and row.left_term_id is not None) or (
        row.right_is_term and row.right_term_id is not None
    )
