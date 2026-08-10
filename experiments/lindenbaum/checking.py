"""An independent check that a found proof is a proof.

The prover is a search, and a search that reports success is exactly the kind of
program whose bugs look like results. Everything here is written against the
finished proof tree and shares nothing with the search that produced it: it
re-matches every step's cited theorem, re-derives every premise, and re-checks
every `$d`. A proof the search returns and this rejects is a bug in the search,
which is the point of having it.

The one thing it does share is `unify` — re-implementing that too would be
theatre, since a second copy of the same idea catches only typos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from experiments.lindenbaum import certify
from experiments.lindenbaum.prover import TAUTOLOGY
from experiments.lindenbaum.unification import RIGID, Terms, disjoint_holds

if TYPE_CHECKING:
    from experiments.lindenbaum.prover import Lemma, Step


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why a step is not a proof step."""

    label: str
    reason: str


class Checker:
    def __init__(
        self,
        terms: Terms,
        by_label: dict[str, Lemma],
        hypotheses: frozenset[int],
        goal_disjoint: frozenset[tuple[str, str]],
    ) -> None:
        self.terms = terms
        self.by_label = by_label
        self.hypotheses = hypotheses
        self.goal_disjoint = goal_disjoint
        self.counter = 0
        #: One substitution for the whole tree.
        #:
        #: A rule's premises may mention variables its conclusion does not —
        #: `3syl` concludes `φ → θ` and its premises name ψ and χ — so matching
        #: the conclusion leaves those open, and what determines them is the
        #: *children*. Verification therefore has to unify each premise with the
        #: child that proved it and carry the bindings on to its siblings, which
        #: is the same shape as the search. Demanding equality instead rejects
        #: every correct proof that uses such a rule, which is most of them.
        self.subst: dict[int, int] = {}

    def check(self, step: Step, expected: int) -> Rejection | None:
        terms = self.terms
        if terms.unify(expected, step.conclusion, self.subst) is None:
            return Rejection(step.label, "step concludes something other than its goal")
        conclusion = terms.apply(step.conclusion, self.subst)
        if any(terms.is_flexible(v) for v in terms.variables(conclusion)):
            return Rejection(step.label, "conclusion still contains an open variable")
        if step.label == "$e":
            if conclusion not in self.hypotheses:
                return Rejection(step.label, "cites a hypothesis the theorem lacks")
            return None
        if step.label == TAUTOLOGY:
            # Re-decided here, not trusted: the search's claim is that the
            # hypotheses propositionally entail this, and a truth table settles
            # it in the checker as readily as in the prover.
            atoms: dict[int, int] = {}
            abstracted = certify.abstract(terms, conclusion, atoms)
            assumptions = [
                certify.abstract(terms, fact, atoms) for fact in sorted(self.hypotheses)
            ]
            if not certify.entailed(abstracted, assumptions):
                return Rejection(step.label, "not propositionally entailed")
            return None

        lemma = self.by_label.get(step.label)
        if lemma is None:
            return Rejection(step.label, "cites a theorem not in the library")
        if len(step.children) != len(lemma.premises):
            return Rejection(step.label, "wrong number of premises")

        self.counter += 1
        prefix = f"?check{self.counter}_"
        cache: dict[int, int] = {}
        renamed = terms.rename(lemma.conclusion, prefix, cache)
        if terms.unify(renamed, conclusion, self.subst) is None:
            return Rejection(step.label, "conclusion does not match the cited theorem")

        for child, premise in zip(step.children, lemma.premises, strict=True):
            wanted = terms.apply(terms.rename(premise, prefix, cache), self.subst)
            found = self.check(child, wanted)
            if found is not None:
                return found

        # `$d` last: the constraint is about what the variables ended up being,
        # and the children are what settled them.
        bindings = {
            name: terms.variable(prefix + name, sort)
            for name, sort in _named(terms, lemma)
        }
        if lemma.disjoint and not disjoint_holds(
            terms, lemma.disjoint, bindings, self.subst, self.goal_disjoint
        ):
            return Rejection(step.label, "a $d constraint is violated")
        return None


def _named(terms: Terms, lemma: Lemma) -> list[tuple[str, str | None]]:
    found: dict[str, str | None] = {}
    for term in (lemma.conclusion, *lemma.premises):
        for variable in terms.variables(term):
            name = terms.var_name[variable] or ""
            if name[:1] not in ("?", RIGID):
                found[name] = terms.sort[variable]
    return list(found.items())
