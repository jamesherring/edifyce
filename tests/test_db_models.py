"""Schema-shape guards for the persistence layer.

These assert the model metadata without touching a database, so they run in the
same offline suite as everything else. They exist to catch accidental renames or
dropped columns/indexes that would silently desync the schema from Atlas.
"""

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pgvector")

from app.db import Base, EMBEDDING_DIMENSIONS


def test_expected_tables_present():
    assert set(Base.metadata.tables) == {
        "users",
        "formal_systems",
        "proof_folders",
        "proofs",
        "proof_references",
        "theorems",
    }


def test_formal_system_self_inheritance_fk():
    fks = Base.metadata.tables["formal_systems"].foreign_keys
    targets = {fk.column.table.name for fk in fks}
    # Inherits-from is a self-reference; owner points at users.
    assert "formal_systems" in targets
    assert "users" in targets


def test_theorem_search_columns_and_indexes():
    theorems = Base.metadata.tables["theorems"]
    assert "pattern" in theorems.c  # structural / pattern search (GIN)
    assert "embedding" in theorems.c  # semantic / AI search (HNSW)

    methods = {
        idx.name: idx.dialect_options["postgresql"].get("using")
        for idx in theorems.indexes
        if "postgresql" in idx.dialect_options
    }
    assert methods.get("ix_theorems_pattern") == "gin"
    assert methods.get("ix_theorems_embedding") == "hnsw"


def test_embedding_dimension_is_positive():
    assert EMBEDDING_DIMENSIONS > 0
