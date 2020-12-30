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

    def add_restriction(self, r):
        # Parse a restriction r and add to context

        if " == " in r:
            # Equivalence

            # Check if it's negated
            negated = len(r) > 4 and r[:4] == "not "

            if negated:
                # Trim off the start
                r = r[4:]

            # Get the left and right hand side of ==
            index = r.index(" == ")
            lhs = r[:index]
            rhs = r[index + 4:]

            # Add the restriction
            self.restrictions.append({
                "type": "equivalence",
                "pair": {lhs, rhs},
                "negated": negated
            })

            return

        centre = " in "
        negated = False
        assert centre in r

        if " not in " in r:
            # Negated
            negated = True
            centre = " not in "

        index = r.index(centre)
        lhs = r[:index]
        rhs = r[index + len(centre):]

        self.restrictions.append({
            "type": "membership",
            "negated": negated,
            "member": lhs,
            "set": rhs
        })

    def get_copy(self):
        return Context(
            variables=self.variables.copy(),
            string_variables=self.string_variables.copy(),
            restrictions=self.restrictions.copy(),
            definitions=self.definitions.copy(),
            system=self.system.copy()
        )

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
