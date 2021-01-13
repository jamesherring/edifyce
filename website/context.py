
class Context(object):
    # A class for the context

    def __init__(self, variables=None, string_variables=None, restrictions=None, definitions=None, system=None):

        # Variables in the file
        self.variables = variables
        if variables is None:
            self.variables = dict()

        # String variables, inside matches
        self.string_variables = string_variables
        if string_variables is None:
            self.string_variables = dict()

        # Restrictions on string variables
        self.restrictions = restrictions
        if restrictions is None:
            self.restrictions = list()

        # Definitions
        self.definitions = definitions
        if definitions is None:
            self.definitions = list()

        # System patterns
        self.system = system
        if system is None:
            self.system = dict()

        # Keep a match history, so we can quick match strings with patterns. Needs to cleared whenever context changes
        self.history = dict()

    def add_by_key(self, context_type, key=None, value=None):

        if context_type == "restrictions":
            self.add_restriction(value)

        else:
            context_part = self.__dict__[context_type]

            if type(context_part) is dict:
                context_part[key] = value

            else:
                context_part.append(value)

    def add_restriction(self, r):
        # Parse a restriction r and add to context

        # The restriction r should match system condition_inner
        condition_inner = self.system["condition_inner"]
        r = condition_inner.match(r, self)

        self.restrictions.append(r)

    def get_variable_restrictions(self, var, mapping=None):
        # Get all restrictions on var, including nested restrictions on equivalent variables

        # Keep track of a set of results for all relevant variables
        if mapping is None:
            mapping = dict()

        if var not in mapping:
            mapping[var] = {
                "positive": {
                    "variables": set()
                },
                "negative": {
                    "variables": set(),
                    "values": set()
                }
            }

        for r in self.restrictions:

            subs = r.get_sub_matches()

            negated = False
            if "negation" in subs:
                negated = True
                subs = subs["negated"].get_sub_matches()["condition"].get_sub_matches()

            if "equal" not in subs:
                # Not an equivalence restriction
                continue

            equal_subs = subs["equal"].get_sub_matches()

            if var in equal_subs:
                # Restriction applies to var

                # Get the other item
                other = None
                for item in equal_subs:
                    if not item == var:
                        other = item
                        break

                # Check if other is a variable
                if other in self.string_variables:
                    # Other is a variable

                    if other in mapping:
                        # Already mapped
                        continue

                    # Update the mapping with other
                    mapping = self.get_variable_restrictions(other, mapping)

                    if negated:
                        # not var == other

                        mapping[var]["negative"]["variables"].add(other)

                        # Check if other has fixed value.
                        if "value" in mapping[other]["positive"]:
                            # This is useful - we know var cannot be equal to this
                            mapping[var]["negative"]["values"].add(mapping[other]["positive"]["value"])

                        # Any equivalent variables also apply to var
                        mapping[var]["positive"]["variables"].update(mapping[other]["positive"]["variables"])

                    else:
                        # var == other
                        mapping[var]["positive"]["variables"].add(other)

                        # Check if other has fixed value
                        if "value" in mapping[other]["positive"]:
                            # This is useful - we know var must be equal to this
                            mapping[var]["positive"]["value"] = mapping[other]["positive"]["value"]

                        # Any negative restrictions on other also apply to var
                        mapping[var]["negative"]["variables"].update(mapping[other]["negative"]["variables"])
                        mapping[var]["negative"]["values"].update(mapping[other]["negative"]["values"])

                else:
                    # Other is a fixed value
                    if negated:
                        # not var == item
                        mapping[var]["negative"]["values"].add(other)

                    else:
                        # var == item
                        mapping[var]["positive"]["value"] = other

        return mapping

    def get_by_path(self, path):
        # Get an instance from the given path, if it's pointing to the context scope

        if path in self.variables:
            return self.variables[path]

        if path in self.string_variables:
            return self.string_variables[path]

        if path in self.definitions:
            return self.definitions[path]

        if path in self.system:
            return self.system[path]

        if "." in path:
            index = path.index(".")
            initial = path[:index]
            remainder = path[index + 1:]

            initial = self.get_by_path(initial)

            if initial is not None:
                return initial.get_by_path(remainder)

        # Otherwise, can't find anything
        return None

    def add_to_history(self, key, pattern, pattern_match, match):
        # Add a match to a key, pattern, pattern_match tuple in history (match may be None)
        self.history[(key, pattern, pattern_match)] = match

    def clear_history(self):
        # Clear context history
        self.history = dict()

    def __eq__(self, other):
        # Check if equal to another context
        return self.variables == other.variables and \
               self.string_variables == other.string_variables and \
               self.restrictions == other.restrictions and \
               self.definitions == other.definitions and \
               self.system == other.system

    def __copy__(self):
        return Context(
            variables=self.variables.copy(),
            string_variables=self.string_variables.copy(),
            restrictions=self.restrictions.copy(),
            definitions=self.definitions.copy(),
            system=self.system.copy()
        )
