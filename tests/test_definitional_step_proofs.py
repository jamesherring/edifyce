"""The definitional-step proof surface.

A proof line justified as ``[<name>, <line>]`` (a named definition) or the
generic ``[Def, <line>]`` claims to be the cited line with one definition (in
scope) unfolded or folded at a single position, verified over kernel terms
(ProofLine.follows_from_definition -> check_definitional_step). A named citation
pins the specific definition; the generic keyword searches those in scope. These
tests cover named and generic citation for a string-path alias definition and a
kernel-path binder definition, the scope/ordering guards, dependency recording,
and that an inference rule of the same label still takes precedence.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import LinePart, LineSpec, Rule, SystemSpec, build_spec

from tests.spec_helpers import brackets, defn, regex_prod, rule, template_prod


def build_declarative(spec: SystemSpec):
    result = build_spec(spec)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def _statement_line() -> LineSpec:
    # The reference part allows the hyphen in labels like `df-subset` and the
    # comma/space in `Def, 1` (a wider set than the shared statement_line helper).
    return LineSpec(
        name="statement",
        shape="<formula> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9, -]+")],
        logical_sort="formula",
    )


def _setvar_prod():
    return regex_prod("setvar", "setvar_atom", "[a-z]")


def _hyp_rule() -> Rule:
    # `with f as formula: deduction f` - introduce any formula from nothing so
    # either the folded or unfolded form can open a proof.
    return rule("HYP", "hypothesis", [], "f", [("f", "formula")])


# An alias definition (string path): `x sub y` abbreviates the membership
# `(x ∈ y)`, named `sub` so a proof can cite it as `[sub, <line>]`. Extra labelled
# definitions can be appended for the distinct/duplicate-label cases.
def alias_spec(extra_definitions: tuple = ()) -> SystemSpec:
    return SystemSpec(
        name="AliasSys",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
        ],
        lines=[_statement_line()],
        definitions=[
            defn("formula", "sub", "x sub y", "(x ∈ y)",
                 [("x", "setvar"), ("y", "setvar")], label="sub"),
            *extra_definitions,
        ],
        rules=[_hyp_rule()],
    )


# A binder definition (kernel path): df-subset, whose defining form binds a fresh
# z, declared with the `fresh` clause so the unfold is capture-avoiding. Named
# `df-subset` (a hyphen in the label, hence the wider reference part).
def subset_spec() -> SystemSpec:
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
        lines=[_statement_line()],
        definitions=[
            defn("formula", "df_subset", "(x ⊆ y)", "∀z.((z ∈ x) → (z ∈ y))",
                 [("x", "setvar"), ("y", "setvar")], fresh=[("z", "setvar")], label="df-subset"),
        ],
        rules=[_hyp_rule()],
    )


# A system whose inference-rule label collides with the definitional-step
# keyword `Def`, to confirm the rule wins.
def colliding_spec() -> SystemSpec:
    return SystemSpec(
        name="Collide",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]")],
        lines=[_statement_line()],
        rules=[
            rule("HYP", "hypothesis", [], "p", [("p", "formula")]),
            rule("Def", "repetition", ["p"], "p", [("p", "formula")]),
        ],
    )


@pytest.fixture(scope="module")
def alias_system():
    return build_declarative(alias_spec())


@pytest.fixture(scope="module")
def subset_system():
    return build_declarative(subset_spec())


@pytest.fixture(scope="module")
def colliding_system():
    return build_declarative(colliding_spec())


# ---------------------------------------------------------------------------
# String-path alias definition
# ---------------------------------------------------------------------------


def test_unfold_step_is_valid(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ b) [Def, 1]")
    assert proof.proof_lines[1].valid is True


def test_fold_step_is_valid(alias_system):
    proof = alias_system.parse("(a ∈ b) [HYP]\na sub b [Def, 1]")
    assert proof.proof_lines[1].valid is True


def test_unrelated_step_is_rejected(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ c) [Def, 1]")
    line = proof.proof_lines[1]
    assert line.valid is False
    assert "does not apply" in line.invalid_message


def test_step_records_the_dependency_edge(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ b) [Def, 1]")
    source, step = proof.proof_lines
    assert step in source.dependent_lines
    assert step.antecedents == (source,)


# ---------------------------------------------------------------------------
# Named citation
# ---------------------------------------------------------------------------


def test_named_definition_unfold_is_valid(alias_system):
    # `sub` is the label from `Define x sub y as (x ∈ y) label sub`.
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ b) [sub, 1]")
    assert proof.proof_lines[1].valid is True


def test_named_definition_fold_is_valid(alias_system):
    proof = alias_system.parse("(a ∈ b) [HYP]\na sub b [sub, 1]")
    assert proof.proof_lines[1].valid is True


def test_named_definition_wrong_step_is_rejected(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ c) [sub, 1]")
    assert proof.proof_lines[1].valid is False


def test_unknown_definition_name_is_an_invalid_reference(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ b) [nope, 1]")
    line = proof.proof_lines[1]
    assert line.valid is False
    assert "not a valid inference rule or definition" in line.invalid_message


def test_named_binder_definition_unfold_is_valid(subset_system):
    # Cite df-subset by name (matching the kernel docstring's example).
    proof = subset_system.parse("(a ⊆ b) [HYP]\n∀z.((z ∈ a) → (z ∈ b)) [df-subset, 1]")
    assert proof.proof_lines[1].valid is True


def test_equivalent_definitions_keep_their_distinct_labels():
    # The same forms declared under two labels must stay separately citable -
    # equivalence-based dedup must not collapse them and drop a label.
    system = build_declarative(alias_spec(extra_definitions=(
        defn("formula", "sub2", "x sub y", "(x ∈ y)",
             [("x", "setvar"), ("y", "setvar")], label="subseteq"),
    )))
    for label in ("sub", "subseteq"):
        proof = system.parse(f"a sub b [HYP]\n(a ∈ b) [{label}, 1]")
        assert proof.proof_lines[1].valid is True, label

    # Two axioms, but one production: a shared defined form is one way to build a
    # formula however many definitions declare it. The notation must de-duplicate
    # against the registry the *system* holds, not against a scoped copy of it -
    # a second entry would make every failed parse redo the same matcher work.
    assert len(system.definitions) == 2
    assert len(system.context.definitions) == 1


def test_duplicate_definition_labels_are_a_build_error():
    # A cited name must resolve to one definition, so two definitions sharing a
    # label is rejected at build time.
    result = build_spec(alias_spec(extra_definitions=(
        defn("formula", "has", "y has x", "(x ∈ y)",
             [("x", "setvar"), ("y", "setvar")], label="sub"),
    )))
    assert "errors" in result
    assert any("Duplicate definition label" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Kernel-path binder definition (generic keyword)
# ---------------------------------------------------------------------------


def test_binder_definition_unfold_step_is_valid(subset_system):
    proof = subset_system.parse("(a ⊆ b) [HYP]\n∀z.((z ∈ a) → (z ∈ b)) [Def, 1]")
    assert proof.proof_lines[1].valid is True


def test_binder_definition_fold_step_is_valid(subset_system):
    proof = subset_system.parse("∀z.((z ∈ a) → (z ∈ b)) [HYP]\n(a ⊆ b) [Def, 1]")
    assert proof.proof_lines[1].valid is True


def test_binder_definition_wrong_unfold_is_rejected(subset_system):
    proof = subset_system.parse("(a ⊆ b) [HYP]\n∀z.((z ∈ a) → (z ∈ c)) [Def, 1]")
    assert proof.proof_lines[1].valid is False


# ---------------------------------------------------------------------------
# Citation guards and rule precedence
# ---------------------------------------------------------------------------


def test_step_requires_exactly_one_cited_line(alias_system):
    proof = alias_system.parse("a sub b [HYP]\n(a ∈ b) [HYP]\n(a ∈ b) [Def, 1, 2]")
    line = proof.proof_lines[2]
    assert line.valid is False


def test_step_must_cite_an_earlier_line(alias_system):
    # Citing a later line (line 2) from line 1 is rejected on ordering grounds.
    proof = alias_system.parse("a sub b [Def, 2]\n(a ∈ b) [HYP]")
    assert proof.proof_lines[0].valid is False


def test_citing_an_unparsed_line_is_a_graceful_invalid(alias_system):
    # The cited source line failed to parse (no line type); the step must be a
    # clean invalid line, not an AttributeError inside follows_from_definition.
    proof = alias_system.parse("!!!garbage\n(a ∈ b) [Def, 1]")
    line = proof.proof_lines[1]
    assert line.valid is False
    assert "not a formula line" in line.invalid_message


def test_inference_rule_label_takes_precedence_over_the_keyword(colliding_system):
    # `Def` names a repetition rule here, so `[Def, 1]` applies that rule (a is
    # repeated) rather than a definitional step.
    proof = colliding_system.parse("a [HYP]\na [Def, 1]")
    line = proof.proof_lines[1]
    assert line.valid is True
    assert line.inference_rule is not None
