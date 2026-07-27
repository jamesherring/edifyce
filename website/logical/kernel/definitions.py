"""Definitions as cited axioms: verifying a single definitional unfold.

Steps 1-3 gave the kernel a term representation, first-order matching, and a
closed proviso vocabulary. Step 4 adds definitions - and does so the way
Metamath does: a definition is an ordinary axiom (a *vertex* in the theory
graph), and a proof step that moves between a defined form and its defining
form must **cite** it. The kernel verifies that one step; it never unfolds
definitions on its own. In particular ``equal`` and ``unify`` stay purely
structural - there is no "equal modulo definitions" mode hidden in the matcher.

A :class:`Definition` is a pair of term-schemas ``(higher, lower)`` sharing
variables, plus an optional **side-condition** drawn from :mod:`side_conditions`.

Capture-avoidance - abstract bound variables
--------------------------------------------
A defining form may bind variables (the ``z`` in ``∀z.(z ∈ x → z ∈ y)``). A
naive unfold of ``z ⊆ b`` would substitute ``x := z`` and produce
``∀z.(z ∈ z → z ∈ b)`` - the free ``z`` *captured* by ``∀z``, silently changing
the meaning.

A definition therefore declares its bound variables as ``fresh``, and its
defining form stores them *abstractly*, by index (see
:class:`~website.logical.kernel.terms.Bound`): ``∀[0].([0] ∈ x → [0] ∈ y)``. The
*consumer* of an unfold then chooses the concrete name each binder takes,
subject to a disjoint-variable proviso (Metamath's ``$d``, auto-generated from
``fresh`` and expressed with the step-3 ``DisjointLeaves`` vocabulary): the
chosen name must be disjoint from every parameter's substitution and from the
other chosen names. So unfolding ``z ⊆ b`` with the fresh name ``w`` yields
``∀w.(w ∈ z → w ∈ b)`` - the capture is avoided by *renaming the binder*, not by
rejecting the application. Reusing ``z`` itself is what the proviso forbids
(``z`` is not disjoint from the argument ``z``), so a naming that *would*
capture is still rejected; only a genuinely fresh choice is admitted. In
:func:`check_definitional_step` the chosen name is not supplied separately - it
is *recovered* from the target term the step is checked against.

A definition's *own* proviso may constrain a binder too, by the name its author
declared it under: the check runs once the binders are resolved, and each one's
chosen leaf is exposed under that name (:func:`_condition_binding`). What a
proviso naming ``z`` means is therefore "whatever this binder is called here",
which is the only thing it could sensibly mean - an abstract binder has no fixed
name to constrain.

Worth stating what this representation *removes*, because it is more than
capture-avoidance. A definition whose defining form binds a dummy makes no choice
of name at all, so there is nothing to prove about the choice. Metamath, whose
defining forms are named, must instead carry the proof as a hypothesis - `df-sb`'s
``$e sbjust.1`` says exactly that its dummy is immaterial. Here that follows from
two unfolds of the same defined form rather than preceding the definition (see
``declarative.Justification`` and the roadmap's A4, which also records why
`set.mm` declines to rely on it).

Two operations, both built entirely from steps 1-3:

* :func:`unfold` - match the ``higher`` schema against a term, check the
  side-condition, and substitute the binding into ``lower``. One application.
* :func:`check_definitional_step` - verify that one term is the other with a
  single definitional unfold applied at one position (in either direction).

This is decidable and terminating by construction: each cited step is exactly
one unfold followed by a structural compare. Searching for *which* definition
applies *where* - to keep proofs terse - is the elaboration layer's job; the
trusted core only ever checks a step it is handed.

Everything here is stated over *terms*. Building a definition from the two
surface forms an author writes is ``formal_system.definitions.parse_definition``,
and a binder's chosen name arrives as the leaf it denotes rather than the string
that spells it - so no grammar is consulted while a step is being checked.

Admissibility - what an unfold may introduce
--------------------------------------------
:func:`unbound_parameters` and :func:`introduced_leaves` answer the structural
half of whether a definition is *admissible* at all, over the same two schemas.
Both express one property: **an unfold must preserve free variables**. If every
leaf of ``lower`` is either a parameter ``higher`` provides or a binder declared
``fresh``, then the unfolded term's free variables are exactly the redex's, so
the step means the same thing wherever it is taken. A defining form that
introduces a name from nowhere breaks that: ``S := (a ∈ b)`` unfolded under
``∀a`` yields ``∀a.(a ∈ b)``, capturing an ``a`` that was free in ``S``. No
proviso can repair it, because the constraint is on where the defined form may
*occur*, which a cited step does not see.

The kernel reports the offending leaves; it does not decide which are benign.
Telling a constant of the object language (``⊥``) from a variable is a question
about the grammar, so the layer that owns the grammar filters (see
``formal_system/definitions.py``).

Scope: this is the *capture* half of admissibility. Conservativity - that the
defined symbol is fresh and the definition non-circular - is still untreated: as
in Metamath, admitting a definition trusts it as an axiom.

Worked example - subset
-----------------------
Definition ``df-subset``:  ``(x ⊆ y)  :=  ∀z.(z ∈ x → z ∈ y)``.  A proof::

    1.  a ⊆ b                        [premise]
    2.  ∀z.(z ∈ a → z ∈ b)           [df-subset, 1]     # cited unfold

is checked by ``check_definitional_step(term("a ⊆ b"), term("∀z.(z ∈ a → z ∈ b)"),
df_subset, context)`` - which unfolds ``a ⊆ b`` (binding ``x:=a, y:=b``) and
compares the result to line 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .side_conditions import And, DisjointLeaves
from .terms import Node, _bound, _bound_label, _node
from .unify import match, sort_admits

if TYPE_CHECKING:
    from ..matching.context import Context
    from .constructors import Constructor
    from .side_conditions import SideCondition
    from .terms import Binding, Bound, Term


@dataclass(frozen=True)
class FreshBinder:
    """A defining form's declared bound variable, as kernel data.

    ``name`` is what the definition's author called it - the key an unfold names
    to rename that binder. ``sort`` is the sort it ranges over, and ``default``
    the leaf its declared name denotes: the name the binder keeps when an unfold
    chooses none, which is the reject-collision fallback.

    ``default`` is a *term* because deciding it is a parsing question, settled
    once when the definition is built (``formal_system.definitions``). Holding the
    answer rather than the sort to re-parse against is what keeps the kernel free
    of the grammar at check time.

    ``scoped`` says how the binder was placed, and the two answers have different
    scopes. A **scoped** binder (:func:`bind_scoped`) binds only within the slots
    the grammar declared it to reach, and ``enclosing`` names the binders it sits
    inside, by index. A binder placed **by name**
    (:func:`~website.logical.kernel.terms.bind`, which is what a declared
    ``fresh`` clause still uses) binds every occurrence of its spelling, so its
    scope is the whole defining form and ``enclosing`` says nothing.

    That distinction is what makes the freshness proviso scope-sensitive: a binder
    must differ from the binders whose scope contains it, and need not differ from
    one in a disjoint scope. ``(∀z.P → ∀z.Q)`` is two scoped binders that may share
    a name; ``∀z.∀z.P`` is two that may not; and a name-bound binder must differ
    from all of them, since its scope covers them.
    """

    name: str
    sort: Constructor
    default: Term
    enclosing: tuple[int, ...] = ()
    scoped: bool = False


@dataclass(frozen=True)
class Definition:
    """A definitional axiom: the defined form ``higher`` equals the defining
    form ``lower`` (both term-schemas over shared variables), subject to an
    optional side-condition.

    ``higher`` and ``lower`` are :class:`~website.logical.kernel.terms.Term`
    schemas - i.e. they contain :class:`~website.logical.kernel.terms.Var`
    leaves for the definition's parameters. For ``df-subset`` above, ``higher``
    is the term for ``x ⊆ y`` and ``lower`` the term for ``∀z.(z ∈ x → z ∈ y)``,
    sharing the variables ``x`` and ``y``.

    ``fresh`` names the defining form's bound variables (see :class:`FreshBinder`),
    one entry for ``df-subset``'s ``z``. In ``lower`` each is stored as an
    abstract, indexed :class:`~website.logical.kernel.terms.Bound` node (in
    ``fresh`` order), so an unfold's consumer chooses each binder's concrete name;
    from ``fresh`` the kernel generates the disjoint-variable proviso that keeps
    that choice capture-free (see the module docstring). ``condition`` is any
    *additional* proviso, checked against the binding an application produces.
    """

    higher: Term
    lower: Term
    condition: SideCondition | None = None
    fresh: tuple[FreshBinder, ...] = ()
    # The name a proof cites this definition by (`[<label>, <line>]`), or None
    # for an unnamed one (still reachable through the generic keyword). It lives
    # here, not on the notation that parses the defined form, because a citation
    # names an *axiom*: two definitions may share one defined form, and each
    # stays separately citable.
    label: str | None = None


def _leaf_name(term: Term) -> str | None:
    """The surface name of a ground leaf, or ``None`` for anything else."""
    if isinstance(term, Node) and not term.children:
        return term.literal
    return None


def bind_scoped(term: Term, first_index: int) -> tuple[Term, tuple[FreshBinder, ...]]:
    """Bind each leaf sitting in a binder slot to its own indexed
    :class:`~website.logical.kernel.terms.Bound`, *within that binder's declared
    scope only*.

    This is what the grammar's ``scopes_over`` buys the term layer. The older
    :func:`~website.logical.kernel.terms.bind` keys on the surface string, so a
    binder rewrites its name everywhere the defining form spells it — which is
    right only when every occurrence happens to be in scope, and silently wrong
    when one is not. Here an occurrence outside the scope is simply left alone:
    it stays a ground leaf, and ``introduced_leaves`` reports it as the free name
    it is.

    Two consequences follow from binding *per occurrence* rather than per name.
    ``(∀z.P(z) → ∀z.Q(z))`` becomes two independent binders, so an unfold may
    spell them differently — they are separate binders that happen to share a
    name, and alpha-variance says so. And two binder slots of *different sorts*
    holding the same name are two binders with their own sorts, rather than one
    carrying whichever sort was seen first.

    ``first_index`` is where this allocation starts, so a caller that has already
    placed binders (a declared ``fresh`` clause, still bound by name) can append
    to them without colliding. Returns the rewritten term and the binders it
    allocated, in allocation order — a pre-order walk, so the indices are a
    function of the defining form alone.
    """
    binders: list[FreshBinder] = []

    def walk(current: Term, env: dict[str, Bound], enclosing: tuple[int, ...]) -> Term:
        if not isinstance(current, Node):
            # A Var is a parameter the defined form supplies; a Bound is already
            # placed. Neither spells a leaf this walk may bind.
            return current
        if not current.children:
            name = current.literal
            return env[name] if name is not None and name in env else current

        # Open a binder for each binder slot holding a name, then hand each child
        # only the bindings that actually reach it: the binder's own slot, and the
        # slots it was declared to scope over.
        scoped: dict[str, dict[str, Bound]] = {label: env for label in current.children}
        opened: dict[str, tuple[int, ...]] = {label: enclosing for label in current.children}

        opening: list[tuple[str, tuple[str, ...], str, Term]] = []
        for slot, targets in current.constructor.scopes_over.items():
            child = current.children.get(slot)
            if child is None:
                continue
            name = _leaf_name(child)
            if name is not None:
                opening.append((slot, targets, name, child))

        # Two sibling slots binding *the same* leaf is not a form with a meaning.
        # They are simultaneous rather than nested, so neither shadows the other,
        # and an occurrence in the scope they share belongs to neither in
        # particular — the walk below would hand it to whichever slot the grammar
        # happened to list second. Refused rather than resolved by declaration
        # order, which is not something an author can see.
        claimed: dict[str, str] = {}
        for slot, _targets, name, _child in opening:
            if name in claimed:
                raise ValueError(
                    f"Binder slots {claimed[name]!r} and {slot!r} of "
                    f"{current.constructor.name!r} both bind {name!r} in the "
                    f"defining form. Neither shadows the other, so an occurrence "
                    f"of {name!r} in the scope they share belongs to neither. "
                    f"Give the two binders different names."
                )
            claimed[name] = slot

        # Binders opened at *one* node constrain each other, whatever the nesting
        # says. A production with two binder slots (`⟪u,v⟫.phi`) scopes both over
        # the same body, so spelling them alike would merge two binders into one —
        # and neither is "inside" the other, so nesting alone would not catch it.
        # Deliberately blanket across siblings rather than restricted to those
        # whose targets actually overlap: two binders on one production are meant
        # to be distinct, and refusing a hypothetical grammar that wanted
        # otherwise is the safe direction.
        base = first_index + len(binders)
        siblings = tuple(range(base, base + len(opening)))
        for offset, (slot, targets, name, child) in enumerate(opening):
            index = base + offset
            sort = current.constructor.slot_sorts[slot]
            binders.append(
                FreshBinder(
                    name=name, sort=sort, default=child,
                    enclosing=(*enclosing, *(s for s in siblings if s != index)),
                    scoped=True,
                )
            )
            node = _bound(index, sort)
            for label in (slot, *targets):
                if label not in current.children:
                    continue
                scoped[label] = {**scoped[label], name: node}
                opened[label] = (*opened[label], index)

        return _node(
            constructor=current.constructor,
            children={
                label: walk(child, scoped[label], opened[label])
                for label, child in current.children.items()
            },
            sort=current.sort,
        )

    return walk(term, {}, ()), tuple(binders)


def _ground_leaves(term: Term) -> list[Node]:
    """Every ground leaf of ``term``: a childless :class:`Node` carrying a literal.

    Variables are excluded - :meth:`Term.free_vars` is the traversal for those.
    (Named for what it collects, to stay clear of :mod:`side_conditions`'
    same-named helper, which yields sort-restricted surface *strings*.)
    """
    if not isinstance(term, Node):
        return []
    if not term.children:
        return [term] if term.literal is not None else []
    return [leaf for child in term.children.values() for leaf in _ground_leaves(child)]


def unbound_parameters(definition: Definition) -> tuple[str, ...]:
    """Parameter names the defining form uses that the defined form does not
    provide, in sorted order.

    This is the free-variable-preservation property stated directly: an unfold
    binds parameters by matching ``higher`` against the redex, so a variable free
    in ``lower`` alone is never determined by the step. It would be free in the
    result, and free in a way the surrounding term could capture.

    A binder declared ``fresh`` is not a parameter - its name is chosen by the
    step, not supplied by ``higher`` - and :meth:`Bound.free_vars` already says
    so, so no special case is needed here.
    """
    introduced = set(definition.lower.free_vars()) - set(definition.higher.free_vars())
    return tuple(sorted(introduced))


def introduced_leaves(definition: Definition) -> tuple[Node, ...]:
    """The ground leaves the defining form spells out that the defined form does
    not, deduplicated by surface literal and ordered by it.

    Each is a token the unfold conjures from nothing. Some are harmless - a
    constant of the object language (``⊥``, ``∅``) denotes one fixed thing and
    can be neither renamed nor captured - and some are not: an undeclared binder,
    or a free variable. Distinguishing them needs the grammar, so that is the
    caller's to do; what the kernel settles is *which* leaves are unaccounted for.

    A binder declared ``fresh`` is stored abstractly (a
    :class:`~website.logical.kernel.terms.Bound`, a variable rather than a ground
    leaf) and so is never reported - being declared is exactly what makes it safe.

    Leaves are matched by **constructor and literal**, the same pair
    :meth:`Term.equal` compares a ground leaf by - not by surface spelling alone.
    One token can be built by two different productions (a nullary notation ``S``
    of ``formula``, and ``S`` as a ``setvar``), and those are different terms: the
    defined form mentioning one must not excuse the defining form introducing the
    other, or a variable slips through as though it were already accounted for.
    """
    def key(leaf: Node) -> tuple[tuple[str, ...], str | None]:
        return (leaf.constructor.signature, leaf.literal)

    defined = {key(leaf) for leaf in _ground_leaves(definition.higher)}
    introduced: dict[tuple[tuple[str, ...], str | None], Node] = {}
    for leaf in _ground_leaves(definition.lower):
        if key(leaf) not in defined:
            introduced.setdefault(key(leaf), leaf)
    return tuple(sorted(introduced.values(), key=lambda leaf: leaf.literal or ""))


def unfold(
    definition: Definition,
    redex: Term,
    context: Context,
    names: dict[str, Term] | None = None,
) -> Term | None:
    """Apply ``definition`` to ``redex`` once (defined form -> defining form).

    ``names`` maps a binder to the leaf it should take in the result, keyed
    either by its reserved index label (:func:`~website.logical.kernel.terms._bound_label`)
    or by its ``fresh`` name - ``{"z": <term w>}`` to unfold
    ``z ⊆ b`` as ``∀w.(w ∈ z → w ∈ b)``. Terms, not strings: naming a binder is a
    choice about the *term*, and reading a name out of a string would put the
    grammar back in the trusted core. An unnamed binder keeps its declared name
    (:attr:`FreshBinder.default`); that is the reject-collision fallback
    (unfolding ``z ⊆ b`` without renaming ``z`` fails the freshness proviso).

    Returns the unfolded term, or ``None`` if ``redex`` is not an instance of the
    definition's ``higher`` form, a chosen bound name would capture (violating the
    disjoint-variable proviso), or the side-condition fails. Reuses only
    :func:`~website.logical.kernel.unify.match`, the side-condition check, and
    :meth:`Term.substitute`.
    """
    binding = match(definition.higher, redex, context)
    if binding is None:
        return None
    bound_binding = _resolve_bound_names(definition, names)
    if bound_binding is None:
        # A chosen name is not a leaf of its binder's sort.
        return None
    # Checked *after* the binders are resolved, so a proviso may constrain one.
    # A binder has no fixed name to write a proviso about - that is the point of
    # storing it abstractly - so what a proviso naming `z` means is "whatever this
    # binder is called at this unfold", which is exactly what resolution just
    # settled. Before, the condition saw the parameters alone and a `z` in it could
    # only ever mean the literal leaf spelled `z`.
    if definition.condition is not None and not definition.condition.check(
        _condition_binding(definition, binding, bound_binding), context
    ):
        return None
    if not _bounds_are_fresh(definition, binding, bound_binding, context):
        return None
    # Parameters and binders substitute in one pass: their keys are disjoint
    # (a binder's key is the reserved, index-derived name a `Bound` carries).
    return definition.lower.substitute({**binding, **bound_binding}, context)


def _condition_binding(
    definition: Definition, binding: Binding, bound_binding: Binding
) -> Binding:
    """The binding a definition's own proviso is checked against.

    The ``higher``-form parameters, plus each binder's chosen name under the name
    its author declared it by - so ``disjoint(z, x)`` on a definition whose
    ``fresh`` clause names ``z`` constrains *that binder*, whatever leaf it ends up
    taking, rather than the literal token ``z``. The reserved index keys
    :func:`_bounds_are_fresh` uses are deliberately not exposed here: they are the
    kernel's own handle on a binder, and an author writes the name.

    A parameter wins a spelling collision, being what the redex actually supplied.
    A definition whose ``fresh`` name is also a parameter is confused about that
    name for reasons older than any proviso (``bind`` abstracts *every* occurrence
    of the spelling, the parameter's included), so nothing here tries to rescue it.
    """
    if not definition.fresh:
        return binding
    named = {
        binder.name: bound_binding[_bound_label(index)]
        for index, binder in enumerate(definition.fresh)
        if _bound_label(index) in bound_binding
    }
    return {**named, **binding}


def _resolve_bound_names(
    definition: Definition, names: dict[str, Term] | None
) -> Binding | None:
    """The binding that instantiates each abstract binder to its chosen concrete
    leaf, taken from ``names`` and falling back to the binder's declared default.

    Each choice is checked structurally - a childless leaf, of a sort the binder
    admits - so a caller cannot smuggle in a term that is not a name of that sort
    (a compound ``(a ∈ b)``, or a leaf of the wrong sort). A choice that fails
    yields ``None``, rejecting the unfold rather than binding a bogus leaf. That
    check used to be a *parse* of the chosen string against the binder's sort
    pattern, which is the same question asked of the grammar instead of the term.
    """
    resolved: Binding = {}
    for index, binder in enumerate(definition.fresh):
        key = _bound_label(index)
        chosen = binder.default
        if names is not None:
            # By index first, then by name. Binders are placed per *occurrence*
            # now, so several may share a spelling — `(∃z.… → ∀z.…)` over two
            # sorts is two binders both called `z`, and only the index tells them
            # apart. Naming by spelling still works, and still renames every
            # binder of that spelling together, which is what a caller wanting
            # one consistent rename means; it is simply unable to say more.
            chosen = names.get(key, names.get(binder.name, binder.default))
        if not _names_a_leaf_of(chosen, binder.sort):
            return None
        resolved[key] = chosen
    return resolved


def _names_a_leaf_of(term: Term, sort: Constructor) -> bool:
    """Whether ``term`` is something a binder of ``sort`` could be called: a
    ground leaf the sort admits.

    "Ground leaf" is the same three-part test :func:`_ground_leaves` applies -
    a childless node that *carries a literal*. The literal is what makes it a
    name: a childless node without one spells nothing, so it could not be the
    binder a reader sees.
    """
    return (
        isinstance(term, Node)
        and not term.children
        and term.literal is not None
        and sort_admits(sort, term)
    )


def _bounds_are_fresh(
    definition: Definition, binding: Binding, bound_binding: Binding, context: Context
) -> bool:
    """Whether the chosen bound names avoid capture - the ``$d`` proviso.

    Each bound variable's chosen name (looked up in ``bound_binding``) must be
    disjoint from every ``higher``-form parameter's substitution, and from the
    chosen names of the binders it sits *inside*. We expose the chosen names in
    the binding (as their own leaves, under their reserved keys) so
    ``DisjointLeaves`` can reference them alongside the parameters.

    **Parameters: every binder, always.** A parameter's substitution is whatever
    the redex supplied, and the unfold drops it into the defining form wherever
    that parameter occurs; a binder spelled the same would capture it. Which
    parameters occur inside which binder's scope is knowable, but requiring all of
    them is the conservative reading and is what this has always done.

    **Binders: only where the scopes nest.** Two binders in disjoint scopes cannot
    capture each other - nothing in one's scope is in the other's - so
    ``(∀z.P → ∀z.Q)`` may spell both ``z``. Requiring every pair to differ would
    reject that, and it is a term the older name-keyed representation accepted
    (as a single binder), so a blanket pairwise check would be a regression rather
    than a tightening. ``∀z.∀z.P`` *does* nest, and is still refused: the inner
    would shadow the outer.

    ``FreshBinder.enclosing`` carries the relation, and is empty for a binder
    placed by name across the whole form (a declared ``fresh`` clause) - which
    reproduces the old blanket behaviour for those, since a name-bound binder's
    scope is everything.
    """
    if not definition.fresh:
        return True

    parameters = tuple(binding)  # the higher form's variables
    combined = {**binding, **bound_binding}
    provisos: list[DisjointLeaves] = []
    # A binder placed by *name* has no recorded scope because its scope is the
    # whole defining form - so it both encloses and is enclosed by every other
    # binder, which is the blanket pairwise rule the name-keyed representation
    # always applied. Keeping it that way is what makes a declared `fresh` clause
    # behave exactly as it did.
    unscoped = {
        index for index, binder in enumerate(definition.fresh) if not binder.scoped
    }
    for index, binder in enumerate(definition.fresh):
        key = _bound_label(index)
        if key not in bound_binding:
            # The step never pinned this binder's concrete name (e.g. a target
            # whose structure did not determine it): nothing to admit.
            return False
        provisos.extend(
            DisjointLeaves(key, parameter, sort=binder.sort) for parameter in parameters
        )
        others = set(binder.enclosing)
        if binder.scoped:
            # A name-placed binder's scope is the whole form, so it encloses
            # every scoped one.
            others |= unscoped
        else:
            # Between two name-placed binders, state the pair once, from the
            # later one — exactly the rule that applied before binders had
            # scopes, so a definition with only a declared `fresh` clause
            # generates the same provisos it always did.
            others |= {other for other in unscoped if other < index}
        provisos.extend(
            DisjointLeaves(key, _bound_label(other), sort=binder.sort)
            for other in sorted(others)
        )

    return And(tuple(provisos)).check(combined, context)


def check_definitional_step(
    before: Term, after: Term, definition: Definition, context: Context
) -> bool:
    """Verify ``after`` is ``before`` with a single unfold of ``definition``
    applied at one position - in either direction (unfold or fold).

    "Either direction" mirrors the two ways a proof may use a definition:
    expanding the defined form (``before`` is the redex) or contracting to it
    (``after`` is). Exactly one occurrence may change; everything else must be
    structurally equal.
    """
    return _rewrites_once(before, after, definition, context) or _rewrites_once(
        after, before, definition, context
    )


def _unfolds_to(definition: Definition, source: Term, target: Term, context: Context) -> bool:
    """Whether unfolding ``source`` at the root yields ``target``, with any bound
    names *recovered from* ``target`` rather than supplied.

    Because the defining form carries its binders abstractly, matching the
    parameter-substituted ``lower`` against ``target`` recovers each binder's
    concrete name in ``target`` (a :class:`~website.logical.kernel.terms.Bound`
    behaves as a schematic variable during the match) - and, threading one
    binding, forces a binder to be spelled *consistently* everywhere it occurs.
    The recovered names are then held to the same freshness proviso an explicit
    unfold applies.
    """
    binding = match(definition.higher, source, context)
    if binding is None:
        return False

    # Recover each binder's concrete name by matching the defining form against
    # the claimed target, *seeded with the parameter binding* so the parameters
    # stay pinned. Without the seed, a schema source (whose parameters are still
    # `Var` leaves in ``lower``) would let the match rebind them to whatever the
    # target holds - turning "one unfold" into "unfold *and* instantiate the
    # parameters", which is not a definitional step.
    recovered = match(definition.lower, target, context, binding=dict(binding))
    if recovered is None:
        return False
    # Only the declared binders may be newly determined by the target; anything
    # else newly bound means the match reached past the binders (e.g. an
    # ill-formed defining form with a free parameter), so reject the step.
    bound_keys = {_bound_label(index) for index in range(len(definition.fresh))}
    if set(recovered) - set(binding) - bound_keys:
        return False
    bound_binding = {key: recovered[key] for key in bound_keys if key in recovered}
    # Checked once the binders are recovered, as :func:`unfold` checks it once they
    # are chosen, and for the same reason: a proviso may constrain a binder, and
    # here the name it takes is read off the target rather than supplied.
    if definition.condition is not None and not definition.condition.check(
        _condition_binding(definition, binding, bound_binding), context
    ):
        return False
    if not _bounds_are_fresh(definition, binding, bound_binding, context):
        return False
    return definition.lower.substitute(recovered, context).equal(target, context)


def _rewrites_once(source: Term, target: Term, definition: Definition, context: Context) -> bool:
    """Whether ``source`` unfolds (higher -> lower) to ``target`` at exactly one
    position."""
    # (1) The rewrite happens at the root: source is the redex (its binders named
    # to match the target).
    if _unfolds_to(definition, source, target, context):
        return True

    # (2) The rewrite happens strictly inside: source and target must share a
    # constructor and differ in exactly one child, where the rewrite recurses.
    if not (isinstance(source, Node) and isinstance(target, Node)):
        return False
    if source.constructor.signature != target.constructor.signature:
        return False
    if source.literal is not None or target.literal is not None:
        return False

    source_locations = source.constructor.slots
    target_locations = target.constructor.slots
    if len(source_locations) != len(target_locations):
        return False

    differing: tuple[str, str] | None = None
    for source_label, target_label in zip(source_locations, target_locations):
        if source_label not in source.children or target_label not in target.children:
            return False
        if source.children[source_label].equal(target.children[target_label], context):
            continue
        if differing is not None:
            # More than one position differs: not a single-step rewrite.
            return False
        differing = (source_label, target_label)

    if differing is None:
        # source and target are already equal: no rewrite occurred.
        return False

    source_label, target_label = differing
    return _rewrites_once(
        source.children[source_label], target.children[target_label], definition, context
    )
