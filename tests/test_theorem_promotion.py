"""Promoting a proved/imported theorem to a reusable schematic rule.

This exercises the "A1" bridge from ``docs/metamath-import-roadmap.md``:
a proved theorem should be reusable like an inference rule — its metavariables
re-instantiated at each citation by unification, subject to its distinct-variable
provisos — *without* being minted as a persisted rule per theorem.

The tests cover three things:

1. **Mechanism (graph, not string).** Promotion is a kernel-term operation:
   ``from_match`` the proved conclusion to a ground term, ``revariabilise`` the
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

4. **The ``promote_from_source`` API** — what it builds, and what it rejects.

5. **Matching regime.** A theorem promoted from a string-rewriting (semi-Thue)
   system stays string-checked, so associative rewrites survive promotion.

6. **Closed (ground) theorems.** A statement with no metavariables — Metamath's
   ``2re`` (``|- 2 e. RR``) — justifies exactly itself and nothing else.
"""

from __future__ import annotations

from copy import copy

import pytest

pytest.importorskip("regex")

from tests.miu_system import miu_spec
from tests.spec_helpers import (
    atom_const_prod,
    brackets,
    regex_prod,
    template_prod,
)
from tests.test_definitional_step_proofs import alias_spec
from tests.test_engine_neutrality import HILBERT
from website.logical.build_context import revariabilise
from website.logical.promotion import promote_from_source
from website.logical.declarative import LinePart, LineSpec, SystemSpec, build_system
from website.logical.formal_system.promotion import PromotedTheorem
from website.logical.kernel.terms import from_match
from website.logical.matching.patterns import StringPattern


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
def ax_five_spec() -> SystemSpec:
    return SystemSpec(
        name="AxFive",
        brackets=brackets(),
        productions=[
            # The leaf's member name must differ from its sort name, else step 4
            # of build_system appends the sort union to itself (see spec_helpers).
            regex_prod("setvar", "var", "[a-z][a-z0-9]*"),
            template_prod("formula", "membership", "x ∈ y",
                          [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)",
                          [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "universal", "∀x p",
                          [("x", "setvar"), ("p", "formula")]),
        ],
        lines=[claim_line()],
    )


def claim_line() -> LineSpec:
    return LineSpec(
        name="claim",
        shape="<formula> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9, ]+")],
        logical_sort="formula",
    )


# A constants-only fragment for closed (ground) theorems: numerals and
# collections as atoms, so a statement like `2 ∈ ℝ` has no metavariables at all.
def closed_spec(leading_productions=()) -> SystemSpec:
    # `leading_productions` go in front of the logical sort's own, for the test
    # that a broad unrelated sort declared first must not capture the parse.
    return SystemSpec(
        name="Closed",
        productions=[
            *leading_productions,
            atom_const_prod("num", "two", "2"),
            atom_const_prod("num", "three", "3"),
            atom_const_prod("coll", "reals", "ℝ"),
            atom_const_prod("coll", "nats", "ℕ"),
            template_prod("formula", "membership", "n ∈ c",
                          [("n", "num"), ("c", "coll")]),
        ],
        lines=[claim_line()],
    )


# ---------------------------------------------------------------------------
# Promotion helpers — the two routes an importer would use.
# ---------------------------------------------------------------------------
def promote_proved_leaf(system, proof, generalise: str, sort_name: str) -> PromotedTheorem:
    """Graph route: build a zero-premise theorem from a *proved* line by
    generalising a named leaf to a sort-widened Var. No string round-trip."""
    context = copy(system.context)
    ground_term = from_match(proof.proof_lines[-1].formula, context)

    sort = system.build_context.variables[sort_name]
    schema_term = revariabilise(ground_term, {generalise: sort})

    deduction = StringPattern(name=generalise, pattern=generalise)
    deduction.schema_term = schema_term
    return PromotedTheorem(label="I", deduction=deduction, variables={generalise: sort})


# `promote_from_source` (the import-facing route: schematic statement + premises +
# $d, handling formula metavariables over compounds) now lives in the engine
# (website.logical.promotion) and is exercised by the citation and $d tests below,
# plus its own error-handling tests.


# ---------------------------------------------------------------------------
# 1. Mechanism: promotion is a graph generalisation; the ephemeral rule checks.
# ---------------------------------------------------------------------------
def test_promotion_is_a_graph_generalisation():
    system = build_system(HILBERT)
    proof = system.parse(SELF_IMPLICATION_PROOF)
    assert proof.valid is True

    ground = from_match(proof.proof_lines[-1].formula, copy(system.context))
    assert ground.free_vars() == {}, "proved conclusion starts fully ground"

    theorem = promote_proved_leaf(system, proof, generalise="a", sort_name="formula")
    free = theorem.deduction.schema_term.free_vars()
    assert set(free) == {"a"}
    assert free["a"] is system.build_context.variables["formula"]


def test_promoted_theorem_checks_at_compound_and_rejects_non_instance():
    system = build_system(HILBERT)
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
    system = build_system(HILBERT)
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
    system = build_system(HILBERT)
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
    system = build_system(ax_five_spec())
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


# ---------------------------------------------------------------------------
# 4. The engine-level promote_from_source API: what it builds and what it rejects.
# ---------------------------------------------------------------------------
def test_promote_from_source_builds_the_expected_schema():
    system = build_system(HILBERT)
    theorem = promote_from_source(system, "I", "(p → p)", {"p": "formula"})

    # A formula metavariable, schematic, at the widened sort.
    free = theorem.deduction.schema_term.free_vars()
    assert set(free) == {"p"}
    assert free["p"] is system.build_context.variables["formula"]

    # ...and it is citable at a compound once registered.
    system.promote(theorem)
    assert system.parse("((a → b) → (a → b)) [I]").valid is True


def test_promote_from_source_rejects_an_unknown_sort():
    system = build_system(HILBERT)
    with pytest.raises(ValueError, match="not a declared pattern"):
        promote_from_source(system, "T", "(p → p)", {"p": "nonsense"})


def test_promote_from_source_rejects_an_unparseable_ground_statement():
    # A ground statement is composed explicitly, so one the grammar cannot parse
    # is a genuine error rather than a silently dead theorem. `∧` is not in
    # HILBERT's grammar.
    system = build_system(HILBERT)
    with pytest.raises(ValueError, match="does not parse"):
        promote_from_source(system, "T", "(a ∧ a)", {})


def test_promote_from_source_accepts_defined_notation():
    # A statement in *defined* notation composes no schema term (definitions are
    # excluded from schema composition) but, having metavariables, still projects
    # structurally and applies — so it must be accepted, not mistaken for garbage.
    # `sub` is the alias `x sub y := (x ∈ y)` from alias_spec().
    system = build_system(alias_spec())
    system.promote(
        promote_from_source(system, "T", "x sub y", {"x": "setvar", "y": "setvar"})
    )
    assert system.parse("a sub b [T]").valid is True


# ---------------------------------------------------------------------------
# 5. A theorem promoted from a string-rewriting (semi-Thue) system stays
#    string-checked, so associative rewrites remain applicable after promotion.
# ---------------------------------------------------------------------------
def test_promoted_theorem_keeps_string_matching():
    system = build_system(miu_spec())
    # MIU's doubling step `Mx -> Mxx`, promoted as a string-checked theorem.
    system.promote(
        promote_from_source(system, "DBL", "Mxx", {"x": "miustr"}, premises=("Mx",), matching="string")
    )
    # From the axiom MI, cite it to double: MI -> MII. This needs associative
    # (string) matching — x binds to "I" and is concatenated with itself, which
    # term unification cannot express.
    assert system.parse("MI\nMII [DBL, 1]").valid is True

    # Control: promoted with the default structural matching, the same rewrite is
    # rejected — confirming the matching mode is what carries it through promotion.
    system.promote(
        promote_from_source(system, "DBLS", "Mxx", {"x": "miustr"}, premises=("Mx",))
    )
    assert system.parse("MI\nMII [DBLS, 1]").proof_lines[1].valid is False


# ---------------------------------------------------------------------------
# 6. Closed (ground) theorems: no metavariables to instantiate, so the statement
#    justifies exactly itself. Metamath's `2re` (|- 2 e. RR) is the shape.
# ---------------------------------------------------------------------------
def test_closed_theorem_justifies_exactly_its_own_statement():
    system = build_system(closed_spec())
    system.promote(promote_from_source(system, "2re", "2 ∈ ℝ", {}))

    # The statement itself checks...
    assert system.parse("2 ∈ ℝ [2re]").valid is True

    # ...and nothing else does: a closed theorem is not a schema, so neither a
    # different numeral nor a different collection may be substituted in.
    assert system.parse("3 ∈ ℝ [2re]").proof_lines[0].valid is False
    assert system.parse("2 ∈ ℕ [2re]").proof_lines[0].valid is False


def test_closed_theorem_in_defined_notation():
    # The ground parse uses the system's *resolved* definitions (which live on the
    # built system's proof context, not the build context), so a closed statement
    # written in defined notation composes. Metamath's closed theorems are stated
    # over defined symbols, so this is the shape that matters for an import.
    system = build_system(alias_spec())
    system.promote(promote_from_source(system, "G", "a sub b", {}))
    assert system.parse("a sub b [G]").valid is True


def test_closed_theorem_at_a_non_union_logical_sort():
    # A system whose logical sort is a bare regex (no union wrapper) parses lines
    # fine, so promoting a ground statement must compose there too rather than
    # claiming the grammar cannot parse it.
    system = build_system(miu_spec())
    system.promote(promote_from_source(system, "T", "MII", {}))
    assert system.parse("MII [T]").valid is True


def test_ground_statement_is_not_composed_for_string_matching():
    # The string checker matches surface strings and never reads `schema_term`, so
    # a string-matched theorem must not be put through ground composition (nor
    # rejected when nothing composes).
    system = build_system(miu_spec())
    system.promote(promote_from_source(system, "TS", "MII", {}, matching="string"))
    assert system.parse("MII [TS]").valid is True


def test_ground_composition_uses_the_logical_sort_not_the_first_match():
    # A broad unrelated sort declared *before* the logical one must not capture the
    # parse: composing at it would build a term no proof line is ever read at,
    # yielding a theorem that silently never applies.
    system = build_system(
        closed_spec(leading_productions=[regex_prod("raw", "rawtext", "[0-9∈ℝℕ ]+")])
    )
    system.promote(promote_from_source(system, "2re", "2 ∈ ℝ", {}))
    assert system.parse("2 ∈ ℝ [2re]").valid is True


def test_closed_statement_is_usable_as_a_premise():
    # A ground *premise* composes the same way, so a mixed theorem — ground
    # premise, ground conclusion — is citable with the premise line.
    system = build_system(closed_spec())
    system.promote(
        promote_from_source(system, "up", "2 ∈ ℝ", {}, premises=("2 ∈ ℕ",))
    )
    system.promote(promote_from_source(system, "2nn", "2 ∈ ℕ", {}))

    proof = system.parse("2 ∈ ℕ [2nn]\n2 ∈ ℝ [up, 1]")
    assert proof.valid is True
