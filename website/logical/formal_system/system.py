"""The top-level :class:`FormalSystem`."""

from copy import copy

from ..matching import Context, Match, Pattern, StringPattern, UnionPattern
from .proof import Proof


def _line_field(match: Match, field: str) -> Match:
    # Project a LineType's declared formula/reference field off a line match.
    # The reserved value "self" denotes the whole match (an axiom asserting its
    # entire formula); any other value names a matched sub-field to read.
    if field == "self":
        return match
    return match.field(field)


class FormalSystem:
    """A formal system."""

    def __init__(self, name, line_types=None, inference_rules=None, build_context=None, context=None):

        # The name of the system
        self.name = name

        # A list of line types
        self.line_types = line_types if line_types is not None else []

        # A list of valid inference rules for the system
        self.inference_rules = inference_rules if inference_rules is not None else []

        # The build context from compiler
        self.build_context = build_context

        # Per declared definition, in spec order, whether it layered: i.e. its
        # defining form was recognised given the definitions before it. The
        # declarative builder sets this; it stays empty for systems built another
        # way. Keyed by position (not by notation) so callers can tell two
        # distinct definitions apart even when they share a defined form.
        self.definition_layering: list[bool] = []

        # A pattern dictionary of all the patterns used in build context
        self.pattern_dictionary = {}

        # Default proof context
        self.context = Context(
            logical=context if context is not None else {}
        )

    def build_pattern_dictionary(self):
        # Build the pattern dictionary using items included in the build context

        if self.build_context is None:
            return

        def add_pattern(dct, pattern):
            # Add a pattern to the dictionary

            if pattern.url_id in dct:
                return

            # Add the pattern to the dictionary
            dct[pattern.url_id] = pattern

            # Look for subpatterns
            if isinstance(pattern, StringPattern):
                for sub_pattern in pattern.variables.values():
                    add_pattern(dct, sub_pattern)

            elif isinstance(pattern, UnionPattern):
                for sub_pattern in pattern.patterns:
                    add_pattern(dct, sub_pattern)

        # Look in the build dictionary variables for patterns
        for item in self.build_context.variables.values():
            if not isinstance(item, Pattern):
                continue

            # Add the pattern
            add_pattern(self.pattern_dictionary, item)

    def parse(self, text, proof=None, proof_model_id=None, reference_proofs=None, context=None, line_number_offset=0):
        # Parse the text into a proof.

        lines = text.split("\n")

        if proof is None:
            # Create a new proof instance
            proof = Proof(formal_system=self)
            proof.reference_proofs = reference_proofs

        if context is None:
            # Create a new proof context instance
            context = copy(self.context)
            context.proof_model_id = proof_model_id

        i = -1
        while i + 1 < len(lines):

            # Increment at the start so we can use 'continue' without concern
            i += 1

            line = lines[i].rstrip()

            # Create a proof line for this line
            proof_line = proof.add_proof_line(line, context)

            # Assume valid unless we find an issue
            proof_line.valid = True

            if proof_line.empty:
                # Ignore blank lines
                continue

            found = False
            # Check the line is of a given line type
            for line_type in self.line_types:

                line = line.lstrip()
                result = line_type.parse_line(line, context)

                if result is None:
                    continue

                # Otherwise meets this line type
                found = True

                # Record the line_type of this line
                proof_line.line_type = line_type
                proof_line.match = result

                # Project the line type's declared formula/reference fields off
                # the match. (`label`, `display` and axiom-marking are handled by
                # ProofLine's defaults and the `behaviour: axiom` line type - not
                # by string `get_by_path` accessors, which could no longer be
                # defined since the accessor-function syntax was removed.)
                if line_type.formula_field is not None:
                    # The logical formula is the sub-field the line type declares
                    # (or the whole match, for `formula: self`).
                    try:
                        formula = _line_field(result, line_type.formula_field)
                        # It has to be a match
                        if type(formula) is Match:
                            proof_line.formula = formula
                    except Exception:
                        pass

                if line_type.reference_field is not None:
                    # The citation reference is the declared sub-field.
                    try:
                        reference_match = _line_field(result, line_type.reference_field)
                        proof_line.reference_string = reference_match.formatted_string()
                        proof_line.reference_string_display = reference_match.string
                    except Exception:
                        pass

                # No need to check other line types
                break

            if not found:
                # The line doesn't match any of the line types. Invalid proof
                proof_line.invalid_message = "Could not parse line."
                proof_line.valid = False

            # Place the line in its subproof (a no-op for systems that declare
            # no scope openers - every line then lands in the root scope).
            proof.assign_scope(proof_line)

            if found:
                # Follow indent/non-indent line rules

                if proof_line.line_type.behaviour == "indent":
                    # This is an indent line.
                    # Parse the block with a copied context

                    new_context = copy(context)

                    # Find the next line with this indent
                    j = i + 1
                    while j < len(lines):
                        block_line = lines[j]

                        if len(block_line) - len(block_line.lstrip()) <= proof_line.indent and \
                                len(block_line.lstrip()) > 0:
                            # This is the out-denting line
                            break

                        j += 1

                    # Compile the block
                    block = "\n".join(lines[i + 1:j])

                    self.parse(
                        text=block,
                        proof=proof,
                        context=new_context,
                        line_number_offset=i + 1
                    )

                    # Update context with definitions created in the block
                    context.definitions = new_context.definitions

                    # Continue from after the block
                    i = j - 1
                    continue

                # Execute the proof line
                proof_line.execute(context)

        if line_number_offset == 0:
            # Check if the proof is valid or has warnings

            proof.valid = True
            proof.has_warnings = False

            for line in proof.proof_lines:
                if not line.valid:
                    proof.valid = False
                    break

            for line in proof.proof_lines:
                if line.warning_message is not None:
                    proof.has_warnings = True
                    break

        return proof

    def add_inference_rule(self, rule):
        # Add an inference rule

        # Remove existing inference rules with the same label
        self.inference_rules = [ir for ir in self.inference_rules if not ir.label == rule.label]

        # Add the new rule
        self.inference_rules.append(rule)

    def add_line_type(self, line_type):
        # Add a line type

        # Remove existing line types with the same name
        self.line_types = [lt for lt in self.line_types if not lt.name == line_type.name]

        # Add the new line type
        self.line_types.append(line_type)

    def equivalent(self, other, context, memo=None):
        # Check if two formal systems are equivalent

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if not type(other) is FormalSystem:
            return False

        if not self.name == other.name:
            return False

        if not len(self.line_types) == len(other.line_types):
            return False

        if not len(self.inference_rules) == len(other.inference_rules):
            return False

        # Assume equivalent while checking recursively
        memo[(self, other)] = True

        for self_line, other_line in zip(self.line_types, other.line_types):
            if not self_line.equivalent(other_line, context, memo):
                memo[(self, other)] = False
                return False

        for self_rule, other_rule in zip(self.inference_rules, other.inference_rules):
            if not self_rule.equivalent(other_rule, context, memo):
                memo[(self, other)] = False
                return False

        if not self.context.equivalent(other.context, context, memo):
            memo[(self, other)] = False
            return False

        # Otherwise ok
        return True

    def format_string(self, s):
        # Format a string s
        pattern = StringPattern(name="temporary", pattern="", pre_format=self.build_context.pre_format)
        return pattern.pre_format_apply(s)

    def __str__(self):
        return self.name
