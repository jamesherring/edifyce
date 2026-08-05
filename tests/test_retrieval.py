"""Engine-level tests for the citation search: which rules could justify a line.

The half of retrieval that is unification rather than a query
(docs/authoring-and-ingestion-roadmap.md §9d). What is checked here is that the
search finds an application when one exists, finds nothing when none does, and —
the property the whole thing rests on — that probing a line leaves no mark on it.
Which candidates a search is *offered* is a database question, covered by
tests/test_retrieval_store.py.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Rule, SystemSpec, build_system
from website.logical.formal_system.retrieval import (
    accessible_lines,
    applications,
    discharges,
    dischargeable_openers,
)

from tests.spec_helpers import (
    assumption_line,
    brackets,
    cp_rule,
    hyp_rule,
    regex_prod,
    reiteration_rule,
    rule,
    statement_line,
    template_prod,
)


def _pq():
    return [("p", "formula"), ("q", "formula")]


MP_SYSTEM = SystemSpec(
    name="PropLogic",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z]"),
        template_prod("formula", "implication", "(p -> q)", _pq()),
    ],
    lines=[statement_line()],
    rules=[
        hyp_rule(),
        rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", _pq()),
        # A conclusion no proof below ever states, so it is the rule the search
        # must *not* return.
        rule("SELF", "self_implication", ["p"], "(p -> p)", _pq()),
        # Two premises that are the same schema: one standing line satisfies both.
        rule("TWO", "two", ["p", "p"], "(p -> p)", [("p", "formula")]),
    ],
)


@pytest.fixture(scope="module")
def mp_system():
    return build_system(MP_SYSTEM)


def _rule(system, label):
    return next(r for r in system.inference_rules if r.label == label)


def _context(system):
    return system.context


# ---------------------------------------------------------------------------
# Finding an application
# ---------------------------------------------------------------------------


def test_the_premises_of_a_hole_are_found(mp_system):
    # The loop's missing move: line 3 is stated and unproved, and MP justifies it
    # from the two lines above — which nothing until now would tell a caller.
    proof = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [?]")
    goal = proof.get_proof_line(3)

    found = applications(
        _rule(mp_system, "MP"), goal, accessible_lines(goal), _context(mp_system)
    )

    assert len(found) == 1
    assert found[0].numbers == [1, 2]
    assert found[0].discharge is False


def test_a_rule_that_cannot_conclude_the_goal_is_not_offered(mp_system):
    # The conclusion-side filter: SELF concludes `(p -> p)`, and the goal is an
    # atom, so no assignment of premises could ever help.
    proof = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [?]")
    goal = proof.get_proof_line(3)

    assert (
        applications(
            _rule(mp_system, "SELF"), goal, accessible_lines(goal), _context(mp_system)
        )
        == []
    )


def test_a_rule_whose_premises_are_absent_is_not_offered(mp_system):
    # MP concludes an atom, so it passes the conclusion filter — and still cannot
    # apply, because nothing above the goal is an implication ending in `b`.
    proof = mp_system.parse("a [HYP]\nc [HYP]\nb [?]")
    goal = proof.get_proof_line(3)

    assert (
        applications(
            _rule(mp_system, "MP"), goal, accessible_lines(goal), _context(mp_system)
        )
        == []
    )


def test_the_search_stops_at_the_limit(mp_system):
    # Two ways to reach `b`, and a caller that asked for one gets one: the search
    # short-circuits rather than enumerating a library's worth of answers.
    source = "a [HYP]\n(a -> b) [HYP]\nc [HYP]\n(c -> b) [HYP]\nb [?]"
    proof = mp_system.parse(source)
    goal = proof.get_proof_line(5)
    pool = accessible_lines(goal)

    assert len(applications(_rule(mp_system, "MP"), goal, pool, _context(mp_system))) == 1
    assert (
        len(
            applications(
                _rule(mp_system, "MP"), goal, pool, _context(mp_system), limit=5
            )
        )
        == 2
    )


def test_one_line_can_fill_two_slots(mp_system):
    # A rule whose two premises are the same schema is satisfied by one standing
    # line used twice, and `[TWO, 1, 1]` is a citation the checker accepts. A
    # search demanding distinct lines per slot would have made exactly those
    # rules unfindable — and reported "nothing can justify this" about a line
    # that one rule justifies outright.
    proof = mp_system.parse("a [HYP]\n(a -> a) [?]")
    goal = proof.get_proof_line(2)

    found = applications(
        _rule(mp_system, "TWO"), goal, accessible_lines(goal), _context(mp_system)
    )

    assert [a.numbers for a in found] == [[1, 1]]
    # And the citation it composes is one the checker takes.
    assert mp_system.parse("a [HYP]\n(a -> a) [TWO, 1, 1]").proof_lines[-1].valid is True


# ---------------------------------------------------------------------------
# Probing records nothing
# ---------------------------------------------------------------------------


def test_a_found_application_does_not_justify_the_line(mp_system):
    # The property the whole search rests on. A probe answers; it does not
    # commit. If it did, a caller that merely *asked* what could justify a hole
    # would find the hole filled — and every rejected candidate would have left
    # its own bookkeeping behind on the way.
    proof = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [?]")
    goal = proof.get_proof_line(3)

    applications(
        _rule(mp_system, "MP"), goal, accessible_lines(goal), _context(mp_system)
    )

    assert goal.valid is False
    assert goal.failure is not None and goal.failure.code == "hole"
    assert goal.inference_rule is None
    assert goal.inference is None
    assert proof.get_proof_line(1).dependent_lines == set()


def test_a_rejected_probe_leaves_no_dependency_edge(mp_system):
    # The other half: a candidate that fails must not have half-registered
    # itself on the lines it tried.
    proof = mp_system.parse("a [HYP]\nc [HYP]\nb [?]")
    goal = proof.get_proof_line(3)

    applications(
        _rule(mp_system, "MP"), goal, accessible_lines(goal), _context(mp_system)
    )

    assert proof.get_proof_line(1).dependent_lines == set()
    assert proof.get_proof_line(2).dependent_lines == set()


# ---------------------------------------------------------------------------
# Scope, and the rules that close a subproof
# ---------------------------------------------------------------------------


CP_SYSTEM = SystemSpec(
    name="CP",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z]"),
        template_prod("formula", "implication", "(p → q)", _pq()),
    ],
    lines=[statement_line(), assumption_line()],
    rules=[
        reiteration_rule(),
        cp_rule(),
        Rule(
            label="MP2",
            name="modus_ponens",
            antecedents=["p", "(p → q)"],
            deduction="q",
            bindings=_pq(),
        ),
    ],
)


@pytest.fixture(scope="module")
def cp_system():
    return build_system(CP_SYSTEM)


def test_a_discharge_rule_is_found_for_the_line_that_closes_a_subproof(cp_system):
    # Without this the search would be blind to exactly the rules that introduce
    # an implication or a quantifier — which in a natural-deduction system is
    # every step that closes a subproof.
    proof = cp_system.parse("assume a\n    a [R, 1]\n(a → a) [?]")
    goal = proof.get_proof_line(3)

    found = discharges(
        _rule(cp_system, "CP"), goal, dischargeable_openers(goal), _context(cp_system)
    )

    assert len(found) == 1
    assert found[0].numbers == [1]  # the opener, which is how a discharge is cited
    assert found[0].discharge is True
    # And still nothing recorded.
    assert goal.valid is False
    assert goal.inference_rule is None


def test_the_two_pools_answer_two_questions(cp_system):
    # An opener lives inside the subproof it opens, so a line below cannot cite
    # it as an antecedent — and can discharge it. Neither pool contains the
    # other, and conflating them would either offer citations the checker
    # refuses or hide every discharge.
    proof = cp_system.parse("assume a\n    a [R, 1]\n(a → a) [CP, 1]\nb [?]")
    goal = proof.get_proof_line(4)

    # Line 1 opens the subproof and line 2 is inside it: neither is citable here.
    assert [line.number for line in accessible_lines(goal)] == [3]
    assert [line.number for line in dischargeable_openers(goal)] == [1]


def test_an_ordinary_rule_search_declines_a_discharge_rule(cp_system):
    # The two searches are not interchangeable: CP has no antecedent slots to
    # fill, so asking `applications` for one must return nothing rather than
    # answering "no premises needed, it applies".
    proof = cp_system.parse("assume a\n    a [R, 1]\n(a → a) [?]")
    goal = proof.get_proof_line(3)

    assert (
        applications(
            _rule(cp_system, "CP"), goal, accessible_lines(goal), _context(cp_system)
        )
        == []
    )
