"""Defined notation: the productions a grammar gains from its definitions."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from . import matches, patterns

if TYPE_CHECKING:
    from .context import Context
    from .matches import Match
    from .patterns import Pattern


class DefinedNotation:
    """A production the grammar gains from a definition.

    Grammatically, a definition's *defined* form is just another way to build a
    term of its sort — ``x ⊆ y`` forms a formula exactly as ``(p → q)`` does —
    and that is the whole of the matching layer's interest in definitions. What
    a definition *means*, that the defined form may be exchanged for a defining
    one, is a kernel definitional axiom
    (:class:`~website.logical.kernel.definitions.Definition`), and a cited step
    is checked against that. Nothing here can apply a definition, which is what
    stops a second, capture-blind checker growing beside the trusted one.

    One thing sets it apart from a declared production: its template is ad-hoc,
    so no union lists it as a member. A match therefore records the sort it
    inhabits (:attr:`~website.logical.matching.matches.Match.sort`) instead of
    leaving that to be read off the constructor.

    Deliberately *unlabelled*. A citation names a definition, not a notation, and
    two definitions may share one defined form — the same ``x sub y`` declared
    under two labels is one production of the grammar and two axioms for the
    kernel. Keeping the label on the kernel definition is what lets both stay
    separately citable without duplicating the production.
    """

    def __init__(self, defined: str, sort: Pattern, context: Context) -> None:

        # The sort this notation builds a term of.
        self.sort: Pattern = sort

        # The defined form's surface template. This is the constructor a term
        # built through this notation carries.
        self.template: patterns.StringPattern = patterns.StringPattern(
            name="Defined notation",
            pattern=defined,
            variables=copy(context.string_variables),
        )

    @property
    def variables(self) -> dict[str, Pattern]:
        # The defined form's parameters - the slots a use of it supplies.
        return self.template.variables

    def match(self, s: str, context: Context) -> Match | None:
        # Parse `s` as this defined form. The match's *constructor* is the
        # template, and the sort it inhabits is recorded alongside, so the term
        # layer projects it like any other production.
        matched = self.template.match(s, context)

        if matched is None:
            return None

        m = matches.Match(string=s, pattern=self.template, sort=self.sort)

        # Re-parent the template match's sub-matches. Shared, not copied: the
        # template match is discarded here and a match is inert once built. (A
        # copy would also give each sub-match a *copied pattern*, which defeats
        # term interning - the kernel keys a node on its constructor's identity.)
        for key, sub_match in matched.sub_matches.items():
            m.add_submatch(key, sub_match)

        return m

    def equivalent(self, other: object, context: Context, memo: dict | None = None,
                   allow_mapping_to: bool = False) -> bool:
        # Two notations are the same production when they build the same sort
        # from the same template. What each one *unfolds to* is not consulted:
        # that is the definition's business, and two definitions sharing a
        # defined form share this one production.
        if not isinstance(other, DefinedNotation):
            return False

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume True while the nested patterns are compared, so a recursive
        # grammar terminates.
        memo[(self, other)] = True

        if not self.template.equivalent(other.template, context, memo, allow_mapping_to):
            memo[(self, other)] = False
            return False

        if not self.sort.equivalent(other.sort, context, memo, allow_mapping_to):
            memo[(self, other)] = False
            return False

        return True

    def __str__(self) -> str:
        return f"Defined notation: '{self.template.pattern}' for {self.sort.name}"
