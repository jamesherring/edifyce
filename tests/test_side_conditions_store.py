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
from app.db.side_conditions_mapping import (  # grammars under test
    _parse,
    _parse_lines,
    definition_condition_string,
    rule_side_conditions_list,
)
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
    brackets,
    defn,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    negation_prod,
    regex_prod,
    rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import SystemSpec, build_spec, lower
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
# of a negated occurs and a sorted atom — exercising leaf/sort/not/and. The two
# custom rules carry their provisos in the `side_conditions` list; the two
# provisoed definitions carry theirs in the `condition` field (a `;` conjoins).
def zfc_spec() -> SystemSpec:
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(), membership_prod(), equality_prod(), negation_prod(),
            implication_prod(), universal_prod(),
        ],
        line=statement_line(),
        rules=[
            hyp_rule(),
            rule("RImp", "refl imp", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["equal(p, q)"]),
            rule("NOcc", "non occur", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")], ["not occurs(p, q)"]),
        ],
        definitions=[
            subset_def(),
            defn("formula", "distinct", "x ≠ y", "¬(x = y)",
                 [("x", "variable"), ("y", "variable")], "disjoint(x, y, variable)"),
            defn("formula", "fresh", "x ⊘ y", "¬(x = y)",
                 [("x", "variable"), ("y", "variable")],
                 "not occurs(y, x) ; atom(x, variable)"),
        ],
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def stored_system(session):
    session.add(spec_to_system(zfc_spec()))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystem).where(FormalSystem.name == "ZFC"))


def _definition(system, name):
    return next(d for d in system.definitions if d.name == name)


def _rule(system, label):
    return next(r for r in system.rules if r.label == label)


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_provisos_round_trip_through_the_database(stored_system):
    rebuilt = system_to_spec(stored_system)
    assert rebuilt == zfc_spec()


def test_rebuilt_spec_lowers_identically(stored_system):
    assert lower(system_to_spec(stored_system)) == lower(zfc_spec())


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
# Rule provisos: the same structured storage generalised from definitions to the
# rule owner (side_conditions.rule_id), rooted per rule.
# ---------------------------------------------------------------------------


def test_rule_provisos_round_trip_through_the_database(stored_system):
    assert system_to_spec(stored_system) == zfc_spec()


def test_single_leaf_rule_proviso_is_one_equal_row(stored_system):
    rimp = _rule(stored_system, "RImp")
    (root,) = rimp.side_conditions
    assert root.parent_id is None
    assert root.rule_id == rimp.id and root.definition_id is None
    assert root.kind == "equal"
    assert (root.left_name, root.right_name) == ("p", "q")


def test_negated_rule_proviso_wraps_an_occurs_leaf(stored_system):
    nocc = _rule(stored_system, "NOcc")
    root = next(sc for sc in nocc.side_conditions if sc.parent_id is None)
    assert root.kind == "not"
    (occurs,) = root.children
    assert occurs.kind == "occurs"
    assert (occurs.left_name, occurs.right_name) == ("p", "q")
    # Every node of a rule tree carries the rule owner, none a definition.
    assert all(sc.rule_id == nocc.id and sc.definition_id is None for sc in nocc.side_conditions)


def test_provisoless_rule_has_no_side_condition_rows(stored_system):
    assert _rule(stored_system, "HYP").side_conditions == []


def test_search_rules_with_an_equality_proviso(session, stored_system):
    labels = session.scalars(
        select(RuleRow.label)
        .join(SideConditionRow, SideConditionRow.rule_id == RuleRow.id)
        .where(SideConditionRow.kind == "equal")
    ).all()
    assert labels == ["RImp"]


def test_proviso_over_an_undeclared_metavar_is_rejected(session):
    # A proviso may only reference the owner's declared bindings. `spec_to_system`
    # rejects a rule proviso naming an undeclared metavar rather than storing a
    # tree that has no binding to check against (which would raise in the kernel).
    spec = zfc_spec()
    next(r for r in spec.rules if r.label == "NOcc").side_conditions = ["not occurs(p, z)"]
    with pytest.raises(ValueError, match="metavariable 'z'"):
        session.add(spec_to_system(spec))


def test_round_tripped_rule_provisos_still_gate_proofs(stored_system):
    # The soundness payoff: a system reassembled from the DB rows enforces the
    # rule provisos exactly as the source system did.
    system = build_spec(system_to_spec(stored_system))["system"]
    # RImp needs equal(p, q): the two sides of the implication must be identical.
    assert system.parse("(x ∈ y → x ∈ y) [RImp]").valid is True
    assert system.parse("(x ∈ y → x ∈ z) [RImp]").valid is False
    # NOcc needs not occurs(p, q): the antecedent must not appear in the consequent.
    assert system.parse("(x ∈ y → z ∈ w) [NOcc]").valid is True
    assert system.parse("(x ∈ y → (x ∈ y → z ∈ w)) [NOcc]").valid is False


# ---------------------------------------------------------------------------
# `or` disjunctions round-trip and gate proofs
# ---------------------------------------------------------------------------

# DIS derives (p → q) when p and q coincide OR p does not occur in q.
def or_spec() -> SystemSpec:
    return SystemSpec(
        name="OrSys",
        brackets=brackets(),
        productions=[
            regex_prod("atom", "prop", "[a-z]"),
            template_prod("formula", "atomic", "a", [("a", "atom")]),
            implication_prod(),
        ],
        line=statement_line(),
        rules=[
            rule("DIS", "disj", [], "(p → q)",
                 [("p", "formula"), ("q", "formula")],
                 ["equal(p, q) or not occurs(p, q)"]),
        ],
    )


@pytest.fixture
def or_system(session):
    session.add(spec_to_system(or_spec()))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystem).where(FormalSystem.name == "OrSys"))


def test_or_proviso_is_stored_as_an_or_tree(or_system):
    dis = _rule(or_system, "DIS")
    root = next(sc for sc in dis.side_conditions if sc.parent_id is None)
    assert root.kind == "or"
    kinds = [child.kind for child in root.children]
    assert kinds == ["equal", "not"]
    # The `not` wraps the occurs leaf.
    assert [c.kind for c in root.children[1].children] == ["occurs"]


def test_or_proviso_round_trips(or_system):
    assert system_to_spec(or_system) == or_spec()
    dis = _rule(or_system, "DIS")
    assert rule_side_conditions_list(dis) == ["equal(p, q) or not occurs(p, q)"]


def test_round_tripped_or_proviso_gates_proofs(or_system):
    system = build_spec(system_to_spec(or_system))["system"]
    # equal disjunct holds.
    assert system.parse("(a → a) [DIS]").valid is True
    # equal fails but `not occurs` holds (a not in (b → c)).
    assert system.parse("(a → (b → c)) [DIS]").valid is True
    # both disjuncts fail: a ≠ (a → b) and a occurs in it.
    assert system.parse("(a → (a → b)) [DIS]").valid is False


# The `or` disjunction also reaches the *definition* owner via the `where` clause.
def or_def_spec() -> SystemSpec:
    return SystemSpec(
        name="OrDefSys",
        brackets=brackets(),
        productions=[
            regex_prod("term", "variable", "[a-z]"),
            membership_prod(),
            equality_prod(),
        ],
        line=statement_line(),
        definitions=[
            defn("formula", "rel", "x ~ y", "x = y",
                 [("x", "variable"), ("y", "variable")], "disjoint(x, y) or atom(x)"),
        ],
    )


@pytest.fixture
def or_def_system(session):
    session.add(spec_to_system(or_def_spec()))
    session.commit()
    session.expire_all()
    return session.scalar(select(FormalSystem).where(FormalSystem.name == "OrDefSys"))


def test_definition_where_or_round_trips(or_def_system):
    assert system_to_spec(or_def_system) == or_def_spec()
    rel = _definition(or_def_system, "rel")
    root = next(sc for sc in rel.side_conditions if sc.parent_id is None)
    assert root.kind == "or"
    assert [child.kind for child in root.children] == ["disjoint", "atom"]
    assert definition_condition_string(rel) == "disjoint(x, y) or atom(x)"


# ---------------------------------------------------------------------------
# Drift guard: the storage grammar matches the engine's surface grammar
# ---------------------------------------------------------------------------


def test_storage_grammar_matches_the_engine_parser():
    # Both accept exactly the closed vocabulary; a context lets the engine parser
    # resolve the sort names in the sample.
    system = build_spec(zfc_spec())["system"]
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
        "atom(x) or equal(x, y)",
        "not occurs(x, phi) or disjoint(x, y, variable)",
        "atom(x) or equal(x, y) or occurs(x, phi)",
    ]
    for text in accepted:
        parse_side_condition(text, context)  # engine: must not raise
        assert _parse(text) is not None  # storage (definition `where`): must not raise
        assert _parse_lines([text]) is not None  # storage (rule block): must not raise

    rejected = [
        "occurs(x)", "bogus(x, y)", "disjoint()", "atom(x, y, z)", "occurs(x, y, z)",
        "atom(x) or", "or atom(x)", "atom(x) or or atom(y)",
    ]
    for text in rejected:
        with pytest.raises(ValueError):
            parse_side_condition(text, context)
        with pytest.raises(ValueError):
            _parse(text)
        with pytest.raises(ValueError):
            _parse_lines([text])
