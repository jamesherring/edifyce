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
`set.mm` renders them. Getting a better spelling means *overriding* that
production's template — :func:`with_overrides`, from a curated table
(`setmm.DISPLAY_OVERRIDES`), because seeding from the file is automatic and safe
while overriding is a decision. :func:`verbatim` is the list those decisions are
made from.

Spacing comes from the source template, not the map. A `$t` rendering carries its
own padding (``' &isin; '``), which is HTML's business; here the template already
says where the spaces go, so the mapped token is trimmed and dropped into the same
slot. That keeps ``( ph -> ps )`` rendering as ``( ph → ps )`` rather than
``( ph  →  ps )``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

from ..kernel.constructors import constructor_for
from ..kernel.definitions import Definition as KernelDefinition
from ..kernel.terms import Node
from ..matching.patterns import (
    AtomPattern,
    Pattern,
    RegexPattern,
    StringPattern,
    UnionPattern,
)
from ..rendering import Projection, Rule
from .typesetting import as_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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


def _reachable_sorts(context: FormalSystemContext) -> dict[str, set[str]]:
    # Each sort with every sort its inclusions reach, itself included. A sort
    # *including* another means everything the inner one builds is also a term of
    # the outer, so their input languages overlap and two slots taking them are
    # not distinguishable by sort name alone.
    direct: dict[str, set[str]] = {}
    for sort, pattern in context.variables.items():
        if not isinstance(pattern, UnionPattern):
            continue
        direct[sort] = {
            member.name
            for member in pattern.patterns
            if isinstance(member, UnionPattern)
        }
    closed: dict[str, set[str]] = {}
    for sort in direct:
        seen = {sort}
        stack = list(direct.get(sort, ()))
        while stack:
            inner = stack.pop()
            if inner in seen:
                continue
            seen.add(inner)
            stack.extend(direct.get(inner, ()))
        closed[sort] = seen
    return closed


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
        elif isinstance(member, (StringPattern, AtomPattern, RegexPattern)):
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


def notation_constructors(
    context: FormalSystemContext,
    definitions: Iterable[KernelDefinition] = (),
) -> list[Constructor]:
    """Every constructor a stored notation must give a spelling, deduplicated.

    What :func:`~website.logical.rendering.total_projection` completes a derived
    notation against, before it is stored: a reader has rows and no grammar, so a
    constructor the notation skips has no source template to fall back to and
    renders as a hole.

    ``definitions`` are the system's registered definitions, for the same reason
    :func:`projection_for` takes them — a *defined* form is notation the grammar
    does not spell, so it is a member of no sort's union and walking the grammar
    alone misses it. A stored term may carry one, so leaving it out would leave
    exactly the hole this function exists to prevent. Pass ``system.definitions``.

    Deduplicated, unlike :func:`_constructors_by_sort`, which reports a production
    once per sort it competes in because that is what an *ambiguity* is about. A
    notation is keyed by constructor name, so the sorts are beside the point.
    """
    everything = chain(
        (constructor for _sort, constructor in _constructors_by_sort(context)),
        (
            definition.higher.constructor
            for definition in definitions
            if isinstance(definition.higher, Node)
        ),
    )
    found: list[Constructor] = []
    seen: set[str] = set()
    for constructor in everything:
        if constructor.name in seen:
            continue
        seen.add(constructor.name)
        found.append(constructor)
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


def with_overrides(
    projection: Projection, overrides: Mapping[str, tuple[Piece, ...]]
) -> Projection:
    """``projection`` with these constructors re-spelled by hand.

    The editorial half of a notation. Seeding from a `$t` map is *faithful* — it
    re-spells the tokens a production is made of and leaves its shape alone, so
    ``( sqrt ` 2 )`` becomes ``( \\surd ` 2 )`` and never ``\\sqrt{2}``. Getting the
    second wants a decision about that production, which no map can supply.

    An override is keyed by constructor name and wins outright over whatever was
    derived, which is what makes it an override rather than a merge: a
    hand-written template is a whole spelling, and blending it with the derived
    one would produce something nobody wrote.

    Overriding a constructor the projection does not name is not an error — the
    common case is exactly that, a production the token map left in the source
    spelling because none of its tokens changed (see :func:`verbatim`).
    """
    return Projection(
        templates={**projection.templates, **overrides},
        name=projection.name,
        rules=projection.rules,
    )


def applicable(
    overrides: Mapping[str, tuple[Piece, ...]], constructors: Iterable[Constructor]
) -> dict[str, tuple[Piece, ...]]:
    """Those of ``overrides`` this grammar can actually use.

    An override is keyed by constructor *name*, and a curated table is a fact
    about one library (`setmm.DISPLAY_OVERRIDES` is `set.mm`'s). Applied to a
    different `.mm` the same names may be absent, or present with different slots
    — and a template naming a slot its term does not carry renders the *label*,
    so `{F}\\left({A}\\right)` over a two-slot ``cfv`` spelled `f`/`x` would put a
    literal ``F`` on the page.

    So an override survives only if the grammar has that constructor and their
    slots match **exactly** — same names, no more and no fewer. A subset is not
    enough: a foreign ``cfv`` taking `F`, `A` *and* `B` would pass a
    names-it-mentions test while silently dropping `B` from every rendering, which
    is a term shown as something it is not. Refusing beats both that and rendering
    a bare slot label, and it is what lets a caller hand the table to any import
    without checking the grammar first.

    Matching names and arity is still not proof of matching *meaning* — a Metamath
    label is local to its library — so a caller applying another library's table
    is making a judgement. It is just no longer making a silent mess.
    """
    known = {constructor.name: constructor for constructor in constructors}
    return {
        name: pieces
        for name, pieces in overrides.items()
        if (constructor := known.get(name)) is not None
        and {text for kind, text in pieces if kind == "slot"} == set(constructor.slots)
    }


def with_rules(projection: Projection, rules: Iterable[Rule]) -> Projection:
    """``projection`` with these shape-matched spellings added.

    :func:`with_overrides`' companion for what a per-production template cannot
    say. A rule matches a production *together with* what sits at given slots, so
    it reaches the spellings where the interesting symbol is an operand — `set.mm`
    writes ``( sqrt ` 2 )`` as generic application holding the constant `csqrt`,
    and no template for `cfv` or for `csqrt` turns that into ``\\sqrt{2}``.

    Added rather than replacing, unlike an override: rules are keyed by shape and
    a projection may hold several with the same root, since fixing a different
    operator in the same applicator is the whole idiom.
    """
    return Projection(
        templates=projection.templates,
        name=projection.name,
        rules=projection.rules + tuple(rules),
    )


def applicable_rules(
    rules: Iterable[Rule], constructors: Iterable[Constructor]
) -> list[Rule]:
    """Those of ``rules`` this grammar can actually use.

    :func:`applicable`'s counterpart, and it refuses on the same grounds, because
    a rule can go wrong in the same way and one more. Its root must be a
    production this grammar has, and its slots must cover that production's
    **exactly** — a rule quietly leaving a slot out renders a term as something it
    is not, and that is the failure mode a curated table carried between libraries
    produces. A rule mentioning a slot the root does not have is refused for the
    same reason in reverse: the slot would render as its own label.

    The extra check is the pins. A pin naming a production the grammar does not
    have can never match, so the rule is dead weight rather than a hazard — but it
    is *silently* dead, which is worse than refused when a table is being carried
    to a `.mm` whose labels happen to differ. Only the first step of a pin's path
    is checked against the root, since resolving a deeper one needs the sort of
    the slot it descends into and there is nothing in the corpus that wants it.

    As with :func:`applicable`, matching names and arity is not proof of matching
    *meaning* — a Metamath label is local to its library — so a caller applying
    another library's table is still making a judgement.
    """
    known = {constructor.name: constructor for constructor in constructors}
    kept: list[Rule] = []
    for rule in rules:
        root = known.get(rule.constructor)
        if root is None or rule.roots(root.slots) != frozenset(root.slots):
            continue
        if any(required not in known for required in rule.pins.values()):
            continue
        kept.append(rule)
    return kept


def verbatim(
    context: FormalSystemContext,
    projection: Projection,
    definitions: Iterable[KernelDefinition] = (),
) -> list[Constructor]:
    """Compound productions ``projection`` leaves spelled as the source spells them.

    §4.4's report, at the level that turns out to matter. The *token* level says
    almost nothing about a published corpus — `set.mm`'s ``latexdef`` covers all
    1,794 of its tokens, so :class:`NotationReport`'s ``unmapped`` is empty — while
    11 compound productions still come out in ASCII, because every token in them
    maps to itself. ``( F ` A )`` is one, and its backtick sets as a left quote:
    36% of `set.mm`'s statements contain one.

    Compound only. An atom the map leaves alone is a token that renders as itself,
    which is a judgement the file already made; a *production* left alone is a
    shape nobody has looked at, and that is the list an author wants.
    """
    return [
        constructor
        for constructor in notation_constructors(context, definitions)
        if constructor.pieces and constructor.name not in projection.templates
    ]


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
    """Two or more productions of one sort that a notation spells the same.

    A ``rules``-introduced spelling appears here under its rule's name prefixed
    with ``rule:``, since a rule is not a production and a curator reading this
    needs to know which of the two tables to edit.
    """

    sort: str
    spelling: str
    productions: tuple[str, ...]


# How a rule's name is written into `Collision.productions`. A rule and a
# production can share a name, and the two live in different tables.
RULE_PREFIX = "rule:"


@dataclass(frozen=True)
class NotationReport:
    """What a candidate notation would leave unsaid or say twice.

    §4.4's "report of unmapped tokens and colliding renderings", so re-syncing a
    notation against a grammar is driven by a list rather than by discovering
    breakage. The two halves matter for different reasons.

    ``unmapped`` is cosmetic: a token the notation does not spell renders in the
    source spelling, and the result is mixed but readable and still correct.

    ``collisions`` is not, and which it is depends on what the notation is *for*.
    As a **display** it is cosmetic too - two things that look alike are a
    presentation flaw, and the term is unambiguous underneath. As a **source** it
    is a correctness bug: two productions spelled alike cannot be told apart by a
    parser, so text no longer determines the term.

    **This finds collisions; it does not certify their absence.** Deciding whether
    a context-free grammar is ambiguous is not something a comparison of surface
    templates can do, and three rounds of review each found another way an earlier
    version answered "no collisions" for a grammar that had them - a regex leaf a
    mapped atom now matches, two slots whose sorts differ by name but overlap by
    inclusion, a defined form reachable from a sort that did not declare it. Those
    are fixed, and the honest reading of an empty ``collisions`` is *nothing was
    found by this check*, not *this notation is unambiguous*. Adopting a notation
    as a source wants a parser run over the corpus as well.
    """

    unmapped: tuple[str, ...] = ()
    collisions: tuple[Collision, ...] = ()

    @property
    def collision_free(self) -> bool:
        """Whether this check found nothing - a necessary condition for a source
        notation, and deliberately not called "usable": see the class docstring on
        what an empty result does and does not establish."""
        return not self.collisions


def _spelling(
    constructor: Constructor,
    tokens: Mapping[str, str],
    templates: Mapping[str, tuple[Piece, ...]],
) -> tuple[Piece, ...]:
    # How this notation actually renders the constructor. An *overridden* template
    # is already in the notation's own alphabet and must not be token-mapped again;
    # a source one is what the map re-spells. Getting this the wrong way round
    # would hide exactly the collisions an override introduces, which is the only
    # kind a curator can create.
    override = templates.get(constructor.name)
    if override is not None:
        return override
    if constructor.pieces:
        return tuple(
            ("lit", _map_literal(text, tokens)) if kind == "lit" else (kind, text)
            for kind, text in constructor.pieces
        )
    if constructor.atom_value is not None:
        return (("lit", tokens.get(constructor.atom_value, constructor.atom_value)),)
    return ()


def _skeleton(
    constructor: Constructor,
    tokens: Mapping[str, str],
    templates: Mapping[str, tuple[Piece, ...]] = {},
) -> str | None:
    # The literal shape, with every slot anonymous. Slot names are private to a
    # production, so two templates differing only in what they call a slot are
    # indistinguishable to a parser; whether their *sorts* keep them apart is a
    # separate question, asked per candidate pair by `_slots_overlap`.
    pieces = _spelling(constructor, tokens, templates)
    if not pieces:
        return None
    return "".join(text if kind == "lit" else "\x00" for kind, text in pieces)


def _shown(
    constructor: Constructor,
    tokens: Mapping[str, str],
    templates: Mapping[str, tuple[Piece, ...]] = {},
) -> str:
    # The same shape, printable: each slot as the sort it takes. A collision is a
    # user-facing record, so it must survive a terminal and a text column.
    pieces = _spelling(constructor, tokens, templates)
    if not any(kind == "slot" for kind, _text in pieces):
        return "".join(text for _kind, text in pieces) or constructor.name
    return "".join(
        text
        if kind == "lit"
        else f"<{constructor.slot_sorts[text].name}>"
        if text in constructor.slot_sorts
        else "<?>"
        for kind, text in pieces
    )


def _slots_overlap(
    left: Constructor, right: Constructor, reachable: Mapping[str, set[str]]
) -> bool:
    # Whether two same-shaped templates can accept the same text. Sorts are
    # compared by *language*, not by name: a sort including another accepts
    # everything it does, so a `<class>` slot and a `<setvar>` slot overlap
    # wherever `setvar` is included in `class`, and `( x ★ y )` matches both.
    if len(left.slots) != len(right.slots):
        return False
    for a, b in zip(left.slots, right.slots):
        first, second = left.slot_sorts.get(a), right.slot_sorts.get(b)
        if first is None or second is None:
            continue
        names = (first.name, second.name)
        if names[1] not in reachable.get(names[0], {names[0]}) and names[
            0
        ] not in reachable.get(names[1], {names[1]}):
            return False
    return True


def _matches_regex(leaf: Constructor, text: str) -> bool:
    # Whether a regex leaf of the sort accepts this whole spelling. A regex
    # production has a *language* rather than a spelling, so it cannot be compared
    # by grouping - but it can be asked. `signature` carries the regex text, the
    # constructor keeping no pattern object.
    _kind, expression = leaf.signature
    try:
        return re.fullmatch(expression, text) is not None
    except re.error:
        # An expression this module cannot compile is not evidence of a collision;
        # the grammar owns it, and refusing to report is the safe direction here
        # because a false collision would bury the real ones.
        return False


def notation_report(
    context: FormalSystemContext,
    tokens: Mapping[str, str],
    notations: Iterable[DefinedNotation] = (),
    templates: Mapping[str, tuple[Piece, ...]] | None = None,
    rules: Iterable[Rule] = (),
) -> NotationReport:
    """Check ``tokens`` against ``context``'s grammar before adopting it.

    Run this rather than reasoning about the token map: a map may collide heavily
    at the *token* level and not at all at the production level, because arity and
    position tell productions apart where a token map cannot. On `set.mm` the
    `$t` Unicode map shares 50 renderings across 107 tokens, and that comes to
    **32** colliding spellings - `∪` is three different tokens, but `( A ∪ B )`,
    `∪ A` and `∪ x ∈ A B` are three different shapes.

    ``notations`` are the defined forms, which are notation too and can collide
    with a declared production just as readily. Pass ``system.context.definitions``
    - a `DefinedNotation` carries both the sort it builds and the pattern its
    template is, so unlike a kernel definition it can be placed. In a Metamath
    import they add nothing, a `$a` having spelled the form before a `df-` gave it
    meaning; in a hand-authored system a definition may be the only thing that
    spells it.

    ``templates`` is the projection actually being adopted, when it differs from
    what ``tokens`` derives — pass ``projection.templates`` after applying
    overrides. Without it this reports the *derived* notation, and an override is
    invisible: it replaces a template wholesale, so a collision one introduces is
    exactly the kind a token-level check cannot see.

    ``rules`` is the other half of a projection, and the other way a curator
    creates a spelling. A rule re-spells a *shape*, so what it writes is a string
    no production's template contains — `( sqrt \\` A )` becomes ``\\sqrt{A}`` —
    and until it is passed here nothing checks that against the rest of the
    notation. Pass ``projection.rules``.

    A rule is compared by **shape alone**, without asking whether the slots could
    take the same text — unlike two productions, which are only reported once
    :func:`_slots_overlap` says so. That is a deliberate asymmetry rather than an
    omission: a rule's slots are *paths* into a pinned shape, so their sorts are
    not readable off one constructor, and a curated table is a handful of entries
    where a false positive costs a glance. The derived grammar is thousands, where
    it would bury the real ones.

    See :class:`NotationReport` on what an empty result does not establish.
    """
    spellings = {} if templates is None else templates
    reachable = _reachable_sorts(context)
    placed: list[tuple[str, Constructor]] = list(_constructors_by_sort(context))
    # A defined form is reachable from every sort that includes the one it builds,
    # because the parser tries the definitions of each union it descends through.
    for notation in notations:
        constructor = constructor_for(notation.template)
        own = notation.sort.name
        for sort, reaches in reachable.items():
            if own in reaches:
                placed.append((sort, constructor))

    unmapped: set[str] = set()
    grouped: dict[tuple[str, str], list[Constructor]] = {}
    regexes: dict[str, list[Constructor]] = {}
    for sort, constructor in placed:
        for kind, text in constructor.pieces:
            if kind == "lit":
                unmapped.update(w for w in text.split() if w not in tokens)
        if constructor.atom_value is not None and constructor.atom_value not in tokens:
            unmapped.add(constructor.atom_value)
        if constructor.kind == "regex":
            regexes.setdefault(sort, []).append(constructor)
            continue
        skeleton = _skeleton(constructor, tokens, spellings)
        if skeleton is not None:
            grouped.setdefault((sort, skeleton), []).append(constructor)

    collisions: list[Collision] = []
    for (sort, _skel), constructors in sorted(grouped.items()):
        # Same shape is necessary but not sufficient: the slots must be able to
        # take the same text too.
        clashing: set[str] = set()
        for i, left in enumerate(constructors):
            for right in constructors[i + 1:]:
                if _slots_overlap(left, right, reachable):
                    clashing.update((left.name, right.name))
        # A regex leaf of the sort accepts a language rather than a spelling, so
        # ask it directly whether it would also match what this one now spells.
        literal = _skeleton(constructors[0], tokens, spellings)
        if literal is not None and "\x00" not in literal:
            for leaf in regexes.get(sort, ()):
                if _matches_regex(leaf, literal):
                    clashing.update({c.name for c in constructors} | {leaf.name})
        if clashing:
            collisions.append(
                Collision(
                    sort=sort,
                    spelling=_shown(constructors[0], tokens, spellings),
                    productions=tuple(sorted(clashing)),
                )
            )
    collisions.extend(_rule_collisions(rules, placed, grouped, tokens, spellings))
    return NotationReport(
        unmapped=tuple(sorted(unmapped)),
        collisions=tuple(sorted(collisions, key=lambda c: (c.sort, c.spelling))),
    )


def _rule_collisions(
    rules: Iterable[Rule],
    placed: Sequence[tuple[str, Constructor]],
    grouped: Mapping[tuple[str, str], list[Constructor]],
    tokens: Mapping[str, str],
    spellings: Mapping[str, tuple[Piece, ...]],
) -> list[Collision]:
    """Spellings the ``rules`` half of a projection introduces, against everything.

    A rule competes for a reading in every sort its **root** production is placed
    at: it renders a term built by that production, so wherever one of those can
    be parsed, so can this. Its own pieces are already in the target notation —
    a rule is authored, not derived — so unlike a production's they are not mapped
    through ``tokens``.
    """
    # (sort, skeleton) -> the rules spelling it, and the sorts each rule sits in.
    by_shape: dict[tuple[str, str], list[str]] = {}
    for index, rule in enumerate(rules):
        skeleton = "".join(
            text if kind == "lit" else "\x00" for kind, text in rule.pieces
        )
        if not skeleton:
            continue
        # `Rule.name` is optional and nothing dispatches on it, so two rules can
        # share one — and two *unnamed* rules on one root share the empty string.
        # The identity has to stay distinct or the pair being reported would
        # deduplicate itself away, which is the collision going quiet at exactly
        # the moment it is found.
        identity = f"{RULE_PREFIX}{rule.name or f'{rule.constructor}#{index}'}"
        for sort in {s for s, c in placed if c.name == rule.constructor}:
            by_shape.setdefault((sort, skeleton), []).append(identity)

    found: list[Collision] = []
    for (sort, skeleton), names in sorted(by_shape.items()):
        # Both directions at once: two rules spelling one shape, and a rule
        # spelling what a production already does.
        clashing = set(names) | {c.name for c in grouped.get((sort, skeleton), ())}
        if len(clashing) < 2:
            continue
        found.append(
            Collision(
                sort=sort,
                spelling=_readable(skeleton),
                productions=tuple(sorted(clashing)),
            )
        )
    return found


def _readable(skeleton: str) -> str:
    # A skeleton's slots are NULs so they compare equal whatever they are called;
    # a collision is a user-facing record and has to survive a terminal.
    return skeleton.replace("\x00", "<>")


def unicode_projection(system: FormalSystem, typesetting: Typesetting) -> Projection:
    """The projection `set.mm`'s ``althtmldef`` map describes, as text.

    The convenience form of :func:`projection_for`: `$t` values are HTML, so they
    go through :func:`~.typesetting.as_text` first (see that function on why
    dropping the markup is a policy rather than a conversion). Takes the whole
    system because a projection needs both halves of its notation - the grammar's
    productions and the definitions' defined forms.

    The one-map form, for a caller that wants only this reading. An import takes
    the general path instead, because it derives every map the file declares and
    applies the editorial overrides to each (`app.db.metamath_store`).
    """
    return projection_for(
        system.build_context,
        {token: as_text(value) for token, value in typesetting.unicode.items()},
        name="unicode",
        definitions=system.definitions,
    )
