"""Round trip between a rule's schema patterns and their stored kernel terms.

A rule's deduction, antecedents and subproof lines are *templates* — strings the
build parses against the whole grammar to get the nested term the checker
actually unifies with (``build_context.compose_schema_term``). That parse is
roughly half of building a system of any size, it happens on every verify, and
it produces the same term every time. These two functions move it off the read
path: :func:`store_schema_terms` writes what a build composed, and
:func:`load_schema_terms` hands it back to the next one.

**Freshness is decided, not maintained.** Each rule row carries the digest of
everything its terms were composed from (``declarative.schema_digests``: the
grammar, plus that rule's own templates and bindings). A row whose digest no
longer matches is simply not read, and the build composes as it always did — so
an edit anywhere in the system needs no cascade, no invalidation sweep and no
ordering guarantee, and a stale row is inert rather than believed. That is the
opposite of ``proof_lines``, where the row *is* the record; here the template
beside it is, and the term is only a saved derivation of it.

See docs/verification-from-rows.md, P3.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.systems import RuleAntecedentRow, RuleRow
from app.db.terms_mapping import load_term, prefetch_terms, store_term
from website.logical.build_context import CachedSchema, SchemaSlot
from website.logical.declarative import schema_digests
from website.logical.matching import StringPattern

if TYPE_CHECKING:
    from app.db.models import FormalSystem
    from app.db.terms import TermRow
    from website.logical.build_context import FormalSystemContext
    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system.rules import InferenceRule
    from website.logical.kernel.terms import Term
    from website.logical.matching import Pattern

# The single-valued schema slots, in the order they are named everywhere below.
# Antecedents are the one repeated slot and live in their own table.
_RULE_SLOTS = ("deduction", "derive", "assume", "fresh")


def _rule_term_ids(rule: RuleRow) -> dict[str, uuid.UUID | None]:
    """Which term each of ``rule``'s single-valued schema slots is stored as."""
    return {
        "deduction": rule.deduction_term_id,
        "derive": rule.subproof_derive_term_id,
        "assume": rule.subproof_assume_term_id,
        "fresh": rule.subproof_fresh_term_id,
    }


def _set_rule_term_ids(rule: RuleRow, ids: dict[str, uuid.UUID | None]) -> None:
    rule.deduction_term_id = ids["deduction"]
    rule.subproof_derive_term_id = ids["derive"]
    rule.subproof_assume_term_id = ids["assume"]
    rule.subproof_fresh_term_id = ids["fresh"]


class SchemaTermCache:
    """The schema terms of one system, ready to answer a build.

    Every row this can serve is already in memory: the build happens outside the
    session (``build_spec`` is called straight from an async route), and a
    SQLAlchemy identity map holds only weak references — so the rows are held
    here rather than merely loaded.

    It also carries the digests it was selected by, which is what pairs it with
    :func:`store_schema_terms` afterwards: computing them means fingerprinting
    the whole grammar, and a verify that both reads and writes should do that
    once rather than at each end.
    """

    def __init__(
        self,
        digests: list[str],
        rows: dict[SchemaSlot, TermRow | None],
        graph: list[TermRow],
    ) -> None:
        self.digests = digests
        self._rows = rows
        # Every row of the schema graph, roots and descendants alike. Holding the
        # roots is not enough: a child reached through an edge is found in the
        # identity map only while something still refers to it, and one that has
        # been collected is fetched again — a query per edge, outside the session's
        # greenlet, which is an error rather than a slow path.
        self._graph = graph
        # One memo across every slot, so the subterms a system's rules share —
        # which, for a grammar with one main connective, is most of them — are
        # rebuilt once rather than once per schema.
        self._memo: dict[object, Term] = {}

    def __len__(self) -> int:
        return len(self._rows)

    def __call__(
        self, slot: SchemaSlot, context: FormalSystemContext
    ) -> CachedSchema | None:
        if slot not in self._rows:
            return None
        row = self._rows[slot]
        if row is None:
            # Stored, and composes to nothing — a hit. Those are the templates
            # nothing parses, so composing them again is the most expensive miss
            # there is (every candidate sort tried, all failing).
            return CachedSchema(None)
        return CachedSchema(load_term(row, context, self._memo))


def load_schema_terms(
    session: Session, system: FormalSystem, spec: SystemSpec
) -> SchemaTermCache:
    """Every usable stored schema term of ``system``.

    ``spec`` must be the one about to be built — the slot keys are positions in
    ``spec.rules``, and the digests are computed from it. Always returns a cache,
    empty when nothing stored is still current; hand the same one back to
    :func:`store_schema_terms` after the build.
    """
    digests = schema_digests(spec)
    fresh = [
        (index, rule)
        for index, rule in enumerate(system.rules)
        if index < len(digests) and rule.schema_digest == digests[index]
    ]
    if not fresh:
        return SchemaTermCache(digests, {}, [])

    ids: dict[SchemaSlot, uuid.UUID | None] = {}
    for index, rule in fresh:
        for slot, term_id in _rule_term_ids(rule).items():
            ids[SchemaSlot(index, slot)] = term_id
        for antecedent in rule.antecedents:
            ids[SchemaSlot(index, "antecedent", antecedent.position)] = antecedent.term_id

    # One sweep for the whole system's schema graph. The build happens outside
    # the session, so every row it will touch has to be in memory by the time
    # this returns — and has to stay there (see SchemaTermCache).
    graph = prefetch_terms(session, [i for i in ids.values() if i is not None])
    by_id = {row.id: row for row in graph}
    return SchemaTermCache(
        digests, {slot: None if i is None else by_id[i] for slot, i in ids.items()}, graph
    )


def store_schema_terms(
    session: Session,
    system: FormalSystem,
    built: EngineSystem,
    cache: SchemaTermCache,
) -> int:
    """Persist the schema terms ``built`` composed, returning how many rules changed.

    Idempotent: a rule whose stored digest already matches is left alone, so
    calling this after every build costs one digest comparison per rule once the
    system has settled. ``cache`` must be the one :func:`load_schema_terms`
    returned for the spec ``built`` was built from — its digests are what the
    rows are stamped with, and recomputing them here would fingerprint the whole
    grammar a second time for the same answer.
    """
    digests = cache.digests
    rules = list(system.rules)
    engine_rules = list(built.inference_rules)
    if not (len(rules) == len(engine_rules) == len(digests)):
        # Only reachable if the three drifted apart, which would silently attach
        # one rule's terms to another. Refuse rather than write a plausible lie.
        raise ValueError(
            f"Cannot store schema terms: {len(rules)} rule rows, "
            f"{len(engine_rules)} built rules, {len(digests)} digests."
        )

    written = 0
    for row, engine_rule, digest in zip(rules, engine_rules, digests):
        if row.schema_digest == digest:
            continue
        _store_rule(session, system, row, engine_rule)
        row.schema_digest = digest
        written += 1
    return written


def _store_rule(
    session: Session, system: FormalSystem, row: RuleRow, rule: InferenceRule
) -> None:
    subproof = rule.subproof_schema
    patterns: dict[str, Pattern | None] = {
        "deduction": rule.deduction,
        "derive": None if subproof is None else subproof.conclusion,
        "assume": None if subproof is None else subproof.assumption,
        "fresh": None if subproof is None else subproof.fresh,
    }
    _set_rule_term_ids(
        row, {slot: _term_id(session, system, patterns[slot]) for slot in _RULE_SLOTS}
    )

    by_position: dict[int, RuleAntecedentRow] = {a.position: a for a in row.antecedents}
    for position, pattern in enumerate(rule.antecedents):
        antecedent = by_position.get(position)
        # A build takes its antecedents from the rows in position order, so a gap
        # here means the rows changed under us; leave the row alone rather than
        # guess which template the term belongs to.
        if antecedent is not None:
            antecedent.term_id = _term_id(session, system, pattern)


def _term_id(
    session: Session, system: FormalSystem, pattern: Pattern | None
) -> uuid.UUID | None:
    # Only a `StringPattern` carries a schema term: the other things a schema can
    # resolve to are declared grammar patterns, returned whole by
    # `build_schema_pattern` before it composes anything (a bare sort name, a
    # constant atom). Those never consult a stored term either, so storing NULL
    # for them is exact rather than a gap.
    if not isinstance(pattern, StringPattern) or pattern.schema_term is None:
        return None
    stored = store_term(session, system, pattern.schema_term)
    if stored.id is None:
        session.flush()
    return stored.id
