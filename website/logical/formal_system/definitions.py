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

So this module supplies only that grammar predicate, and the matching layer below
it does neither: patterns parse, and nothing else.

Why the predicate is a *declaration*, not a deduction
-----------------------------------------------------
This module used to infer the answer from the leaf's constructor - a constant
atom or a slotless production was read as constant - cross-checked against every
variable-like sort reachable from the definition's own. Each part of that was a
guess, and the guesses had holes: an atom constant declared a *member of the
variable sort* (``setvar ::= [A-Z] | c``) is a variable the author spelled with
an atom, but the constructor says "constant", so ``T ≝ (c ∈ c)`` was admitted and
``∀c.T ⟶ ∀c.(c ∈ c)`` captured ``c``.

No property of a production's shape settles it, because the same shape means
different things in different grammars: a one-token atom is a constant in
``formula ::= ⊥`` and a variable in ``setvar ::= a | b | c``. Metamath faces the
same question and answers it the same way - every token is declared ``$c`` or
``$v`` - so the author declares it here too, via
``Production.denotes_constant``, and this module reads the declaration.

The default is variable-like, which is the safe direction: an undeclared leaf is
refused, so a forgotten declaration costs a rejected definition. The unsafe
direction - declaring a bindable token constant - takes a positive act, and stays
confined to the system it is made in (a proof is only ever checked against its
own system, and cross-proof citation is same-system-only).

One declaration is refused outright rather than trusted: an indexed atom family
(``p_#``) is a supply of interchangeable tokens, so no grammar makes it denote a
fixed thing and no author could mean it. ``declarative.build_system`` rejects it.
Every other case is a genuine judgement about the grammar, which only binding
slots on productions could check (see AGENTS.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..kernel import (
    Definition,
    check_definitional_step,
    introduced_leaves,
    unbound_parameters,
)
from ..kernel.terms import Node

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel.terms import Term
    from ..matching.context import Context
    from ..matching.definitions import Definition as MatchingDefinition


class DefinitionError(Exception):
    """Raised when a definition is not soundly expressible as a kernel one.

    Carries a message written for the *author* of the definition; the declarative
    builder surfaces it as a build error against the system.
    """


def _introduced_name_error(
    legacy: MatchingDefinition, names: Sequence[str]
) -> DefinitionError:
    """The build error for a defining form that introduces ``names`` out of
    nowhere - written for the author, and naming every remedy.

    One message covers every spelling of the mistake (an undeclared binder, a
    parameter the defined form omits, a variable left free, a constant the author
    has not declared as one), because they are the same defect and the ways out
    are the same three.
    """
    listed = ", ".join(repr(name) for name in names)
    plural = len(names) > 1
    them = "them" if plural else "it"
    return DefinitionError(
        f"Definition '{legacy.higher.pattern}' introduces {listed} in its defining "
        f"form '{legacy.lower_source}', but the defined form does not mention "
        f"{them}. An unfold would then conjure {them} wherever the definition is "
        f"used, and under a binder of the same name that silently rebinds "
        f"{them} — so the step would not mean the same thing everywhere it is "
        f"taken. Either make {listed} parameters the defined form supplies; or, if "
        f"the defining form binds {them}, declare {them} with a `fresh` clause "
        f"giving the sort; or, if {'they are' if plural else 'it is'} in fact "
        f"{'constants' if plural else 'a constant'} of the object language that no "
        f"binder can ever bind, mark the "
        f"{'productions that build' if plural else 'production that builds'} "
        f"{them} as denoting a constant."
    )


def _lower_only_parameters(legacy: MatchingDefinition) -> list[str]:
    """The declared parameters the *defining* form uses that the defined form does
    not - a binder written as an ordinary parameter.

    Checked before parsing so the author is told which name is the problem. The
    kernel would catch it too (the leaf is introduced from nowhere either way),
    but only after the defining form has been parsed and abstracted.
    """
    return sorted(set(legacy.variables) - set(legacy.higher.variables))


def build_kernel_definition(legacy: MatchingDefinition, context: Context) -> Definition:
    """The kernel definition ``legacy`` denotes.

    ``context`` must already hold ``legacy`` itself: an alias definition's
    *defined* form is grammatical only because the definition is in scope, so the
    definition is what lets ``higher`` parse at all.

    Raises :class:`DefinitionError` when the definition cannot be expressed as a
    kernel one - because a form does not parse, or because the defining form
    introduces a binder the author has not declared.
    """
    if legacy.lower_source is None:
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
            lower=legacy.lower_source,
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

    # Deduplicated by *name* only here: two constructors spelling the same token
    # are two problems to the kernel but one thing for the author to fix.
    conjured = sorted(
        {
            leaf.literal
            for leaf in introduced_leaves(kernel_def)
            if not leaf.pattern.denotes_constant
        }
    )
    if conjured:
        raise _introduced_name_error(legacy, conjured)

    return kernel_def


def denotes_a_constant(kernel_def: Definition) -> bool:
    """Whether a built definition's *defined* form is itself a constant of the
    object language - true exactly when that form is a ground leaf.

    A nullary definition (``S ≝ (⊥ → ⊥)``) puts a new leaf into the grammar that
    no production declared a role for. It needs no declaration: reaching here
    means every leaf of its defining form was accounted for, so ``S`` abbreviates
    one fixed term and denotes one fixed thing. Nor can it be captured - its
    constructor is the definition's own, distinct from any variable sort that
    happens to spell the same token, which is the same reason
    :func:`~website.logical.kernel.definitions.introduced_leaves` keys on
    constructor rather than spelling. So a later definition may introduce it
    exactly as it may introduce ``⊥``, and ``T ≝ S`` layers on ``S ≝ ⊥``.

    Derived rather than declared: the builder has just established the fact, and
    there is nothing here for an author to know that the engine does not.
    """
    higher = kernel_def.higher
    return isinstance(higher, Node) and not higher.children and higher.literal is not None


def follows_by_definition(
    before: Term, after: Term, legacy: MatchingDefinition, context: Context
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

    return check_definitional_step(before, after, legacy.kernel, context)
