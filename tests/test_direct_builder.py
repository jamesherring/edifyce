"""Construction details of the direct `SystemSpec → FormalSystem` builder.

`declarative.build_system` constructs a `FormalSystem` straight from a
`SystemSpec` by calling the engine's construction primitives directly. These
tests pin the construction-time contract the builder is responsible for:
`respect_brackets` set at construction (not patched on afterwards), an
unbuildable spec surfaced as errors rather than a raised exception, and a built
system that actually checks proofs.

Broad structural/behavioural parity across the declarative feature matrix is
covered by the systems/store/side-condition/string-rewriting suites, which all
run through `build_system`.
"""

import pytest

pytest.importorskip("regex")

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
    statement_line,
    subset_def,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import LineSpec, SystemSpec, build_spec, build_system


def _zfc():
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            conjunction_prod(), disjunction_prod(), implication_prod(),
            biconditional_prod(), universal_prod(), existential_prod(),
        ],
        lines=[statement_line()],
        axioms=[axiom("EXT", "extensionality", "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[
            subset_def(),
            defn("formula", "superset", "x ⊇ y", "y ⊆ x", [("x", "variable"), ("y", "variable")]),
        ],
    )


def _numeral():
    # No `notation` bracket pair; a leaf regex sort member.
    return SystemSpec(
        name="PA",
        productions=[regex_prod("term", "numeral", "[0-9]+"), variable_prod(), equality_prod()],
        lines=[statement_line()],
        rules=[hyp_rule()],
    )


def test_brackets_are_set_at_construction_not_patched():
    # The statement pattern carries the bracket map straight from construction —
    # the point of retiring the old post-compile `_patch_brackets`.
    system = build_system(_zfc())
    statement = next(lt for lt in system.line_types if lt.name == "statement")
    assert statement.pattern.respect_brackets == {"(": ")"}


def test_no_bracket_system_leaves_patterns_unbracketed():
    system = build_system(_numeral())
    statement = next(lt for lt in system.line_types if lt.name == "statement")
    assert statement.pattern.respect_brackets is None


def test_built_system_checks_proofs():
    # The built system checks proofs: an MP chain (including a definition-backed
    # step) validates, and a non-formula line is rejected.
    system = build_system(_zfc())
    good = system.parse("x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]")
    assert good.valid is True
    defined = system.parse("x ⊆ y [HYP]\n(x ⊆ y → x ⊇ y) [HYP]\nx ⊇ y [MP, 1, 2]")
    assert defined.valid is True
    assert system.parse("HELLO 123").valid is False


def test_build_spec_reports_errors_for_an_unbuildable_spec():
    # A line shape with no grammar-sort placeholder can't be built; `build_spec`
    # surfaces that as errors rather than raising.
    spec = SystemSpec(
        name="Broken",
        productions=[regex_prod("formula", "atom", "[a-z]+")],
        lines=[LineSpec(name="statement", shape="assertion", parts=[], logical_sort="formula")],
    )
    result = build_spec(spec)
    assert "errors" in result and result["errors"]
