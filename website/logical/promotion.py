"""Building a :class:`PromotedTheorem` from a proved or imported theorem's source.

Promotion is how a proved lemma — or one imported from another corpus, notably a
Metamath ``$p`` — becomes citable in a system without joining its primitive
inference rules. The statement arrives as text in *the system's own grammar*, not
a source language of ours, so this is engine surface rather than anything to do
with the retired ``.edi`` compiler it used to share a module with.

See :class:`~website.logical.formal_system.promotion.PromotedTheorem` for what a
promoted theorem is, and :meth:`FormalSystem.promote` for registering one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import copy
from typing import TYPE_CHECKING

from website.logical.build_context import (
    FormalSystemContext,
    build_schema_pattern,
    warm_grammar_index,
)
from website.logical.formal_system import FormalSystem, PromotedTheorem
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import from_match
from website.logical.matching import Pattern, StringPattern

if TYPE_CHECKING:
    from website.logical.kernel.terms import Term


def _logical_sorts(system: FormalSystem) -> list[Pattern]:
    # The sorts a proof line's formula is actually parsed at: each logical line
    # type's declared formula field (or the whole line pattern, for `formula:
    # self`). Composing a ground statement against *these* - rather than whichever
    # sort in the grammar happens to match first - keeps promotion in step with how
    # the system parses a line, so a theorem cannot be built against an unrelated
    # sort that no proof line would ever be read at.
    sorts: list[Pattern] = []
    for line_type in system.line_types:
        if line_type.behaviour != "logical" or line_type.formula_field is None:
            continue

        if line_type.formula_field == "self":
            sort = line_type.pattern
        elif isinstance(line_type.pattern, StringPattern):
            sort = line_type.pattern.variables.get(line_type.formula_field)
        else:
            continue

        if isinstance(sort, Pattern) and not any(sort is seen for seen in sorts):
            sorts.append(sort)
    return sorts


def _ground_schema_term(
    text: str,
    system: FormalSystem,
    context: FormalSystemContext,
    sorts: Sequence[Pattern],
) -> Term | None:
    # Compose the nested kernel term of a *ground* statement - one with literal
    # structure but no metavariables, like a closed theorem `2 ∈ ℝ`.
    #
    # compose_schema_term deliberately declines these (it keys on a metavariable),
    # so promotion composes them here instead. Two differences from that path: the
    # parse runs only at the system's logical `sorts` (see _logical_sorts), never
    # falling back to the rest of the grammar, and may use the system's *resolved*
    # definitions, which live on the built system's proof context - a
    # promoted theorem is built against an already-compiled system, unlike a rule
    # schema composed mid-compilation, where the build context still holds pending
    # records. There is nothing to re-variabilise: a ground statement binds no
    # metavariable. Returns None when no logical sort parses the text.
    parse_context = copy(context)
    parse_context.definitions = list(system.context.definitions)
    # Same reasoning as compose_schema_term: nothing this parse depends on moves
    # while it runs, so the substring parses can be memoised.
    parse_context.parse_memo = {}
    for sort in sorts:
        matched = sort.match(text, parse_context)
        if matched is not None:
            return from_match(matched)
    return None


def _theorem_schema(
    text: str,
    system: FormalSystem,
    context: FormalSystemContext,
    name: str,
    matching: str,
) -> Pattern:
    # Build one schema pattern for a promoted theorem's statement or premise.
    #
    # A *ground* compound - literal structure but no metavariables - composes no
    # schema term through the rule path, and its flat projection cannot match the
    # nested term a proof formula parses to, so it would be a theorem that never
    # applies. Compose the ground term explicitly instead: the schema is then that
    # exact term, and unification against a cited line is structural equality -
    # precisely the semantics of a closed theorem (`2 ∈ ℝ` justifies `2 ∈ ℝ` and
    # nothing else). A statement *with* metavariables is left alone: it projects
    # structurally even when nothing is composed, notably defined notation, whose
    # flat projection does apply (a `sub` alias matches an `a sub b` line).
    #
    # Only for structural matching: the string checker matches surface strings and
    # never reads `schema_term` (see InferenceRule.check), so composing a term for
    # it - let alone failing when none composes - would be meaningless.
    # A promoted theorem's statement is a proof line's formula, so it is read at
    # the sorts a line is read at - not at whichever sort of the grammar happens
    # to come first. Both composition paths take the same list.
    sorts = _logical_sorts(system)
    pattern = build_schema_pattern(text, context, name, prefer=sorts)
    if (
        matching != "string"
        and isinstance(pattern, StringPattern)
        and pattern.schema_term is None
        and pattern.non_variable_locations
        and not pattern.variable_locations
    ):
        ground = _ground_schema_term(text, system, context, sorts)
        if ground is None:
            raise ValueError(
                f"Statement {text!r} has no metavariables and does not parse at any "
                "of the system's logical sorts."
            )
        # A fresh shell, never the pattern build_schema_pattern returned: that can
        # be a system-owned pattern out of the grammar, which must not be given a
        # theorem's schema term.
        pattern = StringPattern(name=name, pattern=text)
        pattern.schema_term = ground
    return pattern


def promote_from_source(
    system: FormalSystem,
    label: str,
    statement: str,
    metavariables: Mapping[str, str],
    premises: Sequence[str] = (),
    distinct: Sequence[str] = (),
    matching: str = "structural",
) -> PromotedTheorem:
    """Build a :class:`PromotedTheorem` from a proved/imported theorem's source.

    The import-facing promotion route. The theorem is given as source text in the
    system's own grammar: its conclusion ``statement``, its hypotheses
    ``premises``, its ``metavariables`` (name -> sort name), and its distinct-
    variable provisos ``distinct`` (each a ``disjoint(...)`` line). A Metamath
    ``$p`` maps here directly - ``$e`` -> ``premises``, ``$f`` -> ``metavariables``,
    ``$d`` -> ``distinct``. The metavariables are re-instantiated at each citation
    by unification and the provisos enforced against that binding (see
    :class:`~website.logical.formal_system.promotion.PromotedTheorem`).

    Unlike generalising a concrete proof line by renaming leaves, this parses the
    statement against the grammar with the metavariables held schematic, so a
    formula metavariable may stand for a *compound* (the usual case).

    ``matching`` sets how a citation is checked, mirroring ``InferenceRule``:
    ``"structural"`` (term unification, the default) or ``"string"`` for a theorem
    proved in a semi-Thue / string-rewriting system (e.g. MIU), which must stay
    string-checked to remain applicable.

    Register the result with :meth:`FormalSystem.promote` to make it citable. The
    theorem is not added to the system's primitive ``inference_rules``.

    A *closed* theorem - one whose statement is ground, such as Metamath's
    ``2 e. RR`` - is supported: with no metavariables to instantiate it justifies
    exactly its own statement and nothing else.

    Raises :class:`ValueError` if the system has no build context, if a sort name
    is not a declared pattern of the system, or if a structurally-matched ground
    conclusion/premise parses at none of the system's logical sorts. A statement
    *with* metavariables that names an undefined symbol is not rejected here - as
    with an authored rule schema it simply yields a theorem that never applies - so
    validate imports upstream.
    """
    if system.build_context is None:
        raise ValueError("Cannot promote a theorem against a system with no build context.")

    # Copy the context so the theorem's metavariables can be set in
    # string_variables without mutating the system's own build context. Warm the
    # grammar index on the original first, so the copy inherits it rather than
    # rebuilding it per theorem.
    warm_grammar_index(system.build_context)
    context = copy(system.build_context)
    string_variables: dict[str, Pattern] = {}
    for name, sort_name in metavariables.items():
        sort = system.build_context.variables.get(sort_name)
        if not isinstance(sort, Pattern):
            raise ValueError(
                f"Metavariable {name!r} names sort {sort_name!r}, which is not a "
                "declared pattern of the system."
            )
        string_variables[name] = sort
    context.string_variables = string_variables

    deduction = _theorem_schema(statement, system, context, label, matching)
    antecedents = tuple(
        _theorem_schema(text, system, context, f"{label}.premise{index}", matching)
        for index, text in enumerate(premises)
    )
    side_conditions = tuple(parse_side_condition(line, context) for line in distinct)

    return PromotedTheorem(
        label=label,
        deduction=deduction,
        antecedents=antecedents,
        side_conditions=side_conditions,
        variables=dict(string_variables),
        matching=matching,
    )
