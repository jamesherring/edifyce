"""The engine hosts the *mechanism*; each system supplies its own *logic*.

Two checks that the scoped-subproof rework did not smuggle logic into the
engine:

1. A system with no ``scope`` line types (a Hilbert-style axioms-plus-MP
   system) is wholly unaffected - no subproofs are created and every line sits
   in the root scope. Simpler systems stay fully compatible.

2. The discharge *mechanism* is not tied to implication: the same engine
   expresses negation-introduction (reductio), whose conclusion is a negation,
   purely from source. What a discharge rule concludes lives in the system, not
   the engine.
"""

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


# ---------------------------------------------------------------------------
# 1. Hilbert-style system: axiom schemas as zero-premise rules, plus MP.
#    No assumptions, no `scope:` lines - the deduction theorem is a metatheorem
#    here, not an object-level rule, and the scope machinery stays inert.
# ---------------------------------------------------------------------------
HILBERT = r"""FormalSystem Hilbert:

    Regex atom:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    formula:
        implication

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern statement:
        with f as formula, r as reference:
            f [r]

    statement.formula():
        return self.f
    statement.reference():
        return self.r

    LineType claim:
        pattern: statement
        behaviour: logical

    with p as formula, q as formula, r as formula:

        InferenceRule axiom_k:
            label:
                K
            deduction:
                (p → (q → p))

        InferenceRule axiom_s:
            label:
                S
            deduction:
                ((p → (q → r)) → ((p → q) → (p → r)))

        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p → q)
            deduction:
                q
"""


@pytest.fixture(scope="module")
def hilbert():
    return compiled(HILBERT)


def test_hilbert_proves_self_implication_without_assumptions(hilbert):
    # The classic S/K/MP derivation of a -> a: no assumption anywhere.
    proof = hilbert.parse(
        "((a → ((a → a) → a)) → ((a → (a → a)) → (a → a))) [S]\n"
        "(a → ((a → a) → a)) [K]\n"
        "((a → (a → a)) → (a → a)) [MP, 1, 2]\n"
        "(a → (a → a)) [K]\n"
        "(a → a) [MP, 3, 4]"
    )
    assert proof.valid is True


def test_scope_machinery_is_inert_without_scope_lines(hilbert):
    proof = hilbert.parse("(a → (b → a)) [K]")
    # Every line lands in the single root scope; no subproofs are ever created.
    assert all(line.scope is proof.root_scope for line in proof.proof_lines)
    assert proof.root_scope.children == []
    assert proof.root_scope.kind is None


# ---------------------------------------------------------------------------
# 2. The same discharge mechanism, a different conclusion: negation
#    introduction (reductio). Its deduction is a negation, not an implication.
# ---------------------------------------------------------------------------
NEG = r"""FormalSystem Neg:

    Regex atom:
        ^[a-z][a-z0-9]*$

    Regex falsum:
        ^⊥$

    UnionPattern formula:
        atom
        falsum

    Pattern negation:
        with p as formula:
            ¬p

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    formula:
        negation
        implication

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern statement:
        with f as formula, r as reference:
            f [r]

    statement.formula():
        return self.f
    statement.reference():
        return self.r

    Pattern assumption_pattern:
        with phi as formula:
            assume phi

    assumption_pattern.formula():
        return self.phi

    LineType claim:
        pattern: statement
        behaviour: logical

    LineType assume:
        pattern: assumption_pattern
        behaviour: logical
        scope: assumption

    with p as formula, q as formula:

        InferenceRule reiteration:
            label:
                R
            antecedents:
                p
            deduction:
                p

        InferenceRule contradiction:
            label:
                X
            antecedents:
                p
                ¬p
            deduction:
                ⊥

        InferenceRule negation_intro:
            label:
                NI
            subproof:
                assume:
                    p
                derive:
                    ⊥
            deduction:
                ¬p

        InferenceRule conditional_proof:
            label:
                CP
            subproof:
                assume:
                    p
                derive:
                    q
            deduction:
                (p → q)
"""


@pytest.fixture(scope="module")
def neg():
    return compiled(NEG)


def test_negation_introduction_is_a_discharge_rule(neg):
    # a -> ¬¬a: ¬I (conclusion a negation) nested inside ->I - same mechanism.
    proof = neg.parse(
        "assume a\n"
        "    assume ¬a\n"
        "        ⊥ [X, 1, 2]\n"
        "    ¬¬a [NI, 2]\n"
        "(a → ¬¬a) [CP, 1]"
    )
    assert proof.valid is True, [(l.display, l.valid) for l in proof.proof_lines]


def test_negation_introduction_is_scope_checked(neg):
    # The soundness guarantee is the mechanism's, not any one rule's: ¬I cannot
    # discharge a subproof opened in a closed sibling scope either.
    proof = neg.parse(
        "assume a\n"
        "    assume ¬a\n"
        "        ⊥ [X, 1, 2]\n"
        "assume b\n"
        "    ¬¬a [NI, 2]"
    )
    assert proof.proof_lines[4].valid is False
