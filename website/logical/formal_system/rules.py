"""Inference rules and their applications: :class:`InferenceRule`, :class:`Inference`."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..matching import Match, get_by_path, parse_path
from .proof import ProofLine, Subproof

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.patterns import Pattern


@dataclass(eq=False)
class SubproofSchema:
    """The subproof an inference rule discharges.

    A discharge rule (conditional proof, RAA, universal generalisation) does
    not cite individual lines - it consumes a whole subproof as a unit. This
    records what that subproof must look like:

    ``assumption`` - pattern the subproof's opening hypothesis must match, or
                     ``None`` when the subproof is opened by a fresh variable
                     rather than a hypothesis.
    ``conclusion`` - pattern the subproof's final line must match.
    ``fresh``      - the eigenvariable pattern for a variable-opened subproof
                     (universal generalisation), or ``None``. Its presence is
                     what makes the rule require a ``variable`` subproof rather
                     than an ``assumption`` one; the freshness side-condition is
                     enforced in :meth:`InferenceRule.check_discharge`.
    """

    conclusion: Pattern
    assumption: Pattern | None = None
    fresh: Pattern | None = None

    @property
    def kind(self) -> str:
        # Which kind of scope opener this schema discharges.
        return "variable" if self.fresh is not None else "assumption"


class InferenceRule:
    """Inference rules for deduction."""

    def __init__(self, name, label=None, antecedents=None, deduction=None, condition=None,
                 allow_extra_antecedents=False, variables=None, subproof_schema=None):

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

        # The subproof this rule discharges (SubproofSchema), if it is a
        # discharge rule. None for an ordinary line-antecedent rule.
        self.subproof_schema = subproof_schema

    @property
    def is_discharge(self) -> bool:
        # Whether this rule discharges a subproof rather than citing lines.
        return self.subproof_schema is not None

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

        # First check if the deduction matches
        inference.deduction_inference_match = self.deduction.match(deduction.formula.formatted_string(), context)

        if inference.deduction_inference_match is None:
            # No match
            return False

        # Check if the antecedents match
        for pattern, ant in zip(self.antecedents, antecedents):
            if ant.line_type is None:
                return False

            if (not ant.line_type.behaviour == "logical") and pattern.equivalent(ant.line_type.pattern, context):
                # This is an instance of a non-logical line
                continue

            if ant.formula is None:
                return False

            # Set the inference match - can be used in the Condition
            match = pattern.match(ant.formula.formatted_string(), ant.context)

            if match is None:
                # No match
                return False

            inference.antecedent_inference_matches.append(match)

        # Check variables are consistent
        if not inference.check_variables(context):
            # Variables not consistent
            return False

        # Check the rule condition
        if self.condition is not None:
            # Add contextual variables for the condition
            context_copy = copy(context)
            context_copy.mapping = copy(inference.variables)

            try:
                if not self.condition.check_condition(inference, context_copy):
                    # Doesn't meet the condition
                    return False

            except Exception:
                # Error trying to apply the condition
                return False

        # Otherwise ok
        deduction.inference_rule = self
        deduction.inference = inference
        deduction.valid = True

        # Add the deduction line as dependent to each of the antecedents
        for ant in antecedents:
            ant.dependent_lines.add(deduction)

        return True

    def check_discharge(self, subproof: Subproof, deduction: ProofLine, context: Context) -> bool:
        # Check that `deduction` follows by discharging `subproof` under this rule.

        schema = self.subproof_schema

        if schema is None or deduction.formula is None:
            return False

        # The subproof must be opened the way the schema expects (a hypothesis
        # for conditional-proof-style rules, a fresh variable for generalisation).
        if subproof.kind != schema.kind:
            return False

        conclusion = subproof.conclusion
        if conclusion is None or conclusion.formula is None:
            # An empty subproof discharges nothing.
            return False

        # Derive one consistent binding across the deduction and the subproof's
        # assumption/conclusion, forcing shared metavariables (the `p` in both a
        # subproof's assumption and the deduction) to agree. This uses the same
        # string matcher as InferenceRule.check: the term-based checker
        # (kernel.unify) is not yet the live matcher - migrating discharge to it
        # alone would reject ground-literal conclusions such as a falsum `⊥`,
        # whose rule schema is a StringPattern literal but whose proof-line match
        # is a RegexPattern (different term constructors). That is the "close the
        # loop into a term-based proof checker" work the kernel roadmap defers to
        # step 4, to be done for the whole checker at once, not piecemeal here.
        deduction_match = self.deduction.match(deduction.formula.formatted_string(), context)
        if deduction_match is None:
            return False

        variables: dict = copy(deduction_match.sub_matches)

        pairs: list[tuple[Pattern, ProofLine]] = [(schema.conclusion, conclusion)]
        if schema.assumption is not None:
            pairs.append((schema.assumption, subproof.assumption))

        for pattern, line in pairs:
            if line is None or line.formula is None:
                return False

            match = pattern.match(line.formula.formatted_string(), context)
            if match is None:
                return False

            for name, sub_match in match.sub_matches.items():
                if name in variables:
                    if not sub_match.equivalent(variables[name], context):
                        return False
                else:
                    variables[name] = sub_match

        # Freshness side-condition for universal generalisation: the
        # eigenvariable must be genuinely arbitrary - it may not occur in any
        # hypothesis still in force around the subproof (checked structurally on
        # kernel terms by Subproof.eigenvariable_is_fresh).
        if schema.fresh is not None and not subproof.eigenvariable_is_fresh(context):
            return False

        deduction.inference_rule = self
        deduction.valid = True
        return True

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
