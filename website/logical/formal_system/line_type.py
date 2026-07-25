"""The :class:`LineType` describing a category of proof line."""


class LineType:
    """Class for types of lines in formal proofs."""

    # `behaviour` has no default: there is no value that is right to assume, and
    # every construction site knows which kind of line it is building.
    def __init__(self, name, pattern=None, *, behaviour, scope=None,
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

        # The behaviour of these lines. The set is deliberately closed to what a
        # SystemSpec can build - `logical` and `comment` from a LineSpec, `axiom`
        # from a declared axiom - so a value here can never name a line type
        # nothing constructs. Two things that look missing are handled elsewhere,
        # not by a behaviour: a definitional *step* is a `logical` line citing a
        # definition (see `proof.DEFINITION_KEY`), and a lemma from another proof
        # arrives through the `reference_context` its caller pre-seeds (see
        # app/routers/proofs.py).
        self.behaviour = behaviour
        if self.behaviour not in ("logical", "axiom", "comment"):
            raise ValueError(f"'{self.behaviour}' is not a valid LineType behaviour.")

        # A logical line is checked against its formula, so one it cannot project
        # is inert: every instance would be rejected with "No formula defined for
        # logical line." Refuse it at construction instead, where the author can
        # still act on it.
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
        # None means the line opens no scope. It is separate from `behaviour` so
        # one line can be *both* a formula-bearing logical line and a scope opener.
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
        # nests deeply costs exponentially (see UnionPattern.match). Scoped to the
        # one line rather than the proof: a line is the largest stretch over which
        # the context is known not to move, and nothing is gained by assuming more.
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
