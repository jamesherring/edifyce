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
        names that actually differ.
        """
        renamed = self.symbols.get(stored)
        if renamed is not None:
            return renamed
        return self.sorts.get(stored, stored)

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

    The sort half is §3.2, and is the reason this function takes built systems
    rather than specs: a sort's branches are :attr:`Constructor.admits`, which
    only exists once the grammar has been projected.
    """
    if translation.identity:
        return []

    source_grammar = _grammar(source)
    target_grammar = _grammar(target)
    errors: list[str] = []

    for original, renamed in sorted(translation.symbols.items()):
        pair, missing = _mapped(source_grammar, target_grammar, original, renamed)
        errors.extend(missing)
        if pair is not None:
            errors.extend(_shape_errors(original, renamed, *pair))

    for original, renamed in sorted(translation.sorts.items()):
        pair, missing = _mapped(source_grammar, target_grammar, original, renamed)
        errors.extend(missing)
        if pair is None:
            continue
        from_sort, to_sort = pair
        admitted = {constructor.name for constructor in to_sort.admits}
        for branch in sorted(from_sort.admits, key=lambda c: c.name):
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


def _mapped(
    source_grammar: Mapping[str, Pattern],
    target_grammar: Mapping[str, Pattern],
    original: str,
    renamed: str,
) -> tuple[tuple[Constructor, Constructor] | None, list[str]]:
    # Both ends of one map entry, projected — and the reasons there is no such
    # pair. A name absent from either grammar is a mis-stated edge rather than a
    # narrowing, and saying *which side* is missing is the whole of the
    # diagnosis, so both are reported rather than the first.
    from_pattern = source_grammar.get(original)
    to_pattern = target_grammar.get(renamed)
    errors: list[str] = []
    if from_pattern is None:
        errors.append(
            f"The map renames {original!r}, which the source system's grammar "
            "does not declare."
        )
    if to_pattern is None:
        errors.append(
            f"The map sends {original!r} to {renamed!r}, which the target "
            "system's grammar does not declare."
        )
    if from_pattern is None or to_pattern is None:
        return None, errors
    return (constructor_for(from_pattern), constructor_for(to_pattern)), errors


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
