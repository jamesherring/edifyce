"""The :class:`Definition` linking higher- and lower-level patterns."""

from copy import copy

from . import matches, patterns
from .conditions import Condition
from .paths import get_by_path, parse_path


class Definition:
    """A definition class - linking higher level string patterns with lower level ones."""

    def __init__(self, lower, higher, pattern, context, condition_string=None):

        # The pattern this definition applies to
        self.pattern = pattern

        self.lower = None
        self.lower_match_template = None

        # Create a higher pattern
        self.higher = patterns.StringPattern(
            name="Definition (higher)",
            pattern=higher,
            variables=copy(context.string_variables),
            pre_format=self.pattern.pre_format
        )

        self.variables = copy(self.higher.variables)

        # We might not know what the lower pattern is
        if lower is not None:

            # Get the match for variables
            match = self.pattern.match(lower, context)
            if match is None:
                raise ValueError(f"Lower pattern for definition must match the pattern. '{lower}' is not an instance of {pattern.name}.")

            # Create a lower pattern
            self.lower = match.create_pattern(context)

            # Keep the lower match as a template
            self.lower_match_template = match

            # Store the variables in a common dictionary.
            self.variables = self.lower.variables
            self.variables.update(self.higher.variables)

        # Optional condition string
        self.condition = Condition(pattern.pre_format_apply(condition_string), context=context) \
            if condition_string is not None else None

        # Cached term-based (kernel) counterpart, built lazily by the
        # formal_system layer for definitional-step checking over the shared-DAG
        # term representation (see formal_system/definitions.py). Held opaquely so
        # the matching layer keeps its no-kernel-import rule; `ready` records that
        # a build was attempted, and `kernel_definition is None` after that means
        # the definition is not soundly expressible as a kernel definition (it has
        # a legacy condition or a binder the `Define` DSL cannot declare), so the
        # caller falls back to the string-based check_application path. A shallow
        # copy carries both across the context copies the engine makes, so the
        # build happens at most once per definition.
        self.kernel_definition = None
        self.kernel_definition_ready = False

    def match(self, s, context):
        # Check if the definition applies to a string s, of the higher level match.
        # We assume if there's a match, any condition has been met.

        higher_match = self.higher.match(s, context)

        if higher_match is None:
            return None

        # Success - create a match
        m = matches.Match(
            string=s,
            pattern=self.pattern,
            definition=self
        )

        # Add submatches according to the variables in the higher match
        for key, sub_match in higher_match.sub_matches.items():
            m.add_submatch(key, sub_match.duplicate())

        return m

    def check_application(self, lower, higher, context, mapping=None, lower_to_higher_mapping=None):
        # Check if this definition defines higher match from lower match. Recursive algorithm.
        # Optionally specify mapping that must be consistent.

        if self.lower is None:
            # Can't do this if we don't know the lower pattern
            return False

        if mapping is None:
            mapping = {}

        if lower_to_higher_mapping is None:
            lower_to_higher_mapping = {}

        if lower.formatted_string() in lower_to_higher_mapping and \
                not lower_to_higher_mapping[lower.formatted_string()] == higher.string:
            # Inconsistent mapping
            return False

        if (lower.definition is None and higher.definition is None) or \
                (lower.definition is not None and lower.definition.equivalent(higher.definition, context)):
            # Both definitions are the same or both None. No need to unpack, just need to check sub_matches

            if not len(lower.sub_matches) == len(higher.sub_matches):
                return False

            for key, lower_sub in lower.sub_matches.items():
                if key not in higher.sub_matches:
                    return False

                higher_sub = higher.sub_matches[key]

                # Check application inside the submatches
                if not self.check_application(lower_sub, higher_sub, context, mapping, lower_to_higher_mapping):
                    return False

            # Otherwise ok

            if len(lower.sub_matches) == 0:
                lower_to_higher_mapping[lower.formatted_string()] = higher.formatted_string()

            # Don't need to check definition variables since both lower and higher are making use of the same definition
            return True

        # Otherwise, lower and higher definitions are different. Need higher to define to lower to be valid
        if higher.definition is None or not self.equivalent(higher.definition, context, allow_mapping_to=True):
            return False

        # Higher must use this definition.

        mapping = copy(higher.sub_matches)
        result = self.lower_match_template.maps_to_up_to_definition(lower, context, mapping=mapping)
        if not result:
            return False

        # Check condition
        if self.condition is not None:

            # Update context with condition variables
            context_copy = copy(context)
            context_copy.mapping.update(mapping)

            return self.condition.check_condition(None, context_copy)

        # Otherwise ok
        return True

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
        if path == "higher()":
            return self.higher

        if path == "lower()":
            return self.lower

        if path == "pattern()":
            return self.pattern

        if path == "variables()":
            return self.variables

        if recurse:
            # Try generic get_by_path
            return get_by_path(self, path, context, recurse=False)

        raise Exception(f"Could not find value from path '{path}'.")

    def equivalent(self, other, context, memo=None, allow_mapping_to=False):
        # Check if two definitions are the same.

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, Definition):
            return False

        # Assume True when checking nested patterns - so recursive patterns can compare equal
        memo[(self, other)] = True

        if (self.lower is None and other.lower is not None) or (self.lower is not None and other.lower is None):
            return False

        if self.lower is not None and other.lower is not None:
            if not self.lower.equivalent(other.lower, context, memo, allow_mapping_to):
                memo[(self, other)] = False
                return False

        if not self.higher.equivalent(other.higher, context, memo, allow_mapping_to):
            memo[(self, other)] = False
            return False

        if not self.pattern.equivalent(other.pattern, context, memo, allow_mapping_to):
            memo[(self, other)] = False
            return False

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def get_lower(self, higher_match, context):
        # Get a lower match from the higher match

        if self.lower is None:
            # Can't do this if we don't know the lower pattern
            return False

        # Variables are from the given higher match
        variables = higher_match.sub_matches

        # Build the lower string from the pattern
        s = ""

        # First get all the locations
        var_locations = list(self.lower.variable_locations)
        non_var_locations = list(self.lower.non_variable_locations)
        locations = var_locations + non_var_locations
        locations.sort()

        for i in locations:
            if i in non_var_locations:
                s += self.lower.non_variable_locations[i]
                continue

            # i in var_locations
            label = self.lower.variable_locations[i]["label"]
            pattern = self.lower.variable_locations[i]["pattern"]

            if not (label in variables):
                raise ValueError(f"Could not build lower pattern - missing variable {label}.")

            if not (pattern.equivalent(variables[label].pattern, context, allow_mapping_to=True)):
                raise ValueError(f"Could not build lower pattern - mismatched patterns for variable {label}.")

            s += variables[label].formatted_string()

        result = self.pattern.match(s, context)

        if result is None:
            raise ValueError(f"Could not build lower pattern - no match for {s}.")

        return result

    def __str__(self):
        if self.lower is None:
            return f"Definition: '{self.higher.pattern}' is unknown for {self.pattern.name}"

        return f"Definition: '{self.higher.pattern}' is defined as '{self.lower.pattern}' for {self.pattern.name}"
