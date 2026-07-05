"""Side-conditions: a small, fixed vocabulary of structural provisos.

Many inference rules carry a proviso - "``x`` is not free in ``φ``", "``x``
and ``y`` are distinct" - that must hold for the rule to apply. Today those are
written in a Turing-complete condition mini-language (``matching/conditions.py``
plus the ``get_by_path`` interpreter) that the checker *executes* per proof
line. Step 3 replaces that, for the common cases, with a **closed algebra** of
side-conditions evaluated by total, terminating structural checks over terms.

The whole vocabulary
--------------------
* :class:`Occurs` - one term appears as a subterm of another (syntactic
  occurrence). ``Not(Occurs(x, phi))`` is the freshness proviso "``x`` does not
  occur in ``φ``".
* :class:`Distinct` - two terms share no variable leaf. This is Metamath's sole
  side-condition, the disjoint-variable proviso ``$d``; for a variable ``x`` and
  a formula ``φ`` it is the ``$d``-style "``x`` not free in ``φ``".
* :class:`IsVariable` - a term is a single atomic variable.
* :class:`Not`, :class:`And`, :class:`Or` - total boolean combinators.

That is the entire language: no loops, no reflection, no user code. A condition
is checked against the *binding* a rule match produces
(:func:`~website.logical.kernel.unify.match_all`), so it references the rule's
metavariables by name.

Deliberate limits (kept out of the trusted core)
------------------------------------------------
:class:`Occurs` is *syntactic* - it does not know binders, so it cannot express
capture-sensitive "free modulo ``∀``/``∃``/``λ``". :class:`Distinct` is the
``$d`` over-approximation that Metamath uses precisely to stay binder-agnostic
and sound. Conditions that need binder scoping, or membership in a proof-context
set (``x ∈ Γ`` over the assumptions), depend on the object logic or on proof
state and are intentionally *not* expressible here; they belong in the
elaboration layer, not the kernel. Keeping this vocabulary closed and
logic-agnostic is what lets it stay small and total.

Worked example - vacuous quantification
---------------------------------------
Rule: from ``φ`` infer ``∀x.φ`` provided ``x`` does not occur in ``φ``. After
matching the step, check the proviso against the binding::

    condition = Not(Occurs("x", "phi"))
    binding = match_all([(ant, premise), (ded, conclusion)], context)
    valid = binding is not None and condition.check(binding, context)

    # φ = P(y), ∀x.P(y):  x ∉ P(y) -> condition holds -> valid
    # φ = P(x), ∀x.P(x):  x ∈ P(x) -> condition fails -> rejected
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .terms import Node, Var
# Reuse the unifier's sort test, so "is this leaf a variable of sort S" means
# exactly what it means when a variable of sort S binds during matching.
from .unify import _sort_admits

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.patterns import Pattern
    from .terms import Term

    # The substitution a rule match produces: metavariable name -> bound Term.
    Binding = dict[str, Term]


class SideCondition:
    """Base class for the closed side-condition algebra.

    Every condition is checked against a ``binding`` (a rule match's
    substitution) and returns a plain ``bool`` - no exceptions for a failed
    proviso, only for a *malformed* one (a name the binding never bound).
    """

    def check(self, binding: Binding, context: Context) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Occurs(SideCondition):
    """``needle`` appears as a subterm of ``haystack`` (both metavariables).

    Syntactic occurrence - ``Occurs("x", "phi")`` is true when the term bound to
    ``x`` is structurally present anywhere inside the term bound to ``phi``. The
    freshness proviso is its negation, ``Not(Occurs("x", "phi"))``.
    """

    needle: str
    haystack: str

    def check(self, binding: Binding, context: Context) -> bool:
        return _occurs(
            _bound(binding, self.needle), _bound(binding, self.haystack), context
        )


@dataclass(frozen=True)
class Distinct(SideCondition):
    """The terms bound to ``left`` and ``right`` share no variable leaf.

    This is Metamath's ``$d``. ``variable_sort`` restricts which leaves count as
    variables (e.g. ``setvar``); left unset, every atomic leaf counts. For a
    variable ``x`` and a formula ``φ``, ``Distinct("x", "phi", setvar)`` is the
    ``$d``-style "``x`` does not occur (free) in ``φ``".
    """

    left: str
    right: str
    variable_sort: Pattern | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        left = _variable_leaves(_bound(binding, self.left), context, self.variable_sort)
        right = _variable_leaves(_bound(binding, self.right), context, self.variable_sort)
        return left.isdisjoint(right)


@dataclass(frozen=True)
class IsVariable(SideCondition):
    """The term bound to ``name`` is a single atomic variable.

    Sorts already constrain what a metavariable may bind to during matching, so
    this is mainly for rules that must additionally insist a slot is atomic (not
    a compound term). ``variable_sort`` optionally pins the expected sort.
    """

    name: str
    variable_sort: Pattern | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        term = _bound(binding, self.name)
        if not _is_atomic(term):
            return False
        return self.variable_sort is None or _sort_admits(self.variable_sort, term, context)


@dataclass(frozen=True)
class Not(SideCondition):
    """Negation - true exactly when ``inner`` is false."""

    inner: SideCondition

    def check(self, binding: Binding, context: Context) -> bool:
        return not self.inner.check(binding, context)


@dataclass(frozen=True)
class And(SideCondition):
    """Conjunction - true when every part holds (vacuously true if empty)."""

    parts: tuple[SideCondition, ...]

    def check(self, binding: Binding, context: Context) -> bool:
        return all(part.check(binding, context) for part in self.parts)


@dataclass(frozen=True)
class Or(SideCondition):
    """Disjunction - true when any part holds (vacuously false if empty)."""

    parts: tuple[SideCondition, ...]

    def check(self, binding: Binding, context: Context) -> bool:
        return any(part.check(binding, context) for part in self.parts)


def _bound(binding: Binding, name: str) -> Term:
    """Look up a metavariable's bound term, or fail loudly on a malformed
    condition (one naming a metavariable the rule never binds)."""
    if name not in binding:
        raise ValueError(
            f"Side-condition references '{name}', which the rule match did not bind."
        )
    return binding[name]


def _is_atomic(term: Term) -> bool:
    """A term with no internal structure: a variable, or a childless leaf."""
    return isinstance(term, Var) or (isinstance(term, Node) and not term.children)


def _occurs(needle: Term, haystack: Term, context: Context) -> bool:
    """Whether ``needle`` is structurally present anywhere within ``haystack``."""
    if haystack.equal(needle, context):
        return True
    if isinstance(haystack, Node):
        return any(_occurs(needle, child, context) for child in haystack.children.values())
    return False


def _variable_leaves(term: Term, context: Context, variable_sort: Pattern | None) -> set[str]:
    """The surface strings of ``term``'s atomic leaves, optionally restricted to
    those of ``variable_sort``.

    For a formula like ``P(x)`` this is ``{"P", "x"}`` unrestricted, or ``{"x"}``
    with ``variable_sort=setvar`` - which is what makes :class:`Distinct` behave
    as a variable-occurrence check rather than a whole-symbol check.
    """
    leaves: set[str] = set()

    def walk(node: Term) -> None:
        if isinstance(node, Var):
            if variable_sort is None or _sort_admits(variable_sort, node, context):
                leaves.add(node.name)
            return
        if isinstance(node, Node) and not node.children:
            if variable_sort is None or _sort_admits(variable_sort, node, context):
                leaves.add(node.literal if node.literal is not None else node.to_string())
            return
        if isinstance(node, Node):
            for child in node.children.values():
                walk(child)

    walk(term)
    return leaves
