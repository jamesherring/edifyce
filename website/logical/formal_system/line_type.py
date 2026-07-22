"""The :class:`LineType` describing a category of proof line."""


class LineType:
    """Class for types of lines in formal proofs."""

    def __init__(self, name, pattern=None, behaviour="none", add_context=None, scope=None,
                 formula_field: str | None = None, reference_field: str | None = None):

        # The name of this line type
        self.name = name

        # The pattern for these lines to match (Pattern instance)
        self.pattern = pattern

        # Which matched sub-field carries the logical formula, and which the
        # citation reference: `FormalSystem.parse` projects these off the line
        # match directly. The reserved value "self" means the whole match (an
        # axiom asserting its entire formula). None means the line declares no
        # such field (e.g. a non-logical or scope-only line).
        self.formula_field = formula_field
        self.reference_field = reference_field

        # The behaviour of these lines
        self.behaviour = behaviour
        if self.behaviour not in ("none", "import", "logical", "axiom", "indent", "definition", "comment"):
            raise ValueError(f"'{self.behaviour}' is not a valid LineType behaviour.")

        # The scope this line opens, orthogonal to behaviour. A scope opener
        # starts a subproof that a discharge rule can later consume as a unit:
        #   "assumption" - opens a subproof under a hypothesis (for e.g. ->I),
        #   "variable"   - opens a subproof under a fresh variable (for e.g. VI).
        # None means the line opens no scope. Keeping this separate from
        # `behaviour` lets one line be *both* a formula-bearing logical line and
        # a scope opener - the thing the old `indent` behaviour could not be.
        self.scope = scope
        if self.scope not in (None, "assumption", "variable"):
            raise ValueError(f"'{self.scope}' is not a valid LineType scope.")

        # The data paths (and their values) to add to context, if any
        self.add_context = add_context if add_context is not None else {}

    def parse_line(self, line, context):
        # Check if the given line string is of this type
        return self.pattern.match(line, context)

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        memo[(self, other)] = False

        if type(other) is not LineType:
            return False

        if not self.name == other.name:
            return False

        if not self.behaviour == other.behaviour:
            return False

        if not self.scope == other.scope:
            return False

        if not self.formula_field == other.formula_field:
            return False

        if not self.reference_field == other.reference_field:
            return False

        if not self.add_context == other.add_context:
            return False

        # Assume true for recursive checks
        memo[(self, other)] = True

        if not self.pattern.equivalent(other.pattern, context, memo):
            memo[(self, other)] = False
            return False

        # Otherwise ok
        memo[(self, other)] = True
        return True

    def __str__(self):
        return self.name
