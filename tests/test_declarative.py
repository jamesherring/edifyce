"""Tests for the declarative spec→system pipeline (website.logical.declarative).

Formal systems are assembled directly as :class:`SystemSpec` objects (the
scripted-assembly path) and driven through the *real* builder (``build_system``)
and proof checker: grammar parsing, order-independence (the fix for the engine's
silent forward-declaration trap), and -- the headline requirement -- definitions
that remain first-class from the grammar down into inference checking.
"""

import ast
from pathlib import Path

import pytest

pytest.importorskip("regex")

from tests.spec_helpers import (
    assumption_line,
    atom_const_prod,
    atom_family_prod,
    axiom,
    biconditional_prod,
    brackets,
    conjunction_prod,
    comment_line,
    cp_rule,
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
    reiteration_rule,
    rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import (
    DeclarativeError,
    LinePart,
    LineSpec,
    Rule,
    Subproof,
    SystemSpec,
    build_spec,
    build_system,
    registered_definition_layering,
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
        lines=[statement_line()],
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
# Positional layering: a definition builds on the ones before it, so ordering
# matters. `registered_definition_layering` reports, per position, which survive
# -- the basis for rejecting a reorder that would silently un-layer a definition.
# `x ⊇ y ≝ y ⊆ x` builds on `x ⊆ y`, so it registers only when subset precedes it.
# ---------------------------------------------------------------------------


def _layered_spec(definitions):
    return SystemSpec(
        name="Layered",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            conjunction_prod(), implication_prod(), universal_prod(),
        ],
        lines=[statement_line()],
        definitions=definitions,
    )


def test_layered_definitions_register_when_ordered_dependency_first():
    layering = registered_definition_layering(_layered_spec([subset_def(), superset_def()]))
    assert layering == [True, True]


def test_dependent_definition_silently_drops_when_placed_before_its_dependency():
    # The reversed order does not raise -- superset's defining form `y ⊆ x` just
    # matches nothing without subset ahead of it, so it (position 0) drops.
    layering = registered_definition_layering(_layered_spec([superset_def(), subset_def()]))
    assert layering == [False, True]


def test_layering_is_positional_when_two_definitions_share_a_defined_form():
    # `pos` (higher `x ⊆ y`, lower an atom) and `dep` (SAME higher `x ⊆ y`, lower
    # `y ⊇ x`) both define `x ⊆ y`; `dep` builds on the separate `sup`. Tracking
    # by position — not by defined-form string, which would collapse the two —
    # catches that reordering `dep` ahead of `sup` drops `dep` even though the
    # other `x ⊆ y` keeps the form present.
    pos = defn("formula", "pos", "x ⊆ y", "x ∈ y", [("x", "variable"), ("y", "variable")])
    sup = superset_def()
    dep = defn("formula", "dep", "x ⊆ y", "y ⊇ x", [("x", "variable"), ("y", "variable")])

    assert registered_definition_layering(_layered_spec([pos, sup, dep])) == [True, True, True]
    # `dep` (position 0) now precedes `sup`, so its `y ⊇ x` is unrecognised.
    assert registered_definition_layering(_layered_spec([dep, pos, sup])) == [False, True, True]


def test_layering_is_unaffected_by_an_unrelated_draft_error():
    # Draft-tolerant CRUD can persist a system that does not fully compile (here a
    # rule binding names a sort the grammar lacks). Layering must still be read
    # off the grammar+definitions alone, so a reorder guard can trust it rather
    # than seeing the whole build fail and treating every definition as dropped.
    broken_rule = rule("BAD", "bad", ["p"], "p", [("p", "no_such_sort")])

    def spec(definitions):
        s = _layered_spec(definitions)
        s.rules = [broken_rule]
        return s

    # The unrelated error does fail a full build...
    assert "errors" in build_spec(spec([subset_def(), superset_def()]))
    # ...but layering is computed regardless, and still catches the bad order.
    assert registered_definition_layering(spec([subset_def(), superset_def()])) == [True, True]
    assert registered_definition_layering(spec([superset_def(), subset_def()])) == [False, True]


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


def test_a_very_long_formula_still_parses(zfc):
    # A deeply nested but well-formed formula over 1000 characters. The retired
    # `pre_format` hook capped every matched string at that length, so a line
    # this long used to fail with "Limit exceeded in apply pre-format
    # replacements" — a valid proof reported invalid.
    formula = "x ∈ y"
    while len(formula) < 1100:
        formula = f"({formula} → x ∈ y)"
    assert len(formula) > 1000

    proof = zfc.parse(f"{formula} [HYP]")
    assert proof.valid is True


# ---------------------------------------------------------------------------
# Structured accessors: the formula/reference are declared fields on the line
# type. The interpreted `formula()`/`reference()` accessor mini-language is gone.
# ---------------------------------------------------------------------------


def test_line_types_declare_formula_and_reference_fields(zfc):
    statement = next(lt for lt in zfc.line_types if lt.name == "statement")
    # The logical line names its formula and citation fields directly.
    assert statement.formula_field == "f"
    assert statement.reference_field == "r"

    # A bare axiom asserts its whole match: `formula: self`.
    extensionality = next(lt for lt in zfc.line_types if lt.name == "extensionality")
    assert extensionality.formula_field == "self"


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
        lines=[statement_line()],
        rules=[
            hyp_rule(),
            rule("RImp", "refl imp", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["equal(p, q)"]),
            rule("NOcc", "non occur", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["not occurs(p, q)"]),
        ],
    )


def test_side_conditions_gate_the_rule_during_checking():
    # The payoff: the built system enforces the provisos.
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
        lines=[LineSpec(name="statement", shape="<reference>", parts=[],
                        logical_sort=None)],
    )
    result = build_spec(spec)
    assert "errors" in result
    assert result["errors"]


def test_build_system_raises_declarative_error_on_invalid_shape():
    # `build_system` raises DeclarativeError directly (build_spec catches it and
    # reports errors); a shape whose sole placeholder is not a grammar sort has
    # no logical field to project.
    spec = SystemSpec(
        name="S",
        productions=[template_prod("formula", "atom", "a")],
        lines=[LineSpec(name="statement", shape="assertion", parts=[],
                        logical_sort="formula")],
    )
    with pytest.raises(DeclarativeError):
        build_system(spec)


# ---------------------------------------------------------------------------
# Atom productions: constants (one literal) and indexed families (`base_#`),
# built directly into the engine's AtomPattern — the going-forward way to
# declare atomic sort members without a stand-in regex.
# ---------------------------------------------------------------------------


def atomic_spec() -> SystemSpec:
    # `prop` is the infinite family p, p_0, p_1, …; `falsum` is the constant ⊥.
    return SystemSpec(
        name="Atomic",
        brackets=brackets(),
        productions=[
            atom_family_prod("formula", "prop", "p"),
            atom_const_prod("formula", "falsum", "⊥"),
            negation_prod(),
            implication_prod(),
        ],
        lines=[statement_line()],
        rules=[
            hyp_rule(),
            rule("X", "contradiction", ["a", "¬a"], "⊥",
                 [("a", "formula")]),
        ],
    )


def test_atoms_build_into_atom_patterns():
    from website.logical.matching import AtomPattern

    system = build_system(atomic_spec())
    prop = system.build_context.variables["prop"]
    falsum = system.build_context.variables["falsum"]
    assert isinstance(prop, AtomPattern) and prop.base == "p" and prop.value is None
    assert isinstance(falsum, AtomPattern) and falsum.value == "⊥" and falsum.base is None
    # Both are members of the `formula` sort, in declared order.
    formula = system.build_context.variables["formula"]
    assert [p.name for p in formula.patterns] == ["prop", "falsum", "negation", "implication"]


def test_atom_family_admits_arbitrary_members():
    system = build_system(atomic_spec())
    # The base and any indexed member are well-formed formulas…
    assert system.parse("p [HYP]").valid is True
    assert system.parse("p_42 [HYP]").valid is True
    # …but a different base is not in the family.
    assert system.parse("q_0 [HYP]").valid is False


def test_atom_constant_is_a_literal_and_a_rule_conclusion():
    system = build_system(atomic_spec())
    # The contradiction rule concludes the *constant* ⊥ from p and ¬p.
    proof = system.parse("p_0 [HYP]\n¬p_0 [HYP]\n⊥ [X, 1, 2]")
    assert proof.valid is True
    # ⊥ nests inside a compound like any other formula member.
    assert system.parse("(p_0 → ⊥) [HYP]").valid is True


# ---------------------------------------------------------------------------
# Multiple logical line types: a system may declare several line shapes; the
# engine tries each when parsing a proof line.
# ---------------------------------------------------------------------------


def test_multiple_logical_line_types_build_and_parse():
    spec = SystemSpec(
        name="TwoLines",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[
            statement_line(),  # `<formula> [<reference>]`, named "statement"
            LineSpec(
                name="turnstile",
                shape="⊢ <formula> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="formula",
            ),
        ],
        rules=[hyp_rule()],
    )
    system = build_system(spec)
    assert [lt.name for lt in system.line_types] == ["statement", "turnstile"]
    # A plain line matches `statement`; a ⊢-prefixed line matches `turnstile`.
    assert system.parse("(a → b) [HYP]").valid is True
    assert system.parse("⊢ (a → b) [HYP]").valid is True


def test_single_line_kwarg_is_accepted_for_back_compat():
    # The former single-line API (`line=`) still constructs and builds; it
    # normalises into `lines` without becoming a compared field.
    spec = SystemSpec(
        name="Compat",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        line=statement_line(),
        rules=[hyp_rule()],
    )
    assert [ls.name for ls in spec.lines] == ["statement"]
    assert spec == SystemSpec(
        name="Compat",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line()],
        rules=[hyp_rule()],
    )
    assert build_system(spec).parse("(a → b) [HYP]").valid is True


def test_same_named_line_parts_are_scoped_per_line():
    # Two lines both name their reference part "reference" but with different
    # regexes; each line must keep its own — the later, narrower `assume` part
    # must not overwrite `claim`'s in the shared namespace.
    spec = SystemSpec(
        name="Parts",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[
            LineSpec(
                name="claim", shape="<formula> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9, ]+")],
                logical_sort="formula",
            ),
            LineSpec(
                name="assume", shape="assume <formula> [<reference>]",
                parts=[LinePart(name="reference", regex="[0-9]+")],
                logical_sort="formula",
            ),
        ],
        rules=[hyp_rule()],
    )
    system = build_system(spec)
    # If `claim` had been rebound to `assume`'s digits-only regex, the citation
    # "HYP" would fail to match and no line would parse this.
    assert system.parse("(a → b) [HYP]").valid is True


def scoped_spec() -> SystemSpec:
    # Propositional fragment with a scope-opening `assume` line and reiteration,
    # enough to exercise subproofs and scope-checked references without a
    # discharge rule.
    return SystemSpec(
        name="Scoped",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[reiteration_rule()],
    )


def test_the_engine_carries_no_edi_compiler():
    """The `.edi` compiler is gone; nothing may reintroduce a dependency on it.

    Kept as a guard rather than deleted with the module: `compiler.py` is still
    in the history, and an import of it (or a resurrected copy) would fail
    somewhere far from the cause. Cheap to keep, and it states the invariant.
    """
    engine = Path(__file__).resolve().parent.parent / "website" / "logical"
    assert not (engine / "compiler.py").exists()

    offenders = []
    for path in sorted(engine.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Both halves matter. `from .compiler import compile` puts it in
                # the module, `from website.logical import compiler` in the
                # names — the same dependency, written two ways.
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            offenders += [f"{path.name} -> {n}" for n in names if "compiler" in n]

    assert offenders == []


def commented_spec() -> SystemSpec:
    spec = scoped_spec()
    spec.lines.append(comment_line())
    return spec


def test_comment_line_builds_an_unchecked_line_type():
    system = build_system(commented_spec())
    note = {lt.name: lt for lt in system.line_types}["note"]
    assert note.behaviour == "comment"
    # No formula to project — the field is left unset rather than pointed at
    # prose, so nothing harvesting line formulae picks it up.
    assert note.formula_field is None


def test_comment_line_is_valid_unnumbered_and_uncitable():
    system = build_system(commented_spec())
    proof = system.parse("-- a header\na [R, 1]\n-- trailing note")
    notes = [line for line in proof.proof_lines if line.display.startswith("--")]

    # Prose passes without justification and takes no citation number, so the
    # step between the two notes is still line 1.
    assert all(line.valid for line in notes)
    assert [line.number for line in proof.proof_lines] == [None, 1, None]


def test_comment_line_does_not_close_the_subproof_it_sits_in():
    # An unindented note dedents past the opener. If commentary took part in
    # scoping it would close the subproof and the next step would be rejected as
    # out of scope — a failure on a line the author never touched.
    system = build_system(commented_spec())
    proof = system.parse("assume a\n-- granted for the subproof\n    a [R, 1]")
    assert proof.valid is True


def test_comment_line_carries_no_citation_reference():
    # Projecting the prose as the line's reference would surface it in the UI as
    # the rule that justified the line ("by a header").
    system = build_system(commented_spec())
    note = {lt.name: lt for lt in system.line_types}["note"]
    assert note.reference_field is None
    assert system.parse("-- a header").data()["lines"][0]["reference"] is None


def test_comment_line_is_exempt_from_bracket_parity():
    # Prose is not a term, so an unbalanced bracket in a note must not stop the
    # line matching — which would fail the whole proof, not just the note.
    system = build_system(commented_spec())
    note = {lt.name: lt for lt in system.line_types}["note"]
    assert note.pattern.respect_brackets is None
    # The logical line still respects them.
    assert {lt.name: lt for lt in system.line_types}["statement"].pattern.respect_brackets

    line = system.parse("-- discharge ( here").proof_lines[0]
    assert line.valid is True
    assert line.line_type.name == "note"


@pytest.mark.parametrize(
    "line",
    [
        LineSpec(name="n", shape="-- <undeclared>", behaviour="comment"),
        LineSpec(name="n", shape="<formula> [<undeclared>]", logical_sort="formula"),
    ],
    ids=["comment", "logical"],
)
def test_undeclared_shape_placeholder_names_itself(line):
    # It has to resolve to a pattern later either way; without this the failure
    # is a bare KeyError whose message is just the token.
    spec = scoped_spec()
    spec.lines.append(line)
    with pytest.raises(DeclarativeError, match="naming no grammar sort or part"):
        build_system(spec)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"behaviour": "indent"}, "invalid behaviour"),
        ({"behaviour": "comment", "scope": "assumption"}, "cannot open a"),
        ({"behaviour": "comment", "logical_sort": "formula"}, "carries no formula"),
    ],
)
def test_unauthorable_line_behaviours_are_build_errors(overrides, expected):
    spec = scoped_spec()
    line = comment_line()
    for field, value in overrides.items():
        setattr(line, field, value)
    spec.lines.append(line)

    with pytest.raises(DeclarativeError, match=expected):
        build_system(spec)


def test_scope_line_builds_a_scope_opening_line_type():
    system = build_system(scoped_spec())
    by_name = {lt.name: lt for lt in system.line_types}
    assume = by_name["assume"]
    # The `assume` line is BOTH a formula-bearing logical line AND a scope
    # opener — the two concerns the engine keeps orthogonal to `behaviour`.
    assert assume.behaviour == "logical"
    assert assume.scope == "assumption"
    # A plain line opens no scope.
    assert by_name["statement"].scope is None


def test_scope_line_opens_a_subproof_and_scopes_references():
    system = build_system(scoped_spec())

    # A scope opener is granted by fiat — valid with no justification.
    assert system.parse("assume a").proof_lines[0].valid is True

    # A reference within the open scope is accessible.
    assert system.parse("assume a\n    a [R, 1]").proof_lines[1].valid is True

    # But citing a line inside an already-closed sibling subproof is rejected —
    # the cross-scope unsoundness the scope machinery closes.
    proof = system.parse(
        "assume a\n"
        "    a [R, 1]\n"
        "assume b\n"
        "    a [R, 2]"
    )
    assert proof.proof_lines[3].valid is False
    assert "scope" in (proof.proof_lines[3].invalid_message or "").lower()


def test_scope_error_names_the_citation_number_not_the_text_position():
    # The message has to agree with what the author typed. The leading blank
    # shifts every text position by one but no citation number, so the rejected
    # `[R, 2]` must be reported as line 2 — not line 3, where it sits in the file.
    system = build_system(scoped_spec())
    proof = system.parse(
        "\n"
        "assume a\n"
        "    a [R, 1]\n"
        "assume b\n"
        "    a [R, 2]"
    )
    bad = proof.proof_lines[4]
    assert bad.valid is False
    assert "Line 2 is out of scope" in (bad.invalid_message or "")


def test_invalid_line_scope_is_rejected():
    spec = SystemSpec(
        name="BadScope",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]")],
        lines=[LineSpec(name="weird", shape="<formula>", logical_sort="formula", scope="bogus")],
    )
    result = build_spec(spec)
    assert "errors" in result
    assert "scope" in result["errors"][0].lower()


# ---------------------------------------------------------------------------
# Discharge rules: a rule consumes a subproof rather than citing lines.
# ---------------------------------------------------------------------------


def cp_spec() -> SystemSpec:
    # Propositional fragment with an `assume` scope line, reiteration, and a
    # conditional-proof discharge rule (→I).
    return SystemSpec(
        name="CP",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[reiteration_rule(), cp_rule()],
    )


def scoped_fol_spec() -> SystemSpec:
    # A first-order fragment with both discharge rules: CP (→I, an assumption
    # subproof) and UG (∀I, a fresh-variable subproof). `setvar` is a leaf sort
    # whose member name differs from the sort (the binding-sort gotcha).
    return SystemSpec(
        name="ScopedFOL",
        brackets=brackets(),
        productions=[
            regex_prod("setvar", "setvar_atom", "[a-z][a-z0-9]*"),
            template_prod("formula", "membership", "x ∈ y", [("x", "setvar"), ("y", "setvar")]),
            implication_prod(),
            template_prod("formula", "universal", "∀x p", [("x", "setvar"), ("p", "formula")]),
        ],
        lines=[
            statement_line(),
            assumption_line(),
            LineSpec(name="introduce", shape="let <setvar>", logical_sort="setvar", scope="variable"),
        ],
        rules=[
            reiteration_rule(),
            cp_rule(),
            Rule(
                label="UG", name="universal generalisation", antecedents=[], deduction="∀x p",
                bindings=[("x", "setvar"), ("p", "formula")],
                subproof=Subproof(fresh="x", derive="p"),
            ),
        ],
    )


def test_discharge_rule_builds_a_subproof_schema():
    system = build_system(cp_spec())
    cp = {r.label: r for r in system.inference_rules}["CP"]
    assert cp.is_discharge is True
    assert cp.subproof_schema.kind == "assumption"
    # A plain rule is not a discharge rule.
    assert {r.label: r for r in system.inference_rules}["R"].is_discharge is False


def test_conditional_proof_discharges_an_assumption_subproof():
    system = build_system(cp_spec())
    # →I: assume a, reiterate it, discharge to (a → a).
    proof = system.parse("assume a\n    a [R, 1]\n(a → a) [CP, 1]")
    assert proof.valid is True, [(l.display, l.valid) for l in proof.proof_lines]
    # Discharging to a conclusion that was never derived is rejected.
    bogus = system.parse("assume a\n    a [R, 1]\n(a → b) [CP, 1]")
    assert bogus.proof_lines[2].valid is False


def test_universal_generalisation_discharges_a_variable_subproof():
    system = build_system(scoped_fol_spec())
    ug = {r.label: r for r in system.inference_rules}["UG"]
    assert ug.subproof_schema.kind == "variable"

    # ∀x (x∈c → x∈c): introduce an arbitrary x, prove the implication under it,
    # then generalise. x is genuinely fresh, so ∀I is sound.
    sound = system.parse(
        "let x\n"
        "    assume x ∈ c\n"
        "        x ∈ c [R, 2]\n"
        "    (x ∈ c → x ∈ c) [CP, 2]\n"
        "∀x (x ∈ c → x ∈ c) [UG, 1]"
    )
    assert sound.valid is True, [(l.display, l.valid) for l in sound.proof_lines]

    # Freshness violation: x occurs in the enclosing open hypothesis, so
    # generalising over it is unsound — the fresh-variable subproof rejects it.
    unsound = system.parse(
        "assume x ∈ c\n"
        "    let x\n"
        "        x ∈ c [R, 1]\n"
        "    ∀x x ∈ c [UG, 2]"
    )
    assert unsound.proof_lines[3].valid is False


@pytest.mark.parametrize(
    "antecedents,side_conditions",
    [
        (["p"], []),                    # a discharge rule with a line antecedent
        ([], ["equal(p, q)"]),          # a discharge rule with a proviso
    ],
)
def test_discharge_rule_cannot_carry_antecedents_or_side_conditions(antecedents, side_conditions):
    # The discharge check consumes the subproof and never evaluates line
    # antecedents or side-conditions, so accepting them would silently drop a
    # soundness constraint. build_system refuses the pairing.
    spec = SystemSpec(
        name="BadDischarge",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[Rule(label="CP", name="cp", antecedents=antecedents, deduction="(p → q)",
                    bindings=[("p", "formula"), ("q", "formula")],
                    side_conditions=side_conditions, subproof=Subproof(assume="p", derive="q"))],
    )
    result = build_spec(spec)
    assert "errors" in result
    assert "discharge" in result["errors"][0].lower()


def test_discharge_rule_may_carry_an_inert_extra_antecedents_flag():
    # The discharge check ignores `allow_extra_antecedents` (it cites exactly one
    # subproof opener), but an ignored *allowance* is only ever stricter -- it
    # cannot admit anything the flag-free rule would reject. So unlike antecedents
    # and side-conditions above, the pairing is inert rather than unsound, and is
    # permitted: the rule builds and discharges exactly as it would without it.
    spec = SystemSpec(
        name="InertFlag",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[reiteration_rule(),
               Rule(label="CP", name="cp", antecedents=[], deduction="(p → q)",
                    bindings=[("p", "formula"), ("q", "formula")],
                    subproof=Subproof(assume="p", derive="q"),
                    allow_extra_antecedents=True)],
    )
    result = build_spec(spec)
    assert "errors" not in result, result.get("errors")

    system = result["system"]
    # Discharge still works, and still requires exactly one subproof opener --
    # the flag buys the citation nothing.
    assert system.parse("assume a\n    a [R, 1]\n(a → a) [CP, 1]").valid is True
    assert system.parse(
        "assume a\n    a [R, 1]\nassume b\n    b [R, 3]\n(a → a) [CP, 1, 3]"
    ).proof_lines[-1].valid is False


def test_extra_antecedents_flag_governs_a_surplus_citation():
    # With the flag on, a citation may name more lines than the rule has slots:
    # the surplus is kept as unconstrained `extra_antecedents`. With it off (the
    # default), the same citation is rejected as over-specified.
    def spec(allow_extra: bool) -> SystemSpec:
        return SystemSpec(
            name="Extra",
            brackets=brackets(),
            productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
            lines=[statement_line()],
            rules=[
                rule("HYP", "hypothesis", [], "p", [("p", "formula")]),
                Rule(label="MPX", name="mpx", antecedents=["p", "(p → q)"], deduction="q",
                     bindings=[("p", "formula"), ("q", "formula")],
                     allow_extra_antecedents=allow_extra),
            ],
        )

    source = "a [HYP]\n(a → b) [HYP]\nc [HYP]\nb [MPX, 1, 2, 3]"

    permitted = build_system(spec(True)).parse(source).proof_lines[-1]
    assert permitted.valid is True
    assert (len(permitted.antecedents), len(permitted.extra_antecedents)) == (2, 1)

    refused = build_system(spec(False)).parse(source).proof_lines[-1]
    assert refused.valid is False
    assert "exactly 2 antecedent" in refused.invalid_message


@pytest.mark.parametrize(
    "subproof",
    [
        Subproof(derive="q", assume="p", fresh="x"),  # both openers
        Subproof(derive="q"),                          # neither opener
    ],
)
def test_subproof_requires_exactly_one_opener(subproof):
    spec = SystemSpec(
        name="BadSubproof",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[Rule(label="CP", name="cp", antecedents=[], deduction="(p → q)",
                    bindings=[("p", "formula"), ("q", "formula")], subproof=subproof)],
    )
    result = build_spec(spec)
    assert "errors" in result
    assert "exactly one" in result["errors"][0].lower()
