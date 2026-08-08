"""Persistence layer: SQLAlchemy models and async session wiring.

Schema changes are managed with Atlas (see `atlas.hcl` and `migrations/`), which
reads the models in this package as the source of truth.
"""

from app.db.base import Base
from app.db.assumptions import (
    Assumed,
    AssumptionRow,
    RestsOn,
    Stated,
    TheoremAssumptionRow,
    assumption_labels,
    closure_of,
    inherit_closure,
    dependent_counts,
    dependent_entries,
    record_closure,
    rests_on,
    resolve_labels,
    stated,
)
from app.db.models import (
    EMBEDDING_DIMENSIONS,
    FormalSystem,
    OAuthAccount,
    Proof,
    ProofFolder,
    ProofReference,
    Theorem,
    User,
)
from app.db.avoidances import LabelAvoidanceRow
from app.db.avoidances_mapping import avoided_by, store_avoidances
from app.db.descriptions import (
    LabelAttributionRow,
    LabelDescriptionRow,
    LabelReferenceRow,
)
from app.db.descriptions_mapping import (
    contributions,
    load_description,
    load_descriptions,
    mentions_of,
    store_descriptions,
)
from app.db.metamath_store import ImportReport, import_corpus
from app.db.outline_mapping import StoredOutline, store_outline
from app.db.slugs import slugify, unique_slug
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.promoted_theorems_mapping import (
    LibraryChain,
    LibraryLayer,
    PendingLibrary,
    cited_labels,
    load_citable_theorems,
    load_theorems,
    read_library,
    store_theorem,
    theorem_digest,
)
from app.db.proofs_mapping import (
    PendingCitations,
    clear_proof_lines,
    discard_system_checks,
    load_proof_for_check,
    load_proof_lines,
    store_proof_lines,
)
from app.db.session import get_session
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    NotationPieceRow,
    NotationRulePieceRow,
    NotationRulePinRow,
    NotationRuleRow,
    ProductionBindingRow,
    ProductionBindingScopeRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.db.definition_terms import (
    DefinitionTermCache,
    load_definition_terms,
    store_definition_terms,
)
from app.db.schema_terms import (
    SchemaTermCache,
    load_schema_terms,
    store_schema_terms,
)
from app.db.side_conditions import SideConditionRow
from app.db.systems_mapping import (
    effective_library,
    effective_spec,
    inherited_definition_count,
    inherited_rule_count,
    spec_to_system,
    system_to_spec,
)
from app.db.system_relations import (
    RELATION_KINDS,
    RELATION_STATUSES,
    SystemRelationExtraRow,
    SystemRelationObligationRow,
    SystemRelationRow,
    SystemRelationSortRow,
    SystemRelationSymbolRow,
)
from app.db.system_relations_mapping import related_layers
from app.db.terms import TermChildRow, TermRow
from app.db.terms_mapping import (
    TermGraph,
    alpha_digest,
    digest_term,
    prefetch_terms,
    store_term,
    store_terms,
    term_context,
)

__all__ = [
    "Assumed",
    "AssumptionRow",
    "Base",
    "RestsOn",
    "TheoremAssumptionRow",
    "assumption_labels",
    "closure_of",
    "inherit_closure",
    "Stated",
    "stated",
    "dependent_counts",
    "dependent_entries",
    "record_closure",
    "rests_on",
    "resolve_labels",
    "EMBEDDING_DIMENSIONS",
    "FormalSystem",
    "OAuthAccount",
    "Proof",
    "ProofFolder",
    "Theorem",
    "User",
    "ProofReference",
    "get_session",
    # Proof structure (app/db/proof_lines.py) + the checked-proof projection.
    "ProofLineAntecedentRow",
    "ProofLineRow",
    "clear_proof_lines",
    "discard_system_checks",
    "PendingCitations",
    "load_proof_for_check",
    "load_proof_lines",
    "store_proof_lines",
    # Normalised system decomposition (app/db/systems.py) + spec round trip.
    "AxiomBindingRow",
    "AxiomRow",
    "BracketRow",
    "NotationPieceRow",
    "NotationRulePieceRow",
    "NotationRulePinRow",
    "NotationRuleRow",
    "DefinitionBindingRow",
    "DefinitionFreshRow",
    "DefinitionRow",
    "LinePartRow",
    "LineRow",
    "ProductionBindingRow",
    "ProductionBindingScopeRow",
    "RuleAntecedentRow",
    "RuleBindingRow",
    "RuleRow",
    "SideConditionRow",
    "SymbolRow",
    # What a system says about its labels (app/db/descriptions.py).
    "LabelAttributionRow",
    "LabelAvoidanceRow",
    "avoided_by",
    "store_avoidances",
    "LabelReferenceRow",
    "LabelDescriptionRow",
    "contributions",
    "load_description",
    "load_descriptions",
    "mentions_of",
    "store_descriptions",
    # The citable library (app/db/promoted_theorems.py).
    "PromotedTheoremBindingRow",
    "PromotedTheoremPremiseRow",
    "PromotedTheoremRow",
    "PendingLibrary",
    "cited_labels",
    "load_citable_theorems",
    "LibraryChain",
    "LibraryLayer",
    "load_theorems",
    "read_library",
    "store_theorem",
    "theorem_digest",
    "spec_to_system",
    "system_to_spec",
    # The general edge (app/db/system_relations.py).
    "RELATION_KINDS",
    "RELATION_STATUSES",
    "SystemRelationExtraRow",
    "SystemRelationObligationRow",
    "SystemRelationRow",
    "SystemRelationSortRow",
    "SystemRelationSymbolRow",
    "related_layers",
    "effective_spec",
    "effective_library",
    "inherited_definition_count",
    "inherited_rule_count",
    # Term graph (app/db/terms.py) + kernel-term round trip.
    "TermChildRow",
    "TermGraph",
    "TermRow",
    "alpha_digest",
    "digest_term",
    "prefetch_terms",
    "store_term",
    "store_terms",
    "term_context",
    # Rule-schema term cache (app/db/schema_terms.py).
    "SchemaTermCache",
    "load_schema_terms",
    "store_schema_terms",
    # Definition-form term cache (app/db/definition_terms.py).
    "DefinitionTermCache",
    "load_definition_terms",
    "store_definition_terms",
    # Metamath corpus import (app/db/metamath_store.py).
    "ImportReport",
    "import_corpus",
    # The section outline as the folder tree (app/db/outline_mapping.py).
    "StoredOutline",
    "store_outline",
    "slugify",
    "unique_slug",
]
