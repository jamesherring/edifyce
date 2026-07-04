"""The proof/matching :class:`Context` object."""

from copy import copy
from dataclasses import dataclass, field

from .matches import Match


@dataclass(eq=False)
class Context:

    variables: dict = field(default_factory=dict)
    string_variables: dict = field(default_factory=dict)

    # Simple matches for string variables.
    string_variable_matches: dict = field(default_factory=dict)

    # Definitions
    definitions: set = field(default_factory=set)

    # Conditions
    conditions: set = field(default_factory=set)

    # Logical context for inside proofs
    logical: dict = field(default_factory=dict)

    # Reference object
    reference_object: object = None

    # Mapping on string variables - string: string dictionary
    mapping: object = None

    # The proof model id
    proof_model_id: object = None

    def set_string_variable_matches(self):
        # Set string variable matches
        for var, pattern in self.string_variables.items():
            self.string_variable_matches[var] = Match(pattern=pattern, string=var, is_variable=True)

    def equivalent(self, other, context, memo=None):
        # Check equivalence

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume False
        memo[(self, other)] = False

        if type(other) is not Context:
            return False

        if not len(self.variables) == len(other.variables):
            return False

        if not len(self.string_variables) == len(other.string_variables):
            return False

        if not len(self.string_variable_matches) == len(other.string_variable_matches):
            return False

        if not len(self.definitions) == len(other.definitions):
            return False

        if not len(self.conditions) == len(other.conditions):
            return False

        if not len(self.logical) == len(other.logical):
            return False

        if not self.mapping == other.mapping:
            return False

        if not self.proof_model_id == other.proof_model_id:
            return False

        # Assume True for recursive checks
        memo[(self, other)] = True

        if not self.reference_object.equivalent(other.reference_object, context, memo):
            memo[(self, other)] = False
            return False

        for key in self.variables:
            if key not in other.variables:
                memo[(self, other)] = False
                return False

            if not self.variables[key].equivalent(other.variables[key], context, memo):
                memo[(self, other)] = False
                return False

        for key in self.string_variables:
            if key not in other.string_variables:
                memo[(self, other)] = False
                return False

            if not self.string_variables[key].equivalent(other.string_variables[key], context, memo):
                memo[(self, other)] = False
                return False

        for key in self.string_variable_matches:
            if key not in other.string_variable_matches:
                memo[(self, other)] = False
                return False

            if not self.string_variable_matches[key].equivalent(other.string_variable_matches[key], context, memo):
                memo[(self, other)] = False
                return False

        # Check there is a 1-1 correspondence between definitions
        other_defs_used = set()
        for self_def in self.definitions:
            found = False
            for other_def in {item for item in other.definitions if item not in other_defs_used}:
                if self_def.equivalent(other_def, context, memo):
                    found = True
                    other_defs_used.add(other_def)
                    break

            if not found:
                memo[(self, other)] = False
                return False

        # Check there is a 1-1 correspondence between conditions
        other_conds_used = set()
        for self_cond in self.conditions:
            found = False
            for other_cond in {item for item in other.conditions if item not in other_conds_used}:
                if self_cond.equivalent(other_cond, context, memo):
                    found = True
                    other_conds_used.add(other_cond)
                    break

            if not found:
                memo[(self, other)] = False
                return False

        for key in self.logical:
            if key not in other.logical:
                memo[(self, other)] = False
                return False

            if not self.logical[key].equivalent(other.logical[key], context, memo):
                memo[(self, other)] = False
                return False

        # Otherwise ok
        return True

    def __copy__(self):
        # Return a copy of the context
        return Context(
            variables=copy(self.variables),
            string_variables=copy(self.string_variables),
            string_variable_matches=copy(self.string_variable_matches),

            definitions={copy(defn) for defn in self.definitions},
            conditions={copy(cond) for cond in self.conditions},

            # Logical is a dict of dicts
            logical={key: copy(self.logical[key]) for key in self.logical},

            reference_object=self.reference_object,
            mapping=copy(self.mapping),

            proof_model_id=self.proof_model_id
        )
