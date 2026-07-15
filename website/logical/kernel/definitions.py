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

Two operations, both built entirely from steps 1-3:

* :func:`unfold` - match the ``higher`` schema against a term, check the
  side-condition, and substitute the binding into ``lower``. One application.
* :func:`check_definitional_step` - verify that one term is the other with a
  single definitional unfold applied at one position (in either direction).

This is decidable and terminating by construction: each cited step is exactly
one unfold followed by a structural compare. Searching for *which* definition
applies *where* - to keep proofs terse - is the elaboration layer's job; the
trusted core only ever checks a step it is handed.

Scope: this verifies the *use* of a definition. It does not check a
definition's *admissibility* (conservativity - that the defined symbol is fresh
and non-circular). As in Metamath, admitting a definition trusts it as an
axiom; optional well-formedness checks are a separate concern.

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
from .terms import Node, abstract, bind, from_match, _bound, _bound_label, _locations, _signature
from .unify import match

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.patterns import Pattern
    from .side_conditions import SideCondition
    from .terms import Binding, FreeVars, Term


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

    ``fresh`` names the defining form's bound variables (each with its sort),
    e.g. ``(("z", setvar),)`` for ``df-subset``. In ``lower`` each is stored as
    an abstract, indexed :class:`~website.logical.kernel.terms.Bound` node (in
    ``fresh`` order), so an unfold's consumer chooses each binder's concrete name;
    from ``fresh`` the kernel generates the disjoint-variable proviso that keeps
    that choice capture-free (see the module docstring). ``condition`` is any
    *additional* proviso, checked against the binding an application produces.
    """

    higher: Term
    lower: Term
    condition: SideCondition | None = None
    fresh: tuple[tuple[str, Pattern], ...] = ()

    @classmethod
    def parse(
        cls,
        sort: Pattern,
        higher: str,
        lower: str,
        variables: FreeVars,
        context: Context,
        condition: SideCondition | None = None,
        fresh: FreeVars | None = None,
    ) -> Definition:
        """Build a definition by parsing its two surface forms.

        ``sort`` is the ``Pattern`` both forms parse against (e.g. the ``formula``
        union); ``variables`` maps each parameter name to its sort; ``context``
        is an ordinary ground parsing context. Each form is parsed through the
        grammar and its parameters abstracted (see
        :func:`~website.logical.kernel.terms.abstract`), so a multi-level
        defining form keeps its structure - which is why this uses parse +
        abstract rather than ``from_pattern`` (see that helper's note).

        ``fresh`` maps each bound variable of the defining form to its sort (for
        ``df-subset``, ``{"z": setvar}``); in the parsed defining form each such
        variable is replaced by an abstract, indexed
        :class:`~website.logical.kernel.terms.Bound` node (in ``fresh`` order),
        and the capture-avoidance proviso is generated from it. The engine's
        legacy condition DSL is not translated: pass a step-3 ``condition``
        explicitly for any *additional* proviso.
        """
        fresh_items = tuple((fresh or {}).items())
        # Each declared bound variable becomes an abstract, indexed node; the
        # defining form (only) is rewritten to reference binders by index.
        bound_nodes = {name: _bound(index, sort) for index, (name, sort) in enumerate(fresh_items)}

        def schema(text: str, abstract_binders: bool) -> Term:
            matched = sort.match(text, context)
            if matched is None:
                raise ValueError(f"Definition form {text!r} does not parse as '{sort.name}'.")
            term = abstract(from_match(matched, context), variables)
            if abstract_binders and bound_nodes:
                term = bind(term, bound_nodes)
            return term

        return cls(
            higher=schema(higher, abstract_binders=False),
            lower=schema(lower, abstract_binders=True),
            condition=condition,
            fresh=fresh_items,
        )


def unfold(
    definition: Definition,
    redex: Term,
    context: Context,
    names: dict[str, str] | None = None,
) -> Term | None:
    """Apply ``definition`` to ``redex`` once (defined form -> defining form).

    ``names`` maps each declared bound variable (by its ``fresh`` name) to the
    concrete name its binder should take in the result, e.g. ``{"z": "w"}`` to
    unfold ``z ⊆ b`` as ``∀w.(w ∈ z → w ∈ b)``. An unnamed binder keeps its
    declared name; that is the reject-collision fallback (unfolding ``z ⊆ b``
    without renaming ``z`` fails the freshness proviso).

    Returns the unfolded term, or ``None`` if ``redex`` is not an instance of the
    definition's ``higher`` form, a chosen bound name would capture (violating the
    disjoint-variable proviso), or the side-condition fails. Reuses only
    :func:`~website.logical.kernel.unify.match`, the side-condition check, and
    :meth:`Term.substitute`.
    """
    binding = match(definition.higher, redex, context)
    if binding is None:
        return None
    if definition.condition is not None and not definition.condition.check(binding, context):
        return None
    bound_binding = _resolve_bound_names(definition, names)
    if not _bounds_are_fresh(definition, binding, bound_binding, context):
        return None
    # Parameters and binders substitute in one pass: their keys are disjoint
    # (a binder's key is the reserved, index-derived name a `Bound` carries).
    return definition.lower.substitute({**binding, **bound_binding}, context)


def _resolve_bound_names(definition: Definition, names: dict[str, str] | None) -> Binding:
    """The binding that instantiates each abstract binder to its chosen concrete
    leaf: ``{bound-key: Node(sort, literal=chosen)}``, chosen from ``names`` and
    falling back to the declared ``fresh`` name."""
    resolved: Binding = {}
    for index, (name, sort) in enumerate(definition.fresh):
        chosen = names.get(name, name) if names else name
        resolved[_bound_label(index)] = Node(pattern=sort, literal=chosen)
    return resolved


def _bounds_are_fresh(
    definition: Definition, binding: Binding, bound_binding: Binding, context: Context
) -> bool:
    """Whether the chosen bound names avoid capture - the ``$d`` proviso.

    Each declared bound variable's chosen name (looked up in ``bound_binding``)
    must be disjoint from every ``higher``-form parameter's substitution and from
    every other chosen name. We expose the chosen names in the binding (as their
    own leaves, under their reserved keys) so ``DisjointLeaves`` can reference
    them alongside the parameters.
    """
    if not definition.fresh:
        return True

    parameters = tuple(binding)  # the higher form's variables
    combined = {**binding, **bound_binding}
    provisos: list[DisjointLeaves] = []
    prior_keys: list[str] = []
    for index, (_name, sort) in enumerate(definition.fresh):
        key = _bound_label(index)
        if key not in bound_binding:
            # The step never pinned this binder's concrete name (e.g. a target
            # whose structure did not determine it): nothing to admit.
            return False
        provisos.extend(DisjointLeaves(key, parameter, sort=sort) for parameter in parameters)
        provisos.extend(DisjointLeaves(key, prior, sort=sort) for prior in prior_keys)
        prior_keys.append(key)

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
    if definition.condition is not None and not definition.condition.check(binding, context):
        return False

    # Substitute the parameters, leaving binders abstract; then recover each
    # binder's concrete name by matching the result against the claimed target.
    reified = definition.lower.substitute(binding, context)
    bound_binding = match(reified, target, context)
    if bound_binding is None:
        return False
    if not _bounds_are_fresh(definition, binding, bound_binding, context):
        return False
    return reified.substitute(bound_binding, context).equal(target, context)


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
    if _signature(source.pattern) != _signature(target.pattern):
        return False
    if source.literal is not None or target.literal is not None:
        return False

    source_locations = _locations(source.pattern)
    target_locations = _locations(target.pattern)
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
