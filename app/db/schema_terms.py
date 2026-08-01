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

**A missing term is a miss, never an answer.** A NULL term id is *not* read as
"this template composes to nothing", even under a matching digest. It cannot be:
the same NULL is what a deleted term leaves behind (the FKs are ``ON DELETE SET
NULL``), and what a slot resolving to a declared grammar pattern rather than a
composed one stores. Composing again settles all three correctly, and it is what
the build did before this module existed — so the only thing the distinction
would buy is skipping a compose, at the price of an absence being read as assent.
That trade is exactly the one P2 got wrong twice.

See docs/verification-from-rows.md, P3.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.systems import RuleRow
from app.db.terms_mapping import TermGraph, prefetch_terms, store_term
from website.logical.build_context import SchemaSlot
from website.logical.declarative import schema_digests
from website.logical.matching import StringPattern

if TYPE_CHECKING:
    from app.db.models import FormalSystem
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
    session (``build_spec`` is called straight from an async route), so nothing
    it asks for can be fetched by the time it asks. The graph it holds is flat
    data rather than ORM rows, which is what makes that unconditional — see
    :class:`~app.db.terms_mapping.TermGraph`.

    It also carries the digests it was selected by, which is what pairs it with
    :func:`store_schema_terms` afterwards: computing them means fingerprinting
    the whole grammar, and a verify that both reads and writes should do that
    once rather than at each end.
    """

    def __init__(
        self,
        digests: list[str],
        ids: dict[SchemaSlot, uuid.UUID],
        graph: TermGraph,
    ) -> None:
        self.digests = digests
        self._ids = ids
        # The graph memoises across every slot, so the subterms a system's rules
        # share — which, for a grammar with one main connective, is most of them —
        # are rebuilt once rather than once per schema.
        self._graph = graph

    def __len__(self) -> int:
        return len(self._ids)

    def __call__(self, slot: SchemaSlot, context: FormalSystemContext) -> Term | None:
        return self._graph.term(self._ids.get(slot), context)


def load_schema_terms(
    session: Session, system: FormalSystem, spec: SystemSpec, offset: int = 0
) -> SchemaTermCache:
    """Every usable stored schema term of ``system``.

    ``spec`` must be the one about to be built — the slot keys are positions in
    ``spec.rules``, and the digests are computed from it. Always returns a cache,
    empty when nothing stored is still current; hand the same one back to
    :func:`store_schema_terms` after the build.

    ``offset`` is how many of ``spec.rules`` belong to systems *before* this one,
    which is what an inheritance chain contributes: the spec is the whole chain's
    (``app.db.systems_mapping.effective_spec``) while these rows are one system's,
    so ``system.rules[i]`` is ``spec.rules[offset + i]``. Only this system's own
    rules are cached — an ancestor's row cannot hold the term its template
    composes to *here*, because that term is a function of the whole chain's
    grammar and the ancestor has its own. A child with inherited rules therefore
    recomposes them each build; the fix is a row per (rule, digest) rather than
    one column, and it is not worth a table until a layered system is slow.
    """
    digests = schema_digests(spec)
    fresh = [
        (offset + index, rule)
        for index, rule in enumerate(system.rules)
        if offset + index < len(digests)
        and rule.schema_digest == digests[offset + index]
    ]
    if not fresh:
        return SchemaTermCache(digests, {}, TermGraph({}, {}))

    ids: dict[SchemaSlot, uuid.UUID] = {}
    for index, rule in fresh:
        for slot, term_id in _rule_term_ids(rule).items():
            if term_id is not None:
                ids[SchemaSlot(index, slot)] = term_id
        # Keyed by position *in order*, not by the `position` column: the build
        # enumerates the spec's antecedent list, and `system_to_spec` builds that
        # by reading these rows in position order. The two agree on the ordinal
        # even if the stored positions are not 0, 1, 2 ….
        for ordinal, antecedent in enumerate(rule.antecedents):
            if antecedent.term_id is not None:
                ids[SchemaSlot(index, "antecedent", ordinal)] = antecedent.term_id

    # One sweep for the whole system's schema graph. The build happens outside
    # the session, so every row it will touch has to be in memory by the time
    # this returns.
    graph = prefetch_terms(session, list(ids.values()))
    present = graph.ids
    return SchemaTermCache(
        digests, {slot: i for slot, i in ids.items() if i in present}, graph
    )


def store_schema_terms(
    session: Session,
    system: FormalSystem,
    built: EngineSystem,
    cache: SchemaTermCache,
    offset: int = 0,
) -> int:
    """Persist the schema terms ``built`` composed, returning how many rules changed.

    Idempotent: a rule whose stored digest already matches is left alone, so
    calling this after every build costs one digest comparison per rule once the
    system has settled. ``cache`` must be the one :func:`load_schema_terms`
    returned for the spec ``built`` was built from — its digests are what the
    rows are stamped with, and recomputing them here would fingerprint the whole
    grammar a second time for the same answer.

    ``offset`` pairs these rows with the spec exactly as it does on the way in;
    it must be the same value :func:`load_schema_terms` was given.
    """
    digests = cache.digests
    rules = list(system.rules)
    # `add_inference_rule` *replaces* a rule of the same label, so a system with
    # two rules sharing one builds to fewer than it has rows, and matching them
    # up by position would attach one rule's terms to another. Only the last row
    # of each label survives into `built`; a shadowed one had its templates
    # composed and then discarded, so there is nothing of its own to store. It
    # keeps no digest and composes on every build, exactly as it did before this
    # module existed. (A duplicate label is a system defect either way, and one
    # the API does not currently refuse.)
    surviving = {row.label: index for index, row in enumerate(rules)}

    written = 0
    for index, row in enumerate(rules):
        if offset + index >= len(digests):
            break
        digest = digests[offset + index]
        if row.schema_digest == digest or surviving[row.label] != index:
            continue
        engine_rule = built.rule_by_label(row.label)
        if engine_rule is None:
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

    # Paired in order, matching how `system_to_spec` reads them and how the build
    # then enumerates them — not by the `position` column, which need not run
    # 0, 1, 2 …. `zip` is exact here: the built rule's antecedents *are* these
    # rows, one schema each.
    for antecedent, pattern in zip(row.antecedents, rule.antecedents):
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
