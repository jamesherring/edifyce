"""The SQL fingerprint filter agrees with the engine predicate, feature by feature.

`app.db.fingerprints._feature_condition` is the SQL image of
`website.logical.fingerprint.features_compatible` for a fixed query feature — the
query term is in hand, each stored term is a row. The recall contract of the whole
index rests on the two never disagreeing: a stored feature the engine calls
compatible must be one the database keeps, and vice versa. This enumerates every
feature pair over a representative alphabet and asserts exactly that, so a drift in
either direction fails here rather than as a silently missed citation.
"""

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import Column, Integer, String, create_engine, select, true
from sqlalchemy.orm import Session, declarative_base

from app.db.fingerprints import _feature_condition
from website.logical.fingerprint import (
    ABSENT,
    BELOW_VAR,
    VARIABLE,
    features_compatible,
)

Base = declarative_base()


class _Feat(Base):
    __tablename__ = "feat"
    id = Column(Integer, primary_key=True)
    value = Column(String)


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
