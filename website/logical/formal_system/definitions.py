"""Building a :class:`~website.logical.kernel.definitions.Definition` from a
:class:`~website.logical.matching.definitions.Definition`, and checking a
definitional step against it.

The two definition objects play different roles and both are needed:

* the **matching** ``Definition`` is *parser* state - it is what lets
  ``a sub b`` be recognised as a formula at all (``Pattern.try_definitions``);
* the **kernel** ``Definition`` is a definitional *axiom* whose defining form
  stores its binders abstractly (so an unfold is capture-avoiding) and whose
  proviso is drawn from the kernel's closed, structural side-condition
  vocabulary. It is what a proof step is *checked* against.

:func:`build_kernel_definition` derives the second from the first, and the system
builder calls it once per definition at build time (see
``declarative._finalise_definition``), storing the result on the matching
definition's ``kernel`` slot. Every definition reaching a proof therefore already
carries its kernel counterpart: :func:`follows_by_definition` reads it rather
than deriving anything, and there is no second, string-based way to apply a
definition.

Why this is a build-time step, not a check-time one
---------------------------------------------------
Not every ``Define higher as lower`` is soundly expressible as a kernel
definition. The defining form may name something the defined form cannot supply -
an undeclared binder (the ``z`` in ``∀z.(z ∈ x → z ∈ y)``), a parameter the
defined form omits, or a variable simply left free. Each makes the unfold conjure
a name, and a conjured name is capturable wherever the step happens to be taken.

That is a property of the definition, not of any particular step, so it is
settled once - when the system is built and its author can act on it - rather
than surfacing as an opaque "does not apply" on some later proof line. It is also
why no proviso can stand in for it: a proviso constrains the *binding* an unfold
produces, while this constrains where the defined form may legally *occur*, which
a cited step never sees.

Which layer owns what
---------------------
The kernel owns the rule and states it over the term graph:
:func:`~website.logical.kernel.definitions.unbound_parameters` and
:func:`~website.logical.kernel.definitions.introduced_leaves` report exactly the
leaves a defining form introduces from nowhere. It deliberately stops there,
because deciding which of those are *benign* - a constant of the object language
like ``⊥`` denotes one fixed thing and can be neither renamed nor captured - is a
question about the grammar, not about the graph.

So this module supplies only that grammar predicate
(:func:`_is_capture_safe_constant` and friends), and the matching layer below it
does neither: patterns parse, and nothing else.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..kernel import (
    Definition,
    check_definitional_step,
    from_match,
    introduced_leaves,
    unbound_parameters,
)
from ..kernel.terms import Node
from ..matching import AtomPattern, RegexPattern, StringPattern, UnionPattern

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..matching.context import Context
    from ..matching.definitions import Definition as MatchingDefinition
    from ..matching.matches import Match
    from ..matching.patterns import Pattern


# `Match.create_pattern` renames a colliding variable by appending `_<n>`; this
# folds such a rename back onto the name the author actually wrote.
_RENAMED = re.compile(r"_\d+$")


class DefinitionError(Exception):
    """Raised when a definition is not soundly expressible as a kernel one.

    Carries a message written for the *author* of the definition; the declarative
    builder surfaces it as a build error against the system.
    """


def _is_constant_constructor(pattern: Pattern) -> bool:
    """Whether ``pattern`` builds a fixed symbol rather than a variable: a
    constant atom (``⊥``), or a production with no slots to fill (``0``, ``∅``).

    A regex sort is variable-like by construction, and a family atom is freshable,
    so neither qualifies.
    """
    if isinstance(pattern, AtomPattern):
        return pattern.is_constant
    if isinstance(pattern, StringPattern):
        return not pattern.variables
    return False


def _reachable_patterns(sort: Pattern) -> set[Pattern]:
    """``sort`` and every pattern that can occur inside one of its instances.

    Scoping the capture check to these is what keeps it about the *term* language:
    a binder in a defining form binds a variable occurring inside a term of the
    definition's sort, so only these sorts can name one. Patterns registered for
    other purposes - notably a line type's citation-reference field, whose regex
    happily matches ordinary tokens - are not part of that language and must not
    decide whether a leaf is a constant.
    """
    found: set[Pattern] = set()

    def walk(pattern: Pattern) -> None:
        if pattern in found:
            return
        found.add(pattern)
        if isinstance(pattern, UnionPattern):
            children: tuple[Pattern, ...] = tuple(pattern.patterns)
        elif isinstance(pattern, StringPattern):
            children = tuple(pattern.variables.values())
        else:
            return
        for child in children:
            walk(child)

    walk(sort)
    return found


def _is_capture_safe_constant(
    leaf: Node, patterns: set[Pattern], context: Context
) -> bool:
    """Whether ``leaf`` is a grammar *constant* — a symbol that can never stand in
    for a bound variable, so a lower-only occurrence of it in a defining form is
    safe to unfold without risk of capture.

    Two conditions, and both are needed. The leaf's own constructor must be a
    constant one (positive evidence, from the parse itself, that this position
    holds a fixed symbol), **and** nothing bindable in ``patterns`` - the sorts
    reachable from the definition's own sort - may also claim the token: not a
    family atom, not a declared metavariable, not any regex-token sort. The second
    covers an ambiguous grammar, where the same token reads as a declared constant
    *and* as a variable in the same slot.
    """
    if not _is_constant_constructor(leaf.pattern):
        return False

    literal = leaf.literal
    if literal in context.string_variables:
        return False
    if any(
        isinstance(p, AtomPattern) and not p.is_constant and p.is_member(literal)
        for p in patterns
    ):
        return False
    return not any(
        isinstance(p, RegexPattern) and _matches(p, literal, context) for p in patterns
    )


def _matches(pattern: RegexPattern, literal: str, context: Context) -> bool:
    """Whether ``pattern`` claims ``literal``, treating a pattern that cannot be
    evaluated as claiming nothing.

    A regex sort compiles lazily, on its first match, so an unrelated malformed
    one in the same grammar would otherwise raise here and take a well-formed
    definition down with it. Reading it as "claims nothing" costs no soundness: a
    regex that cannot compile cannot match a token in a proof line either, so it
    can never be the sort a bound variable is drawn from.
    """
    try:
        return pattern.match(literal, context) is not None
    except Exception:  # noqa: BLE001 - any matcher failure means "no claim"
        return False


def _introduced_name_error(
    legacy: MatchingDefinition, names: Sequence[str]
) -> DefinitionError:
    """The build error for a defining form that introduces ``names`` out of
    nowhere - written for the author, and naming both remedies.

    One message covers every spelling of the mistake (an undeclared binder, a
    parameter the defined form omits, a variable left free), because they are the
    same defect and the author's two ways out are the same.
    """
    listed = ", ".join(repr(name) for name in names)
    them = "them" if len(names) > 1 else "it"
    return DefinitionError(
        f"Definition '{legacy.higher.pattern}' introduces {listed} in its defining "
        f"form '{legacy.lower_source}', but the defined form does not mention "
        f"{them}. An unfold would then conjure {them} wherever the definition is "
        f"used, and under a binder of the same name that silently rebinds "
        f"{them} — so the step would not mean the same thing everywhere it is "
        f"taken. Either make {listed} parameters the defined form supplies, or, if "
        f"the defining form binds {them}, declare {them} with a `fresh` clause "
        f"giving the sort."
    )


def _lower_only_parameters(legacy: MatchingDefinition) -> list[str]:
    """The declared parameters the *defining* form uses that the defined form does
    not - a binder written as an ordinary parameter.

    Checked before parsing, because this is also the case that leaves
    ``legacy.lower``'s template unparseable: a name used both as a binder and free
    in the body occupies two pattern slots, so ``create_pattern`` renames the
    later ones (``z`` -> ``z_0``). Those renames are folded back onto the name the
    author wrote, which is the only one they can act on.
    """
    lower_only = set(legacy.lower.variables) - set(legacy.higher.variables)
    return sorted(
        name
        for name in lower_only
        if _RENAMED.sub("", name) == name or _RENAMED.sub("", name) not in lower_only
    )


def build_kernel_definition(legacy: MatchingDefinition, context: Context) -> Definition:
    """The kernel definition ``legacy`` denotes.

    ``context`` must already hold ``legacy`` itself: an alias definition's
    *defined* form is grammatical only because the definition is in scope, so the
    definition is what lets ``higher`` parse at all.

    Raises :class:`DefinitionError` when the definition cannot be expressed as a
    kernel one - because a form does not parse, or because the defining form
    introduces a binder the author has not declared.
    """
    if legacy.lower is None:
        raise DefinitionError(
            f"Definition '{legacy.higher.pattern}' has no defining form to unfold to."
        )

    undeclared = _lower_only_parameters(legacy)
    if undeclared:
        raise _introduced_name_error(legacy, undeclared)

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
    except Exception as exc:
        # A surface form the grammar cannot recognise on its own, a deeper matcher
        # error, or the constant probe tripping over a regex sort that only
        # compiles when matched. Reshaped rather than propagated so the author
        # gets a message naming the definition, not a matcher-internal traceback.
        raise DefinitionError(
            f"Definition '{legacy.higher.pattern}' could not be read as a "
            f"definition of {legacy.pattern.name}: {exc}"
        ) from exc

    # The kernel settles which leaves the defining form introduces from nowhere -
    # the structural question, over the two term schemas. All that is left here is
    # the grammar question it deliberately leaves open: which of them are constants
    # of the object language (`⊥`, `∅`), which denote one fixed thing and so can be
    # neither renamed nor captured. Everything else is a name the unfold would
    # conjure - an undeclared binder, or a variable free in the defining form - and
    # either makes the unfold depend on where it is taken.
    unbound = unbound_parameters(kernel_def)
    if unbound:
        raise _introduced_name_error(legacy, unbound)

    bindable = _reachable_patterns(legacy.pattern)
    conjured = [
        leaf.literal
        for leaf in introduced_leaves(kernel_def)
        if not _is_capture_safe_constant(leaf, bindable, context)
    ]
    if conjured:
        raise _introduced_name_error(legacy, conjured)

    return kernel_def


def follows_by_definition(
    before: Match, after: Match, legacy: MatchingDefinition, context: Context
) -> bool:
    """Whether ``before`` and ``after`` are one definitional unfold apart under
    ``legacy``, checked over kernel terms in either direction.

    ``legacy.kernel`` is built when the system is (see
    :func:`build_kernel_definition`), so a definition that reaches a proof always
    carries one.

    Raises :class:`DefinitionError` if one does not - which means it was built
    outside the system builder, via :meth:`Pattern.add_definition` directly.
    Better to say so than to hand ``None`` to the kernel and fail as an
    ``AttributeError`` several frames in.
    """
    if legacy.kernel is None:
        raise DefinitionError(
            f"Definition '{legacy.higher.pattern}' has no kernel counterpart, so no "
            f"step can be checked against it. Definitions are built through "
            f"`declarative.build_system`, which constructs one for each; this one "
            f"reached a proof without it."
        )

    return check_definitional_step(
        from_match(before, context), from_match(after, context), legacy.kernel, context
    )
