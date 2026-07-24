"""The ZFC-style scoped natural-deduction system, as a programmatic ``SystemSpec``.

``scoped_zfc_spec()`` returns a first-order natural-deduction system (membership
``∈``, implication ``→``, negation ``¬``, universal ``∀``) exercised by
``tests/test_zfc_scoped.py``: ``assumption``/``variable`` scope line types that
open first-class subproofs, discharge rules (``CP``, ``UG``) that consume a
subproof as a unit, and ``∀I``'s freshness. It is assembled directly from the
declarative model and built with ``declarative.build_system`` -- there is no
``.edi`` source. (The same system was previously the hand-authored ``.edi``
fixture ``SCOPED_ZFC``; scope + subproof are now first-class in ``SystemSpec``,
so the fixture is retired in favour of this factory.)
"""

from __future__ import annotations

from website.logical.declarative import LineSpec, Rule, Subproof, SystemSpec

from tests.spec_helpers import (
    assumption_line,
    brackets,
    cp_rule,
    mp_rule,
    regex_prod,
    reiteration_rule,
    statement_line,
    template_prod,
)


def scoped_zfc_spec() -> SystemSpec:
    """The scoped ZFC system: scope line types, subproofs, discharge rules."""
    return SystemSpec(
        name="ScopedZFC",
        brackets=brackets(),
        productions=[
            # `setvar` is a leaf sort whose member name must differ from the sort
            # (else step 4 of build_system appends the union to itself).
            regex_prod("setvar", "setvar_atom", "[a-z][a-z0-9]*"),
            template_prod("formula", "membership", "x ∈ y", [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "negation", "¬p", [("p", "formula")]),
            template_prod("formula", "universal", "∀x p", [("x", "setvar"), ("p", "formula")]),
        ],
        lines=[
            statement_line(),   # the claim line: `<formula> [<reference>]`
            assumption_line(),  # `assume <formula>`, opens an assumption subproof
            LineSpec(name="introduce", shape="let <setvar>", logical_sort="setvar", scope="variable"),
        ],
        rules=[
            reiteration_rule(),  # R
            mp_rule(),           # MP
            cp_rule(),           # CP: →I, discharges an assumption subproof
            Rule(                # UG: ∀I, discharges a fresh-variable subproof
                label="UG",
                name="universal generalisation",
                antecedents=[],
                deduction="∀x p",
                bindings=[("x", "setvar"), ("p", "formula")],
                subproof=Subproof(fresh="x", derive="p"),
            ),
        ],
    )
