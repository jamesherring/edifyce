"""The `fresh` clause on a declaratively-built definition.

`fresh` declares the defining form's bound variables, so a quantified definition
(e.g. ``x ⊆ y ≝ ∀z (z ∈ x → z ∈ y)``) unfolds capture-avoidingly. It is not
optional: a defining form that introduces an undeclared binder has no sound
reading as a kernel definition, so the system does not build at all.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_spec
from website.logical.formal_system.definitions import build_kernel_definition

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
    # variable: declared via `fresh`, or, when fresh=False, not declared at all —
    # an undeclared binder, which the build rejects.
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


def test_fresh_builds_a_kernel_definition_and_no_fresh_fails_the_build():
    # The same definition builds a kernel counterpart with `fresh`; without it the
    # binder is undeclared, which is not a definition the kernel can express — so
    # the *system* is rejected, naming the variable and the fix.
    with_fresh = _subset_spec(fresh=True, condition="disjoint(x, y, term)")
    without_fresh = _subset_spec(fresh=False, condition="disjoint(x, y, term)")

    fresh_system = build_spec(with_fresh)["system"]
    fresh_def = _only_definition(fresh_system)
    assert fresh_def.kernel_condition is not None
    assert fresh_def.kernel is not None
    # Built once, at build time — not derived again per step.
    assert build_kernel_definition(fresh_def, _context_of(fresh_system)) == fresh_def.kernel

    result = build_spec(without_fresh)
    assert "errors" in result
    (message,) = result["errors"]
    assert "'z'" in message and "fresh" in message
    # The message quotes the defining form as written, not the renamed template.
    assert "∀z (z ∈ x → z ∈ y)" in message


def test_fresh_round_trips_through_storage():
    # spec_to_system persists the `fresh` clause and system_to_spec reads it back.
    pytest.importorskip("sqlalchemy")
    from app.db import spec_to_system, system_to_spec

    spec = _subset_spec(fresh=True, condition="disjoint(x, y, term)")
    rebuilt = system_to_spec(spec_to_system(spec))
    (definition,) = rebuilt.definitions
    assert definition.fresh == [("z", "variable")]
