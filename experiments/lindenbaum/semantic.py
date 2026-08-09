"""Experiment 2's embedding: what a formula *does*.

A formula is embedded by its truth value under each of a set of assignments to
the generators, giving a point of {-1,+1}^N. Two things follow, and neither is
statistical:

* the connectives become exact coordinatewise operations — negation is a sign
  flip, conjunction a minimum, disjunction a maximum, the biconditional a
  product — so the embedding is a Boolean-algebra homomorphism and not an
  approximation of one;
* one distinguished coordinate, the assignment making every generator true,
  decides provability outright, by the argument in `formulas.py`.

Where this departs from the prototype is only in how the coordinates are chosen.
With ten generators the prototype could take **all** 2¹⁰ assignments and the
embedding was the full Lindenbaum–Tarski / Stone representation of the subalgebra
they generate. A corpus contributes thousands of generators, so 2ⁿ is not
enumerable and the coordinates are *sampled* instead — the distinguished one, and
then uniform assignments. Sampling costs completeness, not correctness: every
identity below is coordinatewise, so it holds on any subset of coordinates, and
the distinguished coordinate is kept by construction rather than sampled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from experiments.lindenbaum.formulas import Skeleton

if TYPE_CHECKING:
    from collections.abc import Sequence

    from experiments.lindenbaum.corpus import Theorem
    from experiments.lindenbaum.formulas import Compound

#: Index of the assignment that makes every generator true.
DISTINGUISHED = 0


def assignments(generators: int, coordinates: int, seed: int) -> np.ndarray:
    """A ``coordinates × generators`` boolean matrix whose first row is all-true."""
    rng = np.random.default_rng(seed)
    omega = rng.random((coordinates, generators)) < 0.5
    omega[DISTINGUISHED, :] = True
    return omega


def _evaluate(skeleton: Skeleton, values: np.ndarray) -> np.ndarray:
    """Evaluate under every assignment at once. ``values`` is coordinates × slots."""
    if skeleton.is_slot:
        return values[:, skeleton.slot]
    if skeleton.op == "not":
        return ~_evaluate(skeleton.args[0], values)
    left = _evaluate(skeleton.args[0], values)
    right = _evaluate(skeleton.args[1], values)
    if skeleton.op == "and":
        return left & right
    if skeleton.op == "or":
        return left | right
    if skeleton.op == "imp":
        return ~left | right
    if skeleton.op == "iff":
        return left == right
    raise ValueError(f"unknown connective {skeleton.op!r}")


def embed(
    compounds: Sequence[Compound], omega: np.ndarray, slot_of: dict[str, int]
) -> np.ndarray:
    """The ±1 semantic embedding of each compound, as ``compounds × coordinates``."""
    matrix = np.empty((len(compounds), omega.shape[0]), dtype=np.int8)
    for row, compound in enumerate(compounds):
        columns = [slot_of[generator.label] for generator in compound.generators]
        matrix[row] = np.where(_evaluate(compound.skeleton, omega[:, columns]), 1, -1)
    return matrix


def embed_one(
    skeleton: Skeleton,
    generators: Sequence[Theorem],
    omega: np.ndarray,
    slot_of: dict[str, int],
) -> np.ndarray:
    columns = [slot_of[generator.label] for generator in generators]
    return np.where(_evaluate(skeleton, omega[:, columns]), 1, -1).astype(np.int8)


def _shift(skeleton: Skeleton, by: int) -> Skeleton:
    if skeleton.is_slot:
        return Skeleton(op="slot", slot=skeleton.slot + by)
    return Skeleton(
        op=skeleton.op, args=tuple(_shift(arg, by) for arg in skeleton.args)
    )


def combine(
    op: str, left: Compound, right: Compound
) -> tuple[Skeleton, tuple[Theorem, ...]]:
    """Join two compounds under ``op``, concatenating their generator slots.

    The two operands keep their own slots rather than sharing one per distinct
    theorem. A shared slot would be the stronger statement — but it is also the
    one that needs the generators to be logically *independent* atoms, which real
    theorems are not, so keeping them separate is what makes the identity checks
    below claims about the embedding rather than about set.mm.
    """
    shifted = _shift(right.skeleton, len(left.generators))
    return (
        Skeleton(op=op, args=(left.skeleton, shifted)),
        left.generators + right.generators,
    )


def hamming(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Per-row Hamming distance between two ±1 matrices."""
    return (left != right).sum(axis=1)


def project(embedding: np.ndarray, dimension: int, seed: int) -> np.ndarray:
    """A Gaussian random projection into ``dimension`` dimensions.

    Entries are N(0, 1/d), the scaling under which ‖Gᵀx‖ concentrates on ‖x‖, so
    the distortion reported downstream is a distance ratio and needs no further
    normalisation.
    """
    rng = np.random.default_rng(seed)
    matrix = rng.normal(
        0.0, 1.0 / np.sqrt(dimension), size=(embedding.shape[1], dimension)
    )
    return embedding.astype(np.float64) @ matrix
