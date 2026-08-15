"""AtomPattern: atomic sorts without a regex, and discharge over the graph.

`AtomPattern` declares atoms two ways - a constant, or an infinite base+index
family (`p_i`) - with no regex engine. This module tests the primitive directly
and then builds a propositional natural-deduction system whose entire *term
algebra* (atoms, variables, formulae) is regex-free, and whose discharge rules
are checked on the kernel's term representation via `unify`.

The system is assembled declaratively (`regex_free_spec` + `build_spec`), the
same build path the database and API use. Note on scope: the one remaining regex
is the `reference` line part - the surface lexer for citation labels like
"CP, 1". That is proof *surface syntax*, not part of the formal system's term
algebra; the logic itself (what the atoms and formulae are) uses no regex.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Rule, Subproof, SystemSpec, build_spec
from website.logical.matching.patterns import AtomPattern

from tests.spec_helpers import (
    assumption_line,
    atom_const_prod,
    atom_family_prod,
    brackets,
    rule,
    statement_line,
    template_prod,
)


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
def regex_free_spec() -> SystemSpec:
    """A propositional ND system whose whole term algebra is regex-free.

    Every formula is built from atoms only -- the infinite family ``p_#`` and the
    constant ``⊥`` -- plus implication and negation. The discharge rules (``NI``,
    ``CP``) are checked on the kernel term representation via ``unify``. The
    metavariables are ``a``/``b`` (not ``p``): ``p`` is a concrete atom of the
    family, so a schema variable named ``p`` would collide with it.
    """
    return SystemSpec(
        name="RegexFree",
        brackets=brackets(),
        productions=[
            atom_family_prod("formula", "prop", "p"),   # p, p_0, p_1, … (infinite)
            atom_const_prod("formula", "falsum", "⊥"),  # the single literal ⊥
            template_prod("formula", "implication", "(a → b)", [("a", "formula"), ("b", "formula")]),
            template_prod("formula", "negation", "¬a", [("a", "formula")]),
        ],
        lines=[statement_line(), assumption_line()],
        rules=[
            rule("R", "reiteration", ["a"], "a", [("a", "formula")]),
            rule("X", "contradiction", ["a", "¬a"], "⊥", [("a", "formula")]),
            Rule(
                label="NI",
                name="negation introduction",
                antecedents=[],
                deduction="¬a",
                bindings=[("a", "formula")],
                subproof=Subproof(assume="a", derive="⊥"),
            ),
            Rule(
                label="CP",
                name="conditional proof",
                antecedents=[],
                deduction="(a → b)",
                bindings=[("a", "formula"), ("b", "formula")],
                subproof=Subproof(assume="a", derive="b"),
            ),
        ],
    )


@pytest.fixture(scope="module")
def regex_free():
    result = build_spec(regex_free_spec())
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
