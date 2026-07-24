"""Engine-level tests for the graph-backed proof checker:

* antecedent assignment via bipartite matching (InferenceRule.slot_admits +
  Proof._first_valid_assignment) - a rule applies regardless of the order its
  antecedents are cited, an impossible citation is rejected without raising, and
  extra antecedents are handled; and
* the graphlib-backed import/theorem dependency helpers on Proof
  (dependency_order / circular_dependency).

Both systems are assembled declaratively (`SystemSpec` + `build_system`), the
same build path the database and API use.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Rule, SystemSpec, build_system
from website.logical.formal_system import Proof

from tests.spec_helpers import brackets, hyp_rule, regex_prod, rule, statement_line, template_prod


def _pq():
    # A fresh binding list per call: specs must never alias a shared mutable list
    # (see tests/spec_helpers.py) — these module-level specs back module-scoped
    # fixtures, so an alias would outlive any single test.
    return [("p", "formula"), ("q", "formula")]


def _prop_productions():
    # An atom leaf plus `(p -> q)`; the ASCII arrow is what these proofs cite.
    return [
        regex_prod("formula", "atom", "[a-z]"),
        template_prod("formula", "implication", "(p -> q)", _pq()),
    ]


# Modus ponens: two antecedents (p and (p -> q)) sharing the metavariable p, so a
# correct assignment of cited lines to slots is what makes the rule apply. TRIP's
# three slots all bind the same p, exercising the incremental consistency prune.
MP_SYSTEM = SystemSpec(
    name="PropLogic",
    brackets=brackets(),
    productions=_prop_productions(),
    lines=[statement_line()],
    rules=[
        hyp_rule(),
        rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", _pq()),
        rule("TRIP", "triple", ["p", "p", "p"], "p", [("p", "formula")]),
    ],
)


# A rule that cites two premises but permits additional (unconstrained) ones, to
# exercise the extra-antecedent branch of the assignment search.
EXTRA_SYSTEM = SystemSpec(
    name="Extra",
    brackets=brackets(),
    productions=_prop_productions(),
    lines=[statement_line()],
    rules=[
        hyp_rule(),
        Rule(
            label="MPX",
            name="modus_ponens_extra",
            antecedents=["p", "(p -> q)"],
            deduction="q",
            bindings=_pq(),
            allow_extra_antecedents=True,
        ),
    ],
)


@pytest.fixture(scope="module")
def mp_system():
    return build_system(MP_SYSTEM)


@pytest.fixture(scope="module")
def extra_system():
    return build_system(EXTRA_SYSTEM)


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


def test_shared_metavariable_over_several_slots_accepts_consistent(mp_system):
    # TRIP has three slots all bound to p; three lines with the same formula are
    # a consistent assignment. The incremental prune must not reject it.
    proof = mp_system.parse("a [HYP]\na [HYP]\na [HYP]\na [TRIP, 1, 2, 3]")
    assert last_line(proof).valid is True


def test_shared_metavariable_over_several_slots_rejects_inconsistent(mp_system):
    # Three distinct formulae cannot all bind the shared p. Each is individually
    # admissible, so this is exactly the case the incremental prune must reject
    # cheaply (rather than exploring every ordering to a leaf check).
    proof = mp_system.parse("a [HYP]\nb [HYP]\nc [HYP]\na [TRIP, 1, 2, 3]")
    assert last_line(proof).valid is False


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


# ---------------------------------------------------------------------------
# import_path enforces the dependency check (FU4)
# ---------------------------------------------------------------------------


def importable_proof(system, reference):
    # A proof set up to import `reference` under the label "R".
    proof = Proof(system, reference_proofs={})
    proof.reference_context["R"] = reference
    return proof


def test_import_of_an_independent_result_succeeds(mp_system):
    dependency = make_proof(mp_system)
    proof = importable_proof(mp_system, dependency)

    result = proof.import_path("R", "imported", mp_system.context)
    assert result.success is True
    assert dependency in proof.proofs_used


def test_import_that_closes_a_cycle_is_rejected(mp_system):
    # The imported proof already (transitively) depends on the importer, so
    # importing it would make the proof justify itself.
    dependency = make_proof(mp_system)
    proof = importable_proof(mp_system, dependency)
    dependency.proofs_used = {proof}

    result = proof.import_path("R", "imported", mp_system.context)
    assert result.success is False
    assert "circular" in result.error_message.lower()
    # The dependency edge and label binding are backed out on rejection.
    assert dependency not in proof.proofs_used
    assert "imported" not in proof.reference_context


def test_cycle_rejection_restores_a_shadowed_label(mp_system):
    # A failed circular import that reuses an existing label must restore the
    # prior binding, not erase it (else earlier valid references would break).
    dependency = make_proof(mp_system)
    proof = importable_proof(mp_system, dependency)
    dependency.proofs_used = {proof}

    existing = make_proof(mp_system)
    proof.reference_context["dup"] = existing

    result = proof.import_path("R", "dup", mp_system.context)
    assert result.success is False
    # The pre-existing binding under "dup" survives the rejected import.
    assert proof.reference_context["dup"] is existing


# ---------------------------------------------------------------------------
# Relaxed antecedent cap (FU5): graceful invalid, not a server error
# ---------------------------------------------------------------------------


def test_oversized_citation_is_a_graceful_invalid_line(extra_system):
    # An extra-antecedent rule cited with more antecedents than the sanity bound
    # is marked invalid with a clear message, rather than raising a server error.
    from website.logical.formal_system.proof import MAX_CITED_ANTECEDENTS

    count = MAX_CITED_ANTECEDENTS + 1
    atoms = [chr(ord("a") + i) for i in range(count)]
    citation = ", ".join(str(i + 1) for i in range(count))
    lines = [f"{atom} [HYP]" for atom in atoms] + [f"b [MPX, {citation}]"]

    proof = extra_system.parse("\n".join(lines))
    line = last_line(proof)
    assert line.valid is False
    assert "too many antecedents" in line.invalid_message
