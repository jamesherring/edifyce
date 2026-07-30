"""Declarations about `set.mm` specifically — data, not engine behaviour.

Two things an import needs that a ``.mm`` file does not say, and that no property
of a statement's shape settles. Both are therefore *declared* per database and
default to nothing, so an import that names neither behaves exactly as one did
before either existed; this module is where `set.mm`'s answers live so they are
written once rather than in each caller.

Keeping them out of the engine is the point. Edifyce checks any formal system, and
a table naming `wal` and `wceq` is a fact about one library — the same reason the
grammar itself is built from the file rather than hard-wired.
"""

from __future__ import annotations

# The productions that mean *definitional equivalence*, so a logical `$a` stated
# over one can be imported as a definition (see :mod:`~.definitions`). Arity and
# slot sorts do not distinguish `↔` from `→`, and reading a one-way implication as
# a definition would licence the reverse rewrite, so this is named rather than
# inferred.
EQUIVALENCES = frozenset({"wb", "wceq"})


# Which slot of a syntax axiom **binds**, and over which others.
#
# A `.mm` file carries no trace of this: `A. x ph` and a two-argument connective
# are the same shape, and Metamath's verifier never needs to tell them apart —
# `$d` provisos carry the weight instead. Edifyce needs it because a definition
# whose defining form binds a dummy must declare that dummy `fresh`, or the unfold
# would conjure a name; `Production.scopes_over` is where a grammar says so, and
# `formal_system.definitions` reads the `fresh` clause off it rather than asking
# an author to write one (docs/binding-slots-design.md).
#
# Written by reading each syntax axiom's statement, and each entry is checked
# against the axiom's own variables when the spec is built. Order does *not*
# decide it, which is worth seeing before trusting any rule that says it does:
#
#     citg    class S. A B _d x        the binder is the last token, and binds `B`
#     cmpo    class ( x e. A , y e. B |-> C )     `x` reaches `B` as well as `C`
#     wral    wff A. x e. A ph         `x` binds `ph` and *not* the domain `A`
#
# `set.mm` says as much itself, in the other direction: `$j free_var 'wsb' with
# 'y'` marks the `y` of `[ y / x ] ph` free although it sits where a binder would.
# Those annotations are an exception list against an assumed default, not a set of
# declarations — there are five of them in the file, against the 28 productions
# below — which is why this is a table rather than something read out of `$j`.
BINDERS: dict[str, dict[str, list[str]]] = {
    # Quantifiers and their restricted forms.
    "wal": {"x": ["ph"]},                       # A. x ph
    "wex": {"x": ["ph"]},                       # E. x ph
    "weu": {"x": ["ph"]},                       # E! x ph
    "wmo": {"x": ["ph"]},                       # E* x ph
    "wral": {"x": ["ph"]},                      # A. x e. A ph
    "wrex": {"x": ["ph"]},                      # E. x e. A ph
    "wreu": {"x": ["ph"]},                      # E! x e. A ph
    # Class abstraction and the ordered-pair abstractions.
    "cab": {"x": ["ph"]},                       # { x | ph }
    "crab": {"x": ["ph"]},                      # { x e. A | ph }
    "copab": {"x": ["ph"], "y": ["ph"]},        # { <. x , y >. | ph }
    "coprab": {"x": ["ph"], "y": ["ph"], "z": ["ph"]},
    # { <. <. x , y >. , z >. | ph }
    # Description operators.
    "cio": {"x": ["ph"]},                       # ( iota x ph )
    "crio": {"x": ["ph"]},                      # ( iota_ x e. A ph )
    "caiota": {"x": ["ph"]},                    # ( iota' x ph )
    # Substitution. `x` binds; `y` is the substitute and stays free, which is what
    # `$j free_var 'wsb' with 'y'` says.
    "wsb": {"x": ["ph"]},                       # [ y / x ] ph
    "wsbc": {"x": ["ph"]},                      # [. A / x ]. ph
    "csb": {"x": ["B"]},                        # [_ A / x ]_ B
    # Maps. A later domain may mention an earlier binder, so `cmpo` and `cmpt3`
    # scope across the domains as well as the body.
    "cmpt": {"x": ["B"]},                       # ( x e. A |-> B )
    "cmpo": {"x": ["B", "C"], "y": ["C"]},      # ( x e. A , y e. B |-> C )
    "cmpt3": {"x": ["B", "C", "D"], "y": ["C", "D"], "z": ["D"]},
    # ( x e. A , y e. B , z e. C |-> D )
    # Indexed families and big operators: the index binds the body, never the
    # index set.
    "ciun": {"x": ["B"]},                       # U_ x e. A B
    "ciin": {"x": ["B"]},                       # |^|_ x e. A B
    "cixp": {"x": ["B"]},                       # X_ x e. A B
    "csu": {"k": ["B"]},                        # sum_ k e. A B
    "cesum": {"k": ["B"]},                      # sum* k e. A B
    "cprod": {"k": ["B"]},                      # prod_ k e. A B
    "citg": {"x": ["B"]},                       # S. A B _d x
    "wdisj": {"x": ["B"]},                      # Disj_ x e. A B
}
