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

from copy import copy, deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import And, Node, Var, from_match, intern
from website.logical.matching import AtomPattern, Pattern, StringPattern, UnionPattern

if TYPE_CHECKING:
    from website.logical.kernel.side_conditions import SideCondition
    from website.logical.kernel.terms import Term


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

    def inherit(self, parent: FormalSystemContext) -> None:
        # Inherit from parent context

        self.variables.update(parent.variables)
        self.definitions.extend(parent.definitions)
        self.proof_context.update(parent.proof_context)
        self.system_dict.update(parent.system_dict)

        # Don't inherit string_variables or current_object

        # Inherit union patterns
        for pattern in self.variables.values():
            if not isinstance(pattern, UnionPattern):
                continue

            # Pattern is a union pattern. Set the inheritance
            pattern.inherits = deepcopy(pattern)

    def __copy__(self) -> FormalSystemContext:
        new_context = FormalSystemContext()

        new_context.variables = copy(self.variables)
        new_context.string_variables = copy(self.string_variables)
        new_context.definitions = copy(self.definitions)
        new_context.current_object = self.current_object
        new_context.proof_context = copy(self.proof_context)
        new_context.system_dict = copy(self.system_dict)
        new_context.error_log = copy(self.error_log)

        return new_context


def build_schema_pattern(text: str, context: FormalSystemContext, name: str) -> Pattern:
    # Build a rule-schema pattern from a source token. A bare constant atom
    # (e.g. a falsum `⊥`) resolves to its *declared* AtomPattern, so the rule's
    # literal and the proof line's atom are the same constructor on the term
    # representation - otherwise a StringPattern literal and the atom would be
    # different constructors and the (now term-based) checker would reject the
    # step. A referenced pattern name is used directly; anything else becomes a
    # StringPattern template with the ambient string variables applied.
    if text in context.variables:
        return context.variables[text]

    for candidate in context.variables.values():
        if isinstance(candidate, AtomPattern) and candidate.is_constant and candidate.is_member(text):
            return candidate

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
    pattern.schema_term = compose_schema_term(pattern, context)
    return pattern


def compose_schema_term(pattern: Pattern, context: FormalSystemContext) -> Term | None:
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

    for candidate in context.variables.values():
        if isinstance(candidate, UnionPattern):
            match = candidate.match(pattern.pattern, parse_context)
            if match is not None:
                return revariabilise(from_match(match), context.string_variables)

    return None


def revariabilise(term: Term, metavariables: dict) -> Term:
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
    # Parse a definition's `where` provisos into a single kernel side-condition
    # (their conjunction), or None when there are none. Each line uses the same
    # closed vocabulary as a rule's side_conditions (see side_condition_syntax).
    if not where_strings:
        return None
    conditions = [parse_side_condition(text, context) for text in where_strings]
    return conditions[0] if len(conditions) == 1 else And(tuple(conditions))
