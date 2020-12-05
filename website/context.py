class Context(object):
    # A class for the context

    def __init__(self, variables=None, string_variables=None, restrictions=None, system=None):

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
        return Context(self.variables.copy(), self.string_variables.copy(), self.restrictions.copy(), self.system.copy())

    def add_to_history(self, key, pattern, match):
        # Add a match to a key, pattern pair in history (match may be None)
        self.history[(key, pattern)] = match

    def clear_history(self):
        # Clear context history
        self.history = dict()
