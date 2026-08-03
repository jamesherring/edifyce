"""A `.mm` file's own ``$t`` map, folded over terms as production templates.

Metamath declares one rendering per *token*. Substituting those into a statement
gives soup; folding them into the *productions* they appear in, and then folding
those over the term, keeps the structure the tree already has. This is the whole
of the bridge, and what it buys is that `set.mm`'s ASCII reads as mathematics.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Definition, LinePart, LineSpec
from website.logical.declarative import Production, SystemSpec, build_system
from website.logical.formal_system import FormalSystem
from website.logical.metamath import build_spec, parse
from website.logical.metamath.definitions import statement_of
from website.logical.metamath.display import (
    applicable,
    applicable_rules,
    notation_constructors,
    notation_report,
    verbatim,
    with_overrides,
    with_rules,
    projection_for,
    unicode_projection,
)
from website.logical.metamath.parser import Database
from website.logical.metamath.setmm import DISPLAY_OVERRIDES, DISPLAY_RULES
from website.logical.metamath.typesetting import Typesetting, typesetting_of
from website.logical.rendering import Projection, Rule, render

SOURCE = r"""
$( $t
    althtmldef "e." as ' &isin; ';
    althtmldef "->" as ' &rarr; ';
    althtmldef "A." as '&forall;';
    althtmldef "RR" as '&#8477;';
    althtmldef "ph" as '<SPAN CLASS=wff STYLE="color:blue">&#x1D711;</SPAN>';
$)
$c |- wff class setvar ( ) -> e. A. RR $.
$v ph ps x A B $.
wph $f wff ph $.
wps $f wff ps $.
vx $f setvar x $.
cA $f class A $.
cB $f class B $.
cr $a class RR $.
cv $a class x $.
wi $a wff ( ph -> ps ) $.
wcel $a wff A e. B $.
wal $a wff A. x ph $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
"""


def built() -> tuple[Database, FormalSystem, Typesetting | None]:
    database = parse(SOURCE)
    system = build_system(build_spec(database, name="t"))
    typesetting = typesetting_of(database.comments)
    return database, system, typesetting


def test_the_projection_respells_a_statement() -> None:
    database, system, typesetting = built()
    projection = unicode_projection(system, typesetting)

    term = statement_of(database.assertions["ax-1"], system)

    assert term.to_string() == "( ph -> ( ps -> ph ) )"
    # `ph` is an atom production, so it is re-spelled by the same map that handles
    # the operators — and its `<SPAN>` markup is stripped on the way through.
    assert render(term, projection) == "( 𝜑 → ( ps → 𝜑 ) )"


def test_an_unprojected_render_is_unchanged() -> None:
    # The property the whole thing rests on: a caller asking for no projection
    # sees exactly what it saw before projections existed.
    database, system, _ = built()

    term = statement_of(database.assertions["ax-1"], system)

    assert render(term) == term.to_string()


def test_spacing_comes_from_the_source_template_not_the_map() -> None:
    # A `$t` rendering carries its own padding (`' &isin; '`), which is HTML's
    # business. The production template already says where the spaces go, so the
    # mapped token is trimmed into the slot — otherwise every operator would
    # render double-spaced.
    database, system, typesetting = built()
    projection = unicode_projection(system, typesetting)

    assert projection.templates["wi"] == (
        ("lit", "( "), ("slot", "ph"), ("lit", " → "), ("slot", "ps"), ("lit", " )")
    )


def test_a_production_with_no_mapped_token_is_left_out() -> None:
    # The projection stays the size of what it changes, so a partial `$t` map — or
    # one for a database that declares more notation than it renders — costs
    # nothing per unmapped production.
    database, system, typesetting = built()
    projection = unicode_projection(system, typesetting)

    assert "cv" not in projection.templates
    assert {"wi", "wcel", "wal", "cr"} <= set(projection.templates)


def test_an_atom_is_respelled_from_its_own_token() -> None:
    database, system, typesetting = built()
    projection = unicode_projection(system, typesetting)

    assert projection.templates["cr"] == (("lit", "ℝ"),)


def test_a_plain_token_map_needs_no_typesetting_block() -> None:
    # `projection_for` takes tokens rather than a `$t`, so a database with no
    # block — or a caller with its own overrides — is served by the same path.
    _database, system, _ = built()
    projection = projection_for(system.build_context, {"->": "⊃"}, name="custom")

    assert projection.name == "custom"
    assert projection.templates["wi"] == (
        ("lit", "( "), ("slot", "ph"), ("lit", " ⊃ "), ("slot", "ps"), ("lit", " )")
    )


def test_a_definitions_own_notation_is_seeded_too() -> None:
    """A definition may be the only thing making a form grammatical.

    Such a form joins no sort's union, so a projection built from the grammar
    alone leaves it in the source spelling while everything around it changes —
    `(S -> p)` rendering as `(S → p)`. The defined forms come from the system's
    definitions, which is why `projection_for` takes them.
    """
    system = build_system(
        SystemSpec(
            name="pc",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(sort="formula", name="implication", template="(A -> B)",
                           bindings=[("A", "formula"), ("B", "formula")]),
                Production(sort="formula", name="falsum", atom_value="F",
                           denotes_constant=True),
            ],
            definitions=[Definition(sort="formula", name="d", higher="S",
                                    lower="(F -> F)", bindings=[])],
            lines=[LineSpec(name="statement", shape="<formula> [<reference>]",
                            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                            logical_sort="formula")],
        )
    )
    term = system.parse("(S -> p) [x]\n").proof_lines[0].formula_term

    without = projection_for(system.build_context, {"S": "⊤", "->": "→"})
    assert render(term, without) == "(S → p)"

    with_definitions = projection_for(
        system.build_context, {"S": "⊤", "->": "→"}, definitions=system.definitions
    )
    assert render(term, with_definitions) == "(⊤ → p)"


def test_a_notation_report_finds_nothing_wrong_with_the_source_spelling() -> None:
    # The identity: a grammar's own tokens are distinct by construction, so no two
    # productions are spelled alike. Everything is "unmapped" because the empty map
    # spells nothing, which is what unmapped means and why it is only cosmetic.
    _database, system, _ = built()
    report = notation_report(system.build_context, {})

    assert report.collision_free
    assert report.collisions == ()
    assert "e." in report.unmapped


def test_a_notation_report_names_the_tokens_it_cannot_spell() -> None:
    _database, system, _ = built()
    report = notation_report(system.build_context, {"e.": "∈"})

    assert "e." not in report.unmapped
    assert "->" in report.unmapped


def two_constants(sort_a: str, sort_b: str) -> FormalSystem:
    """A grammar with two constants, so a notation can be made to confuse them."""
    return build_system(
        SystemSpec(
            name="n",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(sort=sort_a, name="first", atom_value="ALPHA"),
                Production(sort=sort_b, name="second", atom_value="BETA"),
            ],
            lines=[LineSpec(name="statement", shape="<formula> [<reference>]",
                            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                            logical_sort="formula")],
        )
    )


def test_a_notation_that_spells_two_productions_alike_is_not_a_source() -> None:
    # The distinction the whole of §4.2 turns on. As a *display* this is cosmetic —
    # two things look alike and the term underneath is unambiguous. As a *source*
    # it is a correctness bug, because text no longer determines a term.
    system = two_constants("formula", "formula")
    report = notation_report(system.build_context, {"ALPHA": "★", "BETA": "★"})

    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.sort == "formula"
    assert collision.spelling == "★"
    assert collision.productions == ("first", "second")


def test_productions_of_different_sorts_may_share_a_spelling() -> None:
    # Two productions only compete for a parse within one sort, so this is not an
    # ambiguity and reporting it would bury the real ones.
    system = two_constants("formula", "other")
    report = notation_report(system.build_context, {"ALPHA": "★", "BETA": "★"})

    assert report.collision_free


def test_a_sub_sort_competes_in_the_sort_that_includes_it() -> None:
    # The Metamath importer puts each `$v` variable in a `<typecode>_var` sub-sort
    # included into the typecode, so a class variable and a class *constant* fill
    # the same slot. A walk stopping at a sort's own members never compares them —
    # and over set.mm that hid half the collisions, class variables like `.+` being
    # spelled exactly as the `+` operator is.
    _database, system, _ = built()
    report = notation_report(system.build_context, {"RR": "𝐴", "A": "𝐴"})

    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.sort == "class"
    assert collision.productions == ("class_var_A", "cr")


def test_two_templates_differing_only_in_slot_sort_do_not_collide() -> None:
    # A parser tells these apart by what each slot admits, so reporting them would
    # bury the real collisions. Checked under the *identity* notation, where a
    # grammar must always be usable as its own source.
    system = build_system(
        SystemSpec(
            name="s",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(sort="setvar", name="svar", regex="[x-z]"),
                Production(sort="formula", name="frel", template="(A ~ B)",
                           bindings=[("A", "formula"), ("B", "formula")]),
                Production(sort="formula", name="srel", template="(A ~ B)",
                           bindings=[("A", "setvar"), ("B", "setvar")]),
            ],
            lines=[LineSpec(name="statement", shape="<formula> [<reference>]",
                            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                            logical_sort="formula")],
        )
    )
    report = notation_report(system.build_context, {})

    assert report.collision_free


def test_a_collision_spelling_is_printable() -> None:
    # It is a user-facing field, so slots show as the sort they take rather than a
    # sentinel — which also has to survive a terminal, a log and a text column.
    system = build_system(
        SystemSpec(
            name="s",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(sort="formula", name="one", template="(A ~ B)",
                           bindings=[("A", "formula"), ("B", "formula")]),
                Production(sort="formula", name="two", template="(C ~ D)",
                           bindings=[("C", "formula"), ("D", "formula")]),
            ],
            lines=[LineSpec(name="statement", shape="<formula> [<reference>]",
                            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                            logical_sort="formula")],
        )
    )
    (collision,) = notation_report(system.build_context, {}).collisions

    assert collision.spelling == "(<formula> ~ <formula>)"
    assert "\x00" not in collision.spelling


def test_a_defined_form_can_collide_with_a_production() -> None:
    # Defined forms are notation too. `projection_for` already reached them; the
    # report has to as well, or a hand-authored system whose definition spells a
    # form like an existing production is reported usable as a source when it is
    # not.
    system = build_system(
        SystemSpec(
            name="d",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(sort="formula", name="implication", template="(A -> B)",
                           bindings=[("A", "formula"), ("B", "formula")]),
                Production(sort="formula", name="falsum", atom_value="F",
                           denotes_constant=True),
            ],
            definitions=[Definition(sort="formula", name="d", higher="S",
                                    lower="(F -> F)", bindings=[])],
            lines=[LineSpec(name="statement", shape="<formula> [<reference>]",
                            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                            logical_sort="formula")],
        )
    )
    tokens = {"F": "★", "S": "★"}

    assert notation_report(system.build_context, tokens).collision_free
    report = notation_report(
        system.build_context, tokens, notations=system.context.definitions
    )
    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.productions == ("falsum", "formula:S")


LINE = LineSpec(name="statement", shape="<formula> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                logical_sort="formula")


def test_a_mapped_atom_that_a_regex_leaf_would_also_match_collides() -> None:
    # A regex production has a *language*, not a spelling, so it cannot be grouped
    # with the others — but it can be asked. Dropping them let a notation map an
    # atom onto text the sort's variable leaf already accepts, and be reported
    # clean.
    system = build_system(SystemSpec(name="a", productions=[
        Production(sort="formula", name="var", regex="[p-r]"),
        Production(sort="formula", name="alpha", atom_value="ALPHA"),
    ], lines=[LINE]))
    report = notation_report(system.build_context, {"ALPHA": "p"})

    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.productions == ("alpha", "var")


def test_slots_of_sorts_that_include_one_another_overlap() -> None:
    # Sort *names* differing does not make the input languages disjoint: a sort
    # including another accepts everything it does. With `setvar` in `class`,
    # `( x ★ y )` matches both templates, so they collide despite `<class>` and
    # `<setvar>` reading differently.
    system = build_system(SystemSpec(name="b", productions=[
        Production(sort="setvar", name="svar", regex="[x-z]"),
        Production(sort="class", name="setvar"),
        Production(sort="class", name="cconst", atom_value="CC"),
        Production(sort="formula", name="crel", template="(A + B)",
                   bindings=[("A", "class"), ("B", "class")]),
        Production(sort="formula", name="srel", template="(A - B)",
                   bindings=[("A", "setvar"), ("B", "setvar")]),
    ], lines=[LINE]))
    report = notation_report(system.build_context, {"+": "★", "-": "★"})

    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.productions == ("crel", "srel")


def test_a_defined_form_competes_in_every_sort_that_includes_its_own() -> None:
    # The parser tries the definitions of each union it descends through, so a
    # `setvar` definition is a candidate when parsing a `class` too.
    system = build_system(SystemSpec(name="c", productions=[
        Production(sort="setvar", name="svar", regex="[x-z]"),
        Production(sort="setvar", name="unit", atom_value="U",
                   denotes_constant=True),
        Production(sort="class", name="setvar"),
        Production(sort="class", name="cconst", atom_value="CC"),
        Production(sort="formula", name="rel", template="(A = B)",
                   bindings=[("A", "class"), ("B", "class")]),
    ], definitions=[Definition(sort="setvar", name="d", higher="S", lower="U",
                               bindings=[])], lines=[LINE]))
    report = notation_report(
        system.build_context, {"S": "★", "CC": "★"},
        notations=system.context.definitions,
    )

    assert not report.collision_free
    (collision,) = report.collisions
    assert collision.sort == "class"
    assert collision.productions == ("cconst", "setvar:S")


# ---------------------------------------------------------------------------
# Overrides: the editorial half of a notation (roadmap §4.4)
# ---------------------------------------------------------------------------


def test_an_override_replaces_a_derived_template_outright() -> None:
    # A hand-written template is a whole spelling. Blending it with the derived
    # one would produce something nobody wrote.
    _database, system, _typesetting = built()
    derived = projection_for(system.build_context, {"e.": "\\in"}, name="latex")
    assert derived.templates["wcel"] == (
        ("slot", "A"), ("lit", " \\in "), ("slot", "B")
    )

    overridden = with_overrides(
        derived, {"wcel": (("lit", "\\in("), ("slot", "A"), ("lit", ","),
                           ("slot", "B"), ("lit", ")"))}
    )
    assert overridden.templates["wcel"][0] == ("lit", "\\in(")
    assert overridden.name == "latex"


def test_an_override_may_name_a_production_the_map_left_alone() -> None:
    # The common case, and the reason overrides exist at all: a production every
    # token of which maps to itself is *skipped* by the derivation, so it never
    # appears in the derived templates — and it is exactly the one needing help.
    _database, system, _typesetting = built()
    derived = projection_for(system.build_context, {}, name="latex")
    assert "wcel" not in derived.templates

    overridden = with_overrides(derived, {"wcel": (("lit", "!"),)})
    assert overridden.templates["wcel"] == (("lit", "!"),)


def test_overriding_nothing_leaves_the_projection_alone() -> None:
    _database, system, _typesetting = built()
    derived = projection_for(system.build_context, {"e.": "\\in"}, name="latex")
    assert with_overrides(derived, {}).templates == derived.templates


def test_verbatim_names_the_compound_productions_left_as_source() -> None:
    # §4.4's report at the level that matters. A token map covering every token
    # can still leave a *production* in ASCII, when each of its tokens maps to
    # itself — set.mm's `( F ` A )` is the case, and its backtick sets as a quote.
    _database, system, _typesetting = built()
    derived = projection_for(system.build_context, {"e.": "\\in"}, name="latex")

    left = {c.name for c in verbatim(system.build_context, derived)}
    assert "wcel" not in left  # re-spelled, so not on the list
    assert "wi" in left  # `( ph -> ps )`: nothing in it was mapped


def test_verbatim_reports_no_atoms() -> None:
    # An atom the map leaves alone is a token that renders as itself, which is a
    # judgement the file already made. A *production* left alone is a shape nobody
    # has looked at, and that is the list an author wants.
    _database, system, _typesetting = built()
    derived = projection_for(system.build_context, {}, name="latex")

    assert all(c.pieces for c in verbatim(system.build_context, derived))


def test_an_override_for_a_constructor_the_grammar_lacks_is_dropped() -> None:
    # A curated table is a fact about one library. Applied to a different `.mm`
    # the same names may simply be absent, and storing a template for a
    # constructor nothing builds would be storing nonsense.
    _database, system, _typesetting = built()
    constructors = notation_constructors(system.build_context, system.definitions)

    assert applicable({"cfv": (("slot", "F"), ("slot", "A"))}, constructors) == {}
    kept = applicable(
        {"wcel": (("slot", "A"), ("lit", " ! "), ("slot", "B"))}, constructors
    )
    assert "wcel" in kept


def test_an_override_naming_a_slot_the_constructor_lacks_is_dropped() -> None:
    # The sharper half. `render` emits the slot *label* when a template names one
    # the term does not carry, so a `{F}\left({A}\right)` applied to a two-slot
    # production spelled `f`/`x` would put a literal `F` on the page. Refusing
    # beats rendering nonsense.
    _database, system, _typesetting = built()
    constructors = notation_constructors(system.build_context, system.definitions)

    assert applicable({"wcel": (("slot", "A"), ("slot", "B"))}, constructors)
    assert applicable({"wcel": (("slot", "F"), ("slot", "A"))}, constructors) == {}


def test_an_override_that_drops_a_slot_is_dropped() -> None:
    # Naming a *subset* is not enough. A foreign `cfv` taking `F`, `A` and `B`
    # would pass a mentions-only test while silently omitting `B` from every
    # rendering — a term shown as something it is not, which is worse than a
    # visible slot label.
    _database, system, _typesetting = built()
    constructors = notation_constructors(system.build_context, system.definitions)

    assert applicable({"wcel": (("slot", "A"),)}, constructors) == {}
    assert applicable({"wcel": (("lit", "always"),)}, constructors) == {}


def test_the_curated_setmm_table_matches_the_slots_it_names() -> None:
    # The table is written against `set.mm`'s constructors, and a slot renamed
    # upstream would render its own label rather than the subterm. Nothing else
    # would notice, so this does.
    for notation, overrides in DISPLAY_OVERRIDES.items():
        assert notation in {"unicode", "latex"}, notation
        for name, pieces in overrides.items():
            assert pieces, name
            assert any(kind == "slot" for kind, _text in pieces) or name == "cdc", name


# Two connectives of the same shape and the same slot sorts, so a spelling that
# made them alike would be a real ambiguity rather than one the sorts settle.
TWO_CONNECTIVES = r"""
$c |- wff ( ) -> /\\ $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wa $a wff ( ph /\\ ps ) $.
"""


def test_a_collision_an_override_introduces_is_reported() -> None:
    # The only kind of collision curating the table can create, and the one a
    # token-level check cannot see: an override replaces a template wholesale, so
    # nothing about the token map changes when two productions start reading
    # alike.
    system = build_system(build_spec(parse(TWO_CONNECTIVES), name="t"))
    tokens = {"->": "\\to", "/\\": "\\wedge"}
    derived = projection_for(system.build_context, tokens, name="latex")
    assert not notation_report(
        system.build_context, tokens, templates=derived.templates
    ).collisions

    clash = with_overrides(derived, {"wa": derived.templates["wi"]})
    report = notation_report(system.build_context, tokens, templates=clash.templates)
    assert [set(c.productions) for c in report.collisions] == [{"wa", "wi"}]

    # And the token-level view still sees nothing, which is the whole point.
    assert not notation_report(system.build_context, tokens).collisions


def test_the_report_without_templates_reads_the_derived_notation() -> None:
    # The default, and what every existing caller means: no override has been
    # applied, so the map is the notation.
    _database, system, _typesetting = built()
    tokens = {"e.": "\\in"}
    assert notation_report(system.build_context, tokens).collisions == (
        notation_report(system.build_context, tokens, templates={}).collisions
    )


# A grammar that applies things generically, as `set.mm` does: `( F ` A )` is one
# production whatever `F` is, so the symbol a reader thinks of as the operator is
# an operand sitting in a slot.
APPLICATION = r"""
$c |- wff class ( ) ` e. sqrt RR $.
$v A B F $.
cA $f class A $.
cB $f class B $.
cF $f class F $.
csqrt $a class sqrt $.
cr $a class RR $.
cfv $a class ( F ` A ) $.
wcel $a wff A e. B $.
"""


def applying() -> tuple[FormalSystem, list]:
    system = build_system(build_spec(parse(APPLICATION), name="t"))
    return system, notation_constructors(system.build_context, system.definitions)


def test_a_rule_the_grammar_can_use_is_kept() -> None:
    system, constructors = applying()
    rule = Rule(
        name="sqrt",
        constructor="cfv",
        pins={"F": "csqrt"},
        pieces=(("lit", r"\sqrt{"), ("slot", "A"), ("lit", "}")),
    )

    assert applicable_rules([rule], constructors) == [rule]


def test_a_rule_rooted_at_a_constructor_the_grammar_lacks_is_dropped() -> None:
    _system, constructors = applying()
    rule = Rule(
        name="fraction",
        constructor="co",
        pins={"F": "cdiv"},
        pieces=(("slot", "A"), ("lit", "/"), ("slot", "B")),
    )

    assert applicable_rules([rule], constructors) == []


def test_a_rule_that_leaves_a_slot_out_is_dropped() -> None:
    # The same hazard `applicable` refuses for an override, and sharper here: a
    # rule *consumes* what it pins, so a slot neither pinned nor rendered vanishes
    # from the page with nothing to show it ever existed.
    _system, constructors = applying()
    silent = Rule(
        name="half", constructor="cfv", pins={"F": "csqrt"}, pieces=(("lit", "root"),)
    )

    assert applicable_rules([silent], constructors) == []


def test_a_rule_naming_a_slot_the_root_lacks_is_dropped() -> None:
    _system, constructors = applying()
    wrong = Rule(
        name="wrong",
        constructor="cfv",
        pins={"F": "csqrt"},
        pieces=(("slot", "A"), ("slot", "B")),
    )

    assert applicable_rules([wrong], constructors) == []


def test_a_rule_pinning_a_production_the_grammar_lacks_is_dropped() -> None:
    # Dead rather than dangerous — a pin that can never hold never fires — but
    # silently dead, which is exactly what a table carried between libraries would
    # be. Refusing says so.
    _system, constructors = applying()
    absent = Rule(
        name="abs",
        constructor="cfv",
        pins={"F": "cabs"},
        pieces=(("lit", "|"), ("slot", "A"), ("lit", "|")),
    )

    assert applicable_rules([absent], constructors) == []


def test_with_rules_adds_rather_than_replaces() -> None:
    # Unlike an override, which is keyed by name and wins outright: several rules
    # legitimately share a root, since fixing a different operand in the same
    # applicator is the whole idiom.
    first = Rule(name="a", constructor="cfv", pieces=(("slot", "F"),))
    second = Rule(name="b", constructor="cfv", pieces=(("slot", "A"),))

    projection = with_rules(with_rules(Projection(name="x"), [first]), [second])

    assert projection.rules == (first, second)
    assert projection.name == "x"


def test_the_curated_setmm_rules_are_shaped_for_setmm() -> None:
    # As with the overrides: the table is written against `set.mm`'s constructors,
    # and nothing else would notice a slot renamed upstream.
    for notation, rules in DISPLAY_RULES.items():
        assert notation in {"unicode", "latex"}, notation
        for rule in rules:
            assert rule.name, rule
            assert rule.constructor in {"cfv", "co"}, rule.name
            assert rule.pins, rule.name
            # Every slot of the root accounted for, which is what
            # `applicable_rules` checks against a real grammar.
            expected = {"F", "A"} if rule.constructor == "cfv" else {"F", "A", "B"}
            assert rule.roots(expected) == expected, rule.name
    assert len({rule.name for rules in DISPLAY_RULES.values() for rule in rules}) == 7
