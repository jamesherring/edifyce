"""AtomPattern: atomic sorts without a regex, and discharge over the graph.

`AtomPattern` declares atoms two ways - a constant, or an infinite base+index
family (`p_i`) - with no regex engine. This module tests the primitive directly
and then builds a propositional natural-deduction system whose entire *term
algebra* (atoms, variables, formulae) is regex-free, and whose discharge rules
are checked on the kernel's term representation via `unify`.

Note on scope: the one remaining `Regex` below is `reference` - the surface
lexer for citation labels like "CP, 1". That is proof *surface syntax*, not part
of the formal system's term algebra; the logic itself (what the atoms and
formulae are) uses no regex.
"""

import pytest

pytest.importorskip("regex")

from copy import copy

from website.logical.compiler import compile as compile_formal_system
from website.logical.matching.patterns import AtomPattern


# ---------------------------------------------------------------------------
# The primitive
# ---------------------------------------------------------------------------


def test_constant_atom_matches_only_its_value():
    falsum = AtomPattern(name="falsum", value="⊥")
    assert falsum.is_member("⊥")
    assert not falsum.is_member("x")
    assert falsum.match("⊥", None) is not None
    assert falsum.match("x", None) is None


def test_indexed_family_is_infinite_and_canonical():
    var = AtomPattern(name="var", base="p")
    assert var.is_member("p")          # the bare base
    assert var.is_member("p_0")
    assert var.is_member("p_1")
    assert var.is_member("p_42")
    assert not var.is_member("q")      # different base
    assert not var.is_member("p_")     # missing index
    assert not var.is_member("p_01")   # non-canonical (leading zero)
    assert not var.is_member("p_x")    # non-numeric index


def test_family_can_construct_a_fresh_atom():
    var = AtomPattern(name="var", base="p")
    # The constructive advantage over a recogniser: there is always a next one.
    assert var.fresh(set()) == "p_0"
    assert var.fresh({"p_0", "p_1", "p_2"}) == "p_3"
    assert var.fresh({"p_0", "p_5"}) == "p_1"


def test_constant_and_family_are_mutually_exclusive():
    with pytest.raises(ValueError):
        AtomPattern(name="bad", value="⊥", base="p")
    with pytest.raises(ValueError):
        AtomPattern(name="bad")
    with pytest.raises(ValueError):
        AtomPattern(name="const", value="⊥").fresh(set())


# ---------------------------------------------------------------------------
# A regex-free-term-algebra propositional ND system, discharge via unify
# ---------------------------------------------------------------------------
REGEX_FREE = r"""FormalSystem RegexFree:

    Atom prop: p_#
    Atom falsum: ⊥

    UnionPattern formula:
        prop
        falsum

    Pattern implication:
        with a as formula, b as formula:
            (a → b)

    Pattern negation:
        with a as formula:
            ¬a

    formula:
        implication
        negation

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern statement:
        with f as formula, r as reference:
            f [r]
    Pattern assumption_pattern:
        with phi as formula:
            assume phi
    LineType claim:
        pattern: statement
        behaviour: logical
        formula: f
        reference: r
    LineType assume:
        pattern: assumption_pattern
        behaviour: logical
        scope: assumption
        formula: phi

    with a as formula, b as formula:

        InferenceRule reiteration:
            label:
                R
            antecedents:
                a
            deduction:
                a

        InferenceRule contradiction:
            label:
                X
            antecedents:
                a
                ¬a
            deduction:
                ⊥

        InferenceRule negation_intro:
            label:
                NI
            subproof:
                assume:
                    a
                derive:
                    ⊥
            deduction:
                ¬a

        InferenceRule conditional_proof:
            label:
                CP
            subproof:
                assume:
                    a
                derive:
                    b
            deduction:
                (a → b)
"""


@pytest.fixture(scope="module")
def regex_free():
    result = compile_formal_system(REGEX_FREE)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def test_atoms_declared_without_regex(regex_free):
    by_name = {p.name: p for p in regex_free.build_context.variables.values()
               if isinstance(p, AtomPattern)}
    assert by_name["prop"].base == "p"      # infinite family
    assert by_name["falsum"].value == "⊥"   # constant


def test_conditional_proof_over_the_family(regex_free):
    # Discharge is checked via unify.match_all on the term representation.
    proof = regex_free.parse("assume p_0\n    p_0 [R, 1]\n(p_0 → p_0) [CP, 1]")
    assert proof.valid is True


def test_uses_an_arbitrary_family_member(regex_free):
    # p_42 was never "declared" - the infinite family supplies it.
    proof = regex_free.parse("assume p_42\n    p_42 [R, 1]\n(p_42 → p_42) [CP, 1]")
    assert proof.valid is True


def test_negation_intro_with_literal_falsum_conclusion(regex_free):
    # p_0 → ¬¬p_0. The NI subproof's conclusion is the literal ⊥ - the case that
    # used to fail under unify. With AtomPattern it matches its declared atom.
    proof = regex_free.parse(
        "assume p_0\n"
        "    assume ¬p_0\n"
        "        ⊥ [X, 1, 2]\n"
        "    ¬¬p_0 [NI, 2]\n"
        "(p_0 → ¬¬p_0) [CP, 1]"
    )
    assert proof.valid is True, [(l.display, l.valid) for l in proof.proof_lines]


def test_cross_scope_discharge_still_rejected(regex_free):
    # Soundness is unchanged by the representation switch.
    proof = regex_free.parse(
        "assume p_0\n"
        "    p_0 [R, 1]\n"
        "assume p_1\n"
        "    p_0 [R, 2]\n"
        "(p_1 → p_0) [CP, 3]"
    )
    assert proof.valid is False
