"""Building a :class:`~website.logical.kernel.definitions.Definition` -- the
build-time gate a declared definition has to pass.

A definition splits cleanly into two, and only one of them is a *definition*:

* its **defined form** is a production the grammar gains
  (:class:`~website.logical.matching.definitions.DefinedNotation`), which is what
  lets ``a sub b`` be recognised as a formula at all. It parses, and nothing more;
* the definition itself is a **kernel** axiom - defining form stored with its
  binders abstract, so an unfold is capture-avoiding, and its proviso drawn from
  the kernel's closed structural vocabulary. It is what a step is checked against,
  and it lives on the system (``FormalSystem.definitions``), cited by label.

:func:`build_kernel_definition` pairs the two: given a registered notation and the
defining form as written, it produces the axiom or refuses. The system builder
calls it once per definition (see ``declarative._finalise_definition``), so a
definition that cannot be expressed soundly never reaches a proof -- and a proof
step is checked by handing the axiom straight to
:func:`~website.logical.kernel.definitions.check_definitional_step`, with nothing
in between to become a second, string-based way to apply a definition.

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

from ..kernel import Definition, introduced_leaves, unbound_parameters

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel.side_conditions import SideCondition
    from ..kernel.terms import FreeVars
    from ..matching.context import Context
    from ..matching.definitions import DefinedNotation


class DefinitionError(Exception):
    """Raised when a definition is not soundly expressible as a kernel one.

    Carries a message written for the *author* of the definition; the declarative
    builder surfaces it as a build error against the system.
    """


def _introduced_name_error(
    notation: DefinedNotation, lower: str, names: Sequence[str]
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
        f"Definition '{notation.template.pattern}' introduces {listed} in its defining "
        f"form '{lower}', but the defined form does not mention "
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


def build_kernel_definition(
    notation: DefinedNotation,
    lower: str | None,
    context: Context,
    condition: SideCondition | None = None,
    fresh: FreeVars | None = None,
    label: str | None = None,
) -> Definition:
    """The kernel definition that unfolds ``notation`` to ``lower``.

    ``notation`` supplies the grammatical half — the sort, the defined form, and
    the parameters that form takes; ``lower`` is the defining form as written,
    with ``condition`` and ``fresh`` its declared provisos and ``label`` the name
    a proof cites it by. ``lower`` may be ``None``: notation can be registered
    without a defining form, and this is where that is refused.

    ``context`` must already hold ``notation``: a defined form is grammatical
    only because its notation is registered, so that is what lets ``higher``
    parse at all.

    Raises :class:`DefinitionError` when the pair cannot be expressed as a kernel
    definition — because a form does not parse, or because the defining form
    introduces a name out of nowhere.
    """
    if lower is None:
        raise DefinitionError(
            f"Definition '{notation.template.pattern}' has no defining form to unfold to."
        )

    # The definition's parameters are the slots its *defined* form declares -
    # exactly what a use of the notation supplies. A name the defining form uses
    # and the defined form does not is therefore left unabstracted, which is the
    # point: it stays a ground leaf and `introduced_leaves` below reports it as a
    # name the unfold would conjure. Only that check, and `unbound_parameters`
    # beside it, decide what a defining form may introduce.
    variables = dict(notation.variables)

    try:
        kernel_def = Definition.parse(
            sort=notation.sort,
            higher=notation.template.pattern,
            lower=lower,
            variables=variables,
            context=context,
            condition=condition,
            fresh=dict(fresh) if fresh else None,
            label=label,
        )
    except Exception as exc:
        # A surface form the grammar cannot recognise on its own, or a deeper
        # matcher error. Reshaped rather than propagated so the author gets a
        # message naming the definition, not a matcher-internal traceback.
        raise DefinitionError(
            f"Definition '{notation.template.pattern}' could not be read as a "
            f"definition of {notation.sort.name}: {exc}"
        ) from exc

    # The kernel settles which leaves the defining form introduces from nowhere -
    # the structural question, over the two term schemas. All that is left here is
    # the grammar question it deliberately leaves open: which of them are
    # constants of the object language, declared as such by the production that
    # builds them. Everything else is a name the unfold would conjure - an
    # undeclared binder, or a variable free in the defining form - and either
    # makes the unfold depend on where it is taken.
    unbound = unbound_parameters(kernel_def)
    if unbound:
        raise _introduced_name_error(notation, lower, unbound)

    # Deduplicated by *name* only here: two constructors spelling the same token
    # are two problems to the kernel but one thing for the author to fix.
    conjured = sorted(
        {
            leaf.literal
            for leaf in introduced_leaves(kernel_def)
            if not leaf.constructor.denotes_constant
        }
    )
    if conjured:
        raise _introduced_name_error(notation, lower, conjured)

    return kernel_def


def denotes_a_constant(notation: DefinedNotation) -> bool:
    """Whether a definition's *defined* form is itself a constant of the object
    language - true exactly when the notation is nullary, so that form parses to
    a ground leaf.

    A nullary definition (``S ≝ (⊥ → ⊥)``) puts a new leaf into the grammar that
    no production declared a role for. It needs no declaration: ``S`` abbreviates
    one fixed term and so denotes one fixed thing. Nor can it be captured - its
    constructor is the definition's own, distinct from any variable sort that
    happens to spell the same token, which is the same reason
    :func:`~website.logical.kernel.definitions.introduced_leaves` keys on
    constructor rather than spelling. So a later definition may introduce it
    exactly as it may introduce ``⊥``, and ``T ≝ S`` layers on ``S ≝ ⊥``.

    Derived rather than declared: there is nothing here for an author to know
    that the engine does not.

    Asked of the *notation* rather than the built definition, so the answer is
    available before the definition is built - which is what lets a constructor
    snapshot the declaration instead of reading it back through the production
    for the rest of the system's life. The two agree by construction: a
    definition's parameters are exactly its notation's slots (see
    :func:`build_kernel_definition`), so the defined form is a ground leaf
    exactly when the notation takes none.
    """
    return not notation.variables
