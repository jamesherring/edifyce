"""Formal systems: compilation targets and proof checking.

Split out of a single large ``formal_system.py`` module; the public API is
unchanged. Module layout (in dependency order)::

    line_type - LineType (leaf)
    proof     - Proof, ProofLine (leaf)
    rules     - InferenceRule, Inference (uses ProofLine)
    system    - FormalSystem (uses Proof)

The class graph is acyclic, so submodules import each other directly.
"""

from .line_type import LineType
from .proof import Proof, ProofLine, Subproof
from .promotion import PromotedTheorem
from .rules import Inference, InferenceRule, SubproofSchema, statement_term
from .system import FormalSystem

__all__ = [
    "FormalSystem",
    "Inference",
    "InferenceRule",
    "LineType",
    "Proof",
    "ProofLine",
    "PromotedTheorem",
    "Subproof",
    "SubproofSchema",
    "statement_term",
]
