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
    Theorem,
    User,
    proof_references,
)
from app.db.session import get_session
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.db.systems_mapping import spec_to_system, system_to_spec

__all__ = [
    "Base",
    "EMBEDDING_DIMENSIONS",
    "FormalSystem",
    "OAuthAccount",
    "Proof",
    "ProofFolder",
    "Theorem",
    "User",
    "proof_references",
    "get_session",
    # Normalised system decomposition (app/db/systems.py) + spec round trip.
    "AxiomBindingRow",
    "AxiomRow",
    "BracketRow",
    "DefinitionBindingRow",
    "DefinitionRow",
    "LinePartRow",
    "LineRow",
    "ProductionBindingRow",
    "RuleAntecedentRow",
    "RuleBindingRow",
    "RuleRow",
    "SymbolRow",
    "spec_to_system",
    "system_to_spec",
]
