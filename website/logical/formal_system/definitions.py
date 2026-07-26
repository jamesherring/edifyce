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
from ..kernel.constructors import constructor_for, project_sorts
from ..kernel.definitions import FreshBinder
from ..kernel.terms import Node, _bound, abstract, bind, from_match

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel.side_conditions import SideCondition
    from ..kernel.terms import Bound, Term
    from ..matching.context import Context
    from ..matching.definitions import DefinedNotation
    from ..matching.patterns import Pattern


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


def parse_definition(
    sort: Pattern,
    higher: str,
    lower: str,
    variables: dict[str, Pattern],
    context: Context,
    condition: SideCondition | None = None,
    fresh: dict[str, Pattern] | None = None,
    label: str | None = None,
) -> Definition:
    """Build a kernel :class:`~website.logical.kernel.definitions.Definition` by
    parsing its two surface forms.

    ``sort`` is the production both forms parse against (e.g. the ``formula``
    union); ``variables`` maps each parameter name to its sort; ``context`` is an
    ordinary ground parsing context. Each form is parsed through the grammar and
    its parameters abstracted (see
    :func:`~website.logical.kernel.terms.abstract`), so a multi-level defining
    form keeps its structure - which is why this uses parse + abstract rather
    than ``from_pattern`` (see that helper's note).

    ``fresh`` maps each bound variable of the defining form to its sort (for
    ``df-subset``, ``{"z": setvar}``); in the parsed defining form each such
    variable is replaced by an abstract, indexed
    :class:`~website.logical.kernel.terms.Bound` node (in ``fresh`` order), and
    the capture-avoidance proviso is generated from it.

    It may be omitted. A grammar that declares its binding slots
    (``Production.scopes_over``) already says which leaves of the defining form
    are binders, so :func:`_resolve_binders` reads them off the parsed term —
    what an author writes by hand today, and what a Metamath ``$a`` carries no
    trace of. A declaration is still honoured, and still needed wherever the
    binding production has not declared its slots.

    This lives here, not on ``Definition``, because it is the one thing a
    definition needed the *grammar* for. The kernel checks a step against terms;
    turning surface syntax into those terms is this layer's job, and keeping the
    two apart is what lets the trusted core read no strings at all.
    """
    parameter_sorts = project_sorts(variables)

    def parse(against: Pattern, text: str, what: str) -> Term:
        matched = against.match(text, context)
        if matched is None:
            raise ValueError(f"{what} {text!r} does not parse as '{against.name}'.")
        return from_match(matched)

    def schema(text: str) -> Term:
        return abstract(parse(sort, text, "Definition form"), parameter_sorts)

    higher_term = schema(higher)
    lower_term = schema(lower)

    # Each declared binder carries the leaf its name denotes. Parsing that name
    # here is what lets an unfold fall back to it without re-reading a string: a
    # name that is not of its own sort is the author's error, and is refused at
    # build rather than silently failing every unfold later.
    declared = [
        FreshBinder(
            name=name,
            sort=constructor_for(binder_sort),
            # Against the *binder's* sort, not the definition's: `z` is a
            # `setvar`, and it is the sort it ranges over that says what may
            # name it.
            default=parse(binder_sort, name, "Declared bound variable"),
        )
        for name, binder_sort in (fresh or {}).items()
    ]
    binders = _resolve_binders(declared, lower_term)

    # Each binder becomes an abstract, indexed node in the defining form, so the
    # form stores its binders by position rather than by a fixed concrete name.
    bound_nodes: dict[str, Bound] = {
        binder.name: _bound(index, binder.sort) for index, binder in enumerate(binders)
    }
    if bound_nodes:
        lower_term = bind(lower_term, bound_nodes)

    return Definition(
        higher=higher_term,
        lower=lower_term,
        condition=condition,
        fresh=tuple(binders),
        label=label,
    )


def _binders_in_binding_slots(term: Term) -> dict[str, FreshBinder]:
    """The binders ``term`` declares by *shape*: every ground leaf sitting in a
    slot some production declared as binding, keyed by surface name.

    This is what `fresh` has always meant — "which leaves of the defining form
    sit in a binder slot" — asked of the grammar instead of the author. It is
    silent for a production with no `scopes_over` declaration, which is every
    production until one is written, so a system that declares nothing infers
    nothing and reads exactly as it did before.

    A slot holding a :class:`~website.logical.kernel.terms.Var` is skipped: that
    is a *parameter* the defined form supplies, so the unfold substitutes it
    rather than conjuring it, and it needs no capture-avoidance of its own. Only
    a leaf the defining form names itself is a binder.

    Pre-order, first occurrence winning, so the resulting order — and hence the
    :class:`~website.logical.kernel.terms.Bound` index each binder gets — is a
    function of the defining form alone.
    """
    found: dict[str, FreshBinder] = {}

    def walk(current: Term) -> None:
        if not isinstance(current, Node) or not current.children:
            return
        for label, child in current.children.items():
            name = _leaf_name(child) if label in current.constructor.scopes_over else None
            if name is not None and name not in found:
                found[name] = FreshBinder(
                    name=name,
                    # The slot's *declared* sort, not the leaf's own constructor:
                    # it is the sort the binder ranges over that decides what may
                    # name it, exactly as for a declared binder above.
                    sort=current.constructor.slot_sorts[label],
                    default=child,
                )
            walk(child)

    walk(term)
    return found


def _leaf_name(term: Term) -> str | None:
    """The surface name of a ground leaf, or ``None`` for anything else — a
    compound, a parameter (:class:`Var`), or an already-abstract binder."""
    if isinstance(term, Node) and not term.children:
        return term.literal
    return None


def _binds_every_occurrence(term: Term, name: str) -> bool:
    """Whether every leaf spelled ``name`` in ``term`` lies under a binder slot
    that binds it — the half of a `scopes_over` declaration that says *over what*.

    Abstracting a binder replaces the name everywhere it is spelled
    (:func:`~website.logical.kernel.terms.bind` keys on the surface string), so
    inferring one for a defining form that also uses the name *outside* the
    binder's scope would quietly capture a genuinely free occurrence: an unfold
    would rename both together and the definition would mean something the author
    did not write. Whether that is so is exactly what the declared scope decides,
    which is why inference reads it rather than only the binder slot's label.

    So an occurrence out of scope withholds the inference, and the name stays one
    the defining form conjures — refused by ``introduced_leaves`` with the message
    that names the remedy, which is what happened before binding slots existed. A
    declared ``fresh`` clause is untouched: it is the author's positive act.
    """

    def walk(current: Term, bound: bool) -> bool:
        if not isinstance(current, Node):
            # A Var is a parameter the defined form supplies; it spells no leaf.
            return True
        if not current.children:
            return bound or current.literal != name

        # The slots this node binds `name` in: its own binder occurrences, and
        # everything those binders were declared to scope over.
        inner: set[str] = set()
        for slot, targets in current.constructor.scopes_over.items():
            child = current.children.get(slot)
            if child is not None and _leaf_name(child) == name:
                inner.add(slot)
                inner.update(targets)

        return all(
            walk(child, bound or label in inner)
            for label, child in current.children.items()
        )

    return walk(term, False)


def _resolve_binders(
    declared: Sequence[FreshBinder], lower: Term
) -> list[FreshBinder]:
    """The definition's binders: those declared, plus those the grammar shows.

    Inference only ever *adds*. A binder the author declared and the grammar does
    not show may still be one — the production it sits in need not have declared
    its binding slots — so an undetected binder is no evidence against the
    declaration, and silence is never read as denial.

    The one genuine contradiction is a shared name at a different sort: the
    grammar puts the leaf in a slot of one sort and the author declared another.
    That cannot both be true, and the grammar is the thing that was checked.

    An inferred binder must also *cover* its name — every occurrence of it in the
    defining form inside the binder's declared scope (see
    :func:`_binds_every_occurrence`). Only inference is held to this: a declared
    clause is the author's own claim, and honouring it is the behaviour every
    system written before binding slots existed relies on.
    """
    inferred = _binders_in_binding_slots(lower)
    for binder in declared:
        found = inferred.get(binder.name)
        if found is not None and found.sort is not binder.sort:
            raise DefinitionError(
                f"Bound variable {binder.name!r} is declared fresh at sort "
                f"{binder.sort.name!r}, but the defining form puts it in a binder "
                f"slot of sort {found.sort.name!r}. Drop the `fresh` clause and let "
                f"it be inferred, or declare the sort the grammar gives it."
            )
    names = {binder.name for binder in declared}
    return [
        *declared,
        *(
            binder
            for name, binder in inferred.items()
            if name not in names and _binds_every_occurrence(lower, name)
        ),
    ]


def build_kernel_definition(
    notation: DefinedNotation,
    lower: str | None,
    context: Context,
    condition: SideCondition | None = None,
    # Sort *patterns*, not constructors: this is the build boundary, where a
    # declaration still names productions. `parse_definition` projects them, and
    # the definition it returns holds no pattern.
    fresh: dict[str, Pattern] | None = None,
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
        kernel_def = parse_definition(
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


def denotes_a_constant(notation: DefinedNotation, parses_to_its_own_leaf: bool) -> bool:
    """Whether a definition's *defined* form is itself a constant of the object
    language: true when the notation is nullary **and** its form is new to the
    grammar, so that form parses to this notation's own ground leaf.

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

    ``parses_to_its_own_leaf`` is why nullary alone will not do. A sort tries its
    own productions before its notations, so a defined form the grammar *already*
    spells (``Define x ∈ y as ...`` with no parameters) never reaches this
    notation: it parses through the declared production, and to a compound rather
    than to a leaf of this notation at all. Marking that template a constant would
    be the unsafe direction — the flag is what excuses a *later* definition from
    accounting for a token — so a shadowed form takes the variable-like default.
    Nothing is ever built through such a template either way, which is why this is
    a correctness statement rather than a bug fix.

    Note it is a question about *this* notation, not about the grammar before it:
    two definitions may share one defined form, and the second finds the first's
    notation. That is one production and still its own leaf, so both agree.

    Asked of the *notation* rather than the built definition, so the answer is
    available before the definition is built - which is what lets a constructor
    snapshot the declaration instead of reading it back through the production
    for the rest of the system's life.
    """
    return not notation.variables and parses_to_its_own_leaf
