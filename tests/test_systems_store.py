"""The formal-system decomposition round-trips through a real database.

Proves the ``source``/``compiled`` blob can go: a system is stored as flat rows,
reloaded, rebuilt into a ``SystemSpec``, and still lowers to a system that
checks the same proofs -- and the rows are queryable with plain SQL, no compile.
"""

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.systems import spec_to_system, system_to_spec
from app.systems.models import (
    Base,
    DefinitionRow,
    FormalSystemRow,
    ProductionRow,
    RuleAntecedentRow,
    RuleRow,
    SortRow,
)
from website.logical.declarative import build_spec, lower, parse


ZFC_SOURCE = """system ZFC

notation
  brackets ( )

grammar
  term      | variable      | matches [a-z][a-z0-9]*
  formula   | membership    | s ∈ t                   | s, t : term
  formula   | equality      | s = t                   | s, t : term
  formula   | negation      | ¬p                      | p : formula
  formula   | conjunction   | (p ∧ q)                 | p, q : formula
  formula   | implication   | (p → q)                 | p, q : formula
  formula   | biconditional | (p ↔ q)                 | p, q : formula
  formula   | universal     | ∀x p                    | x : variable, p : formula

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


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def stored_system(session):
    # Parse -> rows -> commit -> reload from a fresh identity map.
    spec = parse(ZFC_SOURCE)
    session.add(spec_to_system(spec))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystemRow).where(FormalSystemRow.name == "ZFC"))


# ---------------------------------------------------------------------------
# Round trip fidelity
# ---------------------------------------------------------------------------


def test_spec_round_trips_through_the_database(stored_system):
    rebuilt = system_to_spec(stored_system)
    assert rebuilt == parse(ZFC_SOURCE)


def test_rebuilt_spec_lowers_identically(stored_system):
    # The strongest fidelity check: rows -> spec -> .edi is byte-identical to
    # parsing the original source and lowering it.
    assert lower(system_to_spec(stored_system)) == lower(parse(ZFC_SOURCE))


def test_decomposition_has_no_source_or_json_blob():
    # The system row stores structure, not a dumped source string or JSON.
    columns = {c.name for c in FormalSystemRow.__table__.columns}
    assert "source" not in columns
    assert "compiled" not in columns
    assert not any(str(c.type).upper().startswith("JSON") for c in FormalSystemRow.__table__.columns)


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
        select(FormalSystemRow.name)
        .join(DefinitionRow, DefinitionRow.system_id == FormalSystemRow.id)
        .where(DefinitionRow.name == "subset")
    ).all()
    assert rows == ["ZFC"]


def test_search_composite_productions_of_a_sort(session, stored_system):
    # "Which formula constructors does ZFC have?"
    names = session.scalars(
        select(ProductionRow.name)
        .join(SortRow, ProductionRow.sort_id == SortRow.id)
        .where(SortRow.name == "formula", ProductionRow.kind == "composite")
        .order_by(ProductionRow.position)
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
