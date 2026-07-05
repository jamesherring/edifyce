"""The :class:`LineType` describing a category of proof line."""

from ..matching import PatternFunction


class LineType:
    """Class for types of lines in formal proofs."""

    def __init__(self, name, pattern=None, behaviour="none", add_context=None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match (Pattern instance)
        self.pattern = pattern

        # The behaviour of these lines
        self.behaviour = behaviour
        if self.behaviour not in ("none", "import", "logical", "axiom", "indent", "definition", "comment"):
            raise ValueError(f"'{self.behaviour}' is not a valid LineType behaviour.")

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
        self.functions[name] = PatternFunction(tree=tree, params=() if params is None else params)

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
