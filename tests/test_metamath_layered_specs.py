"""One `SystemSpec` per layer, and the property that makes the split safe.

D3 of docs/system-relationships-roadmap.md. D1 measured where `set.mm` stops
being one theory and starts being the next and shipped the plan
(`setmm.LAYERS`); this is the split itself — `corpus_specs` returns a spec per
layer instead of one covering everything.

**The contract the whole module is about:** layering the pieces back must declare
exactly what the unlayered spec declares. The partition moves where a production
is *stored*; it moves nothing about what the grammar is. Anything else would make
a layered import a different import, and D5's headline invariant — same theorem
count, same verdicts, byte-identical proof sources — could not hold.

Everything here runs on a fixture shaped like `set.mm`'s three layers, since the
file itself is not in the repository. What the fixture reproduces is the shape
that matters: a subsection *inside* a layer, notation declared in each layer and
used only at or after it, and variables that arrive layer by layer.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_spec as build_system_spec
from website.logical.declarative import layered_spec
from website.logical.metamath import parse
from website.logical.metamath.corpus import corpus_spec, corpus_specs
from website.logical.metamath.sections import Layer
from website.logical.metamath.setmm import LAYERS

PART = "#" * 40
SECTION = "#*" * 20
SUBSECTION = "=-" * 20

# Three layers, in `set.mm`'s own section titles so the shipped plan selects
# them. Each declares notation of its own and proves something with it.
CORPUS = f"""
$c |- wff class ( ) -> A. e. $.
$v ph ps x A $.
wph $f wff ph $.
wps $f wff ps $.
vx $f class x $.
cA $f class A $.

$( {PART}
   LOGIC
   {PART} $)
$( {SECTION}
   Pre-logic
   {SECTION} $)
wi $a wff ( ph -> ps ) $.
$( {SECTION}
   Propositional calculus
   {SECTION} $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
$( {SUBSECTION}
   A subsection, which must not open a layer
   {SUBSECTION} $)
pc-thm $p |- ( ph -> ( ps -> ph ) ) $= wph wps ax-1 $.

$( {SECTION}
   Predicate calculus with equality:  Tarski's system S2
   {SECTION} $)
wal $a wff A. x ph $.
ax-4 $a |- ( A. x ph -> ph ) $.
fol-thm $p |- ( A. x ph -> ph ) $= vx wph ax-4 $.

$( {PART}
   SET THEORY
   {PART} $)
$( {SECTION}
   ZF Set Theory - start with the Axiom of Extensionality
   {SECTION} $)
wcel $a wff A e. A $.
ax-ext $a |- ( A e. A -> A e. A ) $.
zf-thm $p |- ( A e. A -> A e. A ) $= cA ax-ext $.
"""


def names(spec) -> list[str]:
    """Every production a spec declares a *name* for, in order.

    Sort inclusions are excluded, since they name a sort rather than themselves
    and are the one production a chain may repeat (`_declares_a_name`).
    """
    return [
        production.name
        for production in spec.productions
        if production.template or production.regex or production.atom_value
        or production.atom_base
    ]


def notation(spec) -> list[str]:
    """The *syntax* productions alone, in order — no variable leaves.

    The distinction matters for the contract below. Splitting a corpus does not
    reorder notation, but it does move where the **variables** sit: one spec
    emits every `$f`-declared leaf after all the syntax, while a chain emits each
    layer's after that layer's. Same members in the same unions either way, and
    a sort's alternatives are tried in the matcher's certainty order rather than
    in declaration order — so what has to be preserved is the *set* of names and
    the order of the notation, which is what a later production could depend on.
    """
    return [
        production.name
        for production in spec.productions
        if not production.sort.endswith("_var")
        and (production.template or production.regex or production.atom_value
             or production.atom_base)
    ]


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_layering_the_split_back_declares_what_the_whole_declared() -> None:
    # **The headline**, and the reason a layered import can be the same import.
    # Whatever the plan does to where a production is stored, the grammar the
    # chain describes is the grammar the single spec described — same names, same
    # order, and a chain that builds.
    database = parse(CORPUS)

    whole = corpus_spec(database)
    split = corpus_specs(database, plan=LAYERS)

    assert len(split) == 3
    chain = layered_spec(split)

    # Every name the whole declared, and no other.
    assert set(names(chain)) == set(names(whole))
    # And the notation in the same order, which is the half that could matter:
    # a production declared later may be read through one declared earlier.
    assert notation(chain) == notation(whole)

    # And it is a *system*, not just a spec: a chain that collides on a name or
    # loses a sort would build to errors rather than to this.
    built = build_system_spec(chain)
    assert "errors" not in built, built["errors"]


def test_each_layer_holds_only_what_its_own_sections_declared() -> None:
    # The partition itself. `wi` and `ax-1`'s notation belong to the first layer,
    # the quantifier to the second, membership to the third — and a production
    # appears in exactly one of them, which is what `layered_spec` requires and
    # what makes the chain's namespace well defined.
    database = parse(CORPUS)
    split = corpus_specs(database, plan=LAYERS)

    assert [spec.name for spec in split] == [
        "Propositional calculus", "First-order logic", "ZF set theory"
    ]
    assert "wi" in names(split[0])
    assert "wal" in names(split[1]) and "wal" not in names(split[0])
    assert "wcel" in names(split[2]) and "wcel" not in names(split[1])

    everywhere = [name for spec in split for name in names(spec)]
    assert len(everywhere) == len(set(everywhere)), "a production is in one layer"


def test_only_the_root_carries_the_line_type_and_the_brackets() -> None:
    # A later layer is a **delta**. Restating the line type would redeclare a
    # name across the chain, which `layered_spec` refuses — and restating the
    # brackets would be harmless but is still a second place for one fact.
    database = parse(CORPUS)
    split = corpus_specs(database, plan=LAYERS)

    assert [line.name for line in split[0].lines] == ["statement"]
    assert split[0].brackets and split[0].token_separated
    for later in split[1:]:
        assert later.lines == []
        assert later.brackets == []


# ---------------------------------------------------------------------------
# What an empty or unmatched plan does
# ---------------------------------------------------------------------------


def test_no_plan_is_exactly_todays_single_spec() -> None:
    # The contract `BINDERS` and `EQUIVALENCES` already follow, and what keeps
    # this additive: an import naming no plan behaves as it did before layering
    # existed. Asserted against `corpus_spec` itself rather than against a
    # remembered shape.
    database = parse(CORPUS)

    assert len(corpus_specs(database)) == 1
    # Identical, order included: with no plan there is no split to reorder
    # anything, and this is the assertion that says so.
    assert names(corpus_specs(database)[0]) == names(corpus_spec(database))


def test_a_plan_the_file_does_not_open_is_the_same_as_none() -> None:
    # A variant `.mm`, or a plan written for another file. One layer of it opens
    # here, so there is nothing to split and the result is the single spec.
    database = parse(CORPUS)
    elsewhere = (Layer(name="Nothing here", starts_with="Category theory"),)

    assert len(corpus_specs(database, plan=elsewhere)) == 1
    assert names(corpus_specs(database, plan=elsewhere)[0]) == names(
        corpus_spec(database)
    )


# ---------------------------------------------------------------------------
# The horizon, which bounds the layers as well as the walk
# ---------------------------------------------------------------------------


def test_a_limit_short_of_a_layer_drops_it() -> None:
    # `limit` stops the walk, and a layer the walk never reaches holds nothing.
    # Emitting it empty would be a system row with no grammar, which is a worse
    # thing to store than one fewer layer.
    database = parse(CORPUS)

    assert len(corpus_specs(database, limit=1, plan=LAYERS)) == 1
    assert len(corpus_specs(database, limit=2, plan=LAYERS)) == 2
    assert len(corpus_specs(database, limit=3, plan=LAYERS)) == 3


def test_a_limited_split_still_layers_back_to_the_limited_whole() -> None:
    # The contract again, at a horizon short of the file's end — which is the
    # case a milestone slice actually runs (§7.1's N).
    database = parse(CORPUS)

    chain = layered_spec(corpus_specs(database, limit=2, plan=LAYERS))
    whole = corpus_spec(database, limit=2)

    assert set(names(chain)) == set(names(whole))
    assert notation(chain) == notation(whole)
    assert "errors" not in build_system_spec(chain)


def test_a_layer_with_theorems_but_no_notation_is_still_a_layer() -> None:
    # The case `set.mm` actually presents at the milestone slice, and the reason
    # two milestones are recorded rather than one: the file opens ZF with
    # `ax-ext` and five theorems before its first new syntax axiom, so a ZF spec
    # built at N declares nothing.
    #
    # It is still emitted. A layer with theorems and no grammar is a system that
    # inherits its whole language, which is an ordinary thing for a layer to be —
    # dropping it would put its theorems in the layer below, which is the one
    # thing the partition exists to prevent. What *is* dropped is a layer the
    # walk never reaches at all, which holds nothing of either kind.
    source = CORPUS.replace(
        "wcel $a wff A e. A $.\nax-ext $a |- ( A e. A -> A e. A ) $.",
        "ax-ext $a |- ( ph -> ph ) $.",
    ).replace("zf-thm $p |- ( A e. A -> A e. A ) $= cA ax-ext $.",
              "zf-thm $p |- ( ph -> ph ) $= wph ax-ext $.")
    database = parse(source)
    split = corpus_specs(database, plan=LAYERS)

    assert [spec.name for spec in split] == [
        "Propositional calculus", "First-order logic", "ZF set theory"
    ]
    assert names(split[2]) == []
    # And it still builds as a chain, which is what says an empty layer is a
    # legal one rather than something the builder tolerates by accident.
    assert "errors" not in build_system_spec(layered_spec(split))
