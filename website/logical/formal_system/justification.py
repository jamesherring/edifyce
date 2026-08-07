"""Why a proof line checked, as data rather than as a citation.

:mod:`~.diagnostics` is this module's mirror. It says why a line did *not* go
through; a line that did carries `[imbi12d, 2, 3]` and nothing else, which names
the step without explaining it — a reader who does not already know `imbi12d`
learns from it only that *something* applied, and which lines it applied to.

What the checker established is richer, and is already on the line: the rule it
resolved the label to, that rule's own schemas, which cited line filled which
premise, the substitution the match derived, and the provisos that had to hold
over it. This assembles those into one record.

The substitution is the interesting half
----------------------------------------
A rule is a schema and a step is an instance of it, so "why does this line
follow" is answered by *what the metavariables stood for here* — which is
exactly the binding :meth:`~.rules.InferenceRule.applies` already derives and
keeps. Nothing is recomputed: this reads what the check left behind.

Two steps carry less, and say so rather than pretending otherwise. A **discharge**
rule consumes a subproof rather than cited lines, and the checker keeps no
binding for one (`check_discharge` records the rule and the verdict), so its
record names the block it consumed and offers no assignments. A **definitional**
step cites no rule at all — the checker searches the definitions in scope — so
its record is the definition that applied.

Display, not soundness
----------------------
Like :mod:`~.diagnostics` and :mod:`~..rendering`, none of this is consulted by
the checker, and none of it re-derives a verdict. A wrong record here misleads a
reader; it cannot make a false proof check, because the verdict was settled
before any of it was built.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel.definitions import Definition
from ..kernel.side_conditions import references
from ..rendering import render

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel.terms import Term
    from ..matching import Pattern
    from ..rendering import Projection
    from .proof import ProofLine
    from .rules import InferenceRule


@dataclass(frozen=True)
class Premise:
    """One antecedent of the rule, and the line that filled it.

    ``schema`` is the rule's own — what it *demands* of that slot — and the rest
    is what this step supplied. ``number`` is the citation number rather than a
    position, so it is the same thing the reader sees in the gutter; it is None
    for a premise filled from another proof, whose lines this proof does not
    number.
    """

    position: int
    schema: str
    number: int | None = None
    statement: str | None = None
    # A line the rule did not ask for and tolerated (`allow_extra_antecedents`).
    # Kept apart from the declared slots because it justifies nothing, and a
    # reader counting premises against the rule would otherwise be one out.
    extra: bool = False


@dataclass(frozen=True)
class Assignment:
    """What one of the rule's metavariables stood for on this step."""

    variable: str
    stands_for: str


@dataclass(frozen=True)
class Proviso:
    """A side-condition the step had to satisfy, and what it constrained.

    ``source`` is the author's own words where the build kept them
    (`InferenceRule.side_condition_sources`) — `x not free in phi` is what a
    reader can check, where the repr of a frozen dataclass is not.

    ``variables`` are the metavariables it mentions, so a reader can find them in
    ``Justification.assignments`` and see what the condition was actually about.
    The *instantiated* condition is deliberately not composed here: rendering one
    would mean inventing a phrasing for each of the kernel's predicates, and the
    proviso plus the assignments it names already say the same thing in the
    author's words rather than in ours.
    """

    source: str
    variables: tuple[str, ...] = ()


@dataclass(frozen=True)
class Justification:
    """The whole of why one line follows, as a reader can check it."""

    # "rule" — an inference rule or a promoted theorem, which are the same shape
    # to the checker; or "definition" for a definitional step, which cites none.
    kind: str
    label: str
    name: str
    # The rule's conclusion schema, in the system's own spelling — what it
    # concludes in general, against which the line is the instance.
    conclusion: str
    premises: tuple[Premise, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    provisos: tuple[Proviso, ...] = ()
    # The subproof a discharge rule consumed, as its schema reads. None for every
    # other kind of step, which cites lines rather than a block.
    discharges: str | None = None


def justification(
    line: ProofLine, projection: Projection | None = None
) -> Justification | None:
    """Why ``line`` checked, or None when nothing justified it.

    None covers every line a citation never resolved for: a hole, an unjustified
    line, a scope opener (which is granted rather than proved), a comment, and a
    line whose check simply failed. Each of those is a *different* thing to say,
    and :mod:`~.diagnostics` is where they are said — this answers only the
    question a justified line raises.

    ``projection`` re-spells the terms in the assignments, so a reader looking at
    a proof through a notation is shown the substitution in that same notation
    rather than in the source spelling underneath it. The rule's own schemas are
    left alone: they are stored text in the system's grammar, not terms, and are
    the "native form" a citation refers to.
    """
    definition = line.applied_definition
    if definition is not None:
        return _definitional(definition, projection)

    rule = line.inference_rule
    if rule is None:
        return None

    inference = line.inference
    binding = None if inference is None else inference.binding
    return Justification(
        kind="rule",
        label=rule.label,
        name=rule.name,
        conclusion=rule.schema_text(rule.deduction),
        premises=_premises(rule, line, projection),
        assignments=_assignments(binding, projection),
        provisos=_provisos(rule),
        discharges=_discharged(rule),
    )


def _premises(
    rule: InferenceRule, line: ProofLine, projection: Projection | None
) -> tuple[Premise, ...]:
    # Paired rather than indexed: `antecedents` is aligned to the rule's slots by
    # `_first_valid_assignment`, and a rule whose check never reached an
    # assignment has slots filled by no line at all.
    declared = [
        Premise(
            position=position,
            schema=rule.schema_text(pattern),
            number=cited.number if cited is not None else None,
            statement=_statement(cited, projection),
        )
        for position, (pattern, cited) in enumerate(
            _paired(rule.antecedents, line.antecedents)
        )
    ]
    extras = [
        Premise(
            position=len(declared) + offset,
            schema="",
            number=cited.number,
            statement=_statement(cited, projection),
            extra=True,
        )
        for offset, cited in enumerate(line.extra_antecedents)
    ]
    return tuple(declared + extras)


def _statement(line: ProofLine | None, projection: Projection | None) -> str | None:
    """A cited line's *formula*, read the way the rest of the record is read.

    Not `display`, which is the whole authored line and carries its own citation
    — quoting `a [HYP]` as the premise of a step reads as though the citation
    were part of what was proved. A line bearing no term keeps its authored text,
    since there is nothing else it could be.
    """
    if line is None:
        return None
    if line.formula_term is None:
        return line.display
    return render(line.formula_term, projection)


def _paired(
    patterns: Sequence[Pattern], cited: Sequence[ProofLine]
) -> list[tuple[Pattern, ProofLine | None]]:
    return [
        (pattern, cited[index] if index < len(cited) else None)
        for index, pattern in enumerate(patterns)
    ]


def _assignments(
    binding: dict[str, Term] | None, projection: Projection | None
) -> tuple[Assignment, ...]:
    if not binding:
        return ()
    # By name, so the same rule reads the same way on every step that uses it —
    # the binding's own order is whatever unification happened to reach first.
    return tuple(
        Assignment(variable=name, stands_for=render(binding[name], projection))
        for name in sorted(binding)
    )


def _provisos(rule: InferenceRule) -> tuple[Proviso, ...]:
    sources = rule.side_condition_sources
    return tuple(
        Proviso(
            source=sources[index] if index < len(sources) else str(condition),
            variables=tuple(sorted(references(condition))),
        )
        for index, condition in enumerate(rule.side_conditions)
    )


def _discharged(rule: InferenceRule) -> str | None:
    schema = rule.subproof_schema
    if schema is None:
        return None
    # As the engine's own vocabulary writes it — `[assume p ⊢ q]` — which is what
    # the system page already shows for a discharge rule, so the two agree.
    opener = (
        f"fresh {rule.schema_text(schema.fresh)}"
        if schema.fresh is not None
        else f"assume {rule.schema_text(schema.assumption)}"
        if schema.assumption is not None
        else ""
    )
    conclusion = rule.schema_text(schema.conclusion)
    return f"[{opener} ⊢ {conclusion}]" if opener else f"[{conclusion}]"


def _definitional(
    definition: Definition, projection: Projection | None
) -> Justification:
    # A definitional step is checked against the *kernel* definition, whose two
    # forms are terms rather than the strings a declared definition carries — so
    # this is the one place a schema is rendered rather than quoted, and the one
    # place the notation reaches a schema at all.
    label = definition.label or "Def"
    return Justification(
        kind="definition",
        label=label,
        name=label,
        conclusion=f"{render(definition.higher, projection)} ≝ "
        f"{render(definition.lower, projection)}",
    )
