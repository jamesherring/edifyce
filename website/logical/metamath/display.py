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
    from ..kernel.constructors import Piece
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
