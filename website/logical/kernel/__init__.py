"""The (nascent) trusted proof kernel.

This package is where the small, auditable checking core lives. It is being
grown incrementally out of the larger pattern-matching engine:

* :mod:`terms` (step 1) - a parse-once tree representation for formulae.
* :mod:`unify` (step 2) - first-order matching that derives a substitution
  making a schema equal a term, the operation rule-checking is built on.

Planned next steps build on these without enlarging the trusted surface: a
fixed vocabulary of structural side-conditions (step 3) and definitions treated
as ordinary axioms (step 4). See :mod:`terms` for the roadmap those steps follow.

Nothing here hard-codes a logic. Constructors, sorts and definitions are all
carried as ordinary per-system objects, so first-order logic, ZF(C) and
near-English surface syntax are all representable without the kernel knowing
about any of them.
"""

from .terms import Node, Term, Var, from_match, from_pattern
from .unify import match, match_all

__all__ = [
    "Node",
    "Term",
    "Var",
    "from_match",
    "from_pattern",
    "match",
    "match_all",
]
