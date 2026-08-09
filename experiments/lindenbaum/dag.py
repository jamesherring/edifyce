"""The term DAG the experiment walks, and the alpha-invariant key it walks for.

Two jobs. First, an **arena**: the corpus's stored terms plus the nodes the
experiment synthesises when it builds a Boolean compound out of them, in one
index space, so a compound is walked by exactly the code that walks a stored
statement.

Second, the key that makes a subtree feature *alpha-normalized*. Collapsing
every variable to a single wildcard would be invariant under renaming, but it is
also invariant under *identifying* two variables — it cannot tell `φ → φ` from
`φ → ψ`, which is most of what a propositional corpus is about. So the key
numbers a subterm's free variables by first occurrence within that subterm, and
keeps each variable's **sort** — a wff metavariable is not a renaming of a
setvar, and the engine's own alpha hash keeps the sort for the same reason:

    key(c(t₁…tₖ)) = H(c, key(t₁), ρ₁, …, key(tₖ), ρₖ)

where ρⱼ maps subterm j's local variable numbering into the parent's. Both
factors are invariant under a consistent renaming of the parent's free variables
and neither is invariant under identifying two of them, so the key is exactly the
alpha class — and it is compositional, which is what lets a stored corpus be
keyed once and reused under every compound built over it.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from experiments.lindenbaum.corpus import Corpus

KIND_NODE = "node"
KIND_VAR = "var"
KIND_BOUND = "bound"


def _hash(payload: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


@dataclass
class Arena:
    """Every term the experiment can see, stored terms and synthesised alike."""

    kind: list[str]
    constructor: list[str | None]
    literal: list[str | None]
    var_name: list[str | None]
    bound_index: list[int | None]
    sort: list[str | None]
    children: list[tuple[int, ...]]
    #: Alpha-invariant 64-bit key per term; see the module docstring.
    key: list[int] = field(default_factory=list)
    #: Free variables in first-occurrence order, the other half of the key.
    free: list[tuple[str, ...]] = field(default_factory=list)

    @staticmethod
    def of(corpus: Corpus) -> Arena:
        arena = Arena(
            kind=list(corpus.kind),
            constructor=list(corpus.constructor),
            literal=list(corpus.literal),
            var_name=list(corpus.var_name),
            bound_index=list(corpus.bound_index),
            sort=list(corpus.sort),
            children=list(corpus.children),
        )
        arena._key_every_term()
        return arena

    def __len__(self) -> int:
        return len(self.kind)

    def add(self, constructor: str, children: tuple[int, ...]) -> int:
        """Append a synthesised node and key it. Returns its index."""
        term = len(self.kind)
        self.kind.append(KIND_NODE)
        self.constructor.append(constructor)
        self.literal.append(None)
        self.var_name.append(None)
        self.bound_index.append(None)
        self.sort.append(None)
        self.children.append(children)
        self.free.append(self._free_of(term))
        self.key.append(self._key_of(term))
        return term

    def _free_of(self, term: int) -> tuple[str, ...]:
        if self.kind[term] == KIND_VAR:
            name = self.var_name[term]
            return (name,) if name is not None else ()
        order: list[str] = []
        seen: set[str] = set()
        for child in self.children[term]:
            for name in self.free[child]:
                if name not in seen:
                    seen.add(name)
                    order.append(name)
        return tuple(order)

    def _key_of(self, term: int) -> int:
        kind = self.kind[term]
        if kind == KIND_VAR:
            # Two variables are alpha-equivalent when they have the same sort —
            # a wff metavariable is not a renaming of a setvar. What further
            # distinguishes them is where they recur, which the parent records.
            return _hash(b"var" + (self.sort[term] or "").encode())
        if kind == KIND_BOUND:
            return _hash(
                b"bound"
                + struct.pack("<q", self.bound_index[term] or 0)
                + (self.sort[term] or "").encode()
            )
        position = {name: at for at, name in enumerate(self.free[term])}
        payload = bytearray(b"node")
        payload += (self.constructor[term] or "").encode()
        payload += b"\x1f"
        payload += (self.literal[term] or "").encode()
        payload += b"\x1f"
        payload += (self.sort[term] or "").encode()
        for child in self.children[term]:
            payload += struct.pack("<Q", self.key[child])
            for name in self.free[child]:
                payload += struct.pack("<i", position[name])
            payload += b"\x1e"
        return _hash(bytes(payload))

    def _key_every_term(self) -> None:
        """Key the whole stored DAG in one post-order pass.

        Iterative rather than recursive: a set.mm statement is shallow, but
        nothing guarantees that of an arbitrary corpus and a blown stack halfway
        through a quarter of a million terms is a poor failure mode.
        """
        total = len(self.kind)
        self.free = [()] * total
        self.key = [0] * total
        done = bytearray(total)
        for root in range(total):
            if done[root]:
                continue
            stack = [(root, False)]
            while stack:
                term, expanded = stack.pop()
                if done[term]:
                    continue
                if expanded:
                    self.free[term] = self._free_of(term)
                    self.key[term] = self._key_of(term)
                    done[term] = 1
                    continue
                stack.append((term, True))
                for child in self.children[term]:
                    if not done[child]:
                        stack.append((child, False))


@dataclass(frozen=True, slots=True)
class Walk:
    """What one pass over a term's *tree* found.

    ``multiplicity`` is per distinct subterm, so the shared DAG is walked once
    but every statistic is the tree's. That distinction is not cosmetic here: a
    compound repeats its generators, and a feature vector that counted a repeated
    conjunct once would make `A ∧ A` and `A` identical to the classifier.
    """

    subterms: list[int]
    multiplicity: dict[int, int]
    #: Height of each distinct subterm — well defined on a DAG, unlike a depth
    #: measured from the root, which a shared subterm has more than one of.
    height: dict[int, int]
    #: Σ multiplicity × height, so the caller can report a mean.
    height_total: int
    leaves: int
    nodes: int
    variables: int


def walk(arena: Arena, root: int) -> Walk:
    order: list[int] = []
    seen: set[int] = set()
    stack = [(root, False)]
    while stack:
        term, expanded = stack.pop()
        if expanded:
            order.append(term)
            continue
        if term in seen:
            continue
        seen.add(term)
        stack.append((term, True))
        for child in arena.children[term]:
            if child not in seen:
                stack.append((child, False))

    height: dict[int, int] = {}
    for term in order:
        kids = arena.children[term]
        height[term] = 1 + max((height[child] for child in kids), default=0)

    multiplicity = dict.fromkeys(order, 0)
    multiplicity[root] = 1
    for term in reversed(order):
        count = multiplicity[term]
        for child in arena.children[term]:
            multiplicity[child] += count

    nodes = leaves = variables = height_total = 0
    for term in order:
        count = multiplicity[term]
        nodes += count
        height_total += count * height[term]
        if not arena.children[term]:
            leaves += count
        if arena.kind[term] == KIND_VAR:
            variables += count
    return Walk(
        subterms=order,
        multiplicity=multiplicity,
        height=height,
        height_total=height_total,
        leaves=leaves,
        nodes=nodes,
        variables=variables,
    )
