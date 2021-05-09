from .matching import *
from copy import copy


class FormalSystem(object):
    # A formal system

    def __init__(self, name, axioms=None, line_types=None, inference_rules=None, proof_context=None):

        # The name of the system
        self.name = name

        # System formula pattern
        self.formula = None

        # A list of patterns
        self.axioms = axioms
        if self.axioms is None:
            self.axioms = []

        # A list of line types
        self.line_types = line_types
        if self.line_types is None:
            self.line_types = []

        # A list of valid inference rules for the system
        self.inference_rules = inference_rules
        if self.inference_rules is None:
            self.inference_rules = []

        # Default proof context
        self.proof_context = proof_context if proof_context is not None else dict()

    def get_references(self, text):
        # Get references to external proofs from the given code

        # Create a default context
        context = copy(self.proof_context)

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

                subs = result.get_sub_matches()

                # Get the path
                path = subs["path"].string

                # The proof reference is the first part
                parts = path.split(".")

                slug = parts[0].replace("_", "-")

                references.add(slug)

                break

        return references

    def parse(self, text, proof=None, reference_proofs=None, proof_context=None, line_number_offset=0):
        # Parse the text into a proof

        lines = text.split("\n")

        if proof is None:
            # Create a new proof instance
            proof = Proof(formal_system=self)
            proof.valid = True

            proof.reference_proofs = reference_proofs

        if proof_context is None:
            # Create a new proof context instance
            proof_context = copy(self.proof_context)

        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            line_number = line_number_offset + i + 1

            # Create a proof line for this line
            proof_line = proof.add_proof_line(line)

            if proof_line.empty:
                # Ignore blank lines
                i += 1
                continue

            # Check the line is of a given line type
            found = False
            for line_type in self.line_types:

                line = line.lstrip()
                result = line_type.parse_line(line, proof_context)

                if result is None:
                    continue

                # Otherwise meets this line type
                found = True

                # Record the line_type of this line
                proof_line.line_type = line_type
                proof_line.match = result

                # Check if the line type has a 'display' value
                try:
                    proof_line.display = result.get_by_path("display", proof_context)

                except Exception as e:
                    # No valid display path
                    pass

                if not line_type.behaviour == "indent":
                    # Check for data to add to context
                    proof_line.edit_context(proof_context)

                if line_type.behaviour == "indent":
                    # Parse the block with a copied context

                    new_context = copy(proof_context)

                    # Edit context
                    proof_line.edit_context(new_context)

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

                    self.parse(text=block, proof=proof, proof_context=new_context, line_number_offset=i + 1)

                    # Continue from after the block
                    i = j - 1
                    break

                elif line_type.behaviour == "logical":
                    # Logical lines for parsing

                    # Try to get the formula, reference, and label
                    reference_string = None
                    label = None

                    try:
                        formula = result.get_by_path("formula", proof_context)

                        # Add formula to the proof line
                        proof_line.formula = formula

                    except Exception as e:
                        # No formula
                        proof_line.valid = False
                        proof_line.invalid_message = "No formula defined for logical line."
                        continue

                    try:
                        reference_string = result.get_by_path("reference", proof_context)
                    except Exception as e:
                        pass

                    try:
                        label = result.get_by_path("label", proof_context)
                    except Exception as e:
                        pass

                    # Add a label if it exists
                    if label:
                        proof_line.label = label

                        # Add this line to proof context
                        proof.context[label] = proof_line

                    if reference_string:
                        # Use the given reference and formula

                        # Get the reference
                        proof_line.reference_string = reference_string
                        reference = proof.get_reference(reference_string)

                        if type(reference) is not dict:
                            # Reference must be a dictionary
                            proof_line.valid = False
                            proof_line.invalid_message = "Invalid reference '" + reference_string + "'."
                            continue

                        if "axiom" in reference:

                            # Get the axiom pattern
                            axiom = reference["axiom"]
                            key = reference["key"]

                            # Check the formula is an instance of this axiom
                            if axiom.match(formula.string, proof_context) is None:
                                # Doesn't fit this axiom - step is invalid
                                proof_line.valid = False
                                proof_line.invalid_message = "Not an instance of " + key + "."

                            else:
                                # Otherwise, axiom matches
                                proof_line.axiom = axiom

                        elif "inference_rule" in reference:
                            # It's an inference rule

                            inference_rule = reference["inference_rule"]

                            # Get the antecedent lines
                            antecedents = reference["antecedents"]

                            key = reference["key"]

                            # Check the number of antecedents
                            if not len(antecedents) == len(inference_rule.antecedents):
                                # Wrong number of antecedents
                                proof_line.valid = False
                                proof_line.invalid_message = key + " requires " + \
                                    str(len(inference_rule.antecedents)) + " antecedent(s)."
                                continue

                            if inference_rule.check(antecedents=antecedents, deduction=proof_line, proof_context=proof_context):
                                # It's a valid step

                                proof_line.antecedents = antecedents
                                proof_line.inference_rule = inference_rule

                            else:
                                # Not a valid line
                                proof_line.valid = False
                                proof_line.invalid_message = key + " does not apply."

                        else:
                            proof_line.invalid_message = "Invalid reference '" + reference_string + "'."
                            proof_line.valid = False

                    else:
                        valid = False

                        # Try to work out the deduction. First try the axioms
                        for axiom in self.axioms:
                            if axiom.match(formula.string, proof_context) is not None:
                                # It's a match
                                proof_line.valid = True
                                proof_line.axiom = axiom
                                valid = True
                                break

                        if valid:
                            # No need to carry on
                            break

                        # No axioms work, need to try inference rules

                elif line_type.behaviour == "definition":
                    # Introduce a new definition to context

                    subs = result.sub_matches
                    defn = self.formula.add_definition(subs["higher"].string, subs["lower"].string, proof_context)

                    # Add variables to the definition
                    for string_var, sub_pattern in proof_context["string_variables"].items():
                        defn.add_variable(string_var, sub_pattern)

                elif line_type.behaviour == "import":
                    # Import a file or result

                    subs = result.get_sub_matches()

                    # Get the path and reference
                    path = subs["path"].string
                    reference = subs["reference"].string

                    # Get the line from the import path
                    parts = path.split(".")

                    if len(parts) > 2:
                        # Too many parts
                        proof_line.valid = False
                        proof_line.invalid_message = "Could not parse path"
                        continue

                    slug = parts[0].replace("_", "-")

                    if slug not in proof.reference_proofs or proof.reference_proofs[slug] is None:
                        # Don't recognise slug
                        proof_line.valid = False
                        proof_line.invalid_message = "Could not find file."
                        continue

                    # Otherwise, get the referenced proof
                    ref_proof = reference_proofs[slug]

                    if len(parts) == 1:
                        # No other parts - reference to the entire proof file
                        proof.context[reference] = ref_proof
                        continue

                    # Otherwise, two parts
                    ref_line = ref_proof.get_reference(parts[1])

                    # Add to proof context
                    proof.context[reference] = ref_line

                elif line_type.behaviour == "none":
                    # Don't need to do anything :)
                    pass

                # No need to check other line types
                break

            if not found:
                # The line doesn't match any of the line types. Invalid proof
                proof_line.invalid_message = "Could not parse line."
                proof_line.valid = False

            i += 1

        if line_number_offset == 0:
            # Check if the proof is valid

            proof.valid = True

            for line in proof.proof_lines:
                if line.line_type is None:
                    proof.valid = False
                    continue

                if line.line_type.behaviour == "logical" and not line.valid:
                    proof.valid = False

        return proof

    def __str__(self):
        return self.name


class LineType(object):
    # Class for types of lines in formal proofs

    def __init__(self, name, pattern=None, behaviour="none", add_context=None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match (Pattern instance)
        self.pattern = pattern

        # The behaviour of these lines
        self.behaviour = behaviour
        assert self.behaviour in ("none", "import", "logical", "indent", "definition")

        # The data paths (and their values) to add to context, if any
        self.add_context = add_context if add_context is not None else dict()

        # Attributes
        self.attributes = dict()

    def parse_line(self, line, proof_context):
        # Check if the given line string is of this type
        return self.pattern.match(line, proof_context)

    def add_attribute(self, name, value):
        # Add an attribute to this line type

        if type(value) is list:
            self.attributes[name] = value

        else:
            self.attributes[name] = str(value)

    def get_attribute(self, name):
        # Get the given attribute

        if name in self.attributes:
            return self.attributes[name]

        # Otherwise, error
        raise Exception(self.name + " does not have attribute: " + name)

    def __str__(self):
        return self.name


class InferenceRule(object):
    # Inference rules for deduction

    def __init__(self, name, label=None, antecedents=None, deduction=None, condition=None, indent=0):

        # The inference rule name
        self.name = name

        # The inference rule label
        self.label = label if label is not None else ""

        # List of antecedent patterns
        self.antecedents = antecedents if antecedents is not None else list()

        # Deduction pattern
        self.deduction = deduction

        # Condition for the rule to apply
        self.condition = condition

        # Deduction indentation relative to antecedents
        self.indent = indent

    def check(self, antecedents, deduction, proof_context):
        # Check to see if the proposed proof lines are valid under this inference rule

        # Check the number of antecedents matches
        if not len(antecedents) == len(self.antecedents):
            return False

        if type(deduction) is not ProofLine:
            # Deduction doesn't point to a valid proof line
            return False

        # Deduction must be after the antecedents
        for ant in antecedents:
            if type(ant) is not ProofLine:
                # antecedent isn't a proof line
                return False

            # Deduction in the same proof must come after the antecedents
            if deduction.proof == ant.proof and deduction.index() < ant.index():
                return False

        # First check if the deduction matches
        deduction.inference_match = self.deduction.match(deduction.formula.string, proof_context)

        if deduction.inference_match is None:
            # No match
            return False

        # Check if the antecedents match
        for pattern, ant in zip(self.antecedents, antecedents):
            if ant.formula is None:
                return False

            # Set the inference match - can be used in the Condition
            ant.inference_match = pattern.match(ant.formula.string, proof_context)

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

            if not self.condition.check(match=None, context=proof_context, condition_context=condition_context):
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

    def __init__(self, formal_system, reference_proofs=None, result=None):

        # The system in which this proof belongs
        self.formal_system = formal_system

        # The proof result
        self.result = result

        # Whether the proof is valid
        self.valid = None

        # The proof lines leading to the result
        self.proof_lines = []

        # A dictionary of references to other proofs
        self.reference_proofs = reference_proofs

        # A context for references and imports
        self.context = dict()

    def get_proof_line(self, line_number):
        # Get a proof line by line number
        if not 0 <= line_number < len(self.proof_lines):
            return None

        return self.proof_lines[line_number - 1]

    def add_proof_line(self, text):
        proof_line = ProofLine(self, text)
        self.proof_lines.append(proof_line)
        return proof_line

    def data(self):
        # Get data for this proof
        return {
            "valid": self.valid,
            "lines": [line.data() for line in self.proof_lines]
        }

    def get_reference(self, ref):
        # Get the referenced line from a ref string

        # Check if it's reference to another line
        if ref in self.context:
            return self.context[ref]

        if "." in ref:
            proof_ref, key = ref.split(".")
            proof_ref = self.get_reference(proof_ref)

            if type(proof_ref) is Proof:
                return proof_ref.get_reference(key)

        # Split the ref into parts
        ref_parts = ref.split(", ")
        key = ref_parts[0]

        # Check the axioms
        for ax in self.formal_system.axioms:
            if key == ax.label:
                # It's an axiom
                return {
                    "axiom": self.formal_system.axiom_dict[key],
                    "key": key
                }

        for ir in self.formal_system.inference_rules:
            if key == ir.label:
                # It's an inference rule

                # Get the antecedent lines
                antecedents = []
                for ant_ref in ref_parts[1:]:
                    antecedents.append(self.get_reference(ant_ref))

                return {
                    "inference_rule": ir,
                    "antecedents": antecedents,
                    "key": key
                }

        # Check if it's a line number
        try:
            return self.get_proof_line(int(ref))
        except ValueError:
            pass

        # Nothing works
        return None


class ProofLine(object):
    # A line in a proof

    def __init__(self, proof, text, reference_string=None, label=None):

        # The proof this line belongs to
        self.proof = proof

        # The text string on this line
        self.text = text

        # The text to display on this line. By default equal to the actual text.
        self.display = text

        # The reference string for this line (if any)
        self.reference_string = reference_string

        # The label for this line (if any)
        self.label = label

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
        self.valid = True

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = []

        # Invalid message
        self.invalid_message = None

        # Temporary match for use in inference rules
        self.inference_match = None

        # Line may be empty
        self.empty = len(self.text) == 0

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def indent_line(self):
        # Get the indent line above this one - returns None if this line is not indented

        if self.indent == 0:
            return None

        index = self.index()
        line = self

        while line.indent >= self.indent or (line.line_type is not None and line.line_type.behaviour == "none"):
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
        # Get an attribute of the proof line given a path s

        if type(s) is list:
            # Get each component
            return [self.get_by_path(item, context) for item in s]

        if type(s) is not str:
            s = str(s)

        if s == "match":
            # Get the match
            return self.match

        # if s[:11] == "inf_match()":
        #     # Get the inference match
        #
        #     if len(s) == 11:
        #         return self.inference_match
        #
        #     assert s[11] == "."
        #
        #     return self.inference_match.get_by_path(s[12:], context)

        if s == "is_root()":
            return self.is_root()

        if s == "pattern":
            return self.line_type.pattern

        if s in self.line_type.attributes:
            return self.get_by_path(self.line_type.get_attribute(s), context)

        if "." in s:
            # Dotted path
            index = s.find(".")
            initial = s[:index]
            remainder = s[index + 1:]
            return self.get_by_path(initial, context).get_by_path(remainder, context)

        raise Exception("Could not find " + s + " in '" + self.text + "'.")

    def edit_context(self, proof_context):
        # Edit the proof context according to the rule on this line type

        if self.line_type.add_context is None:
            # Nothing to change
            return proof_context

        # Otherwise, changes to make
        for key, value in self.line_type.add_context.items():

            if key not in proof_context:
                raise Exception("Can't find '" + key + "' in proof context.")

            current_value = proof_context[key]

            if type(current_value) is dict:
                # Dictionary type context entry

                for sub_key_string, sub_value_string in value.items():

                    # Try get by path
                    sub_key = self.get_by_path(sub_key_string, proof_context)

                    # Get the value
                    sub_value = self.get_by_path(sub_value_string, proof_context)

                    if type(sub_key) is MatchSet:
                        # Need to add each match
                        for m in sub_key.instances:
                            proof_context[key][m.string] = sub_value

                    elif type(sub_key) is Match:
                        # Just one match
                        proof_context[key][sub_key.string] = sub_value

                    else:
                        # Add directly
                        proof_context[key][sub_key] = sub_value

            elif type(current_value) is MatchSet:
                # Set type context entry

                for edit_type, sub_value_string in value.items():

                    # Get the value
                    sub_value = self.get_by_path(sub_value_string, proof_context)

                    if edit_type == "union":
                        # Union the set with the value

                        if type(sub_value) is Match:
                            current_value = current_value.add(sub_value, proof_context)

                        elif type(sub_value) is MatchSet:
                            current_value = current_value.union(sub_value, proof_context)

                        else:
                            # Has to be a match or a match set
                            raise Exception("Cannot union a set with object of type '" + str(type(sub_value)) + "'.")

                    else:
                        raise Exception("Cannot edit a set with operator '" + edit_type + "'.")

        return proof_context

    def data(self):
        # Get data for this proof line
        return {
            "valid": self.valid,
            "behaviour": self.line_type.behaviour if self.line_type is not None else None,
            "name": self.line_type.name if self.line_type is not None else None,
            "invalid_message": self.invalid_message,
            "reference": self.reference_string,
            "label": self.label,
            "display": self.display,
            "indent": self.indent
        }

    def __str__(self):
        return self.text
