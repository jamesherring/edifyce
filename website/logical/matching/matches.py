"""The :class:`Match`: what a pattern produces when it parses a string.

A ``Match`` is a *parse record* and nothing more — the constructor that matched,
the substring it matched, its named sub-matches, and (for a match made through
defined notation) the definition that licensed it. Its whole job is to be handed
to :func:`website.logical.kernel.terms.from_match`, which projects it into a
kernel :class:`~website.logical.kernel.terms.Term`; every operation *on* the
structure — equality, matching, substitution, rendering — belongs to the kernel
and happens on terms.

It did not always. This class used to carry a second implementation of each of
those: ``equivalent`` (a tri-valued structural equality), ``maps_to`` and the
``MatchSet`` it returned mappings over (a matcher), ``replace``/``reset_string``
(substitution and rendering). ``kernel.unify``'s preamble names them as the
near-duplicate tree-walks it replaced, and once proof checking moved onto terms
nothing outside this module called them again. Keeping a match inert is what
stops that second checker growing back.
"""

from copy import copy


class Match:
    """A pattern's parse of a string."""

    def __init__(self, pattern, string, is_variable=False, definition=None):

        self.pattern = pattern
        self.string = string

        # Is this a variable match?
        self.is_variable = is_variable

        # Sub-matches, keyed by the template slot they filled
        self.sub_matches = {}

        # The definition that licensed this match, for one made through defined
        # notation (see Definition.match). None for an ordinary production.
        self.definition = definition

    def add_submatch(self, var, m):
        self.sub_matches[var] = m

    def field(self, name):
        # Project a declared sub-field off this match by name - a line type's
        # formula_field / reference_field. This is the sole surviving use of the
        # retired get_by_path interpreter, reduced to the direct sub-match lookup
        # it always resolved to. Raises KeyError when the field is absent;
        # FormalSystem.parse treats that as "the line has no such field".
        return self.sub_matches[name]

    def variable_leaves(self):
        """Every variable leaf under this match, one entry per occurrence.

        The one structural walk a match still owns, because it answers a question
        about the *parse* rather than about the formula: which of the ambient
        string variables this text actually filled a slot with. A definition reads
        it to learn its defining form's parameters (see
        :class:`~website.logical.matching.definitions.Definition`).
        """
        if not self.sub_matches:
            return [self] if self.is_variable else []

        leaves = []
        for sub in self.sub_matches.values():
            leaves.extend(sub.variable_leaves())
        return leaves

    def duplicate(self):
        # Create a copy of this match
        return copy(self)

    def __str__(self):
        return f"Match for {self.pattern.name}: {self.string}"

    def __copy__(self):
        m = Match(
            pattern=copy(self.pattern),
            string=self.string,
            is_variable=self.is_variable
        )

        m.sub_matches = {key: sub.duplicate() for key, sub in self.sub_matches.items()}
        m.definition = self.definition

        return m
