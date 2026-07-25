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
definition. A defining form may introduce a binder (the ``z`` in
``∀z.(z ∈ x → z ∈ y)``) that the defined form does not mention; unfolding such a
definition without treating ``z`` as a binder would capture a free ``z`` in the
argument and silently change meaning. The ``Define`` DSL can declare those with a
``fresh`` clause, and the kernel then renames the binder to avoid capture - but
an *undeclared* binder has no sound reading.

That is a property of the definition, not of any particular step, so it is
settled once, when the system is built and its author can act on it, rather than
surfacing as an opaque "does not apply" on some later proof line.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..kernel import Definition, check_definitional_step, from_match
from ..kernel.terms import Node, Term, Var
from ..matching import AtomPattern, RegexPattern, StringPattern, UnionPattern

if TYPE_CHECKING:
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


def _ground_leaves(term: Term) -> list[Node]:
    """Every ground leaf (childless :class:`Node` carrying a literal) in ``term``.

    A definition's *parameters* project to :class:`~website.logical.kernel.terms.Var`
    leaves, not ``Node`` literals, and so are excluded; what remains are the fixed
    tokens the form mentions - genuine constants, and, crucially, any *bound*
    variable the defining form introduces (e.g. the ``z`` in ``∀z.(z ∈ x → z ∈ y)``),
    which a ``fresh``-less parse leaves as a ground leaf.
    """
    leaves: list[Node] = []

    def walk(node: Term) -> None:
        if isinstance(node, Node):
            if not node.children:
                if node.literal is not None:
                    leaves.append(node)
                return
            for child in node.children.values():
                walk(child)

    walk(term)
    return leaves


def _has_parameters(term: Term) -> bool:
    """Whether ``term`` contains a schematic :class:`~website.logical.kernel.terms.Var`
    - i.e. whether the definition takes arguments at all."""
    if isinstance(term, Var):
        return True
    return isinstance(term, Node) and any(
        _has_parameters(child) for child in term.children.values()
    )


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


def _undeclared_binder_error(
    legacy: MatchingDefinition, names: list[str], *, declared_as_parameters: bool = False
) -> DefinitionError:
    """The build error for a defining form that introduces ``names`` out of
    nowhere - written for the author, and naming the fix.

    ``declared_as_parameters`` distinguishes the two ways the same mistake is
    spelled: a name given as an ordinary parameter needs *moving*, one never
    declared at all needs adding.
    """
    listed = ", ".join(repr(name) for name in names)
    move = " — as a `fresh` binder, not as an ordinary parameter" if declared_as_parameters else ""
    return DefinitionError(
        f"Definition '{legacy.higher.pattern}' introduces {listed} in its defining "
        f"form '{legacy.lower_source}', but the defined form does not mention "
        f"{'them' if len(names) > 1 else 'it'}. A variable the defining form binds "
        f"must be declared, so an unfold can rename it and avoid capturing a "
        f"variable of the same name in the argument: declare {listed} with a "
        f"`fresh` clause, giving the sort{move}."
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
        raise _undeclared_binder_error(legacy, undeclared, declared_as_parameters=True)

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

    # Binder guard: with no `fresh` declared, a bound variable of the defining
    # form survives as a ground leaf present in `lower` but not in `higher`.
    # Unfolding such a definition is capture-blind, so refuse it.
    #
    # Only for a definition that takes parameters, though. Capture is a parameter's
    # substitution landing under a binder, so a definition with none — a nullary
    # abbreviation like `S ≝ a` or `∅ ≝ 0` — substitutes nothing and unfolds to a
    # fixed term whatever its defining form mentions. A lower-only leaf that is a
    # grammar *constant* is exempt for the same reason: a constant can never be
    # captured, so a defining form that merely mentions one (e.g. `∅`, `⊥`) needs
    # no declaration.
    if _has_parameters(kernel_def.higher):
        defined_literals = {leaf.literal for leaf in _ground_leaves(kernel_def.higher)}
        bindable = _reachable_patterns(legacy.pattern)
        undeclared = sorted(
            {
                leaf.literal
                for leaf in _ground_leaves(kernel_def.lower)
                if leaf.literal not in defined_literals
                and not _is_capture_safe_constant(leaf, bindable, context)
            }
        )
        if undeclared:
            raise _undeclared_binder_error(legacy, undeclared)

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
