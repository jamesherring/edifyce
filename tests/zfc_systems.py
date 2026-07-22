"""Edifyce source for the ZFC-style system used by the proof tests.

``SCOPED_ZFC`` is a first-order natural-deduction system (membership ``∈``,
implication ``→``, negation ``¬``, universal ``∀``) built on the scoped-subproof
engine: a single ``scope: assumption`` line type, first-class subproofs,
discharge rules that consume a subproof as a unit, and a freshness side-condition
for ``∀I``. See ``tests/test_zfc_scoped.py``.
"""

# ---------------------------------------------------------------------------
# Shared first-order language fragment (identical text in both systems).
# ---------------------------------------------------------------------------
_LANGUAGE = r"""
    Regex setvar:
        ^[a-z][a-z0-9]*$

    UnionPattern formula:
        membership

    Pattern membership:
        with x as setvar, y as setvar:
            x ∈ y

    Pattern implication:
        with p as formula, q as formula:
            (p → q)

    Pattern negation:
        with p as formula:
            ¬p

    Pattern universal:
        with x as setvar, p as formula:
            ∀x p

    formula:
        membership
        implication
        negation
        universal

    Regex reference:
        ^[A-Za-z0-9, ]+$

    Pattern statement:
        with f as formula, r as reference:
            f [r]
"""


SCOPED_ZFC = (
    "FormalSystem ScopedZFC:\n"
    + _LANGUAGE
    + r"""
    Pattern assumption_pattern:
        with phi as formula:
            assume phi

    Pattern variable_pattern:
        with x as setvar:
            let x

    LineType claim:
        pattern: statement
        behaviour: logical
        formula: f
        reference: r

    LineType assume:
        pattern: assumption_pattern
        behaviour: logical
        scope: assumption
        formula: phi

    LineType introduce:
        pattern: variable_pattern
        behaviour: logical
        scope: variable
        formula: x

    with p as formula, q as formula, x as setvar:

        InferenceRule reiteration:
            label:
                R
            antecedents:
                p
            deduction:
                p

        InferenceRule modus_ponens:
            label:
                MP
            antecedents:
                p
                (p → q)
            deduction:
                q

        InferenceRule conditional_proof:
            label:
                CP
            subproof:
                assume:
                    p
                derive:
                    q
            deduction:
                (p → q)

        InferenceRule universal_generalisation:
            label:
                UG
            subproof:
                fresh:
                    x
                derive:
                    p
            deduction:
                ∀x p
"""
)
