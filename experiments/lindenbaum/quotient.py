"""Computing in the Boolean algebra *modulo the equivalences already proved*.

`certify.py` abstracts a statement into a propositional formula whose atoms are
the maximal subterms it cannot see inside. Which subterms those are is decided by
one thing: whether their head is a connective. `A ≠ B` is an atom, `¬(A = B)` is
a negation of one, and the corpus proves the two equal — so the algebra is
strictly weaker than the theory it is meant to be an algebra *of*, for no reason
except that nobody told it.

This is the fix, and it is the fix the framing of the whole experiment predicts.
The free Boolean algebra quotients by nothing; the Lindenbaum–Tarski algebra of
ZFC quotients by everything and collapses; the useful object quotients by a
**partial theory**. The partial theory here is the set of biconditionals the
corpus has already established, and a premise-free `⊢ A ↔ B` is exactly a licence
to rewrite one side into the other inside any propositional context.

Two ways that helps, and the second is the larger:

* two atoms the corpus proves equivalent become **one** atom, so a truth table
  that had to keep them apart no longer does;
* an atom whose expansion has connectives in it stops being an atom, so the
  algebra sees propositional structure that was previously opaque. `df-ne`,
  `dfss2`, `df-ral` are all of this kind, and they are the shape of every
  statement in the set-theoretic part of the corpus.

**Soundness.** Replacing a subformula by a provably equivalent one preserves
provability, so a certificate built over the rewritten abstraction certifies the
original. What it *depends on* grows: the equivalences used join the cited lemmas
in the certificate's basis. Only theorems declared before the goal are ever
available, on the same discipline as the rest of the search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from experiments.lindenbaum import certify
from experiments.lindenbaum.unification import Terms

if TYPE_CHECKING:
    from collections.abc import Sequence

    from experiments.lindenbaum.corpus import Theorem

#: The production a biconditional heads in set.mm.
BICONDITIONAL = "wb"

#: How many rewrites one abstraction may perform. A bound rather than a fixed
#: point: `dfss2` expands `A ⊆ B` into a quantified implication whose body is
#: another atom that some other theorem expands again, and the useful depth is
#: one or two — past that the truth table grows without the entailment getting
#: any easier to see.
DEFAULT_BUDGET = 24


@dataclass(frozen=True, slots=True)
class Rewrite:
    """One direction of a proved biconditional: match ``pattern``, become ``into``."""

    label: str
    pattern: int
    into: int


class Equivalences:
    """The proved biconditionals, indexed for rewriting, grown as the walk goes.

    Append-only and time-ordered exactly like `Index`: a goal is never rewritten
    with an equivalence proved after it.
    """

    def __init__(self, terms: Terms) -> None:
        self.terms = terms
        self.by_root: dict[str | None, list[Rewrite]] = {}
        self.size = 0
        # A rewrite once valid stays valid, so hits are cached for good; a miss
        # is only a miss against the equivalences known at the time, so it is
        # cached with that count and rechecked when the set has grown.
        self._hits: dict[int, Rewrite | None] = {}
        self._misses: dict[tuple[int, frozenset[int]], int] = {}
        self._counter = 0

    def add(self, theorem: Theorem) -> None:
        """Record a premise-free `⊢ A ↔ B`, both ways round.

        A theorem with hypotheses states a *rule* about a biconditional, not the
        biconditional, so it licenses no rewriting on its own.
        """
        if theorem.premises or theorem.term < 0:
            return
        term = self.terms.canonical(theorem.term)
        if self.terms.constructor[term] != BICONDITIONAL:
            return
        children = self.terms.children[term]
        if len(children) != 2:
            return
        left, right = children
        for pattern, into in ((left, right), (right, left)):
            # A pattern that is a bare variable matches every atom there is, and
            # a biconditional of that shape — `φ ↔ ¬¬φ`, `φ ↔ (φ ∧ φ)` — is a
            # propositional tautology rather than a definition. Firing it turns
            # every atom into a wrapped copy of itself: more truth table, no more
            # information. The rewrites worth having are the ones keyed on a
            # symbol, because those say what that symbol *means*.
            if self.terms.is_variable(pattern):
                continue
            self.by_root.setdefault(self.terms.constructor[pattern], []).append(
                Rewrite(label=theorem.label, pattern=pattern, into=into)
            )
            self.size += 1

    def forget(self) -> None:
        """Drop the rewrite cache.

        Both the keys and the results are *term indices*, and the arena is
        truncated back to the corpus after every proof attempt — so a cache that
        survived a release would be reading indices that now name something else.
        Called by the runner at the same place it releases.
        """
        self._hits.clear()
        self._misses.clear()

    def rewrite(self, term: int, known: frozenset[int]) -> Rewrite | None:
        """An equivalence that turns ``term`` into something **less opaque**.

        Getting this test right is the whole difference between the quotient
        working and it being churn. "Introduces a connective" is not enough: with
        both directions of `df-ne` recorded, it rewrites the atom `A = B` into
        `¬(A ≠ B)`, which introduces a connective, replaces one opaque atom with
        a different opaque atom, and doubles the vocabulary the truth table has
        to range over. Measured, that fired on 94.6 % of held-out goals and
        bought nothing.

        The test that works: every atom the expansion leaves behind must either
        be **strictly smaller** than what was expanded — a definitional unfolding
        like `df-ifp`, which trades `if(φ, ψ, χ)` for its three components — or
        already be an atom **elsewhere in this problem**, which is what makes
        `A ≠ B → ¬(A = B)` worth doing exactly when `A = B` is also present and
        worthless when it is not. Both clauses are well-founded, so the walk
        terminates on its own and the budget is a safety net rather than the
        thing stopping a regress.
        """
        cached = self._hits.get(term)
        if cached is not None:
            return cached
        if self._misses.get((term, known)) == self.size:
            return None

        terms = self.terms
        if terms.is_variable(term):
            self._misses[term] = self.size
            return None
        for rewrite in self.by_root.get(terms.constructor[term], ()):
            mark = terms.mark()
            cache: dict[int, int] = {}
            self._counter += 1
            prefix = f"?eq{self._counter}_"
            pattern = terms.rename(rewrite.pattern, prefix, cache)
            subst: dict[int, int] = {}
            if terms.unify(pattern, term, subst) is None:
                terms.release(mark)
                continue
            produced = terms.apply(terms.rename(rewrite.into, prefix, cache), subst)
            if any(terms.is_flexible(v) for v in terms.variables(produced)):
                # The other side mentions a variable this side did not determine,
                # so the "equivalent" formula is not a formula yet.
                terms.release(mark)
                continue
            if certify.CONNECTIVES.get(terms.constructor[produced] or "") is None:
                terms.release(mark)
                continue
            size = terms.size(term)
            if any(
                terms.identity(atom) not in known and terms.size(atom) >= size
                for atom in atom_terms(terms, produced)
            ):
                terms.release(mark)
                continue
            found = Rewrite(label=rewrite.label, pattern=term, into=produced)
            self._hits[term] = found
            return found
        self._misses[(term, known)] = self.size
        return None


def atom_terms(terms: Terms, term: int) -> list[int]:
    """The subterms a plain abstraction would leave opaque."""
    found: list[int] = []
    stack = [term]
    while stack:
        current = stack.pop()
        arity = certify.CONNECTIVES.get(terms.constructor[current] or "")
        if arity is not None and len(terms.children[current]) == arity:
            stack.extend(terms.children[current])
        else:
            found.append(current)
    return found


def abstract_problem(
    terms: Terms,
    goal: int,
    facts: Sequence[int],
    equivalences: Equivalences | None,
    used: set[str] | None = None,
    budget: int = DEFAULT_BUDGET,
) -> tuple[certify.Formula, list[certify.Formula]]:
    """Abstract a goal and its assumptions together, over one atom table.

    Two passes when a quotient is supplied. The first is the plain abstraction,
    and exists only to learn **which atoms this problem already has** — the
    second clause of :meth:`Equivalences.rewrite`'s productivity test needs that,
    and it is a property of the problem rather than of any one term. The second
    pass is the one whose result is returned.
    """
    atoms: dict[int, int] = {}
    if equivalences is None:
        return (
            certify.abstract(terms, goal, atoms),
            [certify.abstract(terms, fact, atoms) for fact in facts],
        )
    known = frozenset(
        terms.identity(atom)
        for term in (goal, *facts)
        for atom in atom_terms(terms, term)
    )
    seen = used if used is not None else set()
    remaining = [budget]
    return (
        _walk(terms, goal, atoms, equivalences, seen, remaining, frozenset(), known),
        [
            _walk(terms, fact, atoms, equivalences, seen, remaining, frozenset(), known)
            for fact in facts
        ],
    )


def _walk(
    terms: Terms,
    term: int,
    atoms: dict[int, int],
    equivalences: Equivalences,
    used: set[str],
    budget: list[int],
    expanding: frozenset[int],
    known: frozenset[int],
) -> certify.Formula:
    constructor = terms.constructor[term]
    arity = certify.CONNECTIVES.get(constructor or "")
    if arity is not None and len(terms.children[term]) == arity:
        return certify.Formula(
            op=constructor or "",
            args=tuple(
                _walk(terms, child, atoms, equivalences, used, budget, expanding, known)
                for child in terms.children[term]
            ),
        )
    if budget[0] > 0 and term not in expanding:
        rewrite = equivalences.rewrite(term, known)
        if rewrite is not None:
            budget[0] -= 1
            used.add(rewrite.label)
            return _walk(
                terms,
                rewrite.into,
                atoms,
                equivalences,
                used,
                budget,
                expanding | {term},
                known,
            )
    return certify.Formula(
        op="atom", atom=atoms.setdefault(terms.identity(term), len(atoms))
    )
