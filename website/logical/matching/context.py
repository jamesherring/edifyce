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

            # The *set* is copied, its members are not. A notation is a piece of
            # grammar, shared like the patterns it is built from, and nothing
            # scopes it per copy. Cloning each member used to matter when a
            # definition carried mutable state (the kernel counterpart, filled in
            # after construction); now it only breaks identity, so a notation
            # registered here would no longer de-duplicate against the one the
            # system holds.
            definitions=set(self.definitions),

            # Logical is a dict of dicts
            logical={key: copy(self.logical[key]) for key in self.logical},
        )
