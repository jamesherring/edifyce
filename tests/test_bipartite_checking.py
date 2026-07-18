"""Engine-level tests for the graph-backed proof checker:

* antecedent assignment via bipartite matching (InferenceRule.slot_admits +
  Proof._first_valid_assignment) - a rule applies regardless of the order its
  antecedents are cited, an impossible citation is rejected without raising, and
  extra antecedents are handled; and
* the graphlib-backed import/theorem dependency helpers on Proof
  (dependency_order / circular_dependency).
"""

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system import Proof


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


# Modus ponens: two antecedents (p and (p -> q)) sharing the metavariable p, so a
# correct assignment of cited lines to slots is what makes the rule apply.
MP_SYSTEM = """FormalSystem PropLogic:

    Regex atom:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z 0-9,]+$

    ProofContext:
        given: MatchSet()

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    formula:
        implication

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    statement_pattern.formula():
        return self.f

    statement_pattern.reference():
        return self.r

    LineType statement:
        pattern: statement_pattern
        behaviour: logical

    with p as formula, q as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                p

        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p -> q)
            deduction:
                q
"""


# A rule that cites two premises but permits additional (unconstrained) ones, to
# exercise the extra-antecedent branch of the assignment search.
EXTRA_SYSTEM = """FormalSystem Extra:

    Regex atom:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z 0-9,]+$

    ProofContext:
        given: MatchSet()

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    formula:
        implication

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    statement_pattern.formula():
        return self.f

    statement_pattern.reference():
        return self.r

    LineType statement:
        pattern: statement_pattern
        behaviour: logical

    with p as formula, q as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                p

        InferenceRule modus_ponens_extra:
            label:
                MPX
            antecedents:
                p
                (p -> q)
            deduction:
                q
            allow_extra_antecedents:
                True
"""


@pytest.fixture(scope="module")
def mp_system():
    return compiled(MP_SYSTEM)


@pytest.fixture(scope="module")
def extra_system():
    return compiled(EXTRA_SYSTEM)


def last_line(proof):
    return proof.proof_lines[-1]


# ---------------------------------------------------------------------------
# Antecedent assignment (bipartite matching)
# ---------------------------------------------------------------------------


def test_rule_applies_whatever_the_citation_order(mp_system):
    # The slots are (p, (p -> q)); the assignment search must fill them from the
    # cited lines whichever order they are named in.
    in_order = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [MP, 1, 2]")
    reversed_order = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [MP, 2, 1]")
    assert last_line(in_order).valid is True
    assert last_line(reversed_order).valid is True


def test_impossible_citation_is_rejected_without_raising(mp_system):
    # Neither cited line can fill the (p -> q) slot for conclusion c, so no
    # slot-saturating matching exists: the line is invalid, and crucially the
    # checker returns rather than raising.
    proof = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nc [MP, 1, 2]")
    line = last_line(proof)
    assert line.valid is False
    assert "does not apply" in line.invalid_message


def test_inconsistent_shared_metavariable_is_rejected(mp_system):
    # p is shared across both antecedents; citing a and (x -> b) cannot bind p
    # consistently, so the bipartite feasibility may pass but the authoritative
    # binding check rejects it.
    proof = mp_system.parse("a [HYP]\n(x -> b) [HYP]\nb [MP, 1, 2]")
    assert last_line(proof).valid is False


def test_extra_antecedent_is_accepted(extra_system):
    # MPX needs p and (p -> b); a third cited line is an allowed extra, so the
    # assignment search fills the two real slots and leaves the rest as extras.
    proof = extra_system.parse("a [HYP]\n(a -> b) [HYP]\nc [HYP]\nb [MPX, 1, 2, 3]")
    line = last_line(proof)
    assert line.valid is True
    assert len(line.antecedents) == 2
    assert len(line.extra_antecedents) == 1


def test_auto_justification_finds_antecedents_without_citation(mp_system):
    # With no cited lines, justify() reuses the same assignment search over the
    # accessible prior lines to discover a valid application.
    proof = mp_system.parse("a [HYP]\n(a -> b) [HYP]\nb [MP]")
    assert last_line(proof).valid is True


# ---------------------------------------------------------------------------
# Import / theorem dependency graph (graphlib)
# ---------------------------------------------------------------------------


def make_proof(system):
    return Proof(system)


def test_dependency_order_places_used_proofs_first(mp_system):
    base = make_proof(mp_system)
    middle = make_proof(mp_system)
    top = make_proof(mp_system)
    middle.proofs_used = {base}
    top.proofs_used = {middle}

    order = top.dependency_order()
    assert order.index(base) < order.index(middle) < order.index(top)


def test_no_circular_dependency_in_a_dag(mp_system):
    base = make_proof(mp_system)
    top = make_proof(mp_system)
    top.proofs_used = {base}
    assert top.circular_dependency() is None


def test_circular_dependency_is_detected(mp_system):
    a = make_proof(mp_system)
    b = make_proof(mp_system)
    a.proofs_used = {b}
    b.proofs_used = {a}

    cycle = a.circular_dependency()
    assert cycle is not None
    assert set(cycle) <= {a, b}
    assert cycle[0] == cycle[-1]
