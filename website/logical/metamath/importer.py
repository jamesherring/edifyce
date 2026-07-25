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

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..compiler import promote_from_source
from ..declarative import LinePart, LineSpec, Production, SystemSpec, build_system
from ..formal_system import FormalSystem
from . import compressed
from .parser import Assertion, Database, Hypothesis, MetamathError

if TYPE_CHECKING:
    from ..formal_system import PromotedTheorem

# Metamath labels admit letters, digits, and `-_.`; a citation adds the line
# numbers and separators Edifyce's reference syntax uses.
_REFERENCE_REGEX = r"[A-Za-z0-9_.\-, ]+"


@dataclass
class _Entry:
    """One stack cell: an expression, and where it was emitted if it is logical."""

    typecode: str
    tokens: tuple[str, ...]
    line: int | None = None


def build_spec(
    database: Database, name: str = "Metamath", before: str | None = None
) -> SystemSpec:
    """Build the Edifyce grammar declared by ``database``'s syntax axioms.

    ``before`` stops at that label, exclusive. Rejecting forward *citations* is
    not enough on its own: a syntax step never reaches the kernel, so if the
    grammar carries notation declared later, a proof's lines can be *parsed*
    using it even though nothing cites it - and what the kernel then checks
    depends on notation that did not exist yet. set.mm makes this concrete: the
    mathbox theorem `bj-0` overlaps the nesting of `wi`, and without this limit
    it captures the parse of formulas in theorems 600k lines earlier.
    """
    productions: list[Production] = []

    for assertion in _syntax_before(database, before):
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

    productions.extend(_variable_sort_productions(database, before))
    logical_sort = _logical_sort(database, before)

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


def _syntax_before(database: Database, before: str | None) -> list[Assertion]:
    # The notation-declaring statements available to `before`, in file order.
    syntax = database.syntax_assertions()
    if before is None:
        return list(syntax)
    limit = database.position(before)
    return [a for a in syntax if database.position(a.label) < limit]


def _mentioned_variables(database: Database, before: str | None) -> set[str]:
    # The variables that can appear in statements available to `before` - its own
    # included. Restricting to these keeps the grammar proportionate: set.mm
    # declares 355 variables, and enumerating all of them in every sort's leaf
    # pattern makes a regex too large to store, while only a handful are ever
    # reachable from a given theorem.
    limit = len(database.order) if before is None else database.position(before) + 1
    mentioned: set[str] = set()
    for label in database.order[:limit]:
        assertion = database.assertions[label]
        mentioned.update(t for t in assertion.tokens if t in database.variables)
        for hypothesis in assertion.mandatory:
            mentioned.update(t for t in hypothesis.tokens if t in database.variables)
    return mentioned


def _declared_variables(
    database: Database, before: str | None = None
) -> dict[str, list[str]]:
    # Every `$f`-declared typecode, mapped to the variables inhabiting it. A
    # variable is a member of its sort in its own right - `wph $f wff ph` makes a
    # bare `ph` a wff - so this holds for sorts that *also* have syntax axioms,
    # not only for variable-only ones.
    mentioned = _mentioned_variables(database, before)
    sorts: dict[str, list[str]] = {}
    for hypothesis in database.hypotheses.values():
        if not hypothesis.floating or hypothesis.variable not in mentioned:
            continue
        members = sorts.setdefault(hypothesis.typecode, [])
        if hypothesis.variable not in members:
            members.append(hypothesis.variable)
    return sorts


def _binder_sorts(database: Database) -> list[str]:
    # `$f` typecodes built by no syntax axiom at all - set.mm's `setvar`, whose
    # only members *are* the declared variables. These are the individual-variable
    # sorts, which is what a `$d` constrains (see _distinct_provisos).
    built = {a.typecode for a in database.syntax_assertions()}
    return [t for t in database.floating_typecodes() if t not in built]


def _variable_sort_productions(
    database: Database, before: str | None = None
) -> list[Production]:
    # A leaf production per sort carrying the variables declared for it. Anchored
    # alternation rather than a general identifier pattern, so a sort admits the
    # variables the database declares and nothing else. Without these a bare
    # variable does not parse as its sort, and any statement mentioning one - every
    # `$e` hypothesis, most schemas - fails to read.
    return [
        Production(
            sort=typecode,
            name=f"{typecode}_var",
            regex="(?:" + "|".join(re.escape(v) for v in sorted(members)) + ")",
        )
        for typecode, members in _declared_variables(database, before).items()
    ]


def _logical_sort(database: Database, before: str | None = None) -> str:
    # The sort a `|-` statement is written in. Metamath does not say so directly:
    # the assertion typecode `|-` is not itself a grammar sort, so infer it from
    # the syntax axioms - conventionally `wff`, but read rather than assumed.
    sorts = [a.typecode for a in _syntax_before(database, before)]
    for candidate in ("wff", "formula"):
        if candidate in sorts:
            return candidate
    if not sorts:
        raise MetamathError("Database declares no syntax axioms, so it has no grammar.")
    return sorts[0]


def promote_assertions(
    database: Database, system: FormalSystem, before: str | None = None
) -> None:
    """Register ``database``'s logical assertions on ``system``.

    ``before`` stops at that label, exclusive. A proof may only cite what
    *precedes* it, so checking one theorem must not have that theorem - nor
    anything later - already promoted, or it could justify itself.
    """
    for assertion in database.logical_assertions():
        if assertion.label == before:
            return
        system.promote(promoted_theorem(assertion, database, system))


def promoted_theorem(
    assertion: Assertion, database: Database, system: FormalSystem
) -> PromotedTheorem:
    """Promote one logical ``$a``/``$p`` to a citable schematic theorem."""
    return promote_from_source(
        system,
        label=assertion.label,
        statement=" ".join(assertion.tokens),
        metavariables={h.variable: h.typecode for h in assertion.floatings},
        premises=tuple(" ".join(h.tokens) for h in assertion.essentials),
        distinct=_distinct_provisos(assertion, database),
    )


def _distinct_provisos(assertion: Assertion, database: Database) -> tuple[str, ...]:
    # A `$d x y z` constrains every *pair* among its variables, and Edifyce's
    # algebra takes one pair per proviso, so expand. Only variables the assertion
    # actually binds are kept: a $d naming something outside its metavariables
    # would fail to resolve, and constrains nothing here anyway.
    #
    # The proviso is *sort-restricted* to the variable sort (set.mm's `setvar`).
    # `$d` forbids the substitutions sharing a **variable**, not any leaf at all:
    # sortless `disjoint(A, B)` also separates constants, so it would reject
    # `RR = RR` under `$d A B`, which Metamath permits. Where the variable sort
    # cannot be identified the sort is omitted, which is over-strict - it can
    # reject a legitimate proof, never accept an illegitimate one.
    variable_sorts = _binder_sorts(database)
    sort = f", {variable_sorts[0]}" if len(variable_sorts) == 1 else ""

    bound = {h.variable for h in assertion.floatings}
    provisos: list[str] = []
    for group in assertion.distinct:
        members = sorted(v for v in group if v in bound)
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                proviso = f"disjoint({left}, {right}{sort})"
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
    _reject_forward_citations(assertion, labels, database)
    steps = compressed.decode(letters, labels, assertion.mandatory)

    stack: list[_Entry] = []
    saved: list[_Entry] = []
    lines: list[str] = []
    premises: dict[str, _Entry] = {}

    for step in steps:
        if step.backreference is not None:
            if step.backreference >= len(saved):
                raise MetamathError(f"{label}: backreference to an unsaved step.")
            entry = saved[step.backreference]

        elif step.hypothesis is not None:
            entry = _push_hypothesis(step.hypothesis, lines, premises)

        else:
            entry = _apply(step.label, database, stack, lines, premises, label)

        stack.append(entry)
        if step.saved:
            saved.append(entry)

    if len(stack) != 1:
        raise MetamathError(
            f"{label}: proof ends with {len(stack)} stack entries, expected exactly 1."
        )

    # The proof must actually reach what the theorem claims. Without this a proof
    # that terminates on *some* well-formed result imports cleanly and its lines
    # check - but they establish a different statement, while the theorem is still
    # promoted under its declared one. A green import has to mean the declared
    # statement was derived.
    concluded = stack[0]
    if concluded.tokens != assertion.tokens or concluded.typecode != assertion.typecode:
        raise MetamathError(
            f"{label}: proof concludes "
            f"{concluded.typecode} {' '.join(concluded.tokens)!r}, "
            f"but the statement is {assertion.typecode} {' '.join(assertion.tokens)!r}."
        )

    return "\n".join(lines)


def _reject_forward_citations(
    assertion: Assertion, labels: list[str], database: Database
) -> None:
    # A Metamath proof may cite only what is *active and earlier*. Promoting just
    # the preceding logical assertions is not enough to enforce that, because a
    # syntax step never reaches the kernel: `_apply` folds it into the expression
    # it builds, so a proof citing notation introduced *after* the theorem would
    # translate to a line the kernel happily checks against a grammar that was
    # built from the whole database. Enforce the ordering on the proof table
    # itself, where it covers syntax and logic alike.
    position = {label: index for index, label in enumerate(database.order)}
    limit = position[assertion.label]

    for label in labels:
        if label in database.hypotheses:
            if label not in assertion.active_hypotheses:
                raise MetamathError(
                    f"{assertion.label}: proof cites hypothesis {label!r}, "
                    "which is not in scope for it."
                )
            continue

        cited = position.get(label)
        if cited is None:
            raise MetamathError(
                f"{assertion.label}: proof cites unknown label {label!r}."
            )
        if cited >= limit:
            raise MetamathError(
                f"{assertion.label}: proof cites {label!r}, which is declared later "
                "- a proof may only use what precedes it."
            )


def _push_hypothesis(
    hypothesis: Hypothesis, lines: list[str], premises: dict[str, _Entry]
) -> _Entry:
    # A mandatory hypothesis of the theorem being proved. A floating one stands
    # for its variable; an essential one is a premise of the proof, stated once as
    # a line justified by the hypothesis label (which import_theorem registers as
    # a given). Compressed proofs re-select band-1 hypotheses by letter rather
    # than Z-saving them, so the same premise is pushed repeatedly - emit it once
    # and cite that line again.
    if hypothesis.floating:
        return _Entry(typecode=hypothesis.typecode, tokens=(hypothesis.variable,))

    existing = premises.get(hypothesis.label)
    if existing is not None:
        return existing

    lines.append(f"{' '.join(hypothesis.tokens)} [{hypothesis.label}]")
    entry = _Entry(
        typecode=hypothesis.typecode, tokens=hypothesis.tokens, line=len(lines)
    )
    premises[hypothesis.label] = entry
    return entry


def _apply(
    step_label: str | None,
    database: Database,
    stack: list[_Entry],
    lines: list[str],
    premises: dict[str, _Entry],
    proving: str,
) -> _Entry:
    # Apply a label from the proof's table: pop its mandatory hypotheses, read the
    # substitution off the floating ones and the cited lines off the essential
    # ones, then push its statement under that substitution.
    if step_label is None:
        raise MetamathError(f"{proving}: proof step selects nothing.")

    hypothesis = database.hypotheses.get(step_label)
    if hypothesis is not None:
        return _push_hypothesis(hypothesis, lines, premises)

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


def import_theorem(
    database: Database, label: str, name: str = "Metamath"
) -> tuple[FormalSystem, str]:
    """A system for checking ``label``'s proof, and that proof's Edifyce text.

    Scoped exactly as Metamath scopes a ``${ … $}`` block, which is what makes the
    check meaningful:

    * only assertions *preceding* ``label`` are promoted, so the theorem cannot
      justify itself and cannot reach forward;
    * ``label``'s own ``$e`` hypotheses are registered as givens, so the premise
      lines the proof states resolve. They are assumptions of *this* proof, which
      is why the system is built per theorem rather than shared.
    """
    assertion = database.assertions.get(label)
    if assertion is None:
        raise MetamathError(f"No assertion labelled {label!r}.")

    system = build_system(build_spec(database, name, before=label))
    promote_assertions(database, system, before=label)

    metavariables = {h.variable: h.typecode for h in assertion.floatings}
    for hypothesis in assertion.essentials:
        system.promote(
            promote_from_source(
                system,
                label=hypothesis.label,
                statement=" ".join(hypothesis.tokens),
                metavariables=metavariables,
            )
        )

    return system, import_proof(database, label)
