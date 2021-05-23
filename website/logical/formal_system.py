from .matching import *
from copy import copy
import itertools


class FormalSystem(object):
    # A formal system

    def __init__(self, name, axioms=None, line_types=None, inference_rules=None, proof_context=None, pre_format=None):

        # The name of the system
        self.name = name

        # System formula pattern
        self.formula = None

        # A list of patterns
        self.axioms = axioms if axioms is not None else []

        # A list of line types
        self.line_types = line_types if line_types is not None else []

        # A list of valid inference rules for the system
        self.inference_rules = inference_rules if inference_rules is not None else []

        # Default proof context
        self.proof_context = proof_context if proof_context is not None else dict()

        if "axioms" not in self.proof_context:
            # Keep axioms in context also
            self.proof_context["axioms"] = dict()

        # Default formatting for all strings in the system.
        self.formatting = pre_format if pre_format is not None else dict()

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

                # Get the path
                try:
                    path = result.get_by_path("path()", context)

                except Exception as e:
                    # No valid path here
                    continue

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

        i = -1
        while i + 1 < len(lines):

            # Increment at the start so we can use 'continue' without concern
            i += 1

            line = lines[i].rstrip()
            line_number = line_number_offset + i + 1

            # Create a proof line for this line
            proof_line = proof.add_proof_line(line, proof_context)

            if proof_line.empty:
                # Ignore blank lines
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

                # Check for main line type attributes
                # Try to get the formula, reference, label, display
                try:
                    # Add formula to the proof line
                    proof_line.formula = result.get_by_path("formula()", proof_context)

                    # It has to be a match
                    if type(proof_line.formula) is not Match:
                        proof_line.formula = None

                except Exception as e:
                    pass

                try:
                    reference_string = result.get_by_path("reference()", proof_context)

                    if type(reference_string) is str:
                        proof_line.reference_string = reference_string

                except Exception as e:
                    pass

                try:
                    label = result.get_by_path("label()", proof_context)
                    proof_line.label = label

                except Exception as e:
                    pass

                # Check if the line type has a 'display' value
                try:
                    proof_line.display = result.get_by_path("display()", proof_context)
                except Exception as e:
                    # No valid display path
                    pass

                if not line_type.behaviour == "indent":
                    # Check for data to add to context
                    try:
                        proof_line.edit_context(proof_context)

                    except Exception as e:
                        # Error in editing context
                        proof_line.valid = False
                        proof_line.invalid_message = str(e)

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

                    if proof_line.formula is None:
                        # No formula
                        proof_line.valid = False
                        proof_line.invalid_message = "No formula defined for logical line."
                        continue

                    if proof_line.label is not None:
                        # Add label to reference context
                        proof.reference_context[proof_line.label] = proof_line

                    if proof_line.reference_string is None:
                        valid = False

                        # Try to work out the deduction. First try the axioms
                        for axiom in self.axioms:
                            if axiom.match(proof_line.formula.formatted_string(), proof_context) is not None:
                                # It's a match
                                proof_line.valid = True
                                proof_line.axiom = axiom
                                valid = True
                                break

                        if valid:
                            # No need to carry on
                            break

                        # No axioms work, need to try inference rules
                        continue

                    # Use the given reference and formula

                    # Get the reference
                    reference = proof.get_reference(proof_line.reference_string)

                    if type(reference) is ProofLine and reference.is_axiom:
                        # This is an axiom

                        # Get the axiom pattern
                        axiom = reference.formula.create_pattern(string_variables=proof_context["string_variables"])
                        key = reference.label

                        # Update the StringPattern name
                        axiom.name = key

                        # Check the formula is an instance of this axiom
                        if axiom.match(proof_line.formula.formatted_string(), proof_context) is None:
                            # Doesn't fit this axiom - step is invalid
                            proof_line.valid = False
                            proof_line.invalid_message = "Not an instance of " + key + "."

                        else:
                            # Otherwise, axiom matches
                            proof_line.axiom = axiom

                    elif type(reference) is dict and "inference_rule" in reference:
                        # It's an inference rule

                        inference_rule = reference["inference_rule"]
                        key = reference["key"]

                        # Get the antecedent lines
                        antecedents = reference["antecedents"]

                        if len(antecedents) == 0 and len(inference_rule.antecedents) < 5:
                            # Antecedents not provided. Try to justify:
                            proof.justify(
                                deduction=proof_line,
                                proof_context=proof_context,
                                inference_rule=inference_rule
                            )

                        else:
                            # Check the number of antecedents given
                            if not len(antecedents) == len(inference_rule.antecedents):
                                # Wrong number of antecedents
                                proof_line.valid = False
                                proof_line.invalid_message = key + " requires " + \
                                    str(len(inference_rule.antecedents)) + " antecedent(s)."
                                continue

                            # Try any permutation of the given antecedents
                            permutation_found = False
                            for permutation in list(itertools.permutations(antecedents)):
                                if inference_rule.check(
                                        antecedents=permutation,
                                        deduction=proof_line,
                                        proof_context=proof_context
                                ):
                                    # It's a valid permutation
                                    proof_line.antecedents = permutation
                                    proof_line.inference_rule = inference_rule

                                    permutation_found = True
                                    break

                            if not permutation_found:
                                # Not a valid line
                                proof_line.valid = False
                                proof_line.invalid_message = key + " does not apply."

                    else:
                        proof_line.invalid_message = "Invalid reference '" + reference_string + "'."
                        proof_line.valid = False

                elif line_type.behaviour == "axiom":
                    # Introduce an axiom to the system

                    # Add the proof line to the proof's reference context
                    proof.reference_context[proof_line.label] = proof_line
                    proof_line.is_axiom = True

                elif line_type.behaviour == "definition":
                    # Introduce a new definition to context

                    subs = result.sub_matches
                    defn = self.formula.add_definition(subs["higher"].string, subs["lower"].string, proof_context)

                    # Add variables to the definition
                    for string_var, sub_pattern in proof_context["string_variables"].items():
                        defn.add_variable(string_var, sub_pattern)

                elif line_type.behaviour == "import":
                    # Import a file or result

                    # Get the path and reference
                    try:
                        path = result.get_by_path("path()", proof_context)
                        label = result.get_by_path("label()", proof_context)

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
                            proof.reference_context[label] = ref_proof
                            continue

                        # Otherwise, two parts
                        ref_line = ref_proof.get_reference(parts[1])

                        # Add to proof context
                        proof.reference_context[label] = ref_line

                    except Exception as e:
                        # No valid path or label
                        proof_line.valid = False
                        proof_line.invalid_message = "Could not get path or label from import line: " + str(e)

                elif line_type.behaviour == "none":
                    # Don't need to do anything :)
                    pass

                # No need to check other line types
                break

            if not found:
                # The line doesn't match any of the line types. Invalid proof
                proof_line.invalid_message = "Could not parse line."
                proof_line.valid = False

        if line_number_offset == 0:
            # Check if the proof is valid

            proof.valid = True

            for line in proof.proof_lines:
                if line.line_type is None and not line.empty:
                    proof.valid = False
                    continue

                if line.line_type is not None and line.line_type.behaviour == "logical" and not line.valid:
                    proof.valid = False
                    continue

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
        assert self.behaviour in ("none", "import", "logical", "axiom", "indent", "definition")

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
        self.name = name.replace("_", " ")

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

    def get_by_path(self, path, proof_context):
        # Get information from the given path

        initial, remainder = parse_path(path)

        if remainder:
            # Chain the parts
            return self.get_by_path(initial, proof_context).get_by_path(remainder, proof_context)

        # Otherwise, only one part

        if path[:12] == "antecedents[" and path[-1] == "]":
            # Only if this is the whole path

            try:
                index = int(path[12:-1])

                if "antecedents" in proof_context:
                    return proof_context["antecedents"][index]

                else:
                    return self.antecedents[index]

            except Exception as e:
                raise Exception("Could not parse path: '" + path + "'.")

        if path == "deduction":
            # Get the deduction
            if "deduction" in proof_context:
                return proof_context["deduction"]

            else:
                return self.deduction

        if path in proof_context["variables"]:
            return proof_context["variables"][path]

        raise Exception("Could not parse path: '" + path + "'.")

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

        # Create an inference instance
        inference = Inference(self, antecedents, deduction)

        # First check if the deduction matches
        inference.deduction_inference_match = self.deduction.match(deduction.formula.formatted_string(), proof_context)

        if inference.deduction_inference_match is None:
            # No match
            return False

        # Check if the antecedents match
        for pattern, ant in zip(self.antecedents, antecedents):
            if ant.formula is None:
                return False

            # Set the inference match - can be used in the Condition
            match = pattern.match(ant.formula.formatted_string(), proof_context)

            if match is None:
                # No match
                return False

            inference.antecedent_inference_matches.append(match)

        # Check variables are consistent
        if not inference.check_variables(proof_context):
            # Variables not consistent
            return False

        # Check the rule condition
        if self.condition is not None:
            # Make a condition context with antecedents and deduction
            condition_context = copy(proof_context)
            condition_context.update({
                "antecedents": antecedents,
                "deduction": deduction,
                "inference": inference
            })
            condition_context["variables"].update(inference.variables)

            if not self.check_condition(self.condition, condition_context):
                # Doesn't meet the condition
                return False

        # Otherwise ok
        deduction.antecedents = antecedents
        deduction.inference_rule = self
        deduction.inference = inference
        deduction.valid = True

        # Add the deduction line as dependent to each of the antecedents
        for ant in antecedents:
            ant.dependent_lines.add(deduction)

        return True

    def check_condition(self, c, context):
        # Check a condition c - returns true or false

        # Add the top-most match to context in a copy
        if "self" not in context["variables"]:
            context = copy(context)
            context["variables"]["self"] = self

        # Check the possible condition types
        if not c.type == "atomic":
            # Composite case
            return c.check_composite(self, context)

        # Otherwise, atomic condition

        if " == " in c.string:
            # Equals
            left, right = [self.get_by_path(arg, context) for arg in c.string.split(" == ")]

            if not type(left) == type(right):
                # Mismatched types
                return False

            if type(left) in (Match, MatchSet):
                return left.equivalent(right, context)

            else:
                return left == right

        else:
            # Get by path
            return self.get_by_path(c.string, context)


class Inference(object):
    # An application of an inference rule

    def __init__(self, inference_rule, antecedents, deduction):

        self.inference_rule = inference_rule

        # Antecedents should be a list of proof lines, deduction should be a proof line
        self.antecedents = antecedents
        self.deduction = deduction

        # Store inference matches here
        self.antecedent_inference_matches = []
        self.deduction_inference_match = None

        self.variables = None

    def check_variables(self, proof_context):
        # Check the variables for antecedent and deduction matches are consistent

        self.variables = copy(self.deduction_inference_match.sub_matches)
        for ant_match in self.antecedent_inference_matches:
            for name, sub_match in ant_match.sub_matches.items():
                if name in self.variables:
                    if not sub_match.equivalent(self.variables[name], proof_context):
                        # Same variable with different value
                        return False

                else:
                    # Add to variables
                    self.variables[name] = sub_match

        # All consistent
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
        self.reference_context = dict()

    def get_proof_line(self, line_number):
        # Get a proof line by line number
        if not 0 <= line_number < len(self.proof_lines):
            return None

        return self.proof_lines[line_number - 1]

    def add_proof_line(self, text, proof_context):
        proof_line = ProofLine(self, text, context=copy(proof_context))
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
        if ref in self.reference_context:
            return self.reference_context[ref]

        if "." in ref:
            proof_ref, key = ref.split(".")
            proof_ref = self.get_reference(proof_ref)

            if type(proof_ref) is Proof:
                return proof_ref.get_reference(key)

        # Split the ref into parts
        ref_parts = ref.split(", ")
        key = ref_parts[0]

        # Check the axioms
        # for ax in self.formal_system.axioms:
        #     if key == ax.label:
        #         # It's an axiom
        #         return {
        #             "axiom": self.formal_system.axiom_dict[key],
        #             "key": key
        #         }

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

    def justify(self, deduction, proof_context, inference_rule=None):
        # Artificially try to find a justification for the given reference. Optionally specify a inference rule.

        if inference_rule is not None:

            logical_lines = [
                line for line in self.proof_lines[:deduction.index()]
                if line.line_type is not None and line.line_type.behaviour == "logical"
            ][-len(inference_rule.antecedents):]

            if not len(logical_lines) == len(inference_rule.antecedents):
                # Not enough previous logical lines
                deduction.valid = False
                deduction.invalid_message = "Antecedent lines couldn't be inferred."
                return False

            for permutation in list(itertools.permutations(logical_lines)):

                if inference_rule.check(
                        antecedents=permutation,
                        deduction=deduction,
                        proof_context=proof_context
                ):
                    # Found the valid permutation
                    deduction.antecedents = permutation
                    deduction.inference_rule = inference_rule

                    return True

            # Otherwise, no justification found
            deduction.valid = False
            deduction.invalid_message = inference_rule.label + " does not apply."

            return False

        # Otherwise, no inference rule specified.
        return False


class ProofLine(object):
    # A line in a proof

    def __init__(self, proof, text, context, reference_string=None, label=None):

        # The proof this line belongs to
        self.proof = proof

        # The text string on this line
        self.text = text

        # The text to display on this line. By default equal to the actual text.
        self.display = text

        # A frozen context - useful to later refer to from inference rules
        self.context = context

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

        # This line may be an axiom
        self.is_axiom = False

        # The axiom this line uses (if any)
        self.axiom = None

        # The rule that this line uses
        self.inference_rule = None

        # The inference instance with this line as the deduction
        self.inference = None

        # The antecedents used in the deduction
        self.antecedents = None

        # Whether this step in the proof is valid
        self.valid = True

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = set()

        # Invalid message
        self.invalid_message = None

        # Line may be empty
        self.empty = len(self.text) == 0

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def get_by_path(self, path, proof_context):
        # Get an attribute of the proof line given a path s

        initial, remainder = parse_path(path)

        if remainder:
            # Chain the parts
            return self.get_by_path(initial, proof_context).get_by_path(remainder, proof_context)

        # Otherwise, only one part

        if type(path) is list:
            # Get each component
            return [self.get_by_path(item, proof_context) for item in path]

        if type(path) is not str:
            path = str(path)

        if path == "match":
            # Get the match
            return self.match

        if path == "pattern":
            return self.line_type.pattern

        if len(path) > 2 and path[-2:] == "()" and path[:-2] in self.line_type.attributes:
            return self.get_by_path(self.line_type.get_attribute(path[:-2]), proof_context)

        if path in self.context:
            # Check self context first
            return self.context[path]

        if path in proof_context:
            return proof_context[path]

        raise Exception("Could not find " + path + " in '" + self.text + "'.")

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
                            proof_context[key] = current_value.add(sub_value, proof_context)

                        elif type(sub_value) is MatchSet:
                            proof_context[key] = current_value.union(sub_value, proof_context)

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
