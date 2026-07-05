"""The (nascent) trusted proof kernel.

This package is where the small, auditable checking core lives. It is being
grown incrementally out of the larger pattern-matching engine; the first piece
is :mod:`terms`, a parse-once tree representation for formulae.

Nothing here hard-codes a logic. Constructors, sorts and definitions are all
carried as ordinary per-system objects, so first-order logic, ZF(C) and
near-English surface syntax are all representable without the kernel knowing
about any of them.
"""

from .terms import Node, Term, Var, from_match, from_pattern

__all__ = [
    "Node",
    "Term",
    "Var",
    "from_match",
    "from_pattern",
]
