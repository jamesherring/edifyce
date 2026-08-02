"""Declarations about `set.mm` specifically — data, not engine behaviour.

Three things an import needs that a ``.mm`` file does not say, and that no
property of a statement's shape settles. Both are therefore *declared* per database and
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

# The one assertion that cannot be stated over either of them: `df-bi` *defines*
# `<->`, so it is written in `-.` and `->` and the root test refuses it. `dfbi1` is
# the same content the ordinary way round —
#
#     df-bi  |- -. ( ( ( ph <-> ps ) -> -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) )
#                   -> -. ( -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) -> ( ph <-> ps ) ) )
#     dfbi1  |- ( ( ph <-> ps ) <-> -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) )
#
# — and `set.mm` says so itself, which is why this is one entry rather than a
# reading of a negation nest: the file carries `$j definition 'dfbi1' for 'wb';`,
# the sole `definition` directive among its 1,204 `$j`. The table is written from
# that rather than invented, and `_restatement` checks what the directive cannot:
# that `dfbi1` is *proved* and that its proof cites `df-bi`.
#
# A database bootstraps its equivalence connective once, so a second entry here
# would be a surprise rather than a pattern.
RESTATEMENTS: dict[str, str] = {"df-bi": "dfbi1"}


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
#     cmpo    class ( x e. A , y e. B |-> C )   `y` reaches *back* to `A`, and `x`
#                                               forward to `B`; neither by position
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
    # Maps, whose binders reach the domains as well as the body — but not to the
    # same extent, and the difference is in their definientia rather than in their
    # notation, which is identically shaped:
    #
    #     df-mpo    ( x e. A , y e. B |-> C ) = { <. <. x , y >. , z >. |
    #                                             ( ( x e. A /\ y e. B ) /\ z = C ) }
    #     df-bj-mpt3  ( x e. A , y e. B , z e. C |-> D )
    #                 = { <. s , t >. | E. x e. A E. y e. B E. z e. C ( … /\ t = D ) }
    #
    # `cmpo` abstracts its binders **simultaneously**, so each of them binds across
    # every slot and `y` reaches `A` — which `df-linc` is the corpus's one use of,
    # writing `( s e. ( … ^m v ) , v e. ~P ( Base ` m ) |-> … )`. `cmpt3` nests
    # *restricted existentials* instead, so its scoping is strictly forward and `y`
    # reaches `C` and `D` but never `A`. Reading the second off the first is exactly
    # the analogy to avoid.
    #
    # A binder's own domain is left out of its scope throughout. Each definiens does
    # bind it — `{ <. x , y >. | ( x e. A /\ … ) }` captures an `x` in `A` — but
    # `x e. A ( x )` is degenerate, `set.mm` forbids it by `$d` wherever it could
    # arise, and omitting it is the safe direction: an occurrence read as free costs
    # a refused definition, one wrongly read as bound would hide a capture.
    "cmpt": {"x": ["B"]},                       # ( x e. A |-> B )
    "cmpo": {"x": ["B", "C"], "y": ["A", "C"]},  # ( x e. A , y e. B |-> C )
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


# How a handful of productions should *read* in a notation, where the faithful
# re-spelling reads badly.
#
# A `$t` map is per token, so deriving a notation from one re-spells the tokens a
# production is made of and leaves its shape alone. That is right nearly
# everywhere and wrong in a few places, and the few are not a matter of taste:
# every token in `( F ` A )` maps to *itself* under `latexdef`, so function
# application comes out of a LaTeX notation in raw ASCII with its backtick set as
# a left quote. 36% of `set.mm`'s statements contain one.
#
# So this is the list `display.verbatim` produces, curated. Of the 11 compound
# productions `latexdef` leaves in the source spelling, most are right as they
# are — `A = B`, `A R B`, `( A F B )` need no help — and these are the ones that
# do. Keyed by notation, because an override is a decision about one reading: the
# `unicode` notation deliberately has none, since `( 𝐹 ‘ 𝐴 )` is how `set.mm`
# itself writes application and a Unicode reading exists to be faithful.
#
# What this shape *cannot* express is an override spanning two productions.
# `( sqrt ` 2 )` is `cfv` applied to the constant `csqrt`, so no per-production
# template turns it into ``\\sqrt{2}`` — that needs matching a subtree, which is a
# different mechanism (see the roadmap's §4.4).
DISPLAY_OVERRIDES: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "latex": {
        # Function application. The defect, not a preference: `` ` `` maps to
        # itself, so this renders as `( f ` x )` and TeX sets the backtick as an
        # opening quote. `\left(\right)` so the brackets grow with the argument.
        "cfv": (
            ("slot", "F"),
            ("lit", r"\left("),
            ("slot", "A"),
            ("lit", r"\right)"),
        ),
        # A decimal numeral, built digit by digit: `;` is the constructor, not a
        # character to print, and `; 1 2` is the number 12. Juxtaposition is both
        # the correct reading and the shorter one.
        "cdc": (("slot", "A"), ("slot", "B")),
        # Class abstraction. `|` sets as an ordinary bar with no spacing; `\mid`
        # is the relation TeX provides for exactly this, and the braces have to
        # grow with the body.
        "cab": (
            ("lit", r"\left\{"),
            ("slot", "x"),
            ("lit", r" \mid "),
            ("slot", "ph"),
            ("lit", r"\right\}"),
        ),
    },
}
