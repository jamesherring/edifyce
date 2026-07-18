"""Small, dependency-free graph utilities used by the proof checker.

Two unrelated bits of graph logic the engine had open-coded:

* **Bipartite matching** - deciding whether cited antecedent lines can be
  assigned to an inference rule's antecedent *slots* at all, and enumerating the
  assignments worth trying. The checker used to try *every* permutation of the
  cited lines (factorial, hard-capped at "> 6" with a server error); matching
  lets it reject an impossible citation up front and only search assignments that
  are individually admissible. Implemented here as Kuhn's augmenting-path
  algorithm - a few lines, easy to audit, and enough for the handful of
  antecedents a rule ever has.

* **Topological order** - ordering proofs by their import/theorem dependencies
  and detecting circular ones. This is a thin, typed wrapper over the standard
  library's :class:`graphlib.TopologicalSorter` so callers get a plain ordered
  list and a clear cycle report without repeating the boilerplate.

Kept deliberately generic (plain hashable nodes, no engine imports) so it stays a
leaf utility and can be tested in isolation.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping

L = TypeVar("L", bound="Hashable")
R = TypeVar("R", bound="Hashable")
N = TypeVar("N", bound="Hashable")


def maximum_bipartite_matching(adjacency: Mapping[L, Iterable[R]]) -> dict[L, R]:
    """A maximum-cardinality matching of the bipartite graph in ``adjacency``.

    ``adjacency`` maps each left node to the right nodes it may pair with.
    Returns a dict pairing left nodes to distinct right nodes; its size is the
    largest possible. Uses Kuhn's algorithm: for each left node, try to find an
    augmenting path that frees up a right node already taken.
    """
    # right node -> the left node currently matched to it
    match_right: dict[R, L] = {}

    def augment(left: L, seen: set[R]) -> bool:
        for right in adjacency[left]:
            if right in seen:
                continue
            seen.add(right)
            # Free, or its current partner can be re-homed along an augmenting path.
            if right not in match_right or augment(match_right[right], seen):
                match_right[right] = left
                return True
        return False

    for left in adjacency:
        augment(left, set())

    return {left: right for right, left in match_right.items()}


def saturating_matching(
    left_nodes: Iterable[L], adjacency: Mapping[L, Iterable[R]]
) -> dict[L, R] | None:
    """A matching that pairs *every* node in ``left_nodes``, or ``None`` if none
    exists.

    This is the feasibility question the proof checker asks: can each antecedent
    slot be filled by a distinct, individually-admissible line? A ``None`` result
    means the citation cannot satisfy the rule no matter how the lines are
    ordered, so the checker can reject without any further search.
    """
    left = list(left_nodes)
    matching = maximum_bipartite_matching({node: adjacency[node] for node in left})
    if len(matching) < len(left):
        return None
    return matching


def topological_order(dependencies: Mapping[N, Iterable[N]]) -> list[N]:
    """Nodes ordered so each comes after everything it depends on.

    ``dependencies`` maps a node to the nodes it depends on (its predecessors).
    Raises :class:`graphlib.CycleError` if the dependencies are circular; use
    :func:`find_cycle` to report the offending nodes.
    """
    sorter: TopologicalSorter[N] = TopologicalSorter()
    for node, deps in dependencies.items():
        sorter.add(node, *deps)
    return list(sorter.static_order())


def find_cycle(dependencies: Mapping[N, Iterable[N]]) -> list[N] | None:
    """The nodes of a dependency cycle if one exists, else ``None``.

    The returned list is the cycle as :class:`graphlib.TopologicalSorter`
    reports it - a path of nodes whose last element repeats its first.
    """
    try:
        topological_order(dependencies)
    except CycleError as error:
        # CycleError.args == (message, cycle_list); the cycle is the useful part.
        return list(error.args[1])
    return None
