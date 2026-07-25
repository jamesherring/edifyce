"""Building a kernel definition from a matching.Definition, and checking a
definitional step against it (formal_system/definitions.py).

Every definition gets its kernel counterpart when the *system* is built, and
``ProofLine.follows_from_definition`` checks each step over the shared-DAG term
representation against it. There is no second way to apply a definition, so a
definition that has no sound kernel reading is rejected where its author can act
on it: the build fails.

These tests pin both sides. An alias definition, a constant-carrying one, and a
binder-carrying one (whose bound variables are declared with ``fresh``, optionally
constrained by a ``where`` proviso) build and check - accepting a correct unfold in
either direction, rejecting a wrong one, and avoiding capture. A defining form
that introduces an *undeclared* binder, or a legacy ``if`` proviso, fails the
build.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

# Every system fixture is built declaratively via `build_spec`, the same path the
# database and API use.
from website.logical.declarative import SystemSpec, build_spec
from website.logical.formal_system.definitions import (
    DefinitionError,
    build_kernel_definition,
    follows_by_definition,
)

from tests.spec_helpers import (
    atom_const_prod,
    brackets,
    defn,
    regex_prod,
    rule,
    statement_line,
    template_prod,
)


def build_declarative(spec: SystemSpec):
    result = build_spec(spec)
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


# `setvar` is a single-letter leaf sort used only as a binding sort; its member
# name must differ from the sort name (else build_system's union step recurses).
def _setvar_prod():
    return regex_prod("setvar", "setvar_atom", "[a-z]")


def _hyp_rule():
    # `with f as formula: deduction f` - a bare formula metavariable. Named `f`
    # (not `p`) to stay clear of the single-letter `setvar` tokens.
    return rule("HYP", "hypothesis", [], "f", [("f", "formula")])


# A binder-free alias: `x sub y` abbreviates the membership `(x ∈ y)`. Both
# forms are ordinary grammatical formulae over the parameters x, y, so this is
# exactly the case the kernel definition can represent.
def alias_spec() -> SystemSpec:
    return SystemSpec(
        name="AliasSys",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[statement_line()],
        definitions=[
            defn("formula", "sub", "x sub y", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        rules=[_hyp_rule()],
    )


# df-subset with its binder `z` *undeclared*: the defining form binds `z`, but
# neither `fresh` nor the defined form mentions it, so a capture-blind unfold
# would be unsound. There is no reading of this definition the kernel can check,
# so the system must not build. `declare_z_as_a_parameter` spells the same mistake
# the other way - `z` given as an ordinary parameter, as if the unfold's consumer
# supplied it - which is equally unsound and must be refused too.
def binder_spec(
    where: str | None = None, *, declare_z_as_a_parameter: bool = False
) -> SystemSpec:
    bindings = [("x", "setvar"), ("y", "setvar")]
    if declare_z_as_a_parameter:
        bindings.append(("z", "setvar"))
    return SystemSpec(
        name="BinderSys",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
            template_prod("formula", "subset", "(x ⊆ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[statement_line()],
        definitions=[
            defn(
                "formula", "df_subset", "(x ⊆ y)", "∀z.((z ∈ x) → (z ∈ y))",
                bindings, condition=where,
            ),
        ],
        rules=[_hyp_rule()],
    )


# A defining form that mentions a grammar *constant* (`⊥`, a nullary atom
# declared as denoting one) which the defined form does not. The constant is a
# lower-only ground leaf like an undeclared binder would be, but the declaration
# says it can never be captured, so the bridge must take the kernel path rather
# than refuse it.
def const_spec() -> SystemSpec:
    return SystemSpec(
        name="ConstSys",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            atom_const_prod("formula", "falsum", "⊥", denotes_constant=True),
        ],
        lines=[statement_line()],
        definitions=[
            defn("formula", "notin", "(x ∉ y)", "((x ∈ y) → ⊥)", [("x", "setvar"), ("y", "setvar")]),
        ],
        rules=[_hyp_rule()],
    )


@pytest.fixture(scope="module")
def alias_system():
    return build_declarative(alias_spec())


@pytest.fixture(scope="module")
def const_system():
    return build_declarative(const_spec())


# ---------------------------------------------------------------------------
# build_kernel_definition - the build-time soundness gate
# ---------------------------------------------------------------------------


def test_binder_free_alias_builds_a_kernel_definition(alias_system):
    # The kernel counterpart is built with the system, not derived per step.
    definition = only_definition(alias_system)
    assert definition.kernel is not None


def test_undeclared_binder_fails_the_build():
    # `z` is bound by the defining form and absent from the defined form, so no
    # unfold of this definition is capture-safe. The build says so, naming the
    # variable and the fix.
    result = build_spec(binder_spec())
    assert "errors" in result
    (message,) = result["errors"]
    assert "'z'" in message and "fresh" in message


def test_undeclared_binder_with_a_proviso_fails_the_build():
    # A `where` proviso does not rescue it: the proviso is checked against the
    # binding an unfold produces, and there is no sound unfold to produce one.
    result = build_spec(binder_spec(where="disjoint(x, y, setvar)"))
    assert "errors" in result
    assert "'z'" in result["errors"][0]


def test_binder_declared_as_an_ordinary_parameter_fails_the_build():
    # Declaring `z` as a parameter is the same unsoundness spelled differently:
    # the defined form cannot supply it, so it is a binder however it is declared.
    # This is also the case whose generated pattern renames `z` to `z_0`, so the
    # message must quote the defining form the author wrote.
    result = build_spec(binder_spec(declare_z_as_a_parameter=True))
    assert "errors" in result
    (message,) = result["errors"]
    assert "'z'" in message and "z_0" not in message
    assert "∀z.((z ∈ x) → (z ∈ y))" in message


def test_a_definition_built_outside_the_system_builder_says_so(alias_system):
    # `Pattern.add_definition` is public and does not build a kernel counterpart —
    # only `declarative.build_system` does. A definition that reaches a proof that
    # way must name the broken invariant, not fail as an AttributeError several
    # frames inside the kernel.
    system = alias_system
    formula = system.build_context.variables["formula"]
    context = context_of(system)
    context.string_variables = {"x": system.build_context.variables["setvar"],
                                "y": system.build_context.variables["setvar"]}
    unbuilt = formula.add_definition("(x ∈ y)", "x below y", context)
    assert unbuilt is not None and unbuilt.kernel is None

    _proof, (alias, canonical) = formulae(system, "a sub b", "(a ∈ b)")
    with pytest.raises(DefinitionError, match="no kernel counterpart"):
        follows_by_definition(alias, canonical, unbuilt, context)


def test_a_definition_with_no_defining_form_is_refused(alias_system):
    # `require_lower_match=False` builds a definition whose lower form is unknown.
    # It makes defined notation parse, but there is nothing to unfold *to*.
    context = context_of(alias_system)
    formula = alias_system.build_context.variables["formula"]
    open_definition = formula.add_definition(
        "not a formula at all", "x beside y", context, require_lower_match=False
    )
    assert open_definition is not None and open_definition.lower is None

    with pytest.raises(DefinitionError, match="no defining form"):
        build_kernel_definition(open_definition, context)


def test_constant_carrying_definition_builds_a_kernel_definition(const_system):
    # `⊥` is a lower-only ground leaf, like an undeclared binder — but it is a
    # grammar constant, which can never be captured, so the gate admits it.
    definition = only_definition(const_system)
    assert definition.kernel is not None


# A nullary abbreviation: `S` names one specific formula, taking no arguments.
# `closed` decides whether its defining form is built only from constants, or
# mentions setvars `a`/`b` that nothing determines.
def nullary_spec(*, closed: bool) -> SystemSpec:
    return SystemSpec(
        name="NullarySys",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
            atom_const_prod("formula", "falsum", "⊥", denotes_constant=True),
        ],
        lines=[statement_line()],
        definitions=[
            defn("formula", "s", "S", "(⊥ → ⊥)" if closed else "(a ∈ b)", []),
        ],
        rules=[_hyp_rule()],
    )


def test_closed_nullary_abbreviation_builds_and_checks_a_step():
    # Every leaf of the defining form is a constant, so the unfold produces a
    # fixed term wherever it is taken. Nothing to determine, nothing to capture.
    system = build_declarative(nullary_spec(closed=True))
    definition = only_definition(system)
    assert definition.kernel is not None

    context = context_of(system)
    _proof, (abbreviated, spelled, other) = formulae(
        system, "S", "(⊥ → ⊥)", "(⊥ → (⊥ → ⊥))"
    )
    assert follows_by_definition(abbreviated, spelled, definition, context) is True
    assert follows_by_definition(spelled, abbreviated, definition, context) is True
    assert follows_by_definition(abbreviated, other, definition, context) is False


def test_open_nullary_abbreviation_fails_the_build():
    # `S ≝ (a ∈ b)` leaves `a` and `b` free in the defining form: `S` cannot
    # supply them, so the unfold conjures them at whatever position it is taken.
    # Under a binder for the same name that is capture — `∀a.S` would unfold to
    # `∀a.(a ∈ b)`, silently rebinding an `a` that was free in `S`. No proviso can
    # repair it (the constraint is on where `S` may *occur*, which a cited step
    # does not see), so the definition is refused when the system is built.
    result = build_spec(nullary_spec(closed=False))
    assert "errors" in result
    (message,) = result["errors"]
    assert "'a'" in message and "'b'" in message


def test_a_nullary_definition_may_be_layered_on_by_a_later_one():
    # `S ≝ (⊥ → ⊥)` adds a ground leaf no production declared a role for, so
    # `T ≝ S` would introduce an undeclared token. The build derives the role
    # instead of asking: S abbreviates a fixed term, so it denotes a constant.
    spec = nullary_spec(closed=True)
    spec.definitions.append(defn("formula", "t", "T", "S", []))
    system = build_declarative(spec)
    assert system.definition_layering == [True, True]

    # `context.definitions` is a set, so pick each out by its defined form.
    by_form = {d.higher.pattern: d for d in system.context.definitions}
    assert by_form["S"].higher.denotes_constant is True
    sup = by_form["T"]
    assert sup.kernel is not None

    context = context_of(system)
    _proof, (abbreviated, spelled) = formulae(system, "T", "S")
    assert follows_by_definition(abbreviated, spelled, sup, context) is True


def test_layering_on_a_definition_with_parameters_introduces_nothing():
    # The counterpart: `(x ∉ y)` is compound, never a ground leaf, so the derived
    # role is False and nothing is excused by it — there was nothing to excuse.
    system = build_declarative(const_spec())
    assert only_definition(system).higher.denotes_constant is False


# A constant grammar plus an unused sort whose regex is malformed. The gate once
# probed every reachable sort for the leaf's token, which compiled this regex
# lazily and took a well-formed definition down with it. The gate now reads the
# leaf's own declaration and consults no other sort at all, so no unrelated
# production — broken or otherwise — can reach the decision.
def const_bad_regex_spec() -> SystemSpec:
    spec = const_spec()
    spec.productions.append(regex_prod("junk", "junk_atom", "[unclosed"))
    return spec


def test_unrelated_malformed_regex_sort_does_not_reach_the_gate():
    system = build_declarative(const_bad_regex_spec())
    assert only_definition(system).kernel is not None


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


def test_constant_definition_unfold_checked_by_the_kernel(const_system):
    # The unfold of a constant-carrying definition is verified over kernel terms,
    # in both directions, and a wrong formula is rejected — the constant `⊥` rides
    # through the term check unchanged.
    definition = only_definition(const_system)
    context = context_of(const_system)
    _proof, (folded, unfolded, other) = formulae(
        const_system, "(a ∉ b)", "((a ∈ b) → ⊥)", "(a ∈ b)"
    )

    assert follows_by_definition(folded, unfolded, definition, context) is True
    assert follows_by_definition(unfolded, folded, definition, context) is True
    assert follows_by_definition(folded, other, definition, context) is False


def test_follows_from_definition_uses_the_kernel_path(alias_system):
    # End-to-end through the ProofLine method: a correct step is accepted and a
    # wrong one rejected, with the kernel definition actually built (kernel path).
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    proof, _ = formulae(alias_system, "a sub b", "(a ∈ b)", "(a ∈ c)")
    alias_line, canonical_line, other_line = proof.proof_lines

    assert alias_line.follows_from_definition(canonical_line, definition, context) is True
    assert alias_line.follows_from_definition(other_line, definition, context) is False
    assert definition.kernel is not None


# The declarative form of the same df-subset system, built for the happy-path
# fixtures below. `fresh z as setvar` declares the defining form's bound variable
# so the term checker can unfold df-subset capture-avoidingly; `where` adds an
# optional kernel-vocabulary proviso.
def fresh_spec(where: str | None = None) -> SystemSpec:
    return SystemSpec(
        name="SetTheory",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
            template_prod("formula", "subset", "(x ⊆ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[statement_line()],
        definitions=[
            defn(
                "formula", "df_subset", "(x ⊆ y)", "∀z.((z ∈ x) → (z ∈ y))",
                [("x", "setvar"), ("y", "setvar")], condition=where, fresh=[("z", "setvar")],
            ),
        ],
    )


@pytest.fixture(scope="module")
def fresh_system():
    return build_declarative(fresh_spec())


@pytest.fixture(scope="module")
def guarded_system():
    # Same definition, with an extra kernel-vocabulary proviso: the two subset
    # arguments must be disjoint setvar leaves.
    return build_declarative(fresh_spec(where="disjoint(x, y, setvar)"))


# ---------------------------------------------------------------------------
# `fresh` clause: declared binders take the kernel path
# ---------------------------------------------------------------------------


def test_fresh_clause_is_captured_on_the_definition(fresh_system):
    definition = only_definition(fresh_system)
    assert set(definition.fresh) == {"z"}


def test_declared_binder_builds_a_kernel_definition(fresh_system):
    definition = only_definition(fresh_system)
    assert definition.kernel is not None


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
    assert definition.kernel is not None


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


def test_a_definition_has_no_second_way_to_be_applied(guarded_system):
    # The string-layer application primitives are gone. They could not evaluate a
    # `where` proviso, so a definition carrying one had to be refused there and
    # checked on the kernel path — two paths disagreeing by construction. Now
    # there is one, and this pins that the other cannot come back unnoticed.
    definition = only_definition(guarded_system)
    assert definition.kernel_condition is not None
    assert not hasattr(definition, "check_application")
    assert not hasattr(definition, "get_lower")

    higher = definition.higher.match("(a ⊆ b)", context_of(guarded_system))
    assert higher is not None
    assert not hasattr(higher, "equivalent_under_definitions")
    assert not hasattr(higher, "maps_to_up_to_definition")


# ---------------------------------------------------------------------------
# check_definitional_line: the proof-check entry point
# ---------------------------------------------------------------------------


def _definition_reference(source_line, definition):
    from website.logical.formal_system.proof import DefinitionReference

    return DefinitionReference(key="df", source=source_line, definition=definition)


def test_check_definitional_line_honors_the_proviso_on_the_kernel_path(guarded_system):
    # End-to-end through the proof-check entry point (not just follows_by_definition):
    # the df-subset proviso `disjoint(x, y, setvar)` gates a cited definitional step.
    definition = only_definition(guarded_system)
    context = context_of(guarded_system)

    # Disjoint arguments: the cited step verifies.
    ok_proof, _ = formulae(guarded_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))")
    ok_source, ok_target = ok_proof.proof_lines
    assert ok_proof.check_definitional_line(
        ok_target, _definition_reference(ok_source, definition), context
    ) is True

    # Equal arguments violate the proviso: the step is rejected as a normal
    # non-application (the definition *is* kernel-expressible, so no special message).
    bad_proof, _ = formulae(guarded_system, "(a ⊆ a)", "∀z.((z ∈ a) → (z ∈ a))")
    bad_source, bad_target = bad_proof.proof_lines
    assert bad_proof.check_definitional_line(
        bad_target, _definition_reference(bad_source, definition), context
    ) is False
    assert "does not apply between" in bad_target.invalid_message


def test_check_definitional_line_reports_a_plain_non_application(alias_system):
    # Every definition reaching a proof is kernel-expressible, so a cited step
    # that does not hold has exactly one cause worth reporting: the definition does
    # not relate these two lines. There is no longer a second, unenforceable class
    # of definition needing its own diagnostic — those fail the build instead.
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    proof, _ = formulae(alias_system, "a sub b", "(a ∈ c)")
    source, target = proof.proof_lines

    assert proof.check_definitional_line(
        target, _definition_reference(source, definition), context
    ) is False
    assert "does not apply between" in target.invalid_message
