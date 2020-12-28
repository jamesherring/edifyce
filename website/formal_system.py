from website.context import Context
from django.db import models
import string
import random


def id_gen(length=12, chars=string.ascii_lowercase + string.ascii_uppercase + string.digits + "-_"):
    # An id generator to uniquely identify objects
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))


class FormalSystem(object):
    # A formal system

    def __init__(self, name, axioms=None, line_types=None, inference_rules=None, context_variables=None, context=None):

        # The name of the system
        self.name = name

        # System formula pattern
        self.formula = context_variables["formula"]

        # A list of patterns
        self.axioms = axioms
        if self.axioms is None:
            self.axioms = []

        # Build an axiom dictionary using the names
        self.axiom_dict = dict()
        for a in self.axioms:
            self.axiom_dict[a.name] = a

        # A list of line types and their behaviour
        self.line_types = line_types
        if self.line_types is None:
            self.line_types = []

        # A list of valid inference rules for the system
        self.inference_rules = inference_rules
        if self.inference_rules is None:
            self.inference_rules = []

        # Build an inference rule dictionary using the labels
        self.inference_rule_dict = dict()
        for ir in self.inference_rules:
            self.inference_rule_dict[ir.label] = ir

        # Default context variables
        self.context_variables = context_variables.copy()
        if self.context_variables is None:
            self.context_variables = dict()

        # Default system variables
        self.context_system = dict()
        if context is not None:
            self.context_system = context.system.copy()

    def parse(self, text, proof=None, context=None, line_number_offset=0):
        # Parse the text into a proof

        lines = text.split("\n")

        if proof is None:
            # Create a new proof instance
            proof = Proof()

        if context is None:
            # Create a new context instance
            context = Context()

            # Provide the default variables and system variables
            context.variables = self.context_variables
            context.system = self.context_system

        i = 0
        while i < len(lines):
            line = lines[i]
            line_number = line_number_offset + i + 1

            # Create a proof line for this line
            proof_line = proof.add_proof_line(line)

            # Clear the context history
            context.clear_history()

            # Check the line is of a given line type
            found = False
            for line_type in self.line_types:

                result = line_type.parse_line(line, context)

                if result is None:
                    continue

                # Otherwise meets this line type
                found = True

                # Record the line_type of this line
                proof_line.line_type = line_type
                proof_line.match = result

                if line_type.behaviour == "indent":
                    # Parse the block with a copied context

                    new_context = context.get_copy()

                    # Check for data to add to context
                    key_path = line_type.add_context_key_path
                    value_path = line_type.add_context_value_path

                    if key_path is not None:

                        # Get the keys
                        keys = result.get_by_path(key_path, context)

                        if type(keys) is not list:
                            # Make a singleton list
                            keys = [keys]

                        for key in keys:
                            key_string = key.string

                            # Get the value using the value path - relative to the key
                            value = key.get_by_path(value_path, context).get_value(context)

                            # Add to context
                            new_context.string_variables[key_string] = value

                    # Find the next line with this indent
                    j = line_number + 1
                    while j < len(lines):
                        block_line = lines[j]

                        if len(block_line) - len(block_line.lstrip()) <= proof_line.indent and \
                                len(block_line.lstrip()) > 0:
                            # This is the out-denting line
                            break

                        j += 1

                    # Compile the block
                    block = "\n".join(lines[i + 1:j])

                    self.parse(block, proof, new_context, line_number_offset=i + 1)

                    # Continue from after the block
                    i = j - 1
                    break

                elif line_type.behaviour == "logical":
                    # Logical lines for parsing

                    subs = result.get_sub_matches()

                    if "ref" in subs:
                        # Use the given reference and formula

                        ref = subs["ref"].string
                        formula = subs["f"]

                        proof_line.formula = formula

                        # Split the ref into parts
                        ref_parts = ref.split(", ")
                        key = ref_parts[0]

                        if key in self.axiom_dict:

                            # Get the axiom pattern
                            axiom = self.axiom_dict[key]

                            # Check the formula is an instance of this axiom
                            if axiom.match(formula.string, context) is None:
                                # Doesn't fit this axiom - step is invalid

                                proof_line.invalid_message = "Line " + str(line_number) + ": " + formula.string + \
                                                             " is not an instance of " + key + "."

                            else:
                                # Otherwise, axiom matches
                                proof_line.valid = True
                                proof_line.axiom = axiom

                        elif key in self.inference_rule_dict:
                            # It's an inference rule

                            inference_rule = self.inference_rule_dict[key]

                            # Get the antecedent lines
                            antecedents = []
                            for ant_line_no in ref_parts[1:]:
                                ant_line_no = int(ant_line_no)
                                antecedents.append(proof.get_proof_line(ant_line_no))

                            if inference_rule.check(antecedents=antecedents, deduction=proof_line, context=context):
                                # It's a valid step

                                proof_line.valid = True
                                proof_line.antecedents = antecedents
                                proof_line.inference_rule = inference_rule

                            else:
                                # Not a valid line
                                antecedent_lines = []
                                for ant in antecedents:
                                    if ant is None:
                                        proof_line.invalid_message = "Invalid antecedents"
                                        continue

                                    antecedent_lines = ant.text.lstrip()

                                proof_line.invalid_message = key + " does not apply with antecedents: " + \
                                                             ",".join(antecedent_lines)

                        else:
                            raise Exception("Did not recognise logical key '" + key + "' on line " + str(line_number))

                    else:
                        # Must have a formula
                        formula = subs["formula"]

                        valid = False

                        # Try to work out the deduction. First try the axioms
                        for axiom in self.axioms:
                            if axiom.match(formula.string, context) is not None:
                                # It's a match
                                proof_line.valid = True
                                proof_line.axiom = axiom
                                valid = True
                                break

                        if valid:
                            # No need to carry on
                            break

                        # No axioms work, need to try inference rules

                elif line_type.behaviour == "none":
                    # Don't need to do anything :)
                    pass

                # No need to check other line types
                break

            if not found:
                # The line doesn't match any of the line types
                raise Exception("Could not parse line " + str(line_number) + ": " + line)

            i += 1

        if line_number_offset == 0:
            # Check if the proof is valid
            valid_proof = True
            for line in proof.proof_lines:
                if line.line_type.behaviour == "logical" and not line.valid:
                    valid_proof = False
                    break

            proof.valid = valid_proof

        return proof

    def __str__(self):
        return self.name


class LineType(object):
    # Class for types of lines in formal proofs

    def __init__(self, name, pattern, behaviour, add_context_key_path=None, add_context_value_path=None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match (Pattern instance)
        self.pattern = pattern

        # The behaviour of these lines
        self.behaviour = behaviour
        assert self.behaviour in ("none", "import", "logical", "indent")

        # The data paths to add to context (if any)
        self.add_context_key_path = add_context_key_path
        self.add_context_value_path = add_context_value_path

    def parse_line(self, line, context):
        # Check if the given line string is of this type
        return self.pattern.match(line, context)

    def __str__(self):
        return self.name


class InferenceRule(object):
    # Inference rules for deduction

    def __init__(self, name, label, antecedents, deduction, condition=None, indent=0):

        # The inference rule name
        self.name = name

        # The inference rule label
        self.label = label

        # List of antecedent patterns
        self.antecedents = antecedents

        # Deduction pattern
        self.deduction = deduction

        # Condition for the rule to apply
        self.condition = condition

        # Deduction indentation relative to antecedents
        self.indent = indent

    def check(self, antecedents, deduction, context):
        # Check to see if the proposed proof lines are valid under this inference rule

        if deduction is None:
            # Deduction doesn't point to a valid proof line
            return False

        # Deduction must be after the antecedents
        for ant in antecedents:
            if ant is None:
                # antecedent isn't a proof line
                return False

            if deduction.index() < ant.index():
                return False

        # First check if the deductions matches
        deduction.inference_match = self.deduction.match(deduction.formula.string, context)

        if deduction.inference_match is None:
            # No match
            return False

        # Check if the antecedents match
        for pattern, ant in zip(self.antecedents, antecedents):

            # Set the inference match - can be used in the Condition
            ant.inference_match = pattern.match(ant.formula.string, context)

            if ant.inference_match is None:
                # No match
                return False

        # Check the rule condition
        if self.condition is not None:

            # Make a condition context with antecedents and deduction
            condition_context = {
                "antecedents": antecedents,
                "deduction": deduction
            }

            if not self.condition.check(match=None, context=context, condition_context=condition_context):
                # Doesn't meet the condition
                return False

        # Otherwise ok
        deduction.antecedents = antecedents
        deduction.inference_rule = self
        deduction.valid = True

        # Add the deduction line as dependent to each of the antecedents
        for ant in antecedents:
            ant.dependent_lines.append(deduction)

        return True


class Proof(object):
    # A proof in a formal system

    def __init__(self, result=None):

        # The proof result
        self.result = result

        # Whether the proof is valid
        self.valid = None

        # The proof lines leading to the result
        self.proof_lines = []

    def get_proof_line(self, line_number):
        # Get a proof line by line number
        if not 0 <= line_number < len(self.proof_lines):
            return None

        return self.proof_lines[line_number - 1]

    def add_proof_line(self, text):
        proof_line = ProofLine(self, text)
        self.proof_lines.append(proof_line)
        return proof_line

    def __str__(self):
        return self.name


class ProofLine(object):
    # A line in a proof

    def __init__(self, proof, text):

        # The proof this line belongs to
        self.proof = proof

        # The text string on this line
        self.text = text

        # The formula match (if any) on this line
        self.formula = None

        # The LineType used for this line
        self.line_type = None

        # The match with the line type pattern
        self.match = None

        # The indentation of this line
        self.indent = len(self.text) - len(self.text.lstrip())

        # The axiom this line uses (if any)
        self.axiom = None

        # The rule that this line uses
        self.inference_rule = None

        # The antecedents used in the deduction
        self.antecedents = None

        # Whether this step in the proof is valid
        self.valid = False

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = []

        # Invalid message
        self.invalid_message = None

        # Temporary match for use in inference rules
        self.inference_match = None

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def indent_line(self):
        # Get the indent line above this one - returns None if this line is not indented

        if self.indent == 0:
            return None

        index = self.index()
        line = self

        while line.indent >= self.indent or line.line_type.behaviour == "none":
            index -= 1
            line = self.proof.proof_lines[index]

        # Now line.indent < self.indent
        return line

    def indent_lines(self):
        # Get a set of all indent lines above this one

        indent = self.indent_line()
        if indent is None:
            return set()

        result = indent.indent_lines()
        result.add(indent)

        return result

    def is_root(self):
        # Whether the line has no indent line
        return self.indent_line() is None

    def get_by_path(self, s, context):
        # Get an attribute of the proofline given a path s

        if s[:13] == "indent_line()":
            # Get the indent line

            if len(s) == 13:
                return self.indent_line()

            assert s[13] == "."

            return self.indent_line().get_by_path(s[14:], context)

        if s[:14] == "indent_lines()":

            if len(s) == 14:
                return set(line.match for line in self.indent_lines()), set(), True

            assert s[14] == "."
            remainder = s[15:]

            instances = set()
            negatives = set()
            complete = True

            for m in set(line.match for line in self.indent_lines()):
                result = m.get_by_path(remainder, context)

                if type(result) is tuple:
                    # This is a tuple result with negatives and completeness

                    sub_instances, sub_negatives, sub_complete = result

                    instances = instances.union(sub_instances)
                    negatives = negatives.union(sub_negatives)
                    complete = complete and sub_complete

                    continue

                # Otherwise, just an instances
                instances.add(result)

            return instances, negatives, complete

        if s[:9] == "formula()":
            # Get the formula match

            if len(s) == 9:
                return self.formula

            assert s[9] == "."

            return self.formula.get_by_path(s[10:], context)

        if s[:7] == "match()":
            # Get the inference match

            if len(s) == 7:
                return self.match

            assert s[7] == "."

            return self.match.get_by_path(s[8:], context)

        if s[:11] == "inf_match()":
            # Get the inference match

            if len(s) == 11:
                return self.inference_match

            assert s[11] == "."

            return self.inference_match.get_by_path(s[12:], context)

        if s == "is_root()":
            return self.is_root()

    def __str__(self):
        return self.text
