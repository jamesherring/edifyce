"""Pattern-matching engine for formal systems.

This package was split out of a single large ``matching.py`` module. The
public API is unchanged: every name previously importable from
``website.logical.matching`` is re-exported here.

Module layout (in dependency order)::

    paths       - path lookup / argument parsing helpers (leaf)
    conditions  - the Condition expression tree
    context     - the Context object
    matches     - Match and MatchSet
    patterns    - Pattern and its subclasses (+ PatternFunction)
    definitions - Definition

``matches``, ``patterns`` and ``definitions`` are mutually recursive; they
reference each other through module-level ``from . import ...`` imports and
qualified names so that the import cycle resolves cleanly at runtime.
"""

from .paths import constant, get_by_path, parse_arguments, parse_path, path_maps_to
from .conditions import Condition
from .context import Context
from .matches import Match, MatchSet
from .patterns import (
    AbstractPattern,
    Pattern,
    PatternFunction,
    RegexPattern,
    StringPattern,
    SystemConditionPattern,
    UnionPattern,
)
from .definitions import Definition

__all__ = [
    "AbstractPattern",
    "Condition",
    "Context",
    "Definition",
    "Match",
    "MatchSet",
    "Pattern",
    "PatternFunction",
    "RegexPattern",
    "StringPattern",
    "SystemConditionPattern",
    "UnionPattern",
    "constant",
    "get_by_path",
    "parse_arguments",
    "parse_path",
    "path_maps_to",
]
