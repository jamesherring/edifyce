"""Definitions as cited axioms: verifying a single definitional unfold.

Steps 1-3 gave the kernel a term representation, first-order matching, and a
closed proviso vocabulary. Step 4 adds definitions - and does so the way
Metamath does: a definition is an ordinary axiom (a *vertex* in the theory
graph), and a proof step that moves between a defined form and its defining
form must **cite** it. The kernel verifies that one step; it never unfolds
definitions on its own. In particular ``equal`` and ``unify`` stay purely
structural - there is no "equal modulo definitions" mode hidden in the matcher.

A :class:`Definition` is a pair of term-schemas ``(higher, lower)`` sharing
variables, plus an optional **side-condition** drawn from :mod:`side_conditions`
(so a definition's proviso - e.g. the disjoint-variable condition that keeps an
unfold capture-free - is expressed with the step-3 vocabulary, not a bespoke
one).

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

from .terms import Node, abstract, from_match, _locations, _signature
from .unify import match

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.patterns import Pattern
    from .side_conditions import SideCondition
    from .terms import FreeVars, Term


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

    ``condition`` is checked against the binding produced when the definition is
    applied - e.g. a ``DisjointLeaves`` proviso keeping the substituted terms
    clear of the definition's bound variables (capture-avoidance).
    """

    higher: Term
    lower: Term
    condition: SideCondition | None = None

    @classmethod
    def parse(
        cls,
        sort: Pattern,
        higher: str,
        lower: str,
        variables: FreeVars,
        context: Context,
        condition: SideCondition | None = None,
    ) -> Definition:
        """Build a definition by parsing its two surface forms.

        ``sort`` is the ``Pattern`` both forms parse against (e.g. the ``formula``
        union); ``variables`` maps each parameter name to its sort; ``context``
        is an ordinary ground parsing context. Each form is parsed through the
        grammar and its parameters abstracted (see
        :func:`~website.logical.kernel.terms.abstract`), so a multi-level
        defining form keeps its structure - which is why this uses parse +
        abstract rather than ``from_pattern`` (see that helper's note).

        The engine's legacy condition DSL is not translated: pass a step-3
        ``condition`` explicitly if the definition carries a proviso.
        """

        def schema(text: str) -> Term:
            matched = sort.match(text, context)
            if matched is None:
                raise ValueError(f"Definition form {text!r} does not parse as '{sort.name}'.")
            return abstract(from_match(matched, context), variables)

        return cls(higher=schema(higher), lower=schema(lower), condition=condition)


def unfold(definition: Definition, redex: Term, context: Context) -> Term | None:
    """Apply ``definition`` to ``redex`` once (defined form -> defining form).

    Returns the unfolded term, or ``None`` if ``redex`` is not an instance of
    the definition's ``higher`` form or the side-condition fails. Reuses only
    :func:`~website.logical.kernel.unify.match`, the side-condition check, and
    :meth:`Term.substitute`.
    """
    binding = match(definition.higher, redex, context)
    if binding is None:
        return None
    if definition.condition is not None and not definition.condition.check(binding, context):
        return None
    return definition.lower.substitute(binding, context)


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


def _rewrites_once(source: Term, target: Term, definition: Definition, context: Context) -> bool:
    """Whether ``source`` unfolds (higher -> lower) to ``target`` at exactly one
    position."""
    # (1) The rewrite happens at the root: source is the redex.
    unfolded = unfold(definition, source, context)
    if unfolded is not None and unfolded.equal(target, context):
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
