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
  surface syntax for an instance ``lower`` of one pattern.
* A kernel :class:`~website.logical.kernel.definitions.Definition` is a
  definitional *axiom* whose defining form stores its binders abstractly (so an
  unfold is capture-avoiding) and whose proviso is drawn from the kernel's
  closed, structural side-condition vocabulary.

The ``Define`` DSL can now carry the extra information the kernel needs: a
``fresh`` clause declaring the defining form's bound variables (threaded here as
``legacy.fresh``) and a ``where`` clause of kernel-vocabulary provisos
(``legacy.kernel_condition``). A legacy definition is therefore soundly
expressible as a kernel one **unless it introduces an *undeclared* binder**.
:func:`kernel_definition_for` builds the kernel counterpart when it can and
returns ``None`` otherwise; :func:`follows_by_definition` uses the kernel checker
when a counterpart exists and signals a fall-back to the string path when it does
not. The binder guard below stays as a safety net: an undeclared binder would
otherwise unfold capturingly, so it forces the fallback rather than risk
unsoundness.

Invariant: a **proviso is enforced only on this kernel path**. The string
application path (``matching.Definition.check_application`` / ``get_lower``)
cannot evaluate a ``kernel_condition`` and so refuses a proviso-carrying
definition outright, and ``ProofLine.follows_from_definition`` refuses to fall
back to it. The consequence is that a proviso-carrying definition with **no**
kernel counterpart (e.g. an undeclared binder) can never apply anywhere - it is
not silently accepted (that would drop the proviso), but it is also unusable.
``Proof.check_definitional_line`` names this case explicitly so the failure is a
clear diagnostic rather than an opaque "does not apply".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..kernel import Definition, check_definitional_step, from_match
from ..kernel.terms import Node, Term
from ..matching import AtomPattern, RegexPattern

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


def _is_capture_safe_constant(literal: str, context: Context) -> bool:
    """Whether ``literal`` is a declared grammar *constant* — a nullary atom that
    can never stand in for a bound variable, so a lower-only occurrence of it in a
    defining form is safe to unfold without risk of capture.

    Conservative by design: the token must be claimed by a constant
    :class:`~website.logical.matching.patterns.AtomPattern` **and by nothing
    bindable** - not a family atom (which is freshable), not a declared
    metavariable, and not any regex-token sort (treated as variable-like). A token
    that is only ever a fixed symbol is admitted; anything that could also read as
    a variable is refused, keeping the string fallback. Erring this way can only
    cost completeness (a needless fallback), never soundness (a capturing unfold).
    """
    patterns = list(context.variables.values())
    if not any(
        isinstance(p, AtomPattern) and p.is_constant and p.is_member(literal)
        for p in patterns
    ):
        return False
    if literal in context.string_variables:
        return False
    if any(
        isinstance(p, AtomPattern) and not p.is_constant and p.is_member(literal)
        for p in patterns
    ):
        return False
    return not any(
        isinstance(p, RegexPattern) and p.match(literal, context) is not None
        for p in patterns
    )


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

    try:
        kernel_def = Definition.parse(
            sort=legacy.pattern,
            higher=legacy.higher.pattern,
            lower=legacy.lower.pattern,
            variables=dict(legacy.variables),
            context=context,
            condition=legacy.kernel_condition,
            fresh=dict(legacy.fresh) or None,
        )

        # Binder guard: with no `fresh` declared, a bound variable of the defining
        # form survives as a ground leaf present in `lower` but not in `higher`.
        # Such a definition cannot be checked soundly by a capture-blind unfold, so
        # refuse it here (the fix is to declare the binder with `fresh`). A
        # lower-only leaf that is a grammar *constant* is exempt, though: a
        # constant can never be captured, so a defining form that merely mentions
        # one (e.g. `∅`, `⊥`) stays on the kernel path rather than being pushed to
        # the string fallback.
        higher_leaves = _ground_leaf_literals(kernel_def.higher)
        lower_leaves = _ground_leaf_literals(kernel_def.lower)
        unexplained = lower_leaves - higher_leaves
        if any(not _is_capture_safe_constant(leaf, context) for leaf in unexplained):
            return None
    except Exception:
        # Any failure - a surface form that does not parse as its sort (an alias
        # notation the grammar cannot recognise on its own), a deeper matcher
        # error, or the constant probe tripping over a malformed/unused regex sort
        # that only compiles when matched - must fall back to the string path,
        # never abort the proof check. This is the same fail-closed stance as
        # InferenceRule._side_conditions_hold: declining the kernel path can only
        # keep the legacy behaviour, never accept an invalid step.
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
