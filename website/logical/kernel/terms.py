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

Worked example
--------------
Take a first-order system with atoms and one production
``implication`` = ``(p -> q)``. Parsing ``"(a -> b)"`` and projecting it gives::

    Node(implication, {
        "p": Node(atom, literal="a"),
        "q": Node(atom, literal="b"),
    })

``term.to_string()`` rebuilds ``"(a -> b)"`` from that tree without calling the
matcher again, and ``term.equal(other, context)`` compares two such trees
structurally. The same machinery handles near-English syntax: a production
``membership`` = ``x is an element of y`` turns ``"a is an element of b"`` into
``Node(membership, {"x": Node(setvar, literal="a"), "y": Node(setvar, literal="b")})``.

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

from ..matching.patterns import RegexPattern, StringPattern, UnionPattern


class Term:
    """Base class for terms. Concrete kinds are :class:`Var` and :class:`Node`."""

    def free_vars(self, acc=None):
        """Return ``{name: sort}`` for every variable leaf in this term.

        A ground formula has none; a rule schema such as ``(p -> q)`` returns
        ``{"p": <formula sort>, "q": <formula sort>}``.
        """
        raise NotImplementedError

    def substitute(self, binding, context):
        """Return a copy with each ``Var`` replaced by ``binding[name]`` (if present).

        With ``binding = {"p": <term a>, "q": <term b>}`` the schema ``(p -> q)``
        substitutes to the ground term for ``(a -> b)``.
        """
        raise NotImplementedError

    def equal(self, other, context):
        """Structural equality: same constructor and equal children, no re-parsing.

        The terms for ``"(a -> b)"`` and ``"(a -> b)"`` are equal; the terms for
        ``"(a -> b)"`` and ``"(a -> c)"`` are not.
        """
        raise NotImplementedError

    def to_string(self):
        """Render the surface string from the tree, without re-invoking the matcher.

        The term for ``"(a -> (b -> a))"`` renders back to exactly that string.
        """
        raise NotImplementedError


class Var(Term):
    """A schematic variable (metavariable) ranging over a sort.

    ``sort`` is an arbitrary ``Pattern`` (e.g. ``formula``, ``term``,
    ``setvar``) - the term layer places no constraints on what it may be. For
    example the ``p`` in a modus-ponens schema is ``Var("p", <formula sort>)``.
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
        # e.g. Var("p", formula).substitute({"p": term_for_a}) -> term_for_a;
        # a variable not named in the binding is returned unchanged.
        return binding.get(self.name, self)

    def equal(self, other, context):
        # Two variables are equal when they share a name and an equivalent sort,
        # e.g. Var("p", formula) == Var("p", formula), but != Var("q", formula).
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
                     For ``"(a -> b)"`` this is the ``implication`` pattern.
    ``children``   - ``{slot_label: Term}`` for the production's variable slots,
                     e.g. ``{"p": <term a>, "q": <term b>}``. Empty for a leaf.
    ``literal``    - surface string for a ground leaf with no slots (a constant,
                     atom or regex token), e.g. ``Node(atom, literal="a")``.
                     Mutually exclusive with ``children``.
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
        # A ground leaf (no children) is unaffected by any binding.
        if not self.children:
            return self
        # Otherwise rebuild the same constructor over substituted children, e.g.
        # implication{p, q}.substitute({p: a, q: b}) -> implication{a, b}.
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
        # the same constructor even though the Pattern objects differ.
        if _signature(self.pattern) != _signature(other.pattern):
            return False

        # Ground leaves compare by their surface string, e.g. atom "a" == "a".
        if self.literal is not None or other.literal is not None:
            return self.literal == other.literal

        # Align children by template *position*, not by slot label - the two
        # constructors may spell their variables differently. For instance a
        # production `(lhs -> rhs)` and a rule schema `(p -> q)` share a
        # signature, so `lhs` lines up with `p` and `rhs` with `q`. Matching
        # signatures guarantee equal arity.
        self_slots = _ordered_slots(self.pattern)
        other_slots = _ordered_slots(other.pattern)
        if len(self_slots) != len(other_slots):
            return False

        for self_label, other_label in zip(self_slots, other_slots):
            if self_label not in self.children or other_label not in other.children:
                return False
            if not self.children[self_label].equal(other.children[other_label], context):
                return False

        return True

    def to_string(self):
        # Rebuild the surface string from the production template and children.
        # This is the parse-once payoff: reconstruction never calls match().
        # e.g. implication{p: a, q: (b -> a)} with template "(p -> q)" walks the
        # template emitting "(", then a, then " -> ", then "(b -> a)", then ")".
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
                # A literal chunk of the template, e.g. "(" or " -> ".
                part = non_variable_locations[i]
                out.append(part)
                i += len(part)
            elif i in var_locations:
                # A slot: splice in the child's rendered string.
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
    r"""A constructor identity that ignores the pattern's *name* and its
    variable spellings, so structurally identical productions - a rule's
    synthesised "(p -> q)" schema and a system's named `implication` - compare
    as the same constructor. Each distinct variable is normalised to a
    positional placeholder, so arity and repetition are encoded.

    Examples (the placeholder is a NUL byte followed by the slot index)::

        "(p -> q)"  ->  ('string', '(\x000 -> \x001)')
        "(p -> p)"  ->  ('string', '(\x000 -> \x000)')   # repetition preserved
        "(x -> y)"  ->  ('string', '(\x000 -> \x001)')   # == the "(p -> q)" case

    So ``(p -> q)`` and ``(x -> y)`` share a signature (alpha-equivalent) while
    ``(p -> p)`` differs from ``(p -> q)``.
    """
    if isinstance(pattern, StringPattern):
        template = pattern.pattern
        label_index = {}
        out = []
        i = 0
        while i < len(template):
            if i in pattern.non_variable_locations:
                part = pattern.non_variable_locations[i]
                out.append(part)
                i += len(part)
            elif i in pattern.variable_locations:
                label = pattern.variable_locations[i]["label"]
                index = label_index.setdefault(label, len(label_index))
                out.append(f"\x00{index}")
                i += len(label)
            else:
                i += 1
        return ("string", "".join(out))

    if isinstance(pattern, RegexPattern):
        return ("regex", pattern.pattern)

    return ("named", pattern.name)


def _ordered_slots(pattern):
    """The distinct variable-slot labels of a production, in the order they
    first appear in its template. Used to align two constructors' children by
    position (not by label) once their signatures match.

    For example the production ``(p -> q)`` yields ``["p", "q"]`` and the
    alpha-renamed ``(lhs -> rhs)`` yields ``["lhs", "rhs"]``; zipping the two
    lists pairs ``p`` with ``lhs`` and ``q`` with ``rhs``.
    """
    slots = []
    for offset in sorted(getattr(pattern, "variable_locations", {})):
        label = pattern.variable_locations[offset]["label"]
        if label not in slots:
            slots.append(label)
    return slots


def from_match(match, context):
    r"""Project a :class:`Match` tree into a :class:`Term` (the parse-once bridge).

    The engine's ``Match`` tree carries scaffolding the term layer does not
    need - most notably union-pattern *coercion* nodes, which wrap the branch
    that actually matched (a ``formula`` union around the ``implication`` that
    parsed ``"(a -> b)"``). Those are collapsed, so a formula is the same term
    however many union layers happened to parse it.

    The branches below, by example, for a system with ``formula`` (a union of
    ``atom`` and ``implication``)::

        match of "a"           (a declared variable)  -> Var("a", formula)
        match of "a" via defn  (definition attached)  -> Node(<defn.higher>, ..., definition=...)
        match of "(a -> b)"    (union coercion)       -> collapse to the implication Node
        match of "a"           (a ground atom)        -> Node(atom, literal="a")
        match of "(a -> b)"    (compound)             -> Node(implication, {"p": .., "q": ..})
    """
    pattern = match.pattern

    def child_terms(m):
        children = {}
        for label, sub in m.sub_matches.items():
            if isinstance(sub, list):
                # Rare shape seen in a few matcher paths; take the representative.
                sub = sub[0]
            children[label] = from_match(sub, context)
        return children

    # A variable leaf: the string is itself a declared schematic variable, e.g.
    # a formula written "phi" where phi was declared `with phi as formula`.
    if match.is_variable:
        return Var(name=match.formatted_string(), sort=pattern)

    # A definition-backed match: the matched sort (often a UnionPattern) is not
    # itself a template, and its sub-matches are the definition's variables. Its
    # `higher` form carries both the surface template and those variables, so
    # represent the node through it and keep the definition as metadata. For a
    # definition "x is a subset of y" of `formula`, "a is a subset of b" becomes
    # Node(<higher "x is a subset of y">, {"x": .., "y": ..}, definition=<defn>).
    # Definitional *equality* (relating the higher and lower forms) is a later
    # kernel step; here we only preserve the structure faithfully.
    if match.definition is not None:
        higher = match.definition.higher
        if match.sub_matches:
            return Node(pattern=higher, children=child_terms(match), definition=match.definition)
        return Node(pattern=higher, literal=match.formatted_string(), definition=match.definition)

    # A union match is a coercion wrapper around a single chosen branch: e.g.
    # `formula` wrapping the `implication` that matched "(a -> b)". Collapse it.
    if isinstance(pattern, UnionPattern):
        subs = list(match.sub_matches.values())
        if len(subs) == 1:
            return from_match(subs[0], context)
        # No single branch (nothing to collapse to): treat as a ground leaf.
        return Node(pattern=pattern, literal=match.formatted_string())

    # A ground leaf: regex/atomic token or a literal pattern with no slots, e.g.
    # the atom "a" -> Node(atom, literal="a").
    if not match.sub_matches:
        return Node(pattern=pattern, literal=match.formatted_string())

    # A compound: recurse into the named sub-matches, e.g. "(a -> b)" ->
    # Node(implication, {"p": <term a>, "q": <term b>}).
    return Node(pattern=pattern, children=child_terms(match))


def from_pattern(pattern, context, schematic=None):
    """Project a rule-schema ``Pattern`` into a :class:`Term` whose variable
    slots become :class:`Var` leaves.

    This is how an inference rule's antecedents and deduction (stored as
    ``Pattern`` objects) enter the same term space as parsed formulae, so a
    rule can be applied by substitution. ``schematic`` optionally restricts
    which variable names are treated as schematic; by default every variable
    slot on the pattern is.

    By example, for modus ponens (``with p as formula, q as formula``)::

        antecedent "p"        ->  Var("p", formula)
        antecedent "(p -> q)" ->  Node(implication, {"p": Var("p", ..), "q": Var("q", ..)})
        deduction  "q"        ->  Var("q", formula)

    so ``antecedent2.substitute({"p": a, "q": b})`` yields the term for
    ``"(a -> b)"`` - the same term ``from_match`` produces for that string.
    """

    def is_schematic(label):
        return schematic is None or label in schematic

    if isinstance(pattern, StringPattern):
        # Whole template is a single variable, e.g. an antecedent written "s"
        # (or "p"/"q"): the pattern is just that variable, so it is a bare Var.
        if (
            len(pattern.variable_locations) == 1
            and not pattern.non_variable_locations
            and 0 in pattern.variable_locations
        ):
            info = pattern.variable_locations[0]
            if is_schematic(info["label"]):
                return Var(name=info["label"], sort=info["pattern"])

        if pattern.variables:
            # Compound, e.g. "(p -> q)": each variable slot is a Var of its
            # declared sort. A non-schematic slot recurses (kept for symmetry;
            # rule schemas rarely nest fixed structure).
            children = {}
            for info in pattern.variable_locations.values():
                label = info["label"]
                if is_schematic(label):
                    children[label] = Var(name=label, sort=info["pattern"])
                else:
                    children[label] = from_pattern(info["pattern"], context, schematic)
            return Node(pattern=pattern, children=children)

        # No variables: a ground literal production, e.g. a rule that fixes a
        # specific constant like the axiom schema "true".
        return Node(pattern=pattern, literal=pattern.pattern)

    # A sort used directly in schema position (union/regex/abstract) is a
    # fresh variable ranging over that sort, e.g. an antecedent written
    # `formula` meaning "any formula".
    return Var(name=pattern.name, sort=pattern)
