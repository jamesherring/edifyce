"""The proof/matching :class:`Context` object."""

from copy import copy
from dataclasses import dataclass, field


@dataclass(eq=False)
class Context:

    variables: dict = field(default_factory=dict)
    string_variables: dict = field(default_factory=dict)

    # Defined notations in scope (see matching.DefinedNotation)
    definitions: set = field(default_factory=set)

    # Logical context for inside proofs
    logical: dict = field(default_factory=dict)

    def __copy__(self):
        # Every field is copied one level deep. Callers copy a context to scope
        # it — per proof line, per rule application — and the default shallow
        # copy would share these containers, letting a nested scope's bindings
        # leak back into its parent.
        return Context(
            variables=copy(self.variables),
            string_variables=copy(self.string_variables),

            definitions={copy(defn) for defn in self.definitions},

            # Logical is a dict of dicts
            logical={key: copy(self.logical[key]) for key in self.logical},
        )
