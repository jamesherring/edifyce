"""A fingerprint of a term, for goal-directed retrieval that prunes deeply.

The head-symbol prefilter (`app/db/retrieval.py`) narrows a library to the
theorems whose conclusion has the *same root production* as a goal. That is one
sampled position — the root — and it is why a judgement system where every
statement is `Γ ⊢ φ` is not narrowed at all: the head is always the turnstile,
and everything below it is invisible to the filter.

A **fingerprint** samples a fixed set of positions, not just the root, and
records at each what the term has there — a concrete symbol, a variable, or one
of two ways the position fails to exist. Two terms are unification-*incompatible*
whenever any sampled position disagrees irreconcilably, so a cheap per-position
comparison rejects the overwhelming majority of a library before the unifier is
asked. This is E's and Vampire's fingerprint indexing (Schulz 2012), the
SQL-native member of the discrimination-tree family, and a strict generalisation
of the head-symbol filter — position `()` alone *is* that filter.

**Soundness — it is a filter, never an oracle.** :func:`compatible` returns
`True` for every pair the kernel can unify, so a caller that keeps only the
compatible candidates and confirms each with `unify`/`match` loses nothing: 100%
recall is the contract (docs/search-and-embeddings-roadmap.md Phase 1). What it
buys is precision — fewer candidates handed to the unifier — and precision, not
correctness, is what a larger position set improves. Nothing here is consulted by
the checker; a wrong fingerprint costs a redundant unify, never a bad proof.

The features, following Schulz. At a sampled position a term has either a
*symbol* (its constructor, plus the literal for a ground leaf — two atoms of one
production unify only if their tokens agree), or one of three markers:

* ``VARIABLE`` — a variable sits exactly here. It unifies with any subterm the
  other side has, so it clashes only with ``ABSENT`` (there is nothing to bind).
* ``BELOW_VAR`` — this position lies *under* a variable, which subsumes whatever
  would be here, so it is compatible with everything.
* ``ABSENT`` — the path runs off the end of the term: a ground leaf or a
  lower-arity node terminates above this position, so no subterm exists here. It
  is compatible only with ``ABSENT`` and ``BELOW_VAR``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .kernel.terms import Node, Var

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .kernel.terms import Term

# A path from the root: each step is a child index into the constructor's slot
# order. `()` is the root itself.
Position = tuple[int, ...]

# The sampled positions: the root, its first two children, and their first two —
# E's default FP7, `{ε, 0, 1, 00, 01, 10, 11}`. A fixed set so a fingerprint is a
# fixed-width vector a database can store as columns and compare position by
# position. Widening it sharpens pruning and never changes what matches; it is
# the one knob Phase 1's measurements turn.
FINGERPRINT_POSITIONS: tuple[Position, ...] = (
    (),
    (0,),
    (1,),
    (0, 0),
    (0, 1),
    (1, 0),
    (1, 1),
)

# The three non-symbol features. Single characters so a stored fingerprint stays
# compact, and disjoint from any symbol key (which carries a `S`/`L` tag).
VARIABLE = "A"
BELOW_VAR = "N"
ABSENT = "B"

# A feature is one of the markers above, or a symbol key from `_symbol`.
Feature = str


def _symbol(node: Node) -> Feature:
    """The discriminating feature of a concrete node.

    Its constructor *signature* — what the unifier compares by, so two productions
    that spell one shape differently are one feature — plus, for a ground leaf,
    the literal token, because two atoms of one production (`a` and `b`) unify
    only when their tokens agree. The tags keep a leaf key from colliding with a
    compound key that happens to share a signature.
    """
    signature = "\x1f".join(node.constructor.signature)
    if node.literal is not None:
        return f"L\x1e{signature}\x1e{node.literal}"
    return f"S\x1e{signature}"


def feature_at(term: Term, path: Position) -> Feature:
    """What ``term`` has at ``path`` — a symbol, or a marker for why it does not.

    Walks the child slots named by ``path``. A variable on the way down makes the
    rest of the path :data:`BELOW_VAR`; running past a leaf (or a slot the node
    does not fill) makes it :data:`ABSENT`. At the destination a variable is
    :data:`VARIABLE` and a node is its :func:`_symbol`.
    """
    current = term
    for step in path:
        if isinstance(current, Var):  # a Bound is a Var subclass — treated the same
            return BELOW_VAR
        slots = current.constructor.slots
        if step >= len(slots) or slots[step] not in current.children:
            return ABSENT
        current = current.children[slots[step]]
    return VARIABLE if isinstance(current, Var) else _symbol(current)


def fingerprint(
    term: Term, positions: Sequence[Position] = FINGERPRINT_POSITIONS
) -> tuple[Feature, ...]:
    """The feature at each sampled position — the term's index key."""
    return tuple(feature_at(term, position) for position in positions)


def features_compatible(a: Feature, b: Feature) -> bool:
    """Whether two features at one position permit the terms to unify there.

    The symmetric table Schulz gives for unification: the only irreconcilable
    disagreements are two *distinct* symbols, and a subterm (``VARIABLE`` or a
    symbol) against ``ABSENT`` — where one term has structure the other has run
    out of. ``BELOW_VAR`` is compatible with everything, since the variable above
    it can be instantiated to match.
    """
    if a == b:
        return True
    if a == BELOW_VAR or b == BELOW_VAR:
        return True
    if a == VARIABLE:
        return b != ABSENT
    if b == VARIABLE:
        return a != ABSENT
    # Both are symbols, or one is ABSENT against a symbol: no substitution
    # reconciles them. (ABSENT vs ABSENT and equal symbols were caught by `a == b`.)
    return False


def compatible(query: Sequence[Feature], stored: Sequence[Feature]) -> bool:
    """Whether two fingerprints permit their terms to unify.

    ``True`` for every unifiable pair (the recall contract), so a caller filters
    on this and lets the kernel confirm. A single incompatible position is a
    sound rejection; agreement everywhere is only a licence to try the unifier.
    """
    return all(features_compatible(q, s) for q, s in zip(query, stored))
