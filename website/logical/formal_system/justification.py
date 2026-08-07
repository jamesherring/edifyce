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
from ..kernel.terms import bound_label
from ..rendering import render
from .rules import ANONYMOUS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..matching import Pattern
    from ..rendering import Projection
    from .proof import ProofLine
    from .rules import Inference, InferenceRule


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
    return Justification(
        kind="rule",
        label=rule.label,
        name=rule.name,
        conclusion=rule.schema_text(rule.deduction),
        premises=_premises(rule, line, projection),
        assignments=_assignments(inference, projection),
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
            number=_local_number(cited, line),
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
            number=_local_number(cited, line),
            statement=_statement(cited, projection),
            extra=True,
        )
        for offset, cited in enumerate(line.extra_antecedents)
    ]
    return tuple(declared + extras)


def _local_number(cited: ProofLine | None, deduction: ProofLine) -> int | None:
    """The citation number ``deduction``'s own reader can follow, or None.

    A premise may be filled from a **cited lemma** (`[alias.1]`), whose lines are
    numbered within that proof and not this one. Reporting its number would point
    a reader at this proof's line of that number, which is some unrelated step —
    so a premise from elsewhere carries the statement and no number.
    """
    if cited is None or cited.proof is not deduction.proof:
        return None
    return cited.number


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
    inference: Inference | None, projection: Projection | None
) -> tuple[Assignment, ...]:
    """What the rule's metavariables stood for, whichever kind of match it was.

    A **term** step binds terms, which a notation re-spells. A **string-rewriting**
    step (MIU and its kind) binds surface strings by associative matching, and the
    checker keeps that substitution apart from the term one precisely so nothing
    meaning terms reads it — but it is the same question to a reader, and the one
    thing a rewriting rule's citation cannot say. A string is already its own
    surface form, so no projection applies to it.

    Named metavariables only. A bare-sort slot (`formula` meaning "any formula")
    has no name to share by, so the schema projection renames each occurrence
    apart — `formula\x000` — and that name appears in no schema and no proviso the
    reader is shown beside it. What filled such a slot is the premise row, which
    names the line.

    By name, so the same rule reads the same way on every step that uses it: a
    binding's own order is whatever the match happened to reach first.
    """
    if inference is None:
        return ()
    if inference.binding:
        read = {
            name: render(term, projection)
            for name, term in inference.binding.items()
        }
    else:
        read = dict(inference.string_binding or {})
    return tuple(
        Assignment(variable=name, stands_for=read[name])
        for name in sorted(read)
        if ANONYMOUS not in name
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
    """The definition a `[Def, n]` step applied, as its two forms read.

    A definitional step is checked against the *kernel* definition, whose forms
    are terms rather than the strings a declared definition carries — so this is
    the one place a schema is rendered rather than quoted.

    The defining form stores its binders **abstractly**, by index, because an
    unfold's consumer chooses each one's concrete name. A reader is not that
    consumer, so the declared name goes back where the index sits; without it
    `x ⊆ y` reads as `∀⟨0⟩ (⟨0⟩ ∈ x → ⟨0⟩ ∈ y)`, which names nothing.

    ``label`` is empty for an unlabelled definition rather than a stand-in like
    "Def": that keyword is how a *citation* reaches one, and putting it here would
    hand a caller a label to look prose or a proof up by that names no definition
    at all.
    """
    binders = {
        bound_label(index): render(binder.default, projection)
        for index, binder in enumerate(definition.fresh)
    }
    label = definition.label or ""
    return Justification(
        kind="definition",
        label=label,
        name=label,
        conclusion=f"{render(definition.higher, projection)} ≝ "
        f"{render(definition.lower, projection, binders)}",
    )
