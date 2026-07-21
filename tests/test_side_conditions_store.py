"""Definition provisos round-trip through the structured side-condition table.

Replaces the opaque ``definitions.condition`` string with the kernel's
side-condition algebra stored as rows: a proviso is parsed into a
``SideConditionRow`` tree on the way in, rebuilt to the identical ``where``
surface string on the way out, and its shape is queryable in plain SQL. A
drift guard checks the storage grammar accepts exactly what the engine's
``parse_side_condition`` accepts.
"""

from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system, system_to_spec
from app.db.models import FormalSystem
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import _parse  # grammar under test
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
from website.logical.declarative import build, lower, parse
from website.logical.formal_system.side_condition_syntax import parse_side_condition

_TABLES = [
    m.__table__
    for m in (
        FormalSystem, SymbolRow, ProductionBindingRow, BracketRow,
        LineRow, LinePartRow, DefinitionRow, DefinitionBindingRow,
        AxiomRow, AxiomBindingRow, RuleRow, RuleAntecedentRow, RuleBindingRow,
        SideConditionRow,
    )
]

# ZFC-ish grammar with two provisos: a single disjoint leaf, and a conjunction
# of a negated occurs and a sorted atom — exercising leaf/sort/not/and.
SOURCE = """system ZFC

notation
  brackets ( )

grammar
  term      | variable    | matches [a-z][a-z0-9]*
  formula   | membership  | s ∈ t                   | s, t : term
  formula   | equality    | s = t                   | s, t : term
  formula   | negation    | ¬p                      | p : formula
  formula   | implication | (p → q)                 | p, q : formula
  formula   | universal   | ∀x p                    | x : variable, p : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

rules
  HYP | hypothesis | from | infer p | p : formula

definitions
  formula | subset   | x ⊆ y | means ∀z (z ∈ x → z ∈ y) | x, y, z : variable
  formula | distinct | x ≠ y | means ¬(x = y)            | x, y : variable | where disjoint(x, y, variable)
  formula | fresh    | x ⊘ y | means ¬(x = y)            | x, y : variable | where not occurs(y, x) ; atom(x, variable)
"""


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def stored_system(session):
    session.add(spec_to_system(parse(SOURCE)))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystem).where(FormalSystem.name == "ZFC"))


def _definition(system, name):
    return next(d for d in system.definitions if d.name == name)


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_provisos_round_trip_through_the_database(stored_system):
    rebuilt = system_to_spec(stored_system)
    assert rebuilt == parse(SOURCE)


def test_rebuilt_spec_lowers_identically(stored_system):
    assert lower(system_to_spec(stored_system)) == lower(parse(SOURCE))


def test_provisoless_definition_has_no_side_condition_rows(stored_system):
    subset = _definition(stored_system, "subset")
    assert subset.side_conditions == []


def test_definitions_table_has_no_condition_column():
    assert "condition" not in DefinitionRow.__table__.columns
    assert "side_conditions" in Base.metadata.tables


# ---------------------------------------------------------------------------
# The tree is stored as the kernel algebra, sorts as real symbol references
# ---------------------------------------------------------------------------


def test_single_leaf_proviso_is_one_disjoint_row(stored_system):
    distinct = _definition(stored_system, "distinct")
    (root,) = distinct.side_conditions
    assert root.parent_id is None
    assert root.kind == "disjoint"
    assert (root.left_name, root.right_name) == ("x", "y")
    # The sort is a real FK into the symbol namespace, not a string.
    assert root.sort_symbol is not None and root.sort_symbol.name == "variable"


def test_conjunction_proviso_is_an_and_tree(stored_system):
    fresh = _definition(stored_system, "fresh")
    root = next(sc for sc in fresh.side_conditions if sc.parent_id is None)
    assert root.kind == "and"
    kinds = [child.kind for child in root.children]
    assert kinds == ["not", "atom"]
    # `not occurs(y, x)` — the not wraps the occurs leaf.
    negation = root.children[0]
    assert [c.kind for c in negation.children] == ["occurs"]
    assert (negation.children[0].left_name, negation.children[0].right_name) == ("y", "x")
    # `atom(x, variable)` — one metavar, a sort.
    atom = root.children[1]
    assert atom.left_name == "x" and atom.right_name is None
    assert atom.sort_symbol.name == "variable"


# ---------------------------------------------------------------------------
# The payoff: query proviso shape in plain SQL
# ---------------------------------------------------------------------------


def test_search_definitions_with_a_disjoint_proviso(session, stored_system):
    names = session.scalars(
        select(DefinitionRow.name)
        .join(SideConditionRow, SideConditionRow.definition_id == DefinitionRow.id)
        .where(SideConditionRow.kind == "disjoint")
    ).all()
    assert names == ["distinct"]


def test_search_provisos_over_a_given_sort(session, stored_system):
    # "Which definitions constrain the `variable` sort in a proviso?" — a join
    # through the sort FK, deduped (fresh mentions it once via atom).
    names = session.scalars(
        select(DefinitionRow.name)
        .join(SideConditionRow, SideConditionRow.definition_id == DefinitionRow.id)
        .join(SymbolRow, SideConditionRow.sort_symbol_id == SymbolRow.id)
        .where(SymbolRow.name == "variable")
        .distinct()
    ).all()
    assert sorted(names) == ["distinct", "fresh"]


# ---------------------------------------------------------------------------
# Drift guard: the storage grammar matches the engine's surface grammar
# ---------------------------------------------------------------------------


def test_storage_grammar_matches_the_engine_parser():
    # Both accept exactly the closed vocabulary; a context lets the engine parser
    # resolve the sort names in the sample.
    system = build(SOURCE)["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)

    accepted = [
        "occurs(x, phi)",
        "not occurs(x, phi)",
        "equal(p, q)",
        "disjoint(x, y)",
        "disjoint(x, y, variable)",
        "atom(x)",
        "atom(x, variable)",
    ]
    for text in accepted:
        parse_side_condition(text, context)  # engine: must not raise
        assert _parse(text) is not None  # storage: must not raise

    rejected = ["occurs(x)", "bogus(x, y)", "disjoint()", "atom(x, y, z)", "occurs(x, y, z)"]
    for text in rejected:
        with pytest.raises(ValueError):
            parse_side_condition(text, context)
        with pytest.raises(ValueError):
            _parse(text)
