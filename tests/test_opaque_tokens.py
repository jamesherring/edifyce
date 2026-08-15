"""The token boundary a bracket-spelled constant is read against.

A constant may be *spelled* with a bracket without that bracket grouping
anything — ``set.mm`` names its half-open intervals ``[,)`` and ``(,]``, and
thirteen more of its constants spell a parenthesis. ``declarative`` already lets
the bracket scan step over such a token (``_bracket_opaque_tokens``); the
statements that then read are in ``tests/test_metamath_import.py``.

What is here is the *boundary*: a token is stepped over only where it stands
whole, between whitespace or the ends of the string. Nothing else tells the
constant ``((`` from two grouping parens written together, and a bare ``(`` still
has to be closed. Asserted on ``check_brackets`` directly, because that is where
the difference shows — a formula built over the same grammar fails either way,
for the unrelated reason that no production spells the mangled token.

``SystemSpec.token_separated`` is the declaration that a system writes its
notation this way. Nothing depends on it being true (see its docstring); it is
checked so that declaring it means something.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import DeclarativeError, SystemSpec, build_system
from website.logical.matching import StringPattern

from tests.spec_helpers import atom_const_prod, brackets, statement_line, template_prod

SEPARATED = template_prod(
    "formula", "implication", "( a -> b )", [("a", "formula"), ("b", "formula")]
)
GLUED = template_prod(
    "formula", "implication", "(a -> b)", [("a", "formula"), ("b", "formula")]
)
ATOMS = [
    atom_const_prod("formula", "ph", "ph", denotes_constant=True),
    atom_const_prod("formula", "ps", "ps", denotes_constant=True),
]
INTERVAL = atom_const_prod("formula", "ico", "[,)", denotes_constant=True)


def spec_with(productions, token_separated=False):
    return SystemSpec(
        name="s",
        brackets=brackets(),
        token_separated=token_separated,
        productions=list(productions),
        lines=[statement_line()],
        rules=[],
    )


def scanner(opaque):
    """A bare pattern carrying a bracket table and some opaque tokens."""
    pattern = StringPattern(name="probe", pattern="( a )", respect_brackets={"(": ")"})
    pattern.bracket_opaque = opaque
    return pattern


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


def test_a_token_glued_to_more_text_is_not_the_constant():
    # `[,)x` is not the declared constant, so the `)` in it delimits like any
    # other and the string does not balance.
    probe = scanner(("[,)",))

    assert probe.check_brackets("( A [,) B )") is True
    assert probe.check_brackets("( A [,)x B )") is False
    assert probe.check_brackets("( A x[,) B )") is False


def test_two_grouping_parens_are_not_the_constant_that_spells_them():
    # set.mm names the constant `((`. Were every occurrence stepped over, an
    # ordinary nesting written without the space would lose both its openings.
    probe = scanner(("((",))

    assert probe.check_brackets("((") is True
    assert probe.check_brackets("( A (( B )") is True

    assert probe.check_brackets("((A))") is True
    assert probe.check_brackets("( A ((B )") is False


def test_a_string_naming_no_opaque_token_is_scanned_as_before():
    probe = scanner(("[,)", "(("))

    assert probe.check_brackets("( ( A ) )") is True
    assert probe.check_brackets("( A ( B )") is False
    assert probe.check_brackets("( A ) )") is False


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_the_declaration_is_checked_against_the_production_templates():
    # Declaring it while writing `(a -> b)` would be a lie: the slot shares a
    # token with the paren.
    with pytest.raises(DeclarativeError) as raised:
        build_system(spec_with([*ATOMS, GLUED], token_separated=True))

    assert "implication" in str(raised.value)
    assert "token_separated" in str(raised.value)


def test_a_separated_system_may_declare_it():
    system = build_system(spec_with([*ATOMS, SEPARATED, INTERVAL], token_separated=True))

    assert system.context.variables["formula"].bracket_opaque == ("[,)",)


def test_not_declaring_it_is_never_an_error():
    # The declaration gates nothing - a bracket-spelled constant is read against
    # the token boundary whether or not the system claims to supply one - so a
    # glued system naming one still builds.
    system = build_system(spec_with([*ATOMS, GLUED, INTERVAL]))

    assert system.context.variables["formula"].bracket_opaque == ("[,)",)


def test_a_label_occurring_inside_a_literal_is_not_a_glued_slot():
    # `A` sits inside the quantifier token `A.`, which is the collision
    # `metamath.importer._uncollide` exists for. The check compares whole tokens,
    # so the literal does not read as a slot glued to its neighbour.
    universal = template_prod(
        "formula", "universal", "A. x ph", [("x", "setvar"), ("ph", "formula")]
    )
    spec = spec_with(
        [
            *ATOMS,
            SEPARATED,
            atom_const_prod("setvar", "vx", "x"),
            universal,
        ],
        token_separated=True,
    )

    assert build_system(spec).context.variables["formula"] is not None
