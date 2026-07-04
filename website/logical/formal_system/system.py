"""The top-level :class:`FormalSystem`."""

from copy import copy

from ..matching import Context, Match, Pattern, StringPattern, UnionPattern
from .proof import Proof


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

    def get_references(self, text):
        # Get references to external proofs from the given code.

        # Create a default context
        context = copy(self.context)

        # Track the reference slugs
        references = set()

        # Get the import line types
        import_line_types = [line_type for line_type in self.line_types if line_type.behaviour == "import"]

        lines = text.split("\n")
        for line in lines:

            # Check the line is an import line type
            for line_type in import_line_types:

                result = line_type.parse_line(line, context)

                if result is None:
                    continue

                # Get the path
                try:
                    path = result.get_by_path("path()", context)

                except Exception:
                    # No valid path here
                    continue

                references.add(path)
                break

        return references

    def parse(self, text, proof=None, proof_model_id=None, reference_proofs=None, context=None, line_number_offset=0,
              previous_proof=None, previous_proof_lines_mapped=None):
        # Parse the text into a proof.

        # Optionally specify a previous version of the same proof (via ``previous_proof``) to save
        # reprocessing unchanged lines.

        # Maintain a dictionary of previous proof lines: new proof lines
        previous_proof_lines_mapped = previous_proof_lines_mapped if previous_proof_lines_mapped is not None else {}

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

            # Check if this line was in the previous proof
            found_previous_line = False

            if previous_proof is not None:
                line_matches = [pl for pl in previous_proof.proof_lines if
                                pl.text == line and pl not in previous_proof_lines_mapped]

                if len(line_matches) > 0:
                    previous_line = line_matches[0]

                    # Add this line to the proof line dictionary
                    previous_proof_lines_mapped[previous_line] = proof_line

                    # Populate the new line (returns boolean for success) - if False the proof line is unchanged.
                    result = proof_line.copy_from_previous_proof(previous_line, previous_proof_lines_mapped)

                    # Still need to follow indent/non-indent line rules

                    if result:
                        # Successfully copied the previous line
                        found_previous_line = True

                    else:
                        # Remove the line from the dictionary
                        del previous_proof_lines_mapped[previous_line]

            found = False
            if not found_previous_line:
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

                    # Check for main line type attributes
                    # Try to get the formula, reference, label, display, is_axiom
                    try:
                        # Add formula to the proof line
                        proof_line.formula = result.get_by_path("formula()", context)

                        # It has to be a match
                        if type(proof_line.formula) is not Match:
                            proof_line.formula = None

                    except Exception:
                        pass

                    try:
                        reference_match = result.get_by_path("reference()", context)

                        proof_line.reference_string = reference_match.formatted_string()
                        proof_line.reference_string_display = reference_match.string

                    except Exception:
                        pass

                    try:
                        label = result.get_by_path("label()", context)
                        proof_line.label = label

                    except Exception:
                        pass

                    # Check if the line type has a 'display' value
                    try:
                        proof_line.display = result.get_by_path("display()", context)
                    except Exception:
                        # No valid display path
                        pass

                    try:
                        # Check if there is a valid axiom
                        result.get_by_path("axiom()", context)
                        proof_line.is_axiom = True
                    except Exception:
                        # Not an axiom
                        pass

                    # No need to check other line types
                    break

                if not found:
                    # The line doesn't match any of the line types. Invalid proof
                    proof_line.invalid_message = "Could not parse line."
                    proof_line.valid = False

            if found_previous_line or found:
                # Follow indent/non-indent line rules

                if not proof_line.line_type.behaviour == "indent":
                    # Check for data to add to context
                    try:
                        proof_line.edit_context(context)

                    except Exception as e:
                        # Error in editing context
                        proof_line.valid = False
                        proof_line.invalid_message = str(e)

                else:
                    # This is an indent line.
                    # Parse the block with a copied context

                    new_context = copy(context)

                    # Edit context
                    proof_line.edit_context(new_context)

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
                        line_number_offset=i + 1,
                        previous_proof=previous_proof,
                        previous_proof_lines_mapped=previous_proof_lines_mapped
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
