"""The bridge from a legacy matching.Definition to the kernel's term-based
definitional-step checker (formal_system/definitions.py).

``ProofLine.follows_from_definition`` now checks a definitional step over the
shared-DAG term representation when the definition is soundly expressible as a
kernel one, and falls back to the string-based ``Definition.check_application``
otherwise. These tests pin both branches: an alias definition and a
binder-carrying one (whose bound variables are declared with the ``fresh`` clause,
optionally constrained by a ``where`` proviso) go through the kernel checker
- accepting a correct unfold in either direction, rejecting a wrong one, and
avoiding capture - while a definition with an *undeclared* binder or a legacy
``if`` proviso is refused by the soundness gate so the legacy path is kept.
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

    LineType statement:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r

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

    LineType statement:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r

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
    # (x ⊆ y) := ∀z.((z ∈ x) → (z ∈ y)) with z's binder status *not* declared.
    # Built directly so z is an undeclared bound variable of the defining form;
    # the soundness gate must refuse it (contrast the FRESH_SYSTEM tests below,
    # where `fresh z as setvar` declares it and the kernel path is taken).
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


# A definition authored through the extended DSL: `fresh z as setvar` declares
# the defining form's bound variable, so the term checker can unfold df-subset
# capture-avoidingly. The Define attaches to the `formula` union (its lower form,
# a `forall`, is not a `subset` instance) by re-opening the union with a `with`.
FRESH_SYSTEM = """FormalSystem SetTheory:

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

    formula:
        with x as setvar, y as setvar:
            Define (x ⊆ y) as ∀z.((z ∈ x) → (z ∈ y)) fresh z as setvar%(WHERE)s

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    LineType statement:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r
"""


@pytest.fixture(scope="module")
def fresh_system():
    return build(FRESH_SYSTEM % {"WHERE": ""})


@pytest.fixture(scope="module")
def guarded_system():
    # Same definition, with an extra kernel-vocabulary proviso: the two subset
    # arguments must be disjoint setvar leaves.
    return build(FRESH_SYSTEM % {"WHERE": " where disjoint(x, y, setvar)"})


# ---------------------------------------------------------------------------
# `fresh` clause: declared binders take the kernel path
# ---------------------------------------------------------------------------


def test_fresh_clause_is_captured_on_the_definition(fresh_system):
    definition = only_definition(fresh_system)
    assert set(definition.fresh) == {"z"}


def test_declared_binder_builds_a_kernel_definition(fresh_system):
    definition = only_definition(fresh_system)
    assert kernel_definition_for(definition, context_of(fresh_system)) is not None


def test_declared_binder_unfold_accepted_both_directions(fresh_system):
    definition = only_definition(fresh_system)
    context = context_of(fresh_system)
    proof, (subset, unfolded) = formulae(
        fresh_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))"
    )
    assert follows_by_definition(subset, unfolded, definition, context) is True
    assert follows_by_definition(unfolded, subset, definition, context) is True


def test_declared_binder_rejects_a_wrong_unfold(fresh_system):
    definition = only_definition(fresh_system)
    context = context_of(fresh_system)
    _proof, (subset, other) = formulae(
        fresh_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ c))"
    )
    assert follows_by_definition(subset, other, definition, context) is False


def test_unfold_is_capture_avoiding(fresh_system):
    # Unfolding (z ⊆ b): renaming the binder away from the free z is valid;
    # reusing z (capturing the free z under the quantifier) is not.
    definition = only_definition(fresh_system)
    context = context_of(fresh_system)
    _proof, (subset, renamed, captured) = formulae(
        fresh_system,
        "(z ⊆ b)",
        "∀w.((w ∈ z) → (w ∈ b))",
        "∀z.((z ∈ z) → (z ∈ b))",
    )
    assert follows_by_definition(subset, renamed, definition, context) is True
    assert follows_by_definition(subset, captured, definition, context) is False


# ---------------------------------------------------------------------------
# `where` clause: kernel-vocabulary provisos gate the unfold
# ---------------------------------------------------------------------------


def test_where_proviso_is_parsed_into_a_kernel_condition(guarded_system):
    definition = only_definition(guarded_system)
    assert definition.kernel_condition is not None
    assert kernel_definition_for(definition, context_of(guarded_system)) is not None


def test_where_proviso_gates_the_unfold(guarded_system):
    definition = only_definition(guarded_system)
    context = context_of(guarded_system)
    # Disjoint arguments: the unfold holds.
    _p1, (ok_subset, ok_unfold) = formulae(
        guarded_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))"
    )
    assert follows_by_definition(ok_subset, ok_unfold, definition, context) is True
    # Equal arguments violate disjoint(x, y, setvar): the step is rejected.
    _p2, (bad_subset, bad_unfold) = formulae(
        guarded_system, "(a ⊆ a)", "∀z.((z ∈ a) → (z ∈ a))"
    )
    assert follows_by_definition(bad_subset, bad_unfold, definition, context) is False


def test_where_definition_is_refused_by_the_string_path(guarded_system):
    # A `where` proviso is enforced only on the kernel path; the string-layer
    # application primitives (get_lower, check_application) must refuse a
    # proviso-carrying definition so it cannot be applied unchecked (e.g. via
    # Match.equivalent_under_definitions).
    definition = only_definition(guarded_system)
    context = context_of(guarded_system)
    assert definition.kernel_condition is not None

    higher = definition.higher.match("(a ⊆ b)", context)
    assert higher is not None
    assert definition.get_lower(higher, context) is False
    assert definition.check_application(higher, higher, context) is False


# ---------------------------------------------------------------------------
# legacy `if` rejection and malformed-clause compile errors
# ---------------------------------------------------------------------------


def test_legacy_if_proviso_is_a_compile_error():
    # The legacy pseudo-python `if` proviso has been retired; a definition that
    # uses it is a compile error directing the author to `where`.
    result = compile_formal_system(
        FRESH_SYSTEM % {"WHERE": " if x == x"}
    )
    assert "errors" in result
    assert any("if" in e and "where" in e for e in result["errors"])


def test_malformed_where_sort_is_a_compile_error_not_a_crash():
    # An unknown sort in a `where` proviso is resolved outside run()'s
    # try/except; it must surface as a structured compile error, not a 500.
    result = compile_formal_system(
        FRESH_SYSTEM % {"WHERE": " where disjoint(x, y, no_such_sort)"}
    )
    assert "errors" in result


def test_malformed_fresh_sort_is_a_compile_error_not_a_crash():
    result = compile_formal_system(
        FRESH_SYSTEM.replace("fresh z as setvar", "fresh z as no_such_sort")
        % {"WHERE": ""}
    )
    assert "errors" in result


def test_where_definition_refuses_when_the_kernel_path_is_unavailable(binder_system):
    # A definition that carries a kernel `where` proviso but cannot build a
    # kernel definition (here: an undeclared binder) must be refused, not routed
    # to the string fallback that ignores the proviso.
    from website.logical.kernel import Equal

    definition = binder_definition(binder_system)
    definition.kernel_condition = Equal("x", "y")  # any kernel proviso
    context = context_of(binder_system)
    proof, _ = formulae(binder_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))")
    subset_line, unfolded_line = proof.proof_lines

    # No kernel counterpart is buildable, and the proviso cannot be enforced on
    # the string path, so the step is refused rather than silently accepted.
    assert kernel_definition_for(definition, context) is None
    assert subset_line.follows_from_definition(unfolded_line, definition, {}, context) is False
