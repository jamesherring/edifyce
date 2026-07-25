"""The proof/matching :class:`Context` object."""

from copy import copy
from dataclasses import dataclass, field


@dataclass(eq=False)
class Context:

    variables: dict = field(default_factory=dict)
    string_variables: dict = field(default_factory=dict)

    # Definitions
    definitions: set = field(default_factory=set)

    # Logical context for inside proofs
    logical: dict = field(default_factory=dict)

    # The proof model id
    proof_model_id: object = None

    # Memo for one top-level parse: {(id(pattern), string): Match | None}. None -
    # the default - disables it. A context is long-lived and what a string parses
    # to depends on the grammar, `definitions` and `string_variables`, so only a
    # caller that knows all three are fixed for the duration of a parse may switch
    # it on. See `UnionPattern.match` for why the memo exists at all.
    parse_memo: dict | None = None

    def __copy__(self):
        # Return a copy of the context
        return Context(
            variables=copy(self.variables),
            string_variables=copy(self.string_variables),

            definitions={copy(defn) for defn in self.definitions},

            # Logical is a dict of dicts
            logical={key: copy(self.logical[key]) for key in self.logical},

            proof_model_id=self.proof_model_id,

            # Shared, not copied, so the memo survives the context copies taken
            # during a parse.
            parse_memo=self.parse_memo,
        )
