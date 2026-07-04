"""Path-based value lookup and argument-parsing helpers.

This is the leaf module of the matching package: it references the pattern
and match classes only through function-local imports, so it has no
import-time dependency on its siblings.
"""

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

    if args_string == "":
        return args, kwargs

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
            raise Exception(f"Unexpected argument: '{key}'.")

    # Otherwise, kwargs match.

    # Add the args to kwargs
    for arg, arg_name in zip(args, arg_names[:len(args)]):
        kwargs[arg_name] = arg

    # Add any missing arguments as None
    for arg in arg_names:
        if arg not in kwargs:
            kwargs[arg] = None

    # Return no args, all kwargs
    return [], kwargs


def constant(s):
    from .matches import MatchSet
    # Parse a string s to a constant

    if s == "True":
        return True

    if s == "False":
        return False

    if s == "set()":
        return set()

    if s == "MatchSet()":
        return MatchSet()

    if s == "tuple()":
        return ()

    if s == "list()" or s == "[]":
        return []

    if s == "dict()" or s == "{}":
        return {}

    try:
        if "." not in s:
            return int(s)
        return float(s)
    except ValueError:
        pass

    if len(s) > 1 and s[0] in ("'", '"') and s[0] == s[-1] and s[0] not in s[1:-1]:
        # Looks like a string
        inner = s[1:-1]
        return inner

    return None


def get_by_path(obj, path, context, recurse=True):
    from .conditions import Condition
    from .matches import MatchSet
    from .patterns import Pattern
    # General function to get an object by a path.

    if context.reference_object is None and obj is not None:
        context = copy(context)
        context.reference_object = obj

    initial, remainder = parse_path(path)

    if remainder:
        # Chain the parts
        initial = get_by_path(obj, initial, context)

        return get_by_path(initial, remainder, context)

    # Check none
    if path == "None":
        return None

    # Check for constants
    c = constant(path)
    if c is not None:
        return c

    # Otherwise, only one part
    if hasattr(obj, "get_by_path") and recurse:
        # Try the obj get_by_path first
        try:
            return obj.get_by_path(path, context)
        except Exception:
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
            return context.mapping[path]

    if path in context.logical:
        return context.logical[path]

    if "[" in path and path[-1] == "]":
        # Looks like list or dict lookup

        index = path.index("[")
        initial = path[:index]
        inner = path[index + 1:-1]

        initial = get_by_path(obj, initial, context)
        inner = get_by_path(None, inner, context)

        if isinstance(initial, dict):
            # Dictionary lookup
            if inner in initial:
                return initial[inner]

        # Otherwise looks like a list index
        return initial[int(inner)]

    # Try addition of parts
    if " + " in path:
        try:
            parts = path.split(" + ")

            if len(parts) >= 2:
                evaluated_parts = [get_by_path(obj, part, context) for part in parts]

                result = evaluated_parts[0]
                for part in evaluated_parts[1:]:
                    result = result + part

                return result

        except Exception:
            pass

    if path.startswith("set(") and path[-1] == ")":
        # Make a new set
        inner = path[4:-1]
        return MatchSet(instances={get_by_path(obj, inner, context)})

    if path.startswith("len(") and path[-1] == ")":
        # Get the length of the inner
        inner = path[4:-1]
        return len(get_by_path(obj, inner, context))

    if path.startswith("Condition(") and path[-1] == ")":
        # Make a new condition
        inner = path[10:-1]
        return Condition(string=inner, context=context)

    # Try a pattern match
    if isinstance(obj, Pattern) and path.startswith("match(") and path[-1] == ")":
        inner = path[6:-1]
        inner_value = get_by_path(obj, inner, context)
        return obj.match(inner_value, context)

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

    if path == "conditions":
        return context.conditions

    if recurse and context.reference_object is not None and hasattr(context.reference_object, "get_by_path"):
        # Try the reference object
        return context.reference_object.get_by_path(path, context)

    raise Exception(f"Could not find value from path '{path}'.")


def path_maps_to(path, other_path, context, other_context, mapping):
    from .matches import Match
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
        fn_name = initial[:index]
        args = inner.split(", ")

        if inner == "":
            args = []

        if "(" in other_initial and other_initial[-1] == ")":
            other_index = other_initial.index("(")
            other_inner = other_initial[other_index + 1:-1]
            other_fn_name = other_initial[:other_index]
            other_args = other_inner.split(", ")

            if other_inner == "":
                other_args = []

            if not fn_name == other_fn_name:
                return False

            if not len(args) == len(other_args):
                return False

            for a, b in zip(args, other_args):
                result = path_maps_to(a, b, context, other_context, mapping)

                if not result:
                    return False

            return True

    # Initials have to map
    if initial in mapping and not mapping[initial].string == other_initial:
        # Already mapped the initial to something else
        return False

    # Initial success
    mapping_copy = copy(mapping)

    if initial in context.string_variables and other_initial in other_context.string_variables:
        initial_pattern = context.string_variables[initial]
        other_initial_pattern = other_context.string_variables[other_initial]

        if not initial_pattern.equivalent(other_initial_pattern, context):
            # Variables not of the same pattern
            return False

        # Add to mapping
        mapping_copy[initial] = Match(string=other_initial, pattern=other_initial_pattern, is_variable=True)

    # Remainders have to match
    if remainder is None or path_maps_to(remainder, other_remainder, context, other_context, mapping_copy):
        # Both remainders match

        # Update mapping
        mapping.update(mapping_copy)
        return True

    return False
