"""The scoped-subproof engine: the same ZFC theorems, checked soundly.

This is the target behaviour for the rework. Written before the engine
changes (TDD): assumptions open first-class subproofs, references are
scope-checked, and discharge rules (`CP`/`UG`) consume a whole subproof.
"""

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system

from zfc_systems import SCOPED_ZFC


@pytest.fixture(scope="module")
def scoped():
    result = compile_formal_system(SCOPED_ZFC)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def line_states(proof):
    return [(l.display, l.valid) for l in proof.proof_lines]


# ---------------------------------------------------------------------------
# Orthogonal scope attribute (recommendation A)
# ---------------------------------------------------------------------------


def test_scope_attribute_compiles(scoped):
    by_name = {lt.name: lt for lt in scoped.line_types}
    assume = by_name["assume"]
    # A single line type is BOTH a logical (formula-bearing) line AND a
    # scope opener - the two concerns are no longer fused into `behaviour`.
    assert assume.behaviour == "logical"
    assert assume.scope == "assumption"


def test_assumption_is_valid_without_justification(scoped):
    proof = scoped.parse("assume a ∈ b")
    assert proof.proof_lines[0].valid is True
    assert proof.proof_lines[0].formula is not None


# ---------------------------------------------------------------------------
# Scope-checked references (the soundness core)
# ---------------------------------------------------------------------------


def test_reference_within_scope_is_accessible(scoped):
    # Line 2 reiterates line 1 (the assumption) - same scope, accessible.
    proof = scoped.parse("assume a ∈ b\n    a ∈ b [R, 1]")
    assert proof.proof_lines[1].valid is True


def test_reference_into_closed_sibling_scope_is_rejected(scoped):
    # The cross-scope defect the legacy engine had: line 4 cites line 2,
    # which lives inside the already-closed subproof opened at line 1.
    proof = scoped.parse(
        "assume a ∈ b\n"
        "    a ∈ b [R, 1]\n"
        "assume b ∈ c\n"
        "    a ∈ b [R, 2]"
    )
    assert proof.proof_lines[3].valid is False
    assert "scope" in (proof.proof_lines[3].invalid_message or "").lower()


# ---------------------------------------------------------------------------
# Discharge rules (recommendation C): →I as a first-class subproof rule
# ---------------------------------------------------------------------------


def test_conditional_proof_self_implication(scoped):
    proof = scoped.parse(
        "assume a ∈ b\n"
        "    a ∈ b [R, 1]\n"
        "(a ∈ b → a ∈ b) [CP, 1]"
    )
    assert proof.valid is True, line_states(proof)


def test_conditional_proof_conclusion_may_be_the_assumption(scoped):
    # A one-line subproof: its conclusion is the assumption itself.
    proof = scoped.parse("assume a ∈ b\n(a ∈ b → a ∈ b) [CP, 1]")
    assert proof.valid is True, line_states(proof)


def test_nested_conditional_proof(scoped):
    # (a∈b → (c∈d → a∈b)): →I nested inside →I, discharged from the outside in.
    proof = scoped.parse(
        "assume a ∈ b\n"
        "    assume c ∈ d\n"
        "        a ∈ b [R, 1]\n"
        "    (c ∈ d → a ∈ b) [CP, 2]\n"
        "(a ∈ b → (c ∈ d → a ∈ b)) [CP, 1]"
    )
    assert proof.valid is True, line_states(proof)


def test_cannot_discharge_a_still_open_subproof(scoped):
    # Discharging from *inside* the subproof would let it consume itself.
    proof = scoped.parse("assume a ∈ b\n    (a ∈ b → a ∈ b) [CP, 1]")
    assert proof.proof_lines[1].valid is False


def test_discharge_reference_must_open_a_subproof(scoped):
    # CP must cite a subproof opener, not an arbitrary line.
    proof = scoped.parse(
        "assume a ∈ b\n"
        "    a ∈ b [R, 1]\n"
        "(a ∈ b → a ∈ b) [CP, 2]"
    )
    assert proof.proof_lines[2].valid is False


def test_bogus_theorem_is_rejected(scoped):
    # The legacy system "proves" this; the scoped system must not.
    bogus = (
        "assume a ∈ b\n"
        "    a ∈ b [R, 1]\n"
        "assume b ∈ c\n"
        "    a ∈ b [R, 2]\n"
        "(b ∈ c → a ∈ b) [CP, 3]"
    )
    proof = scoped.parse(bogus)
    assert proof.valid is False


def test_conditional_proof_requires_matching_conclusion(scoped):
    # CP must actually check the subproof's conclusion against q; you cannot
    # discharge to an implication whose consequent was never derived.
    proof = scoped.parse(
        "assume a ∈ b\n"
        "    a ∈ b [R, 1]\n"
        "(a ∈ b → c ∈ d) [CP, 1]"
    )
    assert proof.proof_lines[2].valid is False


# ---------------------------------------------------------------------------
# Universal generalisation: a variable-opened subproof + freshness (via kernel)
# ---------------------------------------------------------------------------


def test_variable_scope_attribute(scoped):
    by_name = {lt.name: lt for lt in scoped.line_types}
    assert by_name["introduce"].scope == "variable"


def test_universal_generalisation_sound(scoped):
    # ∀x (x ∈ c → x ∈ c): introduce an arbitrary x, prove (x∈c → x∈c) under it
    # with CP, then generalise. x is fresh (no enclosing hypothesis mentions it).
    proof = scoped.parse(
        "let x\n"
        "    assume x ∈ c\n"
        "        x ∈ c [R, 2]\n"
        "    (x ∈ c → x ∈ c) [CP, 2]\n"
        "∀x (x ∈ c → x ∈ c) [UG, 1]"
    )
    assert proof.valid is True, line_states(proof)


def test_universal_generalisation_freshness_violation_rejected(scoped):
    # x is NOT arbitrary here: it occurs in the enclosing hypothesis `x ∈ c`,
    # so generalising over it (which would let CP derive x∈c → ∀x x∈c) is
    # unsound. The freshness side-condition rejects the UG step.
    proof = scoped.parse(
        "assume x ∈ c\n"
        "    let x\n"
        "        x ∈ c [R, 1]\n"
        "    ∀x x ∈ c [UG, 2]"
    )
    assert proof.proof_lines[3].valid is False


def test_ug_rejects_generalising_a_variable_from_an_undischarged_assumption(scoped):
    # PR #19 review (P1): opening the subproof with a *different* fresh variable
    # (`let y`) than the one generalised (`∀x`) must not sneak past freshness.
    # Here x occurs in the still-open assumption `x ∈ c`, so ∀x x∈c is unsound;
    # the eigenvariable must be tied to the quantified variable.
    proof = scoped.parse(
        "assume x ∈ c\n"
        "    let y\n"
        "        x ∈ c [R, 1]\n"
        "    ∀x x ∈ c [UG, 2]"
    )
    assert proof.proof_lines[3].valid is False


def test_ug_requires_the_opener_to_be_the_generalised_variable(scoped):
    # Introducing `let x` but concluding `∀y …` generalises a variable that was
    # never the arbitrary one; the opener/quantifier mismatch is rejected.
    proof = scoped.parse(
        "let x\n"
        "    assume x ∈ c\n"
        "        x ∈ c [R, 2]\n"
        "    (x ∈ c → x ∈ c) [CP, 2]\n"
        "∀y (x ∈ c → x ∈ c) [UG, 1]"
    )
    assert proof.proof_lines[4].valid is False


def test_imported_line_from_another_proof_is_accessible():
    # PR #19 review (P2): scope-checking is intra-proof. A line cited from a
    # different proof (an imported result) has an unrelated scope root and must
    # not be rejected as "out of scope" - cross-proof citation is governed by
    # import validation instead.
    from website.logical.formal_system.proof import Proof, ProofLine, line_is_accessible
    from website.logical.matching import Context

    context = Context()
    proof_a = Proof(formal_system=None)
    proof_b = Proof(formal_system=None)

    line_a = ProofLine(proof_a, "a", context)
    line_b = ProofLine(proof_b, "b", context)
    proof_a.assign_scope(line_a)
    proof_b.assign_scope(line_b)

    # Different proofs, different (non-None) scope roots - still accessible.
    assert line_a.scope is not line_b.scope
    assert line_is_accessible(line_b, line_a) is True
    assert line_is_accessible(line_a, line_b) is True


def test_universal_generalisation_over_genuinely_fresh_var_ok(scoped):
    # Here the eigenvariable x does not occur in the enclosing hypothesis
    # (which is about y), so ∀x y∈c is a sound - if vacuous - generalisation.
    # Freshness must permit this: it constrains only the eigenvariable itself.
    proof = scoped.parse(
        "assume y ∈ c\n"
        "    let x\n"
        "        y ∈ c [R, 1]\n"
        "    ∀x y ∈ c [UG, 2]"
    )
    assert proof.proof_lines[3].valid is True, line_states(proof)
