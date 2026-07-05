"""Persistence layer: SQLAlchemy models and async session wiring.

Schema changes are managed with Atlas (see `atlas.hcl` and `migrations/`), which
reads the models in this package as the source of truth.
"""

from app.db.base import Base
from app.db.models import (
    EMBEDDING_DIMENSIONS,
    FormalSystem,
    Proof,
    ProofFolder,
    Theorem,
    User,
    proof_references,
)
from app.db.session import get_session

__all__ = [
    "Base",
    "EMBEDDING_DIMENSIONS",
    "FormalSystem",
    "Proof",
    "ProofFolder",
    "Theorem",
    "User",
    "proof_references",
    "get_session",
]
