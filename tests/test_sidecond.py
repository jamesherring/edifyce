"""Unit tests for the kernel freshness side-condition (kernel step 3).

These exercise :func:`occurs` / :func:`is_fresh` directly on term trees built
from parsed formulae, independently of the proof checker that consumes them.
"""

import pytest

pytest.importorskip("regex")

from copy import copy

from website.logical.compiler import compile as compile_formal_system
from website.logical.kernel.sidecond import is_fresh, occurs
from website.logical.kernel.terms import from_match

from zfc_systems import SCOPED_ZFC


@pytest.fixture(scope="module")
def system():
    result = compile_formal_system(SCOPED_ZFC)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def term_for(system, formula_text):
    context = copy(system.context)
    formula = system.build_context.variables["formula"]
    match = formula.match(formula_text, context)
    assert match is not None, formula_text
    return from_match(match, context)


def test_occurs_finds_variable(system):
    assert occurs(term_for(system, "x ∈ c"), "x") is True


def test_occurs_is_structural_not_textual(system):
    # `x` must not be found inside the token `xy` nor inside any operator.
    assert occurs(term_for(system, "xy ∈ c"), "x") is False


def test_occurs_recurses_into_compounds(system):
    assert occurs(term_for(system, "(x ∈ c → y ∈ c)"), "y") is True
    assert occurs(term_for(system, "(x ∈ c → y ∈ c)"), "z") is False


def test_is_fresh_over_several_terms(system):
    terms = [term_for(system, "a ∈ c"), term_for(system, "b ∈ c")]
    assert is_fresh("x", terms) is True
    assert is_fresh("a", terms) is False


def test_is_fresh_vacuously_true_for_no_terms():
    assert is_fresh("x", []) is True
