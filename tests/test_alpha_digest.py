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
from app.db.terms_mapping import _free_identity
from tests.spec_helpers import (
    brackets,
    equality_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    regex_prod,
    statement_line,
    subset_def,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import SystemSpec, build_spec
from website.logical.kernel import Bound, Node, Var, from_match, intern
from website.logical.matching.patterns import AtomPattern

def zfc_spec() -> SystemSpec:
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod(),
                     universal_prod()],
        line=statement_line(),
        rules=[hyp_rule(), mp_rule()],
        definitions=[subset_def()],
    )


@pytest.fixture(scope="module")
def context():
    result = build_spec(zfc_spec())
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
# Term-kind coverage: schematic Var, abstract Bound, constant atom
# (from_match of these ZFC statements only yields regex-leaf object variables,
# so the Var / Bound / constant branches need directly-built kernel terms).
# ---------------------------------------------------------------------------


def test_alpha_digest_renames_schematic_vars(context):
    impl = context.variables["implication"]
    formula = context.variables["formula"]
    t1 = intern(Node(impl, {"p": Var("p", formula), "q": Var("q", formula)}))
    t2 = intern(Node(impl, {"p": Var("m", formula), "q": Var("n", formula)}))
    assert alpha_digest(t1) == alpha_digest(t2)                      # renamed → same
    shared = intern(Node(impl, {"p": Var("p", formula), "q": Var("p", formula)}))
    assert alpha_digest(shared) != alpha_digest(t1)                  # (p → p) differs


def test_alpha_digest_treats_bound_by_index(context):
    membership = context.variables["membership"]
    term_sort = context.variables["term"]
    b0, b1 = Bound(0, term_sort), Bound(1, term_sort)
    same = intern(Node(membership, {"s": b0, "t": b0}))              # [0] ∈ [0]
    diff = intern(Node(membership, {"s": b0, "t": b1}))              # [0] ∈ [1]
    assert alpha_digest(same) != alpha_digest(diff)
    # A Bound is index-canonical, not a renameable free variable.
    assert _free_identity(b0) is None


def test_alpha_digest_does_not_rename_constant_atoms(context):
    impl = context.variables["implication"]
    top = Node(AtomPattern(name="top", value="⊤"), literal="⊤")
    bot = Node(AtomPattern(name="bot", value="⊥"), literal="⊥")
    # Two distinct constants are fixed structure: swapping them is a real change
    # (contrast two variables, where the swap would be α-equivalent).
    t1 = intern(Node(impl, {"p": top, "q": bot}))
    t2 = intern(Node(impl, {"p": bot, "q": top}))
    assert alpha_digest(t1) != alpha_digest(t2)
    assert _free_identity(top) is None


# ---------------------------------------------------------------------------
# is_free override: constant-denoting regex productions (finding #2)
# ---------------------------------------------------------------------------

def numeral_spec() -> SystemSpec:
    return SystemSpec(
        name="PA",
        productions=[regex_prod("term", "numeral", "[0-9]+"), variable_prod(),
                     equality_prod()],
        line=statement_line(),
        rules=[hyp_rule()],
    )


@pytest.fixture(scope="module")
def numeral_context():
    result = build_spec(numeral_spec())
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    ctx = copy(system.context)
    ctx.variables.update(system.build_context.variables)
    return ctx


def test_default_heuristic_treats_numerals_as_variables(numeral_context):
    # The documented limitation: a `matches [0-9]+` production is renamed like a
    # variable, so distinct numerals collapse into one α-bucket.
    assert alpha_of(numeral_context, "2 = 5") == alpha_of(numeral_context, "7 = 9")


def test_is_free_override_excludes_constant_like_leaves(numeral_context):
    def numerals_are_constants(term):
        identity = _free_identity(term)
        if identity is not None and identity[:2] == ("leaf", "numeral"):
            return None  # a numeral is a constant, not a renameable variable
        return identity

    two_five = term_of(numeral_context, "2 = 5")
    seven_nine = term_of(numeral_context, "7 = 9")
    # Under the override the distinct numerals stay distinct...
    assert alpha_digest(two_five, numerals_are_constants) != alpha_digest(
        seven_nine, numerals_are_constants
    )
    # ...while genuine variables are still renamed.
    assert alpha_digest(term_of(numeral_context, "a = b"), numerals_are_constants) == \
        alpha_digest(term_of(numeral_context, "c = d"), numerals_are_constants)


# ---------------------------------------------------------------------------
# Shared-DAG regression: memoisation must keep this linear, not exponential
# ---------------------------------------------------------------------------


def _shared_tower(base, impl, depth):
    # A balanced shared DAG: each level's two children are the *same* object, so
    # `depth` levels are 2**depth leaves structurally but only depth+base nodes.
    # Built with raw Node (not intern, which is itself un-memoised and would
    # rebuild exponentially) so only alpha_digest's memoisation is under test.
    node = base
    for _ in range(depth):
        node = Node(impl, {"p": node, "q": node})
    return node


def test_alpha_digest_handles_shared_dag_without_blowup(context):
    impl = context.variables["implication"]
    # 2**30 leaves structurally; without DAG memoisation the walk would be 2**30
    # steps and never return, so simply completing is the assertion.
    node = _shared_tower(term_of(context, "x ∈ y"), impl, 30)
    digest = alpha_digest(node)
    assert isinstance(digest, str) and len(digest) == 64
    # Correctness survives the sharing: the same shape with renamed leaves matches.
    renamed = _shared_tower(term_of(context, "a ∈ b"), impl, 30)
    assert alpha_digest(node) == alpha_digest(renamed)


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
