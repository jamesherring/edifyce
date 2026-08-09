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
        # Proof structure (a checked proof's lines + justification edges).
        "proof_lines",
        "proof_line_antecedents",
        # Normalised system decomposition (canonical grammar/rules/definitions).
        "notation_brackets",
        "symbols",
        "production_bindings",
        "production_binding_scopes",
        "line_types",
        "line_parts",
        # How a system's terms may be *read* — one named notation's render steps.
        "notation_pieces",
        "notation_rules",
        "notation_rule_pins",
        "notation_rule_pieces",
        # What a system says about the labels it names, who wrote them, and what
        # its prose points at.
        "label_descriptions",
        "label_attributions",
        "label_citations",
        "label_references",
        # And what it declares a proof does *without*.
        "label_avoidances",
        "definitions",
        "definition_bindings",
        "definition_fresh",
        "axioms",
        "axiom_bindings",
        "rules",
        "rule_antecedents",
        "rule_bindings",
        # Term graph (canonical statement structure for theorems).
        "terms",
        "term_children",
        # Structured definition provisos (the kernel side-condition algebra).
        "side_conditions",
        # The citable library: proved and imported theorems, resolved by label.
        "promoted_theorems",
        "promoted_theorem_premises",
        "promoted_theorem_bindings",
        # A library entry nobody proved, and what transitively rests on it.
        "assumptions",
        "theorem_assumptions",
        # What a formal statement claims to be a formalization *of*, and who
        # said so (app/db/formalizations.py).
        "source_documents",
        "formalizations",
        "glossary_entries",
        # The general edge between two systems, where the spine cannot reach: a
        # second parent, a sort rename, a notation map, and a statement template
        # with the metavariables it introduces (app/db/system_relations.py).
        "system_relations",
        "system_relation_sorts",
        "system_relation_symbols",
        "system_relation_extras",
        "system_relation_obligations",
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


def test_the_prose_search_columns_are_trigram_indexed():
    # Every column `app.db.label_search` puts a `%word%` against, on both
    # haystacks. They are a *set*: the search's predicate is an `OR` across the
    # three, Postgres answers that with a `BitmapOr` of three index scans, and one
    # missing arm sends the planner back to scanning the whole table for the whole
    # predicate — which is a 40× regression on a corpus and would be invisible.
    for table, columns in (
        ("label_descriptions", ("label", "title", "text")),
        ("proofs", ("name", "title", "description")),
    ):
        indexes = {
            index.name: index.dialect_options["postgresql"]
            for index in Base.metadata.tables[table].indexes
            if "postgresql" in index.dialect_options
        }
        for column in columns:
            options = indexes.get(f"ix_{table}_{column}_trgm")
            assert options is not None, f"{table}.{column} is not trigram indexed"
            assert options.get("using") == "gin"
            assert options.get("ops") == {column: "gin_trgm_ops"}


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
