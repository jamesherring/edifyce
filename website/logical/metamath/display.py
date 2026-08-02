"""Turning a `.mm` file's ``$t`` token map into display templates.

:mod:`~.typesetting` reads what `set.mm` declares: one rendering per *token*,
``e.`` as ``∈``, ``sqrt`` as ``√``. Applied to a statement's tokens that gives
soup. What :mod:`~website.logical.rendering` folds instead is one template per
*production*, and this is the bridge: a production's template is made of those
same tokens, so mapping the tokens **inside the template** yields a production
template and the tree supplies everything else.

``wcel`` is ``A e. B``, whose render steps are

    ('slot', 'A'), ('lit', ' e. '), ('slot', 'B')

and mapping the one literal token gives ``('lit', ' ∈ ')``. Folded over a term,
``2 e. RR`` becomes ``2 ∈ ℝ`` - structurally, because the brackets and the nesting
were never in the token map to begin with.

What this does *not* do is invent a better notation than the source has. It is a
faithful re-spelling: ``( sqrt \\` 2 )`` maps to ``( √ \\` 2 )``, not to ``√2``,
because the parentheses and the application backtick are in the production and
`set.mm` renders them. Getting ``\\sqrt{2}`` means *overriding* that production's
template, which the roadmap's §4.4 describes and this deliberately leaves to a
caller: seeding from the file is automatic and safe, and overriding is editorial.

Spacing comes from the source template, not the map. A `$t` rendering carries its
own padding (``' &isin; '``), which is HTML's business; here the template already
says where the spaces go, so the mapped token is trimmed and dropped into the same
slot. That keeps ``( ph -> ps )`` rendering as ``( ph → ps )`` rather than
``( ph  →  ps )``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel.constructors import constructor_for
from ..kernel.definitions import Definition as KernelDefinition
from ..kernel.terms import Node
from ..matching.patterns import AtomPattern, Pattern, StringPattern, UnionPattern
from ..rendering import Projection
from .typesetting import as_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from collections.abc import Iterable

    from ..build_context import FormalSystemContext
    from ..formal_system import FormalSystem
    from ..matching.definitions import DefinedNotation
    from ..kernel.constructors import Constructor, Piece
    from .typesetting import Typesetting


def _map_literal(text: str, tokens: Mapping[str, str]) -> str:
    # Re-spell a literal run, keeping the template's own padding. A literal piece
    # of a Metamath production is whitespace-joined tokens with the spacing the
    # template had (`' e. '`, `'( '`, `' )'`), so the words are what get mapped and
    # the edges are left alone.
    words = text.split()
    if not words:
        return text
    mapped = " ".join(tokens.get(word, word) for word in words)
    lead = " " if text[:1].isspace() else ""
    trail = " " if text[-1:].isspace() else ""
    return f"{lead}{mapped}{trail}"


def _members(union: UnionPattern, seen: set[int]) -> list[Pattern]:
    # Everything that can build a term of this sort, **through inclusions**. A
    # union's member may itself be a union - that is how a sort is included into
    # another, and how the Metamath importer puts each `$v` variable in a
    # `<typecode>_var` sub-sort of its typecode. Stopping at the first level would
    # compare `class`'s own productions with each other and never with the class
    # *variables*, which compete for exactly the same slot.
    if id(union) in seen:
        return []
    seen.add(id(union))
    found: list[Pattern] = []
    for member in union.patterns:
        if isinstance(member, UnionPattern):
            found.extend(_members(member, seen))
        elif isinstance(member, (StringPattern, AtomPattern)):
            found.append(member)
    return found


def _constructors_by_sort(
    context: FormalSystemContext,
) -> list[tuple[str, Constructor]]:
    # Every production with a sort it can build, inclusions followed. Two
    # productions only compete for a parse within one sort, so a shared spelling
    # across sorts is not an ambiguity and must not be reported as one - but a
    # production reachable through two sorts competes in both, and appears twice.
    found: list[tuple[str, Constructor]] = []
    for sort, pattern in context.variables.items():
        if not isinstance(pattern, UnionPattern):
            continue
        already: set[int] = set()
        for member in _members(pattern, set()):
            if id(member) in already:
                continue
            already.add(id(member))
            found.append((sort, constructor_for(member)))
    return found


def _productions(context: FormalSystemContext) -> list[Pattern]:
    # Every production the grammar holds that could carry notation, deduplicated:
    # a production joins its sort's union, and a sort may be included into another,
    # so walking the unions reaches some of them more than once.
    #
    # Atoms count. A Metamath constant is a nullary production - `RR`, `sqrt`, `0`
    # - and its whole rendering is its own token, so leaving them out spells the
    # symbols and not the names they are built from.
    seen: dict[int, Pattern] = {}
    for pattern in context.variables.values():
        if not isinstance(pattern, UnionPattern):
            continue
        for member in pattern.patterns:
            if isinstance(member, (StringPattern, AtomPattern)):
                seen.setdefault(id(member), member)
    return list(seen.values())


def projection_for(
    context: FormalSystemContext,
    tokens: Mapping[str, str],
    name: str = "unicode",
    definitions: Iterable[KernelDefinition] = (),
) -> Projection:
    """A :class:`~website.logical.rendering.Projection` re-spelling ``context``'s
    productions through a ``$t`` token map.

    ``tokens`` is a map of Metamath token to rendering - typically
    ``{t: as_text(v) for t, v in typesetting.unicode.items()}``, since a `$t` value
    is markup rather than text.

    ``definitions`` are the system's registered definitions, whose *defined* forms
    are notation too. A definition may be the only thing making a form grammatical
    - nothing requires a production to declare it first - and such a form is not a
    member of any sort's union, so walking the grammar alone misses it and the
    notation it introduces renders in the source spelling while everything around
    it changes. Pass ``system.definitions``.

    A production none of whose tokens are mapped is left out rather than given an
    identical template, so the projection stays the size of what it changes.
    """
    templates: dict[str, tuple[Piece, ...]] = {}
    constructors = [constructor_for(p) for p in _productions(context)]
    # A defined form's constructor is reached through the definition rather than
    # the grammar: `constructor_for` takes a `Pattern`, and a `DefinedNotation` is
    # not one, but the kernel definition already holds the projected term.
    constructors += [
        definition.higher.constructor
        for definition in definitions
        if isinstance(definition.higher, Node)
    ]
    for constructor in constructors:
        pieces: list[Piece] = []
        changed = False
        if constructor.pieces:
            for kind, text in constructor.pieces:
                if kind != "lit":
                    pieces.append((kind, text))
                    continue
                mapped = _map_literal(text, tokens)
                changed = changed or mapped != text
                pieces.append(("lit", mapped))
        elif constructor.atom_value is not None:
            # An atom is its own token - `RR`, `ph`, `0` - and carries no template,
            # so its rendering *is* the mapped value.
            rendering = tokens.get(constructor.atom_value)
            if rendering is None:
                continue
            changed = rendering != constructor.atom_value
            pieces.append(("lit", rendering))
        if changed:
            templates[constructor.name] = tuple(pieces)
    return Projection(templates=templates, name=name)


@dataclass(frozen=True)
class Collision:
    """Two or more productions of one sort that a notation spells the same."""

    sort: str
    spelling: str
    productions: tuple[str, ...]


@dataclass(frozen=True)
class NotationReport:
    """What a candidate notation would leave unsaid or say twice.

    §4.4's "report of unmapped tokens and colliding renderings", so re-syncing a
    notation against a grammar is driven by a list rather than by discovering
    breakage. Both halves matter for different reasons.

    ``unmapped`` is cosmetic: a token the notation does not spell renders in the
    source spelling, and the result is mixed but readable and still correct.

    ``collisions`` is not, and which it is depends on what the notation is *for*.
    As a **display** it is cosmetic too - two things that look alike are a
    presentation flaw, and the term is unambiguous underneath. As a **source** it
    is a correctness bug: two productions spelled alike cannot be told apart by a
    parser, so text no longer determines the term.
    """

    unmapped: tuple[str, ...] = ()
    collisions: tuple[Collision, ...] = ()

    @property
    def usable_as_source(self) -> bool:
        """Whether text in this notation still determines a term."""
        return not self.collisions


def _spelling(constructor: Constructor, tokens: Mapping[str, str]) -> str | None:
    # What a production would look like, with each slot shown as the *sort* it
    # takes. Slot names are private to a production, so two templates differing
    # only in what they call a slot are spelled alike and a parser cannot tell
    # them apart - but two differing in a slot's **sort** can be told apart, and
    # reporting those as colliding would bury the real ones. Showing the sort does
    # both jobs, and leaves a spelling that can be printed.
    if constructor.pieces:
        return "".join(
            _map_literal(text, tokens)
            if kind == "lit"
            else f"<{constructor.slot_sorts[text].name}>"
            if text in constructor.slot_sorts
            else "<?>"
            for kind, text in constructor.pieces
        )
    if constructor.atom_value is not None:
        return tokens.get(constructor.atom_value, constructor.atom_value)
    return None


def notation_report(
    context: FormalSystemContext,
    tokens: Mapping[str, str],
    notations: Iterable[DefinedNotation] = (),
) -> NotationReport:
    """Check ``tokens`` against ``context``'s grammar before adopting it.

    Run this rather than reasoning about the token map: a map may collide heavily
    at the *token* level and not at all at the production level, because arity and
    position tell productions apart where a token map cannot. On `set.mm` the
    `$t` Unicode map shares 50 renderings across 107 tokens, and that comes to
    **32** colliding spellings over 64 productions - `∪` is three different
    tokens, but `( A ∪ B )`, `∪ A` and `∪ x ∈ A B` are three different shapes.
    Its LaTeX map, measured the same way, collides on 19.

    ``notations`` are the defined forms, which are notation too and can collide
    with a declared production just as readily. Pass ``system.context.definitions``
    - a `DefinedNotation` carries both the sort it builds and the pattern its
    template is, so unlike a kernel definition it can be placed. In a Metamath
    import they add nothing, a `$a` having spelled the form before a `df-` gave it
    meaning; in a hand-authored system a definition may be the only thing that
    spells it.
    """
    by_spelling: dict[tuple[str, str], list[str]] = {}
    unmapped: set[str] = set()
    placed = [
        *_constructors_by_sort(context),
        *(
            (notation.sort.name, constructor_for(notation.template))
            for notation in notations
        ),
    ]
    for sort, constructor in placed:
        for kind, text in constructor.pieces:
            if kind == "lit":
                unmapped.update(w for w in text.split() if w not in tokens)
        if constructor.atom_value is not None and constructor.atom_value not in tokens:
            unmapped.add(constructor.atom_value)
        spelling = _spelling(constructor, tokens)
        if spelling is not None:
            by_spelling.setdefault((sort, spelling), []).append(constructor.name)

    collisions = tuple(
        Collision(sort=sort, spelling=spelling, productions=tuple(sorted(names)))
        for (sort, spelling), names in sorted(by_spelling.items())
        if len(names) > 1
    )
    return NotationReport(unmapped=tuple(sorted(unmapped)), collisions=collisions)


def unicode_projection(system: FormalSystem, typesetting: Typesetting) -> Projection:
    """The projection `set.mm`'s ``althtmldef`` map describes, as text.

    The convenience form of :func:`projection_for`: `$t` values are HTML, so they
    go through :func:`~.typesetting.as_text` first (see that function on why
    dropping the markup is a policy rather than a conversion). Takes the whole
    system because a projection needs both halves of its notation - the grammar's
    productions and the definitions' defined forms.
    """
    return projection_for(
        system.build_context,
        {token: as_text(value) for token, value in typesetting.unicode.items()},
        name="unicode",
        definitions=system.definitions,
    )
