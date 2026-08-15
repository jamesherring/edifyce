"""Persisting a promoted theorem's conclusion fingerprint.

The engine computes a fingerprint from a term (tested in test_fingerprint.py);
this pins the storage half — that `store_theorem` writes the conclusion's
fingerprint, that it decodes back to what the engine computes, and that it is
present exactly when the cached conclusion term is (so a theorem is "indexed" for
retrieval consistently). See docs/search-phase1-fingerprint.md.
"""

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system
from app.db.fingerprints import decode, encode, pattern_fingerprint
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.promoted_theorems_mapping import store_theorem, theorem_digest
from tests.spec_helpers import brackets, regex_prod, statement_line, template_prod, rule
from tests.test_proofs_api import _TABLES
from website.logical.declarative import SystemSpec, build_spec
from website.logical.fingerprint import Fingerprint, fingerprint
from website.logical.promotion import TheoremSpec, promote_spec


def _spec():
    return SystemSpec(
        name="Prop",
        brackets=brackets(),
        productions=[
            regex_prod("formula", "atom", "[a-z]"),
            template_prod(
                "formula", "implication", "(p -> q)",
                [("p", "formula"), ("q", "formula")],
            ),
        ],
        lines=[statement_line()],
        rules=[rule("MP", "mp", ["p", "(p -> q)"], "q",
                    [("p", "formula"), ("q", "formula")])],
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_encode_decode_round_trips():
    fp = Fingerprint(key="deadbeef", features=("S\x1eimplication", "A", "B", "N"))
    assert decode(encode(fp)) == fp


def test_pattern_fingerprint_is_none_without_a_composed_term():
    # A bare grammar pattern (not a StringPattern with a schema_term) carries no
    # term — the same case that leaves statement_term_id NULL.
    assert pattern_fingerprint(None) is None


# ---------------------------------------------------------------------------
# store_theorem writes the fingerprint
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    with Session(engine) as session:
        yield session


@pytest.fixture
def built():
    result = build_spec(_spec())
    assert "errors" not in result, result.get("errors")
    return result["system"]


def _stored(session, system_row, built, spec):
    promoted = promote_spec(built, spec)
    row = store_theorem(
        session, system_row, spec, {s.name: s for s in system_row.symbols},
        position=0, primitive=False, digest=theorem_digest("lib", spec),
        promoted=promoted,
    )
    session.flush()
    return promoted, row


def test_store_theorem_persists_the_conclusion_fingerprint(session, built):
    system_row = spec_to_system(_spec())
    session.add(system_row)
    session.flush()

    spec = TheoremSpec(label="id", statement="(a -> a)",
                       metavariables={"a": "formula"})
    promoted, row = _stored(session, system_row, built, spec)

    assert row.conclusion_fingerprint is not None
    # It is exactly what the engine computes from the conclusion term.
    assert decode(row.conclusion_fingerprint) == fingerprint(promoted.deduction.schema_term)
    # The whole point: a real, structured head, not a bare marker.
    assert decode(row.conclusion_fingerprint).features[0].startswith("S\x1e")


def test_the_fingerprint_is_present_iff_the_cached_term_is(session, built):
    # A bare-metavariable conclusion composes no term, so it caches neither a
    # statement_term_id nor a fingerprint — a theorem is indexed for retrieval
    # consistently, or not at all.
    system_row = spec_to_system(_spec())
    session.add(system_row)
    session.flush()

    bare = TheoremSpec(label="triv", statement="q",
                       metavariables={"q": "formula"})
    promoted, row = _stored(session, system_row, built, bare)

    assert promoted.deduction.schema_term is None
    assert row.statement_term_id is None
    assert row.conclusion_fingerprint is None


def test_the_stored_fingerprint_survives_a_commit_and_reload(session, built):
    system_row = spec_to_system(_spec())
    session.add(system_row)
    session.flush()
    spec = TheoremSpec(label="id", statement="(a -> a)",
                       metavariables={"a": "formula"})
    _stored(session, system_row, built, spec)
    session.commit()
    session.expunge_all()

    reloaded = session.scalar(
        select(PromotedTheoremRow).where(PromotedTheoremRow.label == "id")
    )
    assert decode(reloaded.conclusion_fingerprint).key == fingerprint(
        promote_spec(built, spec).deduction.schema_term
    ).key
