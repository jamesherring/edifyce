"""Term trees: a parse-once representation of formulae.

A formula reaches the engine as a *string*, and recovering its structure means
backtracking over that string (``StringPattern.match``). Doing that every time
structure is needed - which is what the matching layer used to do, comparing
formulae by re-serialising trees back to text - re-derives the same structure
over and over.

A :class:`Term` is that structure captured once. You parse a string with the
matcher, project the resulting :class:`~website.logical.matching.Match` into a
:class:`Term` with :func:`from_match`, and from then on every operation -
equality, substitution, rendering - walks the tree. No string is re-parsed, and
the ``Match`` has done its job.

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

Representation - a shared DAG
-----------------------------
Terms are *interned* (hash-consed): identical subterms are stored once, so a
term is a directed acyclic graph with maximal sharing rather than a tree. Two
structurally equal terms built through the kernel's producers are then the same
object, which is what makes ``equal``'s ``self is other`` fast path fire. This
is a pure optimisation layered under the same value-semantic interface -
``equal`` stays the authoritative structural comparison - so terms must be
treated as immutable once built. See the interning section below.

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
  making a schema equal a term, reusing the constructor's signature for
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
from weakref import WeakValueDictionary

from .constructors import Constructor, constructor_for

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
        # Interned terms are shared, so identity is the common fast path (O(1)).
        if self is other:
            return True
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


# Reserved binding key for an abstract bound variable, keyed by index. The NUL
# prefix cannot collide with a grammar-legal parameter name, so a `Bound` reuses
# all of `Var`'s name-keyed machinery (matching, substitution, interning) without
# risk of being confused with a real metavariable.
_BOUND_PREFIX = "\x00bound:"


def _bound_label(index: int) -> str:
    return f"{_BOUND_PREFIX}{index}"


class Bound(Var):
    """An abstract, indexed bound variable inside a definition's defining form.

    A binder-carrying definition stores its bound variable *abstractly* - by
    index - rather than as a fixed concrete name. ``df-subset``'s defining form
    ``∀z.((z ∈ x) → (z ∈ y))`` is represented as ``∀[0].(([0] ∈ x) → ([0] ∈ y))``
    where ``[0]`` is ``Bound(0, setvar)``. The *consumer* of an unfold then
    chooses the concrete name each index takes (subject to the freshness
    proviso), so ``(z ⊆ b)`` can unfold to ``∀w.((w ∈ z) → (w ∈ b))`` with a
    caller-supplied fresh ``w`` instead of being rejected for capturing ``z``.
    Distinct indices let one definition bind several variables independently.

    A ``Bound`` is a :class:`Var` whose name is a reserved, index-derived key, so
    it matches (recovering the chosen name), substitutes (instantiating it) and
    interns through the ordinary variable machinery. It differs only in that it
    is *bound*, not free: it never appears in :meth:`free_vars`, and it is only
    ever produced by :func:`bind` from a definition's ``fresh`` declaration.
    """

    def __init__(self, index: int, sort: Pattern) -> None:
        super().__init__(_bound_label(index), sort)
        self.index: int = index

    def free_vars(self, acc: FreeVars | None = None) -> FreeVars:
        # A bound variable is not a free parameter, so it contributes nothing.
        return {} if acc is None else acc

    def to_string(self) -> str:
        # Never user-facing: an unfold instantiates every bound variable to a
        # concrete leaf before the term is rendered. A readable placeholder is
        # kept only for debugging an un-instantiated schema.
        return f"⟨{self.index}⟩"

    def __repr__(self) -> str:
        return f"Bound({self.index}:{self.sort.name})"


class Node(Term):
    """A compound term: a production applied to named child terms.

    ``pattern``    - the production (an arbitrary ``Pattern``); the constructor.
                     For ``"(a -> b)"`` this is the ``implication`` pattern.
    ``children``   - ``{slot_label: Term}`` for the production's variable slots,
                     e.g. ``{"p": <term a>, "q": <term b>}``. Empty for a leaf.
    ``literal``    - surface string for a ground leaf with no slots (a constant,
                     atom or regex token), e.g. ``Node(atom, literal="a")``.
                     Mutually exclusive with ``children``.
    ``sort``       - the ``Pattern`` this term *inhabits* (its type), used only
                     by sort checks in matching. Normally ``None``: a term's sort
                     is then its own constructor, which is already a member of
                     whatever union it belongs to. It is set only when the
                     surface constructor is *not* itself a member of the sort -
                     a definition shorthand, whose constructor is the ad-hoc
                     higher form but which still inhabits e.g. ``formula``.

    A node carries no definition *provenance*: relating a defined form to its
    defining form is an explicit step (see :mod:`definitions`), not a property
    of the term. ``sort`` is a typing attribute, not that link - ``equal`` never
    consults it; only ``unify``'s sort check does.
    """

    def __init__(
        self,
        constructor: Constructor,
        children: dict[str, Term] | None = None,
        literal: str | None = None,
        sort: Pattern | None = None,
    ) -> None:
        self.constructor: Constructor = constructor
        self.children: dict[str, Term] = children if children is not None else {}
        self.literal: str | None = literal
        self.sort: Pattern | None = sort

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
        return _node(
            constructor=self.constructor,
            children={
                label: child.substitute(binding, context)
                for label, child in self.children.items()
            },
            literal=self.literal,
            sort=self.sort,
        )

    def equal(self, other: Term, context: Context) -> bool:
        # Interned terms are shared, so identity is the common fast path (O(1)):
        # two structurally equal terms are usually the *same* object.
        if self is other:
            return True

        if not isinstance(other, Node):
            return False

        # Compare constructors by shape, not by name: a rule schema's inline
        # "(p -> q)" and a system's named `implication` production are the same
        # constructor even though they are different objects.
        if self.constructor.signature != other.constructor.signature:
            return False

        # Ground leaves compare by their surface string, e.g. atom "a" == "a".
        if self.literal is not None or other.literal is not None:
            return self.literal == other.literal

        # Align children by template position (with repetition), not by slot
        # label - the two constructors may spell their variables differently
        # (e.g. `p`/`q` vs `lhs`/`rhs`) and either may repeat a variable.
        # Matching signatures guarantee an equal number of occurrences.
        self_locations = self.constructor.slots
        other_locations = other.constructor.slots
        if len(self_locations) != len(other_locations):
            return False

        for self_label, other_label in zip(self_locations, other_locations):
            if self_label not in self.children or other_label not in other.children:
                return False
            if not self.children[self_label].equal(other.children[other_label], context):
                return False

        return True

    def to_string(self) -> str:
        # Rebuild the surface string from the constructor's render steps and the
        # children. This is the parse-once payoff: reconstruction never calls
        # match(). e.g. implication{p: a, q: (b -> a)} walks ("lit", "("),
        # ("slot", "p"), ("lit", " -> "), ("slot", "q"), ("lit", ")").
        if self.literal is not None:
            return self.literal

        pieces = self.constructor.pieces
        if not pieces:
            # No template structure to walk (a bare regex, atom or abstract sort).
            if len(self.children) == 1:
                return next(iter(self.children.values())).to_string()
            return ""

        out = []
        for kind, text in pieces:
            if kind == "lit":
                out.append(text)
            else:
                child = self.children.get(text)
                out.append(child.to_string() if child is not None else text)
        return "".join(out)

    def __repr__(self) -> str:
        if self.literal is not None:
            return f"Node({self.constructor.name}={self.literal!r})"
        return f"Node({self.constructor.name}, {list(self.children)})"


# ---------------------------------------------------------------------------
# Interning: terms are a shared DAG, not a tree
# ---------------------------------------------------------------------------
#
# Identical subterms are stored once (hash-consing), so a term is a directed
# acyclic graph with maximal sharing. Two structurally equal terms built through
# the kernel's constructors are then the *same* object, which makes ``equal``'s
# ``self is other`` fast path fire in the common case. This is a pure
# optimisation: ``equal`` remains the authoritative structural comparison (with
# ``is`` only as a sufficient short-cut), so correctness never depends on
# interning being perfect - it just shares memory and speeds equality up.
#
# The table holds terms weakly, so entries vanish when a term is no longer
# referenced. Keys use child/sort *identity*: while a key's term is alive it
# keeps its children and sort alive, so those ids stay valid; when it dies the
# entry is removed, so a reused id can never collide with a live entry.
_INTERN: WeakValueDictionary = WeakValueDictionary()


def _term_key(term: Term) -> tuple:
    """A canonical, hashable key for interning: a Var by (name, sort); a Node by
    its constructor, literal, inhabited sort, and the identities of its children
    in template-position order (with repetition). Children are already interned,
    so identity captures structure.

    The constructor is keyed by *identity*, not by its signature - two productions
    with the same shape but different identity (a rule schema's inline ``(p -> q)``
    and a system's ``implication``) must not be merged: they are still ``equal``,
    but they carry different sorts, and ``_term_sort``/sort admission depend on a
    node keeping its own constructor. Interning is therefore finer than equality
    (which is sound - ``equal`` remains the authority); it only forgoes sharing
    between alpha-equivalent constructors.
    """
    if isinstance(term, Bound):
        # Keyed by index (its identity), kept distinct from a plain Var so the
        # two never share an interned instance.
        return ("bound", term.index, id(term.sort))
    if isinstance(term, Var):
        return ("var", term.name, id(term.sort))
    child_ids = tuple(
        id(term.children[label])
        for label in term.constructor.slots
        if label in term.children
    )
    return ("node", id(term.constructor), term.literal, id(term.sort), child_ids)


def _canonical(term: Term) -> Term:
    """Return the shared instance for ``term`` (assuming its children are already
    interned), registering it on first sight."""
    key = _term_key(term)
    existing = _INTERN.get(key)
    if existing is not None:
        return existing
    _INTERN[key] = term
    return term


def _var(name: str, sort: Pattern) -> Var:
    return _canonical(Var(name, sort))  # type: ignore[return-value]


def _bound(index: int, sort: Pattern) -> Bound:
    return _canonical(Bound(index, sort))  # type: ignore[return-value]


def _node(
    constructor: Constructor,
    children: dict[str, Term] | None = None,
    literal: str | None = None,
    sort: Pattern | None = None,
) -> Node:
    return _canonical(Node(constructor, children, literal, sort))  # type: ignore[return-value]


def intern(term: Term) -> Term:
    """Return the shared-DAG form of an externally built ``term``, interning it
    and all its subterms bottom-up.

    Kernel producers (:func:`from_match`, :func:`from_pattern`, :func:`abstract`,
    :meth:`Term.substitute`) already return interned terms; use this for a term
    assembled by hand (e.g. ``Node(...)``/``Var(...)`` directly) so it, too,
    shares structure and benefits from the identity fast path.
    """
    if isinstance(term, Node) and term.children:
        term = Node(
            constructor=term.constructor,
            children={label: intern(child) for label, child in term.children.items()},
            literal=term.literal,
            sort=term.sort,
        )
    return _canonical(term)


def from_match(match: Match, context: Context) -> Term:
    r"""Project a :class:`Match` tree into a :class:`Term` (the parse-once bridge).

    The engine's ``Match`` tree carries scaffolding the term layer does not
    need - most notably union-pattern *coercion* nodes, which wrap the branch
    that actually matched (a ``formula`` union around the ``implication`` that
    parsed ``"(a -> b)"``). Those are collapsed, so a formula is the same term
    however many union layers happened to parse it.

    Nothing here knows definitions exist. Defined notation arrives already
    shaped like any other production - its template *is* the constructor, and
    ``Match.sort`` names the sort that ad-hoc constructor inhabits, which reads
    straight across to :attr:`Node.sort` (see ``Definition.match``).

    The branches below, by example, for a system with ``formula`` (a union of
    ``atom`` and ``implication``)::

        match of "a"           (a declared variable)  -> Var("a", formula)
        match of "(a -> b)"    (union coercion)       -> collapse to the implication Node
        match of "a"           (a ground atom)        -> Node(atom, literal="a")
        match of "(a -> b)"    (compound)             -> Node(implication, {"p": .., "q": ..})
        match of "a is a … of" (defined notation)     -> Node(<template>, {...}, sort=formula)
    """
    constructor = constructor_for(match.pattern)

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
        return _var(name=match.string, sort=match.pattern)

    # A union match is a coercion wrapper around a single chosen branch: e.g.
    # `formula` wrapping the `implication` that matched "(a -> b)". Collapse it.
    if constructor.kind == "union":
        subs = list(match.sub_matches.values())
        if len(subs) == 1:
            return from_match(subs[0], context)
        # No single branch (nothing to collapse to): treat as a ground leaf.
        return _node(constructor=constructor, literal=match.string, sort=match.sort)

    # A ground leaf: regex/atomic token or a literal pattern with no slots, e.g.
    # the atom "a" -> Node(atom, literal="a").
    if not match.sub_matches:
        return _node(constructor=constructor, literal=match.string, sort=match.sort)

    # A compound: recurse into the named sub-matches, e.g. "(a -> b)" ->
    # Node(implication, {"p": <term a>, "q": <term b>}).
    return _node(constructor=constructor, children=child_terms(match), sort=match.sort)


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

    constructor = constructor_for(pattern)

    if constructor.kind == "atom":
        # A constant in schema position is a ground leaf (e.g. `derive: ⊥`); a
        # family (e.g. a propositional-variable sort `p_#`) used directly is a
        # fresh variable ranging over it, like any other sort.
        if constructor.atom_value is not None:
            return Node(constructor=constructor, literal=constructor.atom_value)
        return Var(name=constructor.name, sort=pattern)

    if constructor.kind == "string":
        # Whole template is a single variable, e.g. an antecedent written "s"
        # (or "p"/"q"): the pattern is just that variable, so it is a bare Var.
        pieces = constructor.pieces
        if len(pieces) == 1 and pieces[0][0] == "slot":
            label = pieces[0][1]
            if is_schematic(label):
                return _var(name=label, sort=constructor.slot_sorts[label])

        if constructor.has_declared_variables:
            # Compound, e.g. "(p -> q)": each variable slot is a Var of its
            # declared sort. A non-schematic slot recurses (kept for symmetry;
            # rule schemas rarely nest fixed structure).
            children = {}
            for label, slot_sort in constructor.slot_sorts.items():
                if is_schematic(label):
                    children[label] = _var(name=label, sort=slot_sort)
                else:
                    children[label] = from_pattern(slot_sort, context, schematic)
            return _node(constructor=constructor, children=children)

        # No variables: a ground literal production, e.g. a rule that fixes a
        # specific constant like the axiom schema "true".
        return _node(constructor=constructor, literal=constructor.template)

    # A sort used directly in schema position (union/regex/abstract) is a
    # fresh variable ranging over that sort, e.g. an antecedent written
    # `formula` meaning "any formula".
    return _var(name=constructor.name, sort=pattern)


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
                return _var(name=term.literal, sort=variables[term.literal])
            return term
        return _node(
            constructor=term.constructor,
            children={label: abstract(child, variables) for label, child in term.children.items()},
            sort=term.sort,
        )

    return term


def bind(term: Term, bound: dict[str, Bound]) -> Term:
    """Replace each ground leaf whose surface string names a bound variable with
    that variable's abstract :class:`Bound` node.

    This is how a definition's defining form stores its binders by index instead
    of by a fixed concrete name: after :func:`abstract` lifts the definition's
    *parameters* into :class:`Var` leaves, ``bind`` lifts its declared bound
    variables into :class:`Bound` leaves. For ``df-subset`` the parsed
    ``∀z.((z ∈ x) → (z ∈ y))`` (with ``x``/``y`` already abstracted) becomes
    ``∀[0].(([0] ∈ x) → ([0] ∈ y))`` under ``{"z": Bound(0, setvar)}``. Every
    ``z`` leaf - the binder and its uses - maps to the *same* ``Bound``, so the
    binder stays a single shared node.
    """
    if isinstance(term, Var):
        return term

    if isinstance(term, Node):
        if not term.children:
            if term.literal is not None and term.literal in bound:
                return bound[term.literal]
            return term
        return _node(
            constructor=term.constructor,
            children={label: bind(child, bound) for label, child in term.children.items()},
            sort=term.sort,
        )

    return term
