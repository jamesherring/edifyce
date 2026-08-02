"""Primitives for constructing a :class:`FormalSystem` from declared parts.

The build context — the namespace a system is assembled in — plus the two
constructions that need it: turning a rule-schema token into a pattern, and
folding a definition's provisos into one kernel side-condition.

These are construction, not parsing: ``declarative.build_system`` drives them
from ``SystemSpec`` fields. They lived in the retired ``.edi`` compiler until
that module became deletable, which is why they are a module of their own rather
than part of ``declarative``.

Layering: free to import ``matching``, ``kernel``, and ``formal_system`` (see
AGENTS.md) — but nothing here may import ``declarative``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import And, Node, Var, from_match, intern
from website.logical.kernel.constructors import project_sorts
from website.logical.matching import AtomPattern, Pattern, StringPattern, UnionPattern

if TYPE_CHECKING:
    from website.logical.kernel.constructors import Constructor
    from website.logical.kernel.side_conditions import SideCondition
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context


@dataclass(eq=False)
class FormalSystemContext:
    """The namespace a formal system is built in."""

    # Variables in the code
    variables: dict = field(default_factory=dict)

    # String variables for inside patterns
    string_variables: dict = field(default_factory=dict)

    # Definitions created along the way
    definitions: list = field(default_factory=list)

    # Current object at a point in the code
    current_object: object = None

    # Proof context
    proof_context: dict = field(default_factory=dict)

    # External systems for reference
    system_dict: dict = field(default_factory=dict)

    # Error log
    error_log: list = field(default_factory=list)

    # Memo for one top-level parse: {(id(pattern), string): Match | None}. None
    # disables memoisation, which is the default - a context is long-lived and
    # what a string parses to depends on `definitions` and `string_variables`, so
    # only a caller that knows those are fixed for the duration may switch it on
    # (see compose_schema_term). Shared, not copied, by `__copy__`, so it
    # survives the context copies taken during a parse.
    parse_memo: dict | None = None

    # Lookups derived from `variables` (see _GrammarIndex). Shared, not rebuilt,
    # by `__copy__`: promotion copies a context per theorem, and the grammar it
    # indexes is the same one throughout.
    grammar_index: object = None

    def __copy__(self) -> FormalSystemContext:
        new_context = FormalSystemContext()

        new_context.variables = copy(self.variables)
        new_context.string_variables = copy(self.string_variables)
        new_context.definitions = copy(self.definitions)
        new_context.current_object = self.current_object
        new_context.proof_context = copy(self.proof_context)
        new_context.system_dict = copy(self.system_dict)
        new_context.error_log = copy(self.error_log)
        new_context.parse_memo = self.parse_memo
        new_context.grammar_index = self.grammar_index

        return new_context


@dataclass(frozen=True)
class SchemaSlot:
    """Which rule-schema template a composed term belongs to.

    Positional, because a ``SystemSpec`` carries no identifiers: the persistence
    layer produces ``spec.rules`` in row order and ``build_system`` consumes it in
    that order, so an index names the same rule at both ends of the round trip.
    """

    rule: int
    # "deduction", "antecedent", or the subproof's "derive" / "assume" / "fresh".
    slot: str
    # An antecedent's position; 0 for the single-valued slots.
    ordinal: int = 0


# Supplies the stored term for a schema slot, given the build context its
# constructors resolve in. `None` always means "compose it" - nothing stored,
# stored but no longer matching the system, or stored as the absence of a term.
# The three are deliberately not distinguished: composing is what the build did
# before any of this existed, so treating them alike costs time on the rare
# template that composes to nothing and can never cost correctness. Reading an
# absence as an answer is the shape of the two bugs P2 shipped with.
SchemaTermSource = Callable[[SchemaSlot, "FormalSystemContext"], "Term | None"]


@dataclass(frozen=True)
class DefinitionSlot:
    """Which of a definition's two surface forms a stored kernel term belongs to.

    Positional for the same reason :class:`SchemaSlot` is: a ``SystemSpec`` names
    nothing, and the persistence layer and the build walk ``spec.definitions`` in
    the same order. The index is into the *spec*, not into the built system's
    definitions — a definition whose defining form matches nothing is dropped, so
    the two lists need not be the same length.
    """

    definition: int
    # "higher" (the defined form), "lower" (the defining form), or "fresh" — the
    # leaf a declared binder's name denotes, one per binder.
    slot: str
    # A declared binder's position in the definition's `fresh` list; 0 for the two
    # single-valued form slots. Positional for the same reason the definition
    # index is, and matching how `SchemaSlot` keys a rule's antecedents.
    ordinal: int = 0


# Supplies the stored term for a definition form, given the parsing context its
# constructors resolve in. `None` means "parse it", on exactly the contract
# `SchemaTermSource` documents above: an absence is never read as an answer.
#
# The context here is a proof `Context` rather than a `FormalSystemContext`,
# because a defined form is grammatical only through the notation registered on
# the *system's* context. Both satisfy what resolving a stored constructor needs
# (`variables` and `definitions`), so the two sources differ only in which one
# the caller is holding at the point it asks.
DefinitionTermSource = Callable[[DefinitionSlot, "Context"], "Term | None"]


def build_schema_pattern(
    text: str,
    context: FormalSystemContext,
    name: str,
    prefer: Sequence[Pattern] = (),
    cached: Term | None = None,
) -> Pattern:
    # Build a rule-schema pattern from a source token. A bare constant atom
    # (e.g. a falsum `⊥`) resolves to its *declared* AtomPattern, so the rule's
    # literal and the proof line's atom are the same constructor on the term
    # representation - otherwise a StringPattern literal and the atom would be
    # different constructors and the (now term-based) checker would reject the
    # step. A referenced pattern name is used directly; anything else becomes a
    # StringPattern template with the ambient string variables applied.
    #
    # A metavariable of this very rule is never a literal, whatever the grammar
    # also spells that way - so it outranks both lookups below. Two ways a grammar
    # can spell one, and a Metamath import supplies both: a production *named* for
    # the metavariable (labels and variable names share no namespace in Metamath,
    # so a syntax axiom may be labelled `ph`), and, since every `$v` is declared as
    # its own atom leaf, an atom whose token is `ph`. Either way a premise stated
    # as the bare `ph` would resolve to that production and match only what it
    # matches, instead of standing for any wff.
    # `side_condition_syntax._arg` gives a proviso argument the same precedence.
    if text not in context.string_variables:
        if text in context.variables:
            return context.variables[text]

        constant = _grammar_index(context).constant_atoms.get(text)
        if constant is not None:
            return constant

    pattern = StringPattern(name=name, pattern=text)
    pattern.add_variables(context.string_variables)

    # Precompute the schema's nested kernel term. A template like a Hilbert axiom
    # `(p → (q → p))` denotes an implication whose right side is itself an
    # implication, but the StringPattern is a single flat production. The
    # term-based checker matches a schema against a proof formula by comparing
    # term trees, and a proof formula is built compositionally from the system's
    # productions, so the schema must project to the *same* nested tree. Parse
    # the template against the productions (with the rule's variables treated as
    # metavariables) once, here, and stash the resulting term; _schema_term uses
    # it. None when the template is a bare variable (from_pattern already nests
    # trivially) or nothing parses it (fall back to the flat projection).
    #
    # `cached` is that same term read back from storage rather than re-derived:
    # composing is a parse against the whole grammar, which is around half of
    # building a system of any size, and it produces the same term every time the
    # grammar and the template are the same. Deciding *whether* it is the same is
    # the caller's (see declarative.schema_digests).
    pattern.schema_term = (
        cached if cached is not None else compose_schema_term(pattern, context, prefer)
    )
    return pattern


def compose_schema_term(
    pattern: Pattern, context: FormalSystemContext, prefer: Sequence[Pattern] = ()
) -> Term | None:
    # Project a compound rule-schema template into its nested kernel term by
    # parsing it against the system's productions. See build_schema_pattern.
    if not pattern.variable_locations or not pattern.non_variable_locations:
        # A bare variable/sort (no literal structure) needs no compositional
        # parse - from_pattern projects it correctly already.
        return None

    # Match against the system's productions only, never its definitions: they
    # are finalised after this runs (step 8 of build_system), so a parse falling
    # through to a definition-unfold could reach one that is not yet resolved.
    # Composition is about productions anyway; a schema recognisable only via a
    # definition simply falls back to the flat projection.
    parse_context = copy(context)
    parse_context.definitions = []
    # Fixed grammar, fixed definitions, fixed metavariables for the whole of this
    # parse, so the same substring always parses the same way - memoise it. The
    # candidate sorts below re-parse overlapping substrings heavily, and nesting
    # multiplies that: a deeply nested template does not finish without it.
    parse_context.parse_memo = {}

    for candidate in _composition_sorts(context, prefer):
        match = candidate.match(pattern.pattern, parse_context)
        if match is not None:
            return revariabilise(from_match(match), project_sorts(context.string_variables))

    return None


@dataclass(frozen=True)
class _GrammarIndex:
    """Two lookups over a context's declared patterns, keyed by how many there are.

    Both answer questions about the *grammar*, which is fixed once a system is
    built - but the two callers above ask them per schema built, and promotion
    builds one per theorem statement and premise. Scanning every declared pattern
    each time is what made those scans, rather than the parse they set up, the
    bulk of building a system with a large grammar. `size` is the guard: a
    context's `variables` only ever grows, while a system is being assembled, so
    a differing count means rebuild.
    """

    size: int
    constant_atoms: dict[str, Pattern]
    unions: list[Pattern]


def warm_grammar_index(context: FormalSystemContext) -> None:
    """Build the grammar index on `context` itself, before it is copied.

    `__copy__` hands the index on by reference, but a copy that has to *build* one
    stores it only on itself and is then thrown away - so promotion, which copies
    the build context per theorem, rebuilt the index for every theorem. Warming
    the original once means every later copy inherits a hit.
    """
    _grammar_index(context)


def _grammar_index(context: FormalSystemContext) -> _GrammarIndex:
    index = context.grammar_index
    if index is not None and index.size == len(context.variables):
        return index

    constant_atoms: dict[str, Pattern] = {}
    unions: list[Pattern] = []
    for candidate in context.variables.values():
        if isinstance(candidate, UnionPattern):
            unions.append(candidate)
        elif isinstance(candidate, AtomPattern) and candidate.is_constant:
            # First declaration wins, as the scan this replaces did.
            constant_atoms.setdefault(candidate.value, candidate)

    index = _GrammarIndex(len(context.variables), constant_atoms, unions)
    context.grammar_index = index
    return index


def _composition_sorts(
    context: FormalSystemContext, prefer: Sequence[Pattern]
) -> list[Pattern]:
    # The sorts to try composing a schema at, `prefer` first. Which sort a schema
    # is read at matters: a template that parses at several sorts composes to a
    # different term at each, and only one of them is the sort a proof line's
    # formula is actually parsed at. Callers that know it (promotion does - see
    # _logical_sorts) pass it, so the answer no longer depends on where in the
    # grammar's declaration order the right sort happens to sit. It is also the
    # faster order where the two differ: the logical sort matches nearly every
    # time, and the sorts otherwise tried first are large unions whose failing
    # parse costs as much as the succeeding one.
    sorts = [pattern for pattern in prefer if isinstance(pattern, UnionPattern)]
    if not sorts:
        return _grammar_index(context).unions

    seen = {id(pattern) for pattern in sorts}
    sorts.extend(
        union for union in _grammar_index(context).unions if id(union) not in seen
    )
    return sorts


def revariabilise(term: Term, metavariables: dict[str, Constructor]) -> Term:
    # Re-mark the rule's metavariables in a compositionally-parsed schema term.
    # Some slots - notably a setvar matched by a RegexPattern, which (unlike a
    # UnionPattern) does not consult string_variables - come back from the parse
    # as ground leaves rather than variables. Turn any leaf whose literal is a
    # declared metavariable into the corresponding Var, so a schema like the ∀I
    # deduction `∀x p` keeps `x` schematic (able to bind, and to be tied to the
    # subproof's eigenvariable) instead of fixing it to the literal token "x".
    def walk(node):
        if isinstance(node, Node):
            if node.literal is not None and node.literal in metavariables:
                return Var(node.literal, metavariables[node.literal])
            if node.children:
                return Node(
                    constructor=node.constructor,
                    children={label: walk(child) for label, child in node.children.items()},
                    literal=node.literal,
                    sort=node.sort,
                )
        return node

    return intern(walk(term))


def combine_side_conditions(
    where_strings: list, context: FormalSystemContext
) -> SideCondition | None:
    # Parse a definition's provisos into a single kernel side-condition (their
    # conjunction), or None when there are none. Each line uses the same closed
    # vocabulary as a rule's side_conditions (see side_condition_syntax).
    if not where_strings:
        return None
    conditions = [parse_side_condition(text, context) for text in where_strings]
    return conditions[0] if len(conditions) == 1 else And(tuple(conditions))
