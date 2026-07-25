"""Unification over terms: first-order matching that derives a substitution.

Step 1 gave us a :class:`~website.logical.kernel.terms.Term` and a *structural*
equality on it. Step 2 adds the operation the proof checker actually needs:
given a rule *schema* (a term with :class:`~website.logical.kernel.terms.Var`
leaves) and a concrete formula *term*, find the substitution that makes the
schema equal the term - or prove none exists.

Why "unify"
-----------
The engine grew a family of near-duplicate tree-walks - ``Match.equivalent``,
``maps_to``, ``equivalent_with_some_replacements``, ``maps_to_up_to_definition``,
``equivalent_under_definitions`` and ``Definition.check_application`` - each
"compare two match trees, with a knob". All are now deleted, because on the term
representation they are the same operation with two settings:

* do variables bind?  no  -> structural equality (:meth:`Term.equal`)
                      yes -> :func:`match` (this module)
* rewrite under definitions?  that knob rides with step 4 (definitions as
  axioms); see the note at the bottom.

So :func:`match` is the second corner of that table, and structural equality is
the first: with no variables, ``match(a, b, ctx) is not None`` iff
``a.equal(b, ctx)``. Both share the *same* constructor identity
(``Constructor.signature``) and positional child alignment, so matching and
equality can never disagree about what "the same shape" means.

This is *first-order matching* - variables occur only on the schema side and
bind to whole subterms; it is the one-directional specialisation of unification
that rule application needs. Full two-sided unification (variables on both
sides, occurs-check) is not required by the checker and is intentionally out of
scope.

Worked example - modus ponens
------------------------------
With schemas ``p`` and ``(p -> q)`` and deduction ``q``, checking the step
``a``, ``(a -> b)`` therefore ``b``::

    match_all([
        (schema_p,        term_a),        # p := a
        (schema_p_imp_q,  term_a_imp_b),  # consistent with p := a, binds q := b
        (schema_q,        term_b),        # q := b, agrees
    ], context)
    # -> {"p": <term a>, "q": <term b>}   (None if the step is invalid)

and ``schema.substitute(binding, context)`` reproduces the concrete term, which
is the round-trip the checker relies on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..matching.patterns import UnionPattern
# Reuse the *same* constructor identity and slot alignment that Term.equal uses,
# so matching and equality stay defined against one source of truth. Both are now
# fields on the constructor rather than walks over a template (see constructors).
from .constructors import constructor_for
from .terms import Var

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..matching.context import Context
    from ..matching.patterns import Pattern
    from .terms import Term

    # A substitution produced by matching: variable name -> the Term it binds to.
    # Term is imported just above, so no forward-reference quoting is needed.
    Binding = dict[str, Term]


def match(
    schema: Term, subject: Term, context: Context, binding: Binding | None = None
) -> Binding | None:
    """Find a substitution that makes ``schema`` equal ``subject``.

    ``schema`` may contain :class:`Var` leaves; ``subject`` is treated as fixed.
    Returns the (extended) binding on success, or ``None`` if no consistent
    substitution exists. The passed-in ``binding`` is never mutated - an
    extended copy is returned - so callers can try alternatives freely.

    Examples (``p``, ``q`` schematic over ``formula``)::

        match(schema "(p -> q)", term "(a -> b)")  -> {"p": a, "q": b}
        match(schema "(p -> p)", term "(a -> b)")  -> None   # p can't be both
        match(schema "(p -> p)", term "(a -> a)")  -> {"p": a}
    """
    if binding is None:
        binding = {}

    if isinstance(schema, Var):
        bound = binding.get(schema.name)
        if bound is not None:
            # Already bound: the subject must agree with the earlier binding.
            return binding if bound.equal(subject, context) else None
        if not _sort_admits(schema.sort, subject, context):
            # Keep a variable from capturing a term of the wrong sort.
            return None
        # Extend with a copy; never mutate the caller's binding.
        return {**binding, schema.name: subject}

    if isinstance(subject, Var):
        # A concrete production cannot match an opaque (unbound) variable.
        return None

    # Both are Nodes. Constructors must agree name-insensitively (a schema's
    # "(p -> q)" and a production's "(lhs -> rhs)" are the same constructor).
    if schema.constructor.signature != subject.constructor.signature:
        return None

    # Ground leaves (atoms, constants) compare by their surface string.
    if schema.literal is not None or subject.literal is not None:
        return binding if schema.literal == subject.literal else None

    # Match children pairwise by template position, with repetition - the two
    # constructors may spell their slots differently, and a schema may repeat a
    # variable (e.g. "(p -> p)"). Threading one binding makes a repeated - or
    # cross-antecedent - variable bind consistently.
    schema_locations = schema.constructor.slots
    subject_locations = subject.constructor.slots
    if len(schema_locations) != len(subject_locations):
        return None

    current: Binding = binding
    for schema_label, subject_label in zip(schema_locations, subject_locations):
        if schema_label not in schema.children or subject_label not in subject.children:
            return None
        result = match(
            schema.children[schema_label], subject.children[subject_label], context, current
        )
        if result is None:
            return None
        current = result

    return current


def match_all(
    pairs: Iterable[tuple[Term, Term]], context: Context, binding: Binding | None = None
) -> Binding | None:
    """Match several ``(schema, subject)`` pairs under one shared substitution.

    This is how an inference step is checked: every antecedent schema and the
    deduction schema must match their proof-line terms under a *single*
    consistent binding (so the ``p`` in an antecedent and the ``p`` in the
    conclusion denote the same formula). Returns the binding on success, or
    ``None`` if no consistent one exists.
    """
    current: Binding = {} if binding is None else binding
    for schema, subject in pairs:
        result = match(schema, subject, context, current)
        if result is None:
            return None
        current = result
    return current


def _sort_admits(sort: Pattern, term: Term, context: Context) -> bool:
    """Whether ``term`` is an instance of ``sort`` - a purely structural check,
    no string re-parsing. Keeps a variable from binding to a term of the wrong
    sort (an ``atom``-sorted variable must not capture an ``implication``).
    """
    term_sort = _term_sort(term)

    # Memoised per (sort, term sort): the answer is a property of the grammar,
    # which does not change once the system is built, but deriving it walks the
    # pattern lattice twice over - and a variable binds against the same pair on
    # every rule check. The memo lives on the sort's constructor, so it is
    # reclaimed with the grammar (see constructors.Constructor.admits).
    memo = constructor_for(sort).admits
    cached = memo.get(term_sort)
    if cached is not None:
        return cached

    admitted = sort.equivalent(term_sort, context, allow_mapping_to=True) or (
        # `term_sort` is one of the union's (possibly nested) branches, e.g. an
        # `implication` is admitted where a `formula` is expected.
        isinstance(sort, UnionPattern)
        and sort.contains_pattern(term_sort, context, allow_nested=True)
    )
    memo[term_sort] = admitted
    return admitted


def _term_sort(term: Term) -> Pattern:
    """The sort (a ``Pattern``) that ``term`` inhabits - a variable's declared
    sort, a node's recorded ``sort`` when it has one (a definition shorthand,
    whose constructor is not itself a member of its sort), or otherwise the
    node's own constructor (already a member of whatever union it belongs to).

    A constructor's ``source`` is the production it was projected from - the sort
    lattice still lives on the matching layer, so this is where the two meet."""
    if isinstance(term, Var):
        return term.sort
    return term.sort if term.sort is not None else term.constructor.source
