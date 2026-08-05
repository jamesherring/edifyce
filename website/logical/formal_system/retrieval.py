"""Which rules could justify a line, and with which premises.

The read half of the loop `diagnostics` and the citation endpoint left open
(docs/authoring-and-ingestion-roadmap.md §9d). A failure says *which premise is
missing*; a hole says *what is left to prove*. Neither says **what to cite**, and
on a library of 47,589 theorems a caller with no answer to that has no move.

This module is the search half of the answer, and it is deliberately not the
retrieval half. Narrowing 47,589 entries to a handful of candidates is a query
over rows — a conclusion's root constructor is a column, so the filter is an
index scan (`app/db/retrieval.py`) — and confirming a candidate is unification,
which is here. Nothing in this module knows how its candidates were found, which
is what lets the cheap filter be replaced by a sharper one (a discrimination tree,
`docs/search-and-embeddings-roadmap.md` Phase 1) without touching the confirm.

Depth one, and honestly so
--------------------------
An application found here justifies a line **from lines that already stand**. It
does not prove a gap: "here is my next step, find the four lemmas between it and
what I have" is a search over sequences of steps, which is elaboration (§3's
option D) and a different piece of work. What this supports is the step a caller
has already stated — which, in an imported corpus, is the overwhelming majority
of what a proof is made of.

Nothing here records a verdict. Every probe goes through `InferenceRule.applies`
and `InferenceRule.discharges`, which return their answer instead of writing it
onto the line — a search tries many rules against one goal, and all but the
winner are rejections that must leave no trace (see those methods).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .proof import line_is_accessible

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..matching.context import Context
    from .proof import ProofLine
    from .rules import InferenceRule


@dataclass(frozen=True)
class Application:
    """One way a rule justifies a line: the rule, and the lines a citation names.

    ``cited`` is exactly what the citation would carry, in the order it would
    carry it — the slot fillers for an ordinary rule, and the single subproof
    *opener* for a discharge rule. One field for both because the citation syntax
    makes no distinction either (`[CP, 3]` and `[MP, 1, 2]` are the same shape),
    so a caller composing a proposal need not branch. ``discharge`` says which it
    is, for a caller that wants to explain itself.
    """

    rule: InferenceRule
    cited: tuple[ProofLine, ...]
    discharge: bool = False

    @property
    def numbers(self) -> list[int]:
        """The citation numbers, which is how a proposal names lines."""
        return [line.number for line in self.cited]


def accessible_lines(deduction: ProofLine) -> list[ProofLine]:
    """The lines ``deduction`` could cite: numbered, above it, and in scope.

    The candidate pool for an antecedent slot. Scope is the reiteration
    restriction (`line_is_accessible`) — a line inside a closed sibling subproof
    is unusable, and offering it would propose citations the checker then refuses.
    Ordering is the same "after its premises" rule `InferenceRule.applies`
    enforces, applied here so the search never explores what it would reject.

    Non-logical lines are kept: a rule slot may be satisfied by an instance of a
    line *type* rather than by a formula, which `slot_admits` handles and this
    must not pre-empt.
    """
    if deduction.number is None:
        raise ValueError(
            "A line with no citation number cannot cite: it is not in the proof's "
            "numbering, so nothing above it is addressable from it."
        )

    # `numbered_lines` is in source order, so the line's own number bounds what
    # precedes it — cheaper than an `index()` per candidate, which is a scan.
    return [
        line
        for line in deduction.proof.numbered_lines[: deduction.number - 1]
        if line_is_accessible(deduction, line)
    ]


def dischargeable_openers(deduction: ProofLine) -> list[ProofLine]:
    """The subproof openers ``deduction`` could discharge — a different pool.

    Not a subset of :func:`accessible_lines`, and that is the point: an opener
    lives *inside* the subproof it opens, so a line below the subproof cannot
    cite it as an antecedent — and discharging it is exactly what it can do
    instead. The two pools answer two questions and neither contains the other.

    The condition is the one `Proof.check_discharge_line` enforces: the subproof
    must be enclosed by an ancestor of this line's scope, and must not still be
    open around it. Cross-scope discharge is the unsoundness that rule exists to
    close, so a proposer must not offer it.
    """
    if deduction.number is None:
        raise ValueError(
            "A line with no citation number cannot cite: it is not in the proof's "
            "numbering, so nothing above it is addressable from it."
        )

    openers = []
    for line in deduction.proof.numbered_lines[: deduction.number - 1]:
        subproof = line.opened_scope
        if subproof is None or subproof.parent is None:
            continue
        if not subproof.parent.is_ancestor_of(deduction.scope):
            continue
        if subproof.is_ancestor_of(deduction.scope):
            # Still open around this line: discharging it here would give up a
            # hypothesis that is still in force.
            continue
        openers.append(line)
    return openers


def applications(
    rule: InferenceRule,
    deduction: ProofLine,
    pool: Sequence[ProofLine],
    context: Context,
    *,
    limit: int = 1,
) -> list[Application]:
    """Ways ``rule`` justifies ``deduction`` from lines in ``pool``, up to ``limit``.

    An empty list means the rule cannot justify the line from what stands above
    it — which is a fact about *this* proof at *this* point, not about the rule.

    Three filters in increasing cost, the same ladder the checker climbs. The
    conclusion must be able to be this line at all (`concludes`); every slot must
    have at least one individually-admissible line (`admissibility`); and a
    partial assignment that cannot bind is abandoned before it is completed
    (`prefix_binding_exists`).
    Only a complete assignment reaches `applies`, which is authoritative and
    includes the provisos.

    A discharge rule is not searched here — it consumes a subproof rather than
    cited lines, so it has no slots to fill; see :func:`discharges`.
    """
    if rule.is_discharge or limit <= 0:
        return []

    # Cheapest first, and by far the most selective: a rule whose conclusion
    # cannot be this line cannot justify it however its premises are chosen.
    if not rule.concludes(deduction, context):
        return []

    required = len(rule.antecedents)
    if required == 0:
        # Nothing to assign — but still confirmed rather than assumed, because
        # `concludes` skips the side conditions and an axiom can carry one.
        if rule.applies((), (), deduction, context) is None:
            return []
        return [Application(rule, ())]

    adjacency = rule.admissibility(pool, context)
    if any(not adjacency[slot] for slot in range(required)):
        # A slot no standing line could fill on its own: no assignment can.
        return []

    found: list[Application] = []

    def search(slot: int, chosen: list[int]) -> None:
        if len(found) >= limit:
            return
        if slot == required:
            cited = tuple(pool[j] for j in chosen)
            # Extras are empty by construction: this search *selects* the slot
            # fillers out of the pool rather than being handed a citation to
            # distribute, so a rule's `allow_extra_antecedents` never arises.
            if rule.applies(cited, (), deduction, context) is not None:
                found.append(Application(rule, cited))
            return

        # One line may fill **several slots**, which is why this does not skip
        # what it has already chosen and why the feasibility test above is not a
        # saturating matching. `[TWO, 1, 1]` is a citation the checker accepts —
        # a rule whose two premises are both `p` is satisfied by one line twice —
        # and demanding distinct representatives would have made exactly those
        # rules unfindable. The checker's own search asks for distinct
        # representatives because it is handed a citation and distributes it,
        # where naming a line twice is the caller's way of saying "use it twice";
        # this one is choosing, so the choice is its to repeat.
        for j in adjacency[slot]:
            candidate = [*chosen, j]
            # Prune as the checker does: slots are filled in order, so this is a
            # prefix, and unification is monotone — a prefix that cannot bind has
            # no completion that can.
            if not rule.prefix_binding_exists(
                [pool[k] for k in candidate], deduction, context
            ):
                continue
            search(slot + 1, candidate)
            if len(found) >= limit:
                return

    search(0, [])
    return found


def discharges(
    rule: InferenceRule,
    deduction: ProofLine,
    openers: Sequence[ProofLine],
    context: Context,
    *,
    limit: int = 1,
) -> list[Application]:
    """Subproofs in ``openers`` whose discharge under ``rule`` justifies ``deduction``.

    The other half of what can justify a line, and the half a search would
    otherwise silently omit: in a natural-deduction system the steps that
    introduce an implication or a quantifier are all discharges, so a proposer
    blind to them is blind to every rule that closes a subproof.

    ``openers`` is :func:`dischargeable_openers`, which is where the scope
    condition lives — *not* :func:`accessible_lines`, whose pool answers a
    different question and excludes exactly these lines.
    """
    if not rule.is_discharge or limit <= 0:
        return []

    found: list[Application] = []
    for opener in openers:
        if len(found) >= limit:
            break
        subproof = opener.opened_scope
        if subproof is not None and rule.discharges(subproof, deduction, context):
            found.append(Application(rule, (opener,), discharge=True))
    return found
