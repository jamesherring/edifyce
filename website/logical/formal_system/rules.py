"""Inference rules and their applications: :class:`InferenceRule`, :class:`Inference`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel import (
    And,
    DisjointLeaves,
    Equal,
    IsAtom,
    Not,
    Occurs,
    Or,
    Var,
    from_match,
    from_pattern,
    match_all,
)
from ..matching import StringPattern
from .proof import ProofLine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel import SideCondition, Term
    from ..matching.context import Context
    from ..matching.patterns import Pattern

    # A rule match's substitution: schematic variable name -> the Term it binds to.
    Binding = dict[str, Term]


def _normalise_side_condition(condition: SideCondition) -> tuple:
    """A structural normal form for comparing side-conditions across rules.

    Sorts compare by name (not object identity) so two systems that re-parse the
    same proviso agree, and boolean combinators fold to their parts. Used only
    by :meth:`InferenceRule.equivalent`.
    """
    if isinstance(condition, (And, Or)):
        return (
            type(condition).__name__,
            tuple(sorted(_normalise_side_condition(part) for part in condition.parts)),
        )
    if isinstance(condition, Not):
        return ("Not", _normalise_side_condition(condition.inner))
    if isinstance(condition, Occurs):
        return ("Occurs", condition.needle, condition.haystack)
    if isinstance(condition, Equal):
        return ("Equal", condition.left, condition.right)
    if isinstance(condition, DisjointLeaves):
        sort = None if condition.sort is None else condition.sort.name
        return ("DisjointLeaves", condition.left, condition.right, sort)
    if isinstance(condition, IsAtom):
        sort = None if condition.sort is None else condition.sort.name
        return ("IsAtom", condition.name, sort)
    return (type(condition).__name__,)


class InferenceRule:
    """Inference rules for deduction."""

    def __init__(self, name, label=None, antecedents=None, deduction=None, side_conditions=None,
                 allow_extra_antecedents=False, variables=None):

        # The inference rule name
        self.name = name.replace("_", " ")

        # The inference rule label
        self.label = label if label is not None else ""

        # List of antecedent patterns
        self.antecedents = antecedents if antecedents is not None else []

        # Deduction pattern
        self.deduction = deduction

        # Kernel side-conditions (provisos) that must hold for the rule to apply,
        # checked structurally against the term binding. See side_condition_syntax.
        self.side_conditions = side_conditions if side_conditions is not None else []

        # Optionally allow extra antecedents
        self.allow_extra_antecedents = allow_extra_antecedents

        # Keep a set of variables handy
        self.variables = variables

    def check(self, antecedents, extra_antecedents, deduction, context):
        # Check to see if the proposed proof lines are valid under this inference rule

        # Check the number of antecedents matches
        if not len(antecedents) == len(self.antecedents):
            return False

        if type(deduction) is not ProofLine:
            # Deduction doesn't point to a valid proof line
            return False

        # Deduction must be after the antecedents
        for ant in antecedents + extra_antecedents:
            if type(ant) is not ProofLine:
                # antecedent isn't a proof line
                return False

            # Deduction in the same proof must come after the antecedents
            if deduction.proof is ant.proof and deduction.index() <= ant.index():
                return False

        # Create an inference instance
        inference = Inference(self, antecedents, extra_antecedents, deduction)

        # Structural check over terms (the graph representation): the deduction
        # and every logical antecedent must match their schemas under one shared
        # binding, derived by unification. The formulae are already parsed, so we
        # project them straight to terms and never re-run the string matcher.
        binding = self._term_binding(antecedents, deduction, context)
        if binding is None:
            # No consistent match
            return False

        # Kernel side-conditions: soundness-critical provisos (freshness, $d,
        # atomicity, equality) checked structurally against that same binding.
        if not self._side_conditions_hold(binding, context):
            return False

        # Otherwise ok
        deduction.inference_rule = self
        deduction.inference = inference
        deduction.valid = True

        # Add the deduction line as dependent to each of the antecedents
        for ant in antecedents:
            ant.dependent_lines.add(deduction)

        return True

    def _term_binding(
        self, antecedents: Sequence[ProofLine], deduction: ProofLine, context: Context
    ) -> Binding | None:
        """Derive the substitution under which the deduction and every logical
        antecedent match their schemas, or ``None`` if none is consistent.

        Each ``(schema, subject)`` pair is projected into the term space -
        schemas via :func:`from_pattern` (variable slots become ``Var`` leaves),
        already-parsed formulae via :func:`from_match` - and unified together, so
        a metavariable shared across antecedents and the conclusion is forced to
        one value by a single binding rather than reconciled after the fact.
        """
        if deduction.formula is None:
            return None

        pairs = [
            (self._schema_term(self.deduction, 0, context), from_match(deduction.formula, context))
        ]

        for occurrence, (pattern, ant) in enumerate(zip(self.antecedents, antecedents), start=1):
            if ant.line_type is None:
                return None

            if ant.line_type.behaviour != "logical" and pattern.equivalent(
                ant.line_type.pattern, context
            ):
                # An instance of a non-logical line: matched structurally by its
                # type, it carries no formula variables, so it binds nothing.
                continue

            if ant.formula is None:
                return None

            pairs.append(
                (self._schema_term(pattern, occurrence, context), from_match(ant.formula, context))
            )

        return match_all(pairs, context)

    def _schema_term(self, pattern: Pattern, occurrence: int, context: Context) -> Term:
        """Project a schema pattern into a term, keeping named metavariables
        shared but making each bare-sort position independent.

        A named metavariable (``p``, ``q``, ... - a ``StringPattern`` slot) is
        meant to denote the same formula everywhere it appears, so its name is
        left intact and the shared binding pins it. A bare sort used directly
        (``formula`` meaning "any formula") has no name to share by; two such
        positions are independent premises, so each occurrence's anonymous
        variable is renamed apart rather than collapsed into one binding.
        """
        term = from_pattern(pattern, context)

        if isinstance(pattern, StringPattern):
            return term

        renames = {
            name: Var(f"{name}\x00{occurrence}", sort)
            for name, sort in term.free_vars().items()
        }
        return term.substitute(renames, context) if renames else term

    def _side_conditions_hold(self, binding: Binding, context: Context) -> bool:
        """Whether every side-condition holds against the rule's term binding.

        Each proviso is a closed, structural predicate over the matched terms
        (see :mod:`~website.logical.kernel.side_conditions`). A *malformed*
        proviso - one naming a metavariable the rule never binds - raises inside
        the kernel; we fail closed (the rule does not apply) rather than let it
        escape and abort the whole proof parse. Rejecting is sound: a bad
        proviso can only make a rule too strict, never accept an invalid step.
        """
        try:
            return all(
                side_condition.check(binding, context)
                for side_condition in self.side_conditions
            )
        except Exception:
            return False

    def equivalent(self, other, context, memo=None):
        # Check equivalent

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume false
        memo[(self, other)] = False

        if type(other) is not InferenceRule:
            return False

        if not self.name == other.name:
            return False

        if not self.label == other.label:
            return False

        if not len(self.antecedents) == len(other.antecedents):
            return False

        if not self.allow_extra_antecedents == other.allow_extra_antecedents:
            return False

        # Assume true
        memo[(self, other)] = True

        for ant, other_ant in zip(self.antecedents, other.antecedents):
            if not ant.equivalent(other_ant, context, memo):
                memo[(self, other)] = False
                return False

        if not self.deduction.equivalent(other.deduction, context, memo):
            memo[(self, other)] = False
            return False

        if [_normalise_side_condition(c) for c in self.side_conditions] != [
            _normalise_side_condition(c) for c in other.side_conditions
        ]:
            memo[(self, other)] = False
            return False

        # Otherwise ok
        return True


@dataclass(eq=False)
class Inference:
    """A successful application of an inference rule, recorded on the deduction.

    Holds the rule and the proof lines it related. The structural match is now a
    term binding derived in :meth:`InferenceRule.check` (via unification) and is
    not retained here - the old Match-tree fields and variable-reconciliation
    walk went away with the string-based condition path.
    """

    inference_rule: "InferenceRule"

    # Antecedents and extra antecedents are proof lines; deduction is a proof line.
    antecedents: list
    extra_antecedents: list
    deduction: "ProofLine"
