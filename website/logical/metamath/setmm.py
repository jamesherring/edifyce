"""Declarations about `set.mm` specifically — data, not engine behaviour.

Things an import needs that a ``.mm`` file does not say, and that no property of a
statement's shape settles. Each is therefore *declared* per database and defaults
to nothing, so an import naming none behaves exactly as one did before any of them
existed; this module is where `set.mm`'s answers live so they are written once
rather than in each caller.

Keeping them out of the engine is the point. Edifyce checks any formal system, and
a table naming `wal` and `wceq` is a fact about one library — the same reason the
grammar itself is built from the file rather than hard-wired.
"""

from __future__ import annotations

from ..rendering import Rule

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
# What this shape cannot express is a spelling that spans two productions —
# `( sqrt ` 2 )` is `cfv` applied to the constant `csqrt` — which is what
# `DISPLAY_RULES` below is for.
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


# The spellings that span two productions, where a per-production template cannot
# reach.
#
# `set.mm` writes function application and binary operation *generically*: `( F `
# A )` is one production (`cfv`) whatever `F` is, and `( A F B )` is one
# production (`co`). So the symbol a reader thinks of as the operator — `sqrt`,
# `/`, `^` — is an **operand**, a nullary class constant sitting in a slot, and
# re-spelling either production says nothing about it. `( sqrt ` 2 )` comes out of
# `DISPLAY_OVERRIDES` as `\surd\left(2\right)`; only matching the pair says
# `\sqrt{2}`.
#
# A `rendering.Rule` is that pair written down: the production at the root, what
# must sit at a slot for it to apply, and the template to use when it does. The
# pinned operand is *consumed* — there is no `\surd` left in `\sqrt{2}` — which is
# exactly why this cannot be a template for either production alone.
#
# Six, chosen because in each the mathematical notation is genuinely
# two-dimensional or fenced and the linear form is a transcription of it rather
# than the thing. `+`, `x.` and the rest read correctly as `( A + B )` and are
# left alone. As with `DISPLAY_OVERRIDES` this is `latex` only: the `unicode`
# reading exists to be faithful to how `set.mm` itself writes things.
DISPLAY_RULES: dict[str, tuple[Rule, ...]] = {
    "latex": (
        # `( sqrt ` A )`, where `sqrt` maps to `\surd` — the symbol, not the
        # radical, because `\sqrt` in TeX takes its argument under the vinculum
        # and a token map has no argument to give it.
        Rule(
            name="sqrt",
            constructor="cfv",
            pins={"F": "csqrt"},
            pieces=(("lit", r"\sqrt{"), ("slot", "A"), ("lit", "}")),
        ),
        # `( abs ` A )`. `\operatorname{abs}` is a faithful reading of the token
        # and nobody writes it; the bars are the notation.
        Rule(
            name="absolute-value",
            constructor="cfv",
            pins={"F": "cabs"},
            pieces=(
                ("lit", r"\left\lvert "),
                ("slot", "A"),
                ("lit", r"\right\rvert"),
            ),
        ),
        # `( ! ` A )`. Postfix, which no prefix application template can be.
        #
        # Its own nesting is the one place a postfix reading goes wrong, and the
        # rule below is why this one may stay simple: `A!!` is conventionally the
        # *double* factorial, a different operation, so a factorial of a factorial
        # would be shown as mathematics the term does not say. `set.mm` contains no
        # such statement today, and the fix costs a rule rather than parentheses on
        # every `N!` in the corpus.
        Rule(
            name="factorial",
            constructor="cfv",
            pins={"F": "cfa"},
            pieces=(("slot", "A"), ("lit", "!")),
        ),
        # `( ! ` ( ! ` A ) )`. More pins than the rule above, so it is tried first
        # whatever order the table is written in — which is what lets a general
        # spelling stay general and the ambiguous case be answered separately.
        # Fences the *whole* operand rather than reaching past it, so it composes
        # with itself: a third application renders the second's output bracketed
        # again, and no depth produces a bare `!!`.
        Rule(
            name="factorial-of-factorial",
            constructor="cfv",
            pins={"F": "cfa", "A.F": "cfa"},
            pieces=(("lit", r"\left("), ("slot", "A"), ("lit", r"\right)!")),
        ),
        # `( A / B )`. The argument for a rule here is weaker than for `\sqrt` —
        # `A / B` is readable — but a corpus of real analysis is mostly quotients
        # and `\frac` is what they are written as.
        Rule(
            name="fraction",
            constructor="co",
            pins={"F": "cdiv"},
            pieces=(
                ("lit", r"\frac{"),
                ("slot", "A"),
                ("lit", "}{"),
                ("slot", "B"),
                ("lit", "}"),
            ),
        ),
        # `( A ^ B )`, where `^` maps to `\uparrow` — Knuth's arrow, which is a
        # different operation. Superscripting is the notation.
        #
        # The base is braced as well as the exponent, which is not decoration:
        # `expmul` is `( A ^ ( M x. N ) ) = ( ( A ^ M ) ^ N )`, and an unbraced
        # base makes the right-hand side `A^{M}^{N}` — a double superscript TeX
        # refuses to set.
        Rule(
            name="power",
            constructor="co",
            pins={"F": "cexp"},
            pieces=(
                ("lit", "{"),
                ("slot", "A"),
                ("lit", "}^{"),
                ("slot", "B"),
                ("lit", "}"),
            ),
        ),
        # `( N _C K )`, the binomial coefficient. `\mathbin{\operatorname{C}}` is
        # what the token map gives, and it is infix where the notation is stacked.
        Rule(
            name="binomial",
            constructor="co",
            pins={"F": "cbc"},
            pieces=(
                ("lit", r"\binom{"),
                ("slot", "A"),
                ("lit", "}{"),
                ("slot", "B"),
                ("lit", "}"),
            ),
        ),
    ),
}
