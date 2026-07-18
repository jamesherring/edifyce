"""Side-conditions: a small, fixed vocabulary of structural provisos.

Many inference rules carry a proviso - "``x`` is not free in ``φ``", "``x`` and
``y`` are distinct" - that must hold for the rule to apply. Today those are
written in a Turing-complete condition mini-language (``matching/conditions.py``
plus the ``get_by_path`` interpreter) that the checker *executes* per proof
line. Step 3 replaces that, for the common cases, with a **closed algebra** of
side-conditions evaluated by total, terminating structural checks over terms.

The whole vocabulary
--------------------
Each item is a *generic* structural predicate over terms; the first-order-logic
reading is one instantiation, not something the kernel hard-codes.

* :class:`Occurs` - one term occurs as a subterm of another.
      FOL: the freshness proviso is ``Not(Occurs("x", "phi"))`` - "``x`` does
      not occur in ``φ``".
* :class:`DisjointLeaves` - two terms share no leaf (of a given sort).
      FOL, with the ``setvar`` sort, this is Metamath's disjoint-variable
      proviso ``$d`` - "the variable ``x`` does not occur among the variables of
      ``φ``".
* :class:`IsAtom` - a term is a single childless leaf.
      FOL: "this metavariable stands for a variable, not a compound term".
* :class:`Equal` - two terms are structurally equal.
      FOL: ``Equal("p", "q")`` is "these two schemas coincide"; its negation,
      ``Not(Equal(...))``, is the "must be distinct" proviso.
* :class:`Not`, :class:`And`, :class:`Or` - total boolean combinators.

Nothing here names a connective, a quantifier, or a specific notion of
"variable": *which* sort counts as a variable is a per-system parameter (a
``Pattern`` the system supplies), so the vocabulary stays logic-agnostic while
still covering FOPC and ZF(C) - Metamath verifies all of ZFC on ``$d`` alone.
A condition is checked against the *binding* a rule match produces
(:func:`~website.logical.kernel.unify.match_all`), so it references the rule's
metavariables by name.

Why these live in the *kernel*
------------------------------
These provisos are soundness-critical: universal generalisation without its
freshness check derives falsehoods. So the trusted core must verify them itself
(as Metamath's verifier checks ``$d``) rather than trusting an elaborator.
Keeping the vocabulary closed and minimal is what lets the core stay small while
remaining sound.

Deliberate limits (kept out of the trusted core)
------------------------------------------------
:class:`Occurs` is *syntactic* - it does not know binders, so it cannot express
capture-sensitive "free modulo ``∀``/``∃``/``λ``". :class:`DisjointLeaves` is
the sound over-approximation Metamath uses (``$d``) precisely to stay
binder-agnostic. Conditions that need binder scoping, or membership in a
proof-context set (``x ∈ Γ`` over the assumptions), depend on the object logic
or on proof state and are intentionally *not* expressible here; they belong in
the elaboration layer, not the kernel.

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
# Reuse the unifier's sort test, so "is this leaf of sort S" means exactly what
# it means when a variable of sort S binds during matching.
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
    """``needle`` occurs as a subterm of ``haystack`` (both metavariables).

    Generic: pure subterm containment over any term algebra - true when the term
    bound to ``needle`` is structurally present anywhere inside the term bound to
    ``haystack``. No notion of variable or binder is involved.

    FOL: freshness is the negation, ``Not(Occurs("x", "phi"))`` - "``x`` does not
    occur in ``φ``" (e.g. the side-condition on vacuous/∀-introduction).
    """

    needle: str
    haystack: str

    def check(self, binding: Binding, context: Context) -> bool:
        return _occurs(
            _bound(binding, self.needle), _bound(binding, self.haystack), context
        )


@dataclass(frozen=True)
class DisjointLeaves(SideCondition):
    """The terms bound to ``left`` and ``right`` share no leaf of sort ``sort``.

    Generic: a structural check that two subterms have no atom in common. ``sort``
    restricts which leaves count; unset, every atomic leaf does. Restricting to a
    sort is what makes ``P(x)`` and ``P(z)`` count as sharing nothing despite
    both containing the predicate symbol ``P`` - only the ``setvar`` leaves
    ``x``/``z`` are compared.

    FOL: with ``sort`` = the ``setvar`` pattern this is Metamath's
    disjoint-variable proviso ``$d``. For a variable ``x`` and a formula ``φ``,
    ``DisjointLeaves("x", "phi", setvar)`` is the ``$d``-style "``x`` does not
    occur (free) in ``φ``".
    """

    left: str
    right: str
    sort: Pattern | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        left = _leaves(_bound(binding, self.left), context, self.sort)
        right = _leaves(_bound(binding, self.right), context, self.sort)
        return left.isdisjoint(right)


@dataclass(frozen=True)
class IsAtom(SideCondition):
    """The term bound to ``name`` is a single childless leaf, optionally of
    sort ``sort``.

    Generic: "has no internal structure". This is largely redundant with the
    sort discipline already enforced when a metavariable binds during matching,
    so it is only needed when a rule must insist a slot is atomic *beyond* what
    its (possibly broad) sort guarantees.

    FOL: ``IsAtom("x", setvar)`` asserts the metavariable ``x`` stands for a
    variable rather than a compound formula/term.
    """

    name: str
    sort: Pattern | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        term = _bound(binding, self.name)
        if not _is_atom(term):
            return False
        return self.sort is None or _sort_admits(self.sort, term, context)


@dataclass(frozen=True)
class Equal(SideCondition):
    """The terms bound to ``left`` and ``right`` are structurally equal.

    Generic: a total, purely syntactic test over the term algebra - two
    metavariables coincide iff their bound terms are equal (no re-parsing, no
    definitional unfolding). It reuses the same :meth:`Term.equal` the matcher's
    ground case is built on, so "equal" means one thing across the kernel.

    FOL: ``Equal("p", "q")`` asserts two schematic formulas are the same; the
    "these must differ" proviso is its negation, ``Not(Equal("p", "q"))``.
    """

    left: str
    right: str

    def check(self, binding: Binding, context: Context) -> bool:
        return _bound(binding, self.left).equal(_bound(binding, self.right), context)


@dataclass(frozen=True)
class Not(SideCondition):
    """Negation - true exactly when ``inner`` is false."""

    inner: SideCondition

    def check(self, binding: Binding, context: Context) -> bool:
        return not self.inner.check(binding, context)


@dataclass(frozen=True)
class And(SideCondition):
    """Conjunction - true when every part holds (vacuously true if empty).

    Every part is evaluated even once the result is decided, so a *malformed*
    part (naming an unbound metavariable) always raises, regardless of order or
    composition - a typo in a rule's proviso can't be hidden by short-circuiting.
    """

    parts: tuple[SideCondition, ...]

    def check(self, binding: Binding, context: Context) -> bool:
        results = [part.check(binding, context) for part in self.parts]
        return all(results)


@dataclass(frozen=True)
class Or(SideCondition):
    """Disjunction - true when any part holds (vacuously false if empty).

    Like :class:`And`, every part is evaluated (no short-circuit) so a malformed
    part always raises rather than being skipped when an earlier part decides
    the result.
    """

    parts: tuple[SideCondition, ...]

    def check(self, binding: Binding, context: Context) -> bool:
        results = [part.check(binding, context) for part in self.parts]
        return any(results)


def normal_form(condition: SideCondition) -> tuple:
    """A structural normal form for comparing side-conditions by value.

    Sorts compare by name (not object identity) so two parses of the same
    proviso - even in different contexts - agree, and boolean combinators fold
    to their parts. Used to compare rules and definitions structurally rather
    than by their (formatting-sensitive) source text.
    """
    if isinstance(condition, (And, Or)):
        return (
            type(condition).__name__,
            tuple(sorted(normal_form(part) for part in condition.parts)),
        )
    if isinstance(condition, Not):
        return ("Not", normal_form(condition.inner))
    if isinstance(condition, Occurs):
        return ("Occurs", condition.needle, condition.haystack)
    if isinstance(condition, Equal):
        return ("Equal", condition.left, condition.right)
    if isinstance(condition, DisjointLeaves):
        sort = None if condition.sort is None else condition.sort.name
        return ("DisjointLeaves", condition.left, condition.right, sort)
    if isinstance(condition, IsAtom):
        sort = None if condition.sort is None else condition.sort.name
        return ("IsAtom", condition.name, sort)
    return (type(condition).__name__,)


def _bound(binding: Binding, name: str) -> Term:
    """Look up a metavariable's bound term, or fail loudly on a malformed
    condition (one naming a metavariable the rule never binds)."""
    if name not in binding:
        raise ValueError(
            f"Side-condition references '{name}', which the rule match did not bind."
        )
    return binding[name]


def _is_atom(term: Term) -> bool:
    """A term with no internal structure: a variable, or a childless leaf."""
    return isinstance(term, Var) or (isinstance(term, Node) and not term.children)


def _occurs(needle: Term, haystack: Term, context: Context) -> bool:
    """Whether ``needle`` is structurally present anywhere within ``haystack``."""
    if haystack.equal(needle, context):
        return True
    if isinstance(haystack, Node):
        return any(_occurs(needle, child, context) for child in haystack.children.values())
    return False


def _leaves(term: Term, context: Context, sort: Pattern | None) -> set[str]:
    """The surface strings of ``term``'s atomic leaves, optionally restricted to
    those of ``sort``.

    For a formula like ``P(x)`` this is ``{"P", "x"}`` unrestricted, or ``{"x"}``
    with ``sort=setvar`` - which is what makes :class:`DisjointLeaves` behave as
    a variable-occurrence check rather than a whole-symbol check.
    """
    found: set[str] = set()

    def walk(node: Term) -> None:
        if isinstance(node, Var):
            if sort is None or _sort_admits(sort, node, context):
                found.add(node.name)
            return
        if isinstance(node, Node) and not node.children:
            if sort is None or _sort_admits(sort, node, context):
                found.add(node.literal if node.literal is not None else node.to_string())
            return
        if isinstance(node, Node):
            for child in node.children.values():
                walk(child)

    walk(term)
    return found
