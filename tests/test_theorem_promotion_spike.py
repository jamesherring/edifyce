"""Spike: promote a *proved theorem* to a reusable schematic rule at the
**kernel-graph** level, and check a fresh instance through the real checker.

Context. Today a proved theorem is a concrete line: after proving ``(a → a)`` in
a Hilbert system there is no way to reuse it to obtain ``((y → y) → (y → y))`` —
the only route is to re-derive it from the axiom schemes at ``(y → y)``. Making
theorem-as-template reuse work is the "A1" bridge discussed in
``docs/setmm-import-recommendations-detail.md``.

The question this spike answers: does the bridge need the string-layer
``Match.create_pattern`` round-trip, or can promotion happen purely as a graph
operation on kernel terms — which is the level the checker already unifies at?

What it demonstrates, using only existing engine machinery:

1. Take the proved conclusion ``(a → a)`` and project it to a **ground kernel
   term** with :func:`from_match` — ``Node(→, {p: atom a, q: atom a})``.
2. **Generalise on the graph** with :func:`_revariabilise` (the same helper the
   compiler uses to re-mark schema metavariables): rewrite the ``a`` leaves to
   ``Var("a", formula)``, widening the sort to *formula* so the variable may bind
   a compound. No serialisation, no ``create_pattern``, no collision repair.
3. Hang that term on a thin ``StringPattern`` shell as its ``schema_term`` and
   build an **ephemeral** ``InferenceRule`` — never registered in the system.
4. Check ``((y → y) → (y → y))`` through the real ``InferenceRule.check`` →
   ``_term_binding`` → ``match_all`` path. It passes; the mismatched ``(a → b)``
   is rejected because the shared ``Var("a")`` cannot bind two different subterms.

If this holds, the A1 promotion is a term-graph rewrite feeding the existing
unifier, and ``create_pattern``/``AbstractPattern`` (string-layer tools) are not
on the critical path.
"""

from __future__ import annotations

from copy import copy

import pytest

pytest.importorskip("regex")

from tests.test_engine_neutrality import HILBERT
from website.logical.compiler import compile as compile_formal_system
from website.logical.compiler import _revariabilise
from website.logical.formal_system.rules import InferenceRule
from website.logical.kernel.terms import Var, from_match
from website.logical.matching.patterns import StringPattern


# The classic S/K/MP derivation of `a -> a`, with no assumptions (from
# test_engine_neutrality). Its last line is the proved theorem we promote.
SELF_IMPLICATION_PROOF = (
    "((a → ((a → a) → a)) → ((a → (a → a)) → (a → a))) [S]\n"
    "(a → ((a → a) → a)) [K]\n"
    "((a → (a → a)) → (a → a)) [MP, 1, 2]\n"
    "(a → (a → a)) [K]\n"
    "(a → a) [MP, 3, 4]"
)


@pytest.fixture(scope="module")
def hilbert():
    result = compile_formal_system(HILBERT)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def _promote_last_line(system, proof, generalise: str):
    """Build an ephemeral zero-premise rule from a proved line, purely on the
    graph: ``from_match`` to a ground term, ``_revariabilise`` the named leaf to
    a ``formula``-sorted ``Var``, and hang the term on a schema shell.
    """
    context = copy(system.context)

    concluded = proof.proof_lines[-1]
    ground_term = from_match(concluded.formula, context)

    # Widen the generalised leaf to the *formula* sort so it can bind a compound
    # (a wff metavariable), not just an atom. This is the sort a `$f wff a`
    # floating hypothesis would declare on import.
    formula_sort = system.build_context.variables["formula"]
    schema_term = _revariabilise(ground_term, {generalise: formula_sort})

    # A thin schema shell: its `schema_term` is what `_schema_term` returns, so
    # the checker never re-parses a string here. The `pattern` text is inert.
    deduction = StringPattern(name="self_imp", pattern="self_imp")
    deduction.schema_term = schema_term

    rule = InferenceRule(
        name="self_imp",
        label="I",
        antecedents=[],
        deduction=deduction,
        variables={generalise: formula_sort},
        matching="structural",
    )
    return rule, schema_term, context


def _parsed_line(system, formula_with_ref):
    """Parse one claim line and return its ProofLine (its `.formula` Match is set
    during parsing regardless of whether its own justification resolves)."""
    proof = system.parse(formula_with_ref)
    return proof.proof_lines[0]


def test_promotion_is_a_graph_generalisation(hilbert):
    # The proved theorem really is concrete first...
    proof = hilbert.parse(SELF_IMPLICATION_PROOF)
    assert proof.valid is True
    ground = from_match(proof.proof_lines[-1].formula, copy(hilbert.context))
    assert ground.free_vars() == {}, "proved conclusion starts fully ground"

    # ...and promotion turns exactly the named leaf into a schematic Var, on the
    # graph, with the widened `formula` sort.
    _rule, schema_term, _ctx = _promote_last_line(hilbert, proof, generalise="a")
    free = schema_term.free_vars()
    assert set(free) == {"a"}
    assert free["a"] is hilbert.build_context.variables["formula"]


def test_promoted_theorem_instantiates_at_a_compound_formula(hilbert):
    # This is the case that is impossible today via citation: reuse `(a -> a)` at
    # the *compound* formula `(y -> y)` to get `((y -> y) -> (y -> y))`.
    proof = hilbert.parse(SELF_IMPLICATION_PROOF)
    rule, _schema, context = _promote_last_line(hilbert, proof, generalise="a")

    goal = _parsed_line(hilbert, "((y → y) → (y → y)) [I]")
    assert rule.check([], [], goal, context) is True

    # And it instantiates at an atom too.
    goal_atom = _parsed_line(hilbert, "(z → z) [I]")
    assert rule.check([], [], goal_atom, context) is True


def test_promoted_theorem_rejects_a_non_instance(hilbert):
    # `(a -> b)` is not an instance of the scheme `(p -> p)`: the shared Var("a")
    # cannot bind both `a` and `b`, so unification fails and the step is rejected.
    proof = hilbert.parse(SELF_IMPLICATION_PROOF)
    rule, _schema, context = _promote_last_line(hilbert, proof, generalise="a")

    bad = _parsed_line(hilbert, "(a → b) [I]")
    assert rule.check([], [], bad, context) is False


def test_ephemeral_rule_is_a_drop_in_on_the_citation_path(hilbert):
    # The runtime-built rule is a valid drop-in: appended to the rule list only
    # to exercise the ordinary parse/cite pipeline, it validates the instance
    # end-to-end. (Registration here is just to reach the citation path; the
    # object was built from the proved theorem at runtime, not authored in source
    # — the A1 point is that per-theorem rules need not be *persisted*.)
    proof = hilbert.parse(SELF_IMPLICATION_PROOF)
    rule, _schema, _context = _promote_last_line(hilbert, proof, generalise="a")

    hilbert.inference_rules.append(rule)
    try:
        cited = hilbert.parse("((y → y) → (y → y)) [I]")
        assert cited.valid is True
    finally:
        hilbert.inference_rules.remove(rule)
