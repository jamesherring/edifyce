"""The direct `SystemSpec → FormalSystem` builder matches the .edi round-trip.

`declarative.build_system` constructs a `FormalSystem` straight from a
`SystemSpec` by calling the engine's construction primitives directly. This is a
differential guard: for a corpus spanning the declarative feature matrix, the
directly-built system must be *structurally equivalent* to the one produced by
the old text path (`compile(lower(spec))` + the post-compile bracket patch) and
must *check the same proofs the same way*.
"""

import pytest

pytest.importorskip("regex")

from copy import copy

from tests.spec_helpers import (
    axiom,
    biconditional_prod,
    brackets,
    conjunction_prod,
    defn,
    disjunction_prod,
    equality_prod,
    existential_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    negation_prod,
    regex_prod,
    rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)
from website.logical.compiler import compile as compile_edi
from website.logical.declarative import (
    LineSpec,
    SystemSpec,
    _bracket_map,
    build_system,
    lower,
)
from website.logical.matching import Pattern


# ---------------------------------------------------------------------------
# The oracle: the old text path (compile the lowered .edi, then patch brackets
# on every reachable pattern — exactly what `build_spec` did before the direct
# builder replaced it).
# ---------------------------------------------------------------------------


def _patch_brackets(system, mapping):
    if not mapping:
        return
    seen: set[int] = set()

    def walk(pattern):
        if pattern is None or id(pattern) in seen:
            return
        seen.add(id(pattern))
        if hasattr(pattern, "respect_brackets"):
            pattern.respect_brackets = mapping
        for sub in getattr(pattern, "patterns", []) or []:
            walk(sub)
        for sub in (getattr(pattern, "variables", {}) or {}).values():
            walk(sub)

    for value in system.context.variables.values():
        if hasattr(value, "respect_brackets"):
            walk(value)


def _oracle(spec):
    system = compile_edi(lower(spec))["system"]
    _patch_brackets(system, _bracket_map(spec))
    return system


def _assert_structurally_equivalent(direct, oracle):
    # A context whose variables are populated, so pattern `.equivalent` can
    # resolve sort references.
    ctx = copy(oracle.build_context)

    assert direct.name == oracle.name
    assert [lt.name for lt in direct.line_types] == [lt.name for lt in oracle.line_types]
    assert [r.label for r in direct.inference_rules] == [r.label for r in oracle.inference_rules]
    assert set(direct.context.variables) == set(oracle.context.variables)
    assert len(direct.context.definitions) == len(oracle.context.definitions)

    for a, b in zip(direct.line_types, oracle.line_types):
        assert a.equivalent(b, ctx), f"line type {a.name} differs"
    for a, b in zip(direct.inference_rules, oracle.inference_rules):
        assert a.equivalent(b, ctx), f"inference rule {a.label} differs"
    # Compare the Pattern-valued build variables (the grammar). Non-pattern
    # entries — the system-under-its-name and the line types — are covered above;
    # comparing the system self-reference would recurse into `context.equivalent`,
    # which cannot handle a fresh proof context's `reference_object is None`.
    for key in direct.context.variables:
        dv, ov = direct.context.variables[key], oracle.context.variables[key]
        if isinstance(dv, Pattern) and isinstance(ov, Pattern):
            assert dv.equivalent(ov, ctx), f"variable {key} differs"


def _assert_same_proofs(direct, oracle, proofs):
    for proof in proofs:
        d = direct.parse(proof)
        o = oracle.parse(proof)
        assert d.valid == o.valid, f"validity differs for {proof!r}: {d.valid} vs {o.valid}"
        assert [ln["valid"] for ln in d.data()["lines"]] == [
            ln["valid"] for ln in o.data()["lines"]
        ], f"per-line validity differs for {proof!r}"


# ---------------------------------------------------------------------------
# Corpus: one entry per feature combination, with proofs that exercise it.
# ---------------------------------------------------------------------------


def _zfc():
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            conjunction_prod(), disjunction_prod(), implication_prod(),
            biconditional_prod(), universal_prod(), existential_prod(),
        ],
        line=statement_line(),
        axioms=[axiom("EXT", "extensionality", "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[
            subset_def(),
            defn("formula", "superset", "x ⊇ y", "y ⊆ x", [("x", "variable"), ("y", "variable")]),
        ],
    )


def _gated():
    # Custom rules gated by `side_conditions` (equal / not-occurs).
    return SystemSpec(
        name="Gated",
        brackets=brackets(),
        productions=[
            regex_prod("atom", "prop", "[a-z]"),
            template_prod("formula", "atomic", "a", [("a", "atom")]),
            implication_prod(),
        ],
        line=statement_line(),
        rules=[
            hyp_rule(),
            rule("RImp", "refl imp", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["equal(p, q)"]),
            rule("NOcc", "non occur", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["not occurs(p, q)"]),
        ],
    )


def _or_sys():
    # A rule proviso using the `or` disjunction.
    return SystemSpec(
        name="OrSys",
        brackets=brackets(),
        productions=[
            regex_prod("atom", "prop", "[a-z]"),
            template_prod("formula", "atomic", "a", [("a", "atom")]),
            implication_prod(),
        ],
        line=statement_line(),
        rules=[
            rule("DIS", "disj", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["equal(p, q) or not occurs(p, q)"]),
        ],
    )


def _numeral():
    # No `notation` bracket pair; a leaf regex sort member.
    return SystemSpec(
        name="PA",
        productions=[regex_prod("term", "numeral", "[0-9]+"), variable_prod(), equality_prod()],
        line=statement_line(),
        rules=[hyp_rule()],
    )


def _ambiguous():
    # One higher template ("x ⋈ y") defined on two different sorts.
    return SystemSpec(
        name="DUP",
        brackets=brackets(),
        productions=[
            variable_prod(),
            template_prod("term", "pairing", "⟨s, t⟩", [("s", "term"), ("t", "term")]),
            membership_prod(),
            conjunction_prod(),
        ],
        line=statement_line(),
        rules=[hyp_rule()],
        definitions=[
            defn("formula", "both", "x ⋈ y", "(x ∈ y ∧ y ∈ x)", [("x", "variable"), ("y", "variable")]),
            defn("term", "swap", "x ⋈ y", "⟨y, x⟩", [("x", "variable"), ("y", "variable")]),
        ],
    )


def _where_def():
    # A definition carrying a `where` proviso (conjoined via `;`).
    return SystemSpec(
        name="Provisoed",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), equality_prod(), negation_prod(),
                     implication_prod(), universal_prod()],
        line=statement_line(),
        rules=[hyp_rule()],
        definitions=[
            subset_def(),
            defn("formula", "distinct", "x ≠ y", "¬(x = y)",
                 [("x", "variable"), ("y", "variable")], "disjoint(x, y, variable)"),
            defn("formula", "fresh", "x ⊘ y", "¬(x = y)",
                 [("x", "variable"), ("y", "variable")], "not occurs(y, x) ; atom(x, variable)"),
        ],
    )


def _no_reference():
    # A logical line whose shape has no reference part (formula only).
    return SystemSpec(
        name="NoRef",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod()],
        line=LineSpec(name="statement", shape="<formula>", parts=[], logical_sort="formula"),
        rules=[hyp_rule(), mp_rule()],
    )


CORPUS = {
    "zfc": (_zfc(), [
        "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)",
        "x = y",
        "x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]",
        "x ⊆ y [HYP]\n(x ⊆ y → x ⊇ y) [HYP]\nx ⊇ y [MP, 1, 2]",
        "HELLO 123",
    ]),
    "gated": (_gated(), [
        "(a → a) [RImp]", "(a → b) [RImp]",
        "(a → (c → b)) [NOcc]", "(a → (a → b)) [NOcc]",
    ]),
    "or_sys": (_or_sys(), [
        "(a → a) [DIS]", "(a → (b → c)) [DIS]", "(a → (a → b)) [DIS]",
    ]),
    "numeral": (_numeral(), ["2 = 5 [HYP]", "x = y [HYP]"]),
    "ambiguous": (_ambiguous(), ["x ⋈ y [HYP]", "(x ∈ y ∧ y ∈ x) [HYP]"]),
    "where_def": (_where_def(), ["x ≠ y [HYP]", "x ⊘ y [HYP]", "x ⊆ y [HYP]"]),
    "no_reference": (_no_reference(), ["x ∈ y [HYP]", "(x ∈ y → x ∈ y) [HYP]"]),
}


@pytest.mark.parametrize("name", list(CORPUS))
def test_direct_builder_matches_text_path(name):
    spec, proofs = CORPUS[name]
    direct = build_system(spec)
    oracle = _oracle(spec)
    _assert_structurally_equivalent(direct, oracle)
    _assert_same_proofs(direct, oracle, proofs)


def test_brackets_are_set_at_construction_not_patched():
    # The statement pattern carries the bracket map straight from construction —
    # the point of retiring `_patch_brackets`.
    system = build_system(_zfc())
    statement = next(lt for lt in system.line_types if lt.name == "statement")
    assert statement.pattern.respect_brackets == {"(": ")"}


def test_no_bracket_system_leaves_patterns_unbracketed():
    system = build_system(_numeral())
    statement = next(lt for lt in system.line_types if lt.name == "statement")
    assert statement.pattern.respect_brackets is None


def test_build_spec_reports_errors_for_an_unbuildable_spec():
    # A line shape with no grammar-sort placeholder can't be built; `build_spec`
    # surfaces that as errors rather than raising.
    from website.logical.declarative import build_spec

    spec = SystemSpec(
        name="Broken",
        productions=[regex_prod("formula", "atom", "[a-z]+")],
        line=LineSpec(name="statement", shape="assertion", parts=[], logical_sort="formula"),
    )
    result = build_spec(spec)
    assert "errors" in result and result["errors"]
