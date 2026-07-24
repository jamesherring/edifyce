"""Promoting a proved/imported theorem to a reusable schematic rule.

A proved theorem is reused exactly as an inference rule is: its metavariables are
re-instantiated at each citation by unification, subject to its distinct-variable
provisos. To the checker a rule and a schematic theorem are the same shape -
premises + conclusion + side-conditions over metavariables (see
``docs/setmm-import-recommendations-detail.md``, section A1).

A :class:`PromotedTheorem` records that schematic statement *without* placing it
in the system's primitive ``inference_rules``: derived theorems - tens of
thousands of them on a set.mm import - stay in their own namespace, and the
reference resolver builds the ephemeral :class:`InferenceRule` a citation is
checked against on demand (:meth:`PromotedTheorem.as_rule`). Nothing per-theorem
is persisted as a rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .rules import InferenceRule

if TYPE_CHECKING:
    from ..kernel import SideCondition
    from ..matching.patterns import Pattern


@dataclass(frozen=True)
class PromotedTheorem:
    """A proved/imported theorem registered for schematic reuse.

    ``deduction`` and ``antecedents`` are rule-shaped schema patterns (each
    carrying a precomputed ``schema_term`` - the nested kernel term the checker
    unifies against). ``side_conditions`` are the theorem's provisos: a Metamath
    ``$d`` becomes a ``disjoint`` predicate, enforced under the citation's binding
    so a capturing substitution is rejected. ``variables`` maps each metavariable
    name to its sort.

    :meth:`as_rule` wraps these in an ephemeral :class:`InferenceRule` - the same
    object an authored rule is, so ``InferenceRule.check`` (unification of the
    schema terms plus the side-condition check) applies unchanged.
    """

    label: str
    deduction: Pattern
    antecedents: tuple[Pattern, ...] = ()
    side_conditions: tuple[SideCondition, ...] = ()
    variables: dict[str, Pattern] = field(default_factory=dict)

    def as_rule(self) -> InferenceRule:
        """Build the ephemeral rule a citation of this theorem is checked against."""
        return InferenceRule(
            name=self.label,
            label=self.label,
            antecedents=list(self.antecedents),
            deduction=self.deduction,
            side_conditions=list(self.side_conditions),
            variables=dict(self.variables),
        )
