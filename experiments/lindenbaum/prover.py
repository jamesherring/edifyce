"""A backward prover over the corpus, and the geometry that decides what to try.

The search is ordinary: to prove a goal, find a library theorem whose conclusion
unifies with it, and recurse on that theorem's premises. What makes it a
non-trivial search on set.mm is that a rule's premises routinely mention
variables its conclusion does not — `syl` concludes `φ → χ` from `φ → ψ` and
`ψ → χ`, and *nothing in the goal says what ψ is*. Every use of it invents an
intermediate statement. That is the step this cannot be told and has to find, and
it is why the ranking is the experiment rather than the plumbing.

Two things keep the search honest, both of them ways a prover can otherwise
appear to succeed:

* the goal is **frozen** before the search starts, so its metavariables are
  constants and the prover proves the schema rather than some instance of it;
* every step's `$d` obligations are checked and propagated
  (:func:`~experiments.lindenbaum.unification.disjoint_holds`).

The library is whatever was declared before the goal, and nothing about the
goal's own proof is available — not its citations, not its length, not its
depth.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from experiments.lindenbaum import certify, quotient
from experiments.lindenbaum.unification import (
    RIGID,
    Subst,
    Terms,
    disjoint_holds,
    freeze,
)

if TYPE_CHECKING:
    from experiments.lindenbaum.corpus import Theorem

#: Fingerprint marks, as small integers so a whole library is filtered with
#: array comparisons rather than a Python loop. The three special values are
#: fixed codes; a constructor gets the next free one.
BELOW_VAR = 0
ABSENT = 1
VARIABLE = 2
FIRST_SYMBOL = 3

#: The label a propositionally-closed step carries. Not a Metamath theorem: it
#: stands for "a derivation in the propositional calculus exists", which the
#: checker re-decides rather than takes on trust.
TAUTOLOGY = "$taut"

#: Where the fingerprint samples. The root is the head-symbol filter
#: `app/db/retrieval.py` already ships; the rest are what make it prune a corpus
#: where every other statement is an implication.
POSITIONS: tuple[tuple[int, ...], ...] = (
    (),
    (0,),
    (1,),
    (0, 0),
    (0, 1),
    (1, 0),
    (1, 1),
)


@dataclass(frozen=True, slots=True)
class Lemma:
    """A library entry as the prover uses it: a conclusion and what it needs."""

    label: str
    conclusion: int
    premises: tuple[int, ...]
    disjoint: tuple[tuple[str, str], ...]
    #: Bare variable names, so a `$d` obligation can be looked up by name after
    #: the lemma has been refreshed into its own namespace.
    prefix: str = ""

    @property
    def is_fact(self) -> bool:
        return not self.premises


@dataclass(frozen=True, slots=True)
class Step:
    """One node of a found proof."""

    label: str
    conclusion: int
    children: tuple[Step, ...] = ()

    def depth(self) -> int:
        return 1 + max((child.depth() for child in self.children), default=0)

    def size(self) -> int:
        return 1 + sum(child.size() for child in self.children)

    def labels(self) -> set[str]:
        return {self.label}.union(*(child.labels() for child in self.children)) if (
            self.children
        ) else {self.label}


def feature(
    terms: Terms, term: int, path: Sequence[int], symbols: dict[tuple, int]
) -> int:
    """What the fingerprint sees at ``path``: a symbol, or why there is none."""
    current = term
    for step in path:
        if terms.is_variable(current):
            return BELOW_VAR
        children = terms.children[current]
        if step >= len(children):
            return ABSENT
        current = children[step]
    if terms.is_variable(current):
        return VARIABLE
    key = (terms.constructor[current], terms.literal[current])
    return symbols.setdefault(key, len(symbols) + FIRST_SYMBOL)


def _admits(query: int, stored: np.ndarray) -> np.ndarray:
    """Which stored marks a query mark could still unify with.

    Schulz's table, as array algebra. `BELOW_VAR` sits under a variable and so
    subsumes anything; `ABSENT` means the path ran off the end of the term and
    matches only itself; a `VARIABLE` binds to any subterm that exists. Only the
    last line can reject, which is why the filter never loses a candidate the
    unifier would have accepted.
    """
    if query == BELOW_VAR:
        return np.ones(len(stored), dtype=bool)
    if query == ABSENT:
        return (stored == ABSENT) | (stored == BELOW_VAR)
    if query == VARIABLE:
        return stored != ABSENT
    return (stored == query) | (stored == VARIABLE) | (stored == BELOW_VAR)


class Index:
    """Lemmas, prefiltered by fingerprint and ranked by a scorer.

    Append-only: the evaluation walks the corpus in declaration order and each
    theorem joins the library after it has been attempted, so a goal is never
    offered a lemma that did not exist when it was written.
    """

    def __init__(self, terms: Terms) -> None:
        self.terms = terms
        self.lemmas: list[Lemma] = []
        self.symbols: dict[tuple, int] = {}
        self.marks = np.zeros((1024, len(POSITIONS)), dtype=np.int32)
        #: Subterm bags for the structural scorer, as sparse counts.
        self.bags: list[dict[int, float]] = []
        self.norms: list[float] = []
        self.uses: list[float] = []
        self.by_label: dict[str, int] = {}
        #: A dense hashed projection of each bag, so a scorer ranks thousands of
        #: candidates with one matrix product rather than a Python loop over
        #: sparse dictionaries. That loop was most of the prover's runtime, and
        #: nothing is *decided* on the projection — every candidate it orders is
        #: still unified.
        self.width = 64
        self.vectors = np.zeros((1024, self.width), dtype=np.float32)
        self.use_counts = np.zeros(1024, dtype=np.float32)
        #: Inverted index over subterm shapes, for nearest-neighbour lookup.
        self.postings: dict[int, list[int]] = {}
        #: What each library theorem's own proof cited, added when it joins.
        self.cited: list[tuple[str, ...]] = []

    def add(self, lemma: Lemma) -> int:
        at = len(self.lemmas)
        self.lemmas.append(lemma)
        bag = self.bag(lemma.conclusion)
        self.bags.append(bag)
        self.norms.append(sum(v * v for v in bag.values()) ** 0.5 or 1.0)
        self.uses.append(0.0)
        if at >= len(self.vectors):
            self.vectors = np.concatenate(
                [self.vectors, np.zeros_like(self.vectors)], axis=0
            )
            self.use_counts = np.concatenate(
                [self.use_counts, np.zeros_like(self.use_counts)], axis=0
            )
            self.marks = np.concatenate(
                [self.marks, np.zeros_like(self.marks)], axis=0
            )
        self.vectors[at] = self.dense(bag)
        for position, path in enumerate(POSITIONS):
            self.marks[at, position] = feature(
                self.terms, lemma.conclusion, path, self.symbols
            )
        self.by_label.setdefault(lemma.label, at)
        self.cited.append(())
        for key in bag:
            self.postings.setdefault(key, []).append(at)
        return at

    def neighbours(self, goal: int, count: int, rarest: int = 6) -> list[tuple[int, float]]:
        """The library entries whose statements look most like ``goal``.

        Scored through the inverted index on the goal's *rarest* shapes only. A
        shape like "an implication" is in half the corpus and separates nothing;
        the discriminating ones are rare by construction, and restricting to them
        turns a scan of the library into a walk of a few short postings lists.
        """
        bag = self.bag(goal)
        keys = sorted(bag, key=lambda key: len(self.postings.get(key, ())))[:rarest]
        scores: dict[int, float] = {}
        total = len(self.lemmas) or 1
        for key in keys:
            postings = self.postings.get(key, ())
            if not postings or len(postings) > total // 2:
                continue
            weight = bag[key] * (total / len(postings)) ** 0.5
            for at in postings:
                scores[at] = scores.get(at, 0.0) + weight * self.bags[at].get(key, 0.0)
        ranked = sorted(scores.items(), key=lambda pair: -pair[1] / self.norms[pair[0]])
        return ranked[:count]

    def cite(self, label: str) -> None:
        """Record that a proof cited ``label``, if the library holds it."""
        at = self.by_label.get(label)
        if at is not None:
            self.uses[at] += 1.0
            self.use_counts[at] += 1.0

    def dense(self, bag: dict[int, float]) -> np.ndarray:
        vector = np.zeros(self.width, dtype=np.float32)
        for key, value in bag.items():
            vector[key % self.width] += value
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def bag(self, term: int) -> dict[int, float]:
        """Multiset of subterm shapes, with variables collapsed by sort.

        Collapsing is right here and wrong in `certify.py`: a scorer wants
        `φ → ψ` to look like `(A ∈ B) → ψ`, since a lemma about implications is a
        candidate for both. Nothing is decided on this — every candidate it ranks
        is still unified.
        """
        counts: dict[int, float] = {}
        stack = [term]
        while stack:
            current = stack.pop()
            if self.terms.is_variable(current):
                key = hash(("var", self.terms.sort[current]))
            else:
                key = hash(
                    (
                        self.terms.constructor[current],
                        self.terms.literal[current],
                        len(self.terms.children[current]),
                    )
                )
                stack.extend(self.terms.children[current])
            counts[key] = counts.get(key, 0.0) + 1.0
        return counts

    def candidates(self, goal: int) -> np.ndarray:
        size = len(self.lemmas)
        stored = self.marks[:size]
        keep = np.ones(size, dtype=bool)
        for position, path in enumerate(POSITIONS):
            query = feature(self.terms, goal, path, self.symbols)
            keep &= _admits(query, stored[:, position])
            if not keep.any():
                return np.empty(0, dtype=np.int64)
        return np.flatnonzero(keep)


Scorer = Callable[[int, Sequence[int]], "np.ndarray"]


def structural_scorer(index: Index) -> Scorer:
    """Cosine between the goal's hashed subterm profile and each candidate's."""

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        vector = index.dense(index.bag(goal))
        return index.vectors[candidates] @ vector

    return score


def frequency_scorer(index: Index) -> Scorer:
    """How often the library has cited this lemma *so far*.

    The strong classical baseline, and the one a new geometry has to beat. Counts
    come only from proofs already declared, so a goal never benefits from being
    told which lemmas its own era found useful.
    """

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        return index.use_counts[candidates]

    return score


def analogy_scorer(index: Index, neighbours: int = 24) -> Scorer:
    """Premise selection by analogy: what did *similar* theorems cite?

    The geometry used for what it can actually do. Experiment 1 established that
    structural similarity does not predict a formula's truth — but nothing there
    said it fails to predict which *lemmas* a proof of it will need, and those
    are different questions. This asks the second one: find the library entries
    whose statements look most like the goal, and prefer whatever their proofs
    cited.

    Only earlier theorems are neighbours and only their own proofs are read, so
    the goal's proof is never consulted — the analogy is to the corpus as it
    stood, which is the information a person would have had.
    """

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        votes = np.zeros(len(index.lemmas), dtype=np.float32)
        for at, weight in index.neighbours(goal, neighbours):
            for label in index.cited[at]:
                found = index.by_label.get(label)
                if found is not None:
                    votes[found] += weight
        return votes[candidates]

    return score


class OracleScorer:
    """Ranks the lemmas the real proof cited first. Deliberately cheating.

    Not a method — a *measuring instrument*. Comparing a computable ranker
    against this separates the two ways a proof search fails: the ranking never
    offered the right lemma, or the search could not use it when handed it. The
    gap between a real ranker and the oracle is what better retrieval could still
    buy; what the oracle *itself* fails to solve is what no amount of retrieval
    will fix.
    """

    def __init__(self, index: Index) -> None:
        self.index = index
        self.wanted: frozenset[str] = frozenset()
        self._mask = np.zeros(0, dtype=np.float32)

    def aim(self, labels: frozenset[str]) -> None:
        self.wanted = labels
        self._mask = np.zeros(len(self.index.lemmas), dtype=np.float32)
        for label in labels:
            at = self.index.by_label.get(label)
            if at is not None:
                self._mask[at] = 1.0

    def __call__(self, goal: int, candidates: Sequence[int]) -> np.ndarray:
        if len(self._mask) < len(self.index.lemmas):
            self.aim(self.wanted)
        return self._mask[candidates]


def size_scorer(index: Index) -> Scorer:
    """Prefer a lemma whose conclusion is close to the goal in size."""

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        target = index.terms.size(goal)
        return np.array(
            [
                -abs(index.terms.size(index.lemmas[at].conclusion) - target)
                for at in candidates
            ],
            dtype=np.float32,
        )

    return score


def random_scorer(index: Index, seed: int = 0) -> Scorer:
    rng = random.Random(seed)

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        return np.array([rng.random() for _ in candidates], dtype=np.float32)

    return score


def combine(parts: Sequence[tuple[Scorer, float]]) -> Scorer:
    """A weighted sum of scorers, each rank-normalised so the units cancel."""

    def score(goal: int, candidates: Sequence[int]) -> np.ndarray:
        total = np.zeros(len(candidates), dtype=np.float32)
        span = max(len(candidates) - 1, 1)
        for scorer, weight in parts:
            order = np.argsort(np.asarray(scorer(goal, candidates)), kind="stable")
            rank = np.empty(len(candidates), dtype=np.float32)
            rank[order] = np.arange(len(candidates), dtype=np.float32)
            total += weight * (rank / span)
        return total

    return score


@dataclass
class Budget:
    """What one attempt may spend, and what it did spend."""

    steps: int
    used: int = 0
    depth: int = 6
    width: int = 12
    #: How many ranked candidates a single goal may look at. The fingerprint
    #: filter leaves thousands for a set-theory goal and most do not unify, so
    #: without a cap one hopeless goal spends the whole budget renaming terms.
    #: This is where the ranking earns its keep: the cap is only survivable if
    #: what is worth trying is near the front.
    scan: int = 120

    def spend(self) -> bool:
        self.used += 1
        return self.used <= self.steps


@dataclass
class Attempt:
    """One goal handed to the prover, with what it is allowed to assume."""

    label: str
    goal: int
    #: The goal theorem's own `$e` hypotheses, usable as facts.
    hypotheses: tuple[int, ...]
    disjoint: frozenset[tuple[str, str]]
    proof: Step | None = None
    nodes: int = 0
    counter: list[int] = field(default_factory=lambda: [0])


class Prover:
    def __init__(
        self,
        terms: Terms,
        index: Index,
        scorer: Scorer,
        *,
        propositional: bool = False,
        equivalences: quotient.Equivalences | None = None,
    ) -> None:
        self.terms = terms
        self.index = index
        self.scorer = scorer
        #: Close a subgoal outright when the theorem's hypotheses propositionally
        #: entail it. This is the Boolean algebra of `certify.py` used as a
        #: closer: a whole subtree of `syl`/`imp`/`ex`/`adantr` glue becomes one
        #: step, which is aimed squarely at what `run_failures.py` measured — the
        #: wall is the *number of lemmas* a proof needs, not its depth.
        self.propositional = propositional
        #: The proved biconditionals the closer may rewrite an atom through, or
        #: None to compute in the free algebra as before.
        self.equivalences = equivalences
        self._orders: dict[int, list[int]] = {}

    def attempt(
        self, attempt: Attempt, budget: Budget, *, allow_open: bool = False
    ) -> Step | None:
        self._orders = {}
        goal = freeze(self.terms, attempt.goal)
        facts = tuple(freeze(self.terms, h) for h in attempt.hypotheses)
        for depth in range(1, budget.depth + 1):
            found = self._prove([goal], {}, depth, budget, facts, attempt, set())
            if found is not None:
                steps, subst = found
                # A step records the goal it closed *as it stood then*; bindings
                # made later while proving its siblings can still refine it. So
                # the tree is resolved once against the substitution the whole
                # search finished with, and only then is it a proof of anything.
                tree = resolve(self.terms, steps[0], subst)
                # …and only if every variable came out determined. A search can
                # close every subgoal while leaving one variable free — the step
                # then asserts a schema rather than a statement, which is
                # Metamath's *dummy variable*, legal only against `$d`
                # obligations this does not track. Rather than hand the checker
                # something it must refuse, refuse it here: the contract is that
                # a returned proof verifies.
                if allow_open or not _open(self.terms, tree):
                    return tree
            if budget.used > budget.steps:
                break
        return None

    def _prove(
        self,
        goals: list[int],
        subst: Subst,
        depth: int,
        budget: Budget,
        facts: tuple[int, ...],
        attempt: Attempt,
        active: set[int],
    ) -> tuple[tuple[Step, ...], Subst] | None:
        if not goals:
            return ((), subst)
        if depth <= 0 or not budget.spend():
            return None
        terms = self.terms
        # Solve the *most constrained* goal first. Using `ax-mp` leaves one
        # premise a bare flexible variable — it is the middle term, and nothing
        # says what it is. Attacking that first means unifying an unconstrained
        # variable against the whole library; attacking its sibling first
        # determines it. This single ordering is the difference between the
        # search finding modus ponens and never finding it.
        pick = min(
            range(len(goals)),
            key=lambda at: self._difficulty(terms.apply(goals[at], subst)),
        )
        goal = terms.apply(goals[pick], subst)
        rest = goals[:pick] + goals[pick + 1 :]

        if self.propositional and self._entails(goal, facts):
            tail = self._prove(rest, subst, depth, budget, facts, attempt, active)
            if tail is not None:
                return (
                    _splice(tail[0], Step(label=TAUTOLOGY, conclusion=goal), pick),
                    tail[1],
                )

        # A hypothesis of the theorem being proved closes a goal outright — by
        # *unification*, not equality. A goal reached through a rule that left a
        # variable open is a pattern, and `syl` is exactly that: proving it needs
        # `(?ps → χ)` to be closed by the hypothesis `(ψ → χ)`, binding ?ps on the
        # way. Comparing the two for equality finds nothing and makes modus
        # ponens with an undetermined middle term unreachable.
        for fact in facts:
            trial = dict(subst)
            if terms.unify(fact, goal, trial) is None:
                continue
            tail = self._prove(rest, trial, depth, budget, facts, attempt, active)
            if tail is not None:
                return (_splice(tail[0], Step(label="$e", conclusion=goal), pick), tail[1])

        if goal in active:
            return None

        order = self._order(goal)
        if not order:
            return None
        candidates = self.index.candidates(goal)

        tried_facts = 0
        tried_rules = 0
        examined = 0
        for position in order:
            at = candidates[position]
            lemma = self.index.lemmas[at]
            if lemma.premises:
                if depth <= 1 or tried_rules >= budget.width:
                    continue
            elif tried_facts >= budget.width:
                continue
            examined += 1
            if examined > budget.scan:
                break
            attempt.counter[0] += 1
            prefix = f"?{attempt.counter[0]}_"
            cache: dict[int, int] = {}
            conclusion = terms.rename(lemma.conclusion, prefix, cache)
            trial = dict(subst)
            if terms.unify(conclusion, goal, trial) is None:
                continue
            if lemma.premises:
                tried_rules += 1
            else:
                tried_facts += 1
            bindings = {
                name: terms.variable(prefix + name, sort)
                for name, sort in self._named(lemma)
            }
            if lemma.disjoint and not disjoint_holds(
                terms, lemma.disjoint, bindings, trial, attempt.disjoint
            ):
                continue
            premises = tuple(
                terms.rename(premise, prefix, cache) for premise in lemma.premises
            )
            branch = self._prove(
                list(premises),
                trial,
                depth - 1,
                budget,
                facts,
                attempt,
                active | {goal},
            )
            if branch is None:
                continue
            after = self._prove(
                rest, branch[1], depth, budget, facts, attempt, active
            )
            if after is None:
                continue
            # `$d` again, now that the premises have determined the variables.
            # Checked before the branch it is only checked against bindings that
            # do not exist yet, and passes vacuously.
            if lemma.disjoint and not disjoint_holds(
                terms, lemma.disjoint, bindings, after[1], attempt.disjoint
            ):
                continue
            step = Step(label=lemma.label, conclusion=goal, children=branch[0])
            return (_splice(after[0], step, pick), after[1])
        return None

    def _order(self, goal: int) -> list[int]:
        """Candidates for ``goal``, ranked — cached for the whole attempt.

        Iterative deepening visits the same goal once per depth, and ranking
        thousands of candidates was most of the runtime. The index does not
        change during an attempt, so the order cannot either.
        """
        cached = self._orders.get(goal)
        if cached is not None:
            return cached
        candidates = self.index.candidates(goal)
        if candidates.size == 0:
            self._orders[goal] = []
            return []
        scores = np.asarray(self.scorer(goal, candidates))
        order = [int(at) for at in np.argsort(-scores, kind="stable")]
        # Facts and rules get *separate* allowances. Sharing one meant a goal
        # that many facts happened to unify with never reached a rule at all,
        # and every proof longer than one step needs a rule.
        order.sort(key=lambda at: not self.index.lemmas[candidates[at]].is_fact)
        self._orders[goal] = order
        return order

    def _entails(self, goal: int, facts: tuple[int, ...]) -> bool:
        """Whether the hypotheses propositionally entail this (ground) goal.

        Refused for a goal that still carries a flexible variable: the
        abstraction would key that variable as an atom and decide a question
        about a *pattern*, when what closing it means is that some instance is
        provable — which is not the same claim.
        """
        if any(self.terms.is_flexible(v) for v in self.terms.variables(goal)):
            return False
        abstracted, assumptions = quotient.abstract_problem(
            self.terms, goal, facts, self.equivalences
        )
        if abstracted.is_atom:
            return False
        return certify.entailed(abstracted, assumptions)

    def _difficulty(self, goal: int) -> tuple[int, int]:
        flexible = sum(
            1 for v in self.terms.variables(goal) if self.terms.is_flexible(v)
        )
        return (flexible, -self.terms.size(goal))

    def _named(self, lemma: Lemma) -> list[tuple[str, str | None]]:
        terms = self.terms
        found: dict[str, str | None] = {}
        for term in (lemma.conclusion, *lemma.premises):
            for variable in terms.variables(term):
                name = terms.var_name[variable] or ""
                if name[:1] not in ("?", RIGID):
                    found[name] = terms.sort[variable]
        return list(found.items())


def _open(terms: Terms, step: Step) -> bool:
    """Whether any step of the tree still carries an undetermined variable."""
    if any(terms.is_flexible(v) for v in terms.variables(step.conclusion)):
        return True
    return any(_open(terms, child) for child in step.children)


def _splice(steps: tuple[Step, ...], step: Step, at: int) -> tuple[Step, ...]:
    """Put ``step`` back where its goal was.

    The search solves the *most constrained* goal first, so the order it returns
    steps in is not the order the rule listed its premises. A proof whose
    children are permuted is not a proof — it verifies against the wrong premise
    — so the pick is undone here rather than left for a reader to notice.
    """
    return steps[:at] + (step,) + steps[at:]


def resolve(terms: Terms, step: Step, subst: Subst) -> Step:
    return Step(
        label=step.label,
        conclusion=terms.apply(step.conclusion, subst),
        children=tuple(resolve(terms, child, subst) for child in step.children),
    )


def as_lemma(terms: Terms, theorem: Theorem) -> Lemma | None:
    if theorem.term < 0 or any(p < 0 for p in theorem.premise_terms):
        return None
    return Lemma(
        label=theorem.label,
        conclusion=terms.canonical(theorem.term),
        premises=tuple(terms.canonical(p) for p in theorem.premise_terms),
        disjoint=theorem.disjoint,
    )
