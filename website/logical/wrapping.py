"""Wrapping a transferred statement in the shape the target states things in.

`website/logical/translation.py` is R4b: two systems that prove the *same shape*
of thing and disagree about what to call it. This is S2, and it is the other
difference two systems can have — they agree about the language and disagree
about what a **judgement** is. A Hilbert system's theorem is a formula; a sequent
system's is `Γ ⊢ φ`. No rename relates those, because there is nothing to rename:
the target's statement has a constructor at its root the source's never had, and
a metavariable (`Γ`) the source theorem never mentioned.

§5.4 stores that as a *statement template* on the edge, `'{Γ} ⊢ {0}'`, and §6.3
says the one thing that matters about applying it: **it composes a term.** The
transferred statement's stored term is substituted into a hole in the template's
term, so what a citation is checked against has the target's own constructor at
its root and the source's theorem as a subterm. Rendering the two into a string
and re-parsing would be the same answer only when the target's grammar reads the
concatenation the way the source's read the part — which is precisely what an
edge between two independently built systems may not assume (the `bj-0` hazard,
metamath roadmap §1.4).

How a template is written
-------------------------
Target notation, with the extras as ordinary metavariables and **one hole**
spelled `{<sort>}`:

    G ⊢ {wff}          extras: G : context

The hole names the sort the transferred statement is read at *here* — after the
edge's rename, so it is one of the target's sorts. Braces plus a **declared sort
name** are what make it a hole, and both halves are load-bearing. A bare name
would be a hole exactly when no production happened to claim it, which is not a
property an author can predict; and braces alone cannot do it either, since the
corpus this feature exists for spells set-builder `{ x | ph }` (found in review).
So braced text naming no sort is the target's own notation and is left alone.

What is *not* here is a claim that the wrap is **sound**. The template says what
shape a transferred statement takes; §2's obligations say why a theorem of that
shape holds, one per primitive of the source. This module composes a term and
checks it composes; whether `Γ ⊢ φ` follows from `⊢ φ` is the obligations' claim
and the author's to make. See §9.24 of docs/system-relationships-roadmap.md for
what that turns out to cost — the wrap has to hold *uniformly in the extras*, and
that is a stronger demand than it first looks.
"""

from __future__ import annotations

import json
import re
from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from website.logical.kernel import from_match
from website.logical.kernel.constructors import constructor_for
from website.logical.kernel.terms import Term, Var, intern
from website.logical.kernel.unify import sort_admits
from website.logical.matching import Pattern
from website.logical.promotion import logical_sorts

if TYPE_CHECKING:
    from collections.abc import Mapping

    from website.logical.formal_system import FormalSystem
    from website.logical.kernel.constructors import Constructor
    from website.logical.matching.context import Context

class SortMismatch(ValueError):
    """A transferred statement the template's hole cannot hold.

    Its own class so the persistence layer can turn it into the refusal a
    citation shows without catching every `ValueError` a substitution might
    raise — the same reason `_wrapped`'s other refusals are `LookupError`.
    """


# Candidate holes. What makes one a *hole* rather than object notation is that
# its content names one of the target's sorts — see :func:`_holes`, and the note
# on why that test is not "it is in braces".
_BRACED = re.compile(r"\{([^{}]*)\}")


def _holes(target: FormalSystem, text: str) -> list[str]:
    """The brace groups of ``text`` that are holes, as their sort names.

    Braces alone cannot decide it, and the case that settles it is the one this
    project exists to import: set-builder notation is `{ x | ph }`, so a grammar
    that spells ZFC has braces of its own, and a template stating a set-builder
    would otherwise read as a template with a spurious hole in it. Requiring the
    content to be a **declared sort** separates the two, since a sort name is
    something the grammar has told us about and `x | ph` is not.

    It leaves one ambiguity, and it is worth naming rather than guarding: a
    grammar whose object notation spells exactly `{wff}` for a sort it also calls
    `wff`. Nothing distinguishes those, and no grammar has both.
    """
    if target.build_context is None:
        return []
    return [
        braced
        for braced in _BRACED.findall(text)
        if isinstance(target.build_context.variables.get(braced), Pattern)
    ]


@dataclass(frozen=True)
class StatementTemplate:
    """How an edge restates a transferred theorem, and what it may name.

    ``text`` empty is **no wrap**, which is what every edge before S2 carries and
    what an `extension` edge carries always: the source and the target state the
    same kind of thing, so a transferred statement arrives as it is.
    :attr:`identity` is what a caller branches on, exactly as
    :attr:`~website.logical.translation.Translation.identity` is.

    ``extras`` are the metavariables the template introduces — `Γ : context` —
    named in the target's sorts. They become metavariables of every theorem that
    crosses the edge, which is what lets a citation instantiate `Γ` to whatever
    context the citing line happens to have.
    """

    text: str = ""
    extras: Mapping[str, str] = field(default_factory=dict)

    @property
    def identity(self) -> bool:
        """Whether this wraps nothing — the ordinary edge, and the fast path."""
        return not self.text

    @property
    def key(self) -> str:
        """A stable identity, for keying a memo that goes through this wrap.

        The same job :attr:`~website.logical.translation.Translation.key` does,
        and for the same reason: two layers of one chain may wrap a row
        differently, so a memo keyed by row id alone would hand the second
        layer the first one's answer. Empty for the identity, so an unwrapped
        chain memoises exactly as it did before this existed.
        """
        if self.identity:
            return ""
        return json.dumps(
            [self.text, sorted(self.extras.items())],
            ensure_ascii=False,
            sort_keys=True,
        )


NO_TEMPLATE = StatementTemplate()


@dataclass(frozen=True)
class BuiltTemplate:
    """A template parsed against the target, ready to wrap terms.

    ``shape`` is the template's own term — `turnstile{g: Var(G), p: Var({wff})}`
    for the example above — and ``hole`` the name of the variable standing where
    a transferred statement goes. Wrapping is then one substitution, which is the
    whole of §6.3's "a term construction, not a string substitution".
    """

    shape: Term
    hole: str
    hole_sort: Constructor
    extras: Mapping[str, str]
    context: Context

    def wrap(self, term: Term) -> Term:
        """``term`` restated in the target's shape.

        Refuses a term the hole's sort does not admit, and that check is not
        decoration (Codex, on #171). `Term.substitute` places whatever it is
        given, and **two productions of different sorts can be structurally
        identical** — declare `[A-Z]+` in both `ind` and `wff` and the two
        constructors share a `signature`, so their nodes compare `equal`.
        `sort_admits` is the only thing that tells them apart, and unify calls it
        for a *variable binding*, not for a subterm the wrap put there. Without
        this, an edge whose rename lands the source's statements in one sort and
        whose hole names another builds a term the grammar does not generate, and
        it would then justify a line at the hole's sort.
        """
        if not sort_admits(self.hole_sort, term):
            raise SortMismatch(
                f"The statement template reads a transferred statement at sort "
                f"{self.hole_sort.name!r}, which does not admit "
                f"{term.to_string()!r}."
            )
        return self.shape.substitute({self.hole: term}, self.context)

    def variable(self, name: str, sort: str) -> Term | None:
        """The term a bare metavariable of ``sort`` is, for wrapping a premise.

        A premise that is nothing but a metavariable — Metamath's `|- ph`, the
        ordinary shape of a hypothesis — composes no term and stores none
        (`promoted_theorems_mapping._term_id`), because a variable is not a
        structure worth caching. It still has to be *wrapped*, and a wrap needs a
        term, so this builds the one that was never worth storing. ``None`` when
        the sort is not one the target declares, which promotion refuses anyway
        and with a better message.
        """
        pattern = self.context.variables.get(sort)
        if not isinstance(pattern, Pattern):
            return None
        return intern(Var(name, constructor_for(pattern)))


def build_template(
    target: FormalSystem, template: StatementTemplate
) -> BuiltTemplate | None:
    """``template`` parsed against ``target``'s grammar, or ``None`` if it will not.

    ``None`` covers every way a template fails to become a term — no hole, a hole
    at a sort the target does not declare, an extra at one, text that parses at
    none of the target's logical sorts. :func:`template_errors` says *which*, for
    a route that has somewhere to report it; a resolver only needs to know that
    the edge transfers nothing, which is how every other unverifiable claim about
    an edge fails (see `app/db/system_relations_mapping.py`).
    """
    if template.identity or target.build_context is None:
        return None

    holes = _holes(target, template.text)
    if len(holes) != 1:
        return None

    hole = f"{{{holes[0]}}}"
    context = copy(target.build_context)
    # The target's *resolved* definitions, as `promotion._ground_schema_term`
    # takes them: a template is parsed against an already-compiled system, so
    # defined notation is available to it exactly as it is to a proof line.
    context.definitions = list(target.context.definitions)
    context.parse_memo = {}

    declared: dict[str, Pattern] = {}
    for name, sort_name in ((hole, holes[0]), *template.extras.items()):
        sort = target.build_context.variables.get(sort_name)
        if not isinstance(sort, Pattern):
            return None
        declared[name] = sort
    context.string_variables = declared

    # Read at the sorts a *proof line* is read at, never at whichever sort of the
    # grammar matches first. A wrapped statement is what a citation is checked
    # against, so it has to be a thing a line of this system could say.
    for sort in logical_sorts(target):
        matched = sort.match(template.text, context)
        if matched is not None:
            return BuiltTemplate(
                shape=from_match(matched),
                hole=hole,
                hole_sort=constructor_for(declared[hole]),
                extras=dict(template.extras),
                context=context,
            )
    return None


def template_errors(
    target: FormalSystem, template: StatementTemplate
) -> list[str]:
    """Why ``template`` does not restate a statement in ``target``, if it does not.

    Empty when it does. Separate from :func:`build_template` on the same split
    :func:`~website.logical.translation.translation_errors` and
    `system_relations_mapping._translates` are either side of: the resolver needs
    a boolean and fails closed on it, while the route that writes an edge owes
    its author a reason (§9.17).
    """
    if template.identity:
        return []

    if target.build_context is None:
        return [
            "The target system has no build context, so a template cannot be "
            "read against it."
        ]

    errors: list[str] = []
    holes = _holes(target, template.text)
    if not holes:
        braced = _BRACED.findall(template.text)
        errors.append(
            f"The statement template {template.text!r} has no hole, so there is "
            "nowhere for the transferred statement to go. A hole is a sort name "
            "in braces, as in 'G ⊢ {wff}'."
            + (
                " This system's grammar does not declare "
                + ", ".join(repr(text) for text in braced)
                + " as a sort, so that reads as notation of its own."
                if braced else ""
            )
        )
    elif len(holes) > 1:
        errors.append(
            f"The statement template {template.text!r} has {len(holes)} holes "
            "(" + ", ".join(repr(hole) for hole in holes) + "), and an edge "
            "transfers one statement."
        )

    for name, sort_name in (
        (name, sort) for name, sort in template.extras.items()
    ):
        if not isinstance(target.build_context.variables.get(sort_name), Pattern):
            errors.append(
                f"The template's {name!r} is read at sort {sort_name!r}, which "
                "the target system's grammar does not declare."
            )

    if not errors and build_template(target, template) is None:
        errors.append(
            f"The statement template {template.text!r} does not parse at any of "
            "the target system's logical sorts, so a wrapped statement would not "
            "be something a proof line here could say."
        )
    return errors
