import regex as re
from copy import copy


def parse_path(path):
    # Parse a path string to get the initial (and remainder if applicable)

    if "." not in path:
        # No dots
        return path, None

    # Otherwise, dots in path. Get the first part with consistent brackets
    depth = 0
    for i in range(0, len(path)):
        if path[i] == "(":
            depth += 1
        elif path[i] == ")":
            depth -= 1

        if depth == 0 and path[i] == ".":
            return path[:i], path[i + 1:]

    # There are dots - but inside brackets
    return path, None


def parse_arguments(args_string, obj, context, arg_names=None):
    # Parse arguments from a string and get them by path.

    # Optionally specify a list arg_names to force the arguments into just kwargs

    # Target args and kwargs
    args = []
    kwargs = {}

    depth = 0
    start_index = 0
    keyword = None
    for i in range(0, len(args_string)):
        char = args_string[i]

        if char == "(":
            depth += 1
            continue

        if char == ")":
            depth -= 1

        if char == "=" and depth == 0:
            # keyword argument
            keyword = args_string[start_index:i].strip()
            start_index = i + 1
            continue

        if char == "," and depth == 0:
            # Top-level comma of an argument

            value = get_by_path(obj, args_string[start_index:i].strip(), context)

            if keyword is None:
                args.append(value)
            else:
                kwargs[keyword] = value
                keyword = None

            start_index = i + 1

    # Append the final argument
    value = get_by_path(obj, args_string[start_index:].strip(), context)

    if keyword is None:
        args.append(value)
    else:
        kwargs[keyword] = value

    if arg_names is None:
        # Simple case
        return args, kwargs

    # Otherwise, we have specified arg names

    arg_count = len(args) + len(kwargs)

    if arg_count > len(arg_names):
        raise Exception("Mismatched number of arguments given.")

    for key in kwargs.keys():
        if key not in arg_names[len(args):]:
            raise Exception("Unexpected argument: '" + key + "'.")

    # Otherwise, kwargs match.

    # Add the args to kwargs
    for arg, arg_name in zip(args, arg_names[:len(args)]):
        kwargs[arg_name] = arg

    # Add any missing arguments as None
    for arg in arg_names:
        if arg not in kwargs:
            kwargs[args] = None

    # Return no args, all kwargs
    return [], kwargs


def get_by_path(obj, path, context, recurse=True):
    # General function to get an object by a path.

    if context.reference_object is None and obj is not None:
        context = copy(context)
        context.reference_object = obj

    initial, remainder = parse_path(path)

    if remainder:
        # Chain the parts
        initial = get_by_path(obj, initial, context)
        return get_by_path(initial, remainder, context)

    # Check for keywords
    if initial == "True":
        return True

    if initial == "False":
        return False

    if initial == "set()":
        return set()

    # Otherwise, only one part
    if hasattr(obj, "get_by_path") and recurse:
        # Try the obj get_by_path first
        try:
            return obj.get_by_path(path, context)
        except Exception as e:
            pass

    if path in context.variables:
        return context.variables[path]

    if context.mapping is None:
        # Can try string variables

        if path in context.string_variable_matches:
            return context.string_variable_matches[path]

        if path in context.string_variables:
            return context.string_variables[path]

    else:

        # Context mapping exists
        if path in context.mapping:
            # Get the mapped path

            mapped_path = context.mapping[path]
            if type(mapped_path) is Match:
                return mapped_path

            if mapped_path in context.string_variable_matches:
                return context.string_variable_matches[mapped_path]

            if mapped_path in context.string_variables:
                return context.string_variables[path]

    if path in context.logical:
        return context.logical[path]

    if "[" in path and path[-1] == "]":
        # Looks like list lookup
        index = path.index("[")
        initial = path[:index]
        i = int(path[index + 1:-1])
        return get_by_path(obj, initial, context)[i]

    if path[:4] == "set(" and path[-1] == ")":
        # Make a new set
        inner = path[4:-1]
        return MatchSet(instances={get_by_path(obj, inner, context)})

    if type(obj) is set:
        # obj is a set - need to perform a set operation

        name = initial
        args = []
        kwargs = {}

        if "(" in initial and initial[-1] == ")":
            index = initial.index("(")
            name = initial[:index]
            args_string = initial[index + 1:-1]

            args, kwargs = parse_arguments(args_string, obj, context)

        if hasattr(obj, name):
            fn = getattr(obj, name)
            return fn(*args, **kwargs)

    if path == "self" and context.reference_object is not None:
        return context.reference_object

    if recurse and context.reference_object is not None and hasattr(context.reference_object, "get_by_path"):
        # Try the reference object
        return context.reference_object.get_by_path(path, context)

    raise Exception("Could not find value from path '" + path + "'.")


def path_maps_to(path, other_path, context, other_context, mapping):
    # Check if this path maps to the other path under the given mapping

    initial, remainder = parse_path(path)
    other_initial, other_remainder = parse_path(other_path)

    # Remainders have to both be None or both not None
    if (remainder is None and other_remainder is not None) or (remainder is not None and other_remainder is None):
        return False

    # Check function arguments
    if "(" in initial and initial[-1] == ")":
        index = initial.index("(")
        inner = initial[index + 1:-1]
        args = inner.split(", ")

        if "(" in other_initial and other_initial[-1] == ")":
            other_index = other_initial.index("(")
            other_inner = other_initial[other_index + 1:-1]
            other_args = other_inner.split(", ")

            if not len(args) == len(other_args):
                return False

            for a, b in zip(args, other_args):
                result = path_maps_to(a, b, context, other_context, mapping)

                if not result:
                    return False

            return True

    # Initials have to match or map
    if not initial == other_initial:

        if initial in mapping:
            # Already mapped
            return mapping[initial].string == other_initial

        if initial not in context.string_variables or other_initial not in other_context.string_variables:
            # Variables not present
            return False

        initial_pattern = context.string_variables[initial]
        other_initial_pattern = other_context.string_variables[other_initial]

        if not initial_pattern.equivalent(other_initial_pattern, context):
            # Variables not of the same pattern
            return False

        # Success
        mapping[initial] = Match(string=other_initial, pattern=other_initial_pattern, is_variable=True)

    # Remainders have to match
    if remainder is None:
        # Both remainders are None
        return True

    # Both remainders are not None
    return path_maps_to(remainder, other_remainder, context, other_context, mapping)


class Context(object):

    def __init__(self, variables=None, string_variables=None, string_variable_matches=None, definitions=None,
                 logical=None, reference_object=None, mapping=None):

        self.variables = variables if variables is not None else dict()
        self.string_variables = string_variables if string_variables is not None else dict()

        # Simple matches for string variables.
        self.string_variable_matches = string_variable_matches if string_variable_matches is not None else dict()

        # Definitions
        self.definitions = definitions if definitions is not None else []

        # Logical context for inside proofs
        self.logical = logical if logical is not None else dict()

        # Reference object
        self.reference_object = reference_object

        # Mapping on string variables - string: string dictionary
        self.mapping = mapping

    def set_string_variable_matches(self):
        # Set string variable matches
        for var, pattern in self.string_variables.items():
            self.string_variable_matches[var] = Match(pattern=pattern, string=var, is_variable=True)

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False
        memo[(self, other)] = False

        if type(other) is not Context:
            return False

        if not len(self.variables) == len(other.variables):
            return False

        if not len(self.string_variables) == len(other.string_variables):
            return False

        if not len(self.string_variable_matches) == len(other.string_variable_matches):
            return False

        if not len(self.definitions) == len(other.definitions):
            return False

        if not len(self.logical) == len(other.logical):
            return False

        if not self.mapping == other.mapping:
            return False

        # Assume True for recursive checks
        memo[(self, other)] = True

        if not self.reference_object.equivalent(other.reference_object, context, memo):
            memo[(self, other)] = False
            return False

        for key in self.variables:
            if key not in other.variables:
                memo[(self, other)] = False
                return False

            if not self.variables[key].equivalent(other.variables[key], context, memo):
                memo[(self, other)] = False
                return False

        for key in self.string_variables:
            if key not in other.string_variables:
                memo[(self, other)] = False
                return False

            if not self.string_variables[key].equivalent(other.string_variables[key], context, memo):
                memo[(self, other)] = False
                return False

        for key in self.string_variable_matches:
            if key not in other.string_variable_matches:
                memo[(self, other)] = False
                return False

            if not self.string_variable_matches[key].equivalent(other.string_variable_matches[key], context, memo):
                memo[(self, other)] = False
                return False

        for self_def, other_def in zip(self.definitions, other.definitions):
            if not self_def.equivalent(other_def, context, memo):
                memo[(self, other)] = False
                return False

        for key in self.logical:
            if key not in other.logical:
                memo[(self, other)] = False
                return False

            if not self.logical[key].equivalent(other.logical[key], context, memo):
                memo[(self, other)] = False
                return False

        # Otherwise ok
        return True

    def __copy__(self):
        # Return a copy of the context
        return Context(
            variables=copy(self.variables),
            string_variables=copy(self.string_variables),
            string_variable_matches=copy(self.string_variable_matches),

            definitions=[copy(defn) for defn in self.definitions],

            # Logical is a dict of dicts
            logical={key: copy(self.logical[key]) for key in self.logical},

            reference_object=self.reference_object,
            mapping=copy(self.mapping)
        )


class Condition(object):
    # A condition tree object

    def __init__(self, string, parts=None, context=None):

        # The condition string
        self.string = string

        # The condition type - "brackets", "and", "or", "not", "in", "not in", "is", "is not", "equals", or "atomic"
        self.type = None

        # Optionally specify list of string parts
        self.parts = parts

        # Frozen context to store on the condition
        self.context = copy(context)

        # Any sub conditions
        self.sub_conditions = []

        # Any sub-items (for "in", "not in", or "equals" type)
        self.sub_items = []

        self.parse()

    def parse(self):
        # Parse the string into sub conditions

        if self.string == "":
            # No string given
            self.parts = None
            return

        if self.parts is not None:
            parts = self.parts

        else:
            # First parse into a list of condition parts
            parts = []

            i = 0
            depth = 0
            part_start_index = 0
            while i < len(self.string):

                if self.string[i] == "(":
                    # Open bracket

                    if part_start_index < i and depth == 0:
                        # Add the previous part
                        parts.extend(self.string[part_start_index:i].split(" "))

                    if depth == 0:
                        # Keep track of the part_start_index
                        part_start_index = i

                    depth += 1
                    i += 1
                    continue

                if self.string[i] == ")":
                    # Close bracket
                    depth -= 1

                    if depth < 0:
                        raise Exception("Could not parse condition '" + self.string + "', mismatched parentheses.")

                if depth > 0:
                    # Don't need to parse today
                    i += 1
                    continue

                if self.string[i] == ")":
                    # On a close bracket - add the top level group
                    parts.append(self.string[part_start_index:i + 1])
                    i += 1
                    part_start_index = i
                    continue

                i += 1

            if depth > 0:
                raise Exception("Could not parse condition '" + self.string + "', mismatched parentheses.")

            # Add any trailing part
            if part_start_index < i:
                parts.extend(self.string[part_start_index:].split(" "))

            # Remove any empty parts
            parts = [part for part in parts if len(part) > 0]

            # Add spaces to ==
            for i in range(0, len(parts)):
                if parts[i] == "==":
                    parts[i] = " == "

            self.parts = parts

        # Each part is either bracketed, a keyword (and, or, not, in), or atomic

        # Check for brackets
        if len(parts) == 1 and parts[0][0] == "(" and parts[0][-1] == ")":
            self.type = "brackets"

            inner = parts[0][1:-1]
            self.sub_conditions = [Condition(string=inner, context=self.context)]

            return

        # Check for and, or
        for i in range(0, len(parts)):
            part = parts[i]

            if part in ("and", "or"):
                if i == 0 or i == len(parts) - 1:
                    raise Exception("Could not parse condition '" + self.string + "'.")

                self.type = part

                left = parts[:i]
                right = parts[i + 1:]

                self.sub_conditions = [
                    Condition(string="".join(left), parts=left, context=self.context),
                    Condition(string="".join(right), parts=right, context=self.context)
                ]

                # Done
                return

        # Check for in, not in
        for i in range(0, len(parts)):
            part = parts[i]

            if part == "in":
                if i == 0 or i == len(parts) - 1:
                    raise Exception("Could not parse condition '" + self.string + "'.")

                self.type = "in"

                left = parts[:i]
                right = parts[i + 1:]

                if parts[i - 1] == "not":
                    # Not in
                    self.type = "not in"
                    if i - 1 == 0:
                        raise Exception("Could not parse condition '" + self.string + "'.")

                    left = parts[:i - 1]

                self.sub_items = ["".join(left), "".join(right)]

                # Done
                return

        # Check for is, is not
        for i in range(0, len(parts)):
            part = parts[i]

            if part == "is":
                if i == 0 or i == len(parts) - 1:
                    raise Exception("Could not parse condition '" + self.string + "'.")

                self.type = "is"

                left = parts[:i]
                right = parts[i + 1:]

                if parts[i + 1] == "not":
                    # Not in
                    self.type = "is not"
                    if i + 1 == len(parts) - 1:
                        raise Exception("Could not parse condition '" + self.string + "'.")

                    right = parts[i + 2:]

                self.sub_items = ["".join(left), "".join(right)]

                # Done
                return

        # Check for not
        if parts[0] == "not":
            self.type = "not"

            remainder = parts[1:]
            self.sub_conditions = [Condition(string=self.string[4:], parts=remainder, context=self.context)]

            return

        if " == " in self.string:
            # Equals

            # Check the == doesn't occur inside brackets
            depth = 0
            left = None
            right = None
            for i in range(0, len(self.string)):
                char = self.string[i]

                if char == "(":
                    depth += 1
                    continue

                if char == ")":
                    depth -= 1
                    continue

                if depth == 0 and i + 4 < len(self.string) and self.string[i:i + 4] == " == ":
                    left = self.string[:i].strip()
                    right = self.string[i + 4:].strip()
                    break

            if left is not None and right is not None:
                self.type = "equals"
                self.sub_items = (left, right)
                return

        # Otherwise atomic - can be parsed by the match
        self.type = "atomic"

    def is_atomic(self):
        return self.type in {"in", "not in", "is", "is not", "equals", "atomic"}

    def check_condition(self, obj, context):
        # Check a condition for the given object (if it exists)

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = obj

        # Check the possible condition types
        if self.type == "brackets":
            # Easy case
            return self.sub_conditions[0].check_condition(obj, context)

        if self.type == "and":
            return self.sub_conditions[0].check_condition(obj, context) and \
                   self.sub_conditions[1].check_condition(obj, context)

        if self.type == "or":
            return self.sub_conditions[0].check_condition(obj, context) or \
                   self.sub_conditions[1].check_condition(obj, context)

        if self.type == "not":
            return not self.sub_conditions[0].check_condition(obj, context)

        # Otherwise, an atomic condition

        if self.type in ("in", "not in"):
            # Must be for a match set

            item = get_by_path(obj, self.sub_items[0], context)
            match_set = get_by_path(obj, self.sub_items[1], context)

            result = match_set.contains(item, context)

            if self.type == "in":
                return result

            # Negated
            return not result

        if self.type in ("is", "is not"):
            # Check identically equal

            left = get_by_path(obj, self.sub_items[0], context)
            right = get_by_path(obj, self.sub_items[1], context)

            result = left is right

            if self.type == "is":
                return result

            # Negated
            return not result

        if self.type == "equals":
            # Equals
            left_string, right_string = self.sub_items
            left = get_by_path(obj, left_string, context)
            right = get_by_path(obj, right_string, context)

            if not type(left) == type(right):
                # Mismatched types
                return False

            if type(left) in (Match, MatchSet):
                return left.equivalent(right, context)

            else:
                return left == right

        if obj is None:
            # No context object given. Try to get an object from the first condition part
            return get_by_path(None, self.string, context)

        if hasattr(obj, "get_by_path"):
            return obj.get_by_path(self.string, context)

        raise Exception("Couldn't evaluate condition '" + self.string + "'.")

    def validate(self):
        # See if this is a valid condition with the given context

        # Work with a copy of context
        context_copy = copy(self.context)

        # Set string variable matches
        context_copy.set_string_variable_matches()

        try:
            result = self.check_condition(None, context_copy)
        except Exception as e:
            # Not valid condition
            return False

        if result not in (True, False, None):
            # result needs to be boolean or None (uncertain)
            return False

        # Otherwise ok
        return True

    def maps_to(self, other, mapping):
        # Check if this condition maps to the other one under the string variable mapping

        # Work with copies of self context and other context with string_variable_matches
        self_context = copy(self.context)
        other_context = copy(other.context)

        self_context.set_string_variable_matches()
        other_context.set_string_variable_matches()

        # Must be of the same types
        if not self.type == other.type:
            return False

        if not self.is_atomic():
            # Not atomic - so just need to check sub-conditions
            for sub, other_sub in zip(self.sub_conditions, other.sub_conditions):
                if not sub.maps_to(other_sub, mapping):
                    return False

            return True

        if self.type in ("in", "not in"):
            # Need to check the items and set can be mapped

            item, match_set = [get_by_path(self, i, self_context) for i in self.sub_items]
            other_item, other_match_set = [get_by_path(other, i, other_context) for i in other.sub_items]

            result = match_set.maps_to(other_match_set, self_context, mapping)

            if not result:
                return False

            return item.maps_to(other_item, self_context, mapping)

        if self.type in ("equals", "is", "is not"):
            # need to check the two parts

            left, right = [get_by_path(self, i, self_context) for i in self.sub_items]
            other_left, other_right = [get_by_path(other, i, other_context) for i in other.sub_items]

            result = left.maps_to(other_left, self_context, mapping)

            if not result:
                return False

            return right.maps_to(other_right, self_context, mapping)

        # Otherwise atomic - just need to check the path
        return path_maps_to(self.string, other.string, self_context, other_context, mapping)

    def maps_into_set(self, target_condition_set, mapping):
        # Check if this condition maps into the target set using the given mapping

        for target_condition in target_condition_set:
            if self.maps_to(target_condition, mapping):
                # Maps successfully
                return True

        # No luck
        return False

    def get_by_path(self, path, context, recurse=True):
        # Get the value by a path

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        initial, remainder = parse_path(path)

        if remainder:
            # Use generic get by path
            return get_by_path(self, path, context)

        # Otherwise, only one part
        if path[:14] == "maps_into_set(" and path[-1] == ")":
            inner = path[14:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("target_condition_set", "mapping"))[1]

            return self.maps_into_set(kwargs["target_condition_set"], kwargs["mapping"])

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception("Could not find value from path '" + path + "'.")

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = self.string == other.string
        return self.string == other.string

    def __str__(self):
        return "Condition: " + self.string


class Definition(object):
    # A definition class - linking higher level string patterns with lower level ones

    def __init__(self, lower, higher, pattern, context):

        # The pattern this definition applies to
        self.pattern = pattern

        # Get the match for variables
        match = self.pattern.match(lower, context)
        assert match is not None

        # Create a lower pattern
        self.lower = match.create_pattern(context.string_variables)

        # Create a higher pattern
        self.higher = StringPattern(
            name="Definition (higher)",
            pattern=higher,
            variables=self.lower.variables,
            pre_format=self.pattern.pre_format
        )

        # Store the variables
        self.variables = self.lower.variables

    def match(self, s, context):
        # Check if the definition applies to a string s, of the higher level match

        higher_match = self.higher.match(s, context)

        if higher_match is None:
            return None

        # Success - create a match
        m = Match(
            string=s,
            pattern=self.pattern,
            definition=self
        )

        # Add submatches according to the variables in the higher match
        for key, sub_match in higher_match.sub_matches.items():
            m.add_submatch(key, sub_match.duplicate())

        return m

    def check_application(self, lower, higher, context, mapping=None):
        # Check if this definition defines higher match from lower match. Recursive algorithm.
        # Optionally specify mapping that must be consistent

        if mapping is None:
            mapping = dict()

        if lower.string in mapping and not mapping[lower.string] == higher.string:
            # Inconsistent mapping
            return False

        # if lower.equivalent(higher, context):
        # Vacuously True
        # mapping[lower.string] = higher.string
        # return True

        if (lower.definition is None and higher.definition is None) or \
                (lower.definition is not None and lower.definition.equivalent(higher.definition, context)):
            # Both definitions are the same or both None. No need to unpack, just need to check sub_matches

            if not len(lower.sub_matches) == len(higher.sub_matches):
                return False

            for key, lower_sub in lower.sub_matches.items():
                if key not in higher.sub_matches:
                    return False

                higher_sub = higher.sub_matches[key]

                if not self.check_application(lower_sub, higher_sub, context, mapping):
                    return False

            # Otherwise ok

            if len(lower.sub_matches) == 0:
                mapping[lower.string] = higher.string

            return True

        # Otherwise, lower and higher definitions are different. Need higher to define to lower to be valid
        if higher.definition is None or not higher.definition.equivalent(self, context):
            return False

        # Higher uses this definition.

        # Check if lower matches
        defn_lower_match = self.lower.match(lower.string, context)

        if defn_lower_match is None:
            # Lower doesn't match
            return False

        # Compare the variables
        for key, lower_var in defn_lower_match.sub_matches.items():
            if key not in higher.sub_matches:
                return False

            higher_var = higher.sub_matches[key]

            if not self.check_application(lower=lower_var, higher=higher_var, context=context, mapping=mapping):
                # Variables don't match
                return False

        # Otherwise ok
        return True

    def equivalent(self, other, context, memo=None):
        # Check if two definitions are the same

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, Definition):
            return False

        # Assume True when checking nested patterns - so recursive patterns can compare equal
        memo[(self, other)] = True

        if not self.lower.equivalent(other.lower, context, memo):
            memo[(self, other)] = False
            return False

        if not self.higher.equivalent(other.higher, context, memo):
            memo[(self, other)] = False
            return False

        if not self.pattern.equivalent(other.pattern, context, memo):
            memo[(self, other)] = False
            return False

        # Otherwise ok
        memo[(self, other)] = True
        return True


class Match(object):
    # Match object

    def __init__(self, pattern, string, is_variable=False, definition=None):

        self.pattern = pattern
        self.string = string

        # Is this a variable match?
        self.is_variable = is_variable

        # List of sub matches
        self.sub_matches = dict()

        # The parent match
        self.parent_match = None

        # The definition used
        self.definition = definition

    def add_submatch(self, var, m):
        self.sub_matches[var] = m
        m.parent_match = self

    def get_by_path(self, path, context, recurse=True):
        # Get the value by a path

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        initial, remainder = parse_path(path)

        if remainder:
            # Use generic get by path
            return get_by_path(self, path, context)

        # Otherwise, only one part
        if path == "parent()":
            return self.parent_match

        elif path == "pattern()":
            return self.pattern

        elif len(path) > 2 and path[-2:] == "()" and path[:-2] in self.pattern.functions:
            return self.run_function(path[:-2], context)

        elif "(" in path and path[:path.index("(")] in self.pattern.functions:
            # An attribute function with parameters

            index = path.index("(")
            name = path[:index]

            args_string = path[index + 1:-1]
            args, kwargs = parse_arguments(args_string, self, context)

            return self.run_function(name, context, args=args, kwargs=kwargs)

        elif path in self.sub_matches:
            return self.sub_matches[path]

        elif path == "lookup()":
            # Look up the value in context
            if self.string in context.variables:
                return context.variables[self.string]

            raise Exception("Could not find '" + self.string + "' in context.")

        elif path == "union_submatch()":
            # Get the only submatch
            assert type(self.pattern) is UnionPattern

            return list(self.sub_matches.values())[0]

        elif path.startswith("instances(") and path[-1] == ")":
            # Call for instances

            inner = path[10:-1]
            index = inner.find(";")

            condition_string = None

            if index == -1:
                # No condition
                pattern_name = inner

            else:
                # Pattern with a condition
                pattern_name = inner[:index]
                condition_string = inner[index + 2:]

            pattern_label = None
            if " as " in pattern_name:
                pattern_label, pattern_name = pattern_name.split(" as ")

            if pattern_name not in context.variables:
                raise Exception("Unrecognised pattern '" + pattern_name + "'.")

            pattern = context.variables[pattern_name]

            # Build the condition
            condition = None
            if condition_string is not None:
                condition = Condition(condition_string, context=context)

            return self.instances(pattern, context, condition, label=pattern_label)

        elif path.startswith("shallow_instances(") and path[-1] == ")":
            # Find all shallow instances

            inner = path[18:-1]
            index = inner.find(";")

            condition_string = None

            if index == -1:
                # No condition
                pattern_name = inner

            else:
                # Pattern with a condition
                pattern_name = inner[:index]
                condition_string = inner[index + 2:]

            pattern_label = None
            if " as " in pattern_name:
                pattern_label, pattern_name = pattern_name.split(" as ")

            if pattern_name not in context.variables:
                raise Exception("Unrecognised pattern '" + pattern_name + "'.")

            pattern = context.variables[pattern_name]

            # Build the condition
            condition = None
            if condition_string is not None:
                condition = Condition(condition_string, context=context)

            return self.instances(pattern, context, condition, label=pattern_label, shallow=True)

        elif path.startswith("replace(") and path[-1] == ")":
            # Replace
            inner = path[8:-1]

            # Specify arg_names to get all in kwargs
            kwargs = parse_arguments(inner, self, context, arg_names=("needle", "value", "condition"))[1]
            return self.replace(kwargs["needle"], kwargs["value"], context, kwargs["condition"])

        elif path.startswith("equivalent_with_some_replacements(") and path[-1] == ")":
            inner = path[34:-1]

            # Specify arg_names to get all in kwargs
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "needle", "value"))[1]
            return self.equivalent_with_some_replacements(
                kwargs["other"],
                kwargs["needle"],
                kwargs["value"],
                context
            )

        elif path == "string()":
            return self.string

        elif path == "condition()":
            return Condition(string=self.string, context=context)

        elif path.startswith("maps_to(") and path[-1] == ")":
            inner = path[8:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "mapping"))[1]
            return self.maps_to(kwargs["other"], context, kwargs["mapping"])

        else:
            condition_fns = ["has_parent", "equal_any"]

            for cf in condition_fns:
                if path[:len(cf)] == cf:
                    # Looks like a condition
                    condition = Condition(path, context=context)
                    return self.check_condition(condition, context)

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception("Could not find value from path '" + path + "'.")

    def check_condition(self, c, context):
        # Check a condition c - returns true or false

        # Add the top-most match to context in a copy
        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        # Check the possible condition types
        if not c.type == "atomic":
            # Composite case
            return c.check_condition(self, context)

        # Otherwise, atomic condition
        if c.string[:11] == "has_parent(":
            # Has parent of the given pattern

            inner = c.string[11:-1]
            index = inner.find(";")

            sub_condition_string = None
            if index == -1:
                # No sub condition
                pattern_string = inner

            else:
                # There is a sub condition
                pattern_string = inner[:index]
                sub_condition_string = inner[index + 2:]

            condition = None if sub_condition_string is None else Condition(sub_condition_string, context=context)

            # Get the pattern label and name
            pattern_label, pattern_name = pattern_string.split(" as ")

            if pattern_name not in context.variables:
                raise Exception("Could not find pattern '" + pattern_string + "'.")

            # Get the pattern
            pattern = context.variables[pattern_name]

            return self.has_parent(pattern, condition, copy(context), label=pattern_label)

        elif c.string[:10] == "equal_any(":
            # Check if a value is equal to any of a matchset

            inner = c.string[10:-1]
            match_set = self.get_by_path(inner, context)

            return self.equal_any(match_set, context)

        else:
            # Get by path
            return self.get_by_path(c.string, context)

    def run_function(self, name, context, args=None, kwargs=None):
        # Run a custom function with the given name, args and kwargs

        fn = self.pattern.get_function(name)

        if fn is None:
            raise Exception("'" + self.pattern.name + "' does not have function '" + name + "'.")

        # Check the params matches have the correct pattern
        if args is None:
            args = []

        if kwargs is None:
            kwargs = {}

        arg_count = len(args) + len(kwargs)
        if not arg_count == len(fn["params"]):
            # Wrong number of parameters provided
            raise Exception("'" + name + "' expected " + str(len(fn["params"])) + " argument(s), " + str(arg_count) +
                            " provided.")

        # Build a parameter mapping
        param_mapping = dict()

        # Check args
        for given, fn_param in zip(args, fn["params"][:len(args)]):
            param_mapping[fn_param[0]] = given

        # kwargs don't have to be in order
        remaining_fn_params = fn["params"][len(args):]
        remaining_fn_param_dict = {param[0]: param[1] for param in remaining_fn_params}

        # Check kwargs
        for given_name, given in kwargs.items():
            if given_name not in remaining_fn_param_dict:
                raise Exception("'" + name + "' does not accept parameter '" + given_name + ".")

            param_mapping[given_name] = given

        # Create a copy of context
        context_copy = copy(context)

        # Run the tree as a function
        tree = fn["tree"]
        return tree.run_function(item=self, context=context_copy, params=param_mapping, param_types=fn["params"])

    def instances(self, pattern, context, condition=None, attribute_name=None, shallow=False, label=None):
        # Get instances of the pattern in nested sub matches, which meet the specified condition.
        # Optionally specify the attribute we are searching for

        # Optionally specify a label to add matched instances to context - useful for referencing in conditions

        # If shallow - don't look for nested instances of pattern deeper than instances found
        if type(pattern) is str:
            # Need to get the correct pattern
            pattern = context.variables[pattern]

        # If incomplete, it's a variable pattern, that may contain an instance of the needle pattern
        complete = not (self.string in context.string_variables and self.pattern.may_contain(pattern))

        # Create a new MatchSet
        match_set = MatchSet(complete=complete)

        if not match_set.complete and pattern.match(self.string, context) is not None:
            # Don't consider this incomplete - as we have the whole variable instance
            match_set.complete = True

        if self.pattern is pattern:
            # Include self

            if label is not None:
                context.variables[label] = self

            if condition is None or self.check_condition(condition, context):
                match_set.add(self, context)

        if shallow and self.pattern is pattern:
            # Don't check sub matches
            pass

        else:

            # Union with any sub matches
            for key, sub_match_list in self.sub_matches.items():

                # Coerce the sub_matches into a list
                if type(sub_match_list) is not list:
                    sub_match_list = [sub_match_list]

                for sub_match in sub_match_list:
                    # Union the match set into this one
                    sub_match_set = sub_match.instances(pattern, context, condition, attribute_name, shallow, label)
                    match_set = match_set.union(sub_match_set, context)

        # Check context for extra restrictions
        if attribute_name is not None:
            for r in context["restrictions"]:

                subs = r.get_sub_matches()

                negated = False
                if "negation" in subs:
                    negated = True
                    subs = subs["negated"].get_sub_matches()["condition"].get_sub_matches()

                if "membership" in subs:
                    subs = subs["membership"].get_sub_matches()

                if "negative_membership" in subs:
                    subs = subs["negative_membership"].get_sub_matches()
                    negated = not negated

                else:
                    continue

                if subs["set"].string == self.string + "." + attribute_name:
                    # This membership restriction applies

                    item = pattern.match(subs["item"].string, context)
                    if not negated:
                        # Positive membership
                        match_set.add(item, context)

                    else:
                        # Negative membership
                        match_set.remove(item, context)

            # Add the attribute path
            match_set.attribute_match = self
            match_set.attribute_name = attribute_name

        return match_set

    def has_parent(self, pattern, condition=None, context=None, label=None):
        # Return True if self has a parent match of the given pattern.
        # Optionally specify a label to add matches to context - useful if they are referenced in the condition

        if self.parent_match is None:
            return False

        if self.parent_match.pattern is pattern:

            if label is not None:
                context.variables[label] = self.parent_match

            # Check the condition (if any)
            if condition is None or self.parent_match.check_condition(condition, context):
                return True

        return self.parent_match.has_parent(pattern, condition, context, label)

    def equal_any(self, matchset, context):
        # Check if this match is equal to any item in the matchset

        for match in matchset.instances:
            if self.equivalent(match, context):
                return True

        return False

    def replace(self, needle, value, context, condition=None):
        # Return a new match replacing sub matches equivalent to needle with value. Optionally specify condition for
        # needles

        # Start with a copy of the same match
        m = self.duplicate()

        if m.equivalent(needle, context):
            # Easy case

            if condition is None or needle.check_condition(condition, context):
                return value.duplicate()

        # Go through the submatches
        new_sub_matches = dict()
        for key, sub_match in m.sub_matches.items():
            m.sub_matches[key] = sub_match.replace(needle, value, context, condition)

            if not m.sub_matches[key].string == sub_match.string and sub_match.is_variable and \
                    sub_match.string == needle.string:
                # This sub match been changed - update the key
                new_sub_matches[value.string] = m.sub_matches[key]

            else:
                new_sub_matches[key] = m.sub_matches[key]

        if isinstance(m.pattern, StringPattern):

            # Reset the match string
            m.string = ""
            i = 0
            while i < len(self.pattern.pattern):
                if i in self.pattern.non_variable_locations:
                    part = self.pattern.non_variable_locations[i]
                    match_part = part

                else:
                    part = self.pattern.variable_locations[i]["label"]
                    match_part = m.sub_matches[part].string

                    # Check if this value has changed
                    original = self.sub_matches[part]
                    new = m.sub_matches[part]

                    if (not new.string == original.string) and original.is_variable and original.string == needle.string:
                        # This sub match been changed
                        match_part = new.string

                m.string += match_part
                i += len(part)

        elif isinstance(m.pattern, UnionPattern):
            if not m.is_variable:
                m.string = list(m.sub_matches.values())[0].string

        # Replace sub_matches with the dictionary with updated keys
        m.sub_matches = new_sub_matches

        return m

    def pretty_print(self, depth=0):
        # Print the match tree

        if depth > 20:
            return "Exceeded maximum match depth"

        spaces = " " * depth * 4
        s = spaces + "> " + str(self) + ": " + str(self.pattern.name) + "\n"

        for key, item in self.sub_matches.items():
            s += item.pretty_print(depth + 1)

        return s

    def equivalent(self, other, context, memo=None):
        # Test whether two matches are equivalent.

        # A variable will typically return None when matched against a string or another variable - i.e. they could be
        # equal but it can't be guaranteed or ruled out.

        # Does not require equivalence of parent_match

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        if type(other) is not Match:
            memo[(self, other)] = False
            return False

        if not self.is_variable == other.is_variable:
            memo[(self, other)] = False
            return False

        # Belonging to the same pattern is a requirement
        if not self.pattern.equivalent(other.pattern, context, memo):
            memo[(self, other)] = False
            return False

        if self.definition is not None and not self.definition.equivalent(other.definition, context, memo):
            memo[(self, other)] = False
            return False

        # Test equality of sub_matches
        self_subs = self.sub_matches
        other_subs = other.sub_matches

        if not set(self_subs.keys()) == set(other_subs.keys()):
            # Sub matches don't correspond
            memo[(self, other)] = False
            return False

        if len(self_subs) > 0:

            # Keep track of the weakest sub-result - initially assumed to be True
            weakest = True

            for key in self_subs:
                # Check the subs are equivalent
                result = self_subs[key].equivalent(other_subs[key], context, memo)

                if result is False:
                    # Weakest result is False - so we can return this immediately
                    memo[(self, other)] = False
                    return False

                if result is None:
                    weakest = None

            return weakest

        # Otherwise, no sub_matches. Are we dealing with variables?
        self_var = self.string in context.string_variables
        other_var = other.string in context.string_variables

        if not self_var and not other_var:
            # Neither are variables
            memo[(self, other)] = self.string == other.string
            return self.string == other.string

        # Otherwise, at least one variable.
        if self.string == other.string:
            # We can take this as equal
            memo[(self, other)] = True
            return True

        # No apparent relation between self and other
        memo[(self, other)] = False
        return False

    def equivalent_with_some_replacements(self, other, needle, value, context):
        # Check if this match is equivalent to other, with some instances (on self) of needle replaced with value.

        if self.equivalent(other, context):
            # Equivalent without need to consider needle/value
            return True

        if self.equivalent(needle, context) and other.equivalent(value, context):
            # Needle and value
            return True

        # Otherwise need to be equivalent with sub matches equivalent under replacements

        if not self.pattern.equivalent(other.pattern, context):
            # Inconsistent patterns
            return False

        if self.is_variable is not other.is_variable:
            # One is a variable and the other is not
            return False

        # Check match definitions are equivalent
        if self.definition is not None:
            if other.definition is None:
                return False

            if not self.definition.equivalent(other.definition, context):
                return False

        else:
            if other.definition is not None:
                return False

        for key, sub in self.sub_matches.items():
            if key not in other.sub_matches:
                return False

            other_sub = other.sub_matches[key]

            if not sub.equivalent_with_some_replacements(other_sub, needle, value, context):
                return False

        # All sub-matches match
        if self.is_variable:
            # Can't check sub-matches of a variable
            return False

        return True

    def formatted_string(self):
        # Apply pattern formatting to the match string
        return self.pattern.pre_format_apply(self.string)

    def variables(self, context, variables=None):
        # Get the variable leaves in this match structure

        if variables is None:
            variables = MatchSet()

        if len(self.sub_matches) == 0 and self.is_variable:
            variables.add(self, context)

        for m in self.sub_matches.values():
            variables = variables.union(m.variables(context, variables), context)

        return variables

    def create_pattern(self, context):
        # Turn this match into a pattern with the submatches as variables

        pattern = StringPattern(name=self.string, pattern=self.string, pre_format=self.pattern.pre_format)

        # Need to be careful as variables may collide with parts of non-variable strings - which leads to unexpected
        # behaviour.

        # Get a match set of variables
        variables = self.variables(context)

        # Get unique variable names
        var_names = {v.string: v.pattern for v in variables.instances}

        for variable, variable_pattern in var_names.items():
            # Check occurrences of variable in string and in the tree. If string occurrences exceed tree occurrences,
            # there is a collision.

            string_occurrences = pattern.pattern.count(variable)
            tree_occurrences = len({v for v in variables.instances if v.string == variable})

            if string_occurrences == tree_occurrences:
                # All ok
                pattern.add_variable(variable, variable_pattern)
                continue

            # Collision. Try renaming the variable by appending increasing integers until it works
            i = 0
            while True:
                # Create the new variable
                new_var = variable + "_" + str(i)

                # New variable needs to not exist in var_names and not appear in pattern
                if new_var in variable or new_var in pattern.pattern:
                    continue

                # new_var works - use it to replace variable
                old_variable_match = Match(string=variable, pattern=variable_pattern, is_variable=True)
                new_variable_match = Match(string=new_var, pattern=variable_pattern, is_variable=True)

                new_match = self.replace(needle=old_variable_match, value=new_variable_match, context=context)

                # Use new_match to create a pattern
                return new_match.create_pattern(context)

        # In this case all existing variables are ok
        return pattern

    def maps_to(self, other, context, mapping=None):
        # Check if this match maps to the other. Changes mapping and returns a boolean

        if mapping is None:
            mapping = dict()

        if self.is_variable and self.string in mapping:
            return other.equivalent(mapping[self.string], context)

        # Must have consistent patterns
        if not self.pattern.equivalent(other.pattern, context):
            return False

        if self.is_variable and len(self.sub_matches) == 0:
            # Add variable to mapping
            mapping[self.string] = other
            return True

        # Otherwise depends on sub matches
        if not len(self.sub_matches) == len(other.sub_matches):
            return False

        for key, sub in self.sub_matches.items():
            if key not in other.sub_matches:
                return False

            other_sub = other.sub_matches[key]

            # Recursive call will update mapping if successful
            if not sub.maps_to(other_sub, context, mapping):
                return False

        # All ok
        return True

    def duplicate(self, parent_match=None):
        # Create a copy of this match.
        m = Match(
            pattern=copy(self.pattern),
            string=self.string,
            is_variable=self.is_variable
        )

        m.parent_match = parent_match
        m.sub_matches = {key: self.sub_matches[key].duplicate(parent_match=m) for key in self.sub_matches}

        m.definition = self.definition

        return m

    def __str__(self):
        return self.string


class MatchSet(object):
    # Class for a set of match instances

    def __init__(self, instances=None, negatives=None, complete=True, allow_multiple=True, attribute_match=None,
                 attribute_name=None):

        # A set of items in the matchset
        self.instances = instances
        if self.instances is None:
            self.instances = set()

        # A set of items known not to be in the matchset
        self.negatives = negatives
        if self.negatives is None:
            self.negatives = set()

        # Whether the match set is complete - i.e. does not contain variables
        self.complete = complete

        # Whether to allow multiple equivalent elements in the set
        self.allow_multiple = allow_multiple

        # If this is an attribute for a match - note the attribute match and name, to allow for easy comparison later
        self.attribute_match = attribute_match
        self.attribute_name = attribute_name

    def contains(self, match, context):
        # Check if the set contains the match. Return True if positive, False if negative, or None, if uncertain

        assert type(match) is Match

        # Check positives
        for item in self.instances:
            if match.equivalent(item, context):
                return True

        # Check negatives
        for item in self.negatives:
            if match.equivalent(item, context):
                return False

        # Not found in either set.
        if self.complete:
            # Not present in either set
            return False

        # Uncertain
        return None

    def is_subset(self, other, context):
        # Check if this match set is a subset of the other

        if not self.complete:
            # There are other items we can't test
            return False

        for item in self.instances:
            # Check membership of each item
            if not other.contains(item, context):
                # Not a subset
                return False

        # All members of self are members of other
        return True

    def add(self, match, context):
        # Add a match to the set, if it's not equivalent to one of the members

        if (not self.allow_multiple) and self.contains(match, context):
            # We already contain it
            return

        # If there are any elements in self.negatives equivalent to this, remove them
        self.negatives = {item for item in self.negatives if not item.equivalent(match, context)}

        # Add to instances
        self.instances.add(match)

    def remove(self, match, context):
        # Remove a match from the set

        # If there are any elements in self.instances equivalent to this, remove them
        self.instances = {item for item in self.instances if not item.equivalent(match, context)}

        if self.complete:
            # No need to worry about negatives.
            return

        for item in self.negatives:
            if item.equivalent(match, context):
                # Already present in negatives
                return

        # Add to negatives
        self.negatives.add(match)

    def union(self, other, context):
        # Return the union of this match set with another, leaving both unchanged

        new_match_set = MatchSet()

        # Complete only if both sets are complete
        new_match_set.complete = self.complete and other.complete

        # Everything in instances will be in the new instances
        new_match_set.instances = self.instances.copy()

        for item in other.instances:
            new_match_set.add(item, context)

        if new_match_set.complete:
            # No need to worry about negatives
            return new_match_set

        if (not self.complete) and (not other.complete):
            # Both are incomplete. Take only those elements in both negative sets

            for item in self.negatives:
                if other.contains(item, context) is False:
                    new_match_set.negatives.add(item)

            return new_match_set

        # One set is complete, and the other is not.
        # Take the incomplete negatives which are not in the complete instances
        if self.complete:
            complete = self
            incomplete = other
        else:
            complete = other
            incomplete = self

        for item in incomplete.negatives:
            if complete.contains(item, context) is False:
                new_match_set.negatives.add(item)

        return new_match_set

    def equivalent(self, other, context, memo=None):
        # Test equivalence of match sets

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        if type(other) is not MatchSet:
            memo[(self, other)] = False
            return False

        if self.attribute_match is not None and other.attribute_match is not None and \
                self.attribute_name == other.attribute_name and \
                self.attribute_match.equivalent(other.attribute_match, context, memo):
            # Attribute paths align
            memo[(self, other)] = True
            return True

        if not (self.complete and other.complete):
            # Must both be complete to compare
            memo[(self, other)] = False
            return False

        if (not self.allow_multiple) and (not other.allow_multiple):
            # Neither set admits multiples
            if not (len(self.instances) == len(other.instances) and len(self.negatives) == len(other.negatives)):
                # Size of the sets don't match
                memo[(self, other)] = False
                return False

        # Check instances and negatives have a bijection - maps in both directions
        for first, second in ((self, other), (other, self)):
            # Check the match items in instances
            for item in first.instances:
                if not second.contains(item, context):
                    memo[(self, other)] = False
                    return False
            # Every item in self.instances is in other.instances. Do the same with negatives

            for item in first.negatives:
                if second.contains(item, context) is not False:
                    # Other may contain the item
                    memo[(self, other)] = False
                    return False
            # Every item in self.negatives is in other.negatives.

        memo[(self, other)] = True
        return True

    def get_by_path(self, path, context, recurse=True):
        # Get some attribute of the matchset according to the given path

        if context.reference_object is None:
            context = copy(context)
            context.reference_object = self

        initial, remainder = parse_path(path)

        if remainder:
            # Use generic get by path
            return get_by_path(self, path, context)

        # Otherwise, only one part

        if path[:9] == "issubset(" and path[-1] == ")":
            inner = path[9:-1]

            other = get_by_path(context.reference_object, inner, context)
            return self.is_subset(other, context)

        if path[:6] == "union(" and path[-1] == ")":
            inner = path[6:-1]
            other = get_by_path(context.reference_object, inner, context)
            return self.union(other, context)

        if path == "strings()":
            # Return the matches as a set of strings
            if not self.complete:
                raise Exception("Can't get strings of an incomplete set.")

            return {match.string for match in self.instances}

        if path[:8] == "maps_to(" and path[-1] == ")":
            # Check if this matchset maps to the other one. Return the mapping if it exists.
            # Optionally specify a mapping dictionary that must be consistent.

            inner = path[8:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "mapping"))[1]

            other = kwargs["other"]
            mapping = kwargs["mapping"]

            return self.maps_to(other, context, mapping)

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception("Could not find value from path '" + path + "'.")

    def each(self, condition, context):
        # Check if every element meets a condition

        if not self.complete:
            # Can't check the missing elements
            return False

        for item in self.instances:
            if not condition.check(item, context):
                # This match fails
                return False

        return True

    def maps_to(self, other, context, mapping=None):
        # Check if this matchset maps to the other one.
        # Optionally specify a mapping dictionary that must be consistent.

        if type(other) is not MatchSet:
            # Other must also be a match set
            return False

        if mapping is False:
            return False

        if not self.complete:
            # Can't map an incomplete set
            return False

        # Every item in instances must have a corresponding item in other instances
        if len(self.instances) > 0 and len(other.instances) == 0:
            # Nothing to map to
            return False

        def sub_maps_to(source, target, map):
            # Recursive function to try mappings

            for s in source.instances:
                if s.string in map:
                    t = map[s.string]

                    if not other.contains(t, context):
                        # Target is not here
                        return False

                    continue

                for t in target.instances:
                    new_map = map.copy()
                    if s.maps_to(t, context, new_map):
                        # Try with this new mapping

                        # Recurse
                        result_map = sub_maps_to(source, target, new_map)

                        if result_map is False:
                            # This one is not consistent
                            continue

                        # The result works
                        return result_map

                # No consistent mapping
                return False

            # All source instances are mapped
            return map

        result = sub_maps_to(self, other, mapping.copy())

        if result is False:
            return False

        # Success
        mapping.update(result)

        return True

    def __str__(self):
        str_instances = ", ".join(sorted([str(m) for m in self.instances]))
        str_negatives = ", ".join(sorted([str(m) for m in self.negatives]))

        if self.complete:
            return "Complete instances: (" + str_instances + ")"

        if len(self.negatives) == 0:
            return "Incomplete instances: (" + str_instances + ")"

        return "Incomplete instances: (" + str_instances + "), negatives: " + str_negatives


class Pattern(object):
    # Parent class for Pattern objects StringPattern and UnionPattern

    def __init__(self, name, respect_brackets=None, pre_format=None):

        self.name = name

        # Keep a dictionary of functions on the pattern
        self.functions = dict()

        # Note any bracket pairs that should be respected
        self.respect_brackets = respect_brackets

        # Any formatting to be removed from patterns
        self.pre_format = pre_format

        # Default certainty of 0
        self.certainty = 0

    def pre_format_apply(self, s):
        # Remove formatting in the given string before matching

        if type(s) is not str:
            # Can't do much about non-strings
            return s

        if self.pre_format is None:
            # No formatting
            return s

        count = 0
        while True:
            old_s = s

            for pattern, replacement in self.pre_format.items():
                s = re.sub(pattern, replacement, s)

            # No changes
            if s == old_s:
                break

            count += 1

            if count > 100:
                # Likely infinite replacing loop
                raise Exception("Limit exceeded in RegEx replacements for " + s)

        return s

    def add_function(self, name, tree, params=None):
        # Add an function to this pattern. tree is an AbstractSyntaxTree instance

        # Optionally specify a list of (variable, pattern) tuples of parameters
        if params is None:
            params = tuple()

        self.functions[name] = {
            "tree": tree,
            "params": params
        }

    def get_function(self, name):
        # Get the given attribute function

        if name in self.functions:
            return self.functions[name]

        return None

    def check_brackets(self, s):
        # Return a boolean indicating if the string s respects brackets

        if self.respect_brackets is None:
            # Vacuously true
            return True

        i = 0
        stack = []
        while i < len(s):

            found = False

            for opening in self.respect_brackets:
                closing = self.respect_brackets[opening]

                if s[i:i + len(opening)] == opening:
                    i += len(opening)
                    stack.append(opening)
                    found = True
                    break

                if s[i: i + len(closing)] == closing:

                    if len(stack) == 0 or not stack[-1] == opening:
                        # No corresponding opening bracket
                        return False

                    i += len(closing)
                    stack.pop()
                    found = True
                    break

            if not found:
                i += 1

        if len(stack) > 0:
            # Stack left open at the end
            return False

        # All ok
        return True

    def may_contain(self, other, found=None):
        # Check if this pattern may contain the other

        if found is None:
            found = set()

        if self in found:
            return False

        found.add(self)

        if type(self) is UnionPattern:
            sub_patterns = self.patterns

        elif type(self) is StringPattern:
            sub_patterns = tuple(self.variables.values())

        else:
            # AbstractPattern, RegexPattern, or SystemConditionPattern
            return False

        for sub_pattern in sub_patterns:
            if sub_pattern is other:
                return True

            if sub_pattern.may_contain(other, found):
                return True

        return False

    def add_definition(self, lower, higher, context):
        # Add a definition to this pattern

        if self.match(lower, context) is None:
            # No match with lower
            return None

        defn = Definition(lower, higher, self, context)
        context.definitions.append(defn)

        return defn

    def try_definitions(self, s, context):
        # Try definitions to see if they can give a match for s

        for definition in context.definitions:
            if not definition.pattern.equivalent(self, context):
                continue

            result = definition.match(s, context)

            if result is not None:
                return result

        # No definitions work
        return None


class RegexPattern(Pattern):
    # RegEx pattern matching

    def __init__(self, name, pattern, pre_format=None):

        Pattern.__init__(self, name, pre_format=pre_format)

        self.pattern = pattern

    def match(self, s, context, debug=None):
        # Try to match a string s with the pattern

        formatted = self.pre_format_apply(s)

        for re_match in re.finditer(self.pattern, formatted, overlapped=True):

            if re_match is None:
                # No match
                continue

            m = Match(
                pattern=self,
                string=s
            )
            return m

        # No matches
        return None

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if not isinstance(other, RegexPattern):
            return False

        if not self.name == other.name:
            return False

        if not self.pattern == other.pattern:
            return False

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def __str__(self):
        return "RegexPattern: " + self.name


class StringPattern(Pattern):
    """A string pattern created in compiling lattice"""

    def __init__(self, name, pattern, variables=None, respect_brackets=None, pre_format=None):

        Pattern.__init__(self, name, respect_brackets, pre_format)

        # The pattern string
        self.pattern = self.pre_format_apply(pattern)

        # The display pattern. May be different to pattern depending on format
        self.display_pattern = pattern

        # Variables for sub patterns - a dictionary mapping to other StringPatterns or UnionPattern objects
        self.variables = dict()

        # Display variables
        self.display_variables = dict()

        # Record the variable locations for speed
        self.variable_locations = dict()

        if variables is not None:
            self.add_variables(variables)

        # Get the variable locations
        for i in range(0, len(self.pattern)):
            for var, sub_pattern in self.variables.items():
                if self.pattern[i:i + len(var)] == var:
                    # Add the location
                    self.variable_locations[i] = {
                        "label": var,
                        "pattern": sub_pattern
                    }

        # Give the pattern a certainty score - which reflects a naive likelihood of a shallow match resulting in an
        # actual match
        self.certainty = 0

        # Build the non-variable locations
        self.non_variable_locations = None

        # Artificially infinite certainty
        self.certainty = 10000
        self.get_non_variable_locations()

    def get_non_variable_locations(self):

        var_locations = [index for index in self.variable_locations]

        self.non_variable_locations = dict()
        i = 0
        while i < len(self.pattern):
            if i in self.variable_locations:
                i += len(self.variable_locations[i]["label"])
                continue

            # Otherwise, i will be in non_var_locations

            # Get the next variable location
            var_locations = [j for j in var_locations if j > i]
            if len(var_locations) == 0:
                # There are none left - go until the end
                self.non_variable_locations[i] = self.pattern[i:]
                break

            else:
                end = min(var_locations)
                self.non_variable_locations[i] = self.pattern[i:end]
                i = end

        # Update the certainty - the number of non-variable characters
        self.certainty = sum(len(self.non_variable_locations[i]) for i in self.non_variable_locations)

    def match(self, s, context, pattern_offset=0, non_variable_mapping=None, debug=None):
        # Match a string s against this pattern with the given context.
        # Optionally offset the pattern string, to start at an index > 0. This is used recursively.

        # Optionally specify non variable mapping.

        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "

            if pattern_offset == 0:
                print(spaces, "Attempting to match", s, " in ", self.name, ", with pattern: ", self.pattern)

            next_debug = debug + 1

        if pattern_offset == 0:

            formatted = self.pre_format_apply(s)
            if not s == formatted:
                # s has been reformatted
                m = self.match(formatted, context, pattern_offset, non_variable_mapping, debug)

                if m is not None:
                    # Correct the matched string to pre-formatted.
                    m.string = s

                return m

        string_variables = context.string_variables

        if pattern_offset == 0 and not self.check_brackets(s):
            # Brackets don't match
            return None

        # Create an optimistic match
        m = Match(
            pattern=self,
            string=s
        )

        if pattern_offset == 0:
            if len(self.variables) == 0 and s == self.pattern:
                # Match
                return m

            # Check if the whole string is a variable
            for svar, sub_pattern in string_variables.items():
                if s == svar and self == sub_pattern:
                    # Match!
                    m.is_variable = True
                    return m

        if pattern_offset == 0:

            # Try definitions
            result = self.try_definitions(s, context)

            if result is not None:
                # Definition applies
                return result

            # Check the non-variable parts all appear in order
            indices = sorted(index for index in self.non_variable_locations)

            i = 0
            for index in indices:
                part = self.non_variable_locations[index]

                # Find the next occurrence of the part
                j = s[i:].find(part)

                if j == -1:
                    # No match
                    return None

                if index == 0 and j > 0:
                    # Also no match
                    return None

                i += j + len(part)

            # Check the end of the pattern
            if len(indices) > 0:
                last_non_variable = indices[-1]

                if len(self.variable_locations) == 0 or last_non_variable > max(i for i in self.variable_locations):
                    # Pattern ends with a non-variable
                    part = self.non_variable_locations[last_non_variable]

                    if not s[-len(part):] == part:
                        # No match at the end
                        return None

        # Get the pattern string, excluding any initial offset
        pattern = self.pattern[pattern_offset:]

        if len(self.variables) == 0:
            # No variables

            if s == pattern:
                # Valid match
                return m

            # Otherwise, no match
            return None

        # Otherwise, there are variables. Check the pattern character by character.

        # NB this can't be done with regex - could be multiple matches with the same starting position only one of
        # which is valid

        if len(pattern) == 0 and len(s) == 0:
            # Easy case
            return m

        if len(pattern) == 0 and len(s) > 0:
            # No match
            return None

        if non_variable_mapping is None:
            # Build a non-variable mapping - so we know where the possible positions are for each non-variable string
            non_variable_mapping = []

        if pattern_offset == 0 and type(non_variable_mapping) is list:

            index = 0
            for part_index, pattern_part in self.non_variable_locations.items():

                # Find the next occurrence of s_part in s, starting from the previous index
                next_index = s[index:].find(pattern_part)

                # Add to non variable mapping
                non_variable_mapping.append([part_index, [index + next_index]])

                if next_index == -1:
                    return None

                index = index + next_index + 1

            # Add any other legal non variable mappings
            for i in range(0, len(non_variable_mapping)):
                part_index, lst = non_variable_mapping[i]
                start_index = lst[0]
                pattern_part = self.non_variable_locations[part_index]

                max_index = len(s)
                if i < len(non_variable_mapping) - 1:
                    # There is a next item
                    max_index = non_variable_mapping[i + 1][1][0]

                # Search for further instances of pattern_part in s, and add the index of these to lst
                next_index = start_index + 1
                while next_index < max_index:
                    increment = s[next_index:].find(pattern_part)
                    next_index += increment

                    if increment > -1:
                        lst.append(next_index)
                        next_index += 1
                    else:
                        break

            # Convert to a dictionary
            non_variable_mapping = {item[0]: item[1] for item in non_variable_mapping}

        # Check if this is a variable
        if pattern_offset in self.variable_locations:
            # Looks like a variable

            var = self.variable_locations[pattern_offset]["label"]
            sub_pattern = self.variable_locations[pattern_offset]["pattern"]

            # Check if there is a matching string variable in s
            for string_var, str_pattern in string_variables.items():
                if not s[:len(string_var)] == string_var:
                    continue

                # This looks like a string variable. Check the variable type is the same or part of a union
                if str_pattern.equivalent(sub_pattern, context) or \
                        (type(sub_pattern) is UnionPattern and str_pattern in sub_pattern.nested_options()):
                    # These refer to the same pattern

                    # Check the remainder of s also matches
                    remainder = s[len(string_var):]

                    new_non_variable_mapping = {
                        key: [entry - len(string_var) for entry in non_variable_mapping[key]]
                        for key in non_variable_mapping
                    }

                    remainder_match = self.match(
                        remainder,
                        context,
                        pattern_offset=pattern_offset + len(var),
                        non_variable_mapping=new_non_variable_mapping,
                        debug=debug
                    )

                    if remainder_match is None:
                        continue

                    # Match! Check for sub_match conflicts

                    if var in remainder_match.sub_matches:
                        remainder_sub = remainder_match.sub_matches[var]
                        if not (remainder_sub.pattern == sub_pattern and remainder_sub.string == string_var):
                            # There's a conflict with this variable later in the string
                            continue

                    # Otherwise, copy the sub_matches to m and return
                    for name, sub in remainder_match.sub_matches.items():
                        m.add_submatch(name, sub)

                    sub_pattern_match = sub_pattern.match(string_var, context, debug=next_debug)

                    # Add the string variable
                    m.add_submatch(
                        var=var,
                        m=sub_pattern_match
                    )

                    return m

            # Check what comes after the variable in the pattern to filter what to do
            next_offset = pattern_offset + len(var)

            if next_offset == len(self.pattern):
                # This is the final part of the pattern
                possible_js = [len(s)]

            elif next_offset in self.variable_locations:
                # There is another variable immediately following this one (generally not good as it's way slower)

                # Loop through the possibilities for the variable in s
                possible_js = list(range(0, len(s) + 1))

            else:
                # Must be a non-variable string
                assert next_offset in self.non_variable_locations

                # Get the possible positions of the pattern part in s
                possible_js = non_variable_mapping[next_offset]

                # Get the non-variable pattern part
                pattern_part = self.non_variable_locations[next_offset]

                # If the pattern part is final, it has to match the rest of the s exactly
                if len(possible_js) > 1 and next_offset + len(pattern_part) == len(self.pattern):
                    # The next pattern part is final. Keep only the final j
                    possible_js = [possible_js[-1]]

            # Find max j - the position of the next non-variable part
            max_j = len(s)
            keys = tuple(key for key in self.non_variable_locations if key - pattern_offset >= 0)

            if len(keys) > 0:
                min_key = min(keys)
                max_j = max(non_variable_mapping[min_key])

            possible_js = [j for j in possible_js if 0 <= j <= max_j]

            # Loop through the possibilities for the variable in s
            for j in possible_js:

                # Get the substring and remainder of s
                sub_s = s[:j]
                remainder = s[j:]

                remainder_match = None

                # Test if this sub_match is valid
                sub_match = sub_pattern.match(
                    sub_s,
                    context,
                    debug=next_debug
                )

                if sub_match is None:
                    # No match here
                    continue

                if len(remainder) == 0:
                    if next_offset < len(self.pattern) and next_offset not in self.variable_locations:
                        # Pattern still has a string left with nothing to match in s (and it's not a variable,
                        # which could match an empty string). No match.
                        continue

                else:
                    # Remainder is not empty - need to check

                    new_non_variable_mapping = {
                        key: [entry - j for entry in non_variable_mapping[key]]
                        for key in non_variable_mapping
                    }

                    # Check if the remainder of the string is a match
                    remainder_match = self.match(
                        remainder,
                        context,
                        pattern_offset=pattern_offset + len(var),
                        non_variable_mapping=new_non_variable_mapping,
                        debug=debug
                    )

                    if remainder_match is None:
                        # No match.
                        continue

                # The remainder matches

                # Match!

                # Check for conflicts with the sub_matches
                if remainder_match is not None:
                    if var in remainder_match.sub_matches:
                        remainder_sub = remainder_match.sub_matches[var]
                        if not (remainder_sub.pattern == sub_pattern and remainder_sub.string == sub_s):
                            # There's a conflict with this variable later in the string
                            continue

                    # Otherwise, copy the sub_matches to m and return
                    for name, sub in remainder_match.sub_matches.items():
                        m.add_submatch(name, sub)

                # Add the string variable
                m.add_submatch(var, sub_match)

                return m

        # Not a variable - check for literal character match
        if pattern_offset not in self.non_variable_locations:
            # No match
            return None

        part = self.non_variable_locations[pattern_offset]

        if part == s[:len(part)]:
            # Skip past the part in s and in the pattern

            if len(s[len(part):]) == 0 and pattern_offset + len(part) == len(self.pattern):
                # Reached the end of the pattern and string
                return m

            new_non_variable_mapping = {
                key: [entry - len(part) for entry in non_variable_mapping[key]]
                for key in non_variable_mapping
            }

            remainder_match = self.match(
                s[len(part):],
                context,
                pattern_offset=pattern_offset + len(part),
                non_variable_mapping=new_non_variable_mapping,
                debug=debug
            )

            if remainder_match is not None:
                # Success

                # Copy the sub_matches to m and return
                for name, sub in remainder_match.sub_matches.items():
                    m.add_submatch(name, sub)

                return m

        # Otherwise, no match
        return None

    def add_variable(self, name, pattern, use_location="all"):
        # Add a variable

        self.display_variables[name] = pattern

        # Format the variable name
        name = self.pre_format_apply(name)
        self.variables[name] = pattern

        # Get the variable location dict
        var_dict = {
            "label": name,
            "pattern": pattern
        }

        def find_nth(haystack, needle, n):
            # Find the index of the nth occurrence of needle in haystack

            start = haystack.find(needle)

            while start >= 0 and n > 1:
                start = haystack.find(needle, start + len(needle))
                n -= 1

            return start

        def add_location(loc):
            # Add location loc

            if loc == "all":

                # Update the variable locations
                for i in range(0, len(self.pattern)):
                    if self.pattern[i:i + len(name)] == name:
                        # Add the location
                        self.variable_locations[i] = var_dict

            elif loc == "first":
                # Use only the first location

                index = self.pattern.find(name)

                if index == -1:
                    # No instances
                    return

                self.variable_locations[index] = var_dict

            elif loc == "last":
                # Use only the last location

                index = self.pattern.rfind(name)

                if index == -1:
                    # No instances
                    return

                self.variable_locations[index] = var_dict

            elif type(loc) is int:
                # Take the nth location only

                index = find_nth(self.pattern, name, loc)
                self.variable_locations[index] = var_dict

        # Encourage use_location to be a list
        if type(use_location) is not list:
            use_location = [use_location]

        # Add each item in the list
        for item in use_location:
            add_location(item)

        self.get_non_variable_locations()

    def add_variables(self, variable_dict):
        # Add variables using a dictionary

        for name, var in variable_dict.items():
            if self.pre_format_apply(name) in self.pattern:
                self.add_variable(name, var)

    def reset_variables(self):
        # Reset the variables on this pattern

        variables = self.variables

        # Clear the variable locations. Non variable locations taken care of automatically
        self.variables = dict()
        self.variable_locations = dict()

        self.display_variables = dict()

        # Add the variables
        self.add_variables(variables)

    def set_pattern(self, pattern):
        # Reset the pattern string

        self.display_pattern = pattern
        self.pattern = self.pre_format_apply(pattern)

        # Reset variables
        self.reset_variables()

    def set_pre_format(self, pre_format):
        # Set the pre-format dictionary.

        self.pre_format = pre_format

        # Reset the pattern and variables
        self.set_pattern(self.display_pattern)

    def reverse_variables(self):
        # Get the reverse dictionary for variables

        reverse = dict()
        for var, subpattern in self.variables.items():
            if subpattern not in reverse:
                reverse[subpattern] = [var]

            else:
                reverse[subpattern].append(var)

        return reverse

    def reverse_display_variables(self):
        # Get the reverse dictionary for display variables

        reverse = dict()
        for var, subpattern in self.display_variables.items():
            if subpattern not in reverse:
                reverse[subpattern] = [var]

            else:
                reverse[subpattern].append(var)

        return reverse

    def create_match_with_variable_map(self, variable_map):
        # Create a match using this pattern with the given variable map ({String: String})

        s = self.pattern

        # Go through variable locations in reverse order
        indices = sorted([i for i in self.variable_locations], reverse=True)

        for i in indices:
            var_label = self.variable_locations[i]["label"]

            if var_label in variable_map:
                s = s[:i] + variable_map[var_label] + s[i + len(var_label):]

        return Match(string=s, pattern=self)

    def equivalent(self, other, context, memo=None):
        # Check if two patterns are the same

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, StringPattern):
            return False

        if not self.name == other.name:
            return False

        if not self.pre_format == other.pre_format:
            return False

        if not self.respect_brackets == other.respect_brackets:
            return False

        if not self.pattern == other.pattern:
            return False

        if not self.display_pattern == other.display_pattern:
            return False

        if not len(self.variables) == len(other.variables):
            return False

        # Assume True when checking nested patterns - so recursive patterns can compare equal
        memo[(self, other)] = True

        for key, sub_pattern in self.variables.items():
            if key not in other.variables:
                memo[(self, other)] = False
                return False

            if not self.variables[key].equivalent(other.variables[key], context, memo):
                memo[(self, other)] = False
                return False

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def __str__(self):
        return "StringPattern: " + self.name


class UnionPattern(Pattern):
    # A union of patterns

    def __init__(self, name, patterns, respect_brackets=None, pre_format=None):

        Pattern.__init__(self, name, respect_brackets, pre_format)

        # The list of patterns
        self.patterns = patterns

    def match(self, s, context, debug=None):
        # Match s against one of the patterns.

        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "
            print(spaces, "Attempting to match", s, " in ", self.name, ", a UnionPattern.")
            next_debug = debug + 1

        formatted = self.pre_format_apply(s)
        if not s == formatted:
            # s has been reformatted
            m = self.match(formatted, context, debug)

            if m is not None:
                m.string = s

            return m

        # Get the nested options
        nested_options = self.nested_options(path_dict=True)

        pattern_options = [p for p in nested_options if type(p) in (StringPattern, AbstractPattern)]

        # Sort the patterns by decreasing certainty
        pattern_options.sort(key=lambda x: x.certainty, reverse=True)

        string_variables = context.string_variables

        if s in string_variables:
            pattern = string_variables[s]

            if self.equivalent(pattern, context):
                return Match(
                    pattern=self,
                    string=s,
                    is_variable=True
                )

            elif pattern in nested_options:
                m = Match(
                    pattern=pattern,
                    string=s,
                    is_variable=True
                )

                for p in nested_options[pattern]:
                    next_match = Match(
                        pattern=p,
                        string=s
                    )
                    next_match.add_submatch(m.pattern.name, m)

                    m = next_match

                return m

        if not self.check_brackets(s):
            # Brackets don't match
            return None

        for pattern in pattern_options:

            # Try to match the pattern
            result = pattern.match(s, context, debug=next_debug)

            if result is None:
                # No match
                continue

            # Successful match - but result is not a union match
            m = Match(
                pattern=self,
                string=s
            )

            # TODO: Is this correct? May need to add a chain of matches if pattern is nested?

            m.add_submatch(pattern.name, result)

            return m

        # Try definitions
        result = self.try_definitions(s, context)

        if result is not None:
            # Definition applies
            return result

        return None

    def add_variables(self, variable_dict):
        # Add variables to all patterns in the union

        for pattern in self.patterns:
            if type(pattern) is UnionPattern:
                pattern.add_variables(variable_dict)

            elif type(pattern) is StringPattern:
                pattern.add_variables(variable_dict)

    def nested_options(self, path_dict=False):
        # Get a set of all patterns in this union - and any sub-unions
        # Optionally return as a dictionary including the paths to each option

        # Start with an empty set
        found = set()

        if path_dict:
            # It's a dictionary instead
            found = dict()

        for p in self.patterns:

            if type(p) is UnionPattern and p not in found:

                sub_options = p.nested_options(path_dict)

                if path_dict:

                    # Append the sub paths to the dictionary, adding self
                    for pattern in sub_options:

                        if pattern not in found or len(sub_options[pattern]) < len(found[pattern]):
                            found[pattern] = sub_options[pattern]

                        found[pattern].append(self)

                else:
                    found = found.union(sub_options)

            if path_dict:
                found[p] = [self]

            else:
                found.add(p)

        return found

    def set_pre_format(self, pre_format):
        # Set the pre-format dictionary.
        self.pre_format = pre_format

    def equivalent(self, other, context, memo=None):
        # Check if two patterns are the same

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, UnionPattern):
            return False

        if not self.name == other.name:
            return False

        if not self.pre_format == other.pre_format:
            return False

        if not self.respect_brackets == other.respect_brackets:
            return False

        if not len(self.patterns) == len(other.patterns):
            return False

        # Assume True for nested checks
        memo[(self, other)] = True

        # Patterns must be in the same order
        for pattern, other_pattern in zip(self.patterns, other.patterns):
            if not pattern.equivalent(other_pattern, context, memo):
                memo[(self, other)] = False
                return False

        # Looks ok
        return True

    def __str__(self):
        return "UnionPattern: " + self.name


class AbstractPattern(Pattern):
    # Abstract string pattern - used only as a variable

    def __init__(self, name):

        Pattern.__init__(self, name)

        # Arbitrary infinite certainty
        self.certainty = 1000000

    def match(self, s, context, debug=None):
        # Try to match s in the given context

        # s only matches if there is a string variable of this pattern
        if s in context.string_variables and self.equivalent(context.string_variables[s], context):
            return Match(
                pattern=self,
                string=s,
                is_variable=True
            )

        return None

    def equivalent(self, other, context, memo=None):
        # Check equivalence - depends only on name

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if not isinstance(other, AbstractPattern):
            return False

        if not self.name == other.name:
            return False

        memo[(self, other)] = True
        return True

    def __str__(self):
        return "AbstractPattern: " + self.name


class SystemConditionPattern(Pattern):
    # Special pattern used to check if strings can be parsed as a Condition

    def __init__(self, name):
        Pattern.__init__(self, name)

        # Arbitrary infinite certainty
        self.certainty = 1000000

    def match(self, s, context, debug=None):
        # Try to match a string s.

        # We only care if s could be a Condition
        try:
            condition = Condition(string=s, context=context)

            result = condition.validate()

            if result:
                # Return a match
                return Match(
                    pattern=self,
                    string=s
                )

        except Exception as e:
            pass

        # Otherwise, no match
        return None

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = dict()

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if not isinstance(other, SystemConditionPattern):
            return False

        if not self.name == other.name:
            return False

        memo[(self, other)] = True
        return True
