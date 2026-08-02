"""Round trip between a definition's two surface forms and their stored terms.

A definition is written as two strings — ``x ⊆ y`` and ``∀z (z ∈ x → z ∈ y)`` —
and the build parses both against the grammar to get the kernel terms an unfold
is checked against (``formal_system.definitions.parse_definition``). These two
functions move that parse off the read path: :func:`store_definition_terms`
writes what a build derived, and :func:`load_definition_terms` hands it back to
the next one. Same shape as ``app/db/schema_terms.py`` does for rule schemas, and
the same two contracts:

**Freshness is decided, not maintained.** A row whose ``term_digest`` no longer
matches is not read, and the build parses as it always did — so an edit needs no
cascade and a stale row is inert rather than believed.

**A missing term is a miss, never an answer.** A NULL is not read as "this form
parses to nothing". It cannot be: the FKs are ``ON DELETE SET NULL``, so the same
NULL is what a swept term leaves behind.

Two things are specific to definitions.

*The digest is per system, not per definition.* ``declarative.definition_digest``
fingerprints the grammar and the **whole ordered definition block**, and every row
carries that one value. A definition's forms are parsed against the grammar as
extended by the definitions before it, so no definition's terms survive another's
edit; and the slot key is a spec position, which an insertion or a reorder moves.

*The stored term stops before binder placement.* What is written is the pair
``parse_definition`` derived and handed to ``record`` — abstracted, but before
``bind``/``bind_scoped`` run. Storing the finished ``Definition.lower`` instead
would round-trip wrong in a way nothing would report: ``bind_scoped`` places one
binder per *ground leaf* sitting in a binder slot, and an already-bound form has
none, so the rebuilt definition would come back with an empty ``fresh`` and
silently lose its capture-avoidance provisos.

See docs/verification-from-rows.md.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.terms_mapping import TermGraph, prefetch_terms, store_term
from website.logical.build_context import DefinitionSlot
from website.logical.declarative import definition_digest

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from app.db.systems import DefinitionRow
    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context


class DefinitionTermCache:
    """The definition-form terms of one system, ready to answer a build.

    Holds flat data rather than ORM rows for the same reason
    :class:`~app.db.schema_terms.SchemaTermCache` does: the build runs outside the
    session, so nothing it asks for could be fetched by the time it asks.

    It also carries the digest it was selected by, which is what pairs it with
    :func:`store_definition_terms` — computing it means fingerprinting the whole
    grammar, and a verify that both reads and writes should do that once.
    """

    def __init__(
        self, digest: str, ids: dict[DefinitionSlot, uuid.UUID], graph: TermGraph
    ) -> None:
        self.digest = digest
        self._ids = ids
        self._graph = graph

    def __len__(self) -> int:
        return len(self._ids)

    def __call__(self, slot: DefinitionSlot, context: Context) -> Term | None:
        return self._graph.term(self._ids.get(slot), context)


def load_definition_terms(
    session: Session, system: FormalSystem, spec: SystemSpec, offset: int = 0
) -> DefinitionTermCache:
    """Every usable stored definition-form term of ``system``.

    ``spec`` must be the one about to be built — the slot keys are positions in
    ``spec.definitions``, and the digest is computed from it. Always returns a
    cache, empty when nothing stored is still current; hand the same one back to
    :func:`store_definition_terms` after the build.

    ``offset`` is how many of ``spec.definitions`` belong to systems *before* this
    one, which is what an inheritance chain contributes: the spec is the whole
    chain's (``app.db.systems_mapping.effective_spec``) while these rows are one
    system's, so ``system.definitions[i]`` is ``spec.definitions[offset + i]``.
    Counted separately from the rule offset — `effective_spec` concatenates each
    part list independently.

    Only this system's own definitions are cached, for the reason
    :func:`~app.db.schema_terms.load_schema_terms` gives: an ancestor's row cannot
    hold the term its form parses to *here*, because that term is a function of
    the whole chain's grammar and the ancestor has its own.
    """
    digest = definition_digest(spec)
    ids: dict[DefinitionSlot, uuid.UUID] = {}
    # By position in the ORM collection, which `system_to_spec` reads in the same
    # order to build this layer's definitions — not by the `position` column, which
    # need not run 0, 1, 2 …. The two agree on the ordinal either way.
    for index, row in enumerate(system.definitions):
        if row.term_digest != digest:
            continue
        for slot, term_id in (
            ("higher", row.higher_term_id),
            ("lower", row.lower_term_id),
        ):
            if term_id is not None:
                ids[DefinitionSlot(offset + index, slot)] = term_id

    if not ids:
        return DefinitionTermCache(digest, {}, TermGraph({}, {}))

    # One sweep for the whole block: the build happens outside the session, so
    # every row it will touch has to be in memory by the time this returns.
    graph = prefetch_terms(session, list(ids.values()))
    present = graph.ids
    return DefinitionTermCache(
        digest, {slot: i for slot, i in ids.items() if i in present}, graph
    )


def store_definition_terms(
    session: Session,
    system: FormalSystem,
    built: EngineSystem,
    cache: DefinitionTermCache,
    offset: int = 0,
) -> int:
    """Persist the definition-form terms ``built`` derived, returning rows changed.

    Idempotent: a definition whose stored digest already matches is left alone, so
    calling this after every build costs one comparison per definition once the
    system has settled. ``cache`` must be the one :func:`load_definition_terms`
    returned for the spec ``built`` was built from — its digest is what the rows
    are stamped with, and recomputing it here would fingerprint the whole grammar
    a second time for the same answer.

    ``offset`` pairs these rows with the spec exactly as it does on the way in.

    A definition the build *dropped* — its defining form matched nothing given the
    definitions before it — registered no kernel definition and so derived no
    forms. Its row is left untouched, digest and all, so it keeps parsing (and
    keeps being dropped) on every build rather than recording an absence that a
    later read would have to tell apart from a swept term.
    """
    written = 0
    for index, row in enumerate(system.definitions):
        forms = built.definition_forms.get(offset + index)
        if forms is None or _is_current(row, cache.digest):
            continue
        higher, lower = forms
        row.higher_term_id = _term_id(session, system, higher)
        row.lower_term_id = _term_id(session, system, lower)
        row.term_digest = cache.digest
        written += 1
    return written


def _is_current(row: DefinitionRow, digest: str) -> bool:
    """Whether ``row`` already holds both terms this build would write.

    A matching digest is not enough on its own. The FKs are ``ON DELETE SET
    NULL``, so sweeping a term leaves the row with its digest intact and a hole
    where the term was — and a write skipped on the digest alone would never fill
    it, leaving that form reparsed on every verify for the life of the system.

    Both ids, because a registered definition always derives *both* forms: unlike
    a rule's schema slot, where a NULL is the ordinary way to record a slot that
    resolved to a declared grammar pattern, a NULL here can only be a hole.
    """
    return (
        row.term_digest == digest
        and row.higher_term_id is not None
        and row.lower_term_id is not None
    )


def _term_id(session: Session, system: FormalSystem, term: Term) -> uuid.UUID:
    stored = store_term(session, system, term)
    if stored.id is None:
        session.flush()
    return stored.id
