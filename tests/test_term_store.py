"""Kernel terms round-trip through the relational term graph.

Proves the `theorems.pattern` JSONB blob can go (PR #23 follow-up): a
statement's kernel term is stored as shared `terms` / `term_children` rows,
reloaded from a fresh identity map, rebuilt into a live term that is `equal` to
the original and renders the identical surface string — and statement structure
is queryable in plain SQL (including transitively, via a recursive CTE) with no
JSON scans and no recompiling.
"""

import time
from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, aliased

from app.db import digest_term, store_term
from app.db.terms_mapping import prefetch_terms
from app.db.models import FormalSystem, Theorem
from app.db.terms import TermChildRow, TermRow
from tests.database import create_tables, database_url
from tests.spec_helpers import (
    brackets,
    conjunction_prod,
    defn,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import SystemSpec, build_spec
from website.logical.kernel import from_match


def zfc_spec() -> SystemSpec:
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod(),
                     universal_prod()],
        lines=[statement_line()],
        rules=[hyp_rule(), mp_rule()],
        definitions=[subset_def()],
    )


@pytest.fixture(scope="module")
def engine_context():
    result = build_spec(zfc_spec())
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    return context


@pytest.fixture
def session(tmp_path):
    url = database_url(tmp_path)
    create_tables(
        url,
        [
            FormalSystem.__table__,
            TermRow.__table__,
            TermChildRow.__table__,
            Theorem.__table__,
        ],
    )
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture
def system_row(session):
    row = FormalSystem(name="ZFC", slug="zfc")
    session.add(row)
    session.flush()
    return row


def term_of(context, formula_string):
    formula = context.variables["formula"]
    return from_match(formula.match(formula_string, context))


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
        # One interned child in *two* slots. The sweep's recursive CTE dedups its
        # rows, so it has to key on the slot as well as on the edge's endpoints —
        # keying on the endpoints alone would collapse these to one and lose a
        # slot, which reconstructs as a node missing half its children.
        "(x ∈ y → x ∈ y)",
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

    reloaded = prefetch_terms(session, [root_id]).term(root_id, engine_context)
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

    # "Which theorems use this defined shorthand?" — defined notation is a
    # production like any other, named `<sort>:<template>`, so it is an ordinary
    # `node` row found by constructor name.
    rows = session.scalars(
        select(Theorem.statement)
        .join(TermRow, Theorem.statement_term_id == TermRow.id)
        .where(TermRow.kind == "node", TermRow.constructor == "formula:x ⊆ y")
    ).all()
    assert rows == ["x ⊆ y"]

    # And "which use *any* defined shorthand?" — a node carries a `sort` only
    # when its constructor is not itself a member of the sort it inhabits, which
    # is exactly what a defined form is.
    rows = session.scalars(
        select(Theorem.statement)
        .join(TermRow, Theorem.statement_term_id == TermRow.id)
        .where(TermRow.kind == "node", TermRow.sort.is_not(None))
    ).all()
    assert rows == ["x ⊆ y"]


# ---------------------------------------------------------------------------
# Defined-node resolution disambiguates by sort
# ---------------------------------------------------------------------------

def ambiguous_spec() -> SystemSpec:
    # One higher template ("x ⋈ y") defined on two different sorts.
    return SystemSpec(
        name="DUP",
        brackets=brackets(),
        productions=[
            variable_prod(),
            template_prod("term", "pairing", "⟨s, t⟩", [("s", "term"), ("t", "term")]),
            membership_prod(),
            conjunction_prod(),
        ],
        lines=[statement_line()],
        rules=[hyp_rule()],
        definitions=[
            defn("formula", "both", "x ⋈ y", "(x ∈ y ∧ y ∈ x)",
                 [("x", "variable"), ("y", "variable")]),
            defn("term", "swap", "x ⋈ y", "⟨y, x⟩",
                 [("x", "variable"), ("y", "variable")]),
        ],
    )


def test_defined_nodes_reload_with_their_stored_sort(session):
    # One template ("x ⋈ y") defined on two sorts. They are two productions and
    # carry two names, `formula:x ⋈ y` and `term:x ⋈ y`, so resolution cannot
    # confuse them — the disambiguation the loader used to do by hand is now a
    # property of the name.
    result = build_spec(ambiguous_spec())
    assert "errors" not in result, result.get("errors")
    engine_system = result["system"]
    context = copy(engine_system.context)
    context.variables.update(engine_system.build_context.variables)
    formula = context.variables["formula"]

    as_formula = from_match(formula.match("x ⋈ y", context))
    as_term = from_match(formula.match("x ⋈ y ∈ z", context)).children["s"]
    assert (as_formula.sort.name, as_term.sort.name) == ("formula", "term")

    system = FormalSystem(name="DUP", slug="dup")
    ids = {}
    for label, term in (("formula", as_formula), ("term", as_term)):
        row = store_term(session, system, term)
        session.flush()
        ids[label] = row.id
    session.commit()
    session.expire_all()

    graph = prefetch_terms(session, list(ids.values()))
    for label, original in (("formula", as_formula), ("term", as_term)):
        reloaded = graph.term(ids[label], context)
        assert reloaded.sort.name == label
        assert reloaded.equal(original, context)


def test_prefetch_does_not_enumerate_paths_through_a_shared_dag(session):
    """The sweep must be linear in *nodes*, not in root-to-node paths.

    A term graph is a DAG with heavy sharing — that is what interning buys — so a
    recursive walk joined with `UNION ALL` enumerates every distinct path and is
    exponential in depth. Measured on this shape at depth 21: 4,194,302 rows
    against 21. The result set is identical either way, so nothing fails; it just
    gets slower the more sharing there is, in the function written to make
    loading cheap. Hence a shape whose path count is astronomical and a wall
    clock with an enormous margin, rather than an assertion on rows.
    """
    system = FormalSystem(name="Deep", slug="deep")
    session.add(system)
    session.flush()

    # A chain of `depth` nodes, each reaching the next by *two* slots: 2**depth
    # distinct paths from the root, `depth + 1` distinct nodes, and `2 * depth`
    # distinct edges — which is what the CTE dedups down to, since it carries the
    # slot. Both bounds are linear; only the path count is not.
    depth = 40
    nodes = [
        TermRow(formal_system=system, kind="node", constructor="c", digest=f"d{i}")
        for i in range(depth + 1)
    ]
    session.add_all(nodes)
    for i in range(depth):
        nodes[i].children.append(TermChildRow(slot="l", position=0, child=nodes[i + 1]))
        nodes[i].children.append(TermChildRow(slot="r", position=1, child=nodes[i + 1]))
    session.flush()

    started = time.monotonic()
    loaded = prefetch_terms(session, [nodes[0].id])
    elapsed = time.monotonic() - started

    assert loaded.ids == {node.id for node in nodes}
    # 2**40 paths would not finish this decade; the node walk is milliseconds.
    assert elapsed < 5
