"""The formal-system decomposition round-trips through a real database.

Proves the ``source``/``compiled`` blob can go: a system is stored as flat rows,
reloaded, and rebuilt into a ``SystemSpec`` equal to the original that still
builds a system checking the same proofs -- and the rows are queryable with
plain SQL, no compile.
"""

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, aliased

from app.db import Base, SideConditionRow, spec_to_system, system_to_spec
from app.db.models import FormalSystem
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from tests.spec_helpers import (
    assumption_line,
    atom_const_prod,
    atom_family_prod,
    axiom,
    biconditional_prod,
    brackets,
    conjunction_prod,
    cp_rule,
    defn,
    equality_prod,
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
    universal_prod,
    variable_prod,
)
from website.logical.declarative import LinePart, LineSpec, SystemSpec, build_spec

# The system decomposition now lives among the full app schema. The pgvector
# `theorems` table (and other Postgres-only bits) aren't SQLite-creatable, so
# create just the system-decomposition tables for this round-trip test.
_SYSTEM_TABLES = [
    m.__table__
    for m in (
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        LineRow, LinePartRow, DefinitionRow, DefinitionBindingRow, DefinitionFreshRow,
        AxiomRow, AxiomBindingRow, RuleRow, RuleAntecedentRow, RuleBindingRow,
        SideConditionRow,
    )
]


def zfc_spec() -> SystemSpec:
    # A compact but genuine fragment of ZFC, assembled directly as a SystemSpec.
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            conjunction_prod(), implication_prod(), biconditional_prod(),
            universal_prod(),
        ],
        lines=[statement_line()],
        axioms=[axiom("EXT", "extensionality", "∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)")],
        rules=[hyp_rule(), mp_rule()],
        definitions=[
            subset_def(),
            defn("formula", "superset", "x ⊇ y", "y ⊆ x",
                 [("x", "variable"), ("y", "variable")]),
        ],
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_SYSTEM_TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def stored_system(session):
    # Spec -> rows -> commit -> reload from a fresh identity map.
    spec = zfc_spec()
    session.add(spec_to_system(spec))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystem).where(FormalSystem.name == "ZFC"))


# ---------------------------------------------------------------------------
# Round trip fidelity
# ---------------------------------------------------------------------------


def test_spec_round_trips_through_the_database(stored_system):
    rebuilt = system_to_spec(stored_system)
    assert rebuilt == zfc_spec()


def atomic_spec() -> SystemSpec:
    # An atom constant (⊥) and an atom family (p_#) alongside a composite.
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
        rules=[hyp_rule(), rule("X", "contradiction", ["a", "¬a"], "⊥", [("a", "formula")])],
    )


def two_line_spec() -> SystemSpec:
    # Two logical line types: the usual `statement` plus a ⊢-prefixed `turnstile`.
    return SystemSpec(
        name="TwoLines",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[
            statement_line(),
            LineSpec(
                name="turnstile",
                shape="⊢ <formula> [<ref>]",
                parts=[LinePart(name="ref", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="formula",
            ),
        ],
        rules=[hyp_rule()],
    )


def test_multiple_line_types_round_trip_through_the_database(session):
    session.add(spec_to_system(two_line_spec()))
    session.commit()
    session.expire_all()
    stored = session.scalar(select(FormalSystem).where(FormalSystem.name == "TwoLines"))

    # Both line rows persist, in position order.
    assert [line.name for line in stored.lines] == ["statement", "turnstile"]
    assert system_to_spec(stored) == two_line_spec()

    system = build_spec(system_to_spec(stored))["system"]
    assert system.parse("(a → b) [HYP]").valid is True
    assert system.parse("⊢ (a → b) [HYP]").valid is True


def test_atom_productions_round_trip_through_the_database(session):
    # Constant / family atoms persist as kind="atom" rows carrying atom_value /
    # atom_base, and rebuild into an equal SystemSpec.
    session.add(spec_to_system(atomic_spec()))
    session.commit()
    session.expire_all()
    stored = session.scalar(select(FormalSystem).where(FormalSystem.name == "Atomic"))

    kinds = {s.name: s.kind for s in stored.symbols}
    assert kinds["prop"] == "atom" and kinds["falsum"] == "atom"
    assert system_to_spec(stored) == atomic_spec()

    # And the rebuilt spec still builds a system that checks atom proofs.
    system = build_spec(system_to_spec(stored))["system"]
    assert system.parse("p_7 [HYP]").valid is True
    assert system.parse("p_0 [HYP]\n¬p_0 [HYP]\n⊥ [X, 1, 2]").valid is True


def scoped_spec() -> SystemSpec:
    # A scope-opening `assume` line alongside the plain `statement` line.
    return SystemSpec(
        name="Scoped",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[reiteration_rule()],
    )


def test_scoped_line_types_round_trip_through_the_database(session):
    # The `scope` a line opens persists on the line row and rebuilds into an
    # equal spec whose subproof scope-checking still holds.
    session.add(spec_to_system(scoped_spec()))
    session.commit()
    session.expire_all()
    stored = session.scalar(select(FormalSystem).where(FormalSystem.name == "Scoped"))

    scopes = {line.name: line.scope for line in stored.lines}
    assert scopes == {"statement": None, "assume": "assumption"}
    assert system_to_spec(stored) == scoped_spec()

    system = build_spec(system_to_spec(stored))["system"]
    # In-scope reiteration checks; citing into a closed sibling subproof does not.
    assert system.parse("assume a\n    a [R, 1]").proof_lines[1].valid is True
    out_of_scope = system.parse(
        "assume a\n    a [R, 1]\nassume b\n    a [R, 2]"
    )
    assert out_of_scope.proof_lines[3].valid is False


def discharge_spec() -> SystemSpec:
    # A scope-opening `assume` line plus a conditional-proof discharge rule.
    return SystemSpec(
        name="Discharge",
        brackets=brackets(),
        productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
        lines=[statement_line(), assumption_line()],
        rules=[reiteration_rule(), cp_rule()],
    )


def test_discharge_rules_round_trip_through_the_database(session):
    # The subproof a discharge rule consumes persists on the rule row (three
    # schema lines) and rebuilds into an equal spec whose →I discharge still
    # checks.
    session.add(spec_to_system(discharge_spec()))
    session.commit()
    session.expire_all()
    stored = session.scalar(select(FormalSystem).where(FormalSystem.name == "Discharge"))

    cp_row = next(r for r in stored.rules if r.label == "CP")
    assert (cp_row.subproof_derive, cp_row.subproof_assume, cp_row.subproof_fresh) == ("q", "p", None)
    # A non-discharge rule stores no subproof.
    r_row = next(r for r in stored.rules if r.label == "R")
    assert r_row.subproof_derive is None
    assert system_to_spec(stored) == discharge_spec()

    system = build_spec(system_to_spec(stored))["system"]
    assert system.parse("assume a\n    a [R, 1]\n(a → a) [CP, 1]").valid is True


def labelled_definition_spec() -> SystemSpec:
    # An alias definition carrying a citation label (`sub`); the label must persist
    # on the definition row and rebuild into a definition citable as `[sub, line]`.
    return SystemSpec(
        name="Labelled",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod()],
        lines=[statement_line()],
        definitions=[
            defn("formula", "sub", "x sub y", "x ∈ y",
                 [("x", "term"), ("y", "term")], label="sub"),
        ],
        rules=[hyp_rule()],
    )


def test_labelled_definitions_round_trip_through_the_database(session):
    # A definition's citation `label` persists on its row and rebuilds into an
    # equal spec whose named citation still resolves.
    session.add(spec_to_system(labelled_definition_spec()))
    session.commit()
    session.expire_all()
    stored = session.scalar(select(FormalSystem).where(FormalSystem.name == "Labelled"))

    assert {d.name: d.label for d in stored.definitions} == {"sub": "sub"}
    assert system_to_spec(stored) == labelled_definition_spec()

    system = build_spec(system_to_spec(stored))["system"]
    proof = system.parse("a sub b [HYP]\na ∈ b [sub, 1]")
    assert proof.proof_lines[1].valid is True


def test_decomposition_has_no_source_or_json_blob():
    # The system row stores structure, not a dumped source string or JSON.
    columns = {c.name for c in FormalSystem.__table__.columns}
    assert "source" not in columns
    assert "compiled" not in columns
    assert not any(str(c.type).upper().startswith("JSON") for c in FormalSystem.__table__.columns)


# ---------------------------------------------------------------------------
# The rebuilt system still compiles and checks proofs
# ---------------------------------------------------------------------------


def test_rebuilt_system_compiles_and_checks_proofs(stored_system):
    spec = system_to_spec(stored_system)
    result = build_spec(spec)
    assert "errors" not in result, result.get("errors")
    system = result["system"]

    # Axiom assertion is valid.
    assert system.parse("∀x ∀y (∀z (z ∈ x ↔ z ∈ y) → x = y)").valid is True

    # Modus ponens over the raw base.
    assert system.parse("x ∈ y [HYP]\n(x ∈ y → x = y) [HYP]\nx = y [MP, 1, 2]").valid is True

    # Modus ponens over layered defined notation survives the round trip.
    assert system.parse("x ⊆ y [HYP]\n(x ⊆ y → x ⊇ y) [HYP]\nx ⊇ y [MP, 1, 2]").valid is True


# ---------------------------------------------------------------------------
# The payoff: structural search in plain SQL, without compiling anything
# ---------------------------------------------------------------------------


def test_search_systems_that_define_a_name(session, stored_system):
    # "Which systems define subset?" - a join, not a compile-and-scan.
    rows = session.scalars(
        select(FormalSystem.name)
        .join(DefinitionRow, DefinitionRow.system_id == FormalSystem.id)
        .where(DefinitionRow.name == "subset")
    ).all()
    assert rows == ["ZFC"]


def test_search_composite_productions_of_a_sort(session, stored_system):
    # "Which formula constructors does ZFC have?" - productions (template
    # symbols) whose union (member_of) is the `formula` sort.
    union = aliased(SymbolRow)
    names = session.scalars(
        select(SymbolRow.name)
        .join(union, SymbolRow.member_of_union_id == union.id)
        .where(union.name == "formula", SymbolRow.kind == "composite")
        .order_by(SymbolRow.position)
    ).all()
    assert names == [
        "membership", "equality", "negation", "conjunction",
        "implication", "biconditional", "universal",
    ]


def test_search_rules_by_antecedent_count(session, stored_system):
    # "Which rules take two premises?" - group-by over antecedent rows.
    two_premise = session.scalars(
        select(RuleRow.label)
        .join(RuleAntecedentRow, RuleAntecedentRow.rule_id == RuleRow.id)
        .group_by(RuleRow.id)
        .having(func.count(RuleAntecedentRow.id) == 2)
    ).all()
    assert two_premise == ["MP"]
