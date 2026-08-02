"""A proviso's *term arguments* come back from rows rather than from a parse.

The last text-to-term derivation on the build path. A proviso is a closed
vocabulary over the owner's metavariables, and all of that is already rows — but
an argument that is not a declared metavariable is a term expression parsed
against the grammar (``equal(t, ∅)``), and it may use defined notation. That one
parse is what ``app/db/proviso_terms.py`` stores.

Two things distinguish it from the other two caches, and both are what these
tests are mostly about:

* **The stored term is the raw parse, before abstraction.** Abstraction depends
  on the *owner's* metavariables, the parse only on the grammar — so one cache
  serves a rule and a definition alike. A store made after abstraction would hand
  one owner's ``Var``s to another.
* **The digest is the definition block's, not the owner's.** A rule's own
  ``schema_digest`` cannot serve, because a rule's proviso may name defined
  notation and that digest does not cover the definitions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system
from app.db.models import FormalSystem, OAuthAccount, Proof, ProofFolder, Theorem, User
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.proviso_terms import load_proviso_terms, store_proviso_terms
from app.db.side_conditions import SideConditionRow
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
    ProductionBindingScopeRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.db.systems_mapping import system_to_spec
from app.db.terms import TermChildRow, TermRow
from tests.database import enable_foreign_keys
from tests.spec_helpers import (
    brackets,
    defn,
    regex_prod,
    rule,
    statement_line,
    template_prod,
)
import website.logical.formal_system.side_condition_syntax as syntax_module
from website.logical.declarative import SystemSpec, build_spec

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

_TABLES = [
    model.__table__
    for model in (
        User, OAuthAccount,
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow,
        RuleRow, RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, Theorem, TermRow, TermChildRow,
        ProofLineRow, ProofLineAntecedentRow,
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
    )
]


def defined_argument_spec() -> SystemSpec:
    """A rule *and* a definition whose provisos both name the defined `∅`.

    Two owners on one argument text is the point: the cache is keyed by the text
    and shared, so this is what says a rule and a definition can both be served
    from one stored term — and that neither gets the other's abstraction.
    """
    return SystemSpec(
        name="DefArg",
        brackets=brackets(),
        productions=[
            regex_prod("term", "variable", "[a-z]"),
            template_prod("term", "zero", "0", [], denotes_constant=True),
            template_prod("formula", "pred", "P(t)", [("t", "term")]),
            template_prod("formula", "implication", "(p → q)",
                          [("p", "formula"), ("q", "formula")]),
        ],
        lines=[statement_line()],
        definitions=[
            defn("term", "emptyset", "∅", "0", []),
            defn("formula", "empty_pred", "E(t)", "P(t)", [("t", "term")],
                 provisos=["equal(t, ∅)"], label="dfE"),
        ],
        rules=[rule("RE", "re", [], "P(t)", [("t", "term")], ["equal(t, ∅)"])],
    )


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://")
    enable_foreign_keys(engine)
    Base.metadata.create_all(engine, tables=_TABLES)
    return engine


def _store(engine: Engine, spec: SystemSpec) -> int:
    """Store ``spec``, build it cold, and write back the terms that build parsed."""
    with Session(engine) as session:
        row = spec_to_system(spec)
        session.add(row)
        session.flush()
        spec_now = system_to_spec(row)
        built = build_spec(spec_now)["system"]
        written = store_proviso_terms(session, row, built, spec_now)
        session.commit()
        return written


def _rebuild(engine: Engine):
    """Build the stored system *through* the cache."""
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec = system_to_spec(row)
        source = load_proviso_terms(session, row, spec)
        return build_spec(spec, proviso_terms=source)["system"], source


def _conditions(system) -> list[str]:
    """Every proviso the built system carries, rule and definition alike."""
    return [repr(d.condition) for d in system.definitions if d.condition is not None] + [
        repr(c) for r in system.inference_rules for c in r.side_conditions
    ]


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


def test_a_cached_build_produces_the_same_provisos(engine: Engine) -> None:
    spec = defined_argument_spec()
    cold = build_spec(spec)["system"]
    _store(engine, spec)
    warm, _source = _rebuild(engine)
    assert _conditions(warm) == _conditions(cold)


def test_a_served_argument_is_not_parsed_at_all(engine: Engine, monkeypatch) -> None:
    # Agreement alone would pass for a build that read the cache and discarded it.
    # `_parse_term` is the only place a proviso reads the grammar; poison it and
    # require the warm build to succeed anyway.
    _store(engine, defined_argument_spec())

    def exploding(*args: object, **kwargs: object) -> None:
        raise AssertionError("a proviso argument was parsed despite a stored term")

    monkeypatch.setattr(syntax_module, "_parse_term", exploding)
    warm, _source = _rebuild(engine)
    assert len(_conditions(warm)) == 2, "the definition's proviso and the rule's"


def test_the_cached_proviso_still_gates_proofs(engine: Engine) -> None:
    # The verdict, not just the shape: `∅` satisfies `equal(t, ∅)` and a variable
    # does not. A wrongly-served term would show up here and nowhere else.
    _store(engine, defined_argument_spec())
    warm, _source = _rebuild(engine)
    assert warm.parse("P(∅) [RE]").valid is True
    assert warm.parse("P(a) [RE]").valid is False


def test_one_stored_term_serves_both_owners(engine: Engine) -> None:
    # The rule and the definition share the argument text `∅`, so the cache holds
    # it once — and each owner abstracts it against its *own* metavariables on the
    # way out. That is why the stored term is the raw parse.
    _store(engine, defined_argument_spec())
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        stored = [
            node
            for node in session.scalars(select(SideConditionRow))
            if node.right_is_term
        ]
        assert len(stored) == 2, "one proviso node per owner"
        assert {node.right_name for node in stored} == {"∅"}
        # Interned, so both point at the same row.
        assert len({node.right_term_id for node in stored}) == 1
        assert all(node.term_digest is not None for node in stored)
        assert row is not None


# ---------------------------------------------------------------------------
# Inertness and the cache's contract
# ---------------------------------------------------------------------------


def test_the_same_argument_parsing_differently_is_not_believed(engine: Engine) -> None:
    # The case the digest exists for, and the only one that needs it. The cache is
    # keyed by the argument's *text*, so most staleness is self-guarding: change
    # the text and the lookup misses by key. What the digest catches is the text
    # staying put while what it parses *to* moves — here `∅` stops being defined
    # notation and becomes an ordinary production, so `equal(t, ∅)` reads the same
    # and means a different constructor.
    _store(engine, defined_argument_spec())

    edited = defined_argument_spec()
    edited.definitions = [d for d in edited.definitions if d.name != "emptyset"]
    edited.productions = [
        *edited.productions,
        template_prod("term", "empty", "∅", [], denotes_constant=True),
    ]

    cold = build_spec(edited)["system"]
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        source = load_proviso_terms(session, row, edited)
        warm = build_spec(edited, proviso_terms=source)["system"]

    # Both must read the *production*, not the notation the rows still describe.
    assert _conditions(warm) == _conditions(cold)
    assert all("term:∅" not in condition for condition in _conditions(warm))


def test_storing_is_idempotent(engine: Engine) -> None:
    spec = defined_argument_spec()
    assert _store(engine, spec) > 0
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        source = load_proviso_terms(session, row, spec_now)
        built = build_spec(spec_now, proviso_terms=source)["system"]
        # A warm build derives nothing, so there is nothing to write.
        assert built.proviso_terms.derived == {}
        assert store_proviso_terms(session, row, built, spec_now) == 0


def test_a_metavariable_argument_stores_no_term(engine: Engine) -> None:
    # `occurs(x, p)` names two metavariables, which stay bare names resolved
    # against the match binding — there is no term, and no row should claim one.
    spec = SystemSpec(
        name="NoTerms",
        brackets=brackets(),
        productions=[
            regex_prod("term", "variable", "[a-z]"),
            template_prod("formula", "pred", "P(t)", [("t", "term")]),
        ],
        lines=[statement_line()],
        rules=[rule("R", "r", [], "P(t)", [("t", "term")], ["atom(t, term)"])],
    )
    assert _store(engine, spec) == 0
    with Session(engine) as session:
        for node in session.scalars(select(SideConditionRow)):
            assert node.left_term_id is None and node.right_term_id is None
            assert node.term_digest is None


def test_a_deleted_term_costs_a_re_parse_and_not_a_proviso(engine: Engine) -> None:
    # SET NULL, so sweeping the term must leave the proviso row intact and merely
    # unserved — and the next store must fill the hole rather than skip on the
    # digest alone.
    _store(engine, defined_argument_spec())
    with Session(engine) as session:
        target = session.scalars(
            select(SideConditionRow.right_term_id).where(
                SideConditionRow.right_term_id.is_not(None)
            )
        ).first()
        session.execute(sa_delete(TermChildRow).where(TermChildRow.parent_id == target))
        session.execute(sa_delete(TermRow).where(TermRow.id == target))
        session.commit()

        rows = list(session.scalars(select(SideConditionRow)))
        assert any(r.right_is_term and r.right_term_id is None for r in rows)

    warm, _source = _rebuild(engine)
    assert _conditions(warm) == _conditions(build_spec(defined_argument_spec())["system"])

    # And it heals.
    assert _store_again(engine) > 0


def _store_again(engine: Engine) -> int:
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        source = load_proviso_terms(session, row, spec_now)
        built = build_spec(spec_now, proviso_terms=source)["system"]
        written = store_proviso_terms(session, row, built, spec_now)
        session.commit()
        return written
