"""Pattern classes: the base :class:`Pattern` and its concrete subclasses."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import regex as re

from . import definitions, matches

if TYPE_CHECKING:
    from .context import Context
    from .definitions import DefinedNotation
    from .matches import Match


class Pattern:
    """Parent class for Pattern objects StringPattern and UnionPattern."""

    def __init__(self, name, respect_brackets=None):

        self.name = name

        # Note any bracket pairs that should be respected
        self.respect_brackets = respect_brackets

        # Whether the tokens this production yields are *constants* of the object
        # language rather than variables of it — declared by the system author, as
        # Metamath's `$c`/`$v` are. Opaque to matching, which never reads it; the
        # kernel's definition builder does (see formal_system/definitions.py),
        # exactly as with `StringPattern.schema_term`.
        #
        # Deliberately not `is_constant`: `AtomPattern.is_constant` asks a purely
        # structural question (one literal token, or an indexed family?) and the
        # two answers differ — a constant-shaped atom declared as a member of the
        # variable sort is bindable, so it is *not* an object-language constant.
        #
        # False is the safe default: an undeclared leaf is treated as a variable,
        # so a definition introducing it is refused rather than excused.
        self.denotes_constant = False

        # Memo slot for the kernel's projection of this production (see
        # kernel.constructors). Filled by the kernel on first use and *owned by
        # this pattern*, so it lives and dies with the production. A module-level
        # cache cannot: a grammar is mutually recursive, so a constructor's slot
        # sorts reach back to the production it was built from, and any strong
        # global root keeps the whole graph alive for the process's lifetime.
        # Opaque to matching, which never reads it — as with `schema_term`.
        self.kernel_constructor = None

        # Default certainty of 0
        self.certainty = 0

        # Arbitrary id for use in URLs
        self.url_id = "".join(random.SystemRandom().choice("0123456789abcdef") for _ in range(8))

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

    def add_notation(self, defined: str, context: Context) -> DefinedNotation:
        # Register `defined` as a production of this sort - the grammatical half
        # of a definition, and all of it the matching layer needs (see
        # DefinedNotation). What the notation unfolds to is the kernel's
        # business; the system builder pairs the two.
        #
        # Returns the notation now in `context`, which may be one registered
        # earlier: the same template for the same sort is one production however
        # many definitions declare it.

        notation = definitions.DefinedNotation(defined, self, context)

        for existing in context.definitions:
            if existing.equivalent(notation, context):
                return existing

        context.definitions.add(notation)

        return notation

    def try_definitions(self, s: str, context: Context) -> Match | None:
        # Try the defined notations in scope to see if one gives a match for s.
        # Called after this pattern's own productions, so defined notation can
        # never shadow a primitive one.

        for notation in context.definitions:
            if not notation.sort.can_map_to(self, context):
                continue

            result = notation.match(s, context)

            if result is not None:
                return result

        # No notation works
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

        # Build the non-variable locations
        self.non_variable_locations = None

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

    def match(self, s, context, pattern_offset=0, non_variable_mapping=None, debug=None):
        # Match a string s against this pattern with the given context.
        # Optionally offset the pattern string, to start at an index > 0. This is used recursively.

        # Optionally specify non variable mapping.

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
                # A defined notation applies
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


class UnionPattern(Pattern):
    """A union of patterns."""

    def __init__(self, name, patterns, respect_brackets=None, inherits=None):

        Pattern.__init__(self, name, respect_brackets)

        # The list of patterns
        self.patterns = patterns

        self.pattern_type = "UnionPattern"

        # Inherits from a previous unionpattern
        self.inherits = inherits

    def match(self, s, context, debug=None):
        # Match s against one of the patterns.

        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "
            print(spaces, "Attempting to match", s, " in ", self.name, ", a UnionPattern.")
            next_debug = debug + 1

        # Get the nested options
        nested_options = self.nested_options(context, path_dict=True)

        pattern_options = [p for p in nested_options if not isinstance(p, UnionPattern)]

        # Sort the patterns by decreasing certainty
        pattern_options.sort(key=lambda x: x.certainty, reverse=True)

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

        for pattern in pattern_options:

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
            # A defined notation applies
            return result

        # Try union patterns - they may have definitions on lower union patterns
        union_options = [p for p in nested_options if isinstance(p, UnionPattern)]

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

    def add_variables(self, variable_dict):
        # Add variables to all patterns in the union

        for pattern in self.patterns:
            if type(pattern) is UnionPattern:
                pattern.add_variables(variable_dict)

            elif type(pattern) is StringPattern:
                pattern.add_variables(variable_dict)

    def nested_options(self, context, path_dict=False):
        # Get a set of all patterns in this union - and any sub-unions
        # Optionally return as a dictionary including the paths to each option

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

        return found

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

        if not allow_nested:
            for pattern in self.patterns:
                if pattern.equivalent(other, context):
                    return True

            return False

        # Otherwise check all nested options
        for pattern in self.nested_options(context):
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

