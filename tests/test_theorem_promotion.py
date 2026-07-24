"""Promoting a proved/imported theorem to a reusable schematic rule.

This exercises the "A1" bridge from ``docs/setmm-import-recommendations-detail.md``:
a proved theorem should be reusable like an inference rule — its metavariables
re-instantiated at each citation by unification, subject to its distinct-variable
provisos — *without* being minted as a persisted rule per theorem.

The tests cover three things:

1. **Mechanism (graph, not string).** Promotion is a kernel-term operation:
   ``from_match`` the proved conclusion to a ground term, ``_revariabilise`` the
   named leaves to sort-widened ``Var``s, and hang the term on a schema shell. No
   ``Match.create_pattern`` string round-trip. The ephemeral rule checks through
   the real ``InferenceRule.check`` → ``_term_binding`` → ``match_all`` path.

2. **The wired citation path.** ``FormalSystem.promote`` registers a theorem in
   its own namespace (not ``inference_rules``); ``Proof.get_reference`` resolves a
   citation of that label — with or without cited premises — to an ephemeral rule.
   The previously-needed "append to inference_rules" shim is gone.

3. **Soundness under binders (``$d`` → ``disjoint``).** A promoted theorem carries
   its distinct-variable provisos; a capturing instance is rejected. Demonstrated
   with an ``ax-5``-shaped theorem ``(phi -> A.x phi)`` whose ``$d x phi`` blocks
   substituting ``phi`` with a formula in which ``x`` occurs free.
"""

from __future__ import annotations

from copy import copy

import pytest

pytest.importorskip("regex")

from tests.test_engine_neutrality import HILBERT
from website.logical.compiler import _revariabilise, build_schema_pattern
from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system.promotion import PromotedTheorem
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel.terms import from_match
from website.logical.matching.patterns import StringPattern


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


# The classic S/K/MP derivation of `a -> a`, no assumptions (test_engine_neutrality).
SELF_IMPLICATION_PROOF = (
    "((a → ((a → a) → a)) → ((a → (a → a)) → (a → a))) [S]\n"
    "(a → ((a → a) → a)) [K]\n"
    "((a → (a → a)) → (a → a)) [MP, 1, 2]\n"
    "(a → (a → a)) [K]\n"
    "(a → a) [MP, 3, 4]"
)


# A first-order fragment with a binder, for the $d test: membership, implication,
# universal, and a claim line type so standalone formulas can be checked.
AX_FIVE_SYSTEM = r"""FormalSystem AxFive:

    Regex setvar:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        membership

    Pattern membership:
        with x as setvar, y as setvar:
            x ∈ y

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    Pattern universal:
        with x as setvar, p as formula:
            ∀x p

    formula:
        membership
        implication
        universal

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern statement:
        with f as formula, r as reference:
            f [r]

    LineType claim:
        pattern: statement
        behaviour: logical
        formula: f
        reference: r
"""


# ---------------------------------------------------------------------------
# Promotion helpers — the two routes an importer would use.
# ---------------------------------------------------------------------------
def promote_proved_leaf(system, proof, generalise: str, sort_name: str) -> PromotedTheorem:
    """Graph route: build a zero-premise theorem from a *proved* line by
    generalising a named leaf to a sort-widened Var. No string round-trip."""
    context = copy(system.context)
    ground_term = from_match(proof.proof_lines[-1].formula, context)

    sort = system.build_context.variables[sort_name]
    schema_term = _revariabilise(ground_term, {generalise: sort})

    deduction = StringPattern(name=generalise, pattern=generalise)
    deduction.schema_term = schema_term
    return PromotedTheorem(label="I", deduction=deduction, variables={generalise: sort})


def promote_from_source(
    system,
    label: str,
    statement: str,
    metavariables: dict[str, str],
    premises: tuple[str, ...] = (),
    distinct: tuple[str, ...] = (),
) -> PromotedTheorem:
    """Source route (import-style): read a *schematic* statement + premises + $d
    directly. Handles formula-metavariables over compounds, which a leaf rename
    cannot. This is what an importer does with `$p`/`$e`/`$d`.
    """
    context = copy(system.build_context)
    context.string_variables = {
        name: system.build_context.variables[sort] for name, sort in metavariables.items()
    }
    deduction = build_schema_pattern(statement, context, label)
    antecedents = tuple(
        build_schema_pattern(text, context, f"{label}.ant{i}") for i, text in enumerate(premises)
    )
    side_conditions = tuple(parse_side_condition(line, context) for line in distinct)
    return PromotedTheorem(
        label=label,
        deduction=deduction,
        antecedents=antecedents,
        side_conditions=side_conditions,
        variables=dict(context.string_variables),
    )


# ---------------------------------------------------------------------------
# 1. Mechanism: promotion is a graph generalisation; the ephemeral rule checks.
# ---------------------------------------------------------------------------
def test_promotion_is_a_graph_generalisation():
    system = compiled(HILBERT)
    proof = system.parse(SELF_IMPLICATION_PROOF)
    assert proof.valid is True

    ground = from_match(proof.proof_lines[-1].formula, copy(system.context))
    assert ground.free_vars() == {}, "proved conclusion starts fully ground"

    theorem = promote_proved_leaf(system, proof, generalise="a", sort_name="formula")
    free = theorem.deduction.schema_term.free_vars()
    assert set(free) == {"a"}
    assert free["a"] is system.build_context.variables["formula"]


def test_promoted_theorem_checks_at_compound_and_rejects_non_instance():
    system = compiled(HILBERT)
    proof = system.parse(SELF_IMPLICATION_PROOF)
    rule = promote_proved_leaf(system, proof, generalise="a", sort_name="formula").as_rule()
    context = copy(system.context)

    good = system.parse("((y → y) → (y → y)) [I]").proof_lines[0]
    assert rule.check([], [], good, context) is True

    bad = system.parse("(a → b) [I]").proof_lines[0]
    assert rule.check([], [], bad, context) is False


# ---------------------------------------------------------------------------
# 2. The wired citation path: cite a promoted theorem with no shim.
# ---------------------------------------------------------------------------
def test_zero_premise_theorem_is_citable_without_registering_a_rule():
    system = compiled(HILBERT)
    proof = system.parse(SELF_IMPLICATION_PROOF)
    system.promote(promote_proved_leaf(system, proof, generalise="a", sort_name="formula"))

    # The case impossible today via citation: reuse `(a -> a)` at the compound
    # `(y -> y)` — now resolved through the ordinary parse/cite pipeline.
    cited = system.parse("((y → y) → (y → y)) [I]")
    assert cited.valid is True

    # And it is *not* among the system's primitive rules.
    assert all(rule.label != "I" for rule in system.inference_rules)
    assert "I" in system.promoted_theorems


def test_promoted_theorem_with_a_premise_is_cited_like_a_rule():
    # `w`: from `p` derive `(q -> p)` (weakening; provable via K + MP). Promoted
    # from its schematic statement and cited `[w, <premise line>]`.
    system = compiled(HILBERT)
    system.promote(
        promote_from_source(
            system, "w", "(q → p)", {"p": "formula", "q": "formula"}, premises=("p",)
        )
    )

    proof = system.parse(
        "(a → (b → a)) [K]\n"                 # a valid premise line, p := (a -> (b -> a))
        "(c → (a → (b → a))) [w, 1]"          # conclude (q -> p) with q := c
    )
    assert proof.valid is True
    assert proof.proof_lines[1].valid is True


# ---------------------------------------------------------------------------
# 3. Soundness under binders: $d -> disjoint blocks the capturing instance.
# ---------------------------------------------------------------------------
def test_distinct_variable_proviso_is_carried_and_enforced():
    system = compiled(AX_FIVE_SYSTEM)
    # ax-5:  |- ( phi -> A.x phi )   with   $d x phi
    system.promote(
        promote_from_source(
            system,
            "AX5",
            "(phi → ∀x phi)",
            {"phi": "formula", "x": "setvar"},
            distinct=("disjoint(x, phi, setvar)",),
        )
    )

    # Good: x does not occur in phi := (y ∈ y). The disjoint proviso holds.
    good = system.parse("(y ∈ y → ∀x y ∈ y) [AX5]")
    assert good.valid is True

    # Bad: phi := (x ∈ y) captures the bound x. Without the proviso this would
    # derive the false `(x ∈ y -> A.x x ∈ y)`; disjoint(x, phi) rejects it.
    bad = system.parse("(x ∈ y → ∀x x ∈ y) [AX5]")
    assert bad.valid is False

    # Control: the *same* statement promoted with no $d accepts the capturing
    # instance — confirming it is the disjoint proviso doing the rejecting above,
    # not a structural accident, and that dropping $d is genuinely unsound.
    system.promote(
        promote_from_source(system, "AX5NODV", "(phi → ∀x phi)", {"phi": "formula", "x": "setvar"})
    )
    unsound = system.parse("(x ∈ y → ∀x x ∈ y) [AX5NODV]")
    assert unsound.valid is True
