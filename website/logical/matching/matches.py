"""The :class:`Match` and :class:`MatchSet` classes."""

import itertools
from copy import copy

from . import patterns


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

    def field(self, name):
        # Project a declared sub-field off this match by name - a line type's
        # formula_field / reference_field. This is the sole surviving use of the
        # retired get_by_path interpreter, reduced to the direct sub-match lookup
        # it always resolved to. Raises KeyError when the field is absent;
        # FormalSystem.parse treats that as "the line has no such field".
        return self.sub_matches[name]

    def replace(self, needle, value, context, allow_variables=False):
        # Return a new match replacing sub matches equivalent to needle with value. Optionally allow variables which
        # may contain needles without raising an error.

        # Start with a copy of the same match
        m = self.duplicate()

        if m.equivalent(needle, context):
            # Easy case
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
                    return value.duplicate()

        if m.is_variable and m.pattern.may_contain(needle.pattern, context):
            # This is a variable match not equivalent to needle. We can't check or replace submatches.

            if allow_variables:
                # Don't raise an exception. This is a variable which will map to something else before replacement.
                return m

            raise Exception("Cannot replace instances in a variable match.")

        # Go through the submatches
        for key, sub_match in m.sub_matches.items():
            m.sub_matches[key] = sub_match.replace(needle, value, context, allow_variables)

        if isinstance(m.pattern, patterns.UnionPattern) and m.definition is None:
            # May need to reset the key (which is the pattern name)
            key = list(m.sub_matches.keys())[0]
            value = m.sub_matches[key]

            # Reset
            m.sub_matches = {value.pattern.name: value}

        # Reset the match string
        m.reset_string()

        return m

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

                new_string += match_part
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

    def formatted_string(self):
        # The match's surface string. Retained as the matching layer's accessor
        # for it (many callers); the pre-format hook it used to apply is gone.
        return self.string

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
                variables={formatted_string: context.string_variables[formatted_string]}
             )

        pattern = patterns.StringPattern(name=self.string, pattern=self.string)

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
