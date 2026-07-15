"""Normalised relational storage for Edifyce formal systems.

The proof engine treats a formal system as a *source string* it recompiles on
demand, and the first-draft persistence layer (see PR #13) stored exactly that
-- a ``source`` text column plus a cached ``compiled`` JSONB blob. Both are
opaque to SQL: you cannot ask "which systems define ``⊆``", "which rules take
two antecedents", or "which systems have a membership relation" without
compiling every row in application code.

This package decomposes a system into flat rows instead -- one row per sort,
production, binding, definition, axiom, rule and antecedent -- so every part is
a first-class, indexable, searchable entity and there are no text dumps or JSON
columns. The bridge to the engine is the declarative front-end's
:class:`~website.logical.declarative.SystemSpec`: rows map to a ``SystemSpec``,
which lowers to ``.edi`` and compiles. The round trip

    SystemSpec  <->  relational rows  ->  (lower) ->  FormalSystem

is what :mod:`app.systems.mapping` provides and the tests exercise end to end.
"""

from .models import (
    AxiomRow,
    Base,
    BracketRow,
    DefinitionRow,
    FormalSystemRow,
    LinePartRow,
    LineRow,
    ProductionRow,
    RuleRow,
    SortRow,
)
from .mapping import spec_to_system, system_to_spec

__all__ = [
    "AxiomRow",
    "Base",
    "BracketRow",
    "DefinitionRow",
    "FormalSystemRow",
    "LinePartRow",
    "LineRow",
    "ProductionRow",
    "RuleRow",
    "SortRow",
    "spec_to_system",
    "system_to_spec",
]
