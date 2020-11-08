from edifyce.website.context import Context


class FormalSystem(object):
    # A formal system

    def __init__(self, name, axioms=None, line_types=None, inference_rules=None):

        # The name of the system
        self.name = name

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

    def parse(self, text, proof=None, context=None, line_number_offset=0):
        # Parse the text into a proof

        lines = text.split("\n")

        if proof is None:
            # Create a new proof instance
            proof = Proof(name="test")

        if context is None:
            # Create a new context instance
            context = Context()

        i = 0
        while i < len(lines):
            line = lines[i]
            line_number = line_number_offset + i + 1

            # Create a proof line for this line
            proof_line = proof.add_proof_line(line)

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

                if line_type.behaviour == "indent":
                    # Parse the block with a copied context

                    new_context = context.get_copy()

                    # Check for data to add to context
                    key_path = line_type.add_context_key_path
                    value_path = line_type.add_context_value_path

                    if key_path is not None:

                        # Get the keys
                        keys = result.get_by_path(key_path, context)

                        for key in keys:
                            key_string = key.get_value(context)

                            # Get the value using the relative value path
                            value = key.get_by_path(value_path, context).get_value(context)

                            # Add to context
                            new_context.string_variables[key_string] = value

                    # Find the next line with this indent
                    j = line_number + 1
                    while j < len(lines):
                        block_line = lines[j]

                        if len(block_line) - len(block_line.lstrip()) <= proof_line.indent and \
                                len(block_line.lstrip()) > 0:
                            # This is the outdenting line
                            break

                        j += 1

                    # Compile the block
                    block = "\n".join(lines[i + 1:j])

                    self.parse(block, proof, new_context, line_number_offset=i + 1)

                    # Continue from after the block
                    i = j - 1
                    break

                elif line_type.behaviour == "logical":
                    # Logical lines must include a ref and a formula

                    subs = result.get_sub_matches()

                    ref = subs["ref"].string
                    formula = subs["formula"]

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
                                antecedent_lines = ant.text.lstrip()

                            proof_line.invalid_message = key + " does not apply with antecedents: " + \
                                                         ",".join(antecedent_lines)

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
                for line in proof.proof_lines:
                    if line.line_type.behaviour == "logical":
                        print(line.text, line.valid)

    def __str__(self):
        return self.name


class LineType(object):
    # Class for types of lines in formal proofs

    def __init__(self, name, pattern, behaviour, add_context_key_path=None, add_context_value_path=None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match
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

    def __init__(self, name, label, antecedents, deduction, indent=0):

        # The inference rule name
        self.name = name

        # The inference rule label
        self.label = label

        # List of antecedent dictionaries - each of the form
        # {
        #     "pattern": some_pattern_instance,
        #     "indent": (optional) some_indent_pattern
        # }
        self.antecedents = antecedents

        # Deduction pattern
        self.deduction = deduction

        # Deduction indentation relative to antecedents
        self.indent = indent

    def check(self, antecedents, deduction, context):
        # Check to see if the proposed proof lines are valid under this inference rule

        # First check if the deductions matches
        deduction_match = self.deduction.match(deduction.formula.string, context)

        if deduction_match is None:
            # No match
            return False

        # Check if the antecedents match
        ant_matches = [deduction_match]
        for ant_patterns, ant in zip(self.antecedents, antecedents):

            if type(ant_patterns) is dict:
                pattern = ant_patterns["pattern"]
            else:
                pattern = ant_patterns

            ant_match = pattern.match(ant.formula.string, context)

            if ant_match is None:
                # No match
                return False

            # Add the match to ant_matches
            ant_matches.append(ant_match)

            # Check the indent if it's present
            if type(ant_patterns) is not dict or "indent" not in ant_patterns:
                continue

            indent_line = ant.indent_line()
            if indent_line is None:
                # There should be an indent line
                return False

            indent_pattern = ant_patterns["indent"]
            indent_match = indent_pattern.match(indent_line.text, context)

            if indent_match is None:
                # No match
                return False

            # Add the match to ant_matches
            ant_matches.append(indent_match)

        # Check the ant_matches have consistent variables
        variables = dict()
        for match in ant_matches:
            subs = match.get_sub_matches()

            for key, submatch in subs.items():
                if key not in variables:
                    variables[key] = submatch
                    continue

                # Otherwise, check consistent
                if not submatch.equivalent(variables[key], context):
                    # Not consistent
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

    def __init__(self, name, result=None):
        # A name for this proof
        self.name = name

        # The proof result
        self.result = result

        # The proof lines leading to the result
        self.proof_lines = []

    def get_proof_line(self, line_number):
        # Get a proof line by line number
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

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def indent_line(self):
        # Get the indent line above this one - returns None if this line is not indented

        if self.indent == 0:
            return None

        index = self.index()
        line = self

        while line.indent >= self.indent:
            index -= 1
            line = self.proof.proof_lines[index]

        # Now line.indent < self.indent
        return line

    def __str__(self):
        return self.text
