"""Reading a theorem stated in one system's names as a theorem of another's.

The spine (`formal_systems.inherits_from_id`) and a plain relation edge both
transfer a theorem *under its own names*: the child's `implication` is the
parent's row, so an ancestor's stored term rebuilds in the descendant's context
without anything being translated (docs/system-relationships-roadmap.md §3.1).
That is the identity case, and it is the common one.

An edge between two systems built independently has no such luck. They may agree
about `→` and disagree about what to call it — one's sort is `prop` and the
other's is `wff`, one's production is `implication` and the other's is `imp` — and
R4b of the roadmap is that disagreement, expressed as a **rename** and applied as
a *term-level constructor remap*: the source's stored term is rebuilt against the
**target's** constructors, resolved by the translated name. No re-parse, and no
second representation — the same graph read a citation across the spine already
is, with one substitution in front of the lookup.

What that buys, and what it therefore has to earn
-------------------------------------------------
A rename is a claim about two grammars, and the claim is that the target's
language *contains* the source's under the map. §3.2 says how it is checked, and
says it in the only terms that can be trusted: **the target's constructor must
admit a superset of the source's**, asked of :attr:`Constructor.admits` rather
than of the two sorts' names. Comparing names would accept a target that spells
`wff` and means something else entirely, which is exactly the failure a rename
makes possible in the first place.

So :func:`translation_errors` refuses a map that **narrows** — a source sort with
a branch whose image the target's sort does not admit — and one whose image is
not there at all. Both fail closed: an edge whose translation does not check out
resolves nothing, on the same rule as an edge with an outstanding obligation.

**It is checked over the source's grammar, not over the map.** The tables say
what an author wrote down; :meth:`Translation.name` is applied to every name a
stored term carries, which is a much larger set, and the difference is exactly
the names nobody said anything about. So the whole source grammar is walked,
every name must have an image here, and an **unmapped** name — one the map leaves
to land on its own spelling — has to be the *same production* on both sides,
template and all. Two systems that both say `implication` and disagree about what
it spells are two productions sharing a name, and reading a theorem from one as a
theorem about the other is the silent version of the failure this module exists
to prevent. Mapping a name to itself is how an author declares that they do mean
those two to correspond.

Two more follow from the same walk. Two source names may not become **one**
target name, since a collapse makes a theorem about either justify a statement
about the other; and a **definition**'s notation is held to the same totality as
a production's, since a term built through one carries its name too.

Three things a rename may **not** change, and one of them is not obvious. A
production's ``kind`` and its ``scopes_over`` are what decide how a term is built
and what binds in it; renaming across a difference in either would give the
transferred theorem a binding structure its own system never had. And its
``slots`` are the labels a stored term keys its children by — `to_string` and
child alignment both look a slot up by name — so two productions related by the
map have to spell their slots alike. That last one is a genuine restriction on
what an author may write rather than a soundness argument, and it is here
because the tables of §5.4 carry a sort map and a symbol map and no *slot* map:
the surface template and the name are what a rename is allowed to move.

What is deliberately **not** compared is an atom's value. Sending the source's
`⊥` to a target constant spelled otherwise is not a mistake — it is what an
interpretation *is*, and §2's obligations are what make it sound, one per source
primitive. Structure is this module's business; meaning is theirs.

What is *not* here is the statement template of §5.4 — `'{Γ} ⊢ {0}'`, which
wraps a transferred statement rather than renaming it. That is S2's, and it
composes a term rather than substituting a name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from website.logical.kernel.constructors import constructor_for
from website.logical.matching import Pattern, UnionPattern

if TYPE_CHECKING:
    from collections.abc import Mapping

    from website.logical.formal_system import FormalSystem
    from website.logical.kernel.constructors import Constructor

# What separates a defined form's sort from its template in the constructor name
# `DefinedNotation` gives it. A declared production's name can never contain it,
# which is what lets one lookup serve both namespaces (see `TermGraph._constructor`).
NOTATION_SEPARATOR = ":"


@dataclass(frozen=True)
class Translation:
    """How a source system's names are read as a target system's.

    Both maps are **empty for identity**, never filled with a row per name, so
    the ordinary edge — two systems that agree on their vocabulary — carries
    nothing and costs nothing. :attr:`identity` is what every caller branches on.

    Two maps because §5.4 stores two, and because only one of them can be
    checked: a *sort* is a claim about what the target admits
    (:func:`translation_errors`), while a *symbol* is a claim about one
    production. They are looked up as one namespace, which is what the systems
    themselves do — a grammar name is unique within a system
    (``uq_symbols_system_name``), so a sort and a production cannot collide.
    """

    sorts: Mapping[str, str] = field(default_factory=dict)
    symbols: Mapping[str, str] = field(default_factory=dict)

    @property
    def identity(self) -> bool:
        """Whether this translates nothing — the common edge, and the fast path."""
        return not self.sorts and not self.symbols

    def name(self, stored: str) -> str:
        """The target's name for a stored production, sort or notation name.

        Unmapped names pass through, so a partial map is the identity on
        everything it does not mention. That is what lets an edge state only the
        names that actually differ — and :func:`translation_errors` is what makes
        the silence safe, by holding an unmapped name to being the *same*
        production on both sides rather than merely a name both spell.

        A **defined form** is named ``<sort>:<template>``
        (:class:`~website.logical.matching.definitions.DefinedNotation`), which
        neither table can hold: a definition declares no symbol row. Its sort
        half is translated and its template left alone, so a definition the two
        systems state alike resolves through a sort rename — and one they spell
        differently is refused by :func:`translation_errors` rather than left to
        fail when something cites it.
        """
        renamed = self.symbols.get(stored)
        if renamed is not None:
            return renamed
        direct = self.sorts.get(stored)
        if direct is not None:
            return direct
        sort, separator, template = stored.partition(NOTATION_SEPARATOR)
        if separator and sort in self.sorts:
            return f"{self.sorts[sort]}{separator}{template}"
        return stored

    @property
    def key(self) -> str:
        """A stable identity, for memoising a rebuild that goes through this map.

        A term graph is read once and rebuilt against several layers, and two
        layers of one chain can translate the same row differently — so a memo
        keyed by row id alone would hand the second layer the first one's answer.
        The identity translation's key is empty, so an unrenamed chain memoises
        exactly as it did before this existed.
        """
        if self.identity:
            return ""
        return json.dumps(
            [sorted(self.sorts.items()), sorted(self.symbols.items())],
            ensure_ascii=False,
            sort_keys=True,
        )


IDENTITY = Translation()


def translation_errors(
    source: FormalSystem, target: FormalSystem, translation: Translation
) -> list[str]:
    """Why ``translation`` does not read ``source``'s language into ``target``'s.

    Empty when it does. Every message names both systems' spelling of whatever it
    is refusing, because a rename's failures are otherwise unreadable: the whole
    difficulty is that two names denote the same thing, or fail to.

    Checked over the **source's whole grammar**, not over the map's entries.
    :meth:`Translation.name` is applied to every name a stored term carries, so a
    check that read only the two tables would validate a fraction of what the
    translation actually does — and the names it skipped are exactly the ones the
    author said nothing about, which is where a silent divergence lives.

    So every production and sort of the source is required to have an image here,
    and the two are held to corresponding. What that means depends on whether the
    author said so: a **mapped** name is a declared correspondence, so its image
    may be spelled differently (that is the interpretation), while an **unmapped**
    one is only a name both systems happen to use, and must be the same
    production down to its template. Mapping a name to itself is how an author
    declares the first about a name the second would refuse.

    The sort half is §3.2, and is the reason this function takes built systems
    rather than specs: a sort's branches are :attr:`Constructor.admits`, which
    only exists once the grammar has been projected.
    """
    if translation.identity:
        return []

    source_grammar = _grammar(source)
    target_grammar = _grammar(target)
    declared = set(translation.sorts) | set(translation.symbols)
    errors = [
        f"The map renames {name!r}, which the source system's grammar does not "
        "declare."
        for name in sorted(declared - set(source_grammar))
    ]
    errors.extend(_collision_errors(source_grammar, translation))

    for original in sorted(source_grammar):
        renamed = translation.name(original)
        to_pattern = target_grammar.get(renamed)
        if to_pattern is None:
            errors.append(
                f"The source's {original!r} is read here as {renamed!r}, which "
                "the target system's grammar does not declare."
            )
            continue
        errors.extend(
            _correspondence_errors(
                original,
                renamed,
                constructor_for(source_grammar[original]),
                constructor_for(to_pattern),
                translation,
                declared=original in declared,
            )
        )

    return errors + _notation_errors(source, target, translation)


def _collision_errors(
    source_grammar: Mapping[str, Pattern], translation: Translation
) -> list[str]:
    # Two of the source's names may not become one of the target's. The unique
    # index behind the map is on the *source* side only, so nothing else stops it,
    # and a collapse makes two of the source's connectives one of the target's —
    # under which a theorem about one justifies a statement about the other.
    #
    # This is a restriction on what an author may state rather than a soundness
    # argument: an interpretation that genuinely identifies two primitives is
    # sound when its obligations discharge, and would want a way to say so. It is
    # refused because nothing in this codebase can tell that apart from a
    # mis-stated map, and the two names are always available to say it another
    # way. Read over the whole grammar, since an unmapped name lands on its own
    # spelling and can collide with a mapped one just as easily.
    taken: dict[str, str] = {}
    errors: list[str] = []
    for original in sorted(source_grammar):
        renamed = translation.name(original)
        held = taken.setdefault(renamed, original)
        if held != original:
            errors.append(
                f"The map reads both {held!r} and {original!r} as {renamed!r}. "
                "Two of the source's productions cannot become one of the "
                "target's: a theorem about either would then justify a statement "
                "about the other."
            )
    return errors


def _correspondence_errors(
    original: str,
    renamed: str,
    from_constructor: Constructor,
    to_constructor: Constructor,
    translation: Translation,
    declared: bool,
) -> list[str]:
    # Everything asked of one source name and its image: that they are the same
    # shape of production, that an unmapped pair really is one production under
    # one name, and — for a sort — that the target's admits what the source's did.
    errors = _shape_errors(original, renamed, from_constructor, to_constructor)
    if not declared and from_constructor.signature != to_constructor.signature:
        errors.append(
            f"{original!r} is spelled {from_constructor.signature[-1]!r} in the "
            f"source and {to_constructor.signature[-1]!r} here, and the map does "
            "not mention it — so the two are different productions that share a "
            "name. Map it explicitly if they are meant to correspond."
        )

    admitted = {constructor.name for constructor in to_constructor.admits}
    for branch in sorted(from_constructor.admits, key=lambda c: c.name):
        image = translation.name(branch.name)
        if image in admitted:
            continue
        errors.append(
            f"Sort {original!r} admits {branch.name!r}, whose image "
            f"{image!r} the target's {renamed!r} does not admit, so the map "
            "narrows: a statement the source could make would not be a "
            "statement of the target."
        )
    return errors


def _notation_errors(
    source: FormalSystem, target: FormalSystem, translation: Translation
) -> list[str]:
    # A defined form is a production of the grammar too — `x ⊆ y` builds a formula
    # exactly as `(p → q)` does — but it is nobody's union member and holds no
    # symbol row, so `_grammar` cannot see it and neither table can name it. Its
    # constructor name still reaches a stored term, so the same totality is asked
    # of it here: every notation the source's definitions introduce must have an
    # image among the target's.
    #
    # Only the *defined* form is compared. What the two systems define it to mean
    # is their own business, on the same ground as an atom's value: reinterpreting
    # a symbol is what an interpretation does, and §2's obligations are what carry
    # it.
    available = {notation.template.name for notation in target.context.definitions}
    return [
        f"The source's definition of {notation.template.name!r} is read here as "
        f"{translation.name(notation.template.name)!r}, which this system defines "
        "no notation for."
        for notation in source.context.definitions
        if translation.name(notation.template.name) not in available
    ]


def _shape_errors(
    original: str, renamed: str, from_constructor: Constructor, to_constructor: Constructor
) -> list[str]:
    # What a rename may not move. See this module's note: `kind` and `scopes_over`
    # decide what a term *is*, and `slots` are the keys its children are stored
    # under, so a difference in any of the three would rebuild the source's term
    # as something else rather than as the same thing under another name.
    errors: list[str] = []
    if from_constructor.kind != to_constructor.kind:
        errors.append(
            f"{original!r} is a {from_constructor.kind} production and "
            f"{renamed!r} is a {to_constructor.kind} one, so one cannot be read "
            "as the other."
        )
    if from_constructor.slots != to_constructor.slots:
        errors.append(
            f"{original!r} takes slots {list(from_constructor.slots)} and "
            f"{renamed!r} takes {list(to_constructor.slots)}. A stored term keys "
            "its children by slot name, and an edge carries no slot map, so two "
            "related productions must spell their slots alike."
        )
    if from_constructor.scopes_over != to_constructor.scopes_over:
        errors.append(
            f"{original!r} binds {from_constructor.scopes_over or '{}'} and "
            f"{renamed!r} binds {to_constructor.scopes_over or '{}'}, so a "
            "statement transferred through the map would bind differently from "
            "the one that was proved."
        )
    return errors


def _grammar(system: FormalSystem) -> dict[str, Pattern]:
    """Every sort and production of ``system``'s grammar, by name.

    Read off the sort unions rather than straight out of
    ``build_context.variables``, and for the reason
    :meth:`~app.db.terms_mapping.TermGraph._grammar_of` records: that namespace
    is shared with lines, line parts and axioms, which are registered *after* the
    productions, so a production and an axiom of one name leave the axiom under
    the key. The unions are the authority — a declared production is always a
    member of its sort's union — and a sort is here under its own name too, which
    is what the sort half of :func:`translation_errors` looks up.
    """
    grammar: dict[str, Pattern] = {}
    for candidate in system.build_context.variables.values():
        if not isinstance(candidate, UnionPattern):
            continue
        grammar.setdefault(candidate.name, candidate)
        for member in candidate.patterns:
            if isinstance(member, Pattern):
                grammar.setdefault(member.name, member)
    return grammar
