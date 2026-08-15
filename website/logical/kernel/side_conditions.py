"""Side-conditions: a small, fixed vocabulary of structural provisos.

Many inference rules carry a proviso - "``x`` is not free in ``φ``", "``x`` and
``y`` are distinct" - that must hold for the rule to apply. These once lived in a
Turing-complete condition mini-language (a string ``get_by_path`` interpreter and
its ``Condition`` tree) that the checker *executed* per proof line; that
interpreter has since been **retired entirely**. Provisos are now this **closed
algebra** of side-conditions, evaluated by total, terminating structural checks
over terms.

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
:class:`~website.logical.kernel.constructors.Constructor` the system supplies),
so the vocabulary stays logic-agnostic while
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
from .unify import sort_admits

if TYPE_CHECKING:
    from ..matching.context import Context
    from .constructors import Constructor
    from .terms import Term

    # The substitution a rule match produces: metavariable name -> bound Term.
    Binding = dict[str, Term]

    # A predicate argument is either a metavariable *name* (resolved against the
    # binding) or a pre-parsed literal *term* (which may itself contain the rule's
    # metavariables as Vars, substituted from the binding at check time). See
    # `_resolve`. The surface parser decides which at compile time.
    TermArg = str | Term


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

    needle: TermArg
    haystack: TermArg

    def check(self, binding: Binding, context: Context) -> bool:
        return _occurs(
            _resolve(self.needle, binding, context),
            _resolve(self.haystack, binding, context),
            context,
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

    left: TermArg
    right: TermArg
    sort: Constructor | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        left = _leaves(_resolve(self.left, binding, context), context, self.sort)
        right = _leaves(_resolve(self.right, binding, context), context, self.sort)
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

    name: TermArg
    sort: Constructor | None = None

    def check(self, binding: Binding, context: Context) -> bool:
        term = _resolve(self.name, binding, context)
        if not _is_atom(term):
            return False
        return self.sort is None or sort_admits(self.sort, term)


@dataclass(frozen=True)
class IsMember(SideCondition):
    """The term bound to ``name`` belongs to sort ``sort``.

    Generic: the same sort test the unifier applies when a metavariable binds
    (:func:`~website.logical.kernel.unify.sort_admits`), *without* :class:`IsAtom`'s extra atomicity guard — so
    a compound term of the sort qualifies. It earns its keep only when a slot's
    declared binding is broader than the guard needs: e.g. a metavariable bound to
    a union sort that a rule must pin to one member sort, where ``atom`` would
    wrongly reject any compound member.

    FOL: ``IsMember("t", term)`` asserts ``t`` is a term (variable *or* compound),
    unlike ``IsAtom("t", term)`` which additionally forces it to be a leaf.
    """

    name: TermArg
    sort: Constructor

    def check(self, binding: Binding, context: Context) -> bool:
        return sort_admits(self.sort, _resolve(self.name, binding, context))


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

    left: TermArg
    right: TermArg

    def check(self, binding: Binding, context: Context) -> bool:
        return _resolve(self.left, binding, context).equal(
            _resolve(self.right, binding, context), context
        )


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


def restate(condition: SideCondition, binding: Binding, context: Context) -> SideCondition:
    """``condition`` re-expressed over whatever ``binding`` maps its names to.

    A proviso names its subject by metavariable, so it can only be checked in the
    match that binds those names. Carrying one *out* of that match - into a rule
    or definition with metavariables of its own - means restating it: each name is
    replaced by the term it stands for there, which may itself mention the outer
    metavariables and is resolved when the outer match runs.

    The one caller is a definition citing a proved theorem as its justification
    (``declarative``): the theorem's provisos are stated in the theorem's
    variables, and the definition inherits them stated in its own. Distinct from
    :func:`_resolve`, which resolves an argument all the way to a *ground* term
    for an immediate check; this one deliberately stops short of ground.

    Exhaustive over the algebra, and unknown members raise rather than pass
    through unchanged - an unrestated proviso would silently read the outer
    binding for a name that means something else there.
    """
    if isinstance(condition, Occurs):
        return Occurs(
            _restated(condition.needle, binding, context),
            _restated(condition.haystack, binding, context),
        )
    if isinstance(condition, DisjointLeaves):
        return DisjointLeaves(
            _restated(condition.left, binding, context),
            _restated(condition.right, binding, context),
            condition.sort,
        )
    if isinstance(condition, IsAtom):
        return IsAtom(_restated(condition.name, binding, context), condition.sort)
    if isinstance(condition, IsMember):
        return IsMember(_restated(condition.name, binding, context), condition.sort)
    if isinstance(condition, Equal):
        return Equal(
            _restated(condition.left, binding, context),
            _restated(condition.right, binding, context),
        )
    if isinstance(condition, Not):
        return Not(restate(condition.inner, binding, context))
    if isinstance(condition, And):
        return And(tuple(restate(part, binding, context) for part in condition.parts))
    if isinstance(condition, Or):
        return Or(tuple(restate(part, binding, context) for part in condition.parts))
    raise ValueError(f"Cannot restate side-condition of type {type(condition).__name__}.")


def references(condition: SideCondition) -> set[str]:
    """Every metavariable name ``condition`` reads, by name or through a term.

    What a match must bind for the condition to be checkable at all - a name it
    does not cover makes :func:`_resolve` raise rather than return a verdict. A
    caller attaching a proviso to something (a definition, say) uses this to
    refuse a mismatch when the proviso is *written*, instead of leaving it to
    surface as an exception on some later step.

    Exhaustive over the algebra for the same reason :func:`restate` is: a member
    that fell through would under-report, and under-reporting here reads as "this
    proviso is fine".
    """
    if isinstance(condition, Occurs):
        return _referenced(condition.needle) | _referenced(condition.haystack)
    if isinstance(condition, DisjointLeaves):
        return _referenced(condition.left) | _referenced(condition.right)
    if isinstance(condition, (IsAtom, IsMember)):
        return _referenced(condition.name)
    if isinstance(condition, Equal):
        return _referenced(condition.left) | _referenced(condition.right)
    if isinstance(condition, Not):
        return references(condition.inner)
    if isinstance(condition, (And, Or)):
        return set().union(*(references(part) for part in condition.parts)) \
            if condition.parts else set()
    raise ValueError(
        f"Cannot read the references of a side-condition of type "
        f"{type(condition).__name__}."
    )


def _referenced(arg: TermArg) -> set[str]:
    """The metavariable names one predicate argument reads - see :func:`references`."""
    return {arg} if isinstance(arg, str) else set(arg.free_vars())


def _restated(arg: TermArg, binding: Binding, context: Context) -> Term:
    """One predicate argument, restated - see :func:`restate`.

    Unlike :func:`_resolve` the result may still carry ``Var`` leaves: they are
    the *outer* metavariables the restated condition is now written over, and are
    substituted when that match runs.

    Which is why a term argument's own variables are checked *before* the
    substitution rather than after: an unbound one survives it looking exactly
    like an outer metavariable, and would then be read against the outer binding,
    where the same spelling means something else entirely.
    """
    if isinstance(arg, str):
        return _bound(binding, arg)
    unbound = sorted(name for name in arg.free_vars() if name not in binding)
    if unbound:
        raise ValueError(
            "Side-condition term references metavariable(s) the match did not "
            f"bind: {', '.join(unbound)}."
        )
    return arg.substitute(binding, context)


def _bound(binding: Binding, name: str) -> Term:
    """Look up a metavariable's bound term, or fail loudly on a malformed
    condition (one naming a metavariable the rule never binds)."""
    if name not in binding:
        raise ValueError(
            f"Side-condition references '{name}', which the rule match did not bind."
        )
    return binding[name]


def _resolve(arg: TermArg, binding: Binding, context: Context) -> Term:
    """Resolve a predicate argument to a concrete term against the match binding.

    A ``str`` is a metavariable name looked up in the binding (fail-loud if
    unbound). A pre-parsed ``Term`` is a literal argument — possibly containing
    the rule's metavariables as ``Var`` nodes — so the binding is substituted into
    it, yielding the ground term to compare (defined symbols stay opaque
    constructors: no unfolding). ``equal``/``_occurs`` do not treat an unbound
    ``Var`` as a wildcard, so the term must be fully substituted first.
    """
    if isinstance(arg, str):
        return _bound(binding, arg)
    ground = arg.substitute(binding, context)
    # A term argument may only reference metavariables the match actually bound.
    # Any left-over Var means the proviso names something the match didn't
    # determine — a malformed condition, which must fail loud (the caller fails
    # closed) rather than compare a term with wildcard leaves and pass vacuously.
    unbound = ground.free_vars()
    if unbound:
        raise ValueError(
            "Side-condition term references metavariable(s) the rule match did not "
            f"bind: {', '.join(sorted(unbound))}."
        )
    return ground


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


def _leaves(term: Term, context: Context, sort: Constructor | None) -> set[str]:
    """The surface strings of ``term``'s atomic leaves, optionally restricted to
    those of ``sort``.

    For a formula like ``P(x)`` this is ``{"P", "x"}`` unrestricted, or ``{"x"}``
    with ``sort=setvar`` - which is what makes :class:`DisjointLeaves` behave as
    a variable-occurrence check rather than a whole-symbol check.
    """
    found: set[str] = set()

    def walk(node: Term) -> None:
        if isinstance(node, Var):
            if sort is None or sort_admits(sort, node):
                found.add(node.name)
            return
        if isinstance(node, Node) and not node.children:
            if sort is None or sort_admits(sort, node):
                found.add(node.literal if node.literal is not None else node.to_string())
            return
        if isinstance(node, Node):
            for child in node.children.values():
                walk(child)

    walk(term)
    return found
