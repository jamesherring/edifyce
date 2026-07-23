import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system


def compiled(code):
    result = compile_formal_system(code)
    assert "errors" not in result, result.get("errors")
    return result["system"]


# A system with plain (behaviour: none) statements and an indent block.
SIMPLE_SYSTEM = """FormalSystem Simple:

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

# A full logical system: statements carry a formula and a justification
# reference, HYP introduces a formula from nothing, and REP repeats a
# previously proven formula.
LOGICAL_SYSTEM = """FormalSystem Logic:

    Regex formula:
        ^[a-z]+$

    Regex reference:
        ^[A-Za-z ]+$

    ProofContext:
        given: MatchSet()

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    LineType statement:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r

    with s as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                s

        InferenceRule repetition:
            label:
                REP
            antecedents:
                s
            deduction:
                s
"""


# A propositional system with a compound production (p -> q). MP has a named
# metavariable shared across its antecedents and conclusion; PAIR uses the bare
# sort `formula` twice, so its two premises are independent "any formula" slots.
PROP_LOGIC_SYSTEM = """FormalSystem PropLogic:

    Regex atom:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z 0-9,]+$

    ProofContext:
        given: MatchSet()

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    formula:
        implication

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    LineType statement:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r

    with p as formula, q as formula:
        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                p

        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p -> q)
            deduction:
                q

        InferenceRule reflexive:
            label:
                RImp
            deduction:
                (p -> q)
            side_conditions:
                equal(p, q)

        InferenceRule non_occurring:
            label:
                NOcc
            deduction:
                (p -> q)
            side_conditions:
                not occurs(p, q)

    InferenceRule pair:
        label:
            PAIR
        antecedents:
            formula
            formula
        deduction:
            formula
"""


@pytest.fixture(scope="module")
def simple_system():
    return compiled(SIMPLE_SYSTEM)


@pytest.fixture(scope="module")
def logical_system():
    return compiled(LOGICAL_SYSTEM)


@pytest.fixture(scope="module")
def prop_logic_system():
    return compiled(PROP_LOGIC_SYSTEM)


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


def test_indent_block_parses_nested_lines(simple_system):
    proof = simple_system.parse("if abc:\n    abc")
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
    # The statement pattern has no formula() function, so logical lines
    # cannot be checked.
    system = compiled(
        """FormalSystem NoFormula:

    Regex word:
        ^[a-z]+$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: word
        behaviour: logical
"""
    )

    proof = system.parse("abc")
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
