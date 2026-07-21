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
        # App/account + proof surface.
        "users",
        "oauth_accounts",
        "formal_systems",
        "proof_folders",
        "proofs",
        "proof_references",
        "theorems",
        # Normalised system decomposition (canonical grammar/rules/definitions).
        "notation_brackets",
        "sorts",
        "productions",
        "production_bindings",
        "line_types",
        "line_parts",
        "definitions",
        "definition_bindings",
        "axioms",
        "axiom_bindings",
        "rules",
        "rule_antecedents",
        "rule_bindings",
        # Term graph (canonical statement structure for theorems).
        "terms",
        "term_children",
    }


def test_formal_systems_has_no_source_or_compiled_blob():
    # PR #23 follow-up: the normalised rows are canonical; the opaque source text
    # and compiled JSONB blob are gone.
    cols = set(Base.metadata.tables["formal_systems"].c.keys())
    assert "source" not in cols
    assert "compiled" not in cols


def test_users_table_is_fastapi_users_shaped():
    users = Base.metadata.tables["users"]
    # Columns fastapi-users' base contributes, plus our custom display_name.
    assert {
        "id",
        "email",
        "hashed_password",
        "is_active",
        "is_superuser",
        "is_verified",
        "display_name",
    } <= set(users.c.keys())


def test_oauth_accounts_links_to_users():
    oauth = Base.metadata.tables["oauth_accounts"]
    assert {"oauth_name", "account_id", "access_token", "user_id"} <= set(oauth.c.keys())
    targets = {fk.column.table.name for fk in oauth.foreign_keys}
    assert targets == {"users"}  # not the library default "user"


def test_formal_system_self_inheritance_fk():
    fks = Base.metadata.tables["formal_systems"].foreign_keys
    targets = {fk.column.table.name for fk in fks}
    # Inherits-from is a self-reference; owner points at users.
    assert "formal_systems" in targets
    assert "users" in targets


def test_theorem_search_columns_and_indexes():
    theorems = Base.metadata.tables["theorems"]
    # Structural search now goes through the term graph, not a JSONB blob.
    assert "pattern" not in theorems.c
    assert "statement_term_id" in theorems.c
    assert "embedding" in theorems.c  # semantic / AI search (HNSW)

    methods = {
        idx.name: idx.dialect_options["postgresql"].get("using")
        for idx in theorems.indexes
        if "postgresql" in idx.dialect_options
    }
    assert methods.get("ix_theorems_embedding") == "hnsw"

    # The graph's interning key: one row per distinct subterm per system.
    terms = Base.metadata.tables["terms"]
    unique = next(i for i in terms.indexes if i.name == "uq_terms_system_digest")
    assert unique.unique


def test_embedding_dimension_is_positive():
    assert EMBEDDING_DIMENSIONS > 0


def test_owner_slug_uniqueness_is_partial_on_owned_rows():
    # owner_id is nullable; the unique index must be scoped to owned rows so that
    # public (ownerless) systems aren't accidentally left unconstrained-by-design
    # yet advertised as unique. See models.FormalSystem.__table_args__.
    fs = Base.metadata.tables["formal_systems"]
    idx = next(i for i in fs.indexes if i.name == "uq_formal_systems_owner_slug")
    assert idx.unique
    where = idx.dialect_options["postgresql"].get("where")
    assert where is not None and "owner_id IS NOT NULL" in str(where)


def test_user_flags_have_db_side_defaults():
    # fastapi-users' base declares these NOT NULL with only a Python-side default;
    # we add server defaults so non-ORM inserts and column-adds stay safe.
    users = Base.metadata.tables["users"]
    for col in ("is_active", "is_superuser", "is_verified"):
        assert users.c[col].server_default is not None, col
