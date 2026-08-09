"""Persisting a term's fingerprint (:mod:`website.logical.fingerprint`) as a column.

The fingerprint itself is computed in the engine from a kernel term; this is the
thin serialization that stores one beside a promoted theorem's conclusion, so
goal-directed retrieval can filter on it without rebuilding the term. It mirrors
how the digests in :mod:`app.db.terms_mapping` persist an engine-computed key of a
term — a derived index, not the term.

The stored form carries the fingerprint's **position-set key** as well as its
features, so a fingerprint written under one ``FINGERPRINT_POSITIONS`` and read
after a change to it is refused by :func:`~website.logical.fingerprint.compatible`
rather than silently compared against the wrong positions (see that function). A
change to the position set therefore means re-indexing, and the key is what makes
forgetting loud.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import JSON, and_, cast, or_, true, type_coerce

from website.logical.fingerprint import (
    ABSENT,
    BELOW_VAR,
    VARIABLE,
    Fingerprint,
    fingerprint,
)
from website.logical.matching import StringPattern

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    from website.logical.matching.patterns import Pattern

# Where `encode` puts each part in the stored JSON array, so the SQL that reads a
# stored fingerprint back stays in step with the SQL-free serialization above.
_KEY_INDEX = 0
_FEATURES_INDEX = 1


def encode(fp: Fingerprint) -> str:
    """A stored fingerprint: its position-set key and features, as JSON."""
    return json.dumps([fp.key, list(fp.features)], ensure_ascii=False)


def decode(stored: str) -> Fingerprint:
    """Rebuild a :class:`Fingerprint` from :func:`encode`'s output."""
    key, features = json.loads(stored)
    return Fingerprint(key=key, features=tuple(features))


def pattern_fingerprint(pattern: Pattern | None) -> str | None:
    """The encoded fingerprint of a schema pattern's composed term, or ``None``.

    ``None`` exactly when the pattern carries no composed term — a bare grammar
    pattern rather than a :class:`StringPattern` with a ``schema_term``. That is
    the same condition under which :func:`~app.db.promoted_theorems_mapping._term_ids`
    stores no ``statement_term_id``, so a theorem's cached term and its fingerprint
    are present or absent together, and one is "indexed" for retrieval iff the
    other is.
    """
    if isinstance(pattern, StringPattern) and pattern.schema_term is not None:
        return encode(fingerprint(pattern.schema_term))
    return None


def _as_json(column: ColumnElement[str | None], dialect: str) -> ColumnElement:
    """The stored JSON, in the form each dialect's ``->`` extraction can read.

    The two backends need opposite things and neither form works on the other, so
    the choice is made here rather than hidden in a column type. SQLite has no JSON
    affinity — ``CAST(x AS JSON)`` gives it NUMERIC affinity and the extraction
    reads NULL — so the text is left as text and :func:`type_coerce` only relabels
    it for indexing. Postgres has no ``text -> int`` operator, so the text must be
    genuinely ``CAST`` to ``json`` before a position can be pulled from it.
    """
    return type_coerce(column, JSON) if dialect == "sqlite" else cast(column, JSON)


def _feature_condition(
    query_feature: str, stored: ColumnElement
) -> ColumnElement[bool] | None:
    """When a stored feature is unification-compatible with a fixed query feature.

    The SQL image of :func:`~website.logical.fingerprint.features_compatible` for a
    *constant* query feature — the query term is in hand, each stored term is a row
    — so the whole per-position test collapses to a comparison the database runs.
    ``None`` means "no constraint": a query variable's position (``BELOW_VAR``)
    unifies with anything, so it is not worth a clause. Kept in lockstep with the
    engine predicate by ``tests/test_fingerprint_sql.py``, which asserts the two
    agree on every feature pair — the recall contract lives in that agreement.
    """
    if query_feature == BELOW_VAR:
        return None
    if query_feature == VARIABLE:
        # A variable here binds to any subterm the other side has — anything but a
        # position that does not exist.
        return stored != ABSENT
    if query_feature == ABSENT:
        # The query ran off its term here, so the stored side must too (or lie
        # under a variable that subsumes the difference).
        return stored.in_([ABSENT, BELOW_VAR])
    # A concrete symbol: the stored side matches it, sits under a variable, or is a
    # variable that can bind to it.
    return stored.in_([query_feature, BELOW_VAR, VARIABLE])


def fingerprint_filter(
    column: ColumnElement[str | None], query: Fingerprint, dialect: str
) -> ColumnElement[bool]:
    """A row's stored fingerprint permits its term to unify with ``query``'s.

    The deep half of the structural prefilter, as one WHERE condition: the head
    filter (`retrieval.py`) picks the constructor bucket with an index, and this
    narrows within it position by position without one. It is layered *on top* of
    that filter and only ever removes rows, so recall is exactly the engine's —
    :func:`~website.logical.fingerprint.compatible` proves a pruned row cannot
    unify.

    Recall-safe on the unindexed too. A row whose fingerprint is NULL, or was
    written under a different :data:`~website.logical.fingerprint.FINGERPRINT_POSITIONS`
    (its stored key no longer matches), cannot be compared — the engine
    :func:`~website.logical.fingerprint.compatible` *raises* on that mismatch — so
    it is kept rather than dropped, falling through to the head filter alone. This
    is the same "unindexed, therefore counted not hidden" contract the NULL cached
    term already has.
    """
    stored = _as_json(column, dialect)
    conditions = [
        condition
        for index, feature in enumerate(query.features)
        if (condition := _feature_condition(feature, stored[_FEATURES_INDEX][index].as_string()))
        is not None
    ]
    key_mismatch = stored[_KEY_INDEX].as_string() != query.key
    return or_(
        column.is_(None),
        key_mismatch,
        and_(*conditions) if conditions else true(),
    )
