"""Persistence layer: SQLAlchemy models and async session wiring.

Schema changes are managed with Atlas (see `atlas.hcl` and `migrations/`), which
reads the models in this package as the source of truth.
"""

from app.db.base import Base
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
from app.db.metamath_store import ImportReport, import_corpus
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.promoted_theorems_mapping import (
    PendingLibrary,
    cited_labels,
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
    effective_spec,
    inherited_definition_count,
    inherited_rule_count,
    spec_to_system,
    system_to_spec,
)
from app.db.terms import TermChildRow, TermRow
from app.db.terms_mapping import (
    TermGraph,
    alpha_digest,
    digest_term,
    prefetch_terms,
    store_term,
)

__all__ = [
    "Base",
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
    # The citable library (app/db/promoted_theorems.py).
    "PromotedTheoremBindingRow",
    "PromotedTheoremPremiseRow",
    "PromotedTheoremRow",
    "PendingLibrary",
    "cited_labels",
    "load_theorems",
    "read_library",
    "store_theorem",
    "theorem_digest",
    "spec_to_system",
    "system_to_spec",
    "effective_spec",
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
]
