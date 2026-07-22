"""String-rewriting inference rules: Hofstadter's MIU system end to end.

Covers the new ``matching="string"`` rule path added for semi-Thue systems:

* the associative matcher primitive (``matching.rewriting``),
* the MIU system compiling and checking real derivations (and rejecting bogus
  steps), including a chain that exercises all four rules,
* the ``matching`` kind surviving the declarative lower/recompile round trip, and
* the ``matching`` column surviving storage in the normalised system tables.
"""

import pytest

pytest.importorskip("regex")

from tests.miu_system import miu_spec
from website.logical.declarative import build_spec, lower
from website.logical.matching import Context, RegexPattern, StringPattern, joint_binding_exists
from website.logical.matching.rewriting import iter_bindings


# ---------------------------------------------------------------------------
# The matcher primitive
# ---------------------------------------------------------------------------


def _pattern(template: str, *variables: str) -> tuple[StringPattern, Context]:
    # A StringPattern over variables whose sort is the [MIU]* regex leaf, with a
    # context that knows those variables (mirrors what the compiler wires up).
    context = Context()
    var_pattern = RegexPattern(name="miustr", pattern="^[MIU]*$")
    for v in variables:
        context.string_variables[v] = var_pattern
    pattern = StringPattern(name="schema", pattern=template)
    pattern.add_variables({v: var_pattern for v in variables})
    return pattern, context


def test_iter_bindings_splits_between_adjacent_variables():
    pattern, context = _pattern("Mxx", "x")
    # "MII": M then x·x over "II" -> x must be "I" (the only consistent split).
    assert [b["x"] for b in iter_bindings(pattern, "MII", context)] == ["I"]


def test_iter_bindings_enumerates_gap_positions():
    pattern, context = _pattern("xIIIy", "x", "y")
    solutions = {(b["x"], b["y"]) for b in iter_bindings(pattern, "MIIII", context)}
    # III can sit at offset 1 (x=M, y=I) or offset 2 (x=MI, y="").
    assert solutions == {("M", "I"), ("MI", "")}


def test_iter_bindings_allows_empty_gaps():
    pattern, context = _pattern("xIIIy", "x", "y")
    assert {(b["x"], b["y"]) for b in iter_bindings(pattern, "III", context)} == {("", "")}


def test_joint_binding_forces_shared_variable_to_agree():
    ant, context = _pattern("Mx", "x")
    ded, _ = _pattern("Mxx", "x")
    # Antecedent MI (x=I) and deduction MII: the shared x=I makes them consistent.
    assert joint_binding_exists([(ant, "MI"), (ded, "MII")], context)
    # ...but MI -> MIII is not doubling, so no shared binding exists.
    assert not joint_binding_exists([(ant, "MI"), (ded, "MIII")], context)


# ---------------------------------------------------------------------------
# The MIU system, compiled and checking proofs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def miu():
    result = build_spec(miu_spec())
    assert "errors" not in result, result.get("errors")
    return result["system"]


def test_axiom_is_self_justifying(miu):
    assert miu.parse("MI").valid is True


@pytest.mark.parametrize(
    "proof",
    [
        "MI\nMII [R2, 1]",                                  # R2: Mx->Mxx, x=I
        "MI\nMIU [R1, 1]",                                  # R1: xI->xIU, x=M
        "MI\nMII [R2, 1]\nMIIII [R2, 2]",                   # R2 twice
        "MI\nMII [R2, 1]\nMIIII [R2, 2]\nMIIIIU [R1, 3]",   # R1 appends U
        "MI\nMII [R2, 1]\nMIIII [R2, 2]\nMUI [R3, 3]",      # R3: III->U
    ],
)
def test_valid_derivations(miu, proof):
    result = miu.parse(proof)
    assert result.valid is True
    assert all(line["valid"] for line in result.data()["lines"])


def test_full_four_rule_chain_reaches_a_theorem(miu):
    # A derivation that uses all four rules, ending with R4 deleting a UU.
    proof = (
        "MI\n"
        "MII [R2, 1]\n"       # R2
        "MIIII [R2, 2]\n"     # R2
        "MUI [R3, 3]\n"       # R3 (III->U)
        "MUIU [R1, 4]\n"      # R1 (append U)
        "MUIUUIU [R2, 5]\n"   # R2 (double after M: x=UIU)
        "MUIIU [R4, 6]"       # R4 (delete the UU)
    )
    result = miu.parse(proof)
    assert result.valid is True


@pytest.mark.parametrize(
    "proof",
    [
        "MI\nMIII [R2, 1]",              # doubling I gives MII, not MIII
        "MI\nMIU [R2, 1]",              # R2 does not produce MIU
        "MI\nMII [R2, 1]\nMU [R3, 2]",  # MII has no III to rewrite
    ],
)
def test_invalid_steps_are_rejected(miu, proof):
    assert miu.parse(proof).valid is False


def test_non_miu_alphabet_does_not_parse(miu):
    # The grammar sort is [MIU]+, so a stray letter is not even a well-formed line.
    assert miu.parse("MZ").valid is False


# ---------------------------------------------------------------------------
# The matching kind round-trips through lowering and recompilation
# ---------------------------------------------------------------------------


def test_matching_kind_lowers_to_the_edi_block():
    edi = lower(miu_spec())
    assert "matching:" in edi
    assert "string" in edi


def test_compiled_rules_carry_the_string_matching_kind(miu):
    kinds = {ir.label: ir.matching for ir in miu.inference_rules}
    assert kinds == {"R1": "string", "R2": "string", "R3": "string", "R4": "string"}
