"""Experiment 1's embedding: what a formula *looks like*.

A bag of alpha-normalized subtree features, hashed into a fixed width, plus a
handful of whole-term statistics. This is the ordinary syntax/graph embedding the
prototype tested — the hypothesis being that structural similarity of formulas
tracks the geometry of truth — and the point of running it at corpus scale is to
find out whether the prototype's negative result was a small-sample artefact.

The width is 512 + 14 = 526, matching the prototype so the two runs are
comparable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from experiments.lindenbaum.dag import KIND_VAR, walk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from experiments.lindenbaum.dag import Arena

BUCKETS = 512
STATISTICS = 14
WIDTH = BUCKETS + STATISTICS


def _statistics(arena: Arena, root: int, walked, distinct_constructors: int) -> list[float]:
    nodes = walked.nodes
    distinct = len(walked.subterms)
    arities = [
        len(arena.children[term])
        for term in walked.subterms
        if arena.children[term]
    ]
    free = len(arena.free[root])
    binary = sum(
        walked.multiplicity[term]
        for term in walked.subterms
        if len(arena.children[term]) == 2
    )
    unary = sum(
        walked.multiplicity[term]
        for term in walked.subterms
        if len(arena.children[term]) == 1
    )
    height = walked.height[root]
    return [
        np.log1p(nodes),
        np.log1p(distinct),
        float(height),
        float(max(arities, default=0)),
        float(sum(arities) / len(arities)) if arities else 0.0,
        np.log1p(walked.leaves),
        np.log1p(walked.variables),
        float(free),
        distinct / nodes if nodes else 0.0,
        np.log1p(distinct_constructors),
        walked.height_total / nodes if nodes else 0.0,
        binary / nodes if nodes else 0.0,
        unary / nodes if nodes else 0.0,
        height / np.log1p(nodes) if nodes else 0.0,
    ]


def embed(arena: Arena, roots: Sequence[int]) -> np.ndarray:
    """The 526-dimensional structural embedding of each root, unstandardised."""
    matrix = np.zeros((len(roots), WIDTH), dtype=np.float64)
    for row, root in enumerate(roots):
        walked = walk(arena, root)
        counts = np.zeros(BUCKETS, dtype=np.float64)
        constructors: set[str] = set()
        for term in walked.subterms:
            counts[arena.key[term] % BUCKETS] += walked.multiplicity[term]
            constructor = arena.constructor[term]
            if constructor is not None:
                constructors.add(constructor)
            elif arena.kind[term] == KIND_VAR:
                constructors.add("$var")
        counts = np.log1p(counts)
        norm = np.linalg.norm(counts)
        if norm > 0:
            counts /= norm
        matrix[row, :BUCKETS] = counts
        matrix[row, BUCKETS:] = _statistics(arena, root, walked, len(constructors))
    return matrix


def standardise(train: np.ndarray, *others: np.ndarray) -> tuple[np.ndarray, ...]:
    """Zero-mean, unit-variance on the training split's statistics only.

    Fitting the scaler on the training rows alone is what keeps the unseen-family
    split honest: a scaler fitted on everything has already seen the held-out
    families' statistics.
    """
    mean = train.mean(axis=0)
    scale = train.std(axis=0)
    scale[scale == 0] = 1.0
    return tuple((matrix - mean) / scale for matrix in (train, *others))
