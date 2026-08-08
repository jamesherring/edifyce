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

from website.logical.fingerprint import Fingerprint, fingerprint
from website.logical.matching import StringPattern

if TYPE_CHECKING:
    from website.logical.matching.patterns import Pattern


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
