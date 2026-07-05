"""Edifyce source for the ZFC-style systems used by the proof tests.

Two systems over the *same* first-order language (membership ``∈``,
implication ``→``, negation ``¬``, universal ``∀``):

``LEGACY_ZFC``
    Natural deduction built with the pre-existing engine: assumptions live in
    a ``given`` :class:`MatchSet`, opened by a ``behaviour: indent`` line, and
    discharge rules (``→I``) cite the assumption line and the conclusion line
    *individually*. References are not scope-checked, so this system is
    unsound - see ``tests/test_zfc_legacy.py``.

``SCOPED_ZFC``
    The same language and theorems, rebuilt on the scoped-subproof engine:
    a single ``scope: assumption`` line type, first-class subproofs, discharge
    rules that consume a subproof as a unit, and a freshness side-condition for
    ``∀I``. Sound - see ``tests/test_zfc_scoped.py``.

Keeping both here lets the two test modules share one source of truth and lets
the write-up diff them directly.
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

    statement.formula():
        return self.f

    statement.reference():
        return self.r
"""


# ---------------------------------------------------------------------------
# Legacy system: assumptions via `indent` + `given`, discharge by line refs.
# ---------------------------------------------------------------------------
LEGACY_ZFC = (
    "FormalSystem LegacyZFC:\n"
    + _LANGUAGE
    + r"""
    ProofContext:
        given: MatchSet()

    Pattern assume_pattern:
        with phi as formula:
            assume phi:

    assume_pattern.formula():
        return self.phi

    LineType claim:
        pattern: statement
        behaviour: logical

    LineType assume:
        pattern: assume_pattern
        behaviour: indent
        context.given:
            add: formula()

    with p as formula, q as formula:

        InferenceRule hypothesis:
            label:
                HYP
            deduction:
                p
            condition:
                deduction.formula() in given

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
            antecedents:
                assume_pattern
                q
            deduction:
                (p → q)
"""
)


# ---------------------------------------------------------------------------
# Scoped system: one `scope: assumption` line type, first-class subproofs,
# discharge rules that consume a whole subproof, freshness for ∀I.
# ---------------------------------------------------------------------------
SCOPED_ZFC = (
    "FormalSystem ScopedZFC:\n"
    + _LANGUAGE
    + r"""
    Pattern assumption_pattern:
        with phi as formula:
            assume phi

    assumption_pattern.formula():
        return self.phi

    Pattern variable_pattern:
        with x as setvar:
            let x

    variable_pattern.formula():
        return self.x

    LineType claim:
        pattern: statement
        behaviour: logical

    LineType assume:
        pattern: assumption_pattern
        behaviour: logical
        scope: assumption

    LineType introduce:
        pattern: variable_pattern
        behaviour: logical
        scope: variable

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
