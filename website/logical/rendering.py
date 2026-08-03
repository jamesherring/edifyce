"""Rendering a term through a display projection.

A term is stored as a DAG and carries no notation of its own: a
:class:`~website.logical.kernel.constructors.Constructor` holds the *source*
template it was parsed from, and ``Node.to_string`` folds that template over the
children to rebuild the surface string. This module is the same fold with the
templates swapped, which is what lets one checked term be shown as ASCII,
Unicode, LaTeX or anything else without a second copy of it.

Why fold the term rather than substitute tokens
-----------------------------------------------
Metamath ships a per-*token* map (:mod:`~.metamath.typesetting`), and applying one
directly to a statement's tokens gives soup - ``( \\surd \\` 2 ) \\in \\mathbb{R}``.
The structure is in the tree, so folding per-*production* templates over the tree
keeps it: brackets, nesting and argument order come from the term, and only the
notation comes from the projection. A production may then render quite unlike its
source (``( sqrt \\` A )`` as ``\\sqrt{A}``), which per-token substitution can
never do.

The fold also reaches everything, which a `Match`-based renderer would not: a rule
schema, a promoted theorem's statement and a definition's two forms are all terms
with no match behind them.

Templates and rules
-------------------
A projection has two halves. Its ``templates`` re-spell one production each,
which is what a `$t`-style token map derives and is nearly all of a notation. Its
``rules`` (:class:`Rule`) match a *shape* instead - a production together with
what sits at particular slots - because the spellings a per-production template
cannot reach are exactly the ones where the interesting symbol is an operand:
``( sqrt \\` 2 )`` is generic application holding the constant ``csqrt``, and
``( A / B )`` is a generic binary operation holding ``cdiv``. A rule is tried
first and wins outright.

Outside the kernel, deliberately
--------------------------------
The kernel hard-codes no logic and stays small; display is not its business. It
exposes what a renderer needs - ``Constructor.pieces``, the same steps
``to_string`` walks - and nothing here reaches back in.

Canonical, not verbatim
-----------------------
A term is what the parse *meant*, so rendering it normalises: redundant brackets
the author typed are gone, and sort coercions collapse. Anyone needing the
author's own keystrokes back must keep the source string; this is not that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING

from .kernel.terms import Node, Term

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

    from .kernel.constructors import Constructor, Piece

# What separates the steps of a slot path in a :class:`Rule`. A path names a
# child of a child (``"F.G"``), which is how a rule reaches past the production at
# its root.
#
# Only a rule's steps are paths. A *template*'s are slot labels and are never
# split, because a Metamath slot label may itself contain a dot — `set.mm` names
# class variables `.+` and `.0.`, and `seq M ( .+ , F )` is a production whose slot
# is one. Within a rule those labels stay reachable because a path resolves
# longest-label-first at every level (:func:`longest_label`), so `A..+` names the
# `.+` of the child `A`.
PATH = "."


def longest_label(remaining: list[str], labelled: Callable[[str], bool]) -> int:
    """How many of ``remaining``'s steps the next slot label spans.

    A path is joined slot labels, and a Metamath slot label may itself contain the
    separator — `set.mm` names class variables `.+`, `.x.` and `.0.`. So a step is
    not simply everything up to the next dot: the longest join that names a child
    is the label, and the rest of the path continues from there. 0 means no prefix
    names one, which is a miss.

    Longest-first rather than shortest, so a child genuinely called ``A.B`` is
    preferred over descending into ``A``; a grammar with both is answering an
    ambiguity nobody can see from the path alone, and taking the more specific
    reading is the one that can be written around.

    Shared by both folds through :func:`_descend` and its row-graph twin, which is
    what keeps them agreeing about what a path *means*.
    """
    for count in range(len(remaining), 0, -1):
        if labelled(PATH.join(remaining[:count])):
            return count
    return 0


@dataclass(frozen=True)
class Rule:
    """A display template for a *shape* rather than for a single production.

    A per-constructor template reaches only what one production spells, and the
    interesting spellings are not there. ``set.mm`` builds ``( sqrt ` 2 )`` out of
    two productions - function application ``cfv`` applied to the *constant*
    ``csqrt`` - so no template for either says ``\\sqrt{2}``; likewise division,
    which is the generic binary operation ``co`` applied to ``cdiv``. Both are the
    same shape: a generic applicator whose operator slot happens to hold one
    particular thing.

    So a rule is that shape written down. ``constructor`` is the production at the
    root; ``pins`` fixes what must sit at given slot paths (``{"F": "csqrt"}``),
    and the rule applies only where every pin holds. ``pieces`` is the template,
    in the same ``("lit", text)`` / ``("slot", path)`` steps a
    :class:`~website.logical.kernel.constructors.Constructor` carries - except
    that a slot names a *path*, so a rule can reach a grandchild the root's own
    template cannot name.

    ``name`` identifies the rule to a curator and is what a layered notation
    overrides by; nothing dispatches on it.

    A rule is display only, like everything here: the term was settled before any
    of it was read, and a wrong rule renders badly rather than checking a false
    proof.
    """

    constructor: str
    pins: Mapping[str, str] = field(default_factory=dict)
    pieces: tuple[Piece, ...] = ()
    name: str = ""

    def roots(self, slots: Collection[str]) -> frozenset[str]:
        """Which of ``slots`` this rule accounts for - pinned or rendered.

        The first *label* of every path it mentions, resolved against ``slots`` the
        way :func:`render` resolves it against a term's children: longest match
        first, since a Metamath slot label may itself contain a dot (`set.mm` names
        class variables `.+` and `.0.`). ``.+.F`` therefore heads at ``.+`` where
        the root has that slot, and ``F.G`` at ``F``.

        A slot of the root missing from this is one the rule would silently drop,
        which is a term shown as something it is not;
        :func:`~website.logical.metamath.display.applicable_rules` refuses a rule
        on those grounds.
        """
        paths = chain(
            self.pins, (text for kind, text in self.pieces if kind == "slot")
        )
        found: set[str] = set()
        for path in paths:
            if not path:
                continue
            steps = path.split(PATH)
            span = longest_label(steps, slots.__contains__)
            # A path whose first step names no slot of the root touches nothing
            # this rule can account for; recording its head keeps it out of the
            # set and so refuses the rule, which is the safe direction.
            found.add(PATH.join(steps[:span]) if span else steps[0])
        return frozenset(found)


def rules_by_constructor(rules: Iterable[Rule]) -> dict[str, tuple[Rule, ...]]:
    """``rules`` indexed by the production at their root, most specific first.

    A render asks this once per constructor rather than scanning every rule, and
    the order is what makes overlapping rules deterministic: more pins is more
    specific, so a rule for ``co`` with its operator fixed is tried before one
    that fixes nothing, whatever order they were written or stored in. Ties keep
    the order given, so a caller that has an opinion still has it.
    """
    grouped: dict[str, list[Rule]] = {}
    for rule in rules:
        grouped.setdefault(rule.constructor, []).append(rule)
    return {
        constructor: tuple(sorted(found, key=lambda rule: -len(rule.pins)))
        for constructor, found in grouped.items()
    }


@dataclass(frozen=True)
class Projection:
    """Display templates for a rendering, by constructor name.

    ``templates`` maps a production's name to the render steps to use in place of
    its own - the same ``("lit", text)`` / ``("slot", label)`` shape
    ``Constructor.pieces`` holds, so a projection is a *substitute template*
    rather than a different kind of thing. A constructor the projection does not
    name renders from its own template, so a partial projection is useful and an
    empty one renders exactly as the source does.

    ``rules`` are the shape-matched templates (:class:`Rule`), tried *before*
    ``templates`` wherever one matches. They are a separate field rather than more
    entries in the map because they are keyed by a shape and not by a name, and
    because a notation is overwhelmingly the map: on `set.mm` the templates number
    in the thousands and the rules in single figures.

    ``name`` labels the projection for reporting ("unicode", "latex"); nothing
    dispatches on it.
    """

    templates: Mapping[str, tuple[Piece, ...]] = field(default_factory=dict)
    name: str = "source"
    rules: tuple[Rule, ...] = ()


def matches(rule: Rule, constructor_at: Callable[[str], str | None]) -> bool:
    """Whether ``rule``'s pins hold, given a way to name the constructor at a path.

    The one piece of rule-matching both folds share. :func:`render` walks
    :class:`~website.logical.kernel.terms.Term`s and
    ``app.db.notations_mapping.render_stored`` walks rows, so they cannot share a
    traversal - but they must agree about what *matching* means, and this is it.
    ``constructor_at`` returns None where the path leads nowhere, which never
    matches: a pin is a positive claim about what is there.
    """
    return all(constructor_at(path) == name for path, name in rule.pins.items())


def total_projection(
    constructors: Iterable[Constructor], base: Projection, name: str | None = None
) -> Projection:
    """``base`` extended to name every constructor, falling back to source steps.

    A projection built for rendering in memory names only what it *changes*, which
    keeps it small — the term carries its own constructor, so an unnamed one still
    renders. A projection that is going to be **stored** wants the opposite: a
    reader has rows and no grammar, so anything the notation does not name has no
    template to fall back to. Completing it against the constructors makes the
    stored notation self-contained, and a proof view then costs a query rather
    than a system rebuild.
    """
    templates = dict(base.templates)
    for constructor in constructors:
        if constructor.name in templates:
            continue
        if constructor.pieces:
            templates[constructor.name] = constructor.pieces
        elif constructor.atom_value is not None:
            templates[constructor.name] = (("lit", constructor.atom_value),)
    return Projection(
        templates=templates, name=name or base.name, rules=base.rules
    )


def render(term: Term, projection: Projection | None = None) -> str:
    """``term`` as a string, through ``projection`` where it has an opinion.

    With no projection this is ``term.to_string()`` exactly - which is a property
    worth relying on, since it means a projection can be introduced without
    changing what an unprojected caller sees.
    """
    if projection is None or not (projection.templates or projection.rules):
        return term.to_string()
    return _render(term, projection.templates, rules_by_constructor(projection.rules))


def _descend(term: Node, path: str) -> Term | None:
    # The subterm a rule's path names, or None where it names nothing. A path is
    # slot labels from this node down; the empty path names *this* node, which is
    # never what a caller wants and is the one value that would let a template
    # recurse on itself, so it is a miss rather than a fixed point.
    if not path:
        return None
    found: Term = term
    remaining = path.split(PATH)
    while remaining:
        if not isinstance(found, Node):
            return None
        children = found.children
        span = longest_label(remaining, children.__contains__)
        if not span:
            return None
        found = children[PATH.join(remaining[:span])]
        remaining = remaining[span:]
    return found


def _matching_rule(term: Node, rules: Mapping[str, tuple[Rule, ...]]) -> Rule | None:
    for rule in rules.get(term.constructor.name, ()):
        if matches(
            rule,
            lambda path: (
                found.constructor.name
                if isinstance(found := _descend(term, path), Node)
                else None
            ),
        ):
            return rule
    return None


def _render(
    term: Term,
    templates: Mapping[str, tuple[Piece, ...]],
    rules: Mapping[str, tuple[Rule, ...]] = {},
) -> str:
    if not isinstance(term, Node):
        # A `Var` (and so a `Bound`) renders as its own name: it stands for a term
        # rather than naming a production, so a projection has nothing to say about
        # it. Substituting metavariable *spellings* is a separate question from
        # notation and is not this map's job.
        return term.to_string()

    # A rule is tried first and wins outright: it was written *because* the root's
    # own template renders this shape badly, so consulting the template after
    # matching would undo the point. Its pinned children are consumed rather than
    # rendered - `( sqrt ` 2 )` becomes `\sqrt{2}` with no `sqrt` left in it.
    rule = _matching_rule(term, rules) if rules else None
    pieces = rule.pieces if rule is not None else templates.get(term.constructor.name)
    if pieces is None:
        # Mirrors `Node.to_string`. An atom carries its own text and has no
        # template; a bare regex or an abstract sort has neither, and stands for
        # its single child.
        if term.literal is not None:
            return term.literal
        pieces = term.constructor.pieces
    if not pieces:
        if len(term.children) == 1:
            return _render(next(iter(term.children.values())), templates, rules)
        return ""

    out: list[str] = []
    for kind, text in pieces:
        if kind == "lit":
            out.append(text)
            continue
        # Only a *rule*'s steps are paths. A template's are slot labels, and a
        # label may itself contain a dot — set.mm names class variables `.+` and
        # `.0.` — so reading one as a path would descend into nothing and print
        # the label where the operand belongs.
        child = _descend(term, text) if rule is not None else term.children.get(text)
        # A slot with no child means the template names something this term does
        # not carry - a projection written against a different production. Emit
        # the label, as `to_string` does, rather than raising in a renderer.
        out.append(_render(child, templates, rules) if child is not None else text)
    return "".join(out)
