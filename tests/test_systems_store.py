"""The formal-system decomposition round-trips through a real database.

Proves the ``source``/``compiled`` blob can go: a system is stored as flat rows,
reloaded, rebuilt into a ``SystemSpec``, and still lowers to a system that
checks the same proofs -- and the rows are queryable with plain SQL, no compile.
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
    axiom,
    biconditional_prod,
    brackets,
    conjunction_prod,
    defn,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    negation_prod,
    statement_line,
    subset_def,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import SystemSpec, build_spec, lower

# The system decomposition now lives among the full app schema. The pgvector
# `theorems` table (and other Postgres-only bits) aren't SQLite-creatable, so
# create just the system-decomposition tables for this round-trip test.
_SYSTEM_TABLES = [
    m.__table__
    for m in (
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        LineRow, LinePartRow, DefinitionRow, DefinitionBindingRow,
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
        line=statement_line(),
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


def test_rebuilt_spec_lowers_identically(stored_system):
    # The strongest fidelity check: rows -> spec -> .edi is byte-identical to
    # lowering the originally-assembled spec.
    assert lower(system_to_spec(stored_system)) == lower(zfc_spec())


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
