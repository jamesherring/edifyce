"""The `fresh` clause on a declaratively-built definition.

`fresh` declares the defining form's bound variables, so a quantified definition
(e.g. ``x ⊆ y ≝ ∀z (z ∈ x → z ∈ y)``) unfolds capture-avoidingly on the kernel
term path instead of being refused for an undeclared binder. That is what makes a
*proviso-carrying* quantified definition usable through the declarative/API path
(the D2 gap): without a way to declare `z`, such a definition has no kernel
counterpart and its proviso can never be enforced.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_spec
from website.logical.formal_system.definitions import kernel_definition_for

from tests.spec_helpers import (
    axiom,
    brackets,
    defn,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    statement_line,
    universal_prod,
    variable_prod,
)


def _subset_spec(*, fresh: bool, condition: str | None) -> SystemSpec:
    # df-subset over a first-order grammar. `z` is the defining form's bound
    # variable: declared via `fresh` (the kernel path) or, when fresh=False, not
    # declared at all (an undeclared binder — the string-fallback / refusal path).
    subset = defn(
        "formula",
        "subset",
        "x ⊆ y",
        "∀z (z ∈ x → z ∈ y)",
        [("x", "variable"), ("y", "variable")],
        condition=condition,
        fresh=[("z", "variable")] if fresh else (),
    )
    return SystemSpec(
        name="Sets",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(),
            implication_prod(), universal_prod(),
        ],
        lines=[statement_line()],
        axioms=[axiom("EXT", "extensionality", "∀x x = x")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[subset],
    )


def _context_of(system):
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return context


def _only_definition(system):
    definitions = list(_context_of(system).definitions)
    assert len(definitions) == 1, definitions
    return definitions[0]


def test_fresh_lets_a_quantified_proviso_definition_verify_a_step():
    # The headline: a proviso-carrying quantified definition, authored through the
    # declarative path with `fresh`, takes the kernel path and enforces its proviso.
    result = build_spec(_subset_spec(fresh=True, condition="disjoint(x, y, term)"))
    assert "errors" not in result, result.get("errors")
    system = result["system"]

    # Disjoint arguments satisfy `disjoint(x, y, term)`: the unfold verifies.
    ok = system.parse("a ⊆ b [HYP]\n∀z (z ∈ a → z ∈ b) [Def, 1]")
    assert ok.proof_lines[1].valid is True

    # Equal arguments violate the proviso: the unfold is rejected.
    bad = system.parse("a ⊆ a [HYP]\n∀z (z ∈ a → z ∈ a) [Def, 1]")
    assert bad.proof_lines[1].valid is False


def test_fresh_builds_a_kernel_definition_that_no_fresh_cannot():
    # The same definition builds a kernel counterpart with `fresh`, and none
    # without it (an undeclared binder) — the D2-refused case the proviso message
    # describes. This is why `fresh` is required to make the proviso enforceable.
    with_fresh = _subset_spec(fresh=True, condition="disjoint(x, y, term)")
    without_fresh = _subset_spec(fresh=False, condition="disjoint(x, y, term)")

    fresh_system = build_spec(with_fresh)["system"]
    plain_system = build_spec(without_fresh)["system"]

    fresh_def = _only_definition(fresh_system)
    plain_def = _only_definition(plain_system)
    assert fresh_def.kernel_condition is not None and plain_def.kernel_condition is not None

    assert kernel_definition_for(fresh_def, _context_of(fresh_system)) is not None
    assert kernel_definition_for(plain_def, _context_of(plain_system)) is None


def test_fresh_round_trips_through_storage():
    # spec_to_system persists the `fresh` clause and system_to_spec reads it back.
    pytest.importorskip("sqlalchemy")
    from app.db import spec_to_system, system_to_spec

    spec = _subset_spec(fresh=True, condition="disjoint(x, y, term)")
    rebuilt = system_to_spec(spec_to_system(spec))
    (definition,) = rebuilt.definitions
    assert definition.fresh == [("z", "variable")]
