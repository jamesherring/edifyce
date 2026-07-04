from copy import copy
import itertools

from .matching import (
    Context,
    Match,
    MatchSet,
    Pattern,
    StringPattern,
    UnionPattern,
    get_by_path,
    parse_arguments,
    parse_path,
)


class FormalSystem:
    # A formal system

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


class LineType:
    # Class for types of lines in formal proofs

    def __init__(self, name, pattern=None, behaviour="none", add_context=None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match (Pattern instance)
        self.pattern = pattern

        # The behaviour of these lines
        self.behaviour = behaviour
        assert self.behaviour in ("none", "import", "logical", "axiom", "indent", "definition", "comment"), \
            f"'{self.behaviour}' is not a valid LineType behaviour."

        # The data paths (and their values) to add to context, if any
        self.add_context = add_context if add_context is not None else {}

        # Custom functions
        self.functions = {}

    def parse_line(self, line, context):
        # Check if the given line string is of this type
        return self.pattern.match(line, context)

    def inherited_functions(self, context):
        # Get all functions associated with this line type. This is to cover functions from formal system inheritance
        return context.variables[self.name].functions

    def add_function(self, name, tree, params=None):
        # Add an function to this pattern. tree is an AbstractSyntaxTree instance

        # Optionally specify a list of (variable, pattern) tuples of parameters
        if params is None:
            params = ()

        self.functions[name] = {
            "tree": tree,
            "params": params
        }

    def get_function(self, name, context):
        # Get the given attribute function

        fns = self.inherited_functions(context)
        if name in fns:
            return fns[name]

        return None

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if type(other) is not LineType:
            return False

        if not self.name == other.name:
            return False

        if not self.behaviour == other.behaviour:
            return False

        if not self.add_context == other.add_context:
            return False

        # Assume true for recursive checks
        memo[(self, other)] = True

        if not self.pattern.equivalent(other.pattern, context, memo):
            memo[(self, other)] = False
            return False

        if not len(self.functions) == len(other.functions):
            memo[(self, other)] = False
            return False

        for key in self.functions:
            if key not in other.functions:
                memo[(self, other)] = False
                return False

            # print("TODO check functions are equivalent")
            # TODO check functions are equivalent

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def __str__(self):
        return self.name


class InferenceRule:
    # Inference rules for deduction

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


class Inference:
    # An application of an inference rule

    def __init__(self, inference_rule, antecedents, extra_antecedents, deduction):

        self.inference_rule = inference_rule

        # Antecedents should be a list of proof lines, deduction should be a proof line
        self.antecedents = antecedents
        self.extra_antecedents = extra_antecedents

        self.deduction = deduction

        # Store inference matches here
        self.antecedent_inference_matches = []
        self.deduction_inference_match = None

        # Variables used in this inference
        self.variables = {}

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

    def copy_to_new_proof(self, proof_line_dictionary):
        # Copy this inference to a new proof with the given mapping for proof lines

        if self.deduction not in proof_line_dictionary:
            # Deduction not mapped
            return None

        new_antecedents = []
        for ant in self.antecedents:
            if ant not in proof_line_dictionary:
                # Antecedent not mapped.
                return None

            # Add the new antecedent
            new_antecedents.append(proof_line_dictionary[ant])

        # Do the same with extra antecedents
        new_extra_antecedents = []
        for ant in self.extra_antecedents:
            if ant not in proof_line_dictionary:
                # Antecedent not mapped.
                return None

            # Add the new antecedent
            new_extra_antecedents.append(proof_line_dictionary[ant])

        # Get the new deduction
        new_deduction = proof_line_dictionary[self.deduction]

        inf = Inference(self.inference_rule, new_antecedents, new_extra_antecedents, new_deduction)

        inf.antecedent_inference_matches = self.antecedent_inference_matches
        inf.deduction_inference_match = self.deduction_inference_match

        inf.variables = self.variables

        return inf


class Proof:
    # A proof in a formal system

    def __init__(self, formal_system, reference_proofs=None, result=None):

        # The system in which this proof belongs
        self.formal_system = formal_system

        # The proof result
        self.result = result

        # Whether the proof is valid
        self.valid = None

        # Any warnings for the proof
        self.has_warnings = False

        # The proof lines leading to the result
        self.proof_lines = []

        # A dictionary of references to other proofs - given on proof creation
        self.reference_proofs = reference_proofs

        # A reference for labelled lines
        self.reference_context = {}

        # Keep a set of proof models referenced from this one (no folders)
        self.proofs_used = set()

        # The proof model id
        self.model_id = None

    def get_proof_line(self, line_number):
        # Get a proof line by line number
        # Line numbers are 1-based, matching how references are written in proofs.
        if not 1 <= line_number <= len(self.proof_lines):
            return None

        return self.proof_lines[line_number - 1]

    def add_proof_line(self, text, context):
        proof_line = ProofLine(self, text, context=copy(context))
        self.proof_lines.append(proof_line)
        return proof_line

    def indicator(self):
        # Get the indicator level
        if not self.valid:
            return "error"

        if self.has_warnings:
            return "warning"

        return "ok"

    def data(self):
        # Get data for this proof
        return {
            "indicator": self.indicator(),
            "lines": [line.data() for line in self.proof_lines]
        }

    def logical_lines(self):
        # Count the logical lines in the proof
        return len([
            line for line in self.proof_lines
            if (not line.empty) and (line.line_type is not None) and line.line_type.behaviour == "logical"
        ])

    def get_reference(self, ref, context):
        # Get the referenced line from a ref string

        # Check if it's reference to another line
        if ref in self.reference_context:
            return self.reference_context[ref]

        for ir in self.formal_system.inference_rules:
            # Compare against the ir label and formatted label
            if ref == ir.label or ref == self.formal_system.format_string(ir.label):
                return {
                    "inference_rule": ir,
                    "antecedents": [],
                    "key": ref,
                    "mapping": {}
                }

        if ", " in ref:
            # Split the ref into parts
            ref_parts = ref.split(", ")
            key = ref_parts[0]

            for ir in self.formal_system.inference_rules:
                if key == ir.label:
                    # It's an inference rule

                    # Get the antecedent lines
                    antecedents = []
                    mapping = {}
                    last_proof_line = None
                    for r in ref_parts[1:]:
                        try:
                            item = self.get_reference(r, context)

                            if isinstance(item, ProofLine):
                                antecedents.append(item)
                                last_proof_line = item
                                continue

                        except Exception:
                            # if item is None and last_proof_line is not None:
                            # Probably a mapping
                            try:
                                if last_proof_line is not None:
                                    mapping.update(self.get_reference_mapping(r, last_proof_line, context))
                                    continue

                            except Exception:
                                pass

                        # Otherwise this is not a proof line
                        raise Exception(f"{r} is not a proof line.")

                    return {
                        "inference_rule": ir,
                        "antecedents": antecedents,
                        "key": key,
                        "mapping": mapping
                    }

            raise Exception(f"'{key}' is not a valid inference rule key.")

        if "." in ref:
            index = ref.index(".")
            proof_ref = ref[:index]
            remainder = ref[index + 1:]

            item = self.get_reference(proof_ref, context)

            if isinstance(item, str):
                # This is an error string
                raise Exception(item)

            if isinstance(item, Proof):
                return item.get_reference(remainder, context)

            elif hasattr(item, "get_reference"):
                # Item has a get reference method (probably a folder!)
                return item.get_reference(remainder, context)

        # Check if it's a line number
        try:
            return self.get_proof_line(int(ref))
        except ValueError:
            pass

        # Nothing works
        raise Exception(f"Invalid reference: {ref}")

    @staticmethod
    def get_reference_mapping(ref, source_proof_line, context):
        # Get the mapping on a proof line with reference to the source proof line.

        if " mapsto " not in ref:
            return {}

        source, target = ref.split(" mapsto ")

        # Get the source pattern using the source line context
        pattern = get_by_path(None, source, source_proof_line.context)

        # Use the same pattern with the current context to get a target match
        target_match = pattern.match(target, context)

        if target_match is None:
            raise Exception(f"Cannot map {source} to {target}.")

        return {source: target_match}

    def check_logical_line(self, proof_line, context):
        # Check if the given proof line is valid.

        if proof_line.proof is not self:
            # Can't check a line outside the proof
            return False

        if proof_line.is_axiom:
            # Easy case
            return True

        if proof_line.formula is None:
            # No formula
            proof_line.valid = False
            proof_line.invalid_message = "No formula defined for logical line."
            return False

        # Get the reference
        try:
            reference = self.get_reference(proof_line.reference_string, context)
        except Exception as e:
            proof_line.invalid_message = str(e)
            proof_line.valid = False
            return False

        if not (type(reference) is dict and "inference_rule" in reference):
            proof_line.invalid_message = f"Invalid reference '{proof_line.reference_string}'."
            proof_line.valid = False
            return False

        # Otherwise, it's an inference rule

        inference_rule = reference["inference_rule"]
        key = reference["key"]
        proof_line.reference_mapping = reference["mapping"]

        # Get the antecedent lines
        antecedents = reference["antecedents"]

        if len(antecedents) == 0 and len(inference_rule.antecedents) == 0:
            # No antecedents for this inference rule
            if inference_rule.check(
                    antecedents=(),
                    extra_antecedents=(),
                    deduction=proof_line,
                    context=context
            ):
                # It's a valid line
                return True

        elif len(antecedents) == 0 and len(inference_rule.antecedents) < 5:
            # Antecedents not provided. Try to justify:
            return self.justify(
                deduction=proof_line,
                context=context,
                inference_rule=inference_rule
            )

        # Otherwise, check the number of antecedents given
        if len(antecedents) < len(inference_rule.antecedents):
            # Not enough antecedents
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires {len(inference_rule.antecedents)!s} antecedent(s)."
            return False

        if len(antecedents) > len(inference_rule.antecedents) and not inference_rule.allow_extra_antecedents:
            # Too many antecedents
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires exactly {len(inference_rule.antecedents)!s} antecedent(s)."
            return False

        if len(antecedents) > 6:
            # Too many permutations to handle
            raise Exception("Server error: too many permutations to consider!")

        extra_antecedents = []
        if inference_rule.allow_extra_antecedents:
            # Split the extra antecedents into a different list
            extra_antecedents = antecedents[len(inference_rule.antecedents):]
            antecedents = antecedents[:len(inference_rule.antecedents)]

        # Try any permutation of the given antecedents
        for permutation in list(itertools.permutations(antecedents)):
            for extra_permutation in list(itertools.permutations(extra_antecedents)):
                if inference_rule.check(
                    antecedents=permutation,
                    extra_antecedents=extra_permutation,
                    deduction=proof_line,
                    context=context
                ):
                    # It's a valid permutation
                    proof_line.antecedents = permutation
                    proof_line.extra_antecedents = extra_permutation
                    proof_line.inference_rule = inference_rule

                    return True

        # No valid permutation found, not a valid line
        proof_line.valid = False
        proof_line.invalid_message = f"{key} does not apply."
        return False

    def import_path(self, path, label, context):
        # Import a result using the given path

        def add_reference(obj):
            # Add a reference to the given object - if it can be associated with a proof
            if isinstance(obj, Proof):
                self.proofs_used.add(obj)

            elif isinstance(obj, ProofLine):
                self.proofs_used.add(obj.proof)

            elif hasattr(obj, "proof"):
                self.proofs_used.add(obj.proof)

            if self in self.proofs_used:
                self.proofs_used.remove(self)

        if path in self.reference_proofs:
            # Found it
            item = self.reference_proofs[path]
            if "errorMessage" in item:
                add_reference(item["target"])
                return {
                    "success": False,
                    "errorMessage": item["errorMessage"],
                    "target": item["target"]
                }

            ref_item = item["target"]

        elif path in self.reference_context:
            # Found it
            ref_item = self.reference_context[path]

            if hasattr(ref_item, "proof"):
                # This is probably a ProofModel
                ref_item = ref_item.proof

        else:
            parts = path.split(".")

            initial = parts[0]
            remainder = ".".join(parts[1:])

            if initial in self.reference_context:
                # Check reference context first
                obj = self.reference_context[initial]

                try:
                    ref_item = obj.get_reference(remainder, context)

                    if hasattr(ref_item, "proof"):
                        # This is probably a ProofModel
                        ref_item = ref_item.proof

                except Exception as e:
                    return {
                        "success": False,
                        "errorMessage": str(e)
                    }

            elif initial in self.reference_proofs:
                # Found it
                ref_dict = self.reference_proofs[initial]

                if "errorMessage" in ref_dict:
                    # This is an error string
                    add_reference(ref_dict["target"])
                    return {
                        "success": False,
                        "errorMessage": ref_dict["errorMessage"],
                        "target": ref_dict["target"]
                    }

                ref_target = ref_dict["target"]
                ref_item = ref_target.get_reference(remainder, context)

                if ref_item is None:
                    # No such label in the ref proof
                    add_reference(ref_target)
                    return {
                        "success": False,
                        "errorMessage": f"{initial} does not have a line with label {remainder}.",
                        "target": ref_target
                    }

                if isinstance(ref_target, Proof) and (ref_target.has_warnings or not ref_target.valid):
                    # Referenced proof has errors
                    add_reference(ref_target)
                    return {
                        "success": False,
                        "errorMessage": f"{path} has unresolved errors.",
                        "target": ref_target
                    }

            else:
                # Don't recognise the path
                return {
                    "success": False,
                    "errorMessage": f"Could not find '{path}'."
                }

        # Add the reference
        self.reference_context[label] = ref_item
        add_reference(ref_item)

        # Add any definitions we have imported
        if isinstance(ref_item, ProofLine) and ref_item.line_type is not None and ref_item.line_type.behaviour == "definition":
            context.definitions.add(ref_item.definition)
            self.import_definition(ref_item.definition, context)

        elif isinstance(ref_item, Proof):
            for line in ref_item.proof_lines:
                if isinstance(line, ProofLine) and line.line_type is not None and line.line_type.behaviour == "definition":
                    context.definitions.add(line.definition)
                    self.import_definition(line.definition, context)

        return {
            "success": True,
            "target": ref_item
        }

    def import_definition(self, definition, context):
        # Import the given definition from one proof to another. Requires careful handling with inherited patterns

        build_context = self.formal_system.build_context

        # Get the pattern name
        pattern_name = definition.pattern.name

        # Get the instance of this pattern in this formal system
        pattern = build_context.variables[pattern_name]

        # Get a copy of context to add the variables needed for this pattern
        context_copy = copy(context)
        context_copy.string_variables.update(definition.variables)

        # Use the build context pattern if it exists
        for key, value in definition.variables.items():
            name = value.name
            if name in build_context.variables:
                context_copy.string_variables[key] = build_context.variables[name]

        # Get the condition string if it exists
        condition_string = None if definition.condition is None else definition.condition.string

        result = pattern.add_definition(definition.lower.pattern, definition.higher.pattern, context_copy,
                                        condition_string, require_lower_match=False)

        if result is None:
            raise Exception(f"Failed to import definition: {definition.higher.pattern}")

        # Remove any existing (possibly duplicate) conditions
        if result not in context.definitions:
            remove_items = set()

            for defn in context.definitions:
                if defn.higher.pattern == result.higher.pattern and defn.pattern.can_map_to(pattern, context):
                    # Can be removed
                    remove_items.add(defn)

            for item in remove_items:
                context.definitions.remove(item)

            # Add the definition to context
            context.definitions.add(result)

    def justify(self, deduction, context, inference_rule=None):
        # Artificially try to find a justification for the given reference. Optionally specify a inference rule.

        if inference_rule is not None:

            logical_lines = [
                line for line in self.proof_lines[:deduction.index()]
                if line.line_type is not None and line.line_type.behaviour in ("logical", "definition")
            ][-len(inference_rule.antecedents):]

            if not len(logical_lines) == len(inference_rule.antecedents):
                # Not enough previous logical lines
                deduction.valid = False
                deduction.invalid_message = "Antecedent lines couldn't be inferred."
                return False

            for permutation in list(itertools.permutations(logical_lines)):

                if inference_rule.check(
                        antecedents=permutation,
                        extra_antecedents=(),
                        deduction=deduction,
                        context=context
                ):
                    # Found the valid permutation
                    deduction.antecedents = permutation
                    deduction.inference_rule = inference_rule

                    return True

            # Otherwise, no justification found
            deduction.valid = False
            deduction.invalid_message = f"{inference_rule.label} does not apply."

            return False

        # Otherwise, no inference rule specified.
        return False


class ProofLine:
    # A line in a proof

    def __init__(self, proof, text, context, reference_string=None, label=None):

        # The proof this line belongs to
        self.proof = proof

        # The text string on this line
        self.text = text

        # The text to display on this line. By default equal to the actual text, stripped.
        self.display = text.strip()

        # A frozen context - useful to later refer to from inference rules
        self.context = context

        # The reference string for this line (if any)
        self.reference_string = reference_string
        self.reference_string_display = reference_string

        # A reference mapping given on the line
        self.reference_mapping = {}

        # The label for this line (if any)
        self.label = label

        # The formula match (if any) on this line
        self.formula = None

        # The definition created (if any) on this line
        self.definition = None

        # The LineType used for this line
        self.line_type = None

        # The match with the line type pattern
        self.match = None

        # The indentation of this line
        self.indent = len(self.text) - len(self.text.lstrip())

        # This line may be an axiom
        self.is_axiom = False
        self.axiom_pattern = None

        # The axiom this line uses (if any)
        self.axiom = None

        # The inference instance with this line as the deduction
        self.inference = None

        # Whether this step in the proof is valid
        self.valid = True

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = set()

        # Invalid message
        self.invalid_message = None

        # Warning message
        self.warning_message = None

        # Line may be empty
        self.empty = len(self.text) == 0

    def execute(self, context):
        # Execute this proof line in the system.

        line_type = self.line_type

        if self.label is not None:
            # Add the proof line to the proof's reference context
            self.proof.reference_context[self.label] = self

        if line_type.behaviour == "logical":
            # Logical lines for parsing
            self.proof.check_logical_line(self, context)

        elif line_type.behaviour == "axiom":
            # Introduce an axiom to the system

            self.is_axiom = True

            self.axiom_pattern = self.formula.create_pattern(context.string_variables)
            self.axiom_pattern.name = self.label

        elif line_type.behaviour == "definition":
            # Introduce a new definition to context

            try:
                # Get the higher and lower strings, and the pattern it should apply to.
                lower = self.match.get_by_path("lower()", context)
                higher = self.match.get_by_path("higher()", context)
                pattern = self.match.get_by_path("for()", context)
            except Exception:
                # Not a valid definition
                self.valid = False
                self.invalid_message = "Missing higher or lower for definition."
                return

            if pattern.match(lower.string, context) is None:
                self.valid = False
                self.invalid_message = f"{lower.string} is not an instance of {pattern.name}."
                return

            # Also try to get conditions
            condition_string = None
            try:
                conditions = self.get_by_path("conditions()", context)
                if len(conditions) > 0:
                    condition_string = " and ".join([c.string for c in conditions])
            except Exception:
                pass

            # Add the definition
            self.definition = pattern.add_definition(lower.formatted_string(), higher.formatted_string(), context,
                                                     condition_string)

        elif line_type.behaviour == "import":
            # Import a file or result

            try:

                if self.label is None:
                    self.valid = False
                    self.invalid_message = "Line has missing label."
                    return

                path = self.match.get_by_path("path()", context)
                result = self.proof.import_path(path, self.label, context)

                if not result["success"]:
                    # Error
                    self.valid = False
                    self.invalid_message = result["errorMessage"]

            except Exception as e:
                # No valid path or label
                self.valid = False
                self.invalid_message = f"Could not get path or label from import line: {e!s}"

        elif line_type.behaviour in ("none", "comment"):
            # Don't need to do anything :)
            pass

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def get_by_path(self, path, context, recurse=True):
        # Get an attribute of the proof line given a path s

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        initial, remainder = parse_path(path)

        if remainder:
            # Use generic get by path
            return get_by_path(self, path, context)

        # Otherwise, only one part
        if path == "text()":
            return self.text

        if path == "match()":
            # Get the match
            return self.match

        if path == "pattern()":
            return self.line_type.pattern

        if path == "formula()":
            return self.formula

        if path == "label()":
            return self.label

        if path == "definition()":
            return self.definition

        if path == "conditions()":
            return self.context.conditions

        if path == "reference_mapping()":
            return copy(self.reference_mapping)

        if path == "previous_formulae()":
            return self.previous_formulae()

        if "(" in path and path[:path.index("(")] in self.line_type.inherited_functions(context):
            # An attribute function with parameters

            index = path.index("(")
            name = path[:index]

            args_strings = path[index + 1:-1]
            args, kwargs = parse_arguments(args_strings, self, context)

            return self.run_function(name, context, args=args, kwargs=kwargs)

        if path.startswith("check_condition(") and path[-1] == ")":
            inner = path[16:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("condition", "mapping"))[1]

            return self.check_condition(kwargs["condition"], context, kwargs["mapping"])

        if path.startswith("follows_from_definition(") and path[-1] == ")":
            # Follows from definition
            inner = path[24:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "definition", "mapping"))[1]

            return self.follows_from_definition(kwargs["other"], kwargs["definition"], kwargs["mapping"], context)

        # Try to get path using the frozen context
        if path in self.context.logical:
            return self.context.logical[path]

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

    def check_condition(self, condition, context, mapping=None):
        # Check a condition using the given context. Optionally specify a string variable mapping

        # Work with a copy of context
        context = copy(context)

        if mapping is not None:
            # Set context mapping
            assert isinstance(mapping, dict), f"Mapping dictionary must be a dictionary, not {type(mapping)!s}."
            context.mapping = mapping

        # Set string variable matches
        context.set_string_variable_matches()

        try:
            return condition.check_condition(self, context)
        except Exception:
            return False

    def follows_from_definition(self, other, definition, mapping, context):
        # Check if this proof line follows from the other by means of a definition.

        if (not self.line_type.behaviour == "logical") or (not other.line_type.behaviour == "logical"):
            # Must be logical lines
            return False

        # Check if the definition applies - in either direction
        return definition.check_application(
            lower=other.formula,
            higher=self.formula,
            context=context,
            mapping=mapping
        ) or definition.check_application(
            lower=self.formula,
            higher=other.formula,
            context=context,
            mapping=mapping
        )

    def edit_context(self, context):
        # Edit the proof context according to the rule on this line type

        if self.line_type.add_context is None:
            # Nothing to change
            return context

        # Otherwise, changes to make
        for key, value in self.line_type.add_context.items():

            if key not in context.__dict__ and key not in context.logical:
                raise Exception(f"Can't find '{key}' in proof context.")

            # Get the current value and target dictionary
            if key in context.logical:
                current_value = context.logical[key]
                target = context.logical
            else:
                current_value = getattr(context, key)
                target = context.__dict__

            if type(current_value) is dict:
                # Dictionary type context entry

                for sub_key_string, sub_value_string in value.items():

                    # Try get by path
                    sub_key = self.get_by_path(sub_key_string, context)

                    # Get the value
                    sub_value = self.get_by_path(sub_value_string, context)

                    if isinstance(sub_key, (list, tuple, set)):
                        # Need to add each item
                        for item in sub_key:
                            target[key][item] = sub_value

                    elif type(sub_key) is Match:
                        # Just one match
                        target[key][sub_key.string] = sub_value

                    else:
                        # Add directly
                        target[key][sub_key] = sub_value

            elif type(current_value) is set:
                # Set type context entry

                for edit_type, sub_value_string in value.items():

                    # Get the value
                    sub_value = self.get_by_path(sub_value_string, context)

                    # Get the attribute function of the set
                    attr = getattr(current_value, edit_type)

                    # Run this with the given value
                    result = attr(sub_value)

                    if result is not None:
                        # Update the target value
                        target[key] = result

                    # Otherwise ok - could be just a function that changes the existing value but doesn't return
                    # anything, e.g. set.add()

            elif type(current_value) is MatchSet:
                # MatchSet type context entry

                for edit_type, sub_value_string in value.items():

                    # Get the value
                    sub_value = self.get_by_path(sub_value_string, context)

                    if edit_type == "union":
                        # Union the set with the value

                        if type(sub_value) is Match:
                            target[key] = current_value.add(sub_value, context)

                        elif type(sub_value) is MatchSet:
                            target[key] = current_value.union(sub_value, context)

                        else:
                            # Has to be a match or a match set
                            raise Exception(f"Cannot union a set with object of type '{type(sub_value)!s}'.")

                    elif edit_type == "add":
                        # Add the value to the set
                        if type(sub_value) is not Match:
                            # Has to be a match
                            raise Exception("Cannot add a non-match to a match set")

                        current_value.add(sub_value, context)

                    else:
                        raise Exception(f"Cannot edit a set with operator '{edit_type}'.")

        return context

    def data(self):
        # Get data for this proof line
        return {
            "valid": self.valid,
            "behaviour": self.line_type.behaviour if self.line_type is not None else None,
            "name": self.line_type.name if self.line_type is not None else None,
            "invalid_message": self.invalid_message,
            "warning_message": self.warning_message,
            "reference": self.reference_string_display,
            "label": self.label,
            "display": self.display,
            "indent": self.indent
        }

    def run_function(self, name, context, args=None, kwargs=None):
        # Run a custom function with the given name, args and kwargs

        fn = self.line_type.get_function(name, context)

        if fn is None:
            raise Exception(f"'{self.line_type.name}' does not have function '{name}'.")

        # Check the params matches have the correct pattern
        if args is None:
            args = []

        if kwargs is None:
            kwargs = {}

        arg_count = len(args) + len(kwargs)
        if not arg_count == len(fn["params"]):
            # Wrong number of parameters provided
            raise Exception(f"'{name}' expected {len(fn['params'])!s} argument(s), {arg_count!s} provided.")

        # Build a parameter mapping
        param_mapping = {}

        # Check args
        for given, fn_param in zip(args, fn["params"][:len(args)]):
            param_mapping[fn_param[0]] = given

        # kwargs don't have to be in order
        remaining_fn_params = fn["params"][len(args):]
        remaining_fn_param_dict = {param[0]: param[1] for param in remaining_fn_params}

        # Check kwargs
        for given_name, given in kwargs.items():
            if given_name not in remaining_fn_param_dict:
                raise Exception(f"'{name}' does not accept parameter '{given_name}.")

            param_mapping[given_name] = given

        # Create a copy of proof line context
        context_copy = copy(context)

        # Run the tree as a function
        tree = fn["tree"]

        return tree.run_function(item=self, context=context_copy, params=param_mapping, param_types=fn["params"])

    def previous_formulae(self):
        # Return a matchset of formulae that have been proven before this statement in the proof and share the same
        # logical context.

        # N.B. we don't require that the previous proof lines are valid
        formulae = MatchSet(allow_multiple=False)
        indent = self.indent

        # Loop through the previous lines and select only those that are parents/siblings of this line context
        for i in range(self.index() - 1, -1, -1):
            line = self.proof.proof_lines[i]

            if line.indent > indent:
                # This line is more indented - ignore
                continue

            if line.indent < indent:
                # This line is less indented - ie. it's a parent line in the abstract syntax tree.
                indent = line.indent
                continue

            if line.line_type is None or not line.line_type.behaviour == "logical":
                # It's not a logical line
                continue

            # Otherwise, it's a relevant logical line
            formulae.add(line.formula, self.context)

        return formulae

    def copy_from_previous_proof(self, previous_line, proof_line_dictionary):
        # Update this line to be a copy of the previous line.

        # First check if this is even valid. We need to have the right variables.
        if previous_line.match is None:
            return False

        match_vars = previous_line.match.variables(previous_line.context)

        # Check all string variables in the previous match are present with equivalent pattern in this context
        for var in match_vars.instances:
            s = var.formatted_string()
            if s not in self.context.string_variables:
                return False

            if not var.pattern.equivalent(self.context.string_variables[s], self.context):
                return False

        # All good - check definition variables if these are used
        if previous_line.definition is not None:
            for key, pattern in previous_line.definition.variables.items():
                if key not in self.context.string_variables:
                    return False

                if not pattern.equivalent(self.context.string_variables[key], self.context):
                    return False

        # Get a new inference
        new_inference = None
        if previous_line.inference is not None:
            # Check the reference is still valid
            try:
                ants = self.proof.get_reference(previous_line.reference_string, self.context)["antecedents"]

            except Exception:
                # Failed to get reference
                return False

            # Look for antecedent lines pointing to other proofs - and add them to our context dictionary if they aren't
            # already there
            for ant in ants:
                if ant.proof.model_id == self.proof.model_id:
                    continue

                # This line is in another proof.
                for previous_ant in previous_line.inference.antecedents:
                    if previous_ant in proof_line_dictionary:
                        # Already mapped
                        continue

                    if ant.equivalent(previous_ant):
                        # These antecedents are the same. Add to the dictionary
                        proof_line_dictionary[previous_ant] = ant

            # Try getting a copy of the inference
            new_inference = previous_line.inference.copy_to_new_proof(proof_line_dictionary)

            if new_inference is None:
                # Failed to get a compatible inference
                return False

        # Check logical context - this needs to match!
        for key, previous_obj in previous_line.context.logical.items():
            if key not in self.context.logical:
                # No match
                return False

            current_obj = self.context.logical[key]

            # We need to confirm the previous and new objects are the same or equivalent

            if previous_obj == current_obj:
                continue

            if not type(previous_obj) == type(current_obj):
                return False

            if not hasattr(previous_obj, "equivalent"):
                # No way to check equivalence
                return False

            try:
                if not previous_obj.equivalent(current_obj, self.context):
                    return False
            except Exception:
                return False

            # Otherwise ok

        self.__init__(
            proof=self.proof,
            text=previous_line.text,
            context=self.context,
            reference_string=previous_line.reference_string,
            label=previous_line.label
        )

        # Set all the other needed attributes
        self.display = previous_line.display
        self.reference_string_display = previous_line.reference_string_display
        self.reference_mapping = previous_line.reference_mapping
        self.formula = previous_line.formula
        self.definition = previous_line.definition
        self.line_type = previous_line.line_type
        self.match = previous_line.match
        self.indent = previous_line.indent
        self.is_axiom = previous_line.is_axiom

        self.inference = new_inference

        self.valid = previous_line.valid
        self.invalid_message = previous_line.invalid_message
        self.warning_message = previous_line.warning_message

        # Ignore dependent lines

        # All ok
        return True

    def equivalent(self, other):
        # Check if this is the same as the other proof line
        return self.proof.model_id == other.proof.model_id and self.index() == other.index()

    def __str__(self):
        return f"ProofLine: {self.text}"
