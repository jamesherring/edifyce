"""Inference rules and their applications: :class:`InferenceRule`, :class:`Inference`."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..kernel import Var, from_match, from_pattern, match_all
from ..matching import Match, StringPattern, get_by_path, parse_path
from .proof import ProofLine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel import Term
    from ..matching.context import Context
    from ..matching.patterns import Pattern

    # A rule match's substitution: schematic variable name -> the Term it binds to.
    Binding = dict[str, Term]


class InferenceRule:
    """Inference rules for deduction."""

    def __init__(self, name, label=None, antecedents=None, deduction=None, condition=None,
                 allow_extra_antecedents=False, variables=None):

        # The inference rule name
        self.name = name.replace("_", " ")

        # The inference rule label
        self.label = label if label is not None else ""

        # List of antecedent patterns
        self.antecedents = antecedents if antecedents is not None else []

        # Deduction pattern
        self.deduction = deduction

        # Condition for the rule to apply
        self.condition = condition

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
        # binding, derived by unification. This replaces re-parsing each line's
        # string against the schema and reconciling the sub-matches by hand
        # (`check_variables`) - the formulae are already parsed, so we project
        # them straight to terms and never re-run the matcher.
        binding = self._term_binding(antecedents, deduction, context)
        if binding is None:
            # No consistent match
            return False

        # The rule's condition is still evaluated by the legacy interpreter,
        # which reads its variables as Match objects. Build those (the old
        # string-matching path) only when a condition is present; they move to
        # the kernel's SideCondition algebra in a later step.
        if self.condition is not None and not self._legacy_condition_holds(
            inference, antecedents, deduction, context
        ):
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

    def _legacy_condition_holds(
        self,
        inference: "Inference",
        antecedents: Sequence[ProofLine],
        deduction: ProofLine,
        context: Context,
    ) -> bool:
        """Evaluate the rule's condition on the legacy Match interpreter.

        The condition mini-language reads its variables as ``Match`` objects, so
        rebuild the deduction/antecedent matches and the consolidated
        ``inference.variables`` the old way, then check the condition against
        them. Retained verbatim until conditions move to the SideCondition
        algebra; ``_term_binding`` has already decided the structural match.
        """
        inference.deduction_inference_match = self.deduction.match(
            deduction.formula.formatted_string(), context
        )
        if inference.deduction_inference_match is None:
            return False

        for pattern, ant in zip(self.antecedents, antecedents):
            if ant.line_type is None:
                return False

            if ant.line_type.behaviour != "logical" and pattern.equivalent(
                ant.line_type.pattern, context
            ):
                continue

            if ant.formula is None:
                return False

            match = pattern.match(ant.formula.formatted_string(), ant.context)
            if match is None:
                return False

            inference.antecedent_inference_matches.append(match)

        if not inference.check_variables(context):
            return False

        # Add contextual variables for the condition
        context_copy = copy(context)
        context_copy.mapping = copy(inference.variables)

        try:
            return bool(self.condition.check_condition(inference, context_copy))
        except Exception:
            # Error trying to apply the condition
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

        if not self.condition.equivalent(other.condition, context, memo):
            memo[(self, other)] = False
            return False

        # Otherwise ok
        return True


@dataclass(eq=False)
class Inference:
    """An application of an inference rule."""

    inference_rule: "InferenceRule"

    # Antecedents should be a list of proof lines, deduction should be a proof line
    antecedents: list
    extra_antecedents: list
    deduction: "ProofLine"

    # Inference matches, populated as the rule is checked
    antecedent_inference_matches: list = field(default_factory=list)
    deduction_inference_match: "Match | None" = None

    # Variables used in this inference
    variables: dict = field(default_factory=dict)

    def get_by_path(self, path, context, recurse=True):
        # Get information from the given path

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        initial, remainder = parse_path(path)

        if remainder:
            # Use generic get by path
            return get_by_path(self, path, context)

        # Otherwise, only one part
        if path == "deduction":
            # Get the deduction
            return self.deduction

        if path == "antecedents":
            return self.antecedents

        if path == "extra_antecedents":
            return self.extra_antecedents

        if path == "antecedent":
            return self.antecedents[0]

        if path in self.variables:
            # Get this variable
            return self.variables[path]

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

    def check_variables(self, context):
        # Check the variables for antecedent and deduction matches are consistent

        # Start with a copy of deduction inference match variables
        self.variables = copy(self.deduction_inference_match.sub_matches)

        # Check consistent with antecedents
        for ant_match in self.antecedent_inference_matches:
            for name, sub_match in ant_match.sub_matches.items():
                if name in self.variables:
                    if not sub_match.equivalent(self.variables[name], context):
                        # Same variable with different value
                        return False

                else:
                    # Add to variables
                    self.variables[name] = sub_match

        # All consistent
        return True
