"""The (nascent) trusted proof kernel.

This package is where the small, auditable checking core lives. It is being
grown incrementally out of the larger pattern-matching engine:

* :mod:`terms` (step 1) - a parse-once tree representation for formulae.
* :mod:`unify` (step 2) - first-order matching that derives a substitution
  making a schema equal a term, the operation rule-checking is built on.
* :mod:`side_conditions` (step 3) - a small, closed vocabulary of structural
  provisos (occurrence, leaf-disjointness, atomicity) checked against a match's
  binding.
* :mod:`definitions` (step 4) - definitions as cited axioms; the kernel verifies
  a single definitional unfold rather than unfolding implicitly. A defining
  form's bound variables are stored abstractly, by index (:class:`Bound`), so an
  unfold's consumer renames the binder to a fresh name instead of being blocked
  when the argument would collide with it.

See :mod:`terms` for the roadmap these steps follow.

Nothing here hard-codes a logic. Constructors, sorts and definitions are all
carried as ordinary per-system objects, so first-order logic, ZF(C) and
near-English surface syntax are all representable without the kernel knowing
about any of them.
"""

from .definitions import (
    Definition,
    FreshBinder,
    check_definitional_step,
    introduced_leaves,
    unbound_parameters,
    unfold,
)
from .side_conditions import (
    And,
    DisjointLeaves,
    Equal,
    IsAtom,
    IsMember,
    Not,
    Occurs,
    Or,
    SideCondition,
    references,
    restate,
)
from .constructors import Constructor, constructor_for
from .terms import Bound, Node, Term, Var, abstract, bind, from_match, from_pattern, intern
from .unify import match, match_all

__all__ = [
    "And",
    "Bound",
    "Constructor",
    "Definition",
    "FreshBinder",
    "DisjointLeaves",
    "Equal",
    "IsAtom",
    "IsMember",
    "Node",
    "Not",
    "Occurs",
    "Or",
    "SideCondition",
    "Term",
    "Var",
    "abstract",
    "bind",
    "check_definitional_step",
    "constructor_for",
    "from_match",
    "from_pattern",
    "intern",
    "introduced_leaves",
    "match",
    "match_all",
    "references",
    "restate",
    "unbound_parameters",
    "unfold",
]
