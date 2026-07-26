"""Constructor identity, computed once instead of re-derived per comparison.

A :class:`~website.logical.kernel.terms.Node` is a *constructor* applied to
named children. Until now that constructor was the parser's own ``Pattern``, and
every operation that needed its identity re-derived it by walking the pattern's
template: :func:`terms._signature` rebuilt a hole-punched skeleton on each
``equal`` and each ``unify.match``; ``_locations`` re-sorted ``variable_locations``
on each child alignment; ``Node.to_string`` probed for template attributes with a
defaulting ``getattr`` because it could not know which pattern class it had.

A :class:`Constructor` is that identity captured once, at build time. Everything
the kernel asks of a constructor - is this the same shape, what slots does it
have, how does it render - becomes a field read.

No ``Pattern`` survives the projection
-------------------------------------
A constructor holds no reference to the production it came from. Its slot sorts
and, for a sort union, its branches are *other constructors*, so a term, a
schema, a side condition's sort argument and the sort a variable ranges over are
all kernel data. This module reads a ``Pattern``; nothing it returns contains
one, which is what lets ``terms``, ``unify``, ``definitions`` and
``side_conditions`` be written against kernel data alone.

That closes the last thread. ``denotes_constant`` was a property reading the
production back, because the build *mutated* it; the role is now settled from the
notation before the definition is built (``declarative._finalise_definition``),
so it is an ordinary snapshot. A sort was a ``Pattern`` because resolving one to
a constructor is mutually recursive; that is handled by registering before
linking (see :func:`constructor_for`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..matching.patterns import AtomPattern, RegexPattern, StringPattern, UnionPattern

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ..matching.patterns import Pattern

    # A rendering step: ("lit", text) emits text verbatim, ("slot", label)
    # splices in the child bound to that label.
    Piece = tuple[str, str]


class Constructor:
    """The identity of a term's constructor, projected from a production.

    ``signature`` is what makes two constructors *the same shape*: the template's
    literal skeleton with every variable occurrence replaced by an anonymous hole.
    It ignores the production's name and its variable spellings, so a rule's
    synthesised ``(p -> q)`` schema and a system's named ``implication`` are one
    constructor. For an atom the identity is what the atom *denotes* - a constant
    by its value, a family by its base - so a rule's inline ``⊥`` and the system's
    declared ``falsum`` agree, which is what lets discharge match a literal
    conclusion.

    Repetition is deliberately not encoded: ``(p -> q)`` and ``(p -> p)`` share a
    signature. Whether the two holes actually hold *equal* subterms is enforced by
    the shared variable binding during child alignment (see ``Node.equal`` and
    ``unify.match``), not here.

    ``slots`` lists the variable-slot labels in template order **with repetition**
    - one entry per occurrence - so two constructors with the same signature align
    position by position. A repeated schema label forces the aligned subterms to be
    equal: ``(p -> p)`` yields ``("p", "p")``, so matching it against a production
    ``(lhs -> rhs)`` looks up the same child for both positions.

    Compared by identity, not by value: one constructor is built per production, so
    two productions of the same shape stay distinct objects. They are still
    ``equal`` as terms - ``signature`` sees to that - but a node keeps its own
    constructor, which ``_term_sort`` and sort admission depend on.
    """

    def __init__(
        self,
        kind: str,
        name: str,
        signature: tuple[str, ...],
        slots: tuple[str, ...],
        pieces: tuple[Piece, ...],
        template: str | None,
        atom_value: str | None = None,
        atom_base: str | None = None,
        has_declared_variables: bool = False,
        denotes_constant: bool = False,
        scopes_over: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.kind: str = kind
        self.name: str = name
        self.signature: tuple[str, ...] = signature
        self.slots: tuple[str, ...] = slots
        self.pieces: tuple[Piece, ...] = pieces
        # The surface template, for a production that has one. Storage records it
        # for a defined form, whose constructor has no name in the namespace.
        self.template: str | None = template
        # Each slot's declared sort, and - for a union - its branches. Both are
        # filled by `_link` immediately after this constructor is registered, not
        # here: they reach back into the grammar, which is mutually recursive.
        self.slot_sorts: dict[str, Constructor] = {}
        self.members: tuple[Constructor, ...] = ()
        # Set for an atom: exactly one of these, mirroring AtomPattern.
        self.atom_value: str | None = atom_value
        self.atom_base: str | None = atom_base
        # Whether the production *declares* variables, which is not the same as
        # having slots: a declared variable that never appears in the template
        # occupies no slot. Schema projection distinguishes the two.
        self.has_declared_variables: bool = has_declared_variables
        # Whether this production's tokens name constants of the object language
        # (Metamath's `$c`) rather than variables a binder may bind. Read by the
        # kernel's definition builder to decide which leaves a defining form may
        # introduce from nowhere.
        self.denotes_constant: bool = denotes_constant
        # Which slots bind, and over which siblings: `{"x": ("phi",)}` for
        # `∀x phi`. A slot named here holds a *binder occurrence*, which is what
        # lets a definition's `fresh` clause be read off the parsed defining form
        # instead of declared (see formal_system.definitions). Empty for a
        # production whose author declared no binding structure — every
        # production, until one does.
        self.scopes_over: dict[str, tuple[str, ...]] = scopes_over or {}
        # Lazily filled by `admits`.
        self._admits: frozenset[Constructor] | None = None

    @property
    def admits(self) -> frozenset[Constructor]:
        """The sorts this production admits when it is *used as a sort*: itself,
        plus - if it is a union - every branch reachable through nested unions.

        This is the whole of sort admission (see ``unify.sort_admits``), which
        used to ask the pattern lattice the same question pair by pair: first
        structural equivalence, then nested union membership. Both collapse to a
        set lookup because **a built system's productions are canonical** - one
        object per production, shared by every context copy - so two productions
        are structurally equivalent exactly when they are the same object.

        That invariant used to be false. ``FormalSystemContext.inherit`` gave each
        union a ``deepcopy`` of itself as an ``inherits`` chain, which is why
        equivalence had to be structural and why ``can_map_to`` existed to walk
        the chain. Nothing ever called it, so the copies were never made; the dead
        machinery is gone and ``tests/test_pattern_canonicity.py`` holds the line.

        Derived from ``members``, which the projection fills - so a sort must be
        projected only once its branches are known. ``declarative.build_system``
        projects the grammar explicitly for that reason.
        """
        if self._admits is None:
            found: set[Constructor] = set()
            stack: list[Constructor] = [self]
            while stack:
                constructor = stack.pop()
                if constructor in found:
                    continue
                found.add(constructor)
                stack.extend(constructor.members)
            self._admits = frozenset(found)
        return self._admits

    def __repr__(self) -> str:
        return f"Constructor({self.name!r}, {self.signature!r})"


def constructor_for(pattern: Pattern) -> Constructor:
    """The constructor ``pattern`` denotes, projected on first sight and reused
    after.

    The memo lives *on the production*, not in a table here, so it is reclaimed
    with it. A module-level cache - even a weak-keyed one - cannot be: a grammar
    is mutually recursive (``implication``'s slot sort is the ``formula`` union
    that contains it), so a constructor's ``slot_sorts`` reach back to its own
    key, and the entry keeps itself alive. Rebuilding a system per request would
    then grow the process without bound.

    That same recursion is why projection is two-phase. ``_build`` reads only what
    a production says about *itself*; the constructor is registered on the pattern
    **before** ``_link`` resolves its slot sorts and branches, so a cycle back to
    this production finds the registered constructor and stops. A partially linked
    constructor is only ever observed by ``_link`` itself, which reads no linked
    field.

    The pattern/constructor reference cycle this creates is ordinary garbage once
    the system is dropped, and the cyclic collector reclaims it.
    """
    existing = pattern.kernel_constructor
    if existing is not None:
        return existing
    built = _build(pattern)
    pattern.kernel_constructor = built
    _link(built, pattern)
    return built


def project_grammar(patterns: Iterable[Pattern]) -> None:
    """Project every production in ``patterns`` to its constructor.

    Called by ``declarative.build_system`` once the sort unions are filled, and
    that timing is the point: a union projected while still empty would be linked
    with no branches, and would then admit nothing but itself for the rest of the
    system's life. Doing it explicitly means the moment is chosen rather than
    falling out of whichever term happens to be built first.
    """
    for pattern in patterns:
        constructor_for(pattern)


def project_sorts(sorts: Mapping[str, Pattern]) -> dict[str, Constructor]:
    """Project a ``name -> production`` mapping to ``name -> constructor``.

    The shape a caller has when it holds declared sorts by name - a rule's
    metavariables, a definition's parameters - and the shape the term layer wants.
    """
    return {name: constructor_for(pattern) for name, pattern in sorts.items()}


def _link(constructor: Constructor, pattern: Pattern) -> None:
    """Resolve the parts of a constructor that point back into the grammar.

    Split from ``_build`` so the constructor can be registered first; see
    :func:`constructor_for`.
    """
    if isinstance(pattern, StringPattern):
        constructor.slot_sorts = {
            info["label"]: constructor_for(info["pattern"])
            for info in pattern.variable_locations.values()
        }
    if isinstance(pattern, UnionPattern):
        if not pattern.patterns:
            # Branches are resolved once, here, so an empty union would be sealed
            # admitting nothing but itself and every later variable of that sort
            # would silently refuse to bind. A sort with no productions cannot be
            # declared (`SystemSpec.sort_names` reads them off the productions),
            # so this only ever means the union has not been filled yet - the
            # ordering `declarative.build_system` exists to get right. Loud, since
            # the alternative is a system that builds and then rejects valid proofs.
            raise ValueError(
                f"Sort {pattern.name!r} was projected before its productions were "
                "added; fill the union first (see declarative.build_system step 4)."
            )
        constructor.members = tuple(
            constructor_for(member) for member in pattern.patterns
        )


def _template_parts(pattern: StringPattern) -> tuple[tuple[str, ...], tuple[Piece, ...]]:
    """Walk a template once, collecting its slot labels (with repetition) and its
    render steps. One pass replaces the three separate walks that used to re-derive
    these on demand."""
    slots: list[str] = []
    pieces: list[Piece] = []
    template = pattern.pattern
    i = 0
    while i < len(template):
        if i in pattern.non_variable_locations:
            part = pattern.non_variable_locations[i]
            pieces.append(("lit", part))
            i += len(part)
        elif i in pattern.variable_locations:
            label = pattern.variable_locations[i]["label"]
            slots.append(label)
            pieces.append(("slot", label))
            i += len(label)
        else:
            # Not reachable for a well-formed template, whose variable and
            # non-variable locations partition it exactly; skip rather than hang.
            i += 1
    return tuple(slots), tuple(pieces)


def _build(pattern: Pattern) -> Constructor:
    if isinstance(pattern, StringPattern):
        slots, pieces = _template_parts(pattern)
        # The signature punches an anonymous hole at each slot, so spelling and
        # name drop out and only the literal skeleton identifies the shape.
        skeleton = "".join(
            text if kind == "lit" else "\x00" for kind, text in pieces
        )
        return Constructor(
            denotes_constant=pattern.denotes_constant,
            kind="string",
            name=pattern.name,
            signature=("string", skeleton),
            slots=slots,
            pieces=pieces,
            template=pattern.pattern,
            has_declared_variables=bool(pattern.variables),
            # Read here rather than in `_link`: a binder slot names *siblings of
            # this production*, so nothing about it reaches back into the grammar.
            scopes_over=dict(pattern.scopes_over),
        )

    if isinstance(pattern, AtomPattern):
        signature = (
            ("atom", "const", pattern.value)
            if pattern.is_constant
            else ("atom", "family", pattern.base)
        )
        return Constructor(
            denotes_constant=pattern.denotes_constant,
            kind="atom",
            name=pattern.name,
            signature=signature,
            slots=(),
            pieces=(),
            template=None,
            atom_value=pattern.value,
            atom_base=pattern.base,
        )

    if isinstance(pattern, RegexPattern):
        return Constructor(
            denotes_constant=pattern.denotes_constant,
            kind="regex",
            name=pattern.name,
            signature=("regex", pattern.pattern),
            slots=(),
            pieces=(),
            template=None,
        )

    # A union or abstract sort used as a constructor: nothing structural to read,
    # so its name is its identity. A union is told apart because a match against
    # one is a *coercion wrapper* the term layer collapses (see from_match).
    return Constructor(
        denotes_constant=pattern.denotes_constant,
        kind="union" if isinstance(pattern, UnionPattern) else "named",
        name=pattern.name,
        signature=("named", pattern.name),
        slots=(),
        pieces=(),
        template=None,
    )
