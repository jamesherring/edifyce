"""The library prefilter: narrowing a system's theorems to a goal's shape.

The query half of §9d. What is checked is that the constructor filter selects the
theorems it should and no others, that the α-digest orders an already-proved
statement first, that a rename does not make a related system's theorems
invisible, and — the one nobody would notice going wrong — that a theorem with no
cached conclusion term is *counted* rather than silently dropped.

Confirming a candidate by unification is the engine's, in tests/test_retrieval.py.
"""

import uuid
from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, store_term
from app.db.fingerprints import encode
from app.db.models import FormalSystem
from app.db.promoted_theorems import PromotedTheoremPremiseRow, PromotedTheoremRow
from app.db.promoted_theorems_mapping import LibraryChain, LibraryLayer
from app.db.retrieval import conclusion_candidates
from app.db.terms import TermChildRow, TermRow
from app.db.terms_mapping import alpha_digest
from website.logical.fingerprint import Fingerprint, compatible, fingerprint
from tests.spec_helpers import (
    brackets,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    statement_line,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import SystemSpec, build_spec
from website.logical.kernel import from_match
from website.logical.translation import Translation
from website.logical.wrapping import NO_TEMPLATE, StatementTemplate


def zfc_spec() -> SystemSpec:
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[
            variable_prod(),
            membership_prod(),
            implication_prod(),
            universal_prod(),
        ],
        lines=[statement_line()],
        rules=[hyp_rule(), mp_rule()],
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
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            FormalSystem.__table__,
            TermRow.__table__,
            TermChildRow.__table__,
            PromotedTheoremRow.__table__,
            PromotedTheoremPremiseRow.__table__,
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
    return from_match(formula.match(formula_string, context))


def add_theorem(
    session,
    system_row,
    context,
    label,
    statement,
    *,
    premises=(),
    store=True,
):
    """A promoted entry with its conclusion term cached, as a promotion writes it."""
    term_id = None
    conclusion_fingerprint = None
    if store:
        term = term_of(context, statement)
        stored = store_term(session, system_row, term)
        # The client-side uuid default lands at flush, not at construction — the
        # same flush `_term_id` does before it hands the id on.
        session.flush()
        term_id = stored.id
        # Written beside the cached term, present or absent together, as a
        # promotion does (`promoted_theorems_mapping.pattern_fingerprint`).
        conclusion_fingerprint = encode(fingerprint(term))
    row = PromotedTheoremRow(
        system_id=system_row.id,
        label=label,
        statement=statement,
        primitive=False,
        statement_term_id=term_id,
        conclusion_fingerprint=conclusion_fingerprint,
    )
    session.add(row)
    session.flush()
    for position, premise in enumerate(premises):
        session.add(
            PromotedTheoremPremiseRow(
                theorem_id=row.id, position=position, statement=premise
            )
        )
    session.flush()
    return row


def chain_of(system_row, translation=None, template=None):
    return LibraryChain(
        (
            LibraryLayer(
                system_row.id,
                "digest",
                translation=translation or Translation(),
                template=template or NO_TEMPLATE,
            ),
        )
    )


# ---------------------------------------------------------------------------
# The filter
# ---------------------------------------------------------------------------


def test_only_theorems_concluding_the_goals_production_are_offered(
    session, system_row, engine_context
):
    # The whole point: a goal that is an implication does not want the library's
    # memberships, and on a real corpus that is most of it.
    imp1 = add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    add_theorem(session, system_row, engine_context, "imp2", "(x ∈ z → x ∈ y)")
    add_theorem(session, system_row, engine_context, "mem1", "x ∈ y")

    found = conclusion_candidates(session, chain_of(system_row), "implication")

    assert [c.label for c in found.candidates] == ["imp1", "imp2"]
    assert found.matched == 2
    assert found.truncated is False
    # A candidate is point-at-able: it carries the interned root of its
    # conclusion, the handle `GET .../terms/{id}` walks — not just a string.
    assert found.candidates[0].statement_term_id == imp1.statement_term_id


def test_a_goal_no_theorem_concludes_finds_nothing(session, system_row, engine_context):
    add_theorem(session, system_row, engine_context, "mem1", "x ∈ y")

    found = conclusion_candidates(session, chain_of(system_row), "implication")

    assert found.candidates == ()
    assert found.matched == 0
    assert found.unindexed == 0


def test_premise_counts_come_back_with_the_candidate(
    session, system_row, engine_context
):
    # What a caller ranks by: a theorem with no premises can close a goal on its
    # own, and one with two needs two lines found for it first.
    add_theorem(session, system_row, engine_context, "ax1", "(x ∈ y → x ∈ z)")
    add_theorem(
        session,
        system_row,
        engine_context,
        "syl",
        "(x ∈ y → x ∈ z)",
        premises=["x ∈ y", "x ∈ z"],
    )

    found = conclusion_candidates(session, chain_of(system_row), "implication")

    assert {c.label: c.premise_count for c in found.candidates} == {"ax1": 0, "syl": 2}


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_an_already_proved_statement_sorts_first(session, system_row, engine_context):
    # `alpha_digest` covering the exact case for free: the goal is *this*
    # statement up to renaming, so it needs no instantiation and should be the
    # first thing a caller tries. The two differ by variable *sharing*, which α
    # preserves — differing only in which letters were picked would make them the
    # same statement, which is the whole point of the digest.
    add_theorem(session, system_row, engine_context, "aaa", "(x ∈ y → x ∈ y)")
    add_theorem(session, system_row, engine_context, "zzz", "(a ∈ b → a ∈ c)")

    goal = term_of(engine_context, "(p ∈ q → p ∈ r)")
    found = conclusion_candidates(
        session,
        chain_of(system_row),
        "implication",
        alpha_digest=alpha_digest(goal),
    )

    # "zzz" would lose on label order; it wins on being the α-identical one.
    assert [c.label for c in found.candidates] == ["zzz", "aaa"]
    assert [c.exact for c in found.candidates] == [True, False]


def test_the_limit_cuts_the_list_and_says_so(session, system_row, engine_context):
    for n in range(5):
        add_theorem(session, system_row, engine_context, f"imp{n}", "(x ∈ y → x ∈ z)")

    found = conclusion_candidates(session, chain_of(system_row), "implication", limit=2)

    assert len(found.candidates) == 2
    assert found.matched == 5
    assert found.truncated is True


def test_an_excluded_label_is_not_offered_again(session, system_row, engine_context):
    add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    add_theorem(session, system_row, engine_context, "imp2", "(x ∈ y → x ∈ z)")

    found = conclusion_candidates(
        session, chain_of(system_row), "implication", exclude=["imp1"]
    )

    assert [c.label for c in found.candidates] == ["imp2"]
    assert found.matched == 1


# ---------------------------------------------------------------------------
# What the filter cannot see
# ---------------------------------------------------------------------------


def test_a_theorem_with_no_cached_term_is_counted_not_hidden(
    session, system_row, engine_context
):
    # The false negative that would otherwise be invisible. A NULL statement term
    # is a cache miss, and retrieval is the one reader that cannot pay a re-parse
    # to recover from it — so it says how much of the library it could not see
    # rather than reporting a short list as a complete one.
    add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    add_theorem(
        session, system_row, engine_context, "lost", "(x ∈ y → x ∈ z)", store=False
    )

    found = conclusion_candidates(session, chain_of(system_row), "implication")

    assert [c.label for c in found.candidates] == ["imp1"]
    assert found.unindexed == 1


def test_a_renamed_layer_is_asked_about_its_own_spelling(
    session, system_row, engine_context
):
    # A related system may call the same production something else. Asking it
    # about the citing system's name would return nothing from exactly the edges
    # a rename exists to cross — a silent false negative rather than an error.
    add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    chain = chain_of(system_row, Translation(symbols={"implication": "imp"}))

    found = conclusion_candidates(session, chain, "imp")

    assert [c.label for c in found.candidates] == ["imp1"]
    assert found.asked == {system_row.id: "implication"}


def test_an_empty_chain_asks_nothing(session):
    found = conclusion_candidates(session, LibraryChain(()), "implication")

    assert found.candidates == ()
    assert found.matched == 0
    assert found.unindexed == 0


def test_a_renamed_away_production_is_not_asked_about(session, system_row, engine_context):
    # The false positive the inverse has to refuse. The layer *has* an
    # `implication` and calls it `imp` here, so this system's own `implication` —
    # if it has one — is something the layer does not supply. Falling back to the
    # identity would ask the layer about its `implication` and read the answers as
    # being about ours, which is a rename doing exactly the damage it prevents.
    add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    chain = chain_of(system_row, Translation(symbols={"implication": "imp"}))

    found = conclusion_candidates(session, chain, "implication")

    assert found.candidates == ()
    assert found.asked == {}
    assert found.unfiltered == 1


def test_a_restating_edge_is_counted_rather_than_answered_for(
    session, system_row, engine_context
):
    # A wrapped edge gives its theorems a conclusion here whose root is the
    # template's (`Γ ⊢ φ`), while the stored row's root is the source statement's.
    # Filtering by the goal's production matches none of them — so the honest
    # answer is "there is a layer I could not ask", not a confident empty list.
    add_theorem(session, system_row, engine_context, "imp1", "(x ∈ y → x ∈ z)")
    chain = chain_of(system_row, template=StatementTemplate(text="{Γ} ⊢ {0}"))

    found = conclusion_candidates(session, chain, "implication")

    assert found.candidates == ()
    assert found.unfiltered == 1
    assert found.asked == {}


def test_a_label_a_nearer_layer_shadows_is_not_offered(session, engine_context):
    # A citation resolves to the nearest layer that has the label, so a shadowed
    # ancestor entry is not the theorem anyone would reach by naming it. Offering
    # it would spend a `limit` slot on a name that means something else — and
    # could lend its α-digest to the theorem a caller actually gets.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            FormalSystem.__table__,
            TermRow.__table__,
            TermChildRow.__table__,
            PromotedTheoremRow.__table__,
            PromotedTheoremPremiseRow.__table__,
        ],
    )
    with Session(engine) as session:
        child = FormalSystem(name="Child", slug="child")
        parent = FormalSystem(name="Parent", slug="parent")
        session.add_all([child, parent])
        session.flush()
        add_theorem(session, child, engine_context, "id", "(x ∈ y → x ∈ y)")
        add_theorem(session, parent, engine_context, "id", "(a ∈ b → a ∈ c)")
        add_theorem(session, parent, engine_context, "other", "(a ∈ b → a ∈ c)")
        # Nearest first, as an inheritance chain is read.
        chain = LibraryChain(
            (LibraryLayer(child.id, "d"), LibraryLayer(parent.id, "d"))
        )

        found = conclusion_candidates(session, chain, "implication")

        labels = [(c.label, c.system_id) for c in found.candidates]
        assert labels == [("id", child.id), ("other", parent.id)]
        assert found.matched == 2


# ---------------------------------------------------------------------------
# The fingerprint: narrowing below the root
# ---------------------------------------------------------------------------


def test_the_fingerprint_prunes_a_shared_head_that_cannot_unify(
    session, system_row, engine_context
):
    # Both conclusions are implications, so the head filter keeps both. Only the
    # fingerprint sees that the goal's left side is a membership while `nested`'s is
    # itself an implication — a position the unifier would reject too. (Leaves in
    # this grammar are ground tokens, so `flat` shares the goal's spelling to stay
    # unifiable; the distinguishing structure is the nesting, not the letters.)
    add_theorem(session, system_row, engine_context, "flat", "(a ∈ b → a ∈ c)")
    add_theorem(
        session, system_row, engine_context, "nested", "((a ∈ b → a ∈ c) → a ∈ b)"
    )
    goal = fingerprint(term_of(engine_context, "(a ∈ b → a ∈ c)"))

    # The head filter alone keeps both — the baseline the fingerprint improves on.
    head_only = conclusion_candidates(session, chain_of(system_row), "implication")
    assert {c.label for c in head_only.candidates} == {"flat", "nested"}

    narrowed = conclusion_candidates(
        session, chain_of(system_row), "implication", goal_fingerprint=goal
    )
    assert [c.label for c in narrowed.candidates] == ["flat"]
    assert narrowed.matched == 1


def test_the_fingerprint_filter_matches_the_engine_predicate(
    session, system_row, engine_context
):
    # The recall contract, against the engine as oracle: the rows the database
    # keeps are exactly the implication-headed theorems whose stored fingerprint
    # `compatible` accepts. A divergence here is either a dropped real match (a
    # recall bug) or a kept impossible one (the SQL disagreeing with the engine).
    corpus = {
        "flat": "(a ∈ b → a ∈ c)",
        "nested_left": "((a ∈ b → a ∈ c) → a ∈ b)",
        "nested_right": "(a ∈ b → (a ∈ c → a ∈ b))",
        "both_members": "(a ∈ b → a ∈ b)",
        "member": "a ∈ b",  # not an implication — the head filter drops it
    }
    for label, statement in corpus.items():
        add_theorem(session, system_row, engine_context, label, statement)

    # Shares the corpus's ground tokens so the match is decided by structure, not
    # by the letters — otherwise a token mismatch would prune everything.
    goal_term = term_of(engine_context, "(a ∈ b → (a ∈ c → a ∈ b))")
    goal = fingerprint(goal_term)

    expected = {
        label
        for label, statement in corpus.items()
        if statement.startswith("(")  # implication-headed, as the head filter asks
        and compatible(goal, fingerprint(term_of(engine_context, statement)))
    }

    found = conclusion_candidates(
        session, chain_of(system_row), "implication", goal_fingerprint=goal
    )
    assert {c.label for c in found.candidates} == expected
    # And the filter actually did something — this goal is not vacuous.
    assert expected != {"flat", "nested_left", "nested_right", "both_members"}


def test_a_theorem_without_a_stored_fingerprint_is_kept(
    session, system_row, engine_context
):
    # A NULL fingerprint is the "not re-indexed yet" state — it cannot be compared,
    # so it must fall through to the head filter rather than be dropped. Its shape
    # would otherwise be pruned by this goal, which is what makes the fallback
    # visible.
    row = add_theorem(
        session, system_row, engine_context, "nested", "((a ∈ b → a ∈ c) → a ∈ b)"
    )
    row.conclusion_fingerprint = None
    session.flush()
    goal = fingerprint(term_of(engine_context, "(a ∈ b → a ∈ c)"))

    found = conclusion_candidates(
        session, chain_of(system_row), "implication", goal_fingerprint=goal
    )
    assert [c.label for c in found.candidates] == ["nested"]


def test_a_fingerprint_from_a_different_position_set_is_kept(
    session, system_row, engine_context
):
    # A fingerprint written under a different FINGERPRINT_POSITIONS cannot be read
    # against the current one — the engine `compatible` raises on that key
    # mismatch. The filter must keep such a row (fall back to the head filter),
    # never silently compare it against positions it does not describe.
    row = add_theorem(
        session, system_row, engine_context, "nested", "((a ∈ b → a ∈ c) → a ∈ b)"
    )
    stale = fingerprint(term_of(engine_context, "((a ∈ b → a ∈ c) → a ∈ b)"))
    row.conclusion_fingerprint = encode(Fingerprint(key="stale-key", features=stale.features))
    session.flush()
    goal = fingerprint(term_of(engine_context, "(a ∈ b → a ∈ c)"))

    found = conclusion_candidates(
        session, chain_of(system_row), "implication", goal_fingerprint=goal
    )
    assert [c.label for c in found.candidates] == ["nested"]
