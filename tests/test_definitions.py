"""Tests for definitions as cited axioms (kernel step 4).

A definition is verified as a single unfold: ``check_definitional_step`` accepts
exactly a one-position rewrite between a defined form and its defining form (in
either direction), and rejects wrong expansions, no-ops, and two-at-once. The
defining form is multi-level (``∀z.(…→…)``), so these also exercise that a
definition schema keeps its grammatical structure (built via parse + abstract).
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Definition as Definition_
from website.logical.declarative import SystemSpec, build_spec, build_system
from website.logical.kernel import (
    Definition,
    DisjointLeaves,
    Var,
    check_definitional_step,
    from_match,
    introduced_leaves,
    match,
    unbound_parameters,
    unfold,
)
from website.logical.matching import Context, RegexPattern, StringPattern, UnionPattern
from tests.spec_helpers import (
    atom_const_prod,
    atom_family_prod,
    brackets,
    regex_prod,
    statement_line,
    template_prod,
)


def build(spec):
    system = build_system(spec)
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return system, context


# Set theory: membership, implication, a universal quantifier, and subset -
# enough to state df-subset as a genuinely multi-level definition. `setvar` is a
# leaf sort whose regex member is named distinctly from the sort.
SET_THEORY = SystemSpec(
    name="SetTheory",
    brackets=brackets(),
    productions=[
        regex_prod("setvar", "letter", "[a-z]"),
        template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
        template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
        template_prod("formula", "subset", "(x ⊆ y)", [("x", "setvar"), ("y", "setvar")]),
    ],
    lines=[statement_line()],
)


@pytest.fixture(scope="module")
def theory():
    system, context = build(SET_THEORY)
    return system, context


@pytest.fixture(scope="module")
def formula(theory):
    system, _context = theory
    return system.build_context.variables["formula"]


@pytest.fixture(scope="module")
def setvar(theory):
    system, _context = theory
    return system.build_context.variables["setvar"]


def term(theory, formula, string):
    _system, context = theory
    matched = formula.match(string, context)
    assert matched is not None, string
    return from_match(matched)


# Propositional logic with a biconditional whose arguments are *formulas*. Unlike
# df-subset (whose arguments are atoms and so cannot nest), df-bicon's redex can
# contain another biconditional, which is what lets a definition apply at
# overlapping (nested) positions.
PROP = SystemSpec(
    name="Prop",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z]"),
        template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
        template_prod("formula", "conjunction", "(p ∧ q)", [("p", "formula"), ("q", "formula")]),
        template_prod("formula", "biconditional", "(p ↔ q)", [("p", "formula"), ("q", "formula")]),
    ],
    lines=[statement_line()],
)


@pytest.fixture(scope="module")
def prop():
    system, context = build(PROP)
    return system, context


@pytest.fixture(scope="module")
def prop_formula(prop):
    system, _context = prop
    return system.build_context.variables["formula"]


def df_bicon(prop):
    # (p ↔ q)  :=  ((p → q) ∧ (q → p)) - a purely structural definition over
    # formula arguments (no binders, so no `fresh`).
    _system, context = prop
    formula = _system.build_context.variables["formula"]
    return Definition.parse(
        formula,
        "(p ↔ q)",
        "((p → q) ∧ (q → p))",
        {"p": formula, "q": formula},
        context,
    )


def df_subset(theory, setvar, condition=None, fresh=None):
    # (x ⊆ y)  :=  ∀z.((z ∈ x) → (z ∈ y))
    _system, context = theory
    formula = _system.build_context.variables["formula"]
    return Definition.parse(
        formula,
        "(x ⊆ y)",
        "∀z.((z ∈ x) → (z ∈ y))",
        {"x": setvar, "y": setvar},
        context,
        condition=condition,
        fresh=fresh,
    )


# ---------------------------------------------------------------------------
# unfold
# ---------------------------------------------------------------------------


def test_unfold_expands_the_defined_form(theory, formula, setvar):
    _system, context = theory
    result = unfold(df_subset(theory, setvar), term(theory, formula, "(a ⊆ b)"), context)
    assert result is not None
    assert result.to_string() == "∀z.((z ∈ a) → (z ∈ b))"


def test_unfold_returns_none_for_a_non_redex(theory, formula, setvar):
    _system, context = theory
    # A membership is not an instance of the definition's higher form.
    assert unfold(df_subset(theory, setvar), term(theory, formula, "(a ∈ b)"), context) is None


# ---------------------------------------------------------------------------
# check_definitional_step
# ---------------------------------------------------------------------------


def test_accepts_a_root_unfold(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    assert check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        d,
        context,
    )


def test_accepts_the_fold_direction(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Same step stated the other way round (contracting to the defined form).
    assert check_definitional_step(
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        term(theory, formula, "(a ⊆ b)"),
        d,
        context,
    )


def test_rejects_a_wrong_expansion(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    assert not check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ c))"),  # b became c
        d,
        context,
    )


def test_rejects_a_no_op(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    line = term(theory, formula, "(a ⊆ b)")
    # Identical terms: no rewrite happened, so it is not a definitional step.
    assert not check_definitional_step(line, line, d, context)


def test_unfolds_a_subterm(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Unfold the left conjunct of an implication, leaving the right untouched.
    assert check_definitional_step(
        term(theory, formula, "((a ⊆ b) → (c ⊆ d))"),
        term(theory, formula, "(∀z.((z ∈ a) → (z ∈ b)) → (c ⊆ d))"),
        d,
        context,
    )


def test_rejects_two_unfolds_at_once(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar)
    # Both subset occurrences expanded: more than one position changed.
    assert not check_definitional_step(
        term(theory, formula, "((a ⊆ b) → (c ⊆ d))"),
        term(theory, formula, "(∀z.((z ∈ a) → (z ∈ b)) → ∀z.((z ∈ c) → (z ∈ d)))"),
        d,
        context,
    )


# ---------------------------------------------------------------------------
# A definition's side-condition gates the unfold
# ---------------------------------------------------------------------------


def test_side_condition_gates_the_unfold(theory, formula, setvar):
    # A definition may carry an *additional* step-3 proviso (beyond the
    # capture-avoidance generated from `fresh`); here it requires the two
    # arguments to be distinct variables. The unfold only fires when it holds.
    _system, context = theory
    d = df_subset(theory, setvar, condition=DisjointLeaves("x", "y", sort=setvar))

    # Distinct arguments: proviso holds, unfold applies.
    assert check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        d,
        context,
    )
    # Equal arguments: proviso fails, so there is no valid definitional step.
    assert unfold(d, term(theory, formula, "(a ⊆ a)"), context) is None
    assert not check_definitional_step(
        term(theory, formula, "(a ⊆ a)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ a))"),
        d,
        context,
    )


# ---------------------------------------------------------------------------
# A definition-only surface form still matches a variable of its sort
# ---------------------------------------------------------------------------


def test_definition_backed_subject_admits_its_sort():
    # A form reachable only through a definition on a union sort has an ad-hoc
    # `higher` constructor, but it still *inhabits* the union (e.g. `formula`).
    # A schematic variable of that sort must therefore bind to it.
    context = Context()
    setvar = RegexPattern("setvar", "^[a-z]$")
    membership = StringPattern("membership", "x in y", variables={"x": setvar, "y": setvar})
    formula = UnionPattern("formula", [membership])

    context.string_variables = {"x": setvar, "y": setvar}
    formula.add_notation("x is a member of y", context)

    subject = from_match(formula.match("a is a member of b", context))
    # Its recorded sort is the union it belongs to, not its higher constructor.
    assert subject.sort is formula

    binding = match(Var("phi", formula), subject, context)
    assert binding is not None
    assert binding["phi"].to_string() == "a is a member of b"


# ---------------------------------------------------------------------------
# A definition is usable in both directions within a proof
# ---------------------------------------------------------------------------


def test_definition_used_in_both_directions(theory, formula, setvar):
    # A single definition supports both unfolding (defined -> defining) and
    # folding (defining -> defined), at the root and inside a larger formula -
    # the two directions a proof may cite df-subset.
    _system, context = theory
    d = df_subset(theory, setvar)

    subset = "(a ⊆ b)"
    expanded = "∀z.((z ∈ a) → (z ∈ b))"
    subset_in_context = "((a ⊆ b) → (c ⊆ d))"
    expanded_in_context = "(∀z.((z ∈ a) → (z ∈ b)) → (c ⊆ d))"

    steps = [
        (subset, expanded),                        # unfold, at the root
        (expanded, subset),                        # fold, at the root
        (subset_in_context, expanded_in_context),  # unfold, inside a larger formula
        (expanded_in_context, subset_in_context),  # fold, inside a larger formula
    ]

    for before, after in steps:
        b, a = term(theory, formula, before), term(theory, formula, after)
        # The two forms genuinely differ (so a direction was really applied)...
        assert not b.equal(a, context)
        # ...and the same definition `d` justifies the step either way.
        assert check_definitional_step(b, a, d, context), f"{before} -> {after}"


# ---------------------------------------------------------------------------
# Capture-avoidance: an application that would replace a bound variable is
# rejected, even though it is a structurally valid instance of the defined form
# ---------------------------------------------------------------------------


def test_rejects_capturing_unfold(theory, formula, setvar):
    # df-subset binds z in its defining form. Declaring z `fresh` makes the
    # kernel reject any application whose argument is z (or contains it), because
    # unfolding would place a free z under ∀z and capture it.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    # `(z ⊆ b)` matches the defined form (x := z), but unfolding it would yield
    # ∀z.((z ∈ z) → (z ∈ b)) - the argument z captured by the binder. Rejected.
    assert unfold(d, term(theory, formula, "(z ⊆ b)"), context) is None
    assert unfold(d, term(theory, formula, "(a ⊆ z)"), context) is None  # other slot too
    assert not check_definitional_step(
        term(theory, formula, "(z ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ z) → (z ∈ b))"),  # the (wrong) captured form
        d,
        context,
    )

    # Arguments clear of the bound variable are unaffected - the unfold applies.
    assert unfold(d, term(theory, formula, "(a ⊆ b)"), context) is not None
    assert check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀z.((z ∈ a) → (z ∈ b))"),
        d,
        context,
    )


def test_without_fresh_the_unfold_would_capture(theory, formula, setvar):
    # Contrast: a definition that does NOT declare its bound variable has no
    # capture-avoidance proviso, so the same application unfolds unsoundly. This
    # documents why `fresh` is required for a binder-carrying definition.
    _system, context = theory
    unguarded = df_subset(theory, setvar)  # no fresh

    captured = unfold(unguarded, term(theory, formula, "(z ⊆ b)"), context)
    assert captured is not None
    assert captured.to_string() == "∀z.((z ∈ z) → (z ∈ b))"  # z was captured


# ---------------------------------------------------------------------------
# Abstract bound variables: a would-be capturing application unfolds cleanly
# once the consumer renames the binder to a fresh name (instead of being
# rejected outright).
# ---------------------------------------------------------------------------


def test_unfold_renames_the_binder_to_a_chosen_fresh_name(theory, formula, setvar):
    # `(z ⊆ b)` collides with the bound `z`. Declaring `z` fresh makes the binder
    # abstract, so the consumer can pick a fresh name `w`: the unfold renames the
    # binder rather than capturing the argument.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    renamed = unfold(d, term(theory, formula, "(z ⊆ b)"), context, names={"z": "w"})
    assert renamed is not None
    assert renamed.to_string() == "∀w.((w ∈ z) → (w ∈ b))"  # binder renamed, no capture

    # The other slot behaves symmetrically: `(a ⊆ z)` -> ∀w.(w ∈ a → w ∈ z).
    other = unfold(d, term(theory, formula, "(a ⊆ z)"), context, names={"z": "w"})
    assert other is not None
    assert other.to_string() == "∀w.((w ∈ a) → (w ∈ z))"


def test_a_chosen_name_that_still_collides_is_rejected(theory, formula, setvar):
    # Renaming does not license *any* name - the chosen name must itself be fresh.
    # Picking `z` (the argument) or `b` (the other argument) would recapture.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    assert unfold(d, term(theory, formula, "(z ⊆ b)"), context, names={"z": "z"}) is None
    assert unfold(d, term(theory, formula, "(z ⊆ b)"), context, names={"z": "b"}) is None
    # A clear name still works, confirming only the colliding choices are refused.
    assert unfold(d, term(theory, formula, "(z ⊆ b)"), context, names={"z": "w"}) is not None


def test_check_step_recovers_the_renamed_binder_from_the_target(theory, formula, setvar):
    # In a proof the chosen name is not supplied separately: it is read off the
    # target line. `check_definitional_step` therefore accepts the renamed unfold
    # (in both directions) and still rejects a target that recaptures.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    subset = "(z ⊆ b)"
    renamed = "∀w.((w ∈ z) → (w ∈ b))"

    # Unfold and fold, with the fresh name recovered from `renamed`.
    assert check_definitional_step(
        term(theory, formula, subset), term(theory, formula, renamed), d, context
    )
    assert check_definitional_step(
        term(theory, formula, renamed), term(theory, formula, subset), d, context
    )

    # A target that reuses a colliding name is still rejected: `∀z.(z ∈ z → z ∈ b)`
    # recaptures the argument `z`, and `∀b.(b ∈ z → b ∈ b)` recaptures `b`.
    assert not check_definitional_step(
        term(theory, formula, subset),
        term(theory, formula, "∀z.((z ∈ z) → (z ∈ b))"),
        d,
        context,
    )
    assert not check_definitional_step(
        term(theory, formula, subset),
        term(theory, formula, "∀b.((b ∈ z) → (b ∈ b))"),
        d,
        context,
    )


def test_check_step_requires_the_binder_used_consistently(theory, formula, setvar):
    # The binder is one abstract node shared across its occurrences, so a target
    # that spells it differently in different positions is not a valid unfold.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    assert not check_definitional_step(
        term(theory, formula, "(a ⊆ b)"),
        term(theory, formula, "∀w.((w ∈ a) → (v ∈ b))"),  # w vs v: inconsistent
        d,
        context,
    )


def test_renamed_unfold_applies_inside_a_larger_formula(theory, formula, setvar):
    # Binder renaming composes with the subterm descent: the left conjunct is
    # unfolded (with a fresh `w`) while the right subset is left untouched.
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    assert check_definitional_step(
        term(theory, formula, "((z ⊆ b) → (c ⊆ d))"),
        term(theory, formula, "(∀w.((w ∈ z) → (w ∈ b)) → (c ⊆ d))"),
        d,
        context,
    )


# ---------------------------------------------------------------------------
# Depth: a step is *one position*, reachable arbitrarily deep. The rewrite is
# not root-only - `check_definitional_step` descends to the single changed
# subterm and carries everything enclosing it through unchanged.
# ---------------------------------------------------------------------------


def test_unfolds_a_deeply_nested_subterm(theory, formula, setvar):
    # The subset redex sits three constructors down: ∀ over → over the subset.
    # Only it is rewritten; the quantifier, the implication and the sibling
    # membership are all preserved.
    _system, context = theory
    d = df_subset(theory, setvar)

    before = "∀e.((a ⊆ b) → (c ∈ d))"
    after = "∀e.(∀z.((z ∈ a) → (z ∈ b)) → (c ∈ d))"
    assert check_definitional_step(
        term(theory, formula, before), term(theory, formula, after), d, context
    )
    # ...and the fold direction reaches just as deep.
    assert check_definitional_step(
        term(theory, formula, after), term(theory, formula, before), d, context
    )


# ---------------------------------------------------------------------------
# Several candidate sites, one applied: the step selects exactly one occurrence
# even when the definition could fire at multiple (disjoint) positions.
# ---------------------------------------------------------------------------


def test_selects_one_of_several_sibling_redexes(theory, formula, setvar):
    # Both conjuncts are subset redexes; unfolding *either* is a valid step, and
    # the two are independent (unfolding one leaves the other intact).
    _system, context = theory
    d = df_subset(theory, setvar)

    both = "((a ⊆ b) → (c ⊆ d))"
    left_only = "(∀z.((z ∈ a) → (z ∈ b)) → (c ⊆ d))"
    right_only = "((a ⊆ b) → ∀z.((z ∈ c) → (z ∈ d)))"

    assert check_definitional_step(
        term(theory, formula, both), term(theory, formula, left_only), d, context
    )
    assert check_definitional_step(
        term(theory, formula, both), term(theory, formula, right_only), d, context
    )


def test_selects_one_of_two_identical_sibling_redexes(theory, formula, setvar):
    # The two candidate sites are *identical* (`(a ⊆ b)` twice). Unfolding one is
    # still a single-position step - stressing that "exactly one child differs"
    # holds even when the children started out equal - while unfolding both is not.
    _system, context = theory
    d = df_subset(theory, setvar)

    both_same = "((a ⊆ b) → (a ⊆ b))"
    one_expanded = "(∀z.((z ∈ a) → (z ∈ b)) → (a ⊆ b))"
    both_expanded = "(∀z.((z ∈ a) → (z ∈ b)) → ∀z.((z ∈ a) → (z ∈ b)))"

    assert check_definitional_step(
        term(theory, formula, both_same), term(theory, formula, one_expanded), d, context
    )
    assert not check_definitional_step(
        term(theory, formula, both_same), term(theory, formula, both_expanded), d, context
    )


# ---------------------------------------------------------------------------
# Overlapping (nested) candidate sites: with df-bicon a redex can *contain*
# another redex of the same definition. Applying the outer, the inner, or a
# deeply-nested occurrence are each valid single steps; applying two at once is
# not - regardless of how the definition's RHS duplicates its arguments.
# ---------------------------------------------------------------------------


def test_unfolds_the_outer_of_two_overlapping_redexes(prop, prop_formula):
    # `((a ↔ b) ↔ c)`: expand the outer ↔. Its RHS mentions each argument twice,
    # so the inner `(a ↔ b)` is *duplicated* into the result - but it is carried
    # through unexpanded, so this is still one unfold at one position.
    _system, context = prop
    d = df_bicon(prop)

    assert check_definitional_step(
        term(prop, prop_formula, "((a ↔ b) ↔ c)"),
        term(prop, prop_formula, "(((a ↔ b) → c) ∧ (c → (a ↔ b)))"),
        d,
        context,
    )


def test_unfolds_the_inner_of_two_overlapping_redexes(prop, prop_formula):
    # Same term, but expand the *inner* ↔ instead, leaving the outer intact.
    _system, context = prop
    d = df_bicon(prop)

    assert check_definitional_step(
        term(prop, prop_formula, "((a ↔ b) ↔ c)"),
        term(prop, prop_formula, "(((a → b) ∧ (b → a)) ↔ c)"),
        d,
        context,
    )


def test_unfolds_the_deepest_of_nested_overlapping_redexes(prop, prop_formula):
    # `(((a ↔ b) ↔ c) ↔ d)`: expand only the innermost ↔, two constructors down.
    _system, context = prop
    d = df_bicon(prop)

    assert check_definitional_step(
        term(prop, prop_formula, "(((a ↔ b) ↔ c) ↔ d)"),
        term(prop, prop_formula, "((((a → b) ∧ (b → a)) ↔ c) ↔ d)"),
        d,
        context,
    )


def test_rejects_expanding_both_overlapping_redexes_at_once(prop, prop_formula):
    # Outer *and* inner expanded in a single claimed step: more than one position
    # changed, so it is not a single definitional unfold - in either direction.
    _system, context = prop
    d = df_bicon(prop)

    assert not check_definitional_step(
        term(prop, prop_formula, "((a ↔ b) ↔ c)"),
        term(
            prop,
            prop_formula,
            "((((a → b) ∧ (b → a)) → c) ∧ (c → ((a → b) ∧ (b → a))))",
        ),
        d,
        context,
    )


def test_selects_one_of_disjoint_bicon_redexes(prop, prop_formula):
    # Non-overlapping siblings under a conjunction: unfolding either ↔ is valid.
    _system, context = prop
    d = df_bicon(prop)

    both = "((a ↔ b) ∧ (c ↔ d))"
    left_only = "(((a → b) ∧ (b → a)) ∧ (c ↔ d))"
    right_only = "((a ↔ b) ∧ ((c → d) ∧ (d → c)))"

    assert check_definitional_step(
        term(prop, prop_formula, both), term(prop, prop_formula, left_only), d, context
    )
    assert check_definitional_step(
        term(prop, prop_formula, both), term(prop, prop_formula, right_only), d, context
    )


# ---------------------------------------------------------------------------
# A step must be *only* an unfold: recovering the binder from the target must
# not also instantiate the definition's parameters. Checking against a schema
# source (whose parameters are still variables) must keep them pinned.
# ---------------------------------------------------------------------------


def test_binder_recovery_does_not_instantiate_parameters(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})

    # `d.higher` is the schema `(x ⊆ y)`, with x/y still variables. A genuine
    # unfold keeps them variables (only the binder is named), so expanding to a
    # form where the parameters became concrete `a`/`b` is NOT a definitional
    # step - it also instantiated x:=a, y:=b.
    assert not check_definitional_step(
        d.higher,
        term(theory, formula, "∀w.((w ∈ a) → (w ∈ b))"),  # parameters instantiated
        d,
        context,
    )


# ---------------------------------------------------------------------------
# A caller-supplied binder name must denote a leaf of its sort; a name that does
# not parse as the sort is rejected rather than producing a bogus formula.
# ---------------------------------------------------------------------------


def test_rejects_a_chosen_name_that_is_not_a_leaf_of_its_sort(theory, formula, setvar):
    _system, context = theory
    d = df_subset(theory, setvar, fresh={"z": setvar})
    redex = term(theory, formula, "(a ⊆ b)")

    # `setvar` is `^[a-z]$`: neither a multi-letter name nor a compound formula
    # parses as a single variable, so the unfold is refused (no bogus `∀aa...`).
    assert unfold(d, redex, context, names={"z": "aa"}) is None
    assert unfold(d, redex, context, names={"z": "(a ∈ b)"}) is None
    # A genuine single-letter name is still accepted, confirming only the
    # ill-typed choices are refused.
    assert unfold(d, redex, context, names={"z": "w"}) is not None


# ---------------------------------------------------------------------------
# Admissibility: what a defining form may introduce
# ---------------------------------------------------------------------------


def test_a_well_formed_definition_introduces_nothing(prop):
    # Every leaf of `((p → q) ∧ (q → p))` is a parameter the defined form
    # supplies, so the unfold is free-variable preserving and there is nothing to
    # report.
    d = df_bicon(prop)
    assert unbound_parameters(d) == ()
    assert introduced_leaves(d) == ()


def test_a_declared_binder_is_not_reported(theory, setvar):
    # `z` is declared `fresh`, so it is stored abstractly and its name is chosen
    # by the step rather than supplied by the defined form. Being declared is
    # exactly what makes it safe. `Bound` subclasses `Var`, so a binder would read
    # as an undetermined parameter but for `Bound.free_vars` returning nothing —
    # this pins that the two agree.
    d = df_subset(theory, setvar, fresh={"z": setvar})
    assert unbound_parameters(d) == ()
    assert introduced_leaves(d) == ()


def test_an_undeclared_binder_is_reported_as_a_ground_leaf(theory, setvar):
    # Without `fresh`, `z` survives the parse as an ordinary ground leaf: the
    # defining form spells a name the defined form never mentions.
    d = df_subset(theory, setvar)
    assert unbound_parameters(d) == ()
    assert [leaf.literal for leaf in introduced_leaves(d)] == ["z"]


def test_a_parameter_the_defined_form_cannot_supply_is_reported(theory, setvar):
    # `w` is a parameter of the defining form alone. An unfold binds parameters by
    # matching the *defined* form against the redex, so nothing determines `w`;
    # it would be free in the result and open to capture where the step is taken.
    _system, context = theory
    formula = _system.build_context.variables["formula"]
    d = Definition.parse(
        formula,
        "(x ⊆ y)",
        "∀z.((z ∈ x) → (z ∈ w))",
        {"x": setvar, "y": setvar, "w": setvar},
        context,
        fresh={"z": setvar},
    )
    assert unbound_parameters(d) == ("w",)


def test_introduced_leaves_are_deduplicated_and_ordered(theory, setvar):
    # `z` occurs twice in the defining form; it is one problem, reported once, and
    # several are reported in a stable order so a build error reads the same way
    # every time.
    _system, context = theory
    formula = _system.build_context.variables["formula"]
    d = Definition.parse(
        formula, "(x ⊆ y)", "∀q.((z ∈ z) → (q ∈ y))", {"x": setvar, "y": setvar}, context
    )
    assert [leaf.literal for leaf in introduced_leaves(d)] == ["q", "z"]


# A grammar where one token is built by two different productions: `S` is both a
# nullary `formula` notation and a `setvar` (the regex is uppercase-only, so the
# constant `c` is not variable-like). Introduced leaves must be tracked by
# constructor, not spelling — otherwise the defined form's `formula` S excuses the
# defining form's `setvar` S, and `∀S.S ⟶ ∀S.(S ∈ c)` captures.
MASKED = SystemSpec(
    name="Masked",
    brackets=brackets(),
    productions=[
        regex_prod("setvar", "setvar_atom", "[A-Z]"),
        atom_const_prod("setvar", "cee", "c"),
        template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
        template_prod("formula", "ess", "S", []),
    ],
    lines=[statement_line()],
)


def test_a_leaf_is_not_excused_by_a_same_spelled_other_constructor():
    system, context = build(MASKED)
    formula = system.build_context.variables["formula"]
    d = Definition.parse(formula, "S", "(S ∈ c)", {}, context)

    # The `S` of `higher` is the nullary formula notation; the `S` of `lower` is a
    # setvar. Same token, different constructors, so the second is still
    # introduced — matching how `Term.equal` compares a ground leaf. `c` is
    # reported too: the kernel names every unaccounted leaf and leaves it to the
    # grammar layer to excuse the constants.
    assert [leaf.literal for leaf in introduced_leaves(d)] == ["S", "c"]
    reported = {leaf.literal: leaf for leaf in introduced_leaves(d)}
    assert reported["S"].constructor is not d.higher.constructor


def _masked_build_spec(productions):
    return SystemSpec(
        name="MaskedBuild",
        brackets=MASKED.brackets,
        productions=list(productions),
        lines=list(MASKED.lines),
        definitions=[
            Definition_(sort="formula", name="d", higher="S", lower="(S ∈ c)", bindings=[])
        ],
    )


def test_a_masked_leaf_still_fails_the_system_build():
    # End to end: neither `S` nor `c` is declared a constant, so both are refused
    # and the step `∀S.S ⟶ ∀S.(S ∈ c)` the definition would license never arises.
    result = build_spec(_masked_build_spec(MASKED.productions))
    assert "errors" in result
    (message,) = result["errors"]
    assert "'S'" in message and "'c'" in message


def test_an_atom_declared_constant_is_excused_but_a_masked_variable_is_not():
    # `c` declared a constant is excused; the `setvar` S is a variable however it
    # is spelled, so the definition is still refused — and named for the leaf that
    # actually endangers it.
    declared = [
        atom_const_prod("setvar", "cee", "c", denotes_constant=True)
        if prod.name == "cee"
        else prod
        for prod in MASKED.productions
    ]
    result = build_spec(_masked_build_spec(declared))
    assert "errors" in result
    (message,) = result["errors"]
    assert "'S'" in message and "'c'" not in message


# `c` is a member of `setvar`, so `∀c.` binds it — the author said as much by
# putting it in that union. Its *constructor* is an atom constant, which is what
# the retired shape heuristic read, so `T ≝ (c ∈ c)` was admitted and the step
# below captured `c`. Nothing about the production's shape distinguishes this
# from `formula ::= ⊥`; only the declaration does.
ATOM_VARIABLE = SystemSpec(
    name="AtomVariable",
    brackets=brackets(),
    productions=[
        regex_prod("setvar", "setvar_atom", "[A-Z]"),
        atom_const_prod("setvar", "cee", "c"),
        template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
        template_prod("formula", "tee", "T", []),
    ],
    lines=[statement_line()],
    definitions=[Definition_(sort="formula", name="d", higher="T", lower="(c ∈ c)", bindings=[])],
)


def test_an_atom_constant_in_the_variable_sort_is_not_excused():
    result = build_spec(ATOM_VARIABLE)
    assert "errors" in result
    (message,) = result["errors"]
    assert "'c'" in message


def test_an_atom_family_cannot_be_declared_a_constant():
    # A family is a supply of interchangeable tokens — `AtomPattern.fresh` mints
    # new ones, which is what eigenvariable selection draws on. So this is not a
    # judgement the author could get right, and the build refuses it rather than
    # letting it excuse `S ≝ (p_0 ∈ p_1)` and admit `∀p_0.S ⟶ ∀p_0.(p_0 ∈ p_1)`.
    spec = SystemSpec(
        name="FamilyConstant",
        brackets=brackets(),
        productions=[
            atom_family_prod("setvar", "prop", "p"),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "forall", "∀x.phi", [("x", "setvar"), ("phi", "formula")]),
            template_prod("formula", "ess", "S", []),
        ],
        lines=[statement_line()],
        definitions=[
            Definition_(sort="formula", name="d", higher="S", lower="(p_0 ∈ p_1)", bindings=[])
        ],
    )
    spec.productions[0].denotes_constant = True

    result = build_spec(spec)
    assert "errors" in result
    (message,) = result["errors"]
    assert "'prop'" in message and "p_#" in message

    # Left undeclared the family is variable-like, so the definition is refused
    # for the ordinary reason and the system still does not build.
    spec.productions[0].denotes_constant = False
    assert "errors" in build_spec(spec)


def test_declaring_a_bindable_atom_constant_is_the_author_s_to_get_wrong():
    # The declaration is authoritative: tick the box on a token a binder can bind
    # and the definition builds, and `∀c.T ⟶ ∀c.(c ∈ c)` captures `c`. Pinned so
    # the trust boundary is visible in the suite rather than only in prose — this
    # is the one direction that costs soundness, and it takes a positive act.
    #
    # Detecting it needs to know which sorts a binder ranges over, which no
    # production declares yet (see the binding-slots follow-up in AGENTS.md).
    spec = SystemSpec(
        name="AtomVariableDeclared",
        brackets=ATOM_VARIABLE.brackets,
        productions=[
            atom_const_prod("setvar", "cee", "c", denotes_constant=True)
            if prod.name == "cee"
            else prod
            for prod in ATOM_VARIABLE.productions
        ],
        lines=list(ATOM_VARIABLE.lines),
        definitions=list(ATOM_VARIABLE.definitions),
    )
    result = build_spec(spec)
    assert "errors" not in result
