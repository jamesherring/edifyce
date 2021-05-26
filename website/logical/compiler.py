from website.logical.matching import *
from website.logical.formal_system import FormalSystem, LineType, InferenceRule
from copy import copy


def compile(code):
    # Compile the given code string into a tree. Return the formal system

    # Create a root node
    root = AbstractSyntaxTree()
    root.add_lines(code.split("\n"))

    context = root.run()

    # Return the formal system
    for item in context.variables.values():
        if type(item) is FormalSystem:
            return item

    raise Exception("No formal system defined.")


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

            parts[i] = parts[i] + ", " + parts[i + 1]
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

                parts[i] = parts[i] + ", " + parts[i + 1]
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


class Context(object):

    def __init__(self):

        # Variables in the code
        self.variables = {
            # Include system condition by default
            "_system_condition_": SystemConditionPattern(name="System Condition")
        }

        # String variables for inside patterns
        self.string_variables = dict()

        # Stack of objects at a point in the code
        self.current_object_stack = []

        # Proof context
        self.proof_context = dict()

        # Formatting context
        self.pre_format = dict()

    def current_object(self):
        if len(self.current_object_stack) == 0:
            return None

        return self.current_object_stack[-1]

    def __copy__(self):
        new_context = Context()

        new_context.variables = copy(self.variables)
        new_context.string_variables = copy(self.string_variables)
        new_context.current_object_stack = copy(self.current_object_stack)
        new_context.proof_context = copy(self.proof_context)
        new_context.pre_format = copy(self.pre_format)

        return new_context


class AbstractSyntaxTree(object):
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
            context = Context()

        # print(len(context.pre_format), self.line)

        if self.is_root():
            # Just run the sub trees

            for tree in self.sub_trees:
                tree.run(context)

            return context

        # Otherwise, check what kind of line this is

        # Remove spaces
        stripped = self.line.strip()

        current_object = context.current_object()

        # New data to add to inner context
        new_object = None
        new_string_variables = dict()

        try:

            if stripped[0] == "#":
                # This is a comment - no need to do anything
                return

            if stripped[:13] == "FormalSystem " and stripped[-1] == ":":
                # Looks like a formal system declaration

                self.type = "FormalSystem"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Add the formal system to context
                fs = FormalSystem(name=name)
                context.variables[name] = fs

                new_object = fs

            elif stripped == "ProofContext:":
                # Proof context definition
                self.type = "ProofContext"
                new_object = current_object.proof_context

            elif stripped[:7] == "Format " and stripped[-1] == ":":
                # Create a format dictionary
                self.type = "Format"

                name = stripped[7:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Create a new dictionary to keep the format
                new_object = dict()

                context.variables[name] = new_object

            elif stripped[:7] == "Format ":
                # Apply a format dictionary

                name = stripped[7:]

                if name not in context.variables:
                    raise Exception("Could not find format dictionary '" + name + "'.")

                pre_format = context.variables[name]

                if type(current_object) is FormalSystem:
                    current_object.pre_format = pre_format

                # Update context formatting, which is used for patterns, string variables, etc.
                context.pre_format.update(pre_format)

            elif stripped[:9] == "Abstract ":
                # Create an abstract pattern variable

                self.type = "Abstract"

                names = stripped[9:].split(", ")

                for name in names:
                    if not self.valid_variable_name(name):
                        self.error = "Invalid variable name: '" + name + "'."
                        return

                    # Add to context
                    context.variables[name] = AbstractPattern(name=name)

            elif stripped[:6] == "Regex " and stripped[-1] == ":":
                # Create a regex pattern variable

                self.type = "Regex"

                name = stripped[6:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Add to context with placeholder pattern
                pattern = RegexPattern(name=name, pattern="")
                context.variables[name] = pattern

                new_object = pattern

            elif stripped[:8] == "Pattern " and stripped[-1] == ":":
                # String pattern

                self.type = "Pattern"

                name = stripped[8:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Create the pattern
                pattern = StringPattern(name=name, pattern="", pre_format=context.pre_format)
                context.variables[name] = pattern

                new_object = pattern

            elif stripped[:13] == "UnionPattern " and stripped[-1] == ":":
                # Union pattern

                self.type = "UnionPattern"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Create the union with no patterns to begin with
                union = UnionPattern(name=name, patterns=[], pre_format=context.pre_format)
                context.variables[name] = union

                new_object = union

            elif stripped[:9] == "LineType " and stripped[-1] == ":":
                # New linetype

                self.type = "LineType"

                name = stripped[9:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Create the linetype
                new_object = LineType(name=name)

                # Add to formal system
                if type(current_object) is not FormalSystem:
                    raise Exception("Cannot add LineType to object of type " + str(type(current_object)) + ".")

                current_object.line_types.append(new_object)

            elif stripped[:14] == "InferenceRule " and stripped[-1] == ":":
                # New InferenceRule

                self.type = "InferenceRule"

                name = stripped[14:-1]

                if not self.valid_variable_name(name):
                    self.error = "Invalid variable name: '" + name + "'."
                    return

                # Create the rule
                new_object = InferenceRule(name=name)

                # Add to the formal system
                if type(current_object) is not FormalSystem:
                    raise Exception("Cannot add inference rule to object of type '" + str(type(current_object)) + "'.")

                current_object.inference_rules.append(new_object)

            elif stripped[:5] == "with " and stripped[-1] == ":":
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
                            self.error = "Could not find pattern with name '" + reference + "'."
                            return

                        pattern = context.variables[reference]

                        if not isinstance(pattern, Pattern):
                            self.error = "'" + reference + "' is not a pattern."
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
                    self.error = "Can't add object of type '" + str(type(obj)) + "' to UnionPattern."
                    return

                # Append the pattern
                current_object.patterns.append(obj)

            elif stripped[-1] == ":" and stripped[:-1] in context.variables:
                # Continue definition of an already defined pattern

                self.type = "PatternContinuation"

                pattern = context.variables[stripped[:-1]]

                if type(pattern) is not UnionPattern:
                    self.error = "Can't start a block with '" + stripped + "'."
                    return

                new_object = pattern

            elif stripped[-15:] == ".add_variables:":
                self.type = "add_variables"

                # Get the pattern
                name = stripped[:-15]

                if name not in context.variables:
                    raise Exception("Could not find pattern '" + name + ".")

                # Pattern is a StringPattern or UnionPattern instance
                pattern = context.variables[name]

                # Construct a dictionary of variables to add
                variable_dict = dict()
                for sub_tree in self.sub_trees:
                    s = sub_tree.line.strip()
                    if len(s) == 0 or s[0] == "#":
                        continue

                    index = s.find(":")

                    if index == -1:
                        raise Exception("Could not parse line '" + stripped + "'.")

                    name = s[:index]
                    value = s[index + 2:]

                    if value not in context.variables:
                        raise Exception("Could not find pattern: '" + value + "'.")

                    variable_dict[name] = context.variables[value]

                pattern.add_variables(variable_dict)

                return

            elif stripped[-8:] == ".format:":
                # Add format dictionary to pattern

                name = stripped[:-8]

                if name not in context.variables:
                    raise Exception("Could not find pattern '" + name + ".")

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
                        format_dict = dict()
                        continue

                    if s in context.variables and type(context.variables[s]) is dict:
                        # This is a formatting dictionary
                        format_dict.update(context.variables[s])
                        continue

                    index = s.find(":")

                    if index == -1:
                        raise Exception("Could not parse line '" + stripped + "'.")

                    key = s[:index]
                    value = s[index + 2:]

                    format_dict[key] = value

                pattern.set_pre_format(format_dict)
                return

            elif self.parent.type == "ProofContext":
                # Add the item to proof context

                index = stripped.find(": ")

                if index == -1:
                    raise Exception("Could not parse line '" + stripped + "'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if value_string == "set()":
                    current_object[key] = set()

                elif value_string == "MatchSet()":
                    current_object[key] = MatchSet()

                elif value_string == "dict()":
                    current_object[key] = dict()

                else:
                    raise Exception("Could not parse value '" + value_string + "'.")

            elif type(current_object) is StringPattern:
                # Define the pattern
                current_object.set_pattern(stripped)

                # Apply string variables
                current_object.add_variables(context.string_variables)

            elif type(current_object) is UnionPattern:
                # Add a pattern to the union

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
                    raise Exception("Could not parse line '" + stripped + "'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if key == "pattern":

                    # Get the value
                    assert value_string in context.variables

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
                            raise Exception("Could not parse context key '" + key + "'.")

                        sub_key = key[index + 1:]

                        if sub_key not in current_object.add_context:
                            current_object.add_context[sub_key] = dict()

                        new_object = current_object.add_context[sub_key]

                else:
                    raise Exception("Unrecognised parameter for LineType '" + key + "'.")

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
                        raise Exception("Could not parse label for '" + current_object.name + "'.")

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

                elif stripped == "format:":
                    # Create a format dictionary

                    new_object = dict()

                    if current_object.deduction is not None:
                        current_object.deduction.pre_format = new_object

                    for ant in current_object.antecedents:
                        ant.pre_format = new_object

            elif type(current_object) is dict:
                # Add a key value pair to the dictionary

                index = stripped.find(":")

                if index == -1:
                    # Item can be reference to already defined dictionary
                    if stripped in context.variables and type(context.variables[stripped]) is dict:
                        current_object.update(context.variables[stripped])

                    else:
                        raise Exception("Could not parse line '" + stripped + "'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

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
                        self.error = "Unrecognised pattern '" + name + "'."
                        return

                    pattern = context.variables[name]

                    if type(pattern) not in (UnionPattern, StringPattern, RegexPattern, AbstractPattern):
                        self.error = "'" + name + "' is not a pattern."
                        return

                    index = remainder.find("(")
                    if index == -1:
                        self.error = "Could not parse '" + stripped + "'."
                        return

                    fn_name = remainder[:index]

                    args_string = remainder[index + 1:-1]
                    args = parse_arguments(args_string)

                    # Check the defined arguments are valid
                    for arg in args:

                        key, value = arg

                        if not self.valid_variable_name(key):
                            self.error = "Invalid variable name: '" + key + "'."
                            return

                        if value not in context.variables:
                            self.error = "'" + value + "' is not defined."
                            return

                    # Change dictionary values from strings to the corresponding patterns
                    args = tuple((arg[0], context.variables[arg[1]]) for arg in args)

                    if len(args) == 0:
                        args = None

                    # Add the function to the pattern
                    pattern.add_function(name=fn_name, tree=self, params=args)

                    self.type = "function"

                    # Don't run sub-trees
                    return

                # Can't parse line
                self.error = "Could not parse '" + stripped + "'."
                return

        except Exception as e:
            # Error running the line
            self.error = str(e)
            return

        # Run any sub trees in a copy of context
        sub_context = copy(context)

        # Add the new object if it exists
        if new_object is not None:
            sub_context.current_object_stack.append(new_object)

        # Add new string variables
        sub_context.string_variables.update(new_string_variables)

        for tree in self.sub_trees:
            tree.run(sub_context)

            if tree.error is not None:
                print(str(tree.line_number) + ": " + tree.error)

        # Add context to formal systems
        if self.type == "FormalSystem":
            proof_context = new_object.proof_context

            if "string_variables" not in proof_context:
                proof_context["string_variables"] = dict()

            if "variables" not in proof_context:
                proof_context["variables"] = dict()

            proof_context["variables"].update(sub_context.variables)

        return context

    def run_function(self, match, context, params=None):
        # Run a function for a given match. For 'function' type trees

        if not self.type == "function":
            raise Exception("Cannot run function on non-function trees.")

        # Update context variables with any parameters
        if params is not None:
            context["variables"].update(params)

        result = None

        for tree in self.sub_trees:
            next_result = tree.run_function_line(match, context)

            if next_result is not None:
                # Update the result
                result = next_result

        return result

    def run_function_line(self, match, context):
        # Run a line in a function for a given match

        stripped = self.line.strip()

        if len(stripped) == 0 or stripped[0] == "#":
            # Nothing to do
            return None

        if stripped[:10] == "instances(" and stripped[-1] == ")":
            # Instances
            return match.get_by_path(stripped, context)

        elif ".each(" in stripped and stripped[-1] == ":":
            # Looks like an each function

            # First need a match set
            index = stripped.index(".each(")
            path = stripped[:index]

            match_set = match.get_by_path(path, context)

            if not match_set.complete:
                # Can't iterate over incomplete match set
                return False

            # Get the parameter named for the loop
            name = stripped[index + 6:-2]

            # Create a copy of context
            context_copy = copy(context)

            # Loop through the match set
            for m in match_set.instances:

                # Add this match to context
                context_copy.variables[name] = m

                result = None

                # Run sub-trees
                for sub_tree in self.sub_trees:
                    result = sub_tree.run_function_line(match, context_copy)

                if not result:
                    # This instance fails
                    return False

            # All instances pass the condition
            return True

        else:
            # Assume it's a condition
            c = Condition(string=stripped)
            return match.check_condition(c, context)

    @staticmethod
    def valid_variable_name(var):
        # Check if var is a valid variable name

        blacklist = [
            "FormalSystem",
            "Abstract",
            "Pattern"
        ]

        return var.isidentifier() and var not in blacklist

    def __str__(self):
        if self.is_root():
            return "Tree root"

        return str(self.line_number) + ": " + self.line


if __name__ == "__main__":

    # Parse the system
    with open("formal_systems/b6cef3e4/predicate.txt") as f:
        predicate = compile(f.read())

    vars = predicate.proof_context["variables"]

    formula = vars["formula"]
    atomic = vars["atomic_formula"]
    equal = vars["equal"]
    variable = vars["variable"]
    term = vars["term"]

    c = {
        "string_variables": {},
        "variables": {},
        "restrictions": {}
    }

    logical = vars["logical_pattern"]

    print(logical)

    c["string_variables"].update({
        "A": formula,
        "B": formula
    })

    print(logical.match("((neg B rightarrow neg A) rightarrow (A rightarrow B)) ref{A3} label{X}", c))



