"""The α-digest: structural identity up to consistent free-variable renaming.

`digest_term` keys a term by its exact structure *including* variable names, so
`a ∈ b` and `y ∈ z` are different rows. `alpha_digest` numbers every free
variable by first occurrence, so those two share one digest — the substrate for
"find me this statement up to what the variables are called" search — while
still telling `a ∈ a` (shared variable) apart from `a ∈ b`.

The pure-function tests pin the invariance directly; the storage tests show the
payoff: α-equivalent statements land in one bucket, addressable by a plain
indexed-column lookup, without merging their exact (faithfully-named) rows.
"""

from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import alpha_digest, digest_term, store_term
from app.db.base import Base
from app.db.models import FormalSystem
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
def context():
    result = build(SOURCE)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    ctx = copy(system.context)
    ctx.variables.update(system.build_context.variables)
    return ctx


def term_of(context, formula_string):
    formula = context.variables["formula"]
    return from_match(formula.match(formula_string, context), context)


def alpha_of(context, formula_string):
    return alpha_digest(term_of(context, formula_string))


# ---------------------------------------------------------------------------
# Pure-function invariance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x ∈ y", "a ∈ b"),                                  # leaves only
        ("(x ∈ y → x ∈ z)", "(a ∈ b → a ∈ c)"),              # compound, shared lhs
        ("∀z (z ∈ x → z ∈ y)", "∀w (w ∈ a → w ∈ b)"),        # binder + body
        ("x ⊆ y", "a ⊆ b"),                                  # defined notation
    ],
)
def test_alpha_digest_is_invariant_under_renaming(context, left, right):
    assert alpha_of(context, left) == alpha_of(context, right)
    # ...and this is a real relaxation: the exact digests genuinely differ.
    assert digest_term(term_of(context, left)) != digest_term(term_of(context, right))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x ∈ y", "x ∈ x"),                       # distinct vs shared variable
        ("(x ∈ y → x ∈ z)", "(x ∈ y → x ∈ x)"),   # sharing across a compound
        ("x ⊆ y", "x ⊆ x"),                       # sharing under defined notation
    ],
)
def test_alpha_digest_preserves_variable_sharing(context, left, right):
    # Renaming-invariance must not blur *which* positions hold the same variable.
    assert alpha_of(context, left) != alpha_of(context, right)


def test_alpha_digest_distinguishes_structure(context):
    assert alpha_of(context, "x ∈ y") != alpha_of(context, "(x ∈ y → x ∈ z)")
    assert alpha_of(context, "(x ∈ y → x ∈ z)") != alpha_of(context, "∀z (z ∈ x → z ∈ y)")


def test_alpha_digest_is_deterministic(context):
    assert alpha_of(context, "(x ∈ y → x ∈ z)") == alpha_of(context, "(x ∈ y → x ∈ z)")


# ---------------------------------------------------------------------------
# Storage: the search-up-to-renaming payoff
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[FormalSystem.__table__, TermRow.__table__, TermChildRow.__table__],
    )
    with Session(engine) as session:
        yield session


@pytest.fixture
def system_row(session):
    row = FormalSystem(name="ZFC", slug="zfc")
    session.add(row)
    session.flush()
    return row


def test_stored_roots_share_alpha_but_not_exact_digest(session, system_row, context):
    a = store_term(session, system_row, term_of(context, "(x ∈ y → x ∈ z)"))
    b = store_term(session, system_row, term_of(context, "(a ∈ b → a ∈ c)"))
    session.commit()

    assert a.alpha_digest == b.alpha_digest      # same α-class...
    assert a.digest != b.digest                  # ...but distinct exact rows
    assert a.id != b.id


def test_search_statements_up_to_renaming(session, system_row, context):
    # Three statements: two are the same modulo variable names, one differs by
    # variable *sharing* and so must not match.
    renamings = ["(x ∈ y → x ∈ z)", "(a ∈ b → a ∈ c)"]
    other = "(x ∈ y → x ∈ x)"
    roots = {s: store_term(session, system_row, term_of(context, s)) for s in [*renamings, other]}
    session.commit()

    # "Find everything α-equivalent to this query" — one indexed-column lookup.
    query_alpha = alpha_of(context, "(p ∈ q → p ∈ r)")
    hits = session.scalars(
        select(TermRow.digest).where(
            TermRow.formal_system_id == system_row.id,
            TermRow.alpha_digest == query_alpha,
        )
    ).all()

    assert set(hits) == {roots[s].digest for s in renamings}
    assert roots[other].digest not in hits


def test_alpha_digest_buckets_group_the_corpus(session, system_row, context):
    for statement in ["x ∈ y", "a ∈ b", "p ∈ q", "x ∈ x"]:
        store_term(session, system_row, term_of(context, statement))
    session.commit()

    # The three renamings of "· ∈ ·" collapse to one α-bucket of membership
    # roots; "x ∈ x" is its own bucket. (Counts are over root membership rows.)
    counts = dict(
        session.execute(
            select(TermRow.alpha_digest, func.count())
            .where(TermRow.constructor == "membership")
            .group_by(TermRow.alpha_digest)
        ).all()
    )
    assert sorted(counts.values()) == [1, 3]
