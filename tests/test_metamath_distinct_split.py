"""A ``$d`` names pairs, and a definition need not be able to state all of them.

Metamath's ``$d`` is one constraint per *pair* of the variables it lists, and the
variables it may list are every mandatory ``$f`` of the assertion — which is more
than a `Definition` has names for. Two of those are nonetheless accounted for
rather than fatal, and this module pins both, together with the refusal that
survives them.

Between them they were the largest remaining refusal in `set.mm`: 92 of the 224
assertions left primitive after binding slots landed, `df-sb` and `df-mo` among
them — the two the justification mechanism was built for in the first place.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.corpus import walk
from website.logical.metamath.definitions import Classified
from website.logical.metamath.setmm import EQUIVALENCES


def classify_all(source: str, binders: dict | None = None) -> dict[str, Classified]:
    verdicts: list[Classified] = []
    checked = list(
        walk(
            parse(source),
            equivalences=EQUIVALENCES,
            classified=verdicts.append,
            binders=binders,
        )
    )
    # Every fixture here walks a theorem, so a definition the classifier admitted
    # and registration then refused shows up as a failed check rather than
    # silently as a verdict nobody acted on.
    assert all(c.verified for c in checked), [c.error for c in checked]
    return {verdict.label: verdict for verdict in verdicts}


# `df-sup`'s shape, and 90 of the 92: the defining form quantifies one spelling
# *twice*, and a `$d` names it. Binders are placed per occurrence, so `y` names two
# of them and no proviso can say which — but the pair it forms with a parameter is
# enforced by the representation whatever is written down, and the pair it forms
# with another binder is a question the kernel answers by scope.
SHARED_BINDER = r"""
$c |- wff class setvar ( ) <-> /\ A. e. NEW $.
$v x y ph ps A B $.
vx $f setvar x $.
vy $f setvar y $.
wph $f wff ph $.
wps $f wff ps $.
cA $f class A $.
cB $f class B $.
cv $a class x $.
wcel $a wff A e. B $.
wa $a wff ( ph /\ ps ) $.
wb $a wff ( ph <-> ps ) $.
wal $a wff A. x ph $.
wnew $a wff NEW A B $.
${
  $d x y A B $.
  df-new $a |- ( NEW A B <-> ( A. y y e. A /\ A. y y e. B ) ) $.
$}
ax-1 $a |- ( ph <-> ph ) $.
id $p |- ( ph <-> ph ) $= ( ax-1 ) AB $.
"""

BINDERS = {"wal": {"x": ["ph"]}}


def test_a_shared_binder_spelling_no_longer_costs_the_definition() -> None:
    classified = classify_all(SHARED_BINDER, BINDERS)["df-new"]

    assert classified.is_definition, classified.reason


def test_the_pairs_a_shared_spelling_is_in_are_the_ones_dropped() -> None:
    # Precisely: what the definition keeps is the pairs among names it can resolve.
    # `y` names two binders, so every pair it is in goes; `A` and `B` are supplied
    # by the defined form, so the pair between them stays.
    condition = classify_all(SHARED_BINDER, BINDERS)["df-new"].definition.condition

    assert condition is not None
    assert "disjoint(A, B" in condition
    assert "y" not in condition


def test_without_the_declaration_the_same_statement_is_still_an_axiom() -> None:
    # The drop is not a loosening of the shape tests: `y` is only a binder because
    # a declaration says `A.` binds. Undeclared, it is a variable the defining form
    # introduces, and that refusal comes first and still stands.
    classified = classify_all(SHARED_BINDER, None)["df-new"]

    assert not classified.is_definition
    assert "defining side introduces 'y'" in classified.reason


# `df-sb`'s shape, and the other 2: the `$d` names a `z` that appears in the `$e`
# and nowhere else. Metamath makes it mandatory because it re-proves the hypothesis
# at every use; here the hypothesis is discharged once, by citing a theorem proved
# earlier, so nothing at an unfold chooses a `z` for the `$d` to constrain.
IN_THE_OBLIGATION_ALONE = r"""
$c |- wff setvar ( ) -> <-> = A. NEW $.
$v x y z ph ps $.
vx $f setvar x $.
vy $f setvar y $.
vz $f setvar z $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wb $a wff ( ph <-> ps ) $.
weq $a wff x = x $.
wal $a wff A. x ph $.
wnew $a wff NEW ph $.
ax-1 $a |- ( ph <-> ph ) $.
${
  $d x y ph $.
  ax-cbv $a |- ( A. x ( x = x -> ph ) <-> A. y ( y = y -> ph ) ) $.
$}
${
  $d ph y z $.
  newjust $p |- ( A. y ( y = y -> ph ) <-> A. z ( z = z -> ph ) ) $= ( ax-cbv ) ABCD $.
$}
${
  $d ph y z $.
  newjust.1 $e |- ( A. y ( y = y -> ph ) <-> A. z ( z = z -> ph ) ) $.
  df-new $a |- ( NEW ph <-> A. y ( y = y -> ph ) ) $.
$}
id $p |- ( ph <-> ph ) $= ( ax-1 ) AB $.
"""


def test_a_d_over_the_obligations_own_dummy_no_longer_costs_the_definition() -> None:
    classified = classify_all(IN_THE_OBLIGATION_ALONE, BINDERS)["df-new"]

    assert classified.is_definition, classified.reason
    assert classified.definition.justification.label == "newjust"
    # `z` is not a variable of either form, so the definition states nothing about
    # it. What licences dropping it is that the citation carries it: `newjust` holds
    # under its own `$d`, and `declarative._discharge_justification` inherits those.
    condition = classified.definition.condition
    assert condition is not None and "z" not in condition
    assert "disjoint(ph, y" in condition


def test_the_same_statement_with_nothing_to_cite_is_still_an_axiom() -> None:
    # The obligation is what the argument rests on, so removing the theorem that
    # discharges it must remove the licence too — and it does, one test earlier:
    # an undischarged hypothesis is refused before the `$d` is ever looked at.
    unproved = IN_THE_OBLIGATION_ALONE.replace(
        "  newjust $p |- ( A. y ( y = y -> ph ) <-> A. z ( z = z -> ph ) ) "
        "$= ( ax-cbv ) ABCD $.\n",
        "",
    )
    classified = classify_all(unproved, BINDERS)["df-new"]

    assert not classified.is_definition
    assert "which nothing proved before it states" in classified.reason
