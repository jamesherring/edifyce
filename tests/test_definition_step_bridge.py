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
from website.logical.kernel import check_definitional_step
from website.logical.kernel.constructors import constructor_for
from website.logical.kernel.definitions import Definition as KernelDefinition
from website.logical.formal_system.definitions import (
    DefinitionError,
    build_kernel_definition,
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
    # The system's single kernel definition - the axiom a step is checked against.
    assert len(system.definitions) == 1, system.definitions
    return system.definitions[0]


def only_notation(system):
    # The system's single defined notation - the production that lets the defined
    # form parse. Paired with the definition above, but a separate object.
    notations = list(context_of(system).definitions)
    assert len(notations) == 1, notations
    return notations[0]


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
# The split: a notation parses, a definition means something
# ---------------------------------------------------------------------------


def test_notation_carries_no_definitional_payload(guarded_system):
    # The parser half is a production and nothing else. It used to carry the
    # defining form, the provisos and the kernel definition itself, each "held
    # opaquely" so this layer could avoid importing the kernel - which is the
    # shape of a courier, not of a parser.
    notation = only_notation(guarded_system)
    assert set(vars(notation)) == {"sort", "template"}

    # And it cannot apply anything: there is one way to check a step.
    assert not hasattr(notation, "kernel")
    assert not hasattr(notation, "check_application")


def test_the_definition_is_a_kernel_axiom_held_by_the_system(guarded_system):
    # The meaning half is the kernel's own Definition, and the system holds it -
    # definitions are fixed once a system is built, so the per-line context copy
    # carries only the notations that let a defined form parse.
    (definition,) = guarded_system.definitions
    assert isinstance(definition, KernelDefinition)
    assert all(
        not isinstance(entry, KernelDefinition)
        for entry in context_of(guarded_system).definitions
    )


# ---------------------------------------------------------------------------
# build_kernel_definition - the build-time soundness gate
# ---------------------------------------------------------------------------


def test_binder_free_alias_builds_a_kernel_definition(alias_system):
    # The kernel counterpart is built with the system, not derived per step.
    assert only_definition(alias_system) is not None


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


def test_a_notation_with_no_defining_form_is_refused(alias_system):
    # Notation can be registered without a defining form — it then makes the
    # defined form parse, but there is nothing to unfold *to*, so no kernel
    # definition can be built for it.
    context = context_of(alias_system)
    formula = alias_system.build_context.variables["formula"]
    notation = formula.add_notation("x beside y", context)

    with pytest.raises(DefinitionError, match="no defining form"):
        build_kernel_definition(notation, None, context)


def test_constant_carrying_definition_builds_a_kernel_definition(const_system):
    # `⊥` is a lower-only ground leaf, like an undeclared binder — but it is a
    # grammar constant, which can never be captured, so the gate admits it.
    assert only_definition(const_system) is not None


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

    context = context_of(system)
    _proof, (abbreviated, spelled, other) = formulae(
        system, "S", "(⊥ → ⊥)", "(⊥ → (⊥ → ⊥))"
    )
    assert check_definitional_step(abbreviated, spelled, definition, context) is True
    assert check_definitional_step(spelled, abbreviated, definition, context) is True
    assert check_definitional_step(abbreviated, other, definition, context) is False


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

    # `context.definitions` is a set of notations, so pick each out by its form.
    by_form = {d.template.pattern: d for d in system.context.definitions}
    assert by_form["S"].template.denotes_constant is True
    # The matching definition is the kernel one whose defined form is `T`.
    (sup,) = [d for d in system.definitions if d.higher.to_string() == "T"]

    context = context_of(system)
    _proof, (abbreviated, spelled) = formulae(system, "T", "S")
    assert check_definitional_step(abbreviated, spelled, sup, context) is True


def test_every_constructor_snapshots_its_production_s_declared_role():
    # `Constructor.denotes_constant` is a snapshot taken when the production is
    # first projected, not a delegation that reads the production back. That is
    # only sound while nothing sets the flag *after* a term could carry the
    # constructor — the one place that could is a nullary defined form, whose role
    # the build derives, and it is settled before the kernel definition (and so
    # before the first projection) is built.
    #
    # A resequencing that moved it back would leave `S` snapshotted False while
    # its production says True, and `T ≝ S` would start failing to build for a
    # reason with no connection to the definition.
    spec = nullary_spec(closed=True)
    spec.definitions.append(defn("formula", "t", "T", "S", []))
    system = build_declarative(spec)

    productions = list(system.context.variables.values()) + [
        d.template for d in system.context.definitions
    ]
    stale = [
        p.name
        for p in productions
        if hasattr(p, "pattern_type")
        and constructor_for(p).denotes_constant != p.denotes_constant
    ]
    assert stale == []

    # And the interesting one is genuinely True, so the check above is not vacuous.
    notation = next(d for d in system.context.definitions if d.template.pattern == "S")
    assert constructor_for(notation.template).denotes_constant is True


def test_a_defined_form_the_grammar_already_parses_is_not_a_constant():
    # A nullary notation whose form a declared production *already* parses. A
    # sort tries its productions before its notations, so this notation never
    # fires and its form parses to a compound, not to a leaf of its own — the
    # opposite of what makes a nullary abbreviation a constant.
    #
    # "Nullary" alone would mark it constant, which is the unsafe direction: the
    # flag is what excuses a later definition from accounting for a token.
    spec = nullary_spec(closed=True)
    spec.definitions = [defn("formula", "shadowed", "(⊥ → ⊥)", "⊥", [])]
    system = build_declarative(spec)

    notation = only_notation(system)
    assert notation.template.pattern == "(⊥ → ⊥)"
    assert notation.template.denotes_constant is False
    assert constructor_for(notation.template).denotes_constant is False

    # And the form really is parsed by the declared production, not the notation.
    formula = context_of(system).variables["formula"]
    matched = formula.match("(⊥ → ⊥)", context_of(system))
    assert matched is not None
    assert matched.pattern is not notation.template


def test_layering_on_a_definition_with_parameters_introduces_nothing():
    # The counterpart: `(x ∉ y)` is compound, never a ground leaf, so the derived
    # role is False and nothing is excused by it — there was nothing to excuse.
    system = build_declarative(const_spec())
    assert only_notation(system).template.denotes_constant is False


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
    assert only_definition(system) is not None


# ---------------------------------------------------------------------------
# check_definitional_step - the term-based step check (kernel path)
# ---------------------------------------------------------------------------


def formulae(system, *lines):
    # The parsed lines' kernel terms - what `follows_by_definition` takes, and
    # what a proof line carries: the projection happens during parsing.
    proof = system.parse("\n".join(f"{line} [HYP]" for line in lines))
    return proof, [pl.formula_term for pl in proof.proof_lines]


def test_alias_unfold_accepted_both_directions(alias_system):
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    _proof, (alias, canonical) = formulae(alias_system, "a sub b", "(a ∈ b)")

    assert alias is not None and canonical is not None
    # Fold direction and unfold direction both hold: one definitional step apart.
    assert check_definitional_step(alias, canonical, definition, context) is True
    assert check_definitional_step(canonical, alias, definition, context) is True


def test_alias_unfold_rejects_a_different_formula(alias_system):
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    _proof, (alias, other) = formulae(alias_system, "a sub b", "(a ∈ c)")

    assert check_definitional_step(alias, other, definition, context) is False


def test_constant_definition_unfold_checked_by_the_kernel(const_system):
    # The unfold of a constant-carrying definition is verified over kernel terms,
    # in both directions, and a wrong formula is rejected — the constant `⊥` rides
    # through the term check unchanged.
    definition = only_definition(const_system)
    context = context_of(const_system)
    _proof, (folded, unfolded, other) = formulae(
        const_system, "(a ∉ b)", "((a ∈ b) → ⊥)", "(a ∈ b)"
    )

    assert check_definitional_step(folded, unfolded, definition, context) is True
    assert check_definitional_step(unfolded, folded, definition, context) is True
    assert check_definitional_step(folded, other, definition, context) is False


def test_follows_from_definition_uses_the_kernel_path(alias_system):
    # End-to-end through the ProofLine method: a correct step is accepted and a
    # wrong one rejected, with the kernel definition actually built (kernel path).
    definition = only_definition(alias_system)
    context = context_of(alias_system)
    proof, _ = formulae(alias_system, "a sub b", "(a ∈ b)", "(a ∈ c)")
    alias_line, canonical_line, other_line = proof.proof_lines

    assert alias_line.follows_from_definition(canonical_line, definition, context) is True
    assert alias_line.follows_from_definition(other_line, definition, context) is False


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
    # `fresh` pairs each declared binder with its sort.
    assert {name for name, _sort in definition.fresh} == {"z"}


def test_declared_binder_builds_a_kernel_definition(fresh_system):
    assert only_definition(fresh_system) is not None


def test_declared_binder_unfold_accepted_both_directions(fresh_system):
    definition = only_definition(fresh_system)
    context = context_of(fresh_system)
    proof, (subset, unfolded) = formulae(
        fresh_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))"
    )
    assert check_definitional_step(subset, unfolded, definition, context) is True
    assert check_definitional_step(unfolded, subset, definition, context) is True


def test_declared_binder_rejects_a_wrong_unfold(fresh_system):
    definition = only_definition(fresh_system)
    context = context_of(fresh_system)
    _proof, (subset, other) = formulae(
        fresh_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ c))"
    )
    assert check_definitional_step(subset, other, definition, context) is False


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
    assert check_definitional_step(subset, renamed, definition, context) is True
    assert check_definitional_step(subset, captured, definition, context) is False


# ---------------------------------------------------------------------------
# `where` clause: kernel-vocabulary provisos gate the unfold
# ---------------------------------------------------------------------------


def test_where_proviso_is_parsed_into_a_kernel_condition(guarded_system):
    definition = only_definition(guarded_system)
    assert definition.condition is not None


def test_where_proviso_gates_the_unfold(guarded_system):
    definition = only_definition(guarded_system)
    context = context_of(guarded_system)
    # Disjoint arguments: the unfold holds.
    _p1, (ok_subset, ok_unfold) = formulae(
        guarded_system, "(a ⊆ b)", "∀z.((z ∈ a) → (z ∈ b))"
    )
    assert check_definitional_step(ok_subset, ok_unfold, definition, context) is True
    # Equal arguments violate disjoint(x, y, setvar): the step is rejected.
    _p2, (bad_subset, bad_unfold) = formulae(
        guarded_system, "(a ⊆ a)", "∀z.((z ∈ a) → (z ∈ a))"
    )
    assert check_definitional_step(bad_subset, bad_unfold, definition, context) is False


def test_a_definition_has_no_second_way_to_be_applied(guarded_system):
    # The string-layer application primitives are gone. They could not evaluate a
    # `where` proviso, so a definition carrying one had to be refused there and
    # checked on the kernel path — two paths disagreeing by construction. Now
    # there is one, and this pins that the other cannot come back unnoticed.
    definition = only_definition(guarded_system)
    assert definition.condition is not None
    assert not hasattr(definition, "check_application")
    assert not hasattr(definition, "get_lower")

    # The notation parses the defined form; it has no way to apply anything.
    notation = only_notation(guarded_system)
    higher = notation.template.match("(a ⊆ b)", context_of(guarded_system))
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
