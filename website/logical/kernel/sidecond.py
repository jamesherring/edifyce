"""Structural side-conditions over terms (kernel step 3).

The roadmap in :mod:`website.logical.kernel.terms` earmarks a small, fixed
vocabulary of side-conditions - freshness, distinctness - checked *structurally*
over :class:`~website.logical.kernel.terms.Term` trees rather than by the general
string-based condition interpreter. This module is that vocabulary's first
entry: the freshness test a sound universal generalisation needs.

Freshness is asked of an *eigenvariable*: the arbitrary variable a
generalisation subproof introduces. The variable is only genuinely arbitrary if
it does not already occur in any hypothesis still in force, so ``∀x`` may bind
it. :func:`occurs` answers "does this variable occur in this term" purely by
walking the tree, and :func:`is_fresh` lifts that to a set of terms.

Because the kernel deliberately hard-codes no logic (it cannot know which node
is a quantifier), :func:`occurs` does not interpret binding: an occurrence under
a binder is still counted. For the eigenvariable check this is conservative in
the safe direction - it can only *reject* a generalisation, never wrongly accept
one - which is exactly what soundness wants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .terms import Node, Var

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .terms import Term


def occurs(term: Term, name: str) -> bool:
    """Whether the variable/atom ``name`` occurs anywhere in ``term``.

    Structural, not textual: it matches a leaf whose token is exactly ``name``
    and never a substring of a larger token or operator, so the eigenvariable
    ``x`` is not spuriously found inside ``xy`` or inside ``∈``.

    Examples (terms for ground formulae)::

        occurs(term "x ∈ c", "x")            -> True
        occurs(term "y ∈ c", "x")            -> False
        occurs(term "(x ∈ c → x ∈ c)", "x")  -> True
    """
    if isinstance(term, Var):
        return term.name == name

    if isinstance(term, Node):
        if term.literal is not None:
            return term.literal == name
        return any(occurs(child, name) for child in term.children.values())

    return False


def is_fresh(name: str, terms: Iterable[Term]) -> bool:
    """Whether ``name`` is fresh for every term in ``terms`` (occurs in none)."""
    return all(not occurs(term, name) for term in terms)
