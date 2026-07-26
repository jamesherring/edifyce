"""Importing Metamath (``.mm``) databases into Edifyce.

The pipeline, and where each piece lives:

``parser``      ``.mm`` text -> :class:`~.parser.Database` (statements, scopes,
                mandatory hypotheses).
``compressed``  a ``$p``'s compressed proof -> the sequence of steps it selects.
``importer``    a database -> an Edifyce ``FormalSystem`` (grammar from the
                syntax axioms, library as promoted theorems) and proof text.

The contract is that an import produces *primitive* Edifyce proofs which the
existing kernel checks. Nothing here re-verifies a Metamath proof; the import is
only a translation, and Edifyce's own checker is what makes the result trusted.

See ``docs/metamath-import-roadmap.md`` for the design this implements.
"""

from .compressed import Step, decode, split_proof
from .importer import (
    build_spec,
    import_database,
    import_proof,
    import_theorem,
    promote_assertions,
    promoted_theorem,
    walk,
)
from .parser import (
    ASSERTION_TYPECODE,
    Assertion,
    Database,
    Hypothesis,
    MetamathError,
    parse,
)

__all__ = [
    "ASSERTION_TYPECODE",
    "Assertion",
    "Database",
    "Hypothesis",
    "MetamathError",
    "Step",
    "build_spec",
    "decode",
    "import_database",
    "import_proof",
    "import_theorem",
    "parse",
    "promote_assertions",
    "promoted_theorem",
    "split_proof",
    "walk",
]
