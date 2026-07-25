"""Engine-level tests for proof parsing, line types, inference, and numbering.

Systems are assembled declaratively (`SystemSpec` + `build_system`) — the build
path the database and API use — apart from the two `.edi` fixtures below, which
pin engine behaviours no declarative system can express. Both are annotated with
why; both die with the compiler.
"""

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.declarative import LinePart, LineSpec, SystemSpec, build_system

from tests.spec_helpers import (
    brackets,
    hyp_rule,
    regex_prod,
    rule,
    statement_line,
    template_prod,
)


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


def simple_spec() -> SystemSpec:
    """Prose the checker accepts without justification.

    The `.edi` original used `behaviour: none`; `comment` is the surviving
    unchecked behaviour, and it is what these tests need — a line that parses,
    is recorded, and is never asked to justify itself.
    """
    return SystemSpec(
        name="Simple",
        lines=[
            LineSpec(
                name="statement",
                shape="<text>",
                parts=[LinePart(name="text", regex="[a-z ]+")],
                behaviour="comment",
            )
        ],
    )


def logical_spec() -> SystemSpec:
    """Statements carry a formula and a justification reference.

    HYP introduces a formula from nothing; REP repeats a previously proven one.
    """
    return SystemSpec(
        name="Logic",
        productions=[regex_prod("formula", "word", "[a-z]+")],
        lines=[statement_line()],
        rules=[
            rule("HYP", "hypothesis", (), "s", [("s", "formula")]),
            rule("REP", "repetition", ("s",), "s", [("s", "formula")]),
        ],
    )


def prop_logic_spec() -> SystemSpec:
    """A propositional system with the compound production ``(p -> q)``.

    MP shares the metavariable p across its antecedents and conclusion; PAIR uses
    the bare sort `formula` twice, so its two premises are independent
    "any formula" slots.
    """
    def pq() -> list[tuple[str, str]]:
        # Fresh per call: a spec must never alias a shared mutable list.
        return [("p", "formula"), ("q", "formula")]

    return SystemSpec(
        name="PropLogic",
        brackets=brackets(),
        productions=[
            regex_prod("formula", "atom", "[a-z]"),
            template_prod("formula", "implication", "(p -> q)", pq()),
        ],
        lines=[statement_line()],
        rules=[
            hyp_rule(),
            rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", pq()),
            rule("RImp", "reflexive", (), "(p -> q)", pq(), ["equal(p, q)"]),
            rule("NOcc", "non_occurring", (), "(p -> q)", pq(), ["not occurs(p, q)"]),
            rule("PAIR", "pair", ["formula", "formula"], "formula", ()),
        ],
    )


# The one behaviour left that only `.edi` can author: `indent` block nesting,
# superseded by `LineSpec.scope` and deliberately not offered declaratively (see
# declarative._LINE_BEHAVIOURS). It dies with the compiler.
INDENT_SYSTEM = """FormalSystem Indented:

    Regex word:
        ^[a-z ]+$

    ProofContext:
        given: MatchSet()

    Pattern if_pattern:
        with s as word:
            if s:

    LineType statement:
        pattern: word
        behaviour: none

    LineType if:
        pattern: if_pattern
        behaviour: indent
"""


# Likewise compiler-bound: a *logical* line with no formula field at all.
# `build_system` always projects one, so this guard is unreachable declaratively.
NO_FORMULA_SYSTEM = """FormalSystem NoFormula:

    Regex word:
        ^[a-z]+$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: word
        behaviour: logical
"""


@pytest.fixture(scope="module")
def simple_system():
    return build_system(simple_spec())


@pytest.fixture(scope="module")
def logical_system():
    return build_system(logical_spec())


@pytest.fixture(scope="module")
def prop_logic_system():
    return build_system(prop_logic_spec())


# ---------------------------------------------------------------------------
# Parsing proofs with non-logical line types
# ---------------------------------------------------------------------------


def test_valid_single_line_proof(simple_system):
    proof = simple_system.parse("hello world")
    assert proof.valid is True
    assert proof.indicator() == "ok"

    data = proof.data()
    assert len(data["lines"]) == 1
    line = data["lines"][0]
    assert line["valid"] is True
    assert line["name"] == "statement"
    assert line["display"] == "hello world"


def test_unparseable_line_is_invalid_not_raised(simple_system):
    proof = simple_system.parse("NOT VALID 123")
    assert proof.valid is False
    assert proof.indicator() == "error"

    line = proof.data()["lines"][0]
    assert line["valid"] is False
    assert line["invalid_message"] == "Could not parse line."


def test_blank_lines_are_ignored(simple_system):
    proof = simple_system.parse("hello\n\nworld")
    assert proof.valid is True
    displays = [l["display"] for l in proof.data()["lines"] if l["display"]]
    assert displays == ["hello", "world"]


def test_indent_block_parses_nested_lines():
    proof = compiled(INDENT_SYSTEM).parse("if abc:\n    abc")
    lines = proof.data()["lines"]
    assert [l["display"] for l in lines] == ["if abc:", "abc"]
    assert [l["indent"] for l in lines] == [0, 4]
    assert all(l["valid"] for l in lines)


def test_proof_data_structure(simple_system):
    data = simple_system.parse("hello").data()
    assert set(data) == {"indicator", "lines"}
    assert set(data["lines"][0]) >= {
        "valid",
        "behaviour",
        "name",
        "invalid_message",
        "display",
        "indent",
    }


# ---------------------------------------------------------------------------
# Citation numbering
# ---------------------------------------------------------------------------


def test_blank_lines_carry_no_citation_number(prop_logic_system):
    # Numbers count citable steps, not text lines, so `[MP, 1, 2]` names the two
    # hypotheses however the source is spaced out.
    proof = prop_logic_system.parse(
        "\n"
        "a [HYP]\n"
        "\n"
        "(a -> b) [HYP]\n"
        "\n"
        "b [MP, 1, 2]"
    )
    assert proof.valid is True
    assert [line.number for line in proof.proof_lines] == [None, 1, None, 2, None, 3]


def test_inserting_a_blank_line_does_not_renumber_citations(prop_logic_system):
    # The regression this numbering exists for: pressing Enter above a proof used
    # to shift every citation below it.
    source = "a [HYP]\n(a -> b) [HYP]\nb [MP, 1, 2]"
    assert prop_logic_system.parse(source).valid is True
    assert prop_logic_system.parse("\n" + source).valid is True


def test_unparseable_lines_are_still_numbered(prop_logic_system):
    # A line that matched no type is a step the author is still writing; skipping
    # it would renumber everything below a typo.
    proof = prop_logic_system.parse("a [HYP]\n???\n(a -> b) [HYP]\nb [MP, 1, 3]")
    assert [line.number for line in proof.proof_lines] == [1, 2, 3, 4]
    assert proof.proof_lines[1].valid is False
    assert proof.proof_lines[3].valid is True


def test_citation_number_reaches_the_data_payload(prop_logic_system):
    lines = prop_logic_system.parse("\na [HYP]").data()["lines"]
    assert [line["number"] for line in lines] == [None, 1]


# ---------------------------------------------------------------------------
# Logical lines and inference rules
# ---------------------------------------------------------------------------


def test_logical_system_compiles_rules(logical_system):
    assert [rule.label for rule in logical_system.inference_rules] == ["HYP", "REP"]


def test_valid_logical_proof(logical_system):
    proof = logical_system.parse("abc [HYP]\nabc [REP]")
    assert proof.valid is True
    assert proof.indicator() == "ok"
    assert proof.logical_lines() == 2

    lines = proof.data()["lines"]
    assert [l["reference"] for l in lines] == ["HYP", "REP"]
    assert all(l["valid"] for l in lines)


def test_inference_rule_does_not_apply(logical_system):
    # REP repeats an already-proven formula; xyz was never proven.
    proof = logical_system.parse("abc [HYP]\nxyz [REP]")
    assert proof.valid is False

    line = proof.data()["lines"][1]
    assert line["valid"] is False
    assert line["invalid_message"] == "REP does not apply."


def test_rule_with_antecedent_needs_previous_logical_line(logical_system):
    proof = logical_system.parse("abc [REP]")
    assert proof.valid is False

    line = proof.data()["lines"][0]
    assert line["invalid_message"] == "Antecedent lines couldn't be inferred."


def test_unknown_reference_is_invalid(logical_system):
    proof = logical_system.parse("abc [NOPE]")
    assert proof.valid is False

    line = proof.data()["lines"][0]
    assert line["invalid_message"] == "Invalid reference: NOPE"


def test_logical_line_without_formula_is_invalid():
    # The statement pattern declares no formula field, so logical lines cannot
    # be checked.
    proof = compiled(NO_FORMULA_SYSTEM).parse("abc")
    assert proof.valid is False
    line = proof.data()["lines"][0]
    assert line["invalid_message"] == "No formula defined for logical line."


# ---------------------------------------------------------------------------
# Inference over compound terms (the kernel term path)
# ---------------------------------------------------------------------------


def test_modus_ponens_over_compound_terms(prop_logic_system):
    # p is shared: q binds to whatever the implication's consequent is, here a
    # nested (b -> c).
    proof = prop_logic_system.parse(
        "a [HYP]\n(a -> (b -> c)) [HYP]\n(b -> c) [MP, 1, 2]"
    )
    assert proof.valid is True
    assert all(l["valid"] for l in proof.data()["lines"])


def test_modus_ponens_rejects_inconsistent_binding(prop_logic_system):
    # The shared metavariable p cannot be both a (antecedent) and c (conclusion).
    proof = prop_logic_system.parse("a [HYP]\n(a -> b) [HYP]\nc [MP, 1, 2]")
    assert proof.valid is False
    assert proof.data()["lines"][2]["invalid_message"] == "MP does not apply."


def test_bare_sort_antecedents_are_independent(prop_logic_system):
    # PAIR's two antecedents are the bare sort `formula`; they must accept two
    # different formulas (an atom and an implication) rather than being forced
    # to be structurally identical.
    proof = prop_logic_system.parse("a [HYP]\n(a -> b) [HYP]\nb [PAIR, 1, 2]")
    assert proof.valid is True
    assert all(l["valid"] for l in proof.data()["lines"])


# ---------------------------------------------------------------------------
# Kernel side-conditions gating a rule (the side_conditions: block)
# ---------------------------------------------------------------------------


def test_equal_side_condition_gates_rule(prop_logic_system):
    # RImp requires equal(p, q): only a reflexive implication qualifies.
    assert prop_logic_system.parse("(a -> a) [RImp]").valid is True
    invalid = prop_logic_system.parse("(a -> b) [RImp]")
    assert invalid.valid is False
    assert invalid.data()["lines"][0]["invalid_message"] == "RImp does not apply."


def test_freshness_side_condition_gates_rule(prop_logic_system):
    # NOcc requires not occurs(p, q): p must not appear inside q.
    assert prop_logic_system.parse("(a -> (c -> b)) [NOcc]").valid is True
    assert prop_logic_system.parse("(a -> (a -> b)) [NOcc]").valid is False
    assert prop_logic_system.parse("(a -> a) [NOcc]").valid is False


# ---------------------------------------------------------------------------
# FormalSystem structure
# ---------------------------------------------------------------------------


def test_line_types_expose_behaviour(logical_system):
    behaviours = {lt.name: lt.behaviour for lt in logical_system.line_types}
    assert behaviours == {"statement": "logical"}


def test_indicator_reflects_validity(simple_system):
    assert simple_system.parse("hello").indicator() == "ok"
    assert simple_system.parse("BAD 1").indicator() == "error"
