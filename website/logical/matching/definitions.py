"""The :class:`Definition` linking higher- and lower-level patterns."""

from copy import copy

from . import matches, patterns


class Definition:
    """A definition linking a higher-level string pattern with a lower-level one.

    This is the *parser* half of a definition: :meth:`match` (via
    ``Pattern.try_definitions``) is what makes defined notation grammatical, so
    ``a sub b`` reads as a formula at all. It does not *apply* definitions —
    verifying that one formula is another with a definition unfolded is the
    kernel's job, against the term-based counterpart on :attr:`kernel` (see
    ``formal_system/definitions.py``). Keeping application out of here is what
    stops a second, capture-blind checker existing alongside the trusted one.
    """

    def __init__(self, lower, higher, pattern, context,
                 fresh=None, kernel_condition=None, label=None):

        # The pattern this definition applies to
        self.pattern = pattern

        # Optional name a proof cites this definition by (`[<label>, <line>]`).
        # None for an unnamed definition (still usable via the generic keyword).
        self.label = label

        # Bound variables of the defining form: {name: sort Pattern}. These are
        # the variables the lower form binds (e.g. the `z` in ∀z.(…)); declaring
        # them lets the term-based checker unfold capture-avoidingly. The sorts
        # are matching Patterns, so this stays within the matching layer. Empty
        # for an ordinary alias definition.
        self.fresh = fresh or {}

        # An optional proviso in the kernel's structural side-condition
        # vocabulary (beyond the capture-avoidance one the kernel derives from
        # `fresh`), from the definition's `where` clause. Held opaquely so the
        # matching layer keeps its no-kernel-import rule; the formal_system
        # bridge passes it to the kernel definition.
        self.kernel_condition = kernel_condition

        self.lower = None

        # The defining form exactly as it was written. `self.lower` is a *pattern*
        # derived from it, whose template renames a variable used in two roles
        # (`create_pattern`'s collision rename), so it is not always a form the
        # author would recognise. Keep the original for error messages.
        self.lower_source = lower

        # Create a higher pattern
        self.higher = patterns.StringPattern(
            name="Definition (higher)",
            pattern=higher,
            variables=copy(context.string_variables),
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

            # Store the variables in a common dictionary.
            self.variables = self.lower.variables
            self.variables.update(self.higher.variables)

        # The term-based (kernel) counterpart this definition denotes - what a
        # definitional step is actually checked against (see
        # formal_system/definitions.py). Held opaquely so the matching layer keeps
        # its no-kernel-import rule, and filled in by the system builder right
        # after the definition enters the proof context, since building it needs
        # the definition itself in scope to parse the defined form.
        #
        # None only between construction and that build. A definition that cannot
        # produce one fails the system build, so every definition a proof sees has
        # it; the engine's context copies are shallow per definition, which is what
        # carries it through to the checker.
        self.kernel = None

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

    def __str__(self):
        if self.lower is None:
            return f"Definition: '{self.higher.pattern}' is unknown for {self.pattern.name}"

        return f"Definition: '{self.higher.pattern}' is defined as '{self.lower.pattern}' for {self.pattern.name}"
