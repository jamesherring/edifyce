"""Bridge from the legacy :class:`matching.Definition` to the kernel's
term-based definitional-step checker.

``ProofLine.follows_from_definition`` historically compared two ``Match`` trees
"up to definition" by walking them and reconciling substrings
(``Match.maps_to_up_to_definition`` / ``equivalent_under_definitions``): a step
verified by re-deriving structure from text. The kernel already has the
replacement - :func:`~website.logical.kernel.definitions.check_definitional_step`
verifies one definitional unfold structurally over the shared-DAG term
representation, with no re-parsing. This module wires the two together.

Why a *bridge* and not a straight swap
--------------------------------------
The two definition models are not the same shape:

* A legacy ``Define higher as lower`` is an *alias*: ``higher`` is alternative
  surface syntax for an instance ``lower`` of one pattern. It carries no
  declaration of the defining form's *bound* variables and its optional proviso
  is written in the engine's string condition DSL.
* A kernel :class:`~website.logical.kernel.definitions.Definition` is a
  definitional *axiom* whose defining form stores its binders abstractly (so an
  unfold is capture-avoiding) and whose proviso is drawn from the kernel's
  closed, structural side-condition vocabulary.

So a legacy definition is soundly expressible as a kernel one **only when it has
no binder and no legacy condition**. :func:`kernel_definition_for` builds the
kernel counterpart in exactly that case and returns ``None`` otherwise;
:func:`follows_by_definition` then uses the kernel checker when a counterpart
exists and signals a fall-back to the string path when it does not. Closing the
gap for binder-carrying definitions needs the ``Define`` DSL to grow a way to
declare bound variables (and to express provisos in the kernel vocabulary); that
is deliberately left as follow-up rather than guessed at here, because guessing a
binder wrong would make an unfold silently capturing - an unsoundness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..kernel import Definition, check_definitional_step, from_match
from ..kernel.terms import Node, Term

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.definitions import Definition as MatchingDefinition
    from ..matching.matches import Match


def _ground_leaf_literals(term: Term) -> set[str]:
    """The surface literals of every ground leaf (childless :class:`Node`) in
    ``term``.

    A definition's *parameters* project to :class:`~website.logical.kernel.terms.Var`
    leaves (not ``Node`` literals) and so are excluded; what remains are the
    fixed tokens the form mentions - genuine constants, and, crucially, any
    *bound* variable the defining form introduces (e.g. the ``z`` in
    ``∀z.(z ∈ x → z ∈ y)``), which a ``fresh``-less parse leaves as a ground leaf.
    """
    literals: set[str] = set()

    def walk(node: Term) -> None:
        if isinstance(node, Node):
            if not node.children:
                if node.literal is not None:
                    literals.add(node.literal)
                return
            for child in node.children.values():
                walk(child)

    walk(term)
    return literals


def kernel_definition_for(
    legacy: MatchingDefinition, context: Context
) -> Definition | None:
    """Build (and cache on ``legacy``) the kernel definition equivalent to
    ``legacy``, or ``None`` if it is not soundly expressible as one.

    Returns ``None`` - and records that on ``legacy`` so it is not retried - when
    the definition has no known lower form, carries a legacy condition, fails to
    parse as two grammatical forms, or introduces a bound variable (a ground
    leaf in the defining form that is absent from the defined form). Any of these
    means the string-based path must be kept for this definition.
    """
    if legacy.kernel_definition_ready:
        return legacy.kernel_definition

    legacy.kernel_definition_ready = True
    legacy.kernel_definition = _build(legacy, context)
    return legacy.kernel_definition


def _build(legacy: MatchingDefinition, context: Context) -> Definition | None:
    if legacy.lower is None:
        # An open definition (unknown lower form) has nothing to unfold to.
        return None

    if legacy.condition is not None:
        # The legacy proviso DSL is not translated to the kernel's structural
        # vocabulary; keep such definitions on the string path (see module docs).
        return None

    try:
        kernel_def = Definition.parse(
            sort=legacy.pattern,
            higher=legacy.higher.pattern,
            lower=legacy.lower.pattern,
            variables=dict(legacy.variables),
            context=context,
        )
    except Exception:
        # Any build failure - a surface form that does not parse as its sort (an
        # alias notation the grammar cannot recognise on its own), or a deeper
        # matcher error - must fall back to the string path, never abort the
        # proof check. This is the same fail-closed stance as
        # InferenceRule._side_conditions_hold: declining the kernel path can only
        # keep the legacy behaviour, never accept an invalid step.
        return None

    # Binder guard: with no `fresh` declared, any bound variable of the defining
    # form survives as a ground leaf present in `lower` but not in `higher`. Such
    # a definition cannot be checked soundly by a capture-blind unfold, so refuse
    # it here (the fix is to let `Define` declare bound variables). A shared
    # constant appears in both forms and is fine.
    higher_leaves = _ground_leaf_literals(kernel_def.higher)
    lower_leaves = _ground_leaf_literals(kernel_def.lower)
    if lower_leaves - higher_leaves:
        return None

    return kernel_def


def follows_by_definition(
    before: Match, after: Match, legacy: MatchingDefinition, context: Context
) -> bool | None:
    """Whether ``before`` and ``after`` are one definitional unfold apart under
    ``legacy``, checked over kernel terms.

    Returns ``True``/``False`` when ``legacy`` has a kernel counterpart (the
    term-based check is authoritative, and covers both unfold directions), or
    ``None`` when it has none - the signal for the caller to fall back to the
    string-based :meth:`Definition.check_application`.
    """
    kernel_def = kernel_definition_for(legacy, context)
    if kernel_def is None:
        return None

    return check_definitional_step(
        from_match(before, context), from_match(after, context), kernel_def, context
    )
