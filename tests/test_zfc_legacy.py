"""The legacy ZFC-style system: what works, and where it is unsound.

These tests pin the *current* behaviour of the pre-existing engine so the
scoped-subproof rework has a concrete baseline to improve on. Two of them
assert behaviour that is logically *wrong* (a bogus theorem is accepted); they
are marked clearly and are the motivation for ``test_zfc_scoped.py``.
"""

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system

from zfc_systems import LEGACY_ZFC


@pytest.fixture(scope="module")
def legacy():
    result = compile_formal_system(LEGACY_ZFC)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def valid(system, text):
    return system.parse(text).valid


# ---------------------------------------------------------------------------
# What the legacy system gets right
# ---------------------------------------------------------------------------


def test_modus_ponens(legacy):
    proof = legacy.parse("a ∈ b [HYP]\n(a ∈ b → c ∈ d) [HYP]\nc ∈ d [MP, 1, 2]")
    # The two HYPs are not inside any assumption block, so `given` is empty and
    # they do not check out - but the MP step itself is structurally valid.
    assert proof.proof_lines[2].valid is True


def test_hypothesis_available_inside_its_block(legacy):
    # An `assume` block adds its formula to `given`; HYP then cites it.
    assert valid(legacy, "assume a ∈ b:\n    a ∈ b [HYP]") is True


def test_conditional_proof_self_implication(legacy):
    # (a ∈ b → a ∈ b): assume a∈b, reiterate it, discharge with CP.
    proof = legacy.parse(
        "assume a ∈ b:\n"
        "    a ∈ b [HYP]\n"
        "(a ∈ b → a ∈ b) [CP, 1, 2]"
    )
    assert proof.valid is True


# ---------------------------------------------------------------------------
# Where the legacy system is UNSOUND (documented, to be fixed by the rework)
# ---------------------------------------------------------------------------


def test_cross_scope_reiteration_is_wrongly_accepted(legacy):
    # Line 4 sits inside the `assume b∈c` block but cites line 2, a hypothesis
    # local to the *already-closed* `assume a∈b` block. In natural deduction
    # that hypothesis was discharged when its block closed and must not be
    # reachable here. The legacy engine does not scope-check references, so it
    # accepts the citation. This is the core defect.
    proof = legacy.parse(
        "assume a ∈ b:\n"
        "    a ∈ b [HYP]\n"
        "assume b ∈ c:\n"
        "    a ∈ b [R, 2]"
    )
    assert proof.proof_lines[3].valid is True  # WRONG: should be rejected


def test_bogus_theorem_is_wrongly_accepted(legacy):
    # Consequence of the defect above: a conditional proof whose body smuggles
    # in a hypothesis from a closed sibling block "proves" (b∈c → a∈b) for
    # unrelated a, b, c. A sound checker must reject this.
    bogus = (
        "assume a ∈ b:\n"
        "    a ∈ b [HYP]\n"
        "assume b ∈ c:\n"
        "    a ∈ b [R, 2]\n"
        "(b ∈ c → a ∈ b) [CP, 3, 4]"
    )
    proof = legacy.parse(bogus)
    assert proof.valid is True  # WRONG: (b∈c → a∈b) is not a theorem
