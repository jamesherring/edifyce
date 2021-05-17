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


class Condition(object):
    # A condition tree object

    def __init__(self, string, parts=None):

        # The condition string
        self.string = string

        # The condition type - "and", "or", "not", "in", "not in", "brackets", or "atomic"
        self.type = None

        # Optionally specify list of string parts
        self.parts = parts

        # Any sub conditions
        self.sub_conditions = []

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
            self.sub_conditions = [Condition(string=inner)]

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
                    Condition(string="".join(left), parts=left),
                    Condition(string="".join(right), parts=right)
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

                if part[i - 1] == "not":
                    # Not in
                    self.type = "not in"
                    if i - 1 == 0:
                        raise Exception("Could not parse condition '" + self.string + "'.")

                    left = parts[:i - 1]

                self.sub_conditions = [
                    Condition(string="".join(left), parts=left),
                    Condition(string="".join(right), parts=right)
                ]

                # Done
                return

        # Check for not
        if parts[0] == "not":

            self.type = "not"

            remainder = parts[1:]
            self.sub_conditions = [Condition(string=self.string[4:], parts=remainder)]

            return

        # Otherwise atomic - can be parsed by the match
        self.type = "atomic"

    def check_composite(self, obj, context):
        # Check a composite type condition for the given object

        # Check the possible condition types
        if self.type == "brackets":
            # Easy case
            return obj.check_condition(self.sub_conditions[0], context)

        elif self.type == "and":
            return obj.check_condition(self.sub_conditions[0], context) and \
                   obj.check_condition(self.sub_conditions[1], context)

        elif self.type == "or":
            return obj.check_condition(self.sub_conditions[0], context) or \
                   obj.check_condition(self.sub_conditions[1], context)

        elif self.type == "not":
            return not obj.check_condition(self.sub_conditions[0], context)

        elif self.type in ("in", "not in"):
            # Must be for a match set

            item = obj.get_by_path(self.sub_conditions[0].string, context)
            match_set = obj.get_by_path(self.sub_conditions[1].string, context)

            result = match_set.contains(item, context)

            if self.type == "in":
                return result

            # Negated
            return not result

        raise Exception("Condition is not composite.")


class Match(object):
    # Match object

    def __init__(self, pattern, string):

        self.pattern = pattern
        self.string = string

        # List of sub matches
        self.sub_matches = dict()

        # The parent match
        self.parent_match = None

    def add_submatch(self, var, m):
        self.sub_matches[var] = m
        m.parent_match = self

    def get_by_path(self, path, context):
        # Get the value by a path

        initial, remainder = parse_path(path)

        if remainder:
            # Chain the parts
            return self.get_by_path(initial, context).get_by_path(remainder, context)

        # Otherwise, only one part

        if path == "parent()":
            return self.parent_match

        elif path == "pattern()":
            return self.pattern

        elif path in self.sub_matches:
            return self.sub_matches[path]

        elif path in self.pattern.attributes:
            return self.run_function(path, context)

        elif path == "lookup()":
            # Look up the value in context
            if self.string in context["variables"]:
                return context["variables"][self.string]

            raise Exception("Could not find '" + self.string + "' in context.")

        elif path == "union_submatch()":
            # Get the only submatch
            assert type(self.pattern) is UnionPattern

            return list(self.sub_matches.values())[0]

        elif path in context["variables"]:
            return context["variables"][path]

        elif path[:10] == "instances(" and path[-1] == ")":
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

            if pattern_name not in context["variables"]:
                raise Exception("Unrecognised pattern '" + pattern_name + "'.")

            pattern = context["variables"][pattern_name]

            # Build the condition
            condition = None
            if condition_string is not None:
                condition = Condition(condition_string)

            return self.instances(pattern, context, condition, label=pattern_label)

        elif path[:18] == "shallow_instances(" and path[-1] == ")":
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

            if pattern_name not in context["variables"]:
                raise Exception("Unrecognised pattern '" + pattern_name + "'.")

            pattern = context["variables"][pattern_name]

            # Build the condition
            condition = None
            if condition_string is not None:
                condition = Condition(condition_string)

            return self.instances(pattern, context, condition, label=pattern_label, shallow=True)

        elif path == "string()":
            return self.string

        elif path in context:
            return context[path]

        if "antecedents" in context and path[:12] == "antecedents[" and path[-1] == "]":
            try:
                index = int(path[12:-1])
                return context["antecedents"][index]

            except Exception as e:
                raise Exception("Could not parse path: '" + path + "'.")

        else:
            condition_fns = ["has_parent", "equal_any"]

            for cf in condition_fns:
                if path[:len(cf)] == cf:
                    # Looks like a condition
                    condition = Condition(path)
                    return self.check_condition(condition, context)

        raise Exception("Could not parse path: '" + path + "'.")

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

            condition = None if sub_condition_string is None else Condition(sub_condition_string)

            # Get the pattern label and name
            pattern_label, pattern_name = pattern_string.split(" as ")

            if pattern_name not in context["variables"]:
                raise Exception("Could not find pattern '" + pattern_string + "'.")

            # Get the pattern
            pattern = context["variables"][pattern_name]

            return self.has_parent(pattern, condition, copy(context), label=pattern_label)

        elif c.string[:10] == "equal_any(":
            # Check if a value is equal to any of a matchset

            inner = c.string[10:-1]
            match_set = self.get_by_path(inner, context)

            return self.equal_any(match_set, context)

        elif " == " in c.string:
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

    def run_function(self, name, context, params=None):
        # Run a custom function with the given name.

        fn = self.pattern.get_function(name)

        if fn is None:
            raise Exception("'" + self.pattern.name + "' does not have function '" + name + "'.")

        # Check the params matches have the correct pattern
        if params is None:
            params = []

        if not len(params) == len(fn["params"]):
            # Wrong number of parameters provided
            raise Exception("'" + name + "' expected " + str(len(fn["params"])) + " argument(s), " + str(len(params)) +
                            " provided.")

        # Build a parameter mapping
        param_mapping = dict()
        for given, fn_param in zip(params, fn["params"]):
            fn_param_label, fn_param_pattern = fn_param

            if not given.pattern == fn_param_pattern:
                # Patterns don't match
                raise Exception("'" + name + "' expected argument of pattern '" + fn_param_pattern.name + "'.")

            param_mapping[fn_param_label] = given

        # Create a copy of context
        context_copy = copy(context)

        # Run the tree as a function
        tree = fn["tree"]
        return tree.run_function(match=self, context=context_copy, params=param_mapping)

    def instances(self, pattern, context, condition=None, attribute_name=None, shallow=False, label=None):
        # Get instances of the pattern in nested sub matches, which meet the specified condition.
        # Optionally specify the attribute we are searching for

        # Optionally specify a label to add matched instances to context - useful for referencing in conditions

        # If shallow - don't look for nested instances of pattern deeper than instances found
        if type(pattern) is str:
            # Need to get the correct pattern
            pattern = context["variables"][pattern]

        # If incomplete, it's a variable pattern, that may contain an instance of the needle pattern
        complete = not (self.string in context["string_variables"] and self.pattern.may_contain(pattern))

        # Create a new MatchSet
        match_set = MatchSet(complete=complete)

        if not match_set.complete and pattern.match(self.string, context) is not None:
            # Don't consider this incomplete - as we have the whole variable instance
            match_set.complete = True

        if self.pattern is pattern:
            # Include self

            if label is not None:
                context["variables"][label] = self

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
                context["variables"][label] = self.parent_match

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

    def pretty_print(self, depth=0):
        # Print the match tree

        if depth > 20:
            return "Exceeded maximum match depth"

        spaces = " " * depth * 4
        s = spaces + "> " + str(self) + ": " + str(self.pattern.name) + "\n"

        for key, item in self.sub_matches.items():
            if type(item) is list:
                # This is a list entry
                s += spaces + "    [\n"

                for sub in item:
                    s += sub.pretty_print(depth + 2)

                s += spaces + "    ]\n"

            elif type(item) is Match:
                s += item.pretty_print(depth + 1)

            else:
                # Simple entry
                print(self.pattern, type(self.pattern))
                print(self.sub_matches)
                s += str(item)

        return s

    def equivalent(self, other, context, allow_definitions=False):
        # Test whether two matches are equivalent. For variables - use context restrictions where possible.

        # A variable will typically return None when matched against a string or another variable - i.e. they could be
        # equal but it can't be guaranteed or ruled out.

        if type(other) is not Match:
            return False

        # Belonging to the same pattern is a requirement, unless there's a convenient definition
        if not self.pattern is other.pattern:

            if not allow_definitions:
                # Ignore possible definitions
                return False

            # See if there's a definition to help
            if self.lower_match is not None:
                # Try the lower match
                if self.lower_match.equivalent(other, context, allow_definitions):
                    return True

                if other.lower_match is not None:
                    # Combine both definitions
                    if self.lower_match.equivalent(other.lower_match, context, allow_definitions):
                        return True

            if other.lower_match is not None:
                # The the other definition
                if self.equivalent(other.lower_match, context, allow_definitions):
                    return True

            # Otherwise, no luck
            return False

        # Test equality of sub_matches
        self_subs = self.sub_matches
        other_subs = other.sub_matches

        if not set(self_subs.keys()) == set(other_subs.keys()):
            # Sub matches don't correspond
            return False

        if len(self_subs) > 0:

            # Keep track of the weakest sub-result - initially assumed to be True
            weakest = True

            for key in self_subs:
                # Check the subs are equivalent
                result = self_subs[key].equivalent(other_subs[key], context, allow_definitions)

                if result is False:
                    # Weakest result is False - so we can return this immediately
                    return False

                if result is None:
                    weakest = None

            return weakest

        # Otherwise, no sub_matches. Are we dealing with variables?
        self_var = self.string in context["string_variables"]
        other_var = other.string in context["string_variables"]

        if not self_var and not other_var:
            # Neither are variables
            return self.string == other.string

        # Otherwise, at least one variable.
        if self.string == other.string:
            # We can take this as equal
            return True

        # Check the restrictions.
        mapping = None
        if self_var:
            mapping = context.get_variable_restrictions(self.string, mapping)
            self_map = mapping[self.string]
        else:
            self_map = {
                "positive": {"value": self.string}
            }

        if other_var:
            mapping = context.get_variable_restrictions(other.string, mapping)
            other_map = mapping[other.string]
        else:
            other_map = {
                "positive": {"value": other.string}
            }

        if "value" in self_map["positive"]:
            # We have a fixed value for self
            self_value = self_map["positive"]["value"]

            if "value" in other_map["positive"]:
                # We have a fixed value for other
                other_value = other_map["positive"]["value"]

                return self_value == other_value

            # No fixed value for other
            if self_value in other_map["negative"]["values"]:
                # Can't be equal
                return False

            # Otherwise, they could be equal, and they could be not equal
            return None

        # No fixed value for self
        if "value" in other_map["positive"]:
            # We have a fixed value for other
            other_value = other_map["positive"]["value"]

            if other_value in self_map["negative"]["values"]:
                # Can't be equal
                return False

            # Otherwise, they could be equal, and they could be not equal
            return None

        # No fixed value for other

        # Both self and other don't have fixed values
        if other.string in self_map["positive"]["variables"]:
            # They are nonetheless the same
            return True

        if other.string in self_map["negative"]["variables"]:
            # They must be different
            return False

        # No apparent relation between self and other
        return None

    def formatted_string(self):
        # Apply pattern formatting to the match string
        return self.pattern.pre_format_apply(self.string)

    def create_pattern(self, string_variables):
        # Turn this match into a pattern with the submatches as variables

        pattern = StringPattern(name="", pattern=self.string, pre_format=self.pattern.pre_format)
        pattern.add_variables(string_variables)

        return pattern

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

    def equivalent(self, other, context):
        # Test equivalence of match sets

        if self.attribute_match is not None and other.attribute_match is not None and \
                self.attribute_name == other.attribute_name and \
                self.attribute_match.equivalent(other.attribute_match, context):
            # Attribute paths align
            return True

        if not (self.complete and other.complete):
            # Must both be complete to compare
            return False

        if (not self.allow_multiple) and (not other.allow_multiple):
            # Neither set admits multiples
            if not (len(self.instances) == len(other.instances) and len(self.negatives) == len(other.negatives)):
                # Size of the sets don't match
                return False

        # Check instances and negatives have a bijection - maps in both directions
        for first, second in ((self, other), (other, self)):
            # Check the match items in instances
            for item in first.instances:
                if not second.contains(item, context):
                    return False
            # Every item in self.instances is in other.instances. Do the same with negatives

            for item in first.negatives:
                if second.contains(item, context) is not False:
                    # Other may contain the item
                    return False
            # Every item in self.negatives is in other.negatives.

        return True

    def get_by_path(self, path, context):
        # Get some attribute of the matchset according to the given path

        initial, remainder = parse_path(path)

        if remainder:
            # Chain the parts
            return self.get_by_path(initial, context).get_by_path(remainder, context)

        # Otherwise, only one part

        if path[:9] == "issubset(" and path[-1] == ")":

            inner = path[9:-1]
            other = self.get_by_path(inner, context)
            return self.is_subset(other, context)

        elif path[:6] == "union(" and path[-1] == ")":
            inner = path[6:-1]
            other = self.get_by_path(inner, context)
            return self.union(other, context)

        elif path[:4] == "set(" and path[-1] == ")":
            # Make a new set
            inner = path[4:-1]
            return MatchSet(instances={self.get_by_path(inner, context)})

        elif path in context["variables"]:
            return context["variables"][path]

        if not self.complete:
            # Can't apply to incomplete set
            raise Exception("Can't get path '" + path + "' from incomplete set.")

        # Otherwise, apply the path to each element in the set
        result = MatchSet()
        for m in self.instances:
            sub_result = m.get_by_path(path, context)

            if type(sub_result) is MatchSet:
                # Extend the results
                result = result.union(sub_result, context)

            else:
                result.add(sub_result, context)

        return result

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

    def __init__(self, name, parent=None, respect_brackets=None, pre_format=None):

        self.name = name

        # The parent pattern (if applicable)
        self.parent = parent

        # Keep a dictionary of attributes on the pattern
        self.attributes = dict()

        # Note any bracket pairs that should be respected
        self.respect_brackets = respect_brackets

        # Any formatting to be removed from patterns
        self.pre_format = pre_format

        # Track equivalent patterns
        self.equivalent_patterns = set()

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

        self.attributes[name] = {
            "tree": tree,
            "params": params
        }

    def get_function(self, name):
        # Get the given attribute function

        if name in self.attributes:
            return self.attributes[name]

        # Check the parent pattern attributes
        if self.parent is not None:
            return self.parent.get_attribute(name)

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


class RegexPattern(Pattern):
    # RegEx pattern matching

    def __init__(self, name, pattern):

        Pattern.__init__(self, name)

        self.pattern = pattern

    def match(self, s, context, debug=None):
        # Try to match a string s with the pattern

        for re_match in re.finditer(self.pattern, s, overlapped=True):

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

    def __str__(self):
        return "RegexPattern: " + self.name


class StringPattern(Pattern):
    """A string pattern created in compiling lattice"""

    def __init__(self, name, pattern, variables=None, parent=None, respect_brackets=None, pre_format=None):

        Pattern.__init__(self, name, parent, respect_brackets, pre_format)

        # The pattern string
        self.pattern = self.pre_format_apply(pattern)

        # The display pattern. May be different to pattern depending on format
        self.display_pattern = pattern

        # Variables for sub patterns - a dictionary mapping to other StringPatterns or UnionPattern objects
        self.variables = dict()

        # Display variables
        self.display_variables = dict()

        # The definitions that apply - only to a certain context
        self.definitions = None

        # Record the last definition this pattern has seen
        self.definition_context = None

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
        spaces = ""
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

        if pattern_offset == 0 and self.parent is not None:

            # Create a new context with variables in the string_variables
            new_context = copy(context)
            new_context["string_variables"].update(self.variables)

            if debug is not None:
                print(spaces, "Checking parent pattern.")

        string_variables = context["string_variables"]

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
                    return m

        if pattern_offset == 0:

            # # Get the definitions for this pattern
            # self.get_definitions(context)
            #
            # # Check if there is an applicable definition
            # for defn in self.definitions:
            #     # Try the definition
            #
            #     if defn["valid"]:
            #         return defn["definition"].apply(s, self, context)

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
                if str_pattern is sub_pattern or \
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

                    # Add the string variable
                    m.add_submatch(
                        var=var,
                        m=sub_pattern.match(string_var, context, debug=next_debug)
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

    def __str__(self):
        return "StringPattern: " + self.name


class UnionPattern(Pattern):
    # A union of patterns

    def __init__(self, name, patterns, parent=None, respect_brackets=None, pre_format=None):

        Pattern.__init__(self, name, parent, respect_brackets, pre_format)

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

        string_variables = context["string_variables"]

        if s in string_variables:
            pattern = string_variables[s]

            if self is pattern:
                return Match(
                    pattern=self,
                    string=s
                )

            elif pattern in nested_options:
                m = Match(
                    pattern=pattern,
                    string=s
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

        # s only matches if there is a variable of this pattern
        if s in context["variables"] and context["variables"][s] is self:
            return Match(
                pattern=self,
                string=s
            )

        return None

    def __str__(self):
        return "AbstractPattern: " + self.name

