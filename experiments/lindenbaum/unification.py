"""Terms the prover can take apart and put back together.

The corpus arrives as an interned DAG of *stored* terms. A prover needs three
things that storage does not provide: fresh copies of a lemma's variables each
time it is used, a way to hold the goal's own variables rigid while it works, and
structural equality between terms it just built and terms the corpus stored.

All three come from one decision — **every term is interned by its exact
structural key**, including the ones the prover builds. Equality is then index
equality, a substitution is a dict of ints, and a term the prover constructs that
happens to be a statement the corpus already stored *is* that stored term.

Variables live in three namespaces, distinguished by a prefix on the name because
that keeps them ordinary terms rather than a parallel representation:

* plain (`ph`, `A`, `x`) — as the corpus stored them. Never unified against
  directly; a lemma is refreshed before use and a goal is frozen before it.
* ``?`` — **flexible**: a refreshed lemma variable, which unification may bind.
* ``!`` — **rigid**: a frozen goal variable. A goal is proved *as a schema*, so
  its own metavariables must behave as constants during the search; unifying one
  with a lemma's variable is fine, but binding it to a term is not, and letting
  that happen is the classic way to "prove" something false.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from experiments.lindenbaum.dag import KIND_BOUND, KIND_NODE, KIND_VAR

if TYPE_CHECKING:
    from collections.abc import Iterable

    from experiments.lindenbaum.corpus import Corpus

FLEXIBLE = "?"
RIGID = "!"

#: A substitution: flexible variable term → the term bound to it.
Subst = dict[int, int]


class Terms:
    """An interned term store, seeded from a corpus and grown by the prover."""

    __slots__ = ("kind", "constructor", "literal", "var_name", "sort", "children",
                 "bound_index", "_by_key", "_key", "_vars", "_size")

    def __init__(self, corpus: Corpus) -> None:
        self.kind = list(corpus.kind)
        self.constructor = list(corpus.constructor)
        self.literal = list(corpus.literal)
        self.var_name = list(corpus.var_name)
        self.bound_index = list(corpus.bound_index)
        self.sort = list(corpus.sort)
        self.children = list(corpus.children)
        self._key: list[tuple] = []
        self._by_key: dict[tuple, int] = {}
        self._vars: list[frozenset[int] | None] = [None] * len(self.kind)
        self._size: list[int] = [0] * len(self.kind)
        self._seed()

    def _signature(self, term: int) -> tuple:
        if self.kind[term] == KIND_VAR:
            return (KIND_VAR, self.sort[term], self.var_name[term])
        if self.kind[term] == KIND_BOUND:
            return (KIND_BOUND, self.sort[term], self.bound_index[term])
        return (
            KIND_NODE,
            self.constructor[term],
            self.literal[term],
            self.sort[term],
            tuple(self._key[child][0] for child in self.children[term]),
        )

    def _seed(self) -> None:
        """Give every stored term a canonical index, keyed by exact structure.

        A layered import interns per layer, so the same `ph` is several rows;
        after this they are one term and the prover never has to ask which layer
        a formula came from.
        """
        total = len(self.kind)
        self._key = [()] * total
        canonical = [0] * total
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
                    signature = self._signature(term)
                    first = self._by_key.setdefault(signature, term)
                    canonical[term] = first
                    self._key[term] = (first, signature)
                    done[term] = 1
                    continue
                stack.append((term, True))
                for child in self.children[term]:
                    if not done[child]:
                        stack.append((child, False))
        # Rewrite every edge to point at the canonical copy, so two layers'
        # copies of one subterm stop being two terms.
        self.children = [
            tuple(canonical[child] for child in kids) for kids in self.children
        ]
        for term in range(total):
            self._key[term] = (canonical[term], self._signature(term))

    def canonical(self, term: int) -> int:
        return self._key[term][0]

    def mark(self) -> int:
        """A watermark to :meth:`release` back to."""
        return len(self.kind)

    def release(self, mark: int) -> None:
        """Discard every term interned since ``mark``.

        A proof attempt refreshes each lemma it tries into a fresh variable
        namespace, and interning keeps all of them — so a few hundred attempts
        against a corpus of this size exhaust memory, which is how the first
        run of the search evaluation died. The corpus's own terms sit below
        every watermark, so releasing costs nothing that is reused; what must
        not outlive the call is the proof tree, whose terms are above it.
        """
        for term in range(mark, len(self.kind)):
            self._by_key.pop(self._key[term][1], None)
        del self.kind[mark:]
        del self.constructor[mark:]
        del self.literal[mark:]
        del self.var_name[mark:]
        del self.bound_index[mark:]
        del self.sort[mark:]
        del self.children[mark:]
        del self._key[mark:]
        del self._vars[mark:]
        del self._size[mark:]

    def _intern(self, signature: tuple) -> int:
        found = self._by_key.get(signature)
        if found is not None:
            return found
        term = len(self.kind)
        self.kind.append(signature[0])
        if signature[0] == KIND_VAR:
            self.constructor.append(None)
            self.literal.append(None)
            self.sort.append(signature[1])
            self.var_name.append(signature[2])
            self.bound_index.append(None)
            self.children.append(())
        elif signature[0] == KIND_BOUND:
            self.constructor.append(None)
            self.literal.append(None)
            self.sort.append(signature[1])
            self.var_name.append(None)
            self.bound_index.append(signature[2])
            self.children.append(())
        else:
            self.constructor.append(signature[1])
            self.literal.append(signature[2])
            self.sort.append(signature[3])
            self.var_name.append(None)
            self.bound_index.append(None)
            self.children.append(tuple(signature[4]))
        self._key.append((term, signature))
        self._vars.append(None)
        self._size.append(0)
        self._by_key[signature] = term
        return term

    def variable(self, name: str, sort: str | None) -> int:
        return self._intern((KIND_VAR, sort, name))

    def node(self, term: int, children: tuple[int, ...]) -> int:
        """A copy of ``term``'s head over new children."""
        return self._intern(
            (
                KIND_NODE,
                self.constructor[term],
                self.literal[term],
                self.sort[term],
                children,
            )
        )

    def is_variable(self, term: int) -> bool:
        return self.kind[term] == KIND_VAR

    def is_flexible(self, term: int) -> bool:
        name = self.var_name[term]
        return self.kind[term] == KIND_VAR and name is not None and name[0] == FLEXIBLE

    def variables(self, term: int) -> frozenset[int]:
        """Every variable term reachable, memoised on the shared DAG."""
        cached = self._vars[term]
        if cached is not None:
            return cached
        if self.kind[term] == KIND_VAR:
            found = frozenset({term})
        elif not self.children[term]:
            found = frozenset()
        else:
            found = frozenset().union(
                *(self.variables(child) for child in self.children[term])
            )
        self._vars[term] = found
        return found

    def size(self, term: int) -> int:
        cached = self._size[term]
        if cached:
            return cached
        total = 1 + sum(self.size(child) for child in self.children[term])
        self._size[term] = total
        return total

    def rename(self, term: int, prefix: str, cache: dict[int, int]) -> int:
        """``term`` with every plain variable renamed into ``prefix``'s namespace."""
        found = cache.get(term)
        if found is not None:
            return found
        if self.kind[term] == KIND_VAR:
            name = self.var_name[term] or ""
            built = (
                term
                if name[:1] in (FLEXIBLE, RIGID)
                else self.variable(prefix + name, self.sort[term])
            )
        elif not self.children[term]:
            built = term
        else:
            built = self.node(
                term,
                tuple(self.rename(child, prefix, cache) for child in self.children[term]),
            )
        cache[term] = built
        return built

    def resolve(self, term: int, subst: Subst) -> int:
        while True:
            bound = subst.get(term)
            if bound is None or bound == term:
                return term
            term = bound

    def apply(self, term: int, subst: Subst, cache: dict[int, int] | None = None) -> int:
        """``term`` with every binding in ``subst`` carried out, recursively."""
        if not subst:
            return term
        if cache is None:
            cache = {}
        found = cache.get(term)
        if found is not None:
            return found
        head = self.resolve(term, subst)
        if self.kind[head] == KIND_VAR or not self.children[head]:
            built = head
        else:
            built = self.node(
                head,
                tuple(self.apply(child, subst, cache) for child in self.children[head]),
            )
        cache[term] = built
        return built

    def occurs(self, variable: int, term: int, subst: Subst) -> bool:
        head = self.resolve(term, subst)
        if head == variable:
            return True
        return any(self.occurs(variable, child, subst) for child in self.children[head])

    def unify(self, left: int, right: int, subst: Subst) -> Subst | None:
        """Unify, binding only flexible variables. Mutates and returns ``subst``.

        A rigid variable unifies with a flexible one — the lemma is allowed to be
        *about* the goal's variables — but never with a term, and never with a
        different rigid variable. That asymmetry is the whole soundness of
        proving a schema.
        """
        left = self.resolve(left, subst)
        right = self.resolve(right, subst)
        if left == right:
            return subst
        if self.is_flexible(left):
            if self.occurs(left, right, subst):
                return None
            # Sorts are compared only when both are known. A *declared*
            # production's node carries no sort — the store keeps one only for a
            # variable, a bound, or defined notation — so requiring equality here
            # refused every binding of a variable to a term, `ax-mp`'s conclusion
            # first among them. Where the store is silent, well-sortedness is
            # already guaranteed by position: unification descends a shared
            # constructor, and the grammar fixed each slot's sort.
            if (
                self.sort[left] is not None
                and self.sort[right] is not None
                and self.sort[left] != self.sort[right]
            ):
                return None
            subst[left] = right
            return subst
        if self.is_flexible(right):
            return self.unify(right, left, subst)
        if self.kind[left] != self.kind[right] or self.kind[left] != KIND_NODE:
            return None
        if (
            self.constructor[left] != self.constructor[right]
            or self.literal[left] != self.literal[right]
            or len(self.children[left]) != len(self.children[right])
        ):
            return None
        for a, b in zip(self.children[left], self.children[right], strict=True):
            if self.unify(a, b, subst) is None:
                return None
        return subst


def freeze(terms: Terms, term: int) -> int:
    return terms.rename(term, RIGID, {})


def disjoint_holds(
    terms: Terms,
    pairs: Iterable[tuple[str, str]],
    bindings: dict[str, int],
    subst: Subst,
    goal_disjoint: frozenset[tuple[str, str]],
) -> bool:
    """Metamath's `$d`, checked for one step and propagated to the goal's own.

    Two obligations, and skipping either is how a search invents proofs the
    verifier rejects. The substitutions for a disjoint pair must share no
    variable; and where they carry the *goal's* variables, the goal must itself
    declare those disjoint, since a proof of the goal may not quietly need more
    than the goal promised.
    """
    for left_name, right_name in pairs:
        left = bindings.get(left_name)
        right = bindings.get(right_name)
        if left is None or right is None:
            continue
        left_vars = terms.variables(terms.apply(left, subst))
        right_vars = terms.variables(terms.apply(right, subst))
        if left_vars & right_vars:
            return False
        for one in left_vars:
            name = terms.var_name[one] or ""
            if name[:1] != RIGID:
                continue
            for other in right_vars:
                other_name = terms.var_name[other] or ""
                if other_name[:1] != RIGID:
                    continue
                bare = (name[1:], other_name[1:])
                if bare not in goal_disjoint and bare[::-1] not in goal_disjoint:
                    return False
    return True
