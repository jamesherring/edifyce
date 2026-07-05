"""Term trees: a parse-once representation of formulae.

Today a formula only ever exists as a *string*. The matcher recovers its
structure by backtracking over that string every time structure is needed
(``StringPattern.match``), and serialises trees back to strings to compare
them (``Match.reset_string`` / ``formatted_string``). Structure is therefore
re-derived, over and over, from text.

A :class:`Term` is that structure captured once. You parse a string with the
existing engine, project the resulting :class:`~website.logical.matching.Match`
into a :class:`Term` with :func:`from_match`, and from then on every operation
- equality, substitution, rendering - walks the tree. No string is re-parsed.

Design invariant - *the kernel hard-codes no logic*
---------------------------------------------------
A :class:`Node` is a production (an arbitrary per-system ``Pattern``) applied
to named child terms. A :class:`Var` ranges over a *sort*, which is likewise
an arbitrary ``Pattern``. Definitions are recorded on the node that used them
and never interpreted here. Nothing in this module enumerates connectives,
quantifiers or set-builder syntax, so first-order logic, ZF(C) and
near-English definitional statements are all representable - the term layer
only ever sees "some production applied to some children". Keeping this module
logic-agnostic is what preserves the goal of supporting arbitrary formal
systems; please keep it that way.

Scope
-----
This is step 1 of the kernel extraction: the *representation* plus the
operations that are unambiguously part of it (``free_vars``, ``substitute``,
structural ``equal``, ``to_string``). Deriving a substitution by unifying two
terms - and doing so modulo definitions - is step 2 and deliberately lives
elsewhere; this module does not depend on it.
"""

from __future__ import annotations


class Term:
    """Base class for terms. Concrete kinds are :class:`Var` and :class:`Node`."""

    def free_vars(self, acc=None):
        """Return ``{name: sort}`` for every variable leaf in this term."""
        raise NotImplementedError

    def substitute(self, binding, context):
        """Return a copy with each ``Var`` replaced by ``binding[name]`` (if present)."""
        raise NotImplementedError

    def equal(self, other, context):
        """Structural equality: same constructor and equal children, no re-parsing."""
        raise NotImplementedError

    def to_string(self):
        """Render the surface string from the tree, without re-invoking the matcher."""
        raise NotImplementedError


class Var(Term):
    """A schematic variable (metavariable) ranging over a sort.

    ``sort`` is an arbitrary ``Pattern`` (e.g. ``formula``, ``term``,
    ``setvar``) - the term layer places no constraints on what it may be.
    """

    def __init__(self, name, sort):
        self.name = name
        self.sort = sort

    def free_vars(self, acc=None):
        if acc is None:
            acc = {}
        acc.setdefault(self.name, self.sort)
        return acc

    def substitute(self, binding, context):
        return binding.get(self.name, self)

    def equal(self, other, context):
        return (
            isinstance(other, Var)
            and other.name == self.name
            and self.sort.equivalent(other.sort, context)
        )

    def to_string(self):
        return self.name

    def __repr__(self):
        return f"Var({self.name!r}:{self.sort.name})"


class Node(Term):
    """A compound term: a production applied to named child terms.

    ``pattern``    - the production (an arbitrary ``Pattern``); the constructor.
    ``children``   - ``{slot_label: Term}`` for the production's variable slots.
    ``literal``    - surface string for a ground leaf with no slots (a constant,
                     atom or regex token). Mutually exclusive with ``children``.
    ``definition`` - the ``Definition`` this node was built through, if any.
                     Recorded for the future definitions-as-axioms work; never
                     interpreted here.
    """

    def __init__(self, pattern, children=None, literal=None, definition=None):
        self.pattern = pattern
        self.children = children if children is not None else {}
        self.literal = literal
        self.definition = definition

    def free_vars(self, acc=None):
        if acc is None:
            acc = {}
        for child in self.children.values():
            child.free_vars(acc)
        return acc

    def substitute(self, binding, context):
        if not self.children:
            return self
        return Node(
            pattern=self.pattern,
            children={
                label: child.substitute(binding, context)
                for label, child in self.children.items()
            },
            literal=self.literal,
            definition=self.definition,
        )

    def equal(self, other, context):
        if not isinstance(other, Node):
            return False

        # Compare constructors by shape, not by pattern name: a rule schema's
        # inline "(p -> q)" and a system's named `implication` production are
        # the same constructor. Child sorts are checked by the recursion below.
        if _signature(self.pattern) != _signature(other.pattern):
            return False

        if self.literal is not None or other.literal is not None:
            return self.literal == other.literal

        if set(self.children) != set(other.children):
            return False

        return all(
            self.children[label].equal(other.children[label], context)
            for label in self.children
        )

    def to_string(self):
        # Rebuild the surface string from the production template and children.
        # This is the parse-once payoff: reconstruction never calls match().
        if self.literal is not None:
            return self.literal

        pattern = self.pattern
        template = getattr(pattern, "pattern", None)
        var_locations = getattr(pattern, "variable_locations", None)
        non_variable_locations = getattr(pattern, "non_variable_locations", None)

        if not isinstance(template, str) or var_locations is None or non_variable_locations is None:
            # No template structure to walk (e.g. a bare regex/abstract sort).
            if len(self.children) == 1:
                return next(iter(self.children.values())).to_string()
            return ""

        out = []
        i = 0
        while i < len(template):
            if i in non_variable_locations:
                part = non_variable_locations[i]
                out.append(part)
                i += len(part)
            elif i in var_locations:
                label = var_locations[i]["label"]
                child = self.children.get(label)
                out.append(child.to_string() if child is not None else label)
                i += len(label)
            else:
                # Should not happen for a well-formed template; skip defensively.
                i += 1

        return "".join(out)

    def __repr__(self):
        if self.literal is not None:
            return f"Node({self.pattern.name}={self.literal!r})"
        return f"Node({self.pattern.name}, {list(self.children)})"


def _signature(pattern):
    """A constructor identity that ignores the pattern's *name* and its
    variable spellings, so structurally identical productions - a rule's
    synthesised "(p -> q)" schema and a system's named `implication` - compare
    as the same constructor. Variable slots normalise to a single placeholder;
    which slots hold equal subterms is decided by the caller's child recursion.
    """
    from ..matching.patterns import RegexPattern, StringPattern

    if isinstance(pattern, StringPattern):
        template = pattern.pattern
        out = []
        i = 0
        while i < len(template):
            if i in pattern.non_variable_locations:
                part = pattern.non_variable_locations[i]
                out.append(part)
                i += len(part)
            elif i in pattern.variable_locations:
                out.append("\x00")
                i += len(pattern.variable_locations[i]["label"])
            else:
                i += 1
        return ("string", "".join(out))

    if isinstance(pattern, RegexPattern):
        return ("regex", pattern.pattern)

    return ("named", pattern.name)


def from_match(match, context):
    """Project a :class:`Match` tree into a :class:`Term` (the parse-once bridge).

    Union-pattern coercion nodes carry no structure of their own and are
    collapsed, so a formula is the same term however many union layers happened
    to parse it.
    """
    from ..matching.patterns import UnionPattern

    pattern = match.pattern

    # A variable leaf: the string is itself a declared schematic variable.
    if match.is_variable:
        return Var(name=match.formatted_string(), sort=pattern)

    # A union match is a coercion wrapper around a single chosen branch.
    if isinstance(pattern, UnionPattern):
        subs = list(match.sub_matches.values())
        if len(subs) == 1:
            return from_match(subs[0], context)
        # No single branch (nothing to collapse to): treat as a ground leaf.
        return Node(pattern=pattern, literal=match.formatted_string())

    # A ground leaf: regex/atomic token or a literal pattern with no slots.
    if not match.sub_matches:
        return Node(
            pattern=pattern,
            literal=match.formatted_string(),
            definition=match.definition,
        )

    # A compound: recurse into the named sub-matches.
    children = {}
    for label, sub in match.sub_matches.items():
        if isinstance(sub, list):
            # Rare shape seen in a few matcher paths; take the representative.
            sub = sub[0]
        children[label] = from_match(sub, context)

    return Node(pattern=pattern, children=children, definition=match.definition)


def from_pattern(pattern, context, schematic=None):
    """Project a rule-schema ``Pattern`` into a :class:`Term` whose variable
    slots become :class:`Var` leaves.

    This is how an inference rule's antecedents and deduction (stored as
    ``Pattern`` objects) enter the same term space as parsed formulae, so a
    rule can be applied by substitution. ``schematic`` optionally restricts
    which variable names are treated as schematic; by default every variable
    slot on the pattern is.
    """
    from ..matching.patterns import StringPattern

    def is_schematic(label):
        return schematic is None or label in schematic

    if isinstance(pattern, StringPattern):
        # Whole template is a single variable, e.g. an antecedent written "s".
        if (
            len(pattern.variable_locations) == 1
            and not pattern.non_variable_locations
            and 0 in pattern.variable_locations
        ):
            info = pattern.variable_locations[0]
            if is_schematic(info["label"]):
                return Var(name=info["label"], sort=info["pattern"])

        if pattern.variables:
            # Compound: each variable slot is a Var of its declared sort.
            children = {}
            for info in pattern.variable_locations.values():
                label = info["label"]
                if is_schematic(label):
                    children[label] = Var(name=label, sort=info["pattern"])
                else:
                    children[label] = from_pattern(info["pattern"], context, schematic)
            return Node(pattern=pattern, children=children)

        # No variables: a ground literal production.
        return Node(pattern=pattern, literal=pattern.pattern)

    # A sort used directly in schema position (union/regex/abstract) is a
    # fresh variable ranging over that sort.
    return Var(name=pattern.name, sort=pattern)
