"""Turning a parsed Metamath database into an Edifyce system and proofs.

Three jobs, in the order an import performs them:

1. :func:`build_spec` - the **grammar**. Metamath has no parser: its syntax
   ``$a`` statements (typecode ``wff``/``class``/…) *are* the productions of the
   language, proved into place step by step. Edifyce has a grammar, so those
   become ``Production``s and the syntax steps of a proof then vanish - they are
   parsing, not reasoning, which is a large part of why an imported proof is
   shorter than the stored one.

2. :func:`promote_assertions` - the **library**. Each logical ``$a``/``$p``
   becomes a :class:`PromotedTheorem`: its statement is the conclusion, its ``$e``
   hypotheses the premises, its ``$f`` hypotheses the metavariables (so citations
   re-instantiate it), and its ``$d`` constraints ``disjoint`` provisos. Metamath
   applies axioms and proved theorems identically, and so does this.

3. :func:`import_proof` - the **proof**. Runs the compressed proof's stack machine
   and emits Edifyce proof text: one line per *logical* step, citing the theorem
   applied and the lines filling its premises. The result is checked by Edifyce's
   own kernel - nothing here re-verifies, which is the point.

What is deliberately not attempted: definition classification (every logical
``$a`` imports as an axiom, never a ``Define``), and any grammar beyond what the
syntax axioms state.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..compiler import promote_from_source
from ..declarative import LinePart, LineSpec, Production, SystemSpec, build_system
from ..formal_system import FormalSystem
from . import compressed
from .parser import Assertion, Database, Hypothesis, MetamathError

# Metamath labels admit letters, digits, and `-_.`; a citation adds the line
# numbers and separators Edifyce's reference syntax uses.
_REFERENCE_REGEX = r"[A-Za-z0-9_.\-, ]+"


@dataclass
class _Entry:
    """One stack cell: an expression, and where it was emitted if it is logical."""

    typecode: str
    tokens: tuple[str, ...]
    line: int | None = None


def build_spec(database: Database, name: str = "Metamath") -> SystemSpec:
    """Build the Edifyce grammar declared by ``database``'s syntax axioms."""
    productions: list[Production] = []

    for assertion in database.syntax_assertions():
        bindings = [(h.variable, h.typecode) for h in assertion.floatings]
        text = " ".join(assertion.tokens)

        if bindings:
            productions.append(
                Production(
                    sort=assertion.typecode,
                    name=assertion.label,
                    template=text,
                    bindings=bindings,
                )
            )
        else:
            # No variables: a constant of its sort (`c2 $a class 2`).
            productions.append(
                Production(sort=assertion.typecode, name=assertion.label, atom_value=text)
            )

    logical_sort = _logical_sort(database)

    return SystemSpec(
        name=name,
        brackets=[("(", ")")],
        productions=productions,
        lines=[
            LineSpec(
                name="statement",
                shape=f"<{logical_sort}> [<reference>]",
                parts=[LinePart(name="reference", regex=_REFERENCE_REGEX)],
                logical_sort=logical_sort,
            )
        ],
    )


def _logical_sort(database: Database) -> str:
    # The sort a `|-` statement is written in. Metamath does not say so directly:
    # the assertion typecode `|-` is not itself a grammar sort, so infer it from
    # the syntax axioms - conventionally `wff`, but read rather than assumed.
    sorts = [a.typecode for a in database.syntax_assertions()]
    for candidate in ("wff", "formula"):
        if candidate in sorts:
            return candidate
    if not sorts:
        raise MetamathError("Database declares no syntax axioms, so it has no grammar.")
    return sorts[0]


def promote_assertions(database: Database, system: FormalSystem) -> None:
    """Register every logical assertion of ``database`` on ``system``."""
    for assertion in database.logical_assertions():
        system.promote(promoted_theorem(assertion, system))


def promoted_theorem(assertion: Assertion, system: FormalSystem):
    """Promote one logical ``$a``/``$p`` to a citable schematic theorem."""
    return promote_from_source(
        system,
        label=assertion.label,
        statement=" ".join(assertion.tokens),
        metavariables={h.variable: h.typecode for h in assertion.floatings},
        premises=tuple(" ".join(h.tokens) for h in assertion.essentials),
        distinct=_distinct_provisos(assertion),
    )


def _distinct_provisos(assertion: Assertion) -> tuple[str, ...]:
    # A `$d x y z` constrains every *pair* among its variables, and Edifyce's
    # algebra takes one pair per proviso, so expand. Only variables the assertion
    # actually binds are kept: a $d naming something outside its metavariables
    # would fail to resolve, and constrains nothing here anyway.
    bound = {h.variable for h in assertion.floatings}
    provisos: list[str] = []
    for group in assertion.distinct:
        members = sorted(v for v in group if v in bound)
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                proviso = f"disjoint({left}, {right})"
                if proviso not in provisos:
                    provisos.append(proviso)
    return tuple(provisos)


def import_proof(database: Database, label: str) -> str:
    """Render the Edifyce proof text for ``label``'s compressed Metamath proof.

    One line per *logical* step; syntax steps build expressions and emit nothing,
    since Edifyce parses well-formedness rather than proving it.
    """
    assertion = database.assertions.get(label)
    if assertion is None:
        raise MetamathError(f"No assertion labelled {label!r}.")
    if not assertion.proof:
        raise MetamathError(f"{label} has no proof (is it a $a?).")

    labels, letters = compressed.split_proof(assertion.proof)
    steps = compressed.decode(letters, labels, assertion.mandatory)

    stack: list[_Entry] = []
    saved: list[_Entry] = []
    lines: list[str] = []

    for step in steps:
        if step.backreference is not None:
            if step.backreference >= len(saved):
                raise MetamathError(f"{label}: backreference to an unsaved step.")
            entry = saved[step.backreference]

        elif step.hypothesis is not None:
            entry = _push_hypothesis(step.hypothesis, lines)

        else:
            entry = _apply(step.label, database, stack, lines, label)

        stack.append(entry)
        if step.saved:
            saved.append(entry)

    if len(stack) != 1:
        raise MetamathError(
            f"{label}: proof ends with {len(stack)} stack entries, expected exactly 1."
        )

    return "\n".join(lines)


def _push_hypothesis(hypothesis: Hypothesis, lines: list[str]) -> _Entry:
    # A mandatory hypothesis of the theorem being proved. A floating one stands
    # for its variable; an essential one is a premise, which the imported proof
    # states as a line justified by the hypothesis label itself.
    if hypothesis.floating:
        return _Entry(typecode=hypothesis.typecode, tokens=(hypothesis.variable,))

    lines.append(f"{' '.join(hypothesis.tokens)} [{hypothesis.label}]")
    return _Entry(
        typecode=hypothesis.typecode, tokens=hypothesis.tokens, line=len(lines)
    )


def _apply(
    step_label: str | None,
    database: Database,
    stack: list[_Entry],
    lines: list[str],
    proving: str,
) -> _Entry:
    # Apply a label from the proof's table: pop its mandatory hypotheses, read the
    # substitution off the floating ones and the cited lines off the essential
    # ones, then push its statement under that substitution.
    if step_label is None:
        raise MetamathError(f"{proving}: proof step selects nothing.")

    hypothesis = database.hypotheses.get(step_label)
    if hypothesis is not None:
        return _push_hypothesis(hypothesis, lines)

    assertion = database.assertions.get(step_label)
    if assertion is None:
        raise MetamathError(f"{proving}: proof cites unknown label {step_label!r}.")

    arity = len(assertion.mandatory)
    if arity > len(stack):
        raise MetamathError(
            f"{proving}: applying {step_label} needs {arity} stack entries, "
            f"found {len(stack)}."
        )

    popped = stack[len(stack) - arity:] if arity else []
    del stack[len(stack) - arity:]

    substitution: dict[str, tuple[str, ...]] = {}
    cited: list[int] = []
    for hypothesis_slot, entry in zip(assertion.mandatory, popped):
        if hypothesis_slot.floating:
            substitution[hypothesis_slot.variable] = entry.tokens
        elif entry.line is not None:
            cited.append(entry.line)

    tokens = _substitute(assertion.tokens, substitution)

    if not assertion.is_logical:
        # A syntax step: it built an expression, not a claim. No proof line.
        return _Entry(typecode=assertion.typecode, tokens=tokens)

    reference = ", ".join([step_label, *(str(n) for n in cited)])
    lines.append(f"{' '.join(tokens)} [{reference}]")
    return _Entry(typecode=assertion.typecode, tokens=tokens, line=len(lines))


def _substitute(
    tokens: tuple[str, ...], substitution: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    out: list[str] = []
    for token in tokens:
        out.extend(substitution.get(token, (token,)))
    return tuple(out)


def import_database(database: Database, name: str = "Metamath") -> FormalSystem:
    """Build a system from ``database`` with every logical assertion promoted."""
    system = build_system(build_spec(database, name))
    promote_assertions(database, system)
    return system
