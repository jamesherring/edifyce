"""Pattern-matching engine for formal systems.

This package was split out of a single large ``matching.py`` module.

Module layout (in dependency order)::

    context     - the Context object
    matches     - Match, the parse record
    patterns    - Pattern and its subclasses
    definitions - DefinedNotation
    rewriting   - all-solutions associative matching for string-rewriting rules

``matches``, ``patterns`` and ``definitions`` are mutually recursive; they
reference each other through module-level ``from . import ...`` imports and
qualified names so that the import cycle resolves cleanly at runtime.

The string ``get_by_path`` interpreter and its ``Condition`` expression tree
(formerly the ``paths`` and ``conditions`` modules) have been retired; proof
checking runs on kernel term unification, the closed side-condition algebra,
and the scope/subproof mechanism instead. ``MatchSet`` went the same way, along
with the tree-walks on ``Match`` that duplicated the kernel's own operations —
this layer parses, and hands the parse straight over (see ``matches``).
"""

from .context import Context
from .matches import Match
from .patterns import (
    AbstractPattern,
    AtomPattern,
    Pattern,
    RegexPattern,
    StringPattern,
    UnionPattern,
)
from .definitions import DefinedNotation
from .rewriting import iter_bindings, iter_joint, joint_binding_exists

__all__ = [
    "AbstractPattern",
    "AtomPattern",
    "Context",
    "DefinedNotation",
    "Match",
    "Pattern",
    "RegexPattern",
    "StringPattern",
    "UnionPattern",
    "iter_bindings",
    "iter_joint",
    "joint_binding_exists",
]
