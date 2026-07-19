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

from website.logical.compiler import compile as compile_formal_system


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


# An alias definition (string path): `x sub y` abbreviates the membership
# `(x ∈ y)`. HYP introduces any formula so either form can open a proof.
ALIAS_SYSTEM = """FormalSystem AliasSys:

    Regex setvar:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z0-9, -]+$

    Pattern membership:
        with x as setvar, y as setvar:
            (x ∈ y)
            Define x sub y as (x ∈ y) label sub

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


# A binder definition (kernel path): df-subset, whose defining form binds a fresh
# z, declared with the `fresh` clause so the unfold is capture-avoiding.
SUBSET_SYSTEM = """FormalSystem SetTheory:

    Regex setvar:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z0-9, -]+$

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
            Define (x ⊆ y) as ∀z.((z ∈ x) → (z ∈ y)) fresh z as setvar label df-subset

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


# A system whose inference-rule label collides with the definitional-step
# keyword, to confirm rules win.
COLLIDING_SYSTEM = """FormalSystem Collide:

    Regex atom:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z0-9, -]+$

    UnionPattern formula:
        atom

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

    with p as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                p

        InferenceRule repetition:
            label:
                Def
            antecedents:
                p
            deduction:
                p
"""


@pytest.fixture(scope="module")
def alias_system():
    return compiled(ALIAS_SYSTEM)


@pytest.fixture(scope="module")
def subset_system():
    return compiled(SUBSET_SYSTEM)


@pytest.fixture(scope="module")
def colliding_system():
    return compiled(COLLIDING_SYSTEM)


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


def test_inference_rule_label_takes_precedence_over_the_keyword(colliding_system):
    # `Def` names a repetition rule here, so `[Def, 1]` applies that rule (a is
    # repeated) rather than a definitional step.
    proof = colliding_system.parse("a [HYP]\na [Def, 1]")
    line = proof.proof_lines[1]
    assert line.valid is True
    assert line.inference_rule is not None
