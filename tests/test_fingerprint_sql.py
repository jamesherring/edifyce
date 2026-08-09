"""The SQL fingerprint filter agrees with the engine predicate, feature by feature.

`app.db.fingerprints._feature_condition` is the SQL image of
`website.logical.fingerprint.features_compatible` for a fixed query feature — the
query term is in hand, each stored term is a row. The recall contract of the whole
index rests on the two never disagreeing: a stored feature the engine calls
compatible must be one the database keeps, and vice versa. This enumerates every
feature pair over a representative alphabet and asserts exactly that, so a drift in
either direction fails here rather than as a silently missed citation.
"""

import json
import os

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import Column, Integer, String, Text, create_engine, make_url, select, true
from sqlalchemy.orm import Session, declarative_base

from app.db.fingerprints import (
    NUL_ESCAPE,
    NUL_SUB_ESCAPE,
    _feature_condition,
    encode,
    fingerprint_filter,
)
from website.logical.fingerprint import (
    ABSENT,
    BELOW_VAR,
    POSITIONS_KEY,
    VARIABLE,
    Fingerprint,
    features_compatible,
)

Base = declarative_base()


class _Feat(Base):
    __tablename__ = "feat"
    id = Column(Integer, primary_key=True)
    value = Column(String)


class _Stored(Base):
    __tablename__ = "stored_fp"
    id = Column(Integer, primary_key=True)
    conclusion_fingerprint = Column(Text)


def _backends():
    """(dialect name, engine URL) for every backend available to this run.

    SQLite always; Postgres when ``EDIFYCE_TEST_DATABASE_URL`` is set — the same
    opt-in `tests/database.py` uses. The JSON extraction in `fingerprint_filter`
    is the one place the two dialects need different SQL (`type_coerce` vs
    `cast`), so the Postgres path only has coverage when that variable points at a
    real database.
    """
    backends = [("sqlite", "sqlite://")]
    url = os.environ.get("EDIFYCE_TEST_DATABASE_URL")
    if url is not None:
        backends.append(
            ("postgresql", make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False))
        )
    return backends


# The markers, two distinct compound symbols, and a ground-leaf symbol — every
# shape `features_compatible` distinguishes, so the cross-product exercises each
# branch of its table (equal symbols, distinct symbols, symbol vs marker, ...).
ALPHABET = (
    VARIABLE,
    BELOW_VAR,
    ABSENT,
    "S\x1eimplication",
    "S\x1emembership",
    "L\x1esetvar\x1ea",
)


def test_the_sql_condition_matches_features_compatible():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            _Feat(id=index, value=value) for index, value in enumerate(ALPHABET)
        )
        session.flush()

        for query in ALPHABET:
            condition = _feature_condition(query, _Feat.value)
            # None means "no clause": a query variable-below position permits
            # everything, so the database keeps every row.
            kept = {
                row.value
                for row in session.execute(
                    select(_Feat.value).where(
                        true() if condition is None else condition
                    )
                )
            }
            expected = {
                stored
                for stored in ALPHABET
                if features_compatible(query, stored)
            }
            assert kept == expected, f"disagreement for query feature {query!r}"


# Realistic features, control characters and all, so the JSON round-trip and the
# dialect extraction are exercised on the shapes production actually stores.
_IMP = "S\x1estring\x1f(\x00 → \x00)"
_MEM = "S\x1estring\x1f\x00 ∈ \x00"
_OTHER = "S\x1estring\x1f(\x00 ⊃ \x00)"
_GOAL = Fingerprint(key=POSITIONS_KEY, features=(_IMP, _MEM, _MEM, VARIABLE, VARIABLE, VARIABLE, VARIABLE))


@pytest.mark.parametrize("dialect,url", _backends())
def test_fingerprint_filter_extracts_and_compares_per_dialect(dialect, url):
    # End to end through the JSON column: `fingerprint_filter` reads a stored
    # fingerprint position by position and compares it to the goal. This is the
    # only SQL that differs by dialect, and on Postgres — the deployment — it runs
    # against a real `json` cast rather than SQLite's text. Only when
    # EDIFYCE_TEST_DATABASE_URL is set does the Postgres row appear.
    engine = create_engine(url)
    Base.metadata.drop_all(engine, tables=[_Stored.__table__])
    Base.metadata.create_all(engine, tables=[_Stored.__table__])
    try:
        with Session(engine) as session:
            rows = {
                # Identical to the goal — compatible, kept.
                "match": encode(_GOAL),
                # A different symbol at position (0,) — pruned.
                "clash": encode(
                    Fingerprint(
                        key=POSITIONS_KEY,
                        features=(_IMP, _OTHER, _MEM, VARIABLE, VARIABLE, VARIABLE, VARIABLE),
                    )
                ),
                # Never re-indexed: kept, it cannot be compared.
                "null": None,
                # Written under a different position set: kept, its key no longer
                # matches, so it is not silently miscompared.
                "stale": encode(
                    Fingerprint(
                        key="stale-key",
                        features=(_IMP, _OTHER, _MEM, VARIABLE, VARIABLE, VARIABLE, VARIABLE),
                    )
                ),
            }
            order = {}
            for index, (label, value) in enumerate(rows.items()):
                session.add(_Stored(id=index, conclusion_fingerprint=value))
                order[index] = label
            session.flush()

            kept = {
                order[row_id]
                for row_id in session.scalars(
                    select(_Stored.id).where(
                        fingerprint_filter(_Stored.conclusion_fingerprint, _GOAL, dialect)
                    )
                )
            }
            assert kept == {"match", "null", "stale"}, dialect
    finally:
        Base.metadata.drop_all(engine, tables=[_Stored.__table__])
        engine.dispose()


def test_the_nul_migration_replace_matches_the_encoder():
    # The data migration `..._sanitize_fingerprint_nul.sql` rewrites a pre-NUL-safe
    # fingerprint with a text replace of the NUL escape. It must land on exactly
    # what `encode` now produces, or a migrated row and a freshly written one would
    # compare unequal. This pins the migration's substitution to the encoder's, so
    # they cannot drift apart.
    fp = Fingerprint(
        key="k",
        features=("S\x1estring\x1f(\x00 → \x00)", "A", "N", "B", "B", "N", "N"),
    )
    # Exactly what the storage PR's encoder wrote: raw features, `json.dumps`
    # escaping the NUL to its six-char unicode form.
    legacy = json.dumps([fp.key, list(fp.features)], ensure_ascii=False)
    migrated = legacy.replace(NUL_ESCAPE, NUL_SUB_ESCAPE)
    assert migrated == encode(fp)
