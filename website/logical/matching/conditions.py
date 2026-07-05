"""The :class:`Condition` expression tree."""

from copy import copy

from .paths import get_by_path, parse_arguments, parse_path, path_maps_to


class Condition:
    """A condition tree object."""

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
                        raise Exception(f"Could not parse condition '{self.string}', mismatched parentheses.")

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
                raise Exception(f"Could not parse condition '{self.string}', mismatched parentheses.")

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
                    raise Exception(f"Could not parse condition '{self.string}'.")

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
                    raise Exception(f"Could not parse condition '{self.string}'.")

                self.type = "in"

                left = parts[:i]
                right = parts[i + 1:]

                if parts[i - 1] == "not":
                    # Not in
                    self.type = "not in"
                    if i - 1 == 0:
                        raise Exception(f"Could not parse condition '{self.string}'.")

                    left = parts[:i - 1]

                self.sub_items = ["".join(left), "".join(right)]

                # Done
                return

        # Check for is, is not
        for i in range(0, len(parts)):
            part = parts[i]

            if part == "is":
                if i == 0 or i == len(parts) - 1:
                    raise Exception(f"Could not parse condition '{self.string}'.")

                self.type = "is"

                left = parts[:i]
                right = parts[i + 1:]

                if parts[i + 1] == "not":
                    # Not in
                    self.type = "is not"
                    if i + 1 == len(parts) - 1:
                        raise Exception(f"Could not parse condition '{self.string}'.")

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

        # First check if the condition is mapped to in context
        if context.mapping is not None:
            for cond in context.conditions:
                if self.maps_to(cond, context.mapping):
                    return True

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
            # Must be for a match set or dictionary

            item = get_by_path(obj, self.sub_items[0], context)
            rhs = get_by_path(obj, self.sub_items[1], context)

            if isinstance(rhs, dict):
                # It's a normal dictionary
                result = item in rhs

            else:
                # Assume it's a match set
                result = rhs.contains(item, context)

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

            if hasattr(left, "equivalent"):
                return left.equivalent(right, context)

            else:
                return left == right

        if obj is None:
            # No context object given. Try to get an object from the first condition part
            return get_by_path(None, self.string, context)

        if hasattr(obj, "get_by_path"):
            return obj.get_by_path(self.string, context)

        raise Exception(f"Couldn't evaluate condition '{self.string}'.")

    def maps_to(self, other, mapping):
        # Check if this condition maps to the other one under the string variable mapping

        # Work with copies of self context and other context with string_variable_matches
        self_context = copy(self.context)
        other_context = copy(other.context)

        if self_context is None or other_context is None:
            # Can't map without context
            return False

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

        if self.type in ("in", "not in", "equals", "is", "is not"):
            # Need to check the items/sets can be mapped.

            left_path, right_path = self.sub_items
            other_left_path, other_right_path = other.sub_items

            if not path_maps_to(left_path, other_left_path, self_context, other_context, mapping):
                # Need to get items manually

                try:
                    left = get_by_path(self, left_path, self_context)
                    other_left = get_by_path(other, other_left_path, other_context)

                    if not left.maps_to(other_left, self_context, mapping):
                        return False

                except Exception:
                    return False

            if not path_maps_to(right_path, other_right_path, self_context, other_context, mapping):
                # Need to get match sets manually

                try:
                    right = get_by_path(self, right_path, self_context)
                    other_right = get_by_path(other, other_right_path, other_context)

                    return right.maps_to(other_right, self_context, mapping)

                except Exception:
                    return False

            # Otherwise both paths map successfully
            return True

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

    def validate(self):
        # Check if the condition is valid.
        return True

    def conjunctive_parts(self):
        # Get the conjunctive parts of this condition.

        if not self.type == "and":
            # Only one part - the whole condition
            return {self}

        # Otherwise get parts recursively
        return self.sub_conditions[0].conjunctive_parts().union(self.sub_conditions[1].conjunctive_parts())

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
        if path.startswith("maps_into_set(") and path[-1] == ")":
            inner = path[14:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("target_condition_set", "mapping"))[1]

            return self.maps_into_set(kwargs["target_condition_set"], kwargs["mapping"])

        if path == "string()":
            return self.string

        if path == "conjunctive_parts()":
            return self.conjunctive_parts()

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = self.string == other.string
        return self.string == other.string

    def __str__(self):
        return f"Condition: {self.string}"
