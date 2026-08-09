"""Building the fragment the experiment classifies: Boolean combinations of theorems.

The corpus supplies generators A₁…Aₙ, each of which the corpus *proved*. A
compound is a Boolean expression over them, and its label is settled — not
guessed — by the argument the prototype gives: if every Aᵢ is a theorem and
f(A₁…Aₙ) evaluates true when every Aᵢ is true, then (A₁ ∧ … ∧ Aₙ) → f is a
propositional tautology whose antecedent the corpus proves, so f is a theorem;
if it evaluates false the same argument proves ¬f. Every compound here is
therefore certified provable or certified refutable, with no model theory and no
appeal to the classifier.

Two constraints on what may serve as a generator, both of them soundness rather
than convenience:

* **No hypotheses.** A Metamath theorem with `$e` hypotheses asserts a *rule* —
  from ⊢H₁…⊢Hₖ infer ⊢C — and not the implication ⊢(H₁ ∧ … ∧ Hₖ) → C, which is
  exactly what fails for generalisation. Half of set.mm is of this shape, and
  taking it as ⊢C would make the labels wrong rather than merely noisy.
* **A stored conclusion term.** A generator with no term is one the experiment
  cannot walk, so it cannot appear in a structural feature.

Free metavariables are *not* a constraint. A `$p` with free `ph` asserts a
schema, provable under every admissible substitution and in particular under the
identity one, which is the instance used here — so ⊢Aᵢ holds as stated and the
argument above goes through unchanged. Two generators sharing the spelling `ph`
is likewise harmless: each is provable on its own, so their conjunction is.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from experiments.lindenbaum.corpus import Theorem
    from experiments.lindenbaum.dag import Arena

#: Connective → (Metamath production, arity). The compound is built in the
#: corpus's own grammar, so what the structural embedding sees is a well-formed
#: wff of the imported system rather than a synthetic tree standing in for one.
CONNECTIVES: dict[str, tuple[str, int]] = {
    "not": ("wn", 1),
    "and": ("wa", 2),
    "or": ("wo", 2),
    "imp": ("wi", 2),
    "iff": ("wb", 2),
}

_BINARY = ("and", "or", "imp", "iff")


@dataclass(frozen=True, slots=True)
class Skeleton:
    """A Boolean expression over generator *slots*, independent of which
    theorems fill them.

    Kept separate from the compound precisely so it can be handed to a
    classifier on its own: the labels are a function of the skeleton alone, so
    the skeleton-only control measures the ceiling any structural method is
    aiming at, and the gap to it measures how much of that signal survives being
    buried in the generators' own syntax.
    """

    op: str
    args: tuple[Skeleton, ...] = ()
    slot: int = -1

    @property
    def is_slot(self) -> bool:
        return self.op == "slot"

    def slots(self) -> set[int]:
        if self.is_slot:
            return {self.slot}
        return {s for arg in self.args for s in arg.slots()}

    def size(self) -> int:
        return 1 + sum(arg.size() for arg in self.args)

    def evaluate(self, values: Sequence[bool]) -> bool:
        if self.is_slot:
            return values[self.slot]
        if self.op == "not":
            return not self.args[0].evaluate(values)
        left = self.args[0].evaluate(values)
        right = self.args[1].evaluate(values)
        if self.op == "and":
            return left and right
        if self.op == "or":
            return left or right
        if self.op == "imp":
            return (not left) or right
        if self.op == "iff":
            return left == right
        raise ValueError(f"unknown connective {self.op!r}")

    def shape(self) -> str:
        """The operator tree with slot identities kept but generators dropped."""
        if self.is_slot:
            return str(self.slot)
        return f"{self.op}({','.join(arg.shape() for arg in self.args)})"


def random_skeleton(rng: random.Random, slots: int, depth: int) -> Skeleton:
    """A random expression over ``slots`` slots, at most ``depth`` deep.

    Every slot is used at least once — a skeleton that ignored a slot would
    silently change how many generators the compound really mentions, which the
    family split depends on.
    """
    used: list[int] = list(range(slots))
    rng.shuffle(used)

    def build(available: list[int], budget: int) -> Skeleton:
        if len(available) == 1 and (budget <= 0 or rng.random() < 0.35):
            return Skeleton(op="slot", slot=available[0])
        if len(available) == 1:
            if rng.random() < 0.5:
                return Skeleton(op="not", args=(build(available, budget - 1),))
            # A binary node over one slot repeats it, which is the only way the
            # fragment produces `A → A` and `A ∧ ¬A` — the two shapes where
            # truth is decided by the skeleton and not by the generator at all.
            operator = rng.choice(_BINARY)
            return Skeleton(
                op=operator,
                args=(build(available, budget - 1), build(available, budget - 1)),
            )
        if rng.random() < 0.15:
            return Skeleton(op="not", args=(build(available, budget - 1),))
        cut = rng.randrange(1, len(available))
        operator = rng.choice(_BINARY)
        return Skeleton(
            op=operator,
            args=(build(available[:cut], budget - 1), build(available[cut:], budget - 1)),
        )

    return build(used, depth)


@dataclass(frozen=True, slots=True)
class Compound:
    """One labelled formula of the fragment."""

    skeleton: Skeleton
    #: Generator theorems filling the skeleton's slots, in slot order.
    generators: tuple[Theorem, ...]
    #: Index of the composed formula in the arena.
    term: int
    #: True when the corpus proves it; False when the corpus proves its negation.
    provable: bool

    @property
    def families(self) -> frozenset[str]:
        return frozenset(generator.section for generator in self.generators)


def compose(arena: Arena, skeleton: Skeleton, roots: Sequence[int]) -> int:
    """Realise a skeleton as a term over the generators' conclusion terms."""
    if skeleton.is_slot:
        return roots[skeleton.slot]
    constructor, arity = CONNECTIVES[skeleton.op]
    children = tuple(compose(arena, arg, roots) for arg in skeleton.args)
    if len(children) != arity:
        raise ValueError(f"{skeleton.op} takes {arity} arguments, got {len(children)}")
    return arena.add(constructor, children)


def generate(
    arena: Arena,
    generators: list[Theorem],
    *,
    count: int,
    rng: random.Random,
    max_slots: int = 4,
    max_depth: int = 4,
) -> list[Compound]:
    """``count`` compounds, balanced between provable and refutable.

    Balance is reached by *rejection*, not by negating a formula of the majority
    class: prefixing `¬` to every refutable formula would put the whole label in
    the outermost node, and a structural classifier would be reading a giveaway
    rather than the corpus. The cost is that the two classes have different
    skeleton-shape distributions — inherent, since the label is a function of the
    shape — and `run.py` reports that distribution rather than hiding it.
    """
    target = count // 2
    kept: list[Compound] = []
    counts = {True: 0, False: 0}
    attempts = 0
    limit = count * 200
    while len(kept) < 2 * target and attempts < limit:
        attempts += 1
        slots = rng.randint(1, max_slots)
        skeleton = random_skeleton(rng, slots, max_depth)
        used = sorted(skeleton.slots())
        if used != list(range(slots)):
            continue
        provable = skeleton.evaluate([True] * slots)
        if counts[provable] >= target:
            continue
        chosen = tuple(rng.sample(generators, slots))
        term = compose(arena, skeleton, [theorem.term for theorem in chosen])
        kept.append(
            Compound(
                skeleton=skeleton, generators=chosen, term=term, provable=provable
            )
        )
        counts[provable] += 1
    if counts[True] != counts[False]:
        raise RuntimeError(
            f"could not balance the fragment: {counts[True]} provable vs "
            f"{counts[False]} refutable after {attempts} attempts"
        )
    rng.shuffle(kept)
    return kept
