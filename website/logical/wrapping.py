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
edge's rename, so it is one of the target's sorts. Braces are what make the hole
unmistakable: a name a grammar could also spell would be a hole exactly when no
production happened to claim it, which is not a property an author can predict.

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
from website.logical.matching import Pattern
from website.logical.promotion import logical_sorts

if TYPE_CHECKING:
    from collections.abc import Mapping

    from website.logical.formal_system import FormalSystem
    from website.logical.matching.context import Context

# The hole, and the only thing a template's text says that is not target
# notation. One per template: two would be two statements to put somewhere, and
# an edge transfers one.
_HOLE = re.compile(r"\{([^{}]*)\}")


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
    extras: Mapping[str, str]
    context: Context

    def wrap(self, term: Term) -> Term:
        """``term`` restated in the target's shape."""
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

    holes = _HOLE.findall(template.text)
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

    errors: list[str] = []
    holes = _HOLE.findall(template.text)
    if not holes:
        errors.append(
            f"The statement template {template.text!r} has no hole, so there is "
            "nowhere for the transferred statement to go. Write the sort it is "
            "read at in braces, as in 'G ⊢ {wff}'."
        )
    elif len(holes) > 1:
        errors.append(
            f"The statement template {template.text!r} has {len(holes)} holes "
            "(" + ", ".join(repr(hole) for hole in holes) + "), and an edge "
            "transfers one statement."
        )

    if target.build_context is None:
        errors.append(
            "The target system has no build context, so a template cannot be "
            "read against it."
        )
        return errors

    for name, sort_name in ((None, holes[0] if holes else None), *(
        (name, sort) for name, sort in template.extras.items()
    )):
        if sort_name is None:
            continue
        if not isinstance(target.build_context.variables.get(sort_name), Pattern):
            errors.append(
                f"The template's {'hole' if name is None else repr(name)} is read "
                f"at sort {sort_name!r}, which the target system's grammar does "
                "not declare."
            )

    if not errors and build_template(target, template) is None:
        errors.append(
            f"The statement template {template.text!r} does not parse at any of "
            "the target system's logical sorts, so a wrapped statement would not "
            "be something a proof line here could say."
        )
    return errors
