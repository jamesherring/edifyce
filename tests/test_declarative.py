"""Tests for the declarative front-end (website.logical.declarative).

These exercise the lowering all the way through the *real* compiler and proof
checker: grammar parsing, order-independence (the fix for the engine's silent
forward-declaration trap), and -- the headline requirement -- definitions that
remain first-class from the grammar down into inference checking.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build, parse, lower


# A compact but genuine fragment of ZFC: a first-order grammar over ∈/=, a
# logical line, an axiom, modus ponens + hypothesis, and layered definitions.
ZFC = """system ZFC

notation
  brackets ( )

grammar
  term      | variable      | matches [a-z][a-z0-9]*
  formula   | membership    | s ∈ t                   | s, t : term
  formula   | equality      | s = t                   | s, t : term
  formula   | negation      | ¬p                      | p : formula
  formula   | conjunction   | (p ∧ q)                 | p, q : formula
  formula   | disjunction   | (p ∨ q)                 | p, q : formula
  formula   | implication   | (p → q)                 | p, q : formula
  formula   | biconditional | (p ↔ q)                 | p, q : formula
  formula   | universal     | ∀x p                    | x : variable, p : formula
  formula   | existential   | ∃x p                    | x : variable, p : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

axioms
  EXT | extensionality | ∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)

rules
  HYP | hypothesis   | from             | infer p | p : formula
  MP  | modus ponens | from p ; (p → q) | infer q | p, q : formula

definitions
  formula | subset   | x ⊆ y | means ∀z (z ∈ x → z ∈ y) | x, y, z : variable
  formula | superset | x ⊇ y | means y ⊆ x              | x, y : variable
"""


@pytest.fixture(scope="module")
def zfc():
    result = build(ZFC)
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
# in any order.
# ---------------------------------------------------------------------------


def test_productions_may_be_written_in_any_order():
    scrambled = """system Scrambled

grammar
  formula | conjunction | (p ∧ q) | p, q : formula
  formula | membership  | s ∈ t   | s, t : term
  formula | universal   | ∀x p    | x : variable, p : formula
  term    | variable    | matches [a-z]+
"""
    system = build(scrambled)["system"]
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
# A couple of parser-level checks
# ---------------------------------------------------------------------------


def test_bindings_parse_mixed_sorts():
    spec = parse(
        "system S\n\ngrammar\n  formula | u | ∀x p | x : variable, p : formula\n"
    )
    assert spec.productions[0].bindings == [("x", "variable"), ("p", "formula")]


def test_unknown_section_is_an_error():
    result = build("system S\n\nwibble\n  nonsense\n")
    assert "errors" in result
    assert "wibble" in result["errors"][0]


def test_lowering_forward_declares_before_use():
    # The empty union declaration must precede the Pattern that references it.
    spec = parse(ZFC)
    edi = lower(spec)
    assert edi.index("UnionPattern formula:") < edi.index("with p as formula")


def test_declarative_proviso_lowers_to_a_where_clause():
    # A definition's proviso column lowers to a `Define ... where ...` clause -
    # the structural kernel proviso - not the retired pseudo-python `if`.
    lines = [
        line + " | where disjoint(x, y, variable)" if "superset" in line else line
        for line in ZFC.split("\n")
    ]
    spec = parse("\n".join(lines))
    edi = lower(spec)
    assert "where disjoint(x, y, variable)" in edi
    assert " ⊆ x if " not in edi  # not lowered as the legacy `if` proviso


def test_declarative_legacy_if_column_is_rejected():
    # The retired `if` proviso is refused at parse time (not silently dropped),
    # mirroring the engine's compile-time rejection.
    from website.logical.declarative import DeclarativeError

    lines = [
        line + " | if disjoint(x, y, variable)" if "superset" in line else line
        for line in ZFC.split("\n")
    ]
    with pytest.raises(DeclarativeError):
        parse("\n".join(lines))


# ---------------------------------------------------------------------------
# Rule side-conditions: a dedicated `side_conditions` section attaches soundness
# provisos to a rule by its label, mirroring the engine's per-rule block.
# ---------------------------------------------------------------------------


# A tiny propositional system whose two custom rules are *only* sound because of
# their provisos: RImp derives (p → q) but only when p and q are the same
# formula; NOcc only when p does not occur in q.
GATED = """system Gated

notation
  brackets ( )

grammar
  atom    | prop        | matches [a-z]
  formula | atomic      | a       | a : atom
  formula | implication | (p → q) | p, q : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

rules
  HYP  | hypothesis | from      | infer p       | p : formula
  RImp | refl imp   | from      | infer (p → q) | p, q : formula
  NOcc | non occur  | from      | infer (p → q) | p, q : formula

side_conditions
  RImp | equal(p, q)
  NOcc | not occurs(p, q)
"""


def test_side_conditions_section_attaches_provisos_to_rules():
    spec = parse(GATED)
    by_label = {rule.label: rule for rule in spec.rules}
    assert by_label["RImp"].side_conditions == ["equal(p, q)"]
    assert by_label["NOcc"].side_conditions == ["not occurs(p, q)"]
    # A rule with no proviso row keeps an empty list.
    assert by_label["HYP"].side_conditions == []


def test_side_conditions_section_lowers_to_a_rule_block():
    edi = lower(parse(GATED))
    assert "side_conditions:" in edi
    assert "equal(p, q)" in edi
    assert "not occurs(p, q)" in edi


def test_side_conditions_gate_the_rule_during_checking():
    # The payoff: the lowered-and-compiled system enforces the provisos.
    system = build(GATED)["system"]
    # RImp requires p == q.
    assert system.parse("(a → a) [RImp]").valid is True
    assert system.parse("(a → b) [RImp]").valid is False
    # NOcc requires p not to occur in q.
    assert system.parse("(a → (c → b)) [NOcc]").valid is True
    assert system.parse("(a → (a → b)) [NOcc]").valid is False


def test_side_conditions_referencing_an_unknown_rule_is_an_error():
    from website.logical.declarative import DeclarativeError

    with pytest.raises(DeclarativeError):
        parse(GATED.replace("  RImp | equal(p, q)", "  Bogus | equal(p, q)"))


# ---------------------------------------------------------------------------
# Escaped pipes in fields (regex alternation, pipe notation)
# ---------------------------------------------------------------------------


def test_escaped_pipe_in_regex_is_not_a_column_separator():
    # A regex alternation must survive: '\|' is a literal pipe, not a column.
    system = build(
        "system S\n\ngrammar\n  token | ident | matches [a-z]+\\|[A-Z]+\n"
    )["system"]
    ident = system.context.variables["ident"]
    assert ident.match("abc", system.context) is not None
    assert ident.match("XYZ", system.context) is not None
    # A regex backslash class like \d is untouched by the escape handling.
    assert parse("system S\n\ngrammar\n  t | n | matches \\d+\n").productions[0].regex == "\\d+"


def test_escaped_pipe_in_template_is_preserved():
    spec = parse(
        "system S\n\ngrammar\n  set | builder | { x \\| p } | x : term, p : formula\n"
    )
    prod = spec.productions[0]
    assert prod.template == "{ x | p }"
    assert prod.bindings == [("x", "term"), ("p", "formula")]


# ---------------------------------------------------------------------------
# build_spec surfaces lowering failures as errors, not exceptions
# ---------------------------------------------------------------------------


def test_build_spec_returns_errors_for_invalid_shape():
    # A line shape with no grammar-sort placeholder fails during lowering; the
    # build contract requires errors, not a raised exception.
    from website.logical.declarative import build_spec

    spec = parse(
        "system S\n\ngrammar\n  formula | atom | a\n\n"
        "line statement\n  shape <reference>\n  reference | matches [A-Z]+\n"
    )
    result = build_spec(spec)
    assert "errors" in result
    assert result["errors"]
