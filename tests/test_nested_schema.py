"""Nested rule-schema templates under the term-based checker.

A rule schema like a Hilbert axiom ``K = (p -> (q -> p))`` is written as one
template string but denotes a *nested* structure - an implication whose right
side is itself an implication. The term-based checker matches a rule's schema
against a proof formula by comparing their term trees, and a proof formula is
built up compositionally from the system's productions. For the two to match,
the schema must be projected to the *same* nested tree, not one flat production.

These tests pin that: axiom instances (K, S) validate, single-level schemas
(modus ponens) are unaffected, and the projected schema term nests.
"""

import pytest

pytest.importorskip("regex")

from copy import copy

from website.logical.compiler import compile as compile_formal_system
from website.logical.kernel import from_match
from website.logical.kernel.terms import _signature


# A minimal Hilbert-style implication system: axiom schemas as zero-premise
# rules (K, S), plus modus ponens. Deeply nested axiom templates are the point.
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
    result = compile_formal_system(HILBERT)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def rule(system, label):
    return next(r for r in system.inference_rules if r.label == label)


# ---------------------------------------------------------------------------
# The projected schema term nests (the mechanism)
# ---------------------------------------------------------------------------


def test_nested_axiom_schema_projects_to_a_nested_term(hilbert):
    # K = (p -> (q -> p)) must project to an implication whose right child is
    # itself an implication - top-level constructor "( _ -> _ )", NOT the flat
    # three-hole "( _ -> ( _ -> _ ) )".
    k = rule(hilbert, "K")
    term = k._schema_term(k.deduction, 0, copy(hilbert.context))

    # Top constructor is a single implication (two holes), NOT the flat
    # three-hole "( _ -> ( _ -> _ ) )".
    assert _signature(term.pattern) == ("string", "(\x00 → \x00)")
    # One child is itself an implication (the nesting survived), the other a
    # bare variable leaf.
    child_sigs = {
        _signature(child.pattern) for child in term.children.values() if hasattr(child, "pattern")
    }
    assert ("string", "(\x00 → \x00)") in child_sigs
    # And it round-trips to the original surface template.
    assert term.to_string() == "(p → (q → p))"


def test_schema_term_matches_a_parsed_formula_of_the_same_shape(hilbert):
    # The projected K schema and a real K instance share a top constructor, so
    # unification can even begin (the old flat projection differed here).
    k = rule(hilbert, "K")
    schema = k._schema_term(k.deduction, 0, copy(hilbert.context))
    instance = from_match(
        hilbert.parse("(a → ((a → a) → a)) [K]").proof_lines[0].formula,
        copy(hilbert.context),
    )
    assert _signature(schema.pattern) == _signature(instance.pattern)


# ---------------------------------------------------------------------------
# End-to-end: axiom instances validate
# ---------------------------------------------------------------------------


def test_k_axiom_instance_validates(hilbert):
    proof = hilbert.parse("(a → ((a → a) → a)) [K]")
    assert proof.proof_lines[0].valid is True


def test_s_axiom_instance_validates(hilbert):
    proof = hilbert.parse(
        "((a → ((a → a) → a)) → ((a → (a → a)) → (a → a))) [S]"
    )
    assert proof.proof_lines[0].valid is True


def test_full_self_implication_derivation(hilbert):
    # The classic S/K/MP derivation of a -> a, with no assumptions anywhere.
    proof = hilbert.parse(
        "((a → ((a → a) → a)) → ((a → (a → a)) → (a → a))) [S]\n"
        "(a → ((a → a) → a)) [K]\n"
        "((a → (a → a)) → (a → a)) [MP, 1, 2]\n"
        "(a → (a → a)) [K]\n"
        "(a → a) [MP, 3, 4]"
    )
    assert proof.valid is True, [(l.display, l.valid) for l in proof.proof_lines]


# ---------------------------------------------------------------------------
# Soundness preserved: non-instances still rejected
# ---------------------------------------------------------------------------


def test_non_instance_of_axiom_is_rejected(hilbert):
    # (a → (b → c)) is NOT an instance of K = (p → (q → p)): the third slot
    # must repeat the first. The shared binding across the nested term must
    # still enforce that - nesting the schema must not weaken it.
    proof = hilbert.parse("(a → (b → c)) [K]")
    assert proof.proof_lines[0].valid is False


def test_every_template_metavariable_stays_schematic(hilbert):
    # Every metavariable in a projected schema is a free Var, none fixed to a
    # literal token.
    k = rule(hilbert, "K")
    term = k._schema_term(k.deduction, 0, copy(hilbert.context))
    assert set(term.free_vars()) == {"p", "q"}


def test_regex_sorted_metavariable_is_kept_schematic():
    # A slot matched by a RegexPattern (a `setvar`) is not recognised as a
    # metavariable during the compositional parse, so it returns as a literal
    # leaf and must be re-marked as a Var - otherwise the ∀I deduction `∀x p`
    # would fix its bound variable to the literal token "x", silently breaking
    # the eigenvariable/quantifier tie. Pin that the `x` stays schematic.
    from zfc_systems import SCOPED_ZFC

    system = compile_formal_system(SCOPED_ZFC)["system"]
    ug = rule(system, "UG")  # deduction: ∀x p, with x a setvar
    term = ug._schema_term(ug.deduction, 0, copy(system.context))
    assert set(term.free_vars()) == {"x", "p"}


def test_modus_ponens_single_level_unaffected(hilbert):
    # MP (a single-level schema) worked before and after: from a K instance and
    # a K instance of the form (that → …), MP peels the top implication.
    proof = hilbert.parse(
        "(a → (b → a)) [K]\n"                         # p := (a → (b → a))
        "((a → (b → a)) → (c → (a → (b → a)))) [K]\n"  # (p → q)
        "(c → (a → (b → a))) [MP, 1, 2]"              # q
    )
    assert proof.proof_lines[2].valid is True, [(l.display, l.valid) for l in proof.proof_lines]
