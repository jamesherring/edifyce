"""The :class:`LineType` describing a category of proof line."""


class LineType:
    """Class for types of lines in formal proofs."""

    def __init__(self, name, pattern=None, behaviour="none", scope=None,
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
        if self.behaviour not in ("none", "import", "logical", "axiom", "definition", "comment"):
            raise ValueError(f"'{self.behaviour}' is not a valid LineType behaviour.")

        # A logical line is checked against its formula, so one it cannot project
        # is inert: every instance would be rejected with "No formula defined for
        # logical line." Refuse it at construction instead, where the author can
        # still act on it. Only the retired `.edi` compiler could build one.
        if self.behaviour == "logical" and self.formula_field is None:
            raise ValueError(
                f"Logical line type '{self.name}' declares no formula field, so no "
                f"line of it could ever be checked; give it one, or make it a "
                f"comment."
            )

        # The scope this line opens, orthogonal to behaviour. A scope opener
        # starts a subproof that a discharge rule can later consume as a unit:
        #   "assumption" - opens a subproof under a hypothesis (for e.g. ->I),
        #   "variable"   - opens a subproof under a fresh variable (for e.g. VI).
        # None means the line opens no scope. Keeping this separate from
        # `behaviour` lets one line be *both* a formula-bearing logical line and
        # a scope opener - which the retired `indent` behaviour could not be.
        self.scope = scope
        if self.scope not in (None, "assumption", "variable"):
            raise ValueError(f"'{self.scope}' is not a valid LineType scope.")

    def parse_line(self, line, context):
        # Check if the given line string is of this type
        return self.pattern.match(line, context)

    def __str__(self):
        return self.name
