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

This module is the *only* place in the kernel that reads a ``Pattern``. Keeping
the projection here is what lets ``terms``, ``unify`` and ``definitions`` be
written against kernel data alone.

The one thing not projected
---------------------------
``denotes_constant`` stays a property delegating to the source production, not a
snapshot, because the build *mutates* it: a nullary defined form's role is
settled only once its kernel definition exists (see
``declarative._finalise_definition``), which is after terms built from that
production may already exist. Snapshotting would freeze the pre-decision value.

That delegation, and the ``source`` field it reads, are the remaining thread back
to the matching layer. It stays until a production's declared role is kernel data
in its own right - at which point ``source`` goes and this module's import of
``Pattern`` goes with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..matching.patterns import AtomPattern, RegexPattern, StringPattern, UnionPattern

if TYPE_CHECKING:
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
        source: Pattern,
        kind: str,
        name: str,
        signature: tuple[str, ...],
        slots: tuple[str, ...],
        pieces: tuple[Piece, ...],
        template: str | None,
        slot_sorts: dict[str, Pattern],
        atom_value: str | None = None,
        atom_base: str | None = None,
        has_declared_variables: bool = False,
    ) -> None:
        self.source: Pattern = source
        self.kind: str = kind
        self.name: str = name
        self.signature: tuple[str, ...] = signature
        self.slots: tuple[str, ...] = slots
        self.pieces: tuple[Piece, ...] = pieces
        # The surface template, for a production that has one. Storage records it
        # for a defined form, whose constructor has no name in the namespace.
        self.template: str | None = template
        # Each slot's declared sort, for projecting a schema (see from_pattern).
        self.slot_sorts: dict[str, Pattern] = slot_sorts
        # Set for an atom: exactly one of these, mirroring AtomPattern.
        self.atom_value: str | None = atom_value
        self.atom_base: str | None = atom_base
        # Whether the production *declares* variables, which is not the same as
        # having slots: a declared variable that never appears in the template
        # occupies no slot. Schema projection distinguishes the two.
        self.has_declared_variables: bool = has_declared_variables
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

        Computed on demand rather than in ``_build``, so it cannot be read before
        ``declarative.build_system`` has finished filling the sort unions.
        """
        if self._admits is None:
            found: dict[int, Constructor] = {}
            stack: list[Pattern] = [self.source]
            while stack:
                pattern = stack.pop()
                if id(pattern) in found:
                    continue
                found[id(pattern)] = constructor_for(pattern)
                if isinstance(pattern, UnionPattern):
                    stack.extend(pattern.patterns)
            self._admits = frozenset(found.values())
        return self._admits

    @property
    def denotes_constant(self) -> bool:
        # Delegated, never snapshotted - the build settles this after the fact for
        # a nullary defined form. See the module docstring.
        return self.source.denotes_constant

    def __repr__(self) -> str:
        return f"Constructor({self.name!r}, {self.signature!r})"


def constructor_for(pattern: Pattern) -> Constructor:
    """The constructor ``pattern`` denotes, built on first sight and reused after.

    The memo lives *on the production*, not in a table here, so it is reclaimed
    with it. A module-level cache - even a weak-keyed one - cannot be: a grammar
    is mutually recursive (``implication``'s slot sort is the ``formula`` union
    that contains it), so a constructor's ``slot_sorts`` reach back to its own
    key, and the entry keeps itself alive. Rebuilding a system per request would
    then grow the process without bound.

    The pattern/constructor reference cycle this creates is ordinary garbage once
    the system is dropped, and the cyclic collector reclaims it.
    """
    existing = pattern.kernel_constructor
    if existing is not None:
        return existing
    built = _build(pattern)
    pattern.kernel_constructor = built
    return built


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
            source=pattern,
            kind="string",
            name=pattern.name,
            signature=("string", skeleton),
            slots=slots,
            pieces=pieces,
            template=pattern.pattern,
            slot_sorts={
                info["label"]: info["pattern"]
                for info in pattern.variable_locations.values()
            },
            has_declared_variables=bool(pattern.variables),
        )

    if isinstance(pattern, AtomPattern):
        signature = (
            ("atom", "const", pattern.value)
            if pattern.is_constant
            else ("atom", "family", pattern.base)
        )
        return Constructor(
            source=pattern,
            kind="atom",
            name=pattern.name,
            signature=signature,
            slots=(),
            pieces=(),
            template=None,
            slot_sorts={},
            atom_value=pattern.value,
            atom_base=pattern.base,
        )

    if isinstance(pattern, RegexPattern):
        return Constructor(
            source=pattern,
            kind="regex",
            name=pattern.name,
            signature=("regex", pattern.pattern),
            slots=(),
            pieces=(),
            template=None,
            slot_sorts={},
        )

    # A union or abstract sort used as a constructor: nothing structural to read,
    # so its name is its identity. A union is told apart because a match against
    # one is a *coercion wrapper* the term layer collapses (see from_match).
    return Constructor(
        source=pattern,
        kind="union" if isinstance(pattern, UnionPattern) else "named",
        name=pattern.name,
        signature=("named", pattern.name),
        slots=(),
        pieces=(),
        template=None,
        slot_sorts={},
    )
