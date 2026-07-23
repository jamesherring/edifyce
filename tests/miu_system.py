"""Hofstadter's MIU system (Gödel, Escher, Bach) as a :class:`SystemSpec`.

MIU is a *string-rewriting* (semi-Thue) system, not a logical one: theorems are
strings over the alphabet ``{M, I, U}``, the sole axiom is ``MI``, and the four
rules rewrite substrings. It is the canonical example of a system the engine's
default term-unification checker cannot express — rule 2 concatenates a variable
with itself (``Mx -> Mxx``) and rules 3/4 bind variables to arbitrary-length
substrings around a gap (``xIIIy``, ``xUUy``). Those need *associative* matching,
so every rule is declared ``matching="string"`` (see
``website.logical.matching.rewriting``).

    Axiom : MI
    R1    : xI    -> xIU     (if it ends in I, append U)
    R2    : Mx    -> Mxx     (double everything after the M)
    R3    : xIIIy -> xUy     (rewrite any III to U)
    R4    : xUUy  -> xy      (drop any UU)

The grammar is a single sort ``miustr`` matched by ``[MIU]+`` (anchored on
lowering, so it rejects non-MIU text). The logical line carries a ``[reference]``
slot so a rule citation like ``[R2, 1]`` parses.
"""

from __future__ import annotations

from website.logical.declarative import LinePart, LineSpec, Production, Rule, SystemSpec


def _rule(label: str, name: str, antecedent: str, deduction: str, variables: list[str]) -> Rule:
    """A single-antecedent string-rewriting rule over ``miustr`` variables."""
    return Rule(
        label=label,
        name=name,
        antecedents=[antecedent],
        deduction=deduction,
        bindings=[(v, "miustr") for v in variables],
        matching="string",
    )


def miu_spec() -> SystemSpec:
    """A fresh :class:`SystemSpec` for the MIU system."""
    return SystemSpec(
        name="MIU",
        productions=[Production(sort="miustr", name="raw", regex="[MIU]+")],
        line=LineSpec(
            name="theorem",
            shape="<miustr> [<reference>]",
            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,]+")],
            logical_sort="miustr",
        ),
        axioms=[Rule(label="AX", name="mi axiom", antecedents=[], deduction="MI", bindings=[])],
        rules=[
            _rule("R1", "rule one", "xI", "xIU", ["x"]),
            _rule("R2", "rule two", "Mx", "Mxx", ["x"]),
            _rule("R3", "rule three", "xIIIy", "xUy", ["x", "y"]),
            _rule("R4", "rule four", "xUUy", "xy", ["x", "y"]),
        ],
    )
