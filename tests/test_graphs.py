"""Unit tests for the dependency-free graph utilities (website/logical/graphs.py):
Kuhn's bipartite matching and the graphlib-backed topological order / cycle
finder that back the proof checker's antecedent assignment and its
import/theorem dependency handling.
"""

from website.logical.graphs import (
    find_cycle,
    maximum_bipartite_matching,
    saturating_matching,
    topological_order,
)


def _is_valid_matching(matching, adjacency):
    # A matching pairs distinct right nodes, each admissible for its left node.
    rights = list(matching.values())
    if len(rights) != len(set(rights)):
        return False
    return all(right in adjacency[left] for left, right in matching.items())


# ---------------------------------------------------------------------------
# maximum_bipartite_matching
# ---------------------------------------------------------------------------


def test_matching_pairs_every_left_when_a_perfect_matching_exists():
    adjacency = {"s1": ["a", "b"], "s2": ["a"]}
    matching = maximum_bipartite_matching(adjacency)
    assert len(matching) == 2
    assert _is_valid_matching(matching, adjacency)
    # s2 can only take a, so s1 must take b.
    assert matching["s2"] == "a"
    assert matching["s1"] == "b"


def test_matching_is_maximum_not_just_maximal():
    # Naively pairing s1->a first would strand s2; augmenting must re-home s1.
    adjacency = {"s1": ["a"], "s2": ["a", "b"]}
    matching = maximum_bipartite_matching(adjacency)
    assert len(matching) == 2
    assert _is_valid_matching(matching, adjacency)


def test_matching_caps_at_the_number_of_distinct_partners():
    # Two left nodes competing for a single right node: at most one can match.
    adjacency = {"s1": ["a"], "s2": ["a"]}
    matching = maximum_bipartite_matching(adjacency)
    assert len(matching) == 1
    assert _is_valid_matching(matching, adjacency)


def test_matching_empty_graph_and_empty_neighbourhoods():
    assert maximum_bipartite_matching({}) == {}
    assert maximum_bipartite_matching({"s1": [], "s2": []}) == {}


# ---------------------------------------------------------------------------
# saturating_matching
# ---------------------------------------------------------------------------


def test_saturating_matching_returns_assignment_when_all_left_can_pair():
    adjacency = {0: ["a", "b"], 1: ["b"]}
    matching = saturating_matching([0, 1], adjacency)
    assert matching is not None
    assert matching[1] == "b"
    assert matching[0] == "a"


def test_saturating_matching_is_none_when_a_slot_is_unfillable():
    assert saturating_matching([0, 1], {0: ["a"], 1: []}) is None


def test_saturating_matching_is_none_without_distinct_representatives():
    # Both slots admit only "a": no system of distinct representatives exists.
    assert saturating_matching([0, 1], {0: ["a"], 1: ["a"]}) is None


def test_saturating_matching_of_no_slots_is_trivially_satisfied():
    assert saturating_matching([], {}) == {}


# ---------------------------------------------------------------------------
# topological_order / find_cycle
# ---------------------------------------------------------------------------


def test_topological_order_places_dependencies_first():
    order = topological_order({"a": [], "b": ["a"], "c": ["b", "a"]})
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_order_of_independent_nodes_contains_them_all():
    assert set(topological_order({"a": [], "b": []})) == {"a", "b"}


def test_find_cycle_returns_none_for_a_dag():
    assert find_cycle({"a": [], "b": ["a"], "c": ["b"]}) is None


def test_find_cycle_reports_a_cycle():
    cycle = find_cycle({"a": ["b"], "b": ["a"]})
    assert cycle is not None
    # graphlib reports a path whose last node repeats the first.
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b"}


def test_find_cycle_detects_a_self_dependency():
    cycle = find_cycle({"a": ["a"]})
    assert cycle is not None
    assert cycle[0] == cycle[-1] == "a"
