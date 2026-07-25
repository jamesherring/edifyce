"""Pattern classes: the base :class:`Pattern` and its concrete subclasses."""

import random

import regex as re

from . import definitions, matches


class Pattern:
    """Parent class for Pattern objects StringPattern and UnionPattern."""

    def __init__(self, name, respect_brackets=None):

        self.name = name

        # Note any bracket pairs that should be respected
        self.respect_brackets = respect_brackets

        # Default certainty of 0
        self.certainty = 0

        # Arbitrary id for use in URLs
        self.url_id = "".join(random.SystemRandom().choice("0123456789abcdef") for _ in range(8))

    @property
    def respect_brackets(self):
        return self._respect_brackets

    @respect_brackets.setter
    def respect_brackets(self, pairs):
        # A property only so that assigning the pairs - which the declarative
        # builder does after construction - keeps the reverse map below in step.
        self._respect_brackets = pairs

        # Closing -> opening, when every delimiter is a single character; None
        # otherwise, leaving check_brackets its general scan. Derived here because
        # check_brackets runs on every candidate parse of every formula, where
        # even measuring the delimiters costs as much as the scan itself.
        self._opening_of = None
        if pairs and all(len(opening) == 1 and len(closing) == 1 for opening, closing in pairs.items()):
            self._opening_of = {closing: opening for opening, closing in pairs.items()}

    def check_brackets(self, s):
        # Return a boolean indicating if the string s respects brackets

        pairs = self._respect_brackets
        if pairs is None:
            # Vacuously true
            return True

        # Single-character delimiters: walk the characters and look each one up,
        # rather than re-slicing the string once per bracket pair per character.
        opening_of = self._opening_of
        if opening_of is not None:
            stack = []
            for character in s:
                if character in pairs:
                    stack.append(character)
                elif character in opening_of:
                    if not stack or stack[-1] != opening_of[character]:
                        # No corresponding opening bracket
                        return False
                    stack.pop()
            return not stack

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

    def may_contain(self, other, context, found=None):
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
            # AbstractPattern or RegexPattern
            return False

        for sub_pattern in sub_patterns:
            if sub_pattern.equivalent(other, context):
                return True

            if sub_pattern.may_contain(other, context, found):
                return True

        return False

    def add_definition(self, lower, higher, context, require_lower_match=True,
                       fresh=None, kernel_condition=None, label=None):
        # Add a definition to this pattern

        # If require_lower_match is False, the lower string will not be checked against the pattern. This helps avoid
        # needing to keep chains of nested definitions in context

        # fresh: {name: sort Pattern} for the defining form's bound variables;
        # kernel_condition: an optional kernel-vocabulary proviso. Both are for
        # the term-based checker (see formal_system/definitions.py) and default
        # to none, so alias definitions are unaffected. label: an optional name a
        # proof cites the definition by.

        if require_lower_match and self.match(lower, context) is None:
            # No match with lower
            return None

        try:
            defn = definitions.Definition(lower, higher, self, context,
                                          fresh=fresh, kernel_condition=kernel_condition, label=label)
        except Exception:
            if not require_lower_match:
                # Try without the lower match
                defn = definitions.Definition(None, higher, self, context,
                                              fresh=fresh, kernel_condition=kernel_condition, label=label)
            else:
                return None

        for d in context.definitions:
            if d.equivalent(defn, context) and d.label == defn.label:
                # This definition has already been created under the same name.
                # Definitions that are structurally equal but carry *different*
                # labels are kept apart, so each name stays citable (equivalence
                # does not consider the label).
                return d

        context.definitions.add(defn)

        return defn

    def try_definitions(self, s, context):
        # Try definitions to see if they can give a match for s

        for definition in context.definitions:
            if not definition.pattern.can_map_to(self, context):
                continue

            result = definition.match(s, context)

            if result is not None:
                return result

        # No definitions work
        return None

    def can_map_to(self, other, context, check_equivalent=True):
        # Check if this pattern can map to the other pattern, taking into account pattern inheritance.

        if check_equivalent and self.equivalent(other, context, allow_mapping_to=True):
            # Easy case. Use check_equivalent to avoid infinite recursion
            return True

        # More fundamental patterns can map to inherited patterns, but not the other way around

        if hasattr(other, "inherits"):
            return self.can_map_to(other.inherits, context)

        # Otherwise false
        return False


class RegexPattern(Pattern):
    """RegEx pattern matching."""

    def __init__(self, name, pattern):

        Pattern.__init__(self, name)

        self.pattern = pattern

        self.pattern_type = "RegexPattern"

    def match(self, s, context, debug=None):
        # Try to match a string s with the pattern

        for re_match in re.finditer(self.pattern, s, overlapped=True):

            if re_match is None:
                # No match
                continue

            m = matches.Match(
                pattern=self,
                string=s
            )
            return m

        # No matches
        return None

    def equivalent(self, other, context, memo=None, allow_mapping_to=False):
        # Check equivalence

        if memo is None:
            memo = {}

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
        return f"RegexPattern: {self.name}"


class AtomPattern(Pattern):
    """An atomic-leaf sort: a constant, or an infinite base+index family.

    This is the going-forward replacement for using :class:`RegexPattern` to
    declare atoms. Two modes:

    * **constant** - matches exactly one literal token (e.g. the falsum ``⊥``,
      the empty set ``∅``, the numeral ``0``).
    * **indexed family** - a base token with an optional natural-number index,
      giving a *countably infinite* supply of atoms without a regex engine:
      base ``p`` matches ``p``, ``p_0``, ``p_1``, ``p_2``, …. Because the family
      is generated rather than merely recognised, a *fresh* atom can be
      constructed (``fresh``), not just tested - which is exactly what
      eigenvariable selection wants.

    An atom always matches to a childless leaf, so it is a genuine atomic term
    for the kernel's structural side-conditions (occurrence, disjoint-leaves).
    """

    def __init__(self, name, value: str | None = None, base: str | None = None) -> None:

        Pattern.__init__(self, name)

        # Exactly one of `value` (constant) or `base` (indexed family) is set.
        if (value is None) == (base is None):
            raise ValueError("AtomPattern needs exactly one of `value` or `base`.")

        self.value = value
        self.base = base

        self.pattern_type = "AtomPattern"

    @property
    def is_constant(self) -> bool:
        return self.value is not None

    def is_member(self, token: str) -> bool:
        # Whether `token` is an atom of this pattern.
        if self.is_constant:
            return token == self.value

        # Indexed family: the bare base, or base + "_" + a natural number.
        if token == self.base:
            return True
        prefix = f"{self.base}_"
        if not token.startswith(prefix):
            return False
        index = token[len(prefix):]
        # A canonical non-negative integer (no sign, no leading zeros beyond "0").
        return index.isdigit() and (index == "0" or index[0] != "0")

    def match(self, s, context, debug=None) -> "matches.Match | None":
        # Match a whole token against this atom. Leaf match, no sub-matches.
        token = s

        if not self.is_member(token):
            return None

        return matches.Match(pattern=self, string=s)

    def fresh(self, used) -> str:
        # Construct an atom of this family not present in `used` (an iterable of
        # tokens). Only meaningful for an indexed family. This is the
        # constructive advantage over a recogniser: there is always a next one.
        if self.is_constant:
            raise ValueError("A constant atom has no fresh instances.")

        used = set(used)
        index = 0
        while f"{self.base}_{index}" in used:
            index += 1
        return f"{self.base}_{index}"

    def equivalent(self, other, context, memo=None, allow_mapping_to=False) -> bool:
        # Two atoms are equivalent when they are the same constant or the same
        # family. Name is deliberately not compared: identity is what the atom
        # denotes, so a rule's inline literal and the system's declared atom of
        # the same value/base agree.
        if not isinstance(other, AtomPattern):
            return False
        return self.value == other.value and self.base == other.base

    def __str__(self):
        return f"AtomPattern: {self.name}"


class StringPattern(Pattern):
    """A string pattern created in compiling lattice"""

    def __init__(self, name, pattern, variables=None, respect_brackets=None):

        Pattern.__init__(self, name, respect_brackets)

        # The pattern string
        self.pattern = pattern

        # An optional precomputed nested kernel Term for a rule-schema template,
        # set at build time (build_context.compose_schema_term) and consumed by the checker;
        # opaque to the matching layer, which never reads it (matching must not
        # depend on the kernel). None for any pattern that is not a compound
        # rule schema. Declared here so consumers use `pattern.schema_term`
        # directly rather than a defaulting getattr.
        self.schema_term = None

        # The display pattern. May be different to pattern depending on format
        self.display_pattern = pattern

        # Variables for sub patterns - a dictionary mapping to other StringPatterns or UnionPattern objects
        self.variables = {}

        # Display variables
        self.display_variables = {}

        # Record the variable locations for speed
        self.variable_locations = {}

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

        # Build the non-variable locations, and the two orderings over them that
        # `match` walks on every attempt (see get_non_variable_locations).
        self.non_variable_locations = None
        self.non_variable_order = []
        self.last_variable_location = -1

        # Artificially infinite certainty
        self.certainty = 10000
        self.get_non_variable_locations()

        self.pattern_type = "StringPattern"

    def get_non_variable_locations(self):

        var_locations = list(self.variable_locations)

        self.non_variable_locations = {}
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

        # The literal parts in positional order, and the last position a variable
        # occupies. Both follow from the locations just built and `match` needs
        # them on every attempt, so derive them here instead of re-sorting the
        # pattern a million times over a run.
        self.non_variable_order = sorted(self.non_variable_locations)
        self.last_variable_location = max(self.variable_locations, default=-1)

    def match(self, s, context, pattern_offset=0, non_variable_mapping=None, debug=None):
        # Match a string s against this pattern with the given context.
        # Optionally offset the pattern string, to start at an index > 0. This is used recursively.

        # Optionally specify non variable mapping.
        #
        # Only whole-pattern calls are memoised (see UnionPattern.match for why
        # there is a memo at all): a partial call carries a `non_variable_mapping`
        # already shifted for its caller, so its result is not a function of
        # `(self, s)` alone.
        memo = context.parse_memo
        if memo is None or pattern_offset != 0 or non_variable_mapping is not None:
            return self._match(s, context, pattern_offset, non_variable_mapping, debug)

        key = (id(self), s)
        if key in memo:
            return memo[key]

        result = self._match(s, context, pattern_offset, non_variable_mapping, debug)
        memo[key] = result
        return result

    def _match(self, s, context, pattern_offset=0, non_variable_mapping=None, debug=None):
        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "

            if pattern_offset == 0:
                print(spaces, "Attempting to match", s, "in", self.name, ", with pattern:", self.pattern)

            next_debug = debug + 1

        string_variables = context.string_variables

        if pattern_offset == 0 and not self.check_brackets(s):
            # Brackets don't match
            return None

        # Create an optimistic match
        m = matches.Match(
            pattern=self,
            string=s
        )

        if pattern_offset == 0:
            if len(self.variables) == 0 and s == self.pattern:
                # Match
                return m

            # Check if the whole string is a variable
            for svar, sub_pattern in string_variables.items():
                if s == svar and self.can_map_to(sub_pattern, context):
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
            indices = self.non_variable_order

            i = 0
            for index in indices:
                part = self.non_variable_locations[index]

                # Find the next occurrence of the part
                j = s.find(part, i)

                if j == -1:
                    # No match
                    return None

                if index == 0 and j > 0:
                    # Also no match
                    return None

                i = j + len(part)

            # Check the end of the pattern
            if len(indices) > 0:
                last_non_variable = indices[-1]

                if last_non_variable > self.last_variable_location:
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
                next_index = s.find(pattern_part, index)

                # Add to non variable mapping
                non_variable_mapping.append([part_index, [next_index]])

                if next_index == -1:
                    return None

                index = next_index + 1

            # Add any other legal non variable mappings
            for i in range(len(non_variable_mapping) - 1, -1, -1):
                part_index, lst = non_variable_mapping[i]
                start_index = lst[0]
                pattern_part = self.non_variable_locations[part_index]

                max_index = len(s)
                if i < len(non_variable_mapping) - 1:
                    # There is a next item
                    max_index = non_variable_mapping[i + 1][1][-1]

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
                        (type(sub_pattern) is UnionPattern and sub_pattern.contains_pattern(str_pattern, context, allow_nested=True)):
                        # (type(sub_pattern) is UnionPattern and str_pattern in sub_pattern.nested_options(context)):
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
                if not (next_offset in self.non_variable_locations):
                    raise ValueError(f"Invalid offset in StringPattern matching - matching {s} in {self.name}.")

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

                # Min key is the position of the next non-variable part in the pattern
                min_key = min(keys)

                # max_j
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
            if name in self.pattern:
                self.add_variable(name, var)

    def reset_variables(self):
        # Reset the variables on this pattern

        variables = self.variables

        # Clear the variable locations. Non variable locations taken care of automatically
        self.variables = {}
        self.variable_locations = {}

        self.display_variables = {}

        # Add the variables
        self.add_variables(variables)

    def set_pattern(self, pattern):
        # Reset the pattern string

        self.display_pattern = pattern
        self.pattern = pattern

        # Reset variables
        self.reset_variables()

    def equivalent(self, other, context, memo=None, allow_mapping_to=False):
        # Check if two patterns are the same

        if self is other:
            # A pattern is equivalent to itself. Worth saying up front: grammars
            # share pattern objects heavily, so this is the common case, and the
            # structural walk below would descend the whole tree to agree.
            return True

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        if allow_mapping_to and self.can_map_to(other, context, check_equivalent=False):
            return True

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, StringPattern):
            return False

        if not self.name == other.name:
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

            if not self.variables[key].equivalent(other.variables[key], context, memo, allow_mapping_to):
                memo[(self, other)] = False
                return False

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def __str__(self):
        return f"StringPattern: {self.name}"


# Bumped whenever any union's membership or shape changes. Flattening a union is
# memoised per union, and a memo is trusted only while this has not moved since
# it was taken - so a *nested* union growing invalidates its containers too,
# without anyone having to track who contains whom. Deliberately global and
# deliberately blunt: unions only change while a system is being assembled, so on
# the hot path of checking proofs the count simply never moves.
_union_revision = 0


def invalidate_union_memos() -> None:
    """Discard every memoised union flattening. Call after reshaping a union."""
    global _union_revision
    _union_revision += 1


def _may_open_with(pattern, character):
    # Whether `pattern` could match a string beginning with `character`.
    #
    # A StringPattern whose template opens with a literal must find that literal
    # at position 0 (see StringPattern.match, which rejects when its leading
    # non-variable part is found anywhere else). An AtomPattern matches only the
    # whole token it denotes - its constant, or its family's base, optionally
    # `_<n>` - so that token's first character decides. This second case carries
    # most of the pruning on a set.mm import, where all but a hundred or so of the
    # 1,346 `class` productions are nullary constants (`RR`, `sin`, `2`).
    #
    # Anything else - a template opening with a variable, a RegexPattern - could
    # open with anything and stays a candidate.
    if type(pattern) is StringPattern:
        literal = pattern.non_variable_locations.get(0)
        return literal is None or literal[0] == character

    if type(pattern) is AtomPattern:
        token = pattern.value if pattern.is_constant else pattern.base
        return not token or token[0] == character

    return True


class UnionPattern(Pattern):
    """A union of patterns."""

    def __init__(self, name, patterns, respect_brackets=None, inherits=None):

        Pattern.__init__(self, name, respect_brackets)

        # The list of patterns
        self.patterns = patterns

        self.pattern_type = "UnionPattern"

        # Inherits from a previous unionpattern
        self.inherits = inherits

        # Memos for the flattening of this union, each paired with the revision it
        # was computed at. Flattening is quadratic in the union's size and was
        # re-run on *every* match, so a grammar of any real size paid it thousands
        # of times over. See `nested_options` and `match_options`.
        self._nested_options_cache: dict = {}
        self._match_options_cache: tuple | None = None

        # Leaves grouped by the first character they can match, filled per
        # character as strings arrive. See `leaf_candidates`.
        self._leaf_index: dict = {}
        self._leaf_index_revision: int | None = None

        # A union built from members that already exist elsewhere can appear
        # inside a flattening taken a moment ago.
        invalidate_union_memos()

    def match(self, s, context, debug=None):
        # Match s against one of the patterns.
        #
        # Parsing a compound formula tries every way of splitting it across a
        # production's variable slots, and re-parses the same substring under each
        # - so a deeply nested formula costs exponentially without a memo. The
        # caller opts in by setting `context.parse_memo`, which asserts that
        # nothing the result depends on (the grammar, `definitions`,
        # `string_variables`) changes for the duration of that parse.
        memo = context.parse_memo
        if memo is None:
            return self._match(s, context, debug)

        key = (id(self), s)
        if key in memo:
            return memo[key]

        result = self._match(s, context, debug)
        memo[key] = result
        return result

    def _match(self, s, context, debug=None):
        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "
            print(spaces, "Attempting to match", s, " in ", self.name, ", a UnionPattern.")
            next_debug = debug + 1

        # Get the nested options, the leaves in certainty order, and the sub-unions
        nested_options, pattern_options, union_options = self.match_options(context)

        string_variables = context.string_variables

        if s in string_variables:
            pattern = string_variables[s]

            if self.can_map_to(pattern, context):
                return matches.Match(
                    pattern=self,
                    string=s,
                    is_variable=True
                )

            # Also check for match against inherited patterns
            if self.inherits is not None:
                result = self.inherits.match(s, context, debug)
                if result is not None:
                    return result

            for p in nested_options:
                if p.equivalent(pattern, context, allow_mapping_to=True):

                    m = matches.Match(
                        pattern=pattern,
                        string=s,
                        is_variable=True
                    )

                    for q in nested_options[p]:
                        next_match = matches.Match(
                            pattern=q,
                            string=s
                        )
                        next_match.add_submatch(m.pattern.name, m)

                        m = next_match

                    return m

        if not self.check_brackets(s):
            # Brackets don't match
            return None

        for pattern in self.leaf_candidates(s, context, pattern_options):

            # Try to match the pattern
            result = pattern.match(s, context, debug=next_debug)

            if result is None:
                # No match
                continue

            # Successful match - but result is not a union match

            # Add a chain of matches if pattern is nested
            for q in nested_options[pattern]:
                next_match = matches.Match(
                    pattern=q,
                    string=s
                )
                next_match.add_submatch(result.pattern.name, result)

                result = next_match

            return result

        # Try definitions
        result = self.try_definitions(s, context)

        if result is not None:
            # Definition applies
            return result

        # Try union patterns - they may have definitions on lower union patterns
        for pattern in union_options:
            result = pattern.try_definitions(s, context)

            if result is None:
                continue

            # Successful match!

            # Add a chain of matches if pattern is nested
            for q in nested_options[pattern]:
                next_match = matches.Match(
                    pattern=q,
                    string=s
                )
                next_match.add_submatch(result.pattern.name, result)

                result = next_match

            return result

        # No match
        return None

    def add_pattern(self, pattern):
        """Add ``pattern`` to the union, invalidating any memoised flattening."""
        self.patterns.append(pattern)
        invalidate_union_memos()

    def add_variables(self, variable_dict):
        # Add variables to all patterns in the union

        # Members are about to change shape, and a flattening dedupes them by
        # structural equivalence, so every memo taken so far is suspect - not only
        # this union's. (Systems are fully assembled before any proof is checked,
        # so this costs nothing on the hot path.)
        invalidate_union_memos()

        for pattern in self.patterns:
            if type(pattern) is UnionPattern:
                pattern.add_variables(variable_dict)

            elif type(pattern) is StringPattern:
                pattern.add_variables(variable_dict)

    def nested_options(self, context, path_dict=False):
        # Get a set of all patterns in this union - and any sub-unions
        # Optionally return as a dictionary including the paths to each option
        #
        # Flattening compares every candidate against everything already found
        # using structural `equivalent`, so it is quadratic in the size of the
        # union - and `match` calls it for every formula it parses. Memoise it,
        # against the revision that says no union has changed since (see
        # `invalidate_union_memos`). The result is handed out live: every caller
        # in the codebase only reads it, and copying a flattened grammar per parse
        # was itself a measurable cost. Treat it as read-only.
        cached = self._nested_options_cache.get(path_dict)
        if cached is not None and cached[0] == _union_revision:
            return cached[1]

        # Start with an empty set
        found = set()

        def pattern_in_set(patt, phi):
            # Check if the set phi contains the given pattern

            for item in phi:
                if patt.equivalent(item, context):
                    return True

            return False

        def add_pattern_to_set(patt, phi):
            # Add a pattern to phi
            if not pattern_in_set(patt, phi):
                phi.add(patt)

        def add_patterns_to_set(patts, phi):
            # Add the patterns to phi
            for patt in patts:
                add_pattern_to_set(patt, phi)

        if path_dict:
            # It's a dictionary instead
            found = {}

        for p in self.patterns:

            if type(p) is UnionPattern and not pattern_in_set(p, found):

                sub_options = p.nested_options(context, path_dict)

                if path_dict:

                    # Append the sub paths to the dictionary, adding self
                    for pattern in sub_options:

                        already_in_found = False
                        for q in found:
                            if pattern.equivalent(q, context):
                                # Exists in found already
                                already_in_found = True

                                if len(sub_options[pattern]) < len(found[q]):
                                    # New option is shorter anyway
                                    found[pattern] = sub_options[pattern] + [self]

                                else:
                                    # Keep the original
                                    found[pattern].append(self)

                                break

                        if not already_in_found:
                            # Does not exist in found yet
                            found[pattern] = sub_options[pattern] + [self]

                else:
                    # found = found.union(sub_options)
                    add_patterns_to_set(sub_options, found)

            if path_dict:
                already_in_found = False
                for item in found:
                    if item.equivalent(p, context):
                        # Exists in found already
                        already_in_found = True
                        found[item] = self
                        break

                if not already_in_found:
                    found[p] = [self]

            else:
                add_pattern_to_set(p, found)

        self._nested_options_cache[path_dict] = (_union_revision, found)
        return found

    def match_options(self, context):
        """The flattening `match` reads: paths, then leaves by certainty, then unions.

        Splitting the flattening into the two lists `match` walks, and ordering the
        leaves, depends only on the union's shape - but `match` did it per formula
        parsed, filtering and sorting the whole grammar each time. Memoised
        alongside `nested_options`, and read-only for the same reason.
        """
        cached = self._match_options_cache
        if cached is not None and cached[0] == _union_revision:
            return cached[1]

        options = self.nested_options(context, path_dict=True)
        leaves = [p for p in options if not isinstance(p, UnionPattern)]
        leaves.sort(key=lambda pattern: pattern.certainty, reverse=True)
        unions = [p for p in options if isinstance(p, UnionPattern)]

        self._match_options_cache = (_union_revision, (options, leaves, unions))
        return options, leaves, unions

    def leaf_candidates(self, s, context, leaves):
        """Those of `leaves` that could match a string starting as `s` does.

        A production that opens with a literal can only read a string opening
        with that literal, so one character rules most of a large grammar out -
        and `match` was trying every leaf for every formula, which is what made
        the cost of a parse grow with the size of the grammar rather than with
        the formula. Grouped per first character, on demand, and rebuilt when a
        union changes (see `invalidate_union_memos`).

        Falls back to every leaf wherever that reasoning does not hold: when
        definitions are in scope, since a leaf can match through an unfold its
        template does not predict; and when `s` is itself a string variable,
        which any leaf matches whatever its template says. Both are decided here
        rather than inside `_may_open_with`, because they are properties of the
        string and the context, not of the leaf.
        """
        if not s or context.definitions or s in context.string_variables:
            return leaves

        if self._leaf_index_revision != _union_revision:
            self._leaf_index = {}
            self._leaf_index_revision = _union_revision

        candidates = self._leaf_index.get(s[0])
        if candidates is None:
            # Filtering preserves the certainty order `match_options` established.
            candidates = [leaf for leaf in leaves if _may_open_with(leaf, s[0])]
            self._leaf_index[s[0]] = candidates
        return candidates

    def inherits_from(self, other, context):
        # Check if this pattern inherits from another

        if self.inherits is None:
            return False

        if self.inherits.equivalent(other, context):
            return True

        # Could be nested inheritance
        return self.inherits.inherits_from(other, context)

    def equivalent(self, other, context, memo=None, allow_mapping_to=False):
        # Check if two patterns are the same

        if self is other:
            # A pattern is equivalent to itself. Worth saying up front: grammars
            # share pattern objects heavily, so this is the common case, and the
            # structural walk below would descend the whole tree to agree.
            return True

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        if allow_mapping_to and self.can_map_to(other, context, check_equivalent=False):
            return True

        # Assume False to save lines
        memo[(self, other)] = False

        if not isinstance(other, UnionPattern):
            return False

        if not self.name == other.name:
            return False

        if not self.respect_brackets == other.respect_brackets:
            return False

        if not len(self.patterns) == len(other.patterns):
            return False

        # Assume True for nested checks
        memo[(self, other)] = True

        # Patterns must be in the same order
        for pattern, other_pattern in zip(self.patterns, other.patterns):
            if not pattern.equivalent(other_pattern, context, memo, allow_mapping_to):
                memo[(self, other)] = False
                return False

        # Looks ok
        return True

    def contains_pattern(self, other, context, allow_nested=False):
        # Check if the union pattern includes a pattern equivalent to other

        options = self.patterns if not allow_nested else self.nested_options(context)

        # A pattern is nearly always asked about by the very object the union
        # holds - a sort checked against a term built from that sort - and a
        # pattern is trivially equivalent to itself. Patterns hash by identity, so
        # this settles the common case without a structural walk per member.
        if other in options:
            return True

        for pattern in options:
            if pattern.equivalent(other, context):
                return True

        return False

    def __str__(self):
        return f"UnionPattern: {self.name}"


class AbstractPattern(Pattern):
    """Abstract string pattern - used only as a variable."""

    def __init__(self, name):

        Pattern.__init__(self, name)

        # Arbitrary infinite certainty
        self.certainty = 1000000

        self.pattern_type = "AbstractPattern"

    def match(self, s, context, debug=None):
        # Try to match s in the given context

        # s only matches if there is a string variable of this pattern
        if s in context.string_variables and self.equivalent(context.string_variables[s], context):
            return matches.Match(
                pattern=self,
                string=s,
                is_variable=True
            )

        return None

    def equivalent(self, other, context, memo=None, allow_mapping_to=False):
        # Check equivalence - depends only on name

        if memo is None:
            memo = {}

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
        return f"AbstractPattern: {self.name}"

