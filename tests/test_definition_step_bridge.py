"""The bridge from a legacy matching.Definition to the kernel's term-based
definitional-step checker (formal_system/definitions.py).

``ProofLine.follows_from_definition`` now checks a definitional step over the
shared-DAG term representation when the definition is soundly expressible as a
kernel one (binder-free, condition-free), and falls back to the string-based
``Definition.check_application`` otherwise. These tests pin both branches: a
binder-free alias definition goes through the kernel checker (accepting a correct
unfold in either direction and rejecting a wrong one), and a definition whose
defining form introduces a bound variable is refused by the soundness gate so
the legacy path is kept.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system.definitions import (
    follows_by_definition,
    kernel_definition_for,
)
from website.logical.matching.definitions import Definition


def build(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def context_of(system):
    # A parsing/checking context carrying both the frozen and build-time
    # variables, mirroring how the engine assembles one during a proof check.
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return context


def only_definition(system):
    definitions = list(context_of(system).definitions)
    assert len(definitions) == 1, definitions
    return definitions[0]


# A binder-free alias: `x sub y` abbreviates the membership `(x ∈ y)`. Both
# forms are ordinary grammatical formulae over the parameters x, y, so this is
# exactly the case the kernel definition can represent.
ALIAS_SYSTEM = """FormalSystem AliasSys:

    Regex setvar:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern membership:
        with x as setvar, y as setvar:
            (x ∈ y)
            Define x sub y as (x ∈ y)

    UnionPattern formula:
        membership

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    statement_pattern.formula():
        return self.f

    statement_pattern.reference():
        return self.r

    LineType statement:
        pattern: statement_pattern
        behaviour: logical

    with f as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                f
"""


# A definition whose defining form binds a fresh variable `z`. The legacy
# `Define` DSL cannot declare `z` as bound, so a capture-blind kernel unfold
# would be unsound - the bridge must refuse it and keep the string path.
BINDER_SYSTEM = """FormalSystem BinderSys:

    Regex setvar:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern membership:
        with x as setvar, y as setvar:
            (x ∈ y)

    UnionPattern formula:
        membership

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    formula:
        implication

    Pattern forall:
        with x as setvar, phi as formula:
            ∀x.phi

    formula:
        forall

    Pattern subset:
        with x as setvar, y as setvar:
            (x ⊆ y)

    formula:
        subset

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    statement_pattern.formula():
        return self.f

    statement_pattern.reference():
        return self.r

    LineType statement:
        pattern: statement_pattern
        behaviour: logical

    with f as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                f
"""


@pytest.fixture(scope="module")
def alias_system():
    return build(ALIAS_SYSTEM)


@pytest.fixture(scope="module")
def binder_system():
    return build(BINDER_SYSTEM)


def binder_definition(system):
    # (x ⊆ y) := ∀z.((z ∈ x) → (z ∈ y)). The legacy `Define` DSL cannot author
    # this - its lower form must be an instance of the pattern, and a `forall`
    # is not a `subset` - so we build the matching.Definition directly, with x, y
    # as parameters and z left as a free (bound) variable of the defining form.
    context = context_of(system)
    setvar = system.build_context.variables["setvar"]
    context.string_variables = {"x": setvar, "y": setvar}
    formula = system.build_context.variables["formula"]
    return Definition(
        lower="∀z.((z ∈ x) → (z ∈ y))",
        higher="(x ⊆ y)",
        pattern=formula,
        context=context,
    )


# ---------------------------------------------------------------------------
# kernel_definition_for - the soundness gate
# ---------------------------------------------------------------------------


def test_binder_free_alias_builds_a_kernel_definition(alias_system):
    definition = only_definition(alias_system)
    kernel_def = kernel_definition_for(definition, context_of(alias_system))
    assert kernel_def is not None
    # It is cached on the legacy definition (built at most once).
    assert definition.kernel_definition_ready is True
    assert definition.kernel_definition is kernel_def


def test_binder_carrying_definition_is_refused(binder_system):
    definition = binder_definition(binder_system)
    kernel_def = kernel_definition_for(definition, context_of(binder_system))
    # `z` is a bound variable the Define DSL cannot declare; the gate refuses it.
    assert kernel_def is None
    assert definition.kernel_definition_ready is True


def test_definition_with_condition_is_refused(alias_system):
    # A legacy proviso is not translated to the kernel vocabulary, so a
    # conditional definition must stay on the string path even when binder-free.
    definition = only_definition(alias_system)
    definition = copy(definition)
    definition.kernel_definition_ready = False
    definition.condition = object()  # stand-in for a parsed Condition
    assert kernel_definition_for(definition, context_of(alias_system)) is None


# ---------------------------------------------------------------------------
# follows_by_definition - the term-based step check (kernel path)
# ---------------------------------------------------------------------------


def formulae(system, *lines):
    proof = system.parse("\n".join(f"{line} [HYP]" for line in lines))
    return proof, [pl.formula for pl in proof.proof_lines]


def test_alias_unfold_accepted_both_directions(alias_system):
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    _proof, (alias, canonical) = formulae(alias_system, "a sub b", "(a ∈ b)")

    assert alias is not None and canonical is not None
    # Fold direction and unfold direction both hold: one definitional step apart.
    assert follows_by_definition(alias, canonical, definition, context) is True
    assert follows_by_definition(canonical, alias, definition, context) is True


def test_alias_unfold_rejects_a_different_formula(alias_system):
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    _proof, (alias, other) = formulae(alias_system, "a sub b", "(a ∈ c)")

    assert follows_by_definition(alias, other, definition, context) is False


def test_follows_from_definition_uses_the_kernel_path(alias_system):
    # End-to-end through the ProofLine method: a correct step is accepted and a
    # wrong one rejected, with the kernel definition actually built (kernel path).
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    proof, _ = formulae(alias_system, "a sub b", "(a ∈ b)", "(a ∈ c)")
    alias_line, canonical_line, other_line = proof.proof_lines

    assert alias_line.follows_from_definition(canonical_line, definition, {}, context) is True
    assert alias_line.follows_from_definition(other_line, definition, {}, context) is False
    assert definition.kernel_definition is not None


def test_binder_definition_falls_back_to_string_path(binder_system):
    # The bridge declines (returns None) for the binder-carrying definition, so
    # follows_from_definition must delegate to the string-based path rather than
    # accept a capture-blind unfold.
    definition = binder_definition(binder_system)
    context = context_of(binder_system)
    proof, _ = formulae(binder_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))")
    subset_line, unfolded_line = proof.proof_lines

    assert subset_line.formula is not None and unfolded_line.formula is not None
    # No kernel counterpart: the term-based check is not applicable here.
    assert follows_by_definition(subset_line.formula, unfolded_line.formula, definition, context) is None
    # The ProofLine method still returns a boolean via the legacy fallback.
    assert isinstance(
        subset_line.follows_from_definition(unfolded_line, definition, {}, context), bool
    )
