"""The :class:`Match` and :class:`MatchSet` classes."""

import itertools
from copy import copy

from . import patterns
from .conditions import Condition
from .paths import get_by_path, parse_arguments, parse_path


class Match:
    """Match object."""

    def __init__(self, pattern, string, is_variable=False, definition=None):

        self.pattern = pattern
        self.string = string

        # Is this a variable match?
        self.is_variable = is_variable

        # List of sub matches
        self.sub_matches = {}

        # The parent match
        self.parent_match = None

        # The definition used
        self.definition = definition

    def add_submatch(self, var, m):
        self.sub_matches[var] = m
        m.parent_match = self

    def get_by_path(self, path, context, recurse=True):
        # Get the value by a path

        # Format the path
        path = self.pattern.pre_format_apply(path)

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

        elif path == "definition()":
            return self.definition

        elif path in self.sub_matches:
            return self.sub_matches[path]

        elif path == "lookup()":
            # Look up the value in context
            if self.string in context.variables:
                return context.variables[self.string]

            raise Exception(f"Could not find '{self.string}' in context.")

        elif path == "sub_matches()":
            return self.sub_matches

        elif path == "union_submatch()":
            # Get the only submatch
            if type(self.pattern) is not patterns.UnionPattern:
                raise ValueError(
                    f"Cannot take union_submatch() of {self.string}, as the corresponding pattern "
                    f"{self.pattern.name} is not a UnionPattern."
                )

            return list(self.sub_matches.values())[0]

        elif path.startswith("contains(") and path[-1] == ")":
            inner = path[9:-1]
            needle = get_by_path(None, inner, context)
            return self.contains(needle, context)

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
                raise Exception(f"Unrecognised pattern '{pattern_name}'.")

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
                raise Exception(f"Unrecognised pattern '{pattern_name}'.")

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
            kwargs = parse_arguments(inner, context.reference_object, context, arg_names=("needle", "value", "condition"))[1]

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

        elif path.startswith("equivalent_under_definitions(") and path[-1] == ")":
            inner = path[29:-1]

            # Specify arg_names to get all in kwargs
            kwargs = parse_arguments(inner, self, context, arg_names=("other",))[1]
            return self.equivalent_under_definitions(kwargs["other"], context)

        elif path.startswith("is_descendant_of(") and path[-1] == ")":
            inner = path[17:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("parent",))[1]
            return self.is_descendant_of(kwargs["parent"])

        elif path == "string()":
            return self.string

        elif path == "formatted_string()":
            return self.formatted_string()

        elif path == "variables()":
            return self.variables(context)

        elif path == "condition()":
            return Condition(string=self.string, context=context)

        elif path.startswith("maps_to(") and path[-1] == ")":
            inner = path[8:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "mapping"))[1]
            return self.maps_to(kwargs["other"], context, kwargs["mapping"])

        elif path.startswith("apply_mapping(") and path[-1] == ")":
            # Try applying a mapping to this match
            inner = path[14:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("mapping",))[1]
            return self.apply_mapping(kwargs["mapping"], context)

        else:
            condition_fns = ["has_parent", "equal_any"]

            for cf in condition_fns:
                if path.startswith(cf):
                    # Looks like a condition
                    condition = Condition(path, context=context)
                    return self.check_condition(condition, context)

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

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

            parts = inner.split("; ")

            if not 1 <= len(parts) <= 3:
                raise ValueError(f"Condition {self.string} has too many parts.")

            pattern_string = parts[0]
            within_match = None
            sub_condition_string = None

            if len(parts) > 1:
                within_match = get_by_path(None, parts[1], context)

            if len(parts) == 3:
                sub_condition_string = parts[2]

            condition = None if sub_condition_string is None else Condition(sub_condition_string, context=context)

            # Get the pattern label and name
            pattern_label, pattern_name = pattern_string.split(" as ")

            if pattern_name not in context.variables:
                raise Exception(f"Could not find pattern '{pattern_string}'.")

            # Get the pattern
            pattern = context.variables[pattern_name]

            return self.has_parent(pattern, within_match, condition, copy(context), label=pattern_label)

        elif c.string[:10] == "equal_any(":
            # Check if a value is equal to any of a matchset

            inner = c.string[10:-1]
            match_set = self.get_by_path(inner, context)

            return self.equal_any(match_set, context)

        else:
            # Get by path
            return self.get_by_path(c.string, context)

    def contains(self, other, context):
        # Check if this match contains other (ie is equivalent to self or some submatch)

        if self.equivalent(other, context):
            return True

        for sub in self.sub_matches.values():
            if sub.contains(other, context):
                return True

        # Otherwise not
        return False

    def instances(self, pattern, context, condition=None, attribute_name=None, shallow=False, label=None):
        # Get instances of the pattern in nested sub matches, which meet the specified condition.
        # Optionally specify the attribute we are searching for

        # Optionally specify a label to add matched instances to context - useful for referencing in conditions

        # If shallow - don't look for nested instances of pattern deeper than instances found
        if type(pattern) is str:
            # Need to get the correct pattern
            pattern = context.variables[pattern]

        # If incomplete, it's a variable pattern, that may contain an instance of the needle pattern
        # complete = not (self.string in context.string_variables and self.pattern.may_contain(pattern, context))
        complete = not (self.is_variable and self.pattern.may_contain(pattern, context))

        # Create a new MatchSet
        match_set = MatchSet(complete=complete)

        if not match_set.complete and pattern.match(self.string, context) is not None:
            # Don't consider this incomplete - as we have the whole variable instance
            match_set.complete = True

        if self.pattern.equivalent(pattern, context):
            # Include self

            if label is not None:
                context.variables[label] = self

            if condition is None or self.check_condition(condition, context):
                match_set.add(self, context)

        if shallow and self.pattern.equivalent(pattern, context):
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

                if subs["set"].string == f"{self.string}.{attribute_name}":
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

    def has_parent(self, pattern, within_match=None, condition=None, context=None, label=None):
        # Return True if self has a parent match of the given pattern.
        # Optionally specify a label to add matches to context - useful if they are referenced in the condition
        # Optionally specify within_match that the parent must be within

        if self.parent_match is None:
            return False

        if within_match is not None and not self.is_descendant_of(within_match):
            # Weird within_match. Should be a parent of self.
            return False

        if self is within_match:
            # Parent will be outside
            return False

        if self.parent_match.pattern.equivalent(pattern, context):

            if label is not None:
                context.variables[label] = self.parent_match

            # Check the condition (if any)
            if condition is None or self.parent_match.check_condition(condition, context):
                return True

        return self.parent_match.has_parent(pattern, within_match, condition, context, label)

    def equal_any(self, matchset, context):
        # Check if this match is equal to any item in the matchset
        for match in matchset.instances:
            if self.equivalent(match, context):
                return True

        return False

    def is_descendant_of(self, parent):
        # Check if this is in the tree of parent. Requires the matches to be in the same structure.

        if self is parent or self.parent_match is None:
            return False

        if self.parent_match is parent or self.parent_match.is_descendant_of(parent):
            return True

        # Otherwise false
        return False

    def replace(self, needle, value, context, condition=None, allow_variables=False):
        # Return a new match replacing sub matches equivalent to needle with value. Optionally specify condition for
        # needles. Optionally allow variables which may contain needles without raising an error.

        # Start with a copy of the same match
        m = self.duplicate()

        if m.equivalent(needle, context):
            # Easy case

            if condition is None or m.check_condition(condition, context):
                # Passes any replacement condition
                return value.duplicate()

        if m.pattern.equivalent(value.pattern, context):
            # Check the chain of union sub-matches in case of something equivalent to needle.
            sub = m
            while isinstance(sub.pattern, patterns.UnionPattern):
                # Check the sub-match

                if len(sub.sub_matches) == 0:
                    # No submatches
                    break

                sub = list(sub.sub_matches.values())[0]
                if sub.equivalent(needle, context):
                    # Looks like a needle
                    if condition is None or sub.check_condition(condition, context):
                        return value.duplicate()

        if m.is_variable and m.pattern.may_contain(needle.pattern, context):
            # This is a variable match not equivalent to needle. We can't check or replace submatches.

            if allow_variables:
                # Don't raise an exception. This is a variable which will map to something else before replacement.
                return m

            raise Exception("Cannot replace instances in a variable match.")

        # Go through the submatches
        for key, sub_match in m.sub_matches.items():
            m.sub_matches[key] = sub_match.replace(needle, value, context, condition, allow_variables)

        if isinstance(m.pattern, patterns.UnionPattern) and m.definition is None:
            # May need to reset the key (which is the pattern name)
            key = list(m.sub_matches.keys())[0]
            value = m.sub_matches[key]

            # Reset
            m.sub_matches = {value.pattern.name: value}

        # Reset the match string
        m.reset_string()

        return m

    def replace_variables(self, variable_dict, context):
        # Replace variables according the matches in the dictionary. This should be a match: match dictionary

        result = copy(self)
        for key, value in variable_dict.items():
            result = result.replace(key, value, context, allow_variables=True)

        return result

    def reset_string(self):
        # Reset the match string according to the patterns

        if isinstance(self.pattern, patterns.StringPattern) or self.definition is not None:

            pattern_used = self.pattern if self.definition is None else self.definition.higher

            new_string = ""
            i = 0
            while i < len(pattern_used.pattern):
                if i in pattern_used.non_variable_locations:
                    part = pattern_used.non_variable_locations[i]
                    match_part = part

                else:
                    part = pattern_used.variable_locations[i]["label"]
                    match_part = self.sub_matches[part].string

                new_string += self.pattern.pre_format_apply(match_part)
                i += len(part)

            self.string = new_string

        elif isinstance(self.pattern, patterns.UnionPattern):
            if not self.is_variable:
                sub_match = list(self.sub_matches.values())[0]
                sub_match.reset_string()
                self.string = sub_match.string

        # Otherwise nothing to do

    def pretty_print(self, depth=0):
        # Print the match tree

        if depth > 20:
            return "Exceeded maximum match depth"

        spaces = " " * depth * 4
        s = f"{spaces}> {self!s}: {self.pattern.name!s}\n"

        for key, item in self.sub_matches.items():
            s += item.pretty_print(depth + 1)

        return s

    def equivalent(self, other, context, memo=None):
        # Test whether two matches are equivalent.

        # A variable will typically return None when matched against a string or another variable - i.e. they could be
        # equal but it can't be guaranteed or ruled out.

        # Does not require equivalence of parent_match
        if memo is None:
            memo = {}

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
        self_var = self.formatted_string() in context.string_variables
        other_var = other.formatted_string() in context.string_variables

        if not self_var and not other_var:
            # Neither are variables
            memo[(self, other)] = self.formatted_string() == other.formatted_string()
            return self.formatted_string() == other.formatted_string()

        # Otherwise, at least one variable.
        if self.formatted_string() == other.formatted_string():
            # We can take this as equal
            memo[(self, other)] = True
            return True

        # No apparent relation between self and other
        memo[(self, other)] = False
        return False

    def equivalent_with_some_replacements(self, other, needle, value, context):
        # Check if this match is equivalent to other, with some instances (on self) of needle replaced with value on
        # other

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

    def equivalent_under_definitions(self, other, context):
        # Check if this match is equivalent to other - with some unknown definitions applied

        if self.definition is None and other.definition is None:
            # Check sub matches
            if not len(self.sub_matches) == len(other.sub_matches):
                return False

            for key in self.sub_matches:
                if key not in other.sub_matches:
                    return False

                self_sub = self.sub_matches[key]
                other_sub = other.sub_matches[key]

                if not self_sub.equivalent_under_definitions(other_sub, context):
                    return False

            # Otherwise ok
            return True

        if self.definition is not None and other.definition is not None and \
                self.definition.equivalent(other.definition, context):
            # Definitions are equivalent - check submatches

            if not len(self.sub_matches) == len(other.sub_matches):
                return False

            for key in self.sub_matches:
                if key not in other.sub_matches:
                    return False

                self_sub = self.sub_matches[key]
                other_sub = other.sub_matches[key]

                if not self_sub.equivalent_under_definitions(other_sub, context):
                    return False

        if self.definition is not None:
            # Unpack definition on self
            try:
                lower = self.definition.get_lower(self, context)
                if lower.equivalent_under_definitions(other, context):
                    return True

            except Exception:
                # Can't get lower. Try applying the definition instead
                if self.definition.check_application(other, self, context):
                    return True

        if other.definition is not None:
            # Unpack definition on other
            try:
                lower = other.definition.get_lower(other, context)
                if self.equivalent_under_definitions(lower, context):
                    return True

            except Exception:
                # Can't get lower. Try applying the definition instead
                if other.definition.check_application(self, other, context):
                    return True

        if self.equivalent(other, context):
            return True

        # Otherwise no luck
        return False

    def formatted_string(self):
        # Apply pattern formatting to the match string
        return self.pattern.pre_format_apply(self.string)

    def variables(self, context, variables=None):
        # Get the variable leaves in this match structure

        if variables is None:
            variables = MatchSet(allow_multiple=True)

        if len(self.sub_matches) == 0 and self.is_variable:
            variables.add(self, context)

        for m in self.sub_matches.values():
            variables = variables.union(m.variables(context, variables), context, allow_multiple=True)

        return variables

    def create_pattern(self, context):
        # Turn this match into a pattern with the submatches as variables

        if self.is_variable:
            # We can just use the pattern given (but ensure it is a stringpattern)
            formatted_string = self.formatted_string()
            return patterns.StringPattern(
                name=formatted_string,
                pattern=formatted_string,
                pre_format=self.pattern.pre_format,
                variables={formatted_string: context.string_variables[formatted_string]}
             )

        pattern = patterns.StringPattern(name=self.string, pattern=self.string, pre_format=self.pattern.pre_format)

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
                new_var = f"{variable}_{i!s}"

                # New variable needs to not exist in var_names and not appear in pattern
                if new_var in variable or new_var in pattern.pattern:
                    continue

                # new_var works - use it to replace variable
                old_variable_match = Match(string=variable, pattern=variable_pattern, is_variable=True)
                new_variable_match = Match(string=new_var, pattern=variable_pattern, is_variable=True)

                new_match = self.replace(needle=old_variable_match, value=new_variable_match, context=context, allow_variables=True)

                # Use new_match to create a pattern
                return new_match.create_pattern(context)

        # In this case all existing variables are ok
        return pattern

    def maps_to(self, other, context, mapping=None):
        # Check if this match maps to the other. Changes mapping and returns a boolean

        if mapping is None:
            mapping = {}
            new_mapping = {}
        else:
            new_mapping = copy(mapping)

        if self.is_variable and self.formatted_string() in new_mapping:
            return other.equivalent(new_mapping[self.formatted_string()], context)

        # Must have consistent patterns
        if not self.pattern.can_map_to(other.pattern, context):
            return False

        if self.is_variable and len(self.sub_matches) == 0:
            # Add variable to (original) mapping
            mapping[self.formatted_string()] = other
            return True

        # Otherwise depends on sub matches
        if not len(self.sub_matches) == len(other.sub_matches):
            return False

        for key, sub in self.sub_matches.items():
            if key not in other.sub_matches:
                return False

            other_sub = other.sub_matches[key]

            # Recursive call will update mapping if successful
            if not sub.maps_to(other_sub, context, new_mapping):
                return False

        # Update the original mapping
        mapping.update(new_mapping)

        # All ok
        return True

    def maps_to_up_to_definition(self, other, context, mapping=None, debug=None):
        # Check if self maps to other - allowing for use of definitions

        spaces = None
        next_debug = None
        if debug is not None:
            spaces = 4 * debug * " "
            print(f"{spaces}Attempting to map {self.formatted_string()} to {other.formatted_string()}.")
            next_debug = debug + 1

        if mapping is None:
            mapping = {}
            new_mapping = {}
        else:
            new_mapping = copy(mapping)

        if self.is_variable and self.formatted_string() in new_mapping:
            result = other.equivalent_under_definitions(new_mapping[self.formatted_string()], context)
            if debug is not None:
                print(f"{spaces}Existing variable '{self.string}' {'passed' if result else 'failed.'}.")
            return result

        # Must have consistent patterns
        if not self.pattern.can_map_to(other.pattern, context):
            if debug is not None:
                print(f"{spaces}Failed too map patterns {self.pattern.name} to {other.pattern.name}.")
            return False

        if self.is_variable and len(self.sub_matches) == 0:
            # Add variable to (original) mapping
            mapping[self.formatted_string()] = other
            if debug is not None:
                print(f"{spaces}Setting variable {self.formatted_string()} as {other.formatted_string()}.")
            return True

        if (self.definition is None and other.definition is None) or \
                (self.definition is not None and other.definition is not None and
                 self.definition.equivalent(other.definition, context, allow_mapping_to=True)):
            # Try submatches

            if not len(self.sub_matches) == len(other.sub_matches):
                # Mismatched sub matches
                if debug is not None:
                    print(f"{spaces}Failed: mismatched submatch count.")
                return False

            for var in self.sub_matches:
                if var not in other.sub_matches:
                    # Mismatched sub matches
                    if debug is not None:
                        print(f"{spaces}Failed: mismatched submatch names.")
                    return False

                self_sub = self.sub_matches[var]
                other_sub = other.sub_matches[var]

                if not self_sub.maps_to_up_to_definition(other_sub, context, new_mapping, next_debug):
                    return False

            # All sub matches map
            mapping.update(new_mapping)
            return True

        if other.definition is not None:
            # Unpack this definition
            try:
                lower = other.definition.get_lower(other, context)

                if self.maps_to_up_to_definition(lower, context, new_mapping, next_debug):
                    mapping.update(new_mapping)
                    return True

            except Exception:
                # Can't get lower
                pass

        if self.definition is not None:
            # Unpack this definition
            try:
                lower = self.definition.get_lower(self, context)

                if lower.maps_to_up_to_definition(other, context, new_mapping, next_debug):
                    mapping.update(new_mapping)
                    return True
            except Exception:
                # Can't get lower
                pass

        # No luck
        if debug is not None:
            print(f"{spaces}Failed: no options passed.")
        return False

    def apply_mapping(self, mapping, context):
        # Apply the given string: match dictionary to get a mapped version of this match.

        # First build a match: match variable dictionary
        variable_dict = {}

        # Loop through the variables and map them
        for var in self.variables(context).instances:
            if var.string not in mapping:
                # This contains a variable not in the mapping and so can't be mapped.
                return False

            variable_dict[var] = mapping[var.string]

        # Replace the variables
        return self.replace_variables(variable_dict, context)

    def duplicate(self, parent_match=None):
        # Create a copy of this match and assign it to the parent
        m = copy(self)
        m.parent_match = parent_match
        return m

    def __str__(self):
        return f"Match for {self.pattern.name}: {self.string}"

    def __copy__(self):
        # Create a copy of this match (ignoring the parent match)
        m = Match(
            pattern=copy(self.pattern),
            string=self.string,
            is_variable=self.is_variable
        )

        m.sub_matches = {key: self.sub_matches[key].duplicate(parent_match=m) for key in self.sub_matches}
        m.definition = self.definition

        return m


class MatchSet:
    """Class for a set of match instances."""

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

        if not isinstance(match, Match):
            raise ValueError(f"MatchSet.contains() requires an argument of type Match, received {type(match)!s} instead.")

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

    def union(self, other, context, allow_multiple=False):
        # Return the union of this match set with another, leaving both unchanged.
        # By default ignore duplicates

        new_match_set = MatchSet(allow_multiple=allow_multiple)

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
            memo = {}

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
        if path.startswith("add(") and path[-1] == ")":
            # Add (doesn't return anything)
            inner = path[4:-1]
            match = get_by_path(context.reference_object, inner, context)
            self.add(match, context)
            return

        if path.startswith("remove(") and path[-1] == ")":
            # Remove (doesn't return anything)
            inner = path[7:-1]
            match = get_by_path(context.reference_object, inner, context)
            self.remove(match, context)
            return

        if path.startswith("issubset(") and path[-1] == ")":
            inner = path[9:-1]

            other = get_by_path(context.reference_object, inner, context)
            return self.is_subset(other, context)

        if path.startswith("union(") and path[-1] == ")":
            inner = path[6:-1]
            other = get_by_path(context.reference_object, inner, context)
            return self.union(other, context)

        if path.startswith("contains(") and path[-1] == ")":
            inner = path[9:-1]
            item = get_by_path(context.reference_object, inner, context)
            return self.contains(item, context)

        if path.startswith("each(") and path[-1] == ")":
            # Condition on each element
            inner = path[5:-1]

            parts = inner.split("; ")

            if len(parts) == 1:
                # Only one part - the condition
                condition = Condition(string=inner, context=context)
                return self.each(condition, context)

            # Otherwise we have named instances
            if len(parts) != 2:
                raise ValueError(f"'each' function must have two parameters. '{path}' contains {len(parts)}.")
            var_name = parts[0]
            condition = Condition(string=parts[1], context=context)

            return self.each(condition, context, var_name)

        if path == "strings()":
            # Return the matches as a set of strings
            if not self.complete:
                raise Exception("Can't get strings of an incomplete set.")

            return {match.string for match in self.instances}

        if path.startswith("maps_to(") and path[-1] == ")":
            # Check if this matchset maps to the other one. Return the mapping if it exists.
            # Optionally specify a mapping dictionary that must be consistent.

            inner = path[8:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "mapping"))[1]

            other = kwargs["other"]
            mapping = kwargs["mapping"]

            return self.maps_to(other, context, mapping)

        if path.startswith("get_mappings_to(") and path[-1] == ")":
            # Get a list of possible mappings
            inner = path[16:-1]
            kwargs = parse_arguments(inner, self, context, arg_names=("other", "mapping"))[1]

            other = kwargs["other"]
            mapping = kwargs["mapping"]

            return self.get_mappings_to(other, context, mapping)

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

    def each(self, condition, context, var_name=None):
        # Check if every element meets a condition. Optionally specify a variable name.

        if not self.complete:
            # Can't check the missing elements
            return False

        # Work with a copy of context
        context_copy = copy(context)

        for item in self.instances:

            if var_name is not None:
                context_copy.variables[var_name] = item

            if not condition.check_condition(item, context_copy):
                # This match fails
                return False

        return True

    def variables(self, context):
        # Get the variables used in this matchset

        result = MatchSet(allow_multiple=False)

        for instance in self.instances:
            result = result.union(instance.variables(context), context)

        return result

    def maps_to(self, other, context, mapping=None):
        # Check if this everything in this matchset maps to the target one. This may not be surjective.
        # Optionally specify a mapping dictionary that must be consistent.
        return len(self.get_mappings_to(other, context, mapping)) > 0

    def get_mappings_to(self, other, context, mapping=None):
        # Get a list of all possible mappings from this set to the target one. Mappings don't need to be surjective.
        # Optionally specify a mapping dictionary that must be consistent.

        if mapping is None:
            mapping = {}

        if type(other) is not MatchSet:
            # Other must also be a match set
            return []

        if mapping is False:
            return []

        if not self.complete:
            # Can't map an incomplete set
            return []

        if len(self.instances) == 0:
            # Vacuously True - every item in instances maps to other_instances
            return [mapping.copy()]

        # Every item in instances must have a corresponding item in other instances
        if len(self.instances) > 0 and len(other.instances) == 0:
            # Nothing to map to
            return []

        # Start with an empty list of mappings
        mapping_list = []

        # Generate and test every possible mapping of other instances on self instances
        maps = [dict(zip(self.instances, values)) for values in itertools.product(other.instances, repeat=len(self.instances))]

        for test_map in maps:
            # Check if the test map is consistent with the given mapping
            consistent = True
            map_copy = mapping.copy()
            for source, target in test_map.items():
                if not source.maps_to(target, context, map_copy):
                    # This one doesn't work
                    consistent = False
                    break

            if not consistent:
                continue

            # Add it to the list
            mapping_list.append(map_copy)

        return mapping_list

    def __str__(self):
        str_instances = ", ".join(sorted([str(m) for m in self.instances]))
        str_negatives = ", ".join(sorted([str(m) for m in self.negatives]))

        if self.complete:
            return f"Complete instances: ({str_instances})"

        if len(self.negatives) == 0:
            return f"Incomplete instances: ({str_instances})"

        return f"Incomplete instances: ({str_instances}), negatives: {str_negatives}"

    def __len__(self):
        if not self.complete:
            raise Exception("Cannot get the length of an incomplete match set")

        return len(self.instances)

    def __copy__(self):
        # Make a copy of this matchset
        return MatchSet(
            instances=copy(self.instances),
            negatives=copy(self.negatives),
            complete=self.complete,
            allow_multiple=self.allow_multiple,
            attribute_match=copy(self.attribute_match),
            attribute_name=self.attribute_name
        )
