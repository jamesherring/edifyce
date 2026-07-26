"""Constants whose spelling contains a bracket.

A grammar may name a constant that is *spelled* with a delimiter without that
delimiter grouping anything. ``set.mm`` declares fourteen — the half-open
interval ``[,)``, the doubled paren ``((``, ``O(1)``, ``(x)`` — and a statement
mentioning one, such as ``( 0 [,) +oo ) C_ RR``, used to be refused before a
parse was attempted: the ``)`` inside ``[,)`` was counted as a delimiter and the
statement read as unbalanced.

Bracket parity is an optimisation and not a grammatical rule (a formula parses
uniquely because its productions *contain* the brackets as literals, not because
the string balances), so the fix is to let a declared constant be opaque to the
scan rather than to weaken the parse.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import (
    LinePart,
    LineSpec,
    Production,
    SystemSpec,
    build_system,
)
from website.logical.matching import AtomPattern, Context, StringPattern, UnionPattern

# The set.mm tokens this exists for, as the roadmap records them.
INTERVAL_TOKENS = ["[,)", "(,]", "(,)"]
ODD_TOKENS = ["((", "O(1)", "(x)"]


def setmm_shaped_system(constants):
    """A system in `set.mm`'s shape: space-separated tokens, `( A OP B )`."""
    productions = [
        Production(sort="class", name="cA", atom_value="A", denotes_constant=True),
        Production(sort="class", name="c0", atom_value="0", denotes_constant=True),
        Production(sort="class", name="cRR", atom_value="RR", denotes_constant=True),
        Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
        Production(sort="wff", name="wps", atom_value="ps", denotes_constant=True),
        Production(
            sort="class", name="co", template="( a b c )",
            bindings=[("a", "class"), ("b", "class"), ("c", "class")],
        ),
        Production(
            sort="wff", name="wi", template="( a -> b )",
            bindings=[("a", "wff"), ("b", "wff")],
        ),
        Production(
            sort="wff", name="wss", template="a C_ b",
            bindings=[("a", "class"), ("b", "class")],
        ),
    ]
    productions += [
        Production(sort="class", name=f"k{i}", atom_value=token, denotes_constant=True)
        for i, token in enumerate(constants)
    ]

    spec = SystemSpec(
        name="setmmish",
        brackets=[("(", ")")],
        token_separated=True,
        productions=productions,
        lines=[
            LineSpec(
                name="statement",
                shape="<wff> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="wff",
            )
        ],
        rules=[],
    )
    return build_system(spec)


def reads(system, text, sort="wff"):
    context = Context()
    context.variables = system.context.variables
    context.parse_memo = {}
    return system.context.variables[sort].match(text, context) is not None


@pytest.fixture
def setmm():
    return setmm_shaped_system([*INTERVAL_TOKENS, *ODD_TOKENS])


def test_the_builder_finds_the_constants_that_spell_a_delimiter(setmm):
    # Derived from the declared productions, not configured: a constant is opaque
    # exactly when its own spelling contains a delimiter.
    opaque = setmm.context.variables["class"].opaque_tokens

    assert set(opaque) == {"[,)", "(,]", "(,)", "((", "O(1)", "(x)"}

    # `A`, `0` and `RR` name constants too, and none of them is opaque.
    assert "A" not in opaque
    assert "RR" not in opaque


def test_a_statement_using_one_now_parses(setmm):
    # The shape of the 15 theorems `set.mm` could not import.
    assert reads(setmm, "( 0 [,) RR ) C_ RR")
    assert reads(setmm, "( 0 (,] RR ) C_ RR")
    assert reads(setmm, "( 0 (,) RR ) C_ RR")
    assert reads(setmm, "( A (x) A ) C_ RR")
    assert reads(setmm, "( A O(1) A ) C_ RR")


def test_ordinary_grouping_still_has_to_balance(setmm):
    assert not reads(setmm, "( 0 [,) RR C_ RR")
    assert not reads(setmm, "( ph -> ps ")
    assert not reads(setmm, "( ph -> ps ) )")
    assert not reads(setmm, "( A ( A ) C_ RR")


def test_nesting_is_unaffected(setmm):
    assert reads(setmm, "( ph -> ps )")
    assert reads(setmm, "( ( ph -> ps ) -> ph )")
    assert reads(setmm, "( ( ( ph -> ps ) -> ph ) -> ps )")
    assert reads(setmm, "( ( 0 [,) RR ) C_ RR -> ph )")


def test_a_system_naming_no_such_constant_declares_none():
    # The common case: nothing changes, and the scan costs what it always did.
    plain = setmm_shaped_system([])

    assert plain.context.variables["class"].opaque_tokens == frozenset()
    assert reads(plain, "( ph -> ps )")


# ---------------------------------------------------------------------------
# Opacity is by whole token
# ---------------------------------------------------------------------------


def bracket_grammar(opaque):
    sort = UnionPattern(name="cls", patterns=[], respect_brackets={"(": ")"})
    group = StringPattern(name="group", pattern="( a )", respect_brackets={"(": ")"})
    binary = StringPattern(name="binary", pattern="( a b c )", respect_brackets={"(": ")"})

    for compound in (group, binary):
        sort.add_pattern(compound)
    for token in ("A", "B", "((", "[,)"):
        sort.add_pattern(AtomPattern(name=f"k{token}", value=token))

    group.add_variables({"a": sort})
    binary.add_variables({"a": sort, "b": sort, "c": sort})

    for pattern in (sort, group, binary):
        pattern.opaque_tokens = opaque

    return sort


def test_a_token_is_opaque_only_where_it_stands_alone():
    # `((` names a constant, and `( (` is two grouping parens. Nothing but the
    # token boundary tells them apart, which is why opacity is not a per-character
    # rule: a bare `(` inside a statement still has to be closed.
    sort = bracket_grammar(("((", "[,)"))

    context = Context()

    assert sort.match("( A (( B )", context) is not None
    assert sort.match("( A [,) B )", context) is not None
    assert sort.match("( ( A ) )", context) is not None
    assert sort.match("((", context) is not None

    assert sort.match("( A ( B )", context) is None
    assert sort.match("( A ) )", context) is None


def test_a_truncated_token_is_not_opaque():
    # A slot's text can cut a token in half. `[,` is not the declared constant,
    # so its `[`... there is none - but `,)` ends in a delimiter that must count.
    sort = bracket_grammar(("((", "[,)"))
    context = Context()

    assert sort.match("( A ,) B )", context) is None


def test_multi_character_delimiters_step_over_them_too():
    # Delimiters longer than a character take the general scan rather than the
    # profile, and it has to respect opacity as well.
    pairs = {"begin": "end"}
    sort = UnionPattern(name="cls", patterns=[], respect_brackets=pairs)
    group = StringPattern(name="group", pattern="begin a end", respect_brackets=pairs)
    sort.add_pattern(group)
    for token in ("A", "beginend"):
        sort.add_pattern(AtomPattern(name=f"k{token}", value=token))
    group.add_variables({"a": sort})

    for pattern in (sort, group):
        pattern.opaque_tokens = ("beginend",)

    context = Context()

    assert sort.match("begin A end", context) is not None
    assert sort.match("begin beginend end", context) is not None
    assert sort.match("begin A", context) is None


# ---------------------------------------------------------------------------
# The promise itself
# ---------------------------------------------------------------------------


def test_a_bracketed_constant_without_the_promise_is_refused():
    # Reading one needs the token boundary, so a system that has not promised its
    # tokens are separated is told so at build time - rather than building
    # happily and failing to parse the statements that mention it.
    spec_productions = [
        Production(sort="class", name="cA", atom_value="A", denotes_constant=True),
        Production(sort="class", name="ico", atom_value="[,)", denotes_constant=True),
        Production(
            sort="wff", name="wi", template="( a -> b )",
            bindings=[("a", "wff"), ("b", "wff")],
        ),
        Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
    ]
    spec = SystemSpec(
        name="unseparated",
        brackets=[("(", ")")],
        productions=spec_productions,
        lines=[
            LineSpec(
                name="statement", shape="<wff> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="wff",
            )
        ],
        rules=[],
    )

    with pytest.raises(ValueError) as raised:
        build_system(spec)

    assert "[,)" in str(raised.value)
    assert "token_separated" in str(raised.value)


def test_the_promise_is_checked_against_the_templates():
    # Declaring it while writing `(a -> b)` would be a lie: the slot is glued to
    # the paren, so no token boundary separates them and a bracketed constant
    # could not be told apart after all.
    spec = SystemSpec(
        name="glued",
        brackets=[("(", ")")],
        token_separated=True,
        productions=[
            Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
            Production(
                sort="wff", name="wi", template="(a -> b)",
                bindings=[("a", "wff"), ("b", "wff")],
            ),
        ],
        lines=[
            LineSpec(
                name="statement", shape="<wff> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="wff",
            )
        ],
        rules=[],
    )

    with pytest.raises(ValueError) as raised:
        build_system(spec)

    assert "wi" in str(raised.value)
    assert "token_separated" in str(raised.value)


def test_a_system_that_keeps_its_tokens_apart_builds():
    system = setmm_shaped_system([])

    assert reads(system, "( ph -> ps )")


def test_the_promise_is_not_needed_when_no_constant_spells_a_bracket():
    # The overwhelmingly common case: nothing declares it, nothing checks it, and
    # a template may glue its tokens together as most systems do.
    spec = SystemSpec(
        name="ordinary",
        brackets=[("(", ")")],
        productions=[
            Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
            Production(
                sort="wff", name="wi", template="(a -> b)",
                bindings=[("a", "wff"), ("b", "wff")],
            ),
        ],
        lines=[
            LineSpec(
                name="statement", shape="<wff> [<reference>]",
                parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
                logical_sort="wff",
            )
        ],
        rules=[],
    )
    system = build_system(spec)

    assert system.context.variables["wff"].opaque_tokens == frozenset()
    assert reads(system, "(ph -> ph)")
