"""Pattern classes: the base :class:`Pattern` and its concrete subclasses."""

from __future__ import annotations

import random
from bisect import bisect_left
from typing import TYPE_CHECKING

import regex as re

from . import definitions, matches

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .context import Context
    from .definitions import DefinedNotation
    from .matches import Match

    # A template segment: `(kind, text, sort, length)`. For a literal, `text` is
    # the literal itself and `sort` is None; for a slot, `text` is the slot's
    # label and `sort` the pattern that fills it. A tuple rather than a dataclass
    # because the walk unpacks one per step of every attempt.
    Segment = tuple[int, str, "Pattern | None", int]

    # Where a string's bracket delimiters sit, and the nesting depth each leaves
    # it at: two lists of the same length (see `Pattern.bracket_profile`).
    BracketProfile = tuple[list[int], list[int]]


# A template segment's kind (see StringPattern.segments).
_LITERAL = 0
_VARIABLE = 1

# Tags distinguishing a bracket answer, and a verdict on the metavariables in
# scope, from a parse in a shared memo (see Pattern.bracket_profile).
_BRACKETS = "brackets"
_METAVARIABLES = "metavariables"

# `bracket_profile`'s answer when there is no profile to give but the string is not
# at fault: the pattern declares no brackets, or declares delimiters longer than a
# character. Distinct from None, which means the string failed the check.
_NO_BRACKETS = ()


def _occurrences(s: str, text: str, start: int, limit: int) -> Iterator[int]:
    # Every position in `s[start:limit]` where `text` occurs, in increasing order.
    # A generator, because a slot's first candidate usually parses and the rest of
    # the scan is then never paid for.
    at = s.find(text, start)

    while at != -1 and at <= limit:
        yield at
        at = s.find(text, at + 1)


def _balanced_ends(
    candidates: Iterable[int], profile: BracketProfile, start: int
) -> Iterator[int]:
    # Those of `candidates` - which must increase - that leave the slot holding a
    # bracket-balanced substring of `s`, given `s`'s bracket profile.
    #
    # `s[start:end]` is balanced exactly when the nesting depth is the same at
    # both ends and never dips below it in between, so one forward pass over the
    # brackets between candidates decides all of them. The pass stops for good at
    # the first dip: that closing bracket is inside every longer span too.
    positions, levels = profile
    total = len(positions)

    at = bisect_left(positions, start)
    base = levels[at - 1] if at else 0
    floor = base

    for end in candidates:
        while at < total and positions[at] < end:
            if levels[at] < floor:
                floor = levels[at]
            at += 1

        if floor < base:
            return

        if (levels[at - 1] if at else 0) == base:
            yield end


def _metavariable_spelt_with_brackets(pattern: Pattern, context: Context) -> bool:
    # Whether any metavariable in scope is spelled with a bracket delimiter in it.
    # Practically never - but a union answers a metavariable by *name* before it
    # checks brackets, so one would be the counterexample to the reasoning in
    # `StringPattern._sort_refuses_unbalanced`, and that reasoning is what lets
    # the search skip a split rather than parse it.
    #
    # Deliberately blunter than "spelled unbalanced": the names are concatenated
    # and searched once, so the whole question costs two substring scans however
    # many metavariables a rule schema declares. Answered per parse, not per
    # candidate split; the key names the dict rather than its contents, which is
    # sound because nothing adds a metavariable during a parse.
    names = context.string_variables
    memo = context.parse_memo

    key = None
    if memo is not None:
        key = (id(names), len(names), id(pattern._respect_brackets), _METAVARIABLES)

        if key in memo:
            return memo[key]

    spelling = "".join(names)
    answer = any(delimiter in spelling for delimiter in pattern._delimiters)

    if key is not None:
        memo[key] = answer

    return answer


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

        # Declared tokens that *contain* a bracket delimiter, and so must be
        # stepped over rather than counted when brackets are profiled. Set by the
        # system builder beside `respect_brackets`; empty for every grammar whose
        # constants avoid its delimiters. See `_opaque_positions`.
        self.bracket_opaque = ()

        # Default certainty of 0
        self.certainty = 0

        # Whether some union lists this pattern as a member (see
        # `UnionPattern.add_pattern`). A union memoises what its members look
        # like — their flattening, their order, the character each may open with
        # — so a member that changes shape afterwards has to say so, and one that
        # belongs to no union has nothing to tell. That distinction is worth
        # keeping: a rule schema builds a template and parses with it
        # immediately (see `build_context.build_schema_pattern`), so invalidating
        # unconditionally would re-flatten the whole grammar once per schema.
        self.union_member = False

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

        # Every delimiter, opening and closing, for the one question asked about
        # the delimiters rather than about a string (see
        # `_metavariable_spelt_with_brackets`).
        self._delimiters = () if pairs is None else (*pairs, *pairs.values())

        # The sole pair, when there is only one - the case every bracketed system
        # in practice is (see `_one_pair_profile`).
        self._one_pair = None
        if self._opening_of is not None and len(pairs) == 1:
            self._one_pair = next(iter(pairs.items()))

    def _opaque_positions(self, s: str) -> set[int] | None:
        # The indices of `s` covered by a declared token that contains a bracket
        # delimiter, or None when the grammar has no such token.
        #
        # set.mm names its half-open intervals `[,)` and `(,]`, and thirteen more
        # of its constants spell a parenthesis (`O(1)`, `(x)`, `((`). The `)` in
        # `[,)` is part of the token, not a bracket, so counting it makes
        # `( 0 [,) +oo ) C_ RR` read as unbalanced and the formula never parses -
        # which is the same collision as a variable found inside a constant, one
        # level down. Whether a character delimits is a property of the *grammar*,
        # so the grammar is what answers it.
        if not self.bracket_opaque:
            return None

        covered: set[int] = set()
        for token in self.bracket_opaque:
            at = s.find(token)
            while at != -1:
                covered.update(range(at, at + len(token)))
                at = s.find(token, at + 1)
        return covered or None

    def brackets_respected(self, s: str, context: Context) -> bool:
        # `check_brackets`, memoised for the length of one parse.
        return self.bracket_profile(s, context) is not None

    def bracket_profile(self, s: str, context: Context) -> BracketProfile | None:
        """Where ``s``'s brackets are and how deep each leaves it, or None.

        A pair of lists — the index of each delimiter, and the nesting depth
        after it. Read-only to every caller, and memoised, so they are handed out
        live rather than copied. None means ``s`` does not respect this pattern's brackets;
        :data:`_NO_BRACKETS` means there is nothing to say (no table, or
        delimiters longer than a character) and the string is not at fault.

        The same single pass that decides whether ``s`` is balanced also answers,
        thereafter for free, every question the search asks about a *span* of it:
        ``s[a:b]`` is balanced exactly when the depth is the same at ``a`` and
        ``b`` and never dips below it in between. That is what turns "which splits
        are worth parsing at all" from a parse per candidate into a pointer walk
        (see :func:`_balanced_ends`), and it is why the check is worth memoising
        rather than merely making fast: every candidate parse of every substring
        of every formula runs it.

        Only the delimiters are recorded, not a depth per character. The formula
        is much longer than its bracket list, and building a per-character profile
        cost more than the scan it was replacing.
        """
        pairs = self._respect_brackets

        if pairs is None:
            # Nothing to respect
            return _NO_BRACKETS

        memo = context.parse_memo

        # Keyed by the bracket table rather than by the pattern - a grammar's
        # productions share one table, and the answer depends on nothing else. A
        # three-part key, so it cannot collide with the two-part parse keys.
        key = None
        if memo is not None:
            key = (id(pairs), s, _BRACKETS)

            if key in memo:
                return memo[key]

        profile = self._bracket_profile(s)

        if key is not None:
            memo[key] = profile

        return profile

    def _bracket_profile(self, s: str) -> BracketProfile | None:
        # Multi-character delimiters fall back to the general scan, which yields a
        # verdict but no profile.
        opening_of = self._opening_of

        if opening_of is None:
            return _NO_BRACKETS if self.check_brackets(s) else None

        if self._one_pair is not None:
            return self._one_pair_profile(s, *self._one_pair, self._opaque_positions(s))

        pairs = self._respect_brackets
        opaque = self._opaque_positions(s)

        positions = []
        levels = []
        stack = []
        depth = 0

        for i, character in enumerate(s):
            if opaque is not None and i in opaque:
                continue
            if character in pairs:
                stack.append(character)
                depth += 1
            elif character in opening_of:
                if not stack or stack[-1] != opening_of[character]:
                    # No corresponding opening bracket
                    return None
                stack.pop()
                depth -= 1
            else:
                continue

            positions.append(i)
            levels.append(depth)

        if stack:
            # Stack left open at the end
            return None

        return positions, levels

    @staticmethod
    def _one_pair_profile(
        s: str, opener: str, closer: str, opaque: set[int] | None = None
    ) -> BracketProfile | None:
        # One grouping pair - which is what every bracketed system here declares -
        # so the delimiters can be *found* rather than the string walked. The two
        # `find` scans run in C and the loop turns once per bracket instead of once
        # per character, which matters because this runs on every substring of
        # every formula. With one pair there is also nothing to match up: a depth
        # that never goes negative and ends at zero is the whole condition.
        positions = []
        levels = []
        depth = 0

        opening = s.find(opener)
        closing = s.find(closer)

        while True:
            if opening == -1:
                if closing == -1:
                    break
                at = closing
            elif closing == -1 or opening < closing:
                at = opening
            else:
                at = closing

            if at == opening:
                opening = s.find(opener, at + 1)
                if opaque is not None and at in opaque:
                    # Inside a declared token that merely spells a delimiter.
                    continue
                depth += 1
            else:
                closing = s.find(closer, at + 1)
                if opaque is not None and at in opaque:
                    continue
                depth -= 1

                if depth < 0:
                    # No corresponding opening bracket
                    return None

            positions.append(at)
            levels.append(depth)

        if depth:
            # Left open at the end
            return None

        return positions, levels

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
            opaque = self._opaque_positions(s)
            stack = []
            for i, character in enumerate(s):
                if opaque is not None and i in opaque:
                    continue
                if character in pairs:
                    stack.append(character)
                elif character in opening_of:
                    if not stack or stack[-1] != opening_of[character]:
                        # No corresponding opening bracket
                        return False
                    stack.pop()
            return not stack

        # Multi-character delimiters: the same opaque tokens apply, so a constant
        # spelling one is stepped over here as well as on the fast path above.
        opaque = self._opaque_positions(s)
        i = 0
        stack = []
        while i < len(s):

            if opaque is not None and i in opaque:
                i += 1
                continue

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
            if not notation.sort.equivalent(self, context):
                continue

            result = notation.match(s, context)

            if result is not None:
                return result

        # No notation works
        return None


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

    def equivalent(self, other, context, memo=None):
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

    def equivalent(self, other, context, memo=None) -> bool:
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

        # Build the non-variable locations, and everything `match` derives from
        # them on every attempt (see get_non_variable_locations).
        self.non_variable_locations = None
        self.non_variable_order = []
        self.last_variable_location = -1
        self.segments: tuple[Segment, ...] = ()
        self.segment_at_offset: dict[int, int] = {}
        self.literal_tail: tuple[int, ...] = (0,)
        self.first_literal_after: tuple[int, ...] = (-1,)
        self.has_repeated_variables = False

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

        self.build_segments()

        # Adding a variable rewrites the template's literals and its certainty,
        # which is exactly what a union's leaf order and leading-character index
        # are built from - so a member reshaped after it joined must discard
        # them, or the production stops being offered for strings it now reads.
        # (`declarative` fills a template before the union takes it, so this
        # normally never fires; the primitive is public and the ordering is not
        # something a caller should have to know.)
        if self.union_member:
            invalidate_union_memos()

    def build_segments(self) -> None:
        """Decompose the template into the slots and literals ``match`` walks.

        A ``StringPattern`` is a template with named slots — ``(a → b)`` — and
        matching is: place the literals, parse what falls between them at the
        slots' sorts. That reading was previously recovered on the fly, character
        offset by character offset, at every step of every attempt. It is a
        property of the template, so it belongs here.

        ``variable_locations`` and ``non_variable_locations`` partition the
        template exactly (``rewriting`` walks the same partition), so this is a
        total walk of it.
        """
        segments: list[Segment] = []

        i = 0
        while i < len(self.pattern):
            if i in self.variable_locations:
                location = self.variable_locations[i]
                label = location["label"]
                segments.append((_VARIABLE, label, location["pattern"], len(label)))
                i += len(label)

            elif i in self.non_variable_locations:
                part = self.non_variable_locations[i]
                segments.append((_LITERAL, part, None, len(part)))
                i += len(part)

            else:
                raise ValueError(
                    f"Offset {i} of {self.name!r} is in neither partition of its template."
                )

        self.segments = tuple(segments)
        count = len(segments)

        # Literal characters still owed from each segment on. A split leaving
        # fewer characters than this cannot complete, whatever the slots take.
        tail = [0] * (count + 1)
        for k in range(count - 1, -1, -1):
            kind, _, _, size = segments[k]
            tail[k] = tail[k + 1] + (size if kind == _LITERAL else 0)
        self.literal_tail = tuple(tail)

        # The first literal segment after each one, or -1. A slot can never end
        # past the last place that literal occurs in the string.
        following = [-1] * (count + 1)
        nearest = -1
        for k in range(count - 1, -1, -1):
            following[k] = nearest
            if segments[k][0] == _LITERAL:
                nearest = k
        self.first_literal_after = tuple(following)

        # Where each segment starts, so a caller entering mid-template
        # (`pattern_offset`) lands on a segment rather than on a character.
        self.segment_at_offset = {}
        offset = 0
        for k, segment in enumerate(segments):
            self.segment_at_offset[offset] = k
            offset += segment[3]
        self.segment_at_offset[offset] = count

        # Whether any label fills more than one slot. When none does, whether a
        # suffix matches is a function of (position, segment) alone.
        labels = [segment[1] for segment in segments if segment[0] == _VARIABLE]
        self.has_repeated_variables = len(labels) != len(set(labels))

    def match(
        self, s: str, context: Context, pattern_offset: int = 0, debug: int | None = None
    ) -> Match | None:
        # Match a string s against this pattern with the given context.
        # Optionally offset the pattern string, to start at an index > 0 - that
        # is, match `s` against the template's tail from that offset on.
        #
        # Only whole-template calls are memoised (see UnionPattern.match for why
        # there is a memo at all); a partial call is a function of the offset too,
        # and nothing repeats one.
        memo = context.parse_memo
        if memo is None or pattern_offset != 0:
            return self._match(s, context, pattern_offset, debug)

        key = (id(self), s)
        if key in memo:
            return memo[key]

        result = self._match(s, context, pattern_offset, debug)
        memo[key] = result
        return result

    def _match(
        self, s: str, context: Context, pattern_offset: int = 0, debug: int | None = None
    ) -> Match | None:
        next_debug = None
        if debug is not None:
            # Debugging
            spaces = debug * 4 * " "

            if pattern_offset == 0:
                print(spaces, "Attempting to match", s, "in", self.name, ", with pattern:", self.pattern)

            next_debug = debug + 1

        # The bracket profile of `s`, when there is one to have: both the verdict
        # on `s` itself and, once the search starts splitting it, an O(1) verdict
        # on every span of it. Only for a whole-template attempt - at an offset,
        # `s` is somebody else's tail and may legitimately be unbalanced.
        profile = None

        if pattern_offset == 0:

            profile = self.bracket_profile(s, context)

            if profile is None:
                # Brackets don't match
                return None

            if profile is _NO_BRACKETS:
                # Balanced vacuously, and with nothing to prune candidate splits by
                profile = None

            if not self.variables and s == self.pattern:
                # Match
                return matches.Match(pattern=self, string=s)

            # The whole string may be a declared metavariable, of a sort this
            # production can stand in for.
            spelled = context.string_variables.get(s)

            if spelled is not None and self.equivalent(spelled, context):
                return matches.Match(pattern=self, string=s, is_variable=True)

            # Try definitions
            result = self.try_definitions(s, context)

            if result is not None:
                # A defined notation applies
                return result

            if not self._literals_appear_in_order(s):
                # Cannot match, on the literals alone
                return None

        if not self.variables:
            # No slots: the template is a literal, and matching is string equality
            # against whatever of it is left.
            if s == self.pattern[pattern_offset:]:
                return matches.Match(pattern=self, string=s)

            return None

        segment = self.segment_at_offset.get(pattern_offset)

        if segment is None:
            raise ValueError(f"Invalid offset in StringPattern matching - matching {s} in {self.name}.")

        # One dict of bindings is threaded through the whole search and undone on
        # the way out of a dead end, rather than a Match being built at every
        # template position and merged upwards.
        bindings = {}

        # Whether a suffix matches depends on the bindings already made only when
        # a slot label repeats. With distinct labels a dead end is a dead end for
        # good, and worth remembering for the length of this attempt.
        failed = None if self.has_repeated_variables else set()

        if not self._walk(s, 0, segment, context, bindings, next_debug, failed, profile):
            return None

        m = matches.Match(pattern=self, string=s)
        for label, sub in bindings.items():
            m.add_submatch(label, sub)

        return m

    def _literals_appear_in_order(self, s: str) -> bool:
        # Whether `s` could match this template, judged on its literal parts alone
        # - a necessary condition, and a cheap one. Every literal part must occur,
        # in template order; a template opening with a literal must find it at
        # position 0, and one ending with a literal must find it at the end.
        # Nearly every candidate a union offers a production dies here, before the
        # search proper allocates anything.
        i = 0
        for index in self.non_variable_order:
            part = self.non_variable_locations[index]

            j = s.find(part, i)

            if j == -1:
                # Missing entirely
                return False

            if index == 0 and j > 0:
                # The template opens with it, so the string must too
                return False

            i = j + len(part)

        if self.non_variable_order:
            last = self.non_variable_order[-1]

            if last > self.last_variable_location and not s.endswith(self.non_variable_locations[last]):
                # The template ends with it, so the string must too
                return False

        return True

    def _walk(
        self,
        s: str,
        start: int,
        segment: int,
        context: Context,
        bindings: dict[str, Match],
        debug: int | None,
        failed: set[tuple[int, int]] | None,
        profile: BracketProfile | None,
    ) -> bool:
        # Match `s[start:]` against this template from `segment` on, recording a
        # sub-match per slot filled in `bindings` and returning whether it
        # matched; on failure `bindings` is left as it was found.
        #
        # Positions are indices into the whole of `s`, so a step neither copies
        # the string nor rebases anything it carries - which is what the walk this
        # replaced spent most of its time doing, rebuilding a table of candidate
        # literal positions at every template position it advanced past.
        #
        # NB this can't be done with a regex: a slot is filled by *parsing* a
        # substring at its declared sort, and several splits can put the same
        # literal in the same place with only one of them parsing.
        segments = self.segments
        count = len(segments)

        # Literal segments are forced. Consume them up to the next slot.
        while segment < count:
            kind, text, sort, size = segments[segment]

            if kind == _VARIABLE:
                break

            if not s.startswith(text, start):
                return False

            start += size
            segment += 1

        else:
            # Only reached when the loop ran out of segments rather than breaking
            # on a slot: the template is exhausted, so the string must be too.
            return start == len(s)

        state = (start, segment)
        if failed is not None and state in failed:
            return False

        # A metavariable spelled at this position fills the slot whole, whatever
        # else the template would let the slot take. Tried first, as the walk this
        # replaced tried it: a rule schema is read with its metavariables in
        # scope, and reading one as a formula that merely *starts* with its name
        # is never what was meant.
        for name, declared in context.string_variables.items():
            if not s.startswith(name, start):
                continue

            if not (
                declared.equivalent(sort, context)
                or (type(sort) is UnionPattern and sort.contains_pattern(declared, context, allow_nested=True))
            ):
                # Declared at a sort this slot cannot take
                continue

            sub = sort.match(name, context, debug=debug)

            if sub is None:
                continue

            if self._bind(s, start + len(name), segment, context, bindings, debug, failed, profile, sub):
                return True

        # Otherwise the slot takes a prefix of what is left, and what the template
        # owes next decides which prefixes are worth trying at all.
        for end in self._slot_candidates(s, start, segment, context, profile):

            sub = sort.match(s[start:end], context, debug=debug)

            if sub is None:
                # Nothing of that length parses at the slot's sort
                continue

            if self._bind(s, end, segment, context, bindings, debug, failed, profile, sub):
                return True

        if failed is not None:
            failed.add(state)

        return False

    def _bind(
        self,
        s: str,
        end: int,
        segment: int,
        context: Context,
        bindings: dict[str, Match],
        debug: int | None,
        failed: set[tuple[int, int]] | None,
        profile: BracketProfile | None,
        sub: Match,
    ) -> bool:
        # Fill the slot at `segment` with `sub`, then match on from `end`. Undoes
        # the binding if what follows does not match. Returns whether it did.
        label = self.segments[segment][1]

        previous = bindings.get(label)

        if previous is not None and previous.string != sub.string:
            # The label is bound to different text elsewhere in the template, and
            # one label means one substring
            return False

        bindings[label] = sub

        if self._walk(s, end, segment + 1, context, bindings, debug, failed, profile):
            return True

        if previous is None:
            del bindings[label]
        else:
            bindings[label] = previous

        return False

    def _slot_candidates(
        self,
        s: str,
        start: int,
        segment: int,
        context: Context,
        profile: BracketProfile | None,
    ) -> Iterable[int]:
        # The end positions worth trying for the slot at `segment`, in increasing
        # order - so an ambiguous template still resolves to the shortest binding,
        # as it did when this enumerated candidate positions up front.
        segments = self.segments
        count = len(segments)
        length = len(s)
        following = segment + 1

        # Whatever the slot takes, the literals still owed have to fit in what is
        # left over.
        limit = length - self.literal_tail[following]

        if limit < start:
            return ()

        if following == count:
            # Final slot: it takes the rest of the string, or nothing does
            return (length,)

        else:
            kind, text, _, size = segments[following]

            if kind == _VARIABLE:
                # Adjacent slots - nothing separates them, so every boundary is a
                # candidate. Bounded by the last place the next literal owed can
                # sit, which is often all that keeps this short of the whole
                # string.
                literal = self.first_literal_after[segment]

                if literal >= 0:
                    latest = s.rfind(segments[literal][1])

                    if latest == -1:
                        return ()

                    if latest < limit:
                        limit = latest

                candidates = range(start, limit + 1)

            elif following + 1 == count:
                # The template ends with this literal, so the string must too -
                # which fixes the slot's end exactly.
                end = length - size

                if end < start or not s.startswith(text, end):
                    return ()

                return (end,)

            else:
                candidates = _occurrences(s, text, start, limit)

        # A slot can only be filled by a bracket-balanced substring, whenever its
        # sort is bound to refuse an unbalanced one - so a split that would leave
        # it holding an unbalanced one is not worth parsing. Reading
        # `((p → q) → (r → s))` at `(a → b)`, three of the four arrows are inside
        # an operand, and every one of them was parsed before being dismissed.
        #
        # Only where the template leaves the slot's end genuinely open, which is
        # what the two returns above have already excluded: where exactly one
        # split is possible, whether it is balanced is the sub-parse's own first
        # question and asking it here as well would only be paying twice.
        if profile is None or not profile[0]:
            return candidates

        if not self._sort_refuses_unbalanced(segments[segment][2], context):
            return candidates

        return _balanced_ends(candidates, profile, start)

    def _sort_refuses_unbalanced(self, sort: Pattern, context: Context) -> bool:
        # Whether `sort` is certain to refuse a string that does not respect this
        # pattern's brackets - which is what licenses skipping such a split rather
        # than parsing it to find out.
        #
        # A union checks the table before it tries any of its members, so sharing
        # the table settles it - with one exception: a union answers a declared
        # metavariable first, by *name*, and nothing obliges a name to balance.
        # Nothing else here may be assumed to check at all: an atom and a regex
        # never do, and a production's own template is checked only at the top of
        # a whole-string attempt.
        if type(sort) is not UnionPattern:
            return False

        if sort.respect_brackets is not self._respect_brackets:
            return False

        if not context.string_variables:
            return True

        return not _metavariable_spelt_with_brackets(self, context)

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

    def equivalent(self, other, context, memo=None):
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

            if not self.variables[key].equivalent(other.variables[key], context, memo):
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


def _may_open_with(pattern: Pattern, character: str) -> bool:
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

    def __init__(self, name, patterns, respect_brackets=None):

        Pattern.__init__(self, name, respect_brackets)

        # The list of patterns
        self.patterns = patterns

        self.pattern_type = "UnionPattern"

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

        for pattern in self.patterns:
            pattern.union_member = True

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

            if self.equivalent(pattern, context):
                return matches.Match(
                    pattern=self,
                    string=s,
                    is_variable=True
                )

            for p in nested_options:
                if p.equivalent(pattern, context):

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

        if not self.brackets_respected(s, context):
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
            # A defined notation applies
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

    def add_pattern(self, pattern: Pattern) -> None:
        """Add ``pattern`` to the union, invalidating any memoised flattening."""
        self.patterns.append(pattern)
        pattern.union_member = True
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

    def match_options(
        self, context: Context
    ) -> tuple[dict, list[Pattern], list[Pattern]]:
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

    def leaf_candidates(
        self, s: str, context: Context, leaves: list[Pattern]
    ) -> list[Pattern]:
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

    def equivalent(self, other, context, memo=None):
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
            if not pattern.equivalent(other_pattern, context, memo):
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

    def equivalent(self, other, context, memo=None):
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

