"""Kernel terms round-trip through the relational term graph.

Proves the `theorems.pattern` JSONB blob can go (PR #23 follow-up): a
statement's kernel term is stored as shared `terms` / `term_children` rows,
reloaded from a fresh identity map, rebuilt into a live term that is `equal` to
the original and renders the identical surface string — and statement structure
is queryable in plain SQL (including transitively, via a recursive CTE) with no
JSON scans and no recompiling.
"""

from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, aliased

from app.db import Base, digest_term, load_term, store_term
from app.db.models import FormalSystem, Theorem
from app.db.terms import TermChildRow, TermRow
from website.logical.declarative import build
from website.logical.kernel import from_match

SOURCE = """system ZFC

notation
  brackets ( )

grammar
  term      | variable      | matches [a-z][a-z0-9]*
  formula   | membership    | s ∈ t                   | s, t : term
  formula   | implication   | (p → q)                 | p, q : formula
  formula   | universal     | ∀x p                    | x : variable, p : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

rules
  HYP | hypothesis   | from             | infer p | p : formula
  MP  | modus ponens | from p ; (p → q) | infer q | p, q : formula

definitions
  formula | subset | x ⊆ y | means ∀z (z ∈ x → z ∈ y) | x, y, z : variable
"""


@pytest.fixture(scope="module")
def engine_context():
    result = build(SOURCE)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return context


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            FormalSystem.__table__,
            TermRow.__table__,
            TermChildRow.__table__,
            Theorem.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


@pytest.fixture
def system_row(session):
    row = FormalSystem(name="ZFC", slug="zfc")
    session.add(row)
    session.flush()
    return row


def term_of(context, formula_string):
    formula = context.variables["formula"]
    return from_match(formula.match(formula_string, context), context)


# ---------------------------------------------------------------------------
# Round trip fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "x ∈ y",                      # ground leaf children
        "(x ∈ y → x ∈ z)",            # compound
        "∀z (z ∈ x → z ∈ y)",         # binder-shaped production
        "x ⊆ y",                      # defined notation (no namespace name)
        "(x ⊆ y → ∀w (w ∈ x → w ∈ y))",  # defined + raw mixed
    ],
)
def test_term_round_trips_through_the_database(
    session, system_row, engine_context, statement
):
    original = term_of(engine_context, statement)
    root = store_term(session, system_row, original)
    session.commit()
    root_id = root.id
    session.expire_all()  # fresh identity map: everything reloads from rows

    reloaded = load_term(session.get(TermRow, root_id), engine_context)
    assert reloaded.equal(original, engine_context)
    assert reloaded.to_string() == statement


def test_stored_rows_hold_no_json_or_source_blob():
    columns = TermRow.__table__.columns
    assert not any(str(c.type).upper().startswith("JSON") for c in columns)
    # And the theorems table no longer carries the old JSONB pattern column.
    assert "pattern" not in Theorem.__table__.columns


# ---------------------------------------------------------------------------
# Interning: storage is a shared DAG, like the kernel's terms
# ---------------------------------------------------------------------------


def test_shared_subterms_are_stored_once(session, system_row, engine_context):
    # Both statements contain the subterm "x ∈ y"; storing the second must
    # reuse the first's rows, not duplicate them.
    store_term(session, system_row, term_of(engine_context, "(x ∈ y → x ∈ z)"))
    session.flush()
    count_after_first = len(session.scalars(select(TermRow.id)).all())

    store_term(session, system_row, term_of(engine_context, "∀w (w ∈ w → x ∈ y)"))
    session.flush()
    rows = session.scalars(select(TermRow)).all()

    # "x ∈ y" appears in both statements but has exactly one row.
    membership_digest = digest_term(term_of(engine_context, "x ∈ y"))
    assert len([r for r in rows if r.digest == membership_digest]) == 1
    # And its leaves ("x", "y") were shared too, not re-created.
    assert len(rows) > count_after_first  # new structure was added...
    assert len({r.digest for r in rows}) == len(rows)  # ...but never duplicated


def test_restoring_the_same_statement_reuses_the_root(
    session, system_row, engine_context
):
    first = store_term(session, system_row, term_of(engine_context, "x ⊆ y"))
    session.flush()
    second = store_term(session, system_row, term_of(engine_context, "x ⊆ y"))
    assert second is first


def test_storing_against_an_unflushed_system_does_not_duplicate(
    session, engine_context
):
    # Import scenario: a new system and several statements in one transaction,
    # with no flush in between. The second store must reuse the first's pending
    # rows rather than re-create equal digests and trip the unique index.
    system = FormalSystem(name="ZFC-unflushed", slug="zfc-unflushed")
    store_term(session, system, term_of(engine_context, "x ∈ y"))
    store_term(session, system, term_of(engine_context, "(x ∈ y → x ∈ z)"))
    session.commit()  # would raise IntegrityError on duplicated digests

    rows = session.scalars(
        select(TermRow).where(TermRow.formal_system_id == system.id)
    ).all()
    assert len({r.digest for r in rows}) == len(rows)
    membership_digest = digest_term(term_of(engine_context, "x ∈ y"))
    assert len([r for r in rows if r.digest == membership_digest]) == 1


# ---------------------------------------------------------------------------
# The payoff: structural search in plain SQL
# ---------------------------------------------------------------------------


def test_search_statements_by_top_constructor(session, system_row, engine_context):
    for statement in ["(x ∈ y → x ∈ z)", "x ∈ y", "∀z (z ∈ x → z ∈ y)"]:
        term = term_of(engine_context, statement)
        root = store_term(session, system_row, term)
        session.add(
            Theorem(
                formal_system=system_row,
                statement=statement,
                statement_term=root,
            )
        )
    session.commit()

    # "Which theorems are implications?" — a join, not a JSON scan.
    implications = session.scalars(
        select(Theorem.statement)
        .join(TermRow, Theorem.statement_term_id == TermRow.id)
        .where(TermRow.constructor == "implication")
    ).all()
    assert implications == ["(x ∈ y → x ∈ z)"]


def test_search_statements_mentioning_a_production(
    session, system_row, engine_context
):
    statements = {
        "∀z (z ∈ x → z ∈ y)": True,   # membership nested two levels down
        "x ⊆ y": False,               # defined notation only; no raw ∈ node
    }
    for statement in statements:
        root = store_term(session, system_row, term_of(engine_context, statement))
        session.add(
            Theorem(
                formal_system=system_row, statement=statement, statement_term=root
            )
        )
    session.commit()

    # "Which theorems mention ∈ anywhere?" — walk the DAG with a recursive CTE.
    reachable = (
        select(Theorem.id.label("theorem_id"), TermRow.id.label("term_id"))
        .join(TermRow, Theorem.statement_term_id == TermRow.id)
        .cte(recursive=True)
    )
    child = aliased(TermRow)
    reachable = reachable.union_all(
        select(reachable.c.theorem_id, child.id)
        .join(TermChildRow, TermChildRow.parent_id == reachable.c.term_id)
        .join(child, TermChildRow.child_id == child.id)
    )
    mentions = session.scalars(
        select(Theorem.statement)
        .join(reachable, reachable.c.theorem_id == Theorem.id)
        .join(TermRow, reachable.c.term_id == TermRow.id)
        .where(TermRow.constructor == "membership")
        .distinct()
    ).all()
    assert mentions == ["∀z (z ∈ x → z ∈ y)"]


def test_search_statements_using_defined_notation(
    session, system_row, engine_context
):
    root = store_term(session, system_row, term_of(engine_context, "x ⊆ y"))
    session.add(
        Theorem(formal_system=system_row, statement="x ⊆ y", statement_term=root)
    )
    session.commit()

    # "Which theorems use a defined shorthand?" — the `defined` kind, whose
    # constructor is the definition's higher template (joinable against the
    # decomposition's definitions.higher column).
    rows = session.scalars(
        select(Theorem.statement)
        .join(TermRow, Theorem.statement_term_id == TermRow.id)
        .where(TermRow.kind == "defined", TermRow.constructor == "x ⊆ y")
    ).all()
    assert rows == ["x ⊆ y"]


# ---------------------------------------------------------------------------
# Defined-node resolution disambiguates by sort
# ---------------------------------------------------------------------------

AMBIGUOUS_SOURCE = """system DUP

notation
  brackets ( )

grammar
  term      | variable    | matches [a-z][a-z0-9]*
  term      | pairing     | ⟨s, t⟩                  | s, t : term
  formula   | membership  | s ∈ t                   | s, t : term
  formula   | conjunction | (p ∧ q)                 | p, q : formula

line statement
  shape <formula> [<reference>]
  reference | matches [A-Za-z0-9 ,]+
  logical formula

rules
  HYP | hypothesis | from | infer p | p : formula

definitions
  formula | both | x ⋈ y | means (x ∈ y ∧ y ∈ x) | x, y : variable
  term    | swap | x ⋈ y | means ⟨y, x⟩           | x, y : variable
"""


def test_defined_nodes_reload_with_their_stored_sort(session):
    # One higher template ("x ⋈ y") defined on two sorts. Loading must pick the
    # definition matching the stored sort — context.definitions is a set, so
    # template alone would choose arbitrarily and corrupt later sort checks.
    result = build(AMBIGUOUS_SOURCE)
    assert "errors" not in result, result.get("errors")
    engine_system = result["system"]
    context = copy(engine_system.context)
    context.variables.update(engine_system.build_context.variables)
    formula = context.variables["formula"]

    as_formula = from_match(formula.match("x ⋈ y", context), context)
    as_term = from_match(formula.match("x ⋈ y ∈ z", context), context).children["s"]
    assert (as_formula.sort.name, as_term.sort.name) == ("formula", "term")

    system = FormalSystem(name="DUP", slug="dup")
    ids = {}
    for label, term in (("formula", as_formula), ("term", as_term)):
        row = store_term(session, system, term)
        session.flush()
        ids[label] = row.id
    session.commit()
    session.expire_all()

    for label, original in (("formula", as_formula), ("term", as_term)):
        reloaded = load_term(session.get(TermRow, ids[label]), context)
        assert reloaded.sort.name == label
        assert reloaded.equal(original, context)
