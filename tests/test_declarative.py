"""Tests for the declarative spec→system pipeline (website.logical.declarative).

Formal systems are assembled directly as :class:`SystemSpec` objects (the
scripted-assembly path) and driven through the *real* compiler and proof
checker: grammar parsing, order-independence (the fix for the engine's silent
forward-declaration trap), and -- the headline requirement -- definitions that
remain first-class from the grammar down into inference checking.
"""

import pytest

pytest.importorskip("regex")

from tests.spec_helpers import (
    axiom,
    biconditional_prod,
    brackets,
    conjunction_prod,
    defn,
    disjunction_prod,
    equality_prod,
    existential_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    negation_prod,
    regex_prod,
    rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import (
    DeclarativeError,
    LineSpec,
    SystemSpec,
    build_spec,
    lower,
)


def superset_def():
    return defn("formula", "superset", "x ⊇ y", "y ⊆ x",
                [("x", "variable"), ("y", "variable")])


def zfc_spec() -> SystemSpec:
    # A compact but genuine fragment of ZFC: a first-order grammar over ∈/=, a
    # logical line, an axiom, modus ponens + hypothesis, and layered definitions.
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            conjunction_prod(), disjunction_prod(), implication_prod(),
            biconditional_prod(), universal_prod(), existential_prod(),
        ],
        line=statement_line(),
        axioms=[axiom("EXT", "extensionality", "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[subset_def(), superset_def()],
    )


@pytest.fixture(scope="module")
def zfc():
    result = build_spec(zfc_spec())
    assert "errors" not in result, result.get("errors")
    return result["system"]


# ---------------------------------------------------------------------------
# Compilation and structure
# ---------------------------------------------------------------------------


def test_builds_without_errors(zfc):
    assert zfc.name == "ZFC"
    # EXT is an asserted axiom (a line type), HYP/MP are inference rules.
    assert [ir.label for ir in zfc.inference_rules] == ["HYP", "MP"]
    assert [lt.name for lt in zfc.line_types] == ["statement", "extensionality"]


# ---------------------------------------------------------------------------
# The grammar parses -- including deep nesting and the extensionality axiom
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "x ∈ y",
        "¬x = y",
        "(x ∈ y → y ∈ z)",
        "∀x ∃y (x ∈ y ∧ y ∈ z)",
        "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)",
    ],
)
def test_grammar_parses_formulas(zfc, text):
    formula = zfc.context.variables["formula"]
    assert formula.match(text, zfc.context) is not None


def test_ill_formed_string_does_not_match(zfc):
    formula = zfc.context.variables["formula"]
    assert formula.match("∈ ∈ ∈", zfc.context) is None


# ---------------------------------------------------------------------------
# Order independence -- the fix for the silent forward-declaration trap.
# In the raw .edi language, defining the connectives before grouping them into
# a `formula` union silently matches nothing. Here productions may be written
# in any order and the lowering forward-declares every sort union first.
# ---------------------------------------------------------------------------


def test_productions_may_be_written_in_any_order():
    scrambled = SystemSpec(
        name="Scrambled",
        productions=[
            conjunction_prod(),
            membership_prod(),
            universal_prod(),
            regex_prod("term", "variable", "[a-z]+"),
        ],
    )
    system = build_spec(scrambled)["system"]
    formula = system.context.variables["formula"]
    assert formula.match("∀x (x ∈ y ∧ y ∈ z)", system.context) is not None


# ---------------------------------------------------------------------------
# Definitions are first-class: recognised wherever a formula is expected,
# including nested inside quantifiers and other connectives.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["x ⊆ y", "x ⊇ y", "∀x x ⊆ y", "(x ⊆ y ∧ y ⊆ z)"])
def test_defined_notation_matches_as_formula(zfc, text):
    formula = zfc.context.variables["formula"]
    match = formula.match(text, zfc.context)
    assert match is not None


def test_defined_notation_is_backed_by_a_definition(zfc):
    formula = zfc.context.variables["formula"]
    match = formula.match("x ⊆ y", zfc.context)
    assert match.definition is not None


# ---------------------------------------------------------------------------
# Full proof checking -- axioms, and the same inference machinery over both the
# raw base and layered defined notation.
# ---------------------------------------------------------------------------


def test_axiom_validates_as_a_bare_assertion(zfc):
    # The extensionality axiom is self-justifying: asserting it is valid.
    proof = zfc.parse("∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)")
    assert proof.valid is True


def test_non_axiom_bare_formula_is_unjustified(zfc):
    # A different formula is not the axiom, so a bare assertion is not valid.
    proof = zfc.parse("x = y")
    assert proof.valid is False


def test_modus_ponens_over_raw_base(zfc):
    proof = zfc.parse("x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]")
    assert proof.valid is True
    assert all(line["valid"] for line in proof.data()["lines"])


def test_modus_ponens_over_defined_notation(zfc):
    # The headline: a proof written entirely in defined notation (⊆, ⊇) is
    # checked by the same rule that works over the raw ∈/= base.
    proof = zfc.parse("x ⊆ y [HYP]\n(x ⊆ y → x ⊇ y) [HYP]\nx ⊇ y [MP, 1, 2]")
    assert proof.valid is True
    assert all(line["valid"] for line in proof.data()["lines"])


# ---------------------------------------------------------------------------
# Structured accessors: the formula/reference are declared fields on the line
# type, not interpreted `formula()`/`reference()` accessor functions.
# ---------------------------------------------------------------------------


def test_line_types_declare_formula_and_reference_fields(zfc):
    statement = next(lt for lt in zfc.line_types if lt.name == "statement")
    # The logical line names its formula and citation fields directly...
    assert statement.formula_field == "f"
    assert statement.reference_field == "r"
    # ...and registers no interpreted accessor function on its pattern.
    assert statement.pattern.functions == {}

    # A bare axiom asserts its whole match: `formula: self`.
    extensionality = next(lt for lt in zfc.line_types if lt.name == "extensionality")
    assert extensionality.formula_field == "self"
    assert extensionality.pattern.functions == {}


def test_lowering_emits_field_declarations_not_accessor_functions():
    edi = lower(zfc_spec())
    assert "formula: f" in edi
    assert "reference: r" in edi
    assert "formula: self" in edi
    # The interpreted accessor bodies are gone.
    assert ".formula()" not in edi
    assert ".reference()" not in edi


def test_legacy_formula_accessor_function_still_works():
    # A hand-written system with no declared field falls back to a `formula()`
    # accessor function — the field-less path the engine still supports.
    from website.logical.compiler import compile as compile_edi

    source = (
        "FormalSystem Legacy:\n"
        "\n"
        "    Regex atom:\n"
        "        ^[a-z]+$\n"
        "\n"
        "    ProofContext:\n"
        "        given: MatchSet()\n"
        "\n"
        "    Pattern statement_pattern:\n"
        "        with f as atom:\n"
        "            f\n"
        "\n"
        "    statement_pattern.formula():\n"
        "        return self.f\n"
        "\n"
        "    LineType statement:\n"
        "        pattern: statement_pattern\n"
        "        behaviour: logical\n"
    )
    system = compile_edi(source)["system"]
    statement = system.line_types[0]
    # No declared field; the accessor function carries the contract instead.
    assert statement.formula_field is None
    assert "formula" in statement.pattern.functions
    # And a proof still resolves its formula (here, an unjustified logical line).
    proof = system.parse("hello")
    assert proof.proof_lines[0].formula is not None


# ---------------------------------------------------------------------------
# Lowering: forward-declaration order and definition provisos
# ---------------------------------------------------------------------------


def test_lowering_forward_declares_before_use():
    # The empty union declaration must precede the Pattern that references it.
    edi = lower(zfc_spec())
    assert edi.index("UnionPattern formula:") < edi.index("with p as formula")


def test_definition_proviso_lowers_to_a_where_clause():
    # A definition's `condition` lowers to a `Define ... where ...` clause -
    # the structural kernel proviso.
    spec = zfc_spec()
    next(d for d in spec.definitions if d.name == "superset").condition = (
        "disjoint(x, y, variable)"
    )
    edi = lower(spec)
    assert "where disjoint(x, y, variable)" in edi


# ---------------------------------------------------------------------------
# Rule side-conditions: soundness provisos attached to a rule, lowered into the
# engine's per-rule `side_conditions` block and enforced during checking.
#
# A tiny propositional system whose two custom rules are *only* sound because of
# their provisos: RImp derives (p → q) but only when p and q are the same
# formula; NOcc only when p does not occur in q.
# ---------------------------------------------------------------------------


def gated_spec() -> SystemSpec:
    return SystemSpec(
        name="Gated",
        brackets=brackets(),
        productions=[
            regex_prod("atom", "prop", "[a-z]"),
            template_prod("formula", "atomic", "a", [("a", "atom")]),
            implication_prod(),
        ],
        line=statement_line(),
        rules=[
            hyp_rule(),
            rule("RImp", "refl imp", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["equal(p, q)"]),
            rule("NOcc", "non occur", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["not occurs(p, q)"]),
        ],
    )


def test_side_conditions_lower_to_a_rule_block():
    edi = lower(gated_spec())
    assert "side_conditions:" in edi
    assert "equal(p, q)" in edi
    assert "not occurs(p, q)" in edi


def test_side_conditions_gate_the_rule_during_checking():
    # The payoff: the lowered-and-compiled system enforces the provisos.
    system = build_spec(gated_spec())["system"]
    # RImp requires p == q.
    assert system.parse("(a → a) [RImp]").valid is True
    assert system.parse("(a → b) [RImp]").valid is False
    # NOcc requires p not to occur in q.
    assert system.parse("(a → (c → b)) [NOcc]").valid is True
    assert system.parse("(a → (a → b)) [NOcc]").valid is False


# ---------------------------------------------------------------------------
# build_spec surfaces lowering failures as errors, not exceptions
# ---------------------------------------------------------------------------


def test_build_spec_returns_errors_for_invalid_shape():
    # A line shape with no grammar-sort placeholder fails during lowering; the
    # build contract requires errors, not a raised exception.
    spec = SystemSpec(
        name="S",
        productions=[template_prod("formula", "atom", "a")],
        line=LineSpec(name="statement", shape="<reference>", parts=[],
                      logical_sort=None),
    )
    result = build_spec(spec)
    assert "errors" in result
    assert result["errors"]


def test_lower_raises_declarative_error_on_invalid_shape():
    # `lower` itself raises DeclarativeError (build_spec catches it); the routers
    # depend on that surface for the /source 422 path.
    spec = SystemSpec(
        name="S",
        productions=[template_prod("formula", "atom", "a")],
        line=LineSpec(name="statement", shape="assertion", parts=[],
                      logical_sort="formula"),
    )
    with pytest.raises(DeclarativeError):
        lower(spec)
