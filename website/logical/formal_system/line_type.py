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

        # The behaviour of these lines. There is deliberately no "definition"
        # behaviour: a definition belongs to the *system*, built once from its
        # SystemSpec and reaching every proof through the shared context. A line
        # that introduced one would have to register it into the proof context at
        # parse time, which nothing has done since the accessor mechanism that
        # supplied its payload was removed - so the value could only ever produce
        # lines that fail closed. A definitional *step* needs no such line: it is
        # a `logical` line citing a definition (see `proof.DEFINITION_KEY`).
        self.behaviour = behaviour
        if self.behaviour not in ("none", "import", "logical", "axiom", "comment"):
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
        # Check if the given line string is of this type.
        #
        # Reading one line is a closed question - the grammar, definitions and
        # string variables it is answered against are whatever they are when the
        # line is read, and none of them move while it is being read - so the
        # substring parses can be memoised. Without that, a line whose formula
        # nests deeply costs exponentially (see UnionPattern.match). The memo is
        # per line, not per proof, so a definition a proof introduces between
        # lines is still seen by the lines after it.
        # Set and restore rather than copy the context: copying one is not cheap,
        # and this runs per line per candidate line type.
        previous = context.parse_memo
        context.parse_memo = {}
        try:
            return self.pattern.match(line, context)
        finally:
            context.parse_memo = previous

    def __str__(self):
        return self.name
