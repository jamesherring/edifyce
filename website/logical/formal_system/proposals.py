"""A term proposed as structure, and its resolution against a grammar.

The write half of the structured path that :mod:`~.diagnostics` and the citation
endpoint left open. A citation is a label and some integers, which need no
grammar; *stating* a formula does, and this is it.

A :class:`Proposal` is one of three things:

* ``ref`` — an id naming a term that already exists. The reason the whole thing
  is worth having: an interned term is shared, so a caller can say "the subterm
  at that position" instead of restating it. In a corpus where statements nest
  deeply that is the difference between a tractable emission and a long one that
  has to be exactly right.
* ``constructor`` — a production by name, with a :class:`Proposal` per slot. The
  vocabulary is the grammar's own and therefore closed and enumerable, which is
  what makes a constrained emission possible rather than aspirational.
* ``var`` — a metavariable of a named sort.

What resolution is *not*
------------------------
It is not a second parser. Nothing here reads surface syntax; a proposal names
productions, and the text a proposal eventually becomes is `rendering.render` of
the resolved term — the source spelling by construction, because a constructor's
own ``pieces`` are the source template.

That is what lets the round trip be **checked** rather than trusted: render the
resolved term, parse it back, and confirm the term that comes out is the term
that went in. A caller never has to be believed about what it meant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..kernel.terms import Node, Term, Var, intern
from ..matching.patterns import Pattern, UnionPattern

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ..kernel.constructors import Constructor
    from ..matching.context import Context


class ProposalError(Exception):
    """A proposal this grammar cannot resolve.

    Always the caller's mistake rather than the system's, and always specific:
    the point of a structured path is that a rejection says which production or
    slot was wrong, not that something was.
    """


@dataclass(frozen=True)
class Proposal:
    """A term named structurally: by reference, by production, or as a variable.

    Exactly one of ``ref``, ``constructor`` and ``var`` is set. ``literal`` and
    ``slots`` qualify ``constructor`` — a compound names one proposal per slot, a
    leaf carries the token it stands for (a constant atom's comes from the
    production itself, so it may be omitted there).

    ``sort`` names the sort a ``var`` ranges over. It is also accepted on a
    ``constructor`` for the one case a term carries it: a defined form, whose
    constructor is not itself a member of the sort it inhabits.
    """

    ref: str | None = None
    constructor: str | None = None
    slots: Mapping[str, "Proposal"] = field(default_factory=dict)
    literal: str | None = None
    var: str | None = None
    sort: str | None = None


def grammar_index(context: Context) -> dict[str, Pattern]:
    """``name -> production`` for everything the sorts of ``context`` can build.

    The unions are the authority, and deliberately not ``context.variables``:
    that namespace is shared with lines, line parts, axioms and the system
    itself, which are registered *after* the productions, so a name declared
    twice resolves to the later one. A production named ``implication`` and an
    axiom of that name leave the axiom's ``LineType`` under the key; a line
    *part* of that name leaves a ``RegexPattern``, which is worse, because it is
    a pattern and so passes for an answer.

    O(grammar), so a caller resolving many names builds it once — the lesson
    ``build_context._GrammarIndex`` already records.
    """
    grammar: dict[str, Pattern] = {}
    for candidate in context.variables.values():
        if not isinstance(candidate, UnionPattern):
            continue
        for member in candidate.patterns:
            if isinstance(member, Pattern):
                grammar.setdefault(member.name, member)
    return grammar


def resolve(
    proposal: Proposal,
    context: Context,
    constructor_for_name: Callable[[str], Constructor],
    term_for_ref: Callable[[str], Term | None],
) -> Term:
    """The interned term ``proposal`` names, or raise :class:`ProposalError`.

    ``constructor_for_name`` resolves a production name and ``term_for_ref`` an
    existing term's id — both injected, because the first is a question about a
    built system and the second about storage, and this module should have to
    know about neither.
    """
    return intern(_resolve(proposal, context, constructor_for_name, term_for_ref, ()))


def _forbid(
    proposal: Proposal, where: str, kind: str, *, sort: bool = True
) -> None:
    # Fields this kind of proposal does not use. A proposal carrying one meant
    # something the resolution will not do, and saying so beats quietly doing
    # less than was asked — which for a `ref` the round trip cannot even notice,
    # since the referenced term *is* the term that comes back.
    carried: list[str] = []
    if proposal.slots:
        carried.append("slots")
    if proposal.literal is not None:
        carried.append("literal")
    if sort and proposal.sort is not None:
        carried.append("sort")
    if carried:
        raise ProposalError(
            f"{kind}{where} carries {', '.join(carried)}, which it does not use."
        )


def _resolve(
    proposal: Proposal,
    context: Context,
    constructor_for_name: Callable[[str], Constructor],
    term_for_ref: Callable[[str], Term | None],
    path: tuple[str, ...],
) -> Term:
    where = f" at {'.'.join(path)}" if path else ""
    named = [
        name
        for name, value in (
            ("ref", proposal.ref),
            ("constructor", proposal.constructor),
            ("var", proposal.var),
        )
        if value is not None
    ]
    if len(named) != 1:
        raise ProposalError(
            f"A proposal{where} names {', '.join(named) or 'nothing'}; it must name "
            "exactly one of ref, constructor or var."
        )

    if proposal.ref is not None:
        # Refused rather than ignored, and this is the arm where it matters most:
        # a referenced term *is* the term, so the round-trip check cannot notice
        # that slots were meant to qualify it. Silently dropping them would commit
        # a line stating something other than what was asked for.
        _forbid(proposal, where, "A ref")
        found = term_for_ref(proposal.ref)
        if found is None:
            raise ProposalError(f"No term{where} with id {proposal.ref!r}.")
        return found

    if proposal.var is not None:
        _forbid(proposal, where, "A variable", sort=False)
        if proposal.sort is None:
            raise ProposalError(
                f"The variable {proposal.var!r}{where} needs a sort to range over."
            )
        return Var(proposal.var, constructor_for_name(proposal.sort))

    assert proposal.constructor is not None  # noqa: S101 - narrowed by the check above
    constructor = constructor_for_name(proposal.constructor)
    expected = set(constructor.slots)
    given = set(proposal.slots)
    if given != expected:
        # Exactly, not "at least": a slot left out would render as its own label
        # and a slot invented would be dropped, and both are a term meaning
        # something other than what was asked for.
        missing = ", ".join(sorted(expected - given)) or "none"
        extra = ", ".join(sorted(given - expected)) or "none"
        raise ProposalError(
            f"{proposal.constructor!r}{where} takes slots "
            f"{', '.join(constructor.slots) or '(none)'}; missing: {missing}; "
            f"unexpected: {extra}."
        )

    literal = proposal.literal
    if not expected:
        # A leaf carries the token it stands for. A *constant* atom's is the
        # production's own — the production names one fixed thing, and its
        # spelling is not the term's to choose — so it need not be given, and
        # giving a different one is a caller inventing a token.
        if constructor.atom_value is not None:
            if literal is not None and literal != constructor.atom_value:
                raise ProposalError(
                    f"{proposal.constructor!r}{where} is spelled "
                    f"{constructor.atom_value!r} and cannot be given as {literal!r}."
                )
            literal = constructor.atom_value
        elif literal is None:
            raise ProposalError(
                f"{proposal.constructor!r}{where} is a leaf and needs the literal "
                "token it stands for."
            )
    elif literal is not None:
        raise ProposalError(
            f"{proposal.constructor!r}{where} has slots, so it carries no literal."
        )

    return Node(
        constructor=constructor,
        children={
            slot: _resolve(
                child, context, constructor_for_name, term_for_ref, (*path, slot)
            )
            for slot, child in proposal.slots.items()
        },
        literal=literal,
        sort=(
            constructor_for_name(proposal.sort) if proposal.sort is not None else None
        ),
    )
