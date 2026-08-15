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

Both systems are assembled declaratively (`SystemSpec` + `build_system`), the
same build path the database and API use.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Rule, Subproof, SystemSpec, build_system

from tests.spec_helpers import (
    assumption_line,
    atom_const_prod,
    brackets,
    cp_rule,
    implication_prod,
    mp_rule,
    negation_prod,
    regex_prod,
    reiteration_rule,
    rule,
    statement_line,
)


# ---------------------------------------------------------------------------
# 1. Hilbert-style system: axiom schemas as zero-premise rules, plus MP.
#    No assumptions, no `scope:` lines - the deduction theorem is a metatheorem
#    here, not an object-level rule, and the scope machinery stays inert.
# ---------------------------------------------------------------------------
_HILBERT_BINDINGS = [("p", "formula"), ("q", "formula"), ("r", "formula")]
HILBERT = SystemSpec(
    name="Hilbert",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        implication_prod(),
    ],
    lines=[statement_line()],
    rules=[
        rule("K", "axiom_k", [], "(p → (q → p))", _HILBERT_BINDINGS),
        rule("S", "axiom_s", [], "((p → (q → r)) → ((p → q) → (p → r)))", _HILBERT_BINDINGS),
        mp_rule(),
    ],
)


@pytest.fixture(scope="module")
def hilbert():
    return build_system(HILBERT)


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
NEG = SystemSpec(
    name="Neg",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        atom_const_prod("formula", "falsum", "⊥"),
        negation_prod(),
        implication_prod(),
    ],
    lines=[statement_line(), assumption_line()],
    rules=[
        reiteration_rule(),  # R
        rule("X", "contradiction", ["p", "¬p"], "⊥", [("p", "formula")]),
        Rule(
            label="NI",
            name="negation introduction",
            antecedents=[],
            deduction="¬p",
            bindings=[("p", "formula")],
            subproof=Subproof(assume="p", derive="⊥"),
        ),
        cp_rule(),  # CP
    ],
)


@pytest.fixture(scope="module")
def neg():
    return build_system(NEG)


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
