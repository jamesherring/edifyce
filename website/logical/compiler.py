from website.logical.matching import *
from website.logical.matching import constant
from website.logical.formal_system import FormalSystem, LineType, InferenceRule, ProofLine
from copy import copy, deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field


def get_inherited_system(code):
    # Get referenced systems from the given code

    slug = None

    lines = code.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("inherit "):
            slug = line[8:]

    return slug


def compile(code, system_dict=None):
    # Compile the given code string into a tree. Return the formal system.

    # Optionally specify a system_dict of reference systems

    # Create an initial context
    context = FormalSystemContext()
    context.system_dict = system_dict if system_dict is not None else {}

    # Create a root node
    root = AbstractSyntaxTree()
    root.add_lines(code.split("\n"))

    context = root.run(context)

    # Return error log if there are errors
    if len(context.error_log) > 0:
        return {"errors": context.error_log}

    # Return the formal system
    for item in context.variables.values():
        if isinstance(item, FormalSystem):
            return {"system": item}

    # Return an empty formal system
    return {"system": FormalSystem(name="")}


def parse_arguments(s):
    # Parse comma separated arguments from a string s

    if len(s) == 0:
        return []

    # Start by splitting on commas
    parts = s.split(", ")

    # Adjust for brackets - every part must be balanced
    i = 0
    while i < len(parts):

        part = parts[i]

        if "(" not in part and ")" not in part:
            i += 1
            continue

        if not part.count("(") == part.count(")"):
            # Brackets don't match

            if i + 1 == len(parts):
                # Invalid input
                return None

            parts[i] = f"{parts[i]}, {parts[i + 1]}"
            parts.pop(i + 1)
            continue

        depth = 0
        continue_flag = False

        for char in part:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1

            continue_flag = False

            if depth < 0:
                # Brackets don't match

                if i + 1 == len(parts):
                    # Invalid input
                    return None

                parts[i] = f"{parts[i]}, {parts[i + 1]}"
                parts.pop(i + 1)

                continue_flag = True
                break

        if continue_flag:
            continue

        i += 1

    # Split the parts into variable names and pattern names
    args = []

    for part in parts:
        vars, pattern = part.split(" as ")

        for var in vars.split(", "):
            args.append((var, pattern))

    return args


@dataclass(eq=False)
class FormalSystemContext:

    # Variables in the code (the system condition pattern is included by default)
    variables: dict = field(
        default_factory=lambda: {"_system_condition_": SystemConditionPattern(name="System Condition")}
    )

    # String variables for inside patterns
    string_variables: dict = field(default_factory=dict)

    # Definitions created along the way
    definitions: list = field(default_factory=list)

    # Current object at a point in the code
    current_object: object = None

    # Proof context
    proof_context: dict = field(default_factory=dict)

    # Formatting context
    pre_format: dict = field(default_factory=dict)

    # External systems for reference
    system_dict: dict = field(default_factory=dict)

    # Error log
    error_log: list = field(default_factory=list)

    def inherit(self, parent):
        # Inherit from parent context

        self.variables.update(parent.variables)
        self.definitions.extend(parent.definitions)
        self.proof_context.update(parent.proof_context)
        self.pre_format.update(parent.pre_format)
        self.system_dict.update(parent.system_dict)

        # Don't inherit string_variables or current_object

        # Inherit union patterns
        for pattern in self.variables.values():
            if not isinstance(pattern, UnionPattern):
                continue

            # Pattern is a union pattern. Set the inheritance
            pattern.inherits = deepcopy(pattern)

    def __copy__(self):
        new_context = FormalSystemContext()

        new_context.variables = copy(self.variables)
        new_context.string_variables = copy(self.string_variables)
        new_context.definitions = copy(self.definitions)
        new_context.current_object = self.current_object
        new_context.proof_context = copy(self.proof_context)
        new_context.pre_format = copy(self.pre_format)
        new_context.system_dict = copy(self.system_dict)
        new_context.error_log = copy(self.error_log)

        return new_context


class AbstractSyntaxTree:
    """A node in an abstract syntax tree"""

    def __init__(self, line=None, line_number=0):

        # The line string if it exists
        self.line = line

        # The line number if it exists
        self.line_number = line_number

        # The list of sub-trees
        self.sub_trees = []

        # The parent tree (if it exists)
        self.parent = None

        # The indent level of this line
        self.indent = None
        if self.line is not None:
            self.indent = len(line) - len(line.lstrip())

        # The type of line this is
        self.type = None

        # The error in parsing this line - if any
        self.error = None

    def is_root(self):
        return self.line is None

    def is_leaf(self):
        return len(self.sub_trees) == 0

    def add_lines(self, lines):
        # Parse the given lines into this node

        def add_sub_lines(last_sub_tree, sub_lines):
            # Add the given sub-lines to the last sub tree, if it exists

            if len(sub_lines) == 0:
                return

            real_line = False
            for line in sub_lines:
                if len(line.strip()) > 0:
                    # Non-empty subline exists
                    real_line = True

            if not real_line:
                # All sub-lines are just empty
                return

            if last_sub_tree is None:
                # No last sub tree to add the lines to
                self.error = "Invalid indent"
                return

            # Recursively add the lines
            last_sub_tree.add_lines(sub_lines)

        sub_tree_indent = 0
        if self.indent is not None:
            sub_tree_indent = self.indent + 4

        # Add the lines with the correct indent
        last_sub_tree = None
        sub_lines = []

        for i in range(0, len(lines)):
            line = lines[i]

            if len(line.lstrip()) == 0:
                # No need to worry about blank lines
                sub_lines.append("")
                continue

            sub_tree = AbstractSyntaxTree(line, line_number=i + 1 + self.line_number)

            if sub_tree.indent == sub_tree_indent:

                # Recursively add sub_lines
                add_sub_lines(last_sub_tree, sub_lines)

                # Add the sub tree
                self.sub_trees.append(sub_tree)
                sub_tree.parent = self
                last_sub_tree = sub_tree

                sub_lines = []
                continue

            # Otherwise, add the line to the sub lines stack
            sub_lines.append(line)

        # Add any remaining sub-lines
        add_sub_lines(last_sub_tree, sub_lines)

    def run(self, context=None):
        # Execute this line in the given context

        if context is None:
            # Create a context
            context = FormalSystemContext()

        if self.is_root():
            # Just run the sub trees

            for tree in self.sub_trees:
                tree.run(context)

            return context

        # Otherwise, check what kind of line this is

        # Remove spaces
        stripped = self.line.strip()

        current_object = context.current_object

        # New data to add to inner context
        new_object = None
        new_string_variables = {}

        try:

            if stripped[0] == "#":
                # This is a comment - no need to do anything
                return

            if stripped.startswith("inherit "):
                # Inherit from an existing formal system

                name = stripped[8:]
                if name not in context.system_dict:
                    self.error = f"Could not find formal system with slug: {name}."
                    return

                system = context.system_dict[name]

                # Inherit the system context
                context.inherit(system.build_context)

                # Add inference rules and line types
                if isinstance(current_object, FormalSystem):
                    for ir in system.inference_rules:
                        current_object.add_inference_rule(ir)

                    for lt in system.line_types:
                        current_object.add_line_type(lt)

                    # Add proof context
                    current_object.context.logical.update(deepcopy(system.context.logical))

            elif stripped.startswith("FormalSystem ") and stripped[-1] == ":":
                # Looks like a formal system declaration

                self.type = "FormalSystem"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Add the formal system to context
                fs = FormalSystem(name=name)
                context.variables[name] = fs

                new_object = fs

            elif stripped == "ProofContext:":
                # Logical proof context definition
                self.type = "ProofContext"
                new_object = current_object.context.logical

            elif stripped.startswith("Format ") and stripped[-1] == ":":
                # Create a format dictionary
                self.type = "Format"

                name = stripped[7:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create a new ordered dictionary to keep the format
                new_object = OrderedDict()

                context.variables[name] = new_object

            elif stripped.startswith("Format "):
                # Apply a format dictionary

                name = stripped[7:]

                if name not in context.variables:
                    raise Exception(f"Could not find format dictionary '{name}'.")

                pre_format = context.variables[name]

                # Update context formatting, which is used for patterns, string variables, etc.
                context.pre_format.update(pre_format)

            elif stripped.startswith("Abstract "):
                # Create an abstract pattern variable

                self.type = "Abstract"

                names = stripped[9:].split(", ")

                for name in names:
                    if not self.valid_variable_name(name):
                        self.error = f"Invalid variable name: '{name}'."
                        return

                    # Add to context
                    context.variables[name] = AbstractPattern(name=name)

            elif stripped.startswith("Regex ") and stripped[-1] == ":":
                # Create a regex pattern variable

                self.type = "Regex"

                name = stripped[6:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Add to context with placeholder pattern
                pattern = RegexPattern(name=name, pattern="", pre_format=context.pre_format)
                context.variables[name] = pattern

                new_object = pattern

            elif stripped.startswith("Pattern ") and stripped[-1] == ":":
                # String pattern

                self.type = "Pattern"

                name = stripped[8:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the pattern
                pattern = StringPattern(name=name, pattern="", pre_format=context.pre_format)
                context.variables[name] = pattern

                new_object = pattern

            elif stripped.startswith("UnionPattern ") and stripped[-1] == ":":
                # Union pattern

                self.type = "UnionPattern"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the union with no patterns to begin with
                union = UnionPattern(name=name, patterns=[], pre_format=context.pre_format)
                context.variables[name] = union

                new_object = union

            elif stripped.startswith("Define ") and " as " in stripped:
                # Definition
                self.type = "Definition"

                remainder = stripped[7:]
                index = remainder.index(" as ")
                higher = remainder[:index]
                lower = remainder[index + 4:]

                # Check for condition
                condition_string = None
                if " if " in lower:
                    index = lower.index(" if ")
                    condition_string = lower[index + 4:]
                    lower = lower[:index]

                if not isinstance(current_object, Pattern):
                    self.error = "Definitions must be created inside a pattern block."
                    return

                # Create the definition - just stored as a dictionary for future parsing
                context.definitions.append({
                    "lower": lower,
                    "higher": higher,
                    "pattern": current_object,
                    "variables": {current_object.pre_format_apply(key): context.string_variables[key] for key in context.string_variables},
                    "condition_string": condition_string
                })

            elif stripped.startswith("LineType ") and stripped[-1] == ":":
                # New linetype

                self.type = "LineType"

                name = stripped[9:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the linetype
                new_object = LineType(name=name)

                # Add to formal system
                if type(current_object) is not FormalSystem:
                    raise Exception(f"Cannot add LineType to object of type {type(current_object)!s}.")

                context.variables[name] = new_object

            elif stripped.startswith("InferenceRule ") and stripped[-1] == ":":
                # New InferenceRule

                self.type = "InferenceRule"

                name = stripped[14:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Gather variables
                temp_pattern = StringPattern(name="temporary", pattern="", pre_format=context.pre_format)
                variables = {temp_pattern.pre_format_apply(var): context.string_variables[var] for var in context.string_variables}

                # Create the rule
                new_object = InferenceRule(name=name, variables=variables)

            elif stripped.startswith("with ") and stripped[-1] == ":":
                # Define string variables

                self.type = "with"

                # Split into parts
                parts = stripped[5:-1].split(", ")

                strings = []
                for part in parts:
                    if " as " in part:
                        # Final string variable and reference

                        final_string, reference = part.split(" as ")
                        strings.append(final_string)

                        if reference not in context.variables:
                            # Can't find reference
                            self.error = f"Could not find pattern with name '{reference}'."
                            return

                        pattern = context.variables[reference]

                        if not isinstance(pattern, Pattern):
                            self.error = f"'{reference}' is not a pattern."
                            return

                        # Add to inner context
                        for s in strings:
                            new_string_variables[s] = pattern

                        # Empty the stack of strings
                        strings = []

                    else:
                        strings.append(part)

            elif stripped in context.variables and type(current_object) is UnionPattern:
                # Get the referenced object

                self.type = "variable"

                obj = context.variables[stripped]

                if type(obj) not in (StringPattern, UnionPattern, RegexPattern, AbstractPattern):
                    self.error = f"Can't add object of type '{type(obj)!s}' to UnionPattern."
                    return

                # Append the pattern
                current_object.patterns.append(obj)

            elif stripped[-1] == ":" and stripped[:-1] in context.variables:
                # Continue definition of an already defined pattern

                self.type = "PatternContinuation"

                pattern = context.variables[stripped[:-1]]

                if type(pattern) is not UnionPattern:
                    self.error = f"Can't start a block with '{stripped}'."
                    return

                new_object = pattern

            elif stripped[-15:] == ".add_variables:":
                self.type = "add_variables"

                # Get the pattern
                name = stripped[:-15]

                if name not in context.variables:
                    raise Exception(f"Could not find pattern '{name}.")

                # Pattern is a StringPattern or UnionPattern instance
                pattern = context.variables[name]

                # Construct a dictionary of variables to add
                variable_dict = {}
                for sub_tree in self.sub_trees:
                    s = sub_tree.line.strip()
                    if len(s) == 0 or s[0] == "#":
                        continue

                    index = s.find(":")

                    if index == -1:
                        raise Exception(f"Could not parse line '{stripped}'.")

                    name = s[:index]
                    value = s[index + 2:]

                    if value not in context.variables:
                        raise Exception(f"Could not find pattern: '{value}'.")

                    variable_dict[name] = context.variables[value]

                pattern.add_variables(variable_dict)

                return

            elif stripped[-8:] == ".format:":
                # Add format dictionary to pattern

                name = stripped[:-8]

                if name not in context.variables:
                    raise Exception(f"Could not find pattern '{name}.")

                # Pattern is a StringPattern or UnionPattern instance
                pattern = context.variables[name]

                # Get the dictionary of variables to add - starting with pre_format context
                format_dict = copy(context.pre_format)
                for sub_tree in self.sub_trees:

                    s = sub_tree.line.strip()

                    if len(s) == 0 or s[0] == "#":
                        continue

                    if s == "clear":
                        # Clear the format so far
                        format_dict = {}
                        continue

                    if s in context.variables and type(context.variables[s]) is dict:
                        # This is a formatting dictionary
                        format_dict.update(context.variables[s])
                        continue

                    index = s.find(":")

                    if index == -1:
                        raise Exception(f"Could not parse line '{stripped}'.")

                    key = s[:index]
                    value = s[index + 2:]

                    format_dict[key] = value

                pattern.set_pre_format(format_dict)
                return

            elif self.parent.type == "ProofContext":
                # Add the item to proof context

                index = stripped.find(": ")

                if index == -1:
                    raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if value_string == "set()":
                    current_object[key] = set()

                elif value_string == "MatchSet()":
                    current_object[key] = MatchSet()

                elif value_string == "dict()":
                    current_object[key] = {}

                else:
                    raise Exception(f"Could not parse value '{value_string}'.")

            elif type(current_object) is StringPattern:
                # Define the pattern
                current_object.set_pattern(stripped)

                # Apply string variables
                current_object.add_variables(context.string_variables)

            elif type(current_object) is UnionPattern:
                # Add a pattern to the union

                if stripped in context.string_variables and isinstance(context.string_variables[stripped], Pattern):
                    # Looks like a reference to another pattern
                    pattern = context.string_variables[stripped]

                else:
                    pattern = StringPattern(name=current_object.name, pattern=stripped, pre_format=context.pre_format)

                    # Add any relevant string variables
                    pattern.add_variables(context.string_variables)

                current_object.patterns.append(pattern)

            elif type(current_object) is RegexPattern:
                # Define the regex pattern
                current_object.pattern = stripped

            elif type(current_object) is LineType:
                # Add an attribute to the line type

                index = stripped.find(":")

                if index == -1:
                    raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if key == "pattern":

                    # Get the value
                    if not (value_string in context.variables):
                        raise ValueError(f"Couldn't find {value_string} in variables.")

                    # Update the line type accordingly
                    current_object.pattern = context.variables[value_string]

                elif key == "behaviour":
                    # Update the behaviour
                    current_object.behaviour = value_string

                elif key[:7] == "context":
                    # Create an 'add to context' dictionary

                    if key == "context":
                        new_object = current_object.add_context

                    else:
                        # Some path within the context
                        index = key.find(".")
                        if index == -1:
                            raise Exception(f"Could not parse context key '{key}'.")

                        sub_key = key[index + 1:]

                        if sub_key not in current_object.add_context:
                            current_object.add_context[sub_key] = {}

                        new_object = current_object.add_context[sub_key]

                else:
                    raise Exception(f"Unrecognised parameter for LineType '{key}'.")

            elif self.parent.type == "InferenceRule":
                # Inference rule

                if stripped == "label:":
                    # Add the label
                    label = None
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            label = stripped_line

                    if label is None:
                        raise Exception(f"Could not parse label for '{current_object.name}'.")

                    current_object.label = label
                    return

                if stripped == "antecedents:":
                    # Create the antecedents list

                    for line in self.sub_trees:
                        stripped_line = line.line.strip()

                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            # Get the antecedents as patterns

                            if stripped_line in context.variables:
                                # Variable pointing to a pattern
                                current_object.antecedents.append(context.variables[stripped_line])

                            else:
                                # New pattern
                                new_pattern = StringPattern(name="antecedent", pattern=stripped_line, pre_format=context.pre_format)

                                # Add variables
                                new_pattern.add_variables(context.string_variables)

                                current_object.antecedents.append(new_pattern)

                    return

                elif stripped == "deduction:":
                    # Get the deduction

                    for line in self.sub_trees:
                        stripped_line = line.line.strip()

                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            # Get the deduction as a pattern

                            if stripped_line in context.variables:
                                # Variable pointing to a pattern
                                current_object.deduction = context.variables[stripped_line]

                            else:
                                # New pattern
                                current_object.deduction = StringPattern(
                                    name="deduction",
                                    pattern=stripped_line,
                                    pre_format=context.pre_format
                                )

                                # Add variables
                                current_object.deduction.add_variables(context.string_variables)

                    return

                elif stripped == "condition:":
                    # Create a condition for the rule

                    # Start with an empty condition
                    new_object = Condition(string="")
                    current_object.condition = new_object

                elif stripped == "allow_extra_antecedents:":
                    # Maybe allow extra antecedents (should be True or False)
                    value = None
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if stripped_line == "True":
                            value = True
                        elif stripped_line == "False":
                            value = False

                    if value is None:
                        raise Exception(f"Could not parse label for '{current_object.name}'.")

                    current_object.allow_extra_antecedents = value
                    return

                elif stripped == "format:":
                    # Create a format dictionary

                    new_object = {}

                    if current_object.deduction is not None:
                        current_object.deduction.pre_format = new_object

                    for ant in current_object.antecedents:
                        ant.pre_format = new_object

            elif type(current_object) in (dict, OrderedDict):
                # Add a key value pair to the dictionary

                index = stripped.find(":")

                if index == -1:
                    # Item can be reference to already defined dictionary
                    if stripped in context.variables and type(context.variables[stripped]) is dict:
                        current_object.update(context.variables[stripped])

                    else:
                        raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                # Check for strings
                if len(key) >= 2 and (key[0] == key[-1] == "'" or key[0] == key[-1] == '"'):
                    key = key[1:-1]

                if len(value_string) >= 2 and (value_string[0] == value_string[-1] == "'" or
                                               value_string[0] == value_string[-1] == '"'):
                    value_string = value_string[1:-1]

                current_object[key] = value_string

            elif type(current_object) is Condition:
                # Apply condition text

                current_object.string = stripped
                current_object.parse()

            else:

                # Check for match functions
                index = stripped.find(".")
                if index > -1 and stripped[-2:] == "):":

                    name = stripped[:index]
                    remainder = stripped[index + 1:-1]

                    if name not in context.variables:
                        self.error = f"Unrecognised variable '{name}'."
                        return

                    obj = context.variables[name]

                    if not isinstance(obj, (Pattern, LineType)):
                        self.error = f"'{name}' is not a pattern or LineType."
                        return

                    index = remainder.find("(")
                    if index == -1:
                        self.error = f"Could not parse '{stripped}'."
                        return

                    fn_name = remainder[:index]

                    args_string = remainder[index + 1:-1]
                    args = parse_arguments(args_string)

                    # Check the defined arguments are valid
                    for arg in args:

                        key, value = arg

                        if not self.valid_variable_name(key):
                            self.error = f"Invalid variable name: '{key}'."
                            return

                        if value not in context.variables and value not in ("dict", "list", "set", "tuple", "MatchSet"):
                            self.error = f"'{value}' is not defined."
                            return

                    # Change dictionary values from strings to the corresponding patterns
                    args = tuple(
                        (arg[0], context.variables[arg[1]]) if arg[1] in context.variables else (arg[0], arg[1])
                        for arg in args
                    )

                    if len(args) == 0:
                        args = None

                    # Add the function to the pattern
                    obj.add_function(name=fn_name, tree=self, params=args)

                    self.type = "function"

                    # Don't run sub-trees
                    return

                # Can't parse line
                self.error = f"Could not parse '{stripped}'."
                return

        except Exception as e:
            # Error running the line
            self.error = str(e)
            return

        # Run any sub trees in a copy of context
        sub_context = copy(context)

        # Add the new object if it exists
        if new_object is not None:
            sub_context.current_object = new_object

        # Add new string variables
        sub_context.string_variables.update(new_string_variables)

        for tree in self.sub_trees:
            tree.run(sub_context)

            if tree.error is not None:
                context.error_log.append(f"{tree.line_number!s}: {tree.error}")

        # Add inference rules to formal systems
        if isinstance(new_object, InferenceRule) and isinstance(current_object, FormalSystem):
            current_object.add_inference_rule(new_object)

        # Add line types to formal systems
        if isinstance(new_object, LineType) and isinstance(current_object, FormalSystem):
            current_object.add_line_type(new_object)

        # Add definitions to parent context
        context.definitions = sub_context.definitions

        # Add context to formal systems
        if self.type == "FormalSystem":
            new_object.context.variables.update(sub_context.variables)

            # Add in the default definitions
            for defn in context.definitions:

                # Make a copy of context
                context_copy = copy(new_object.context)

                # Add variables
                context_copy.string_variables.update(defn["variables"])

                # Get the definition
                result = defn["pattern"].add_definition(defn["lower"], defn["higher"], context_copy, defn["condition_string"])

                if result is not None:
                    new_object.context.definitions.add(result)

            # Set the formal system build context and build the pattern dictionary
            new_object.build_context = sub_context
            new_object.build_pattern_dictionary()

        return context

    def run_function(self, item, context, params=None, param_types=None):
        # Run a function for a given match or proof line. For 'function' type trees

        if not self.type == "function":
            raise Exception("Cannot run function on non-function trees.")

        if params is None:
            params = {}

        if param_types is None:
            param_types = ()

        # Update the context reference object
        context = copy(context)
        context.reference_object = item

        # Check the number of parameters is correct
        if not len(params) == len(param_types):
            raise Exception(f"Expected {len(param_types)!s} arguments, but {len(params)!s} were given.")

        # Check the parameters are of the right type
        param_type_dict = {param[0]: param[1] for param in param_types}

        for key, value in params.items():
            if key not in param_type_dict:
                raise Exception(f"Unexpected argument '{key}'.")

            param_type = param_type_dict[key]

            if isinstance(value, Match):
                if not value.pattern.equivalent(param_type, context):
                    raise Exception("Incorrect argument type.")

            elif isinstance(value, MatchSet) and param_type == "MatchSet":
                pass

            elif isinstance(value, ProofLine):
                if not value.line_type.equivalent(param_type, context):
                    raise Exception("Incorrect argument type.")

            elif isinstance(value, dict) and param_type == "dict":
                pass
            elif isinstance(value, set) and param_type == "set":
                pass
            elif isinstance(value, list) and param_type == "list":
                pass
            elif isinstance(value, tuple) and param_type == "tuple":
                pass

            else:
                raise Exception("Invalid parameter.")

        # Otherwise ok

        # Update variables with any parameters (e.g. 'alpha' as formula)
        context.variables.update(params)

        for tree in self.sub_trees:
            result = tree.run_function_line(item, context)

            if result is not None:
                return result["return"]

    def run_function_line(self, item, context):
        # Run a line in a function for a given match or proof line

        stripped = self.line.strip()

        if len(stripped) == 0 or stripped[0] == "#":
            # Nothing to do
            return None

        if stripped.startswith("return "):
            remainder = stripped[7:]
            return {"return": self.evaluate_line_part(item, remainder, context)}

        if stripped.startswith("if ") and stripped[-1] == ":":
            # If
            condition_string = stripped[3:-1]

            if self.evaluate_line_part(item, condition_string, context):
                # Positive branch

                for tree in self.sub_trees:
                    result = tree.run_function_line(item, context)

                    if result is not None:
                        return result

            else:
                # Negative branch
                pass

            return None

        if stripped.startswith("for ") and stripped[-1] == ":":
            # Looks like a loop
            index = stripped.find(" in ")
            if index == -1:
                raise Exception(f"Could not parse function line '{stripped}.")

            var_name = stripped[4:index]
            set_string = stripped[index + 4:-1]

            try:
                set_value = item.get_by_path(set_string, context)

                if not isinstance(set_value, (list, tuple, set, MatchSet, dict)):
                    raise ValueError(f"Set value {set_string} is not iterable.")

                if isinstance(set_value, MatchSet):
                    if not set_value.complete:
                        # Can't iterate over an incomplete set
                        raise Exception("Could not parse function line '" + stripped + "'." +
                                        " Can't iterate over an incomplete set")

                    iterable = set_value.instances

                else:
                    iterable = set_value

                break_flag = False

                for obj in iterable:
                    # Add the object to context
                    context.variables[var_name] = obj

                    for sub_tree in self.sub_trees:

                        result = sub_tree.run_function_line(item, context)

                        if result is not None:
                            if "loop" in result:
                                command = result["loop"]

                                if command == "break":
                                    break_flag = True
                                    break

                                elif command == "continue":
                                    # Go to the next object
                                    break

                            else:
                                # Otherwise, return value
                                return result

                    if break_flag:
                        break

                # No return value
                return None

            except Exception as e:
                raise Exception(f"Could not parse function line '{stripped}'. {e!s}.")

        if stripped.startswith("while ") and stripped[-1] == ":":
            # Looks like a while loop

            condition_string = stripped[6:-1]
            condition = Condition(string=condition_string)

            while item.check_condition(condition, context):
                # Evaluate the sub trees

                break_flag = False
                for sub_tree in self.sub_trees:

                    result = sub_tree.run_function_line(item, context)

                    if result is not None:
                        if "loop" in result:
                            command = result["loop"]

                            if command == "break":
                                break_flag = True
                                break

                            elif command == "continue":
                                # Go to the next iteration
                                break

                        else:
                            # Otherwise, return value
                            return result

                if break_flag:
                    break

            # No return value
            return None

        if stripped.startswith("print(") and stripped[-1] == ")":
            # Print a value
            inner = stripped[6:-1]
            print(self.evaluate_line_part(item, inner, context))
            return None

        if " = " in stripped:
            # Assignment to a variable in context
            index = stripped.index(" = ")
            var_name = stripped[:index]
            value_string = stripped[index + 3:]

            value = self.evaluate_line_part(item, value_string, context)
            context.variables[var_name] = value

            return None

        if stripped in ("continue", "break"):
            # Loop keywords
            return {"loop": stripped}

        # Try just evaluating the line as a part
        try:
            self.evaluate_line_part(item, stripped, context)
            return None
        except Exception:
            pass

        # Otherwise stuck
        raise Exception(f"Could not parse '{stripped}'.")

    def evaluate_line_part(self, item, line, context):
        # Evaluate part of this line, which may utilise subtrees. Gets a value.

        stripped = line.strip()

        if ".each(" in stripped and stripped.endswith("):"):
            # Looks like an each function

            # First need an iterable
            index = stripped.index(".each(")
            path = stripped[:index]

            obj = item.get_by_path(path, context)

            if type(obj) is MatchSet:
                items = obj.instances

                if not obj.complete:
                    # Can't iterate over incomplete match set - assume False
                    return False

            elif isinstance(obj, (list, tuple, set)):
                # Normal iterable object
                items = obj

            else:
                raise Exception(f"Cannot iterate over '{type(obj)!s}.")

            # Get the parameter named for the loop
            name = stripped[index + 6:-2]

            # Loop through the match set
            for i in items:

                # Add this match to context
                context.variables[name] = i

                result = None

                # Run sub-trees
                for sub_tree in self.sub_trees:
                    result = sub_tree.evaluate_line_part(item, sub_tree.line.strip(), context)

                if not result:
                    # This instance fails
                    return False

            # All instances pass the condition
            return True

        if stripped == "None":
            return None

        c = constant(stripped)
        if c is not None:
            return c

        if stripped[0] == "[":
            # Maybe it's a list

            # Search for top-level commas or closing bracket
            entries = []
            entry_start_index = 1
            depth = 0
            is_string = False
            string_delimiter = None
            found_end = False
            remainder = ""

            for index in range(1, len(stripped)):
                char = stripped[index]

                if is_string and char == string_delimiter:
                    # End string
                    is_string = False
                    depth -= 1
                    continue

                if is_string:
                    # Not ending our string
                    continue

                if char == "'" or char == '"':
                    # Starting a string
                    is_string = True
                    string_delimiter = char
                    depth += 1
                    continue

                if char == "," and depth == 0:
                    # Zero-depth comma - add the entry
                    entries.append(stripped[entry_start_index:index].strip())
                    entry_start_index = index + 1
                    continue

                if char == "]" and depth == 0:
                    # This is the end
                    found_end = True
                    entries.append(stripped[entry_start_index:index].strip())
                    remainder = stripped[index + 1:]
                    break

                if char in ("[", "(", "{"):
                    depth += 1
                    continue

                if char in ("]", ")", "}"):
                    depth -= 1
                    continue

            if not found_end or len(remainder) > 0:
                # Currently don't support list indexing, ie ["x", "y"][0]
                raise Exception(f"Could not parse '{stripped}'.")

            return [self.evaluate_line_part(item, entry, context) for entry in entries]

        # It may be a calculation
        if " + " in stripped:
            try:
                parts = stripped.split(" + ")

                if len(parts) >= 2:
                    evaluated_parts = [self.evaluate_line_part(item, part, context) for part in parts]

                    result = evaluated_parts[0]
                    for part in evaluated_parts[1:]:
                        result = result + part

                    return result

            except Exception:
                pass

        # Try to get by path
        try:
            return item.get_by_path(stripped, context)
        except Exception:
            pass

        if stripped[-1] == "]":
            # Maybe ends with an index
            i = stripped.rfind("[")

            if i > -1:
                key = self.evaluate_line_part(item, stripped[i + 1:-1], context)
                initial = self.evaluate_line_part(item, stripped[:i], context)

                try:
                    return initial[key]
                except Exception:
                    pass

        # Try making a condition
        try:
            c = Condition(string=stripped)
            return item.check_condition(c, context)

        except Exception:
            pass

        raise Exception(f"Could not parse '{stripped}'.")

    @staticmethod
    def valid_variable_name(var):
        # Check if var is a valid variable name
        return var.isidentifier() and var not in {
            "FormalSystem",
            "Abstract",
            "Pattern"
        }

    def __str__(self):
        if self.is_root():
            return "Tree root"

        return f"{self.line_number!s}: {self.line}"
