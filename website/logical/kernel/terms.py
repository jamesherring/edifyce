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
an arbitrary ``Pattern``. The term type knows nothing about definitions:
relating a defined and defining form is an explicit, cited step verified in
:mod:`definitions`, never something ``equal`` or ``unify`` does implicitly.
Nothing in this module enumerates connectives, quantifiers or set-builder
syntax, so first-order logic, ZF(C) and near-English definitional statements
are all representable - the term layer only ever sees "some production applied
to some children". Keeping this module logic-agnostic is what preserves the
goal of supporting arbitrary formal systems; please keep it that way.

Scope and roadmap
-----------------
This is step 1 of the kernel extraction: the *representation* plus the
operations that are unambiguously part of it (``free_vars``, ``substitute``,
structural ``equal``, ``to_string``). It is deliberately the foundation the
later steps build on, not a dependency of them:

* Step 2 (:mod:`unify`) - first-order matching that *derives* a substitution
  making a schema equal a term, reusing ``_signature`` for constructor
  identity and ``substitute`` / ``equal`` here as its ground cases.
* Step 3 (:mod:`side_conditions`) - a small, closed vocabulary of provisos
  (occurrence, leaf-disjointness, atomicity) checked structurally over these
  terms against a match's binding, replacing the general condition interpreter.
* Step 4 (:mod:`definitions`) - definitions as cited axioms. A proof step names
  a definition and the kernel verifies one unfold; ``equal`` / ``unify`` stay
  purely structural, so the term type carries no definition metadata.

Nothing here should grow to depend on those steps; keep the representation
self-contained so the trusted core stays small and auditable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..matching.patterns import RegexPattern, StringPattern, UnionPattern

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.matches import Match
    from ..matching.patterns import Pattern

    # A substitution: schematic variable name -> the Term it maps to.
    # "Term" is quoted: this is a real assignment (not a PEP 563 annotation),
    # and the Term class is defined further down this module.
    Binding = dict[str, "Term"]
    # Free-variable inventory: variable name -> its sort (an arbitrary Pattern).
    FreeVars = dict[str, Pattern]


class Term:
    """Base class for terms. Concrete kinds are :class:`Var` and :class:`Node`."""

    def free_vars(self, acc: FreeVars | None = None) -> FreeVars:
        """Return ``{name: sort}`` for every variable leaf in this term.

        A ground formula has none; a rule schema such as ``(p -> q)`` returns
        ``{"p": <formula sort>, "q": <formula sort>}``.
        """
        raise NotImplementedError

    def substitute(self, binding: Binding, context: Context) -> Term:
        """Return a copy with each ``Var`` replaced by ``binding[name]`` (if present).

        With ``binding = {"p": <term a>, "q": <term b>}`` the schema ``(p -> q)``
        substitutes to the ground term for ``(a -> b)``.
        """
        raise NotImplementedError

    def equal(self, other: Term, context: Context) -> bool:
        """Structural equality: same constructor and equal children, no re-parsing.

        The terms for ``"(a -> b)"`` and ``"(a -> b)"`` are equal; the terms for
        ``"(a -> b)"`` and ``"(a -> c)"`` are not.

        This is the *syntactic* base relation. Step 2 will add ``unify`` (equal
        up to a variable binding) and equality modulo definitions on top of it;
        this method stays purely structural.
        """
        raise NotImplementedError

    def to_string(self) -> str:
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

    def __init__(self, name: str, sort: Pattern) -> None:
        self.name: str = name
        self.sort: Pattern = sort

    def free_vars(self, acc: FreeVars | None = None) -> FreeVars:
        if acc is None:
            acc = {}
        acc.setdefault(self.name, self.sort)
        return acc

    def substitute(self, binding: Binding, context: Context) -> Term:
        # e.g. Var("p", formula).substitute({"p": term_for_a}) -> term_for_a;
        # a variable not named in the binding is returned unchanged.
        return binding.get(self.name, self)

    def equal(self, other: Term, context: Context) -> bool:
        # Two variables are equal when they share a name and an equivalent sort,
        # e.g. Var("p", formula) == Var("p", formula), but != Var("q", formula).
        return (
            isinstance(other, Var)
            and other.name == self.name
            and self.sort.equivalent(other.sort, context)
        )

    def to_string(self) -> str:
        return self.name

    def __repr__(self) -> str:
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

    A node carries no definition provenance: relating a defined form to its
    defining form is an explicit step (see :mod:`definitions`), not a property
    of the term. Provenance, if ever needed, is an elaboration-layer concern.
    """

    def __init__(
        self,
        pattern: Pattern,
        children: dict[str, Term] | None = None,
        literal: str | None = None,
    ) -> None:
        self.pattern: Pattern = pattern
        self.children: dict[str, Term] = children if children is not None else {}
        self.literal: str | None = literal

    def free_vars(self, acc: FreeVars | None = None) -> FreeVars:
        if acc is None:
            acc = {}
        for child in self.children.values():
            child.free_vars(acc)
        return acc

    def substitute(self, binding: Binding, context: Context) -> Term:
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
        )

    def equal(self, other: Term, context: Context) -> bool:
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

        # Align children by template position (with repetition), not by slot
        # label - the two constructors may spell their variables differently
        # (e.g. `p`/`q` vs `lhs`/`rhs`) and either may repeat a variable.
        # Matching signatures guarantee an equal number of occurrences.
        self_locations = _locations(self.pattern)
        other_locations = _locations(other.pattern)
        if len(self_locations) != len(other_locations):
            return False

        for self_label, other_label in zip(self_locations, other_locations):
            if self_label not in self.children or other_label not in other.children:
                return False
            if not self.children[self_label].equal(other.children[other_label], context):
                return False

        return True

    def to_string(self) -> str:
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

    def __repr__(self) -> str:
        if self.literal is not None:
            return f"Node({self.pattern.name}={self.literal!r})"
        return f"Node({self.pattern.name}, {list(self.children)})"


def _signature(pattern: Pattern) -> tuple[str, str]:
    r"""A constructor identity: the template's literal skeleton with every
    variable *occurrence* replaced by an anonymous hole. It ignores the
    pattern's name and its variable spellings, so structurally identical
    productions - a rule's synthesised "(p -> q)" schema and a system's named
    `implication` - are the same constructor.

    Repetition is deliberately *not* encoded: both "(p -> q)" and "(p -> p)"
    give ``'(\x00 -> \x00)'``. That lets a repeated-variable schema like
    "(p -> p)" share a constructor with the production "(p -> q)" that parses a
    subject like "(a -> a)"; whether the two holes actually hold *equal*
    subterms is then enforced by the shared variable binding during child
    alignment (see :meth:`Node.equal` / :func:`unify.match`), not here.

    Examples::

        "(p -> q)"  ->  ('string', '(\x00 -> \x00)')
        "(p -> p)"  ->  ('string', '(\x00 -> \x00)')   # same constructor
        "(a ∧ b)"   ->  ('string', '(\x00 ∧ \x00)')    # differs: different literals
    """
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


def _locations(pattern: Pattern) -> list[str]:
    r"""Variable-slot labels in template order, **with repetition** - one entry
    per occurrence. Two constructors with the same signature have the same
    number of occurrences, so their location lists align position by position.

    A repeated schema label forces the aligned subterms to be equal: "(p -> p)"
    yields ``["p", "p"]``, so matching it against a production "(lhs -> rhs)"
    (``["lhs", "rhs"]``) looks up ``children["p"]`` for both positions, and the
    shared binding then requires ``lhs`` and ``rhs`` to agree. Distinct labels
    like ``["p", "q"]`` simply pair up with the other side's labels in order.
    """
    return [
        pattern.variable_locations[offset]["label"]
        for offset in sorted(getattr(pattern, "variable_locations", {}))
    ]


def from_match(match: Match, context: Context) -> Term:
    r"""Project a :class:`Match` tree into a :class:`Term` (the parse-once bridge).

    The engine's ``Match`` tree carries scaffolding the term layer does not
    need - most notably union-pattern *coercion* nodes, which wrap the branch
    that actually matched (a ``formula`` union around the ``implication`` that
    parsed ``"(a -> b)"``). Those are collapsed, so a formula is the same term
    however many union layers happened to parse it.

    The branches below, by example, for a system with ``formula`` (a union of
    ``atom`` and ``implication``)::

        match of "a"           (a declared variable)  -> Var("a", formula)
        match of "a is a … of" (definition-backed)    -> Node(<defn.higher>, {...})
        match of "(a -> b)"    (union coercion)       -> collapse to the implication Node
        match of "a"           (a ground atom)        -> Node(atom, literal="a")
        match of "(a -> b)"    (compound)             -> Node(implication, {"p": .., "q": ..})
    """
    pattern = match.pattern

    def child_terms(m: Match) -> dict[str, Term]:
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
    # itself a template, and its sub-matches are the definition's variables. The
    # definition's `higher` form carries both the surface template and those
    # variables, so we use it to build a faithfully-structured node - e.g. for a
    # definition "x is a subset of y" of `formula`, "a is a subset of b" becomes
    # Node(<higher "x is a subset of y">, {"x": .., "y": ..}). The definition
    # itself is used only transiently to pick the constructor; the term keeps no
    # reference to it (relating higher and lower forms is a cited step 4).
    if match.definition is not None:
        higher = match.definition.higher
        if match.sub_matches:
            return Node(pattern=higher, children=child_terms(match))
        return Node(pattern=higher, literal=match.formatted_string())

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


def from_pattern(
    pattern: Pattern, context: Context, schematic: set[str] | None = None
) -> Term:
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

    Today a caller applies a rule by supplying the binding and checking the
    result with :meth:`Term.equal`. Step 2 will instead *derive* that binding
    by unifying this schema against the proof line, closing the loop into a
    term-based proof checker.
    """

    def is_schematic(label: str) -> bool:
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


def abstract(term: Term, variables: FreeVars) -> Term:
    """Turn a parsed ground term into a *schema* by replacing each ground leaf
    whose surface string is a parameter name in ``variables`` with a
    :class:`Var` of that sort.

    This is the structure-preserving way to build a *multi-level* schema, such
    as a definition's defining form ``∀z.((z ∈ x) → (z ∈ y))``: parse the
    surface form through the grammar (giving a properly nested term), then
    abstract the parameters ``x``/``y`` into variables. It complements
    :func:`from_pattern`, which reads a single production's slots and so is only
    right for one-level schemas (a rule's ``(p -> q)``); parsing then
    abstracting keeps a nested tree intact, which ``from_pattern`` would flatten.

    Every leaf whose string equals a parameter name becomes that parameter, so
    parameter names must not also occur as *distinct* ground constants in the
    form - true for well-formed schemas, whose parameters are chosen fresh. A
    bound variable of a different name (``z`` above) is left as a ground leaf.
    """
    if isinstance(term, Var):
        return term

    if isinstance(term, Node):
        if not term.children:
            # A ground leaf: abstract it iff its surface string is a parameter.
            if term.literal is not None and term.literal in variables:
                return Var(name=term.literal, sort=variables[term.literal])
            return term
        return Node(
            pattern=term.pattern,
            children={label: abstract(child, variables) for label, child in term.children.items()},
        )

    return term
