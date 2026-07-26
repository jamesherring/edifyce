"""The promise that a system's tokens are whitespace-separated.

A constant may be *spelled* with a bracket without that bracket grouping
anything — ``set.mm`` names its half-open intervals ``[,)`` and ``(,]``, and
thirteen more of its constants spell a parenthesis. ``declarative`` already lets
the bracket scan step over such a token (see ``_bracket_opaque_tokens``, and
``tests/test_metamath_import.py`` for the statements that then read).

What is here is the boundary that makes stepping over one *safe*. Only the token
boundary tells the constant ``((`` from two grouping parens written together, and
a system has to promise its notation supplies one — ``SystemSpec.token_separated``
— or be refused the constant rather than silently mis-read.
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


def statement_line():
    return LineSpec(
        name="statement",
        shape="<wff> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
        logical_sort="wff",
    )


def spec_with(productions, token_separated=False):
    return SystemSpec(
        name="s",
        brackets=[("(", ")")],
        token_separated=token_separated,
        productions=productions,
        lines=[statement_line()],
        rules=[],
    )


SEPARATED = [
    Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
    Production(sort="wff", name="wps", atom_value="ps", denotes_constant=True),
    Production(
        sort="wff", name="wi", template="( a -> b )",
        bindings=[("a", "wff"), ("b", "wff")],
    ),
]

GLUED = [
    Production(sort="wff", name="wph", atom_value="ph", denotes_constant=True),
    Production(
        sort="wff", name="wi", template="(a -> b)",
        bindings=[("a", "wff"), ("b", "wff")],
    ),
]

INTERVAL = Production(sort="wff", name="ico", atom_value="[,)", denotes_constant=True)


def reads(system, text):
    context = Context()
    context.variables = system.context.variables
    context.parse_memo = {}
    return system.context.variables["wff"].match(text, context) is not None


# ---------------------------------------------------------------------------
# The promise
# ---------------------------------------------------------------------------


def test_a_bracketed_constant_without_the_promise_is_refused():
    # Reading one needs the token boundary, so a system that has not promised its
    # tokens supply one is told at build time - rather than building happily and
    # failing to parse every statement that mentions it.
    with pytest.raises(ValueError) as raised:
        build_system(spec_with([*SEPARATED, INTERVAL]))

    assert "[,)" in str(raised.value)
    assert "token_separated" in str(raised.value)


def test_the_promise_is_checked_against_the_templates():
    # Declaring it while writing `(a -> b)` would be a lie: the slot is glued to
    # the paren, so no boundary separates them and a bracketed constant could not
    # be told apart after all.
    with pytest.raises(ValueError) as raised:
        build_system(spec_with([*GLUED, INTERVAL], token_separated=True))

    assert "wi" in str(raised.value)
    assert "token_separated" in str(raised.value)


def test_the_promise_kept_admits_the_constant():
    system = build_system(spec_with([*SEPARATED, INTERVAL], token_separated=True))

    assert system.context.variables["wff"].bracket_opaque == ("[,)",)
    assert reads(system, "( ph -> ps )")


def test_nothing_is_required_of_a_system_naming_no_such_constant():
    # The overwhelmingly common case: the promise is neither needed nor checked,
    # and a template may glue its tokens together as most systems do.
    system = build_system(spec_with(GLUED))

    assert system.context.variables["wff"].bracket_opaque == ()
    assert reads(system, "(ph -> ph)")


def test_the_promise_alone_does_not_need_a_bracketed_constant():
    # Declaring it without naming such a constant is allowed - it just means the
    # templates are held to it.
    system = build_system(spec_with(SEPARATED, token_separated=True))

    assert reads(system, "( ph -> ps )")


# ---------------------------------------------------------------------------
# The boundary the promise buys
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
        pattern.bracket_opaque = opaque

    return sort


def test_a_token_is_opaque_only_where_it_stands_alone():
    # `((` names a constant and `( (` is two grouping parens. Without the
    # boundary the first spelling of the second would be read as the constant,
    # and `( ( A ) )` - a perfectly ordinary nesting - would lose two openings.
    sort = bracket_grammar(("((", "[,)"))
    context = Context()

    assert sort.match("( A (( B )", context) is not None
    assert sort.match("( A [,) B )", context) is not None
    assert sort.match("((", context) is not None

    assert sort.match("( ( A ) )", context) is not None

    assert sort.match("( A ( B )", context) is None
    assert sort.match("( A ) )", context) is None


def test_a_bracket_glued_into_a_longer_token_is_not_the_constant():
    # `[,)x` is not the declared constant, so its `)` is a delimiter like any
    # other and the string does not balance.
    sort = bracket_grammar(("((", "[,)"))
    context = Context()

    assert sort.match("( A [,)x B )", context) is None
