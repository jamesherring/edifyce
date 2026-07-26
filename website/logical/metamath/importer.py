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

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..promotion import promote_from_source
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
        tokens, bindings = _uncollide(
            assertion.tokens, [(h.variable, h.typecode) for h in assertion.floatings]
        )
        text = " ".join(tokens)

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
            # No variables: a constant of its sort (`c2 $a class 2`). Metamath
            # declares the object-language role Edifyce asks for rather than
            # leaving it to be guessed - the token comes from a `$c`, never a
            # `$v`, and the two are disjoint - so say so. Nothing reads it until
            # a definition is built over the token (see Production), which is
            # what an imported `df-` will be.
            productions.append(
                Production(
                    sort=assertion.typecode,
                    name=assertion.label,
                    atom_value=text,
                    denotes_constant=True,
                )
            )

    productions.extend(_variable_productions(database, before))
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


def _uncollide(
    tokens: tuple[str, ...], bindings: list[tuple[str, str]]
) -> tuple[tuple[str, ...], list[tuple[str, str]]]:
    # Rename a production's variable when its name also occurs *inside* one of the
    # template's constants, and give back the rewritten tokens and bindings.
    #
    # A production template is a string, and its variables are located by scanning
    # for their names at every character offset - so a variable whose name is a
    # prefix of a constant is found inside that constant too. Metamath's set.mm
    # does this the moment it quantifies: `wral` is `A. x e. A ph`, where `A.` is
    # the universal quantifier and `A` a class variable. Scanned as text, `A` is
    # found at offset 0 as well, and the production then demands the *same* class
    # in both places - so `A. x e. A ph` parses and `A. y e. B ph` does not. On a
    # set.mm import that silently invalidates every restricted quantification.
    #
    # Metamath is tokenised on whitespace, so the two readings are tellable apart
    # here even though the string matcher cannot tell them apart later: a variable
    # occurring more often as a substring than as a token is colliding. The
    # variable's *name* is private to the production - a formula binds it by
    # position, not by name - so renaming it changes no surface syntax. This is
    # the same remedy `Match.create_pattern` applies to a definition's defined
    # form, which reaches it by comparing string against tree occurrences.
    renamed: dict[str, str] = {}
    for variable, _sort in bindings:
        occurrences = sum(1 for token in tokens if token == variable)
        if sum(token.count(variable) for token in tokens) == occurrences:
            continue

        index = 0
        while True:
            candidate = f"{variable}_{index}"
            taken = any(candidate in token for token in tokens) or any(
                candidate == name for name, _ in bindings
            )
            if not taken and candidate not in renamed.values():
                renamed[variable] = candidate
                break
            index += 1

    if not renamed:
        return tokens, bindings

    return (
        tuple(renamed.get(token, token) for token in tokens),
        [(renamed.get(name, name), sort) for name, sort in bindings],
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
    #
    # A statement's own tokens and its *mandatory* hypotheses are not the whole
    # of it. A proof may also use a variable from an **optional** floating
    # hypothesis - one active where the theorem sits but mentioned by nothing it
    # states - as a dummy, and Metamath permits that. The intermediate lines then
    # carry a variable the grammar has no leaf for, and an otherwise valid proof
    # fails to parse: 14 of set.mm's theorems do this, `ax7` among them. So take
    # the variables of every *active* hypothesis, which is exactly the set a
    # proof at this point is allowed to cite.
    limit = len(database.order) if before is None else database.position(before) + 1
    mentioned: set[str] = set()
    for label in database.order[:limit]:
        assertion = database.assertions[label]
        mentioned.update(t for t in assertion.tokens if t in database.variables)
        for hypothesis_label in assertion.active_hypotheses:
            hypothesis = database.hypotheses[hypothesis_label]
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
    built = database.syntax_typecodes()
    return [t for t in database.floating_typecodes() if t not in built]


def variable_production_name(database: Database, typecode: str, variable: str) -> str:
    """The production name carrying `variable` as a leaf of sort `typecode`.

    Metamath keeps labels and variable names in separate namespaces; Edifyce
    resolves productions out of one, so a name that collides with an assertion
    label would silently rebind it. Salt until free rather than trusting that no
    `set.mm`-alike ever labels a theorem `wff_var_ph`.
    """
    name = f"{typecode}_var_{variable}"
    while name in database.assertions:
        name += "_"
    return name


def _variable_productions(
    database: Database, before: str | None = None
) -> list[Production]:
    # A sub-sort `<typecode>_var` per typecode, holding one atom leaf per declared
    # variable, and included into the typecode's own sort. Without these a bare
    # variable does not parse as its sort, and any statement mentioning one - every
    # `$e` hypothesis, most schemas - fails to read.
    #
    # One leaf *each*, rather than a single regex leaf alternating over all of
    # them, because a sort's variables have to be able to grow. The corpus pass
    # adds notation as the walk reaches it and must add variables the same way
    # (see `walk`), and an alternation cannot be extended in place: a regex leaf's
    # kernel constructor is identified by its regex *text* (`kernel.constructors`),
    # so rewriting it would split one variable into two non-interchangeable terms
    # either side of the rewrite. An atom is identified by its own token, and joins
    # a sort through `add_pattern` - the mechanism notation already grows through.
    #
    # The sub-sort is what keeps `$d` expressible. A proviso restricts to the
    # leaves that *are* variables (`_distinct_provisos`), and with the variables
    # spread over the typecode's own sort there would be no name for just those -
    # `disjoint(A, B, class)` would wrongly separate constants like `RR` too.
    #
    # `denotes_constant` is left False: these are `$v` variables, the things a
    # binder binds, as opposed to the `$c`-derived nullary constants above.
    productions: list[Production] = []
    for typecode, members in _declared_variables(database, before).items():
        sort = f"{typecode}_var"
        productions.extend(
            Production(
                sort=sort,
                name=variable_production_name(database, typecode, variable),
                atom_value=variable,
            )
            for variable in members
        )
        # Shapeless: a production naming another sort *includes* that sort, so a
        # variable reads as its typecode as well as as a variable.
        productions.append(Production(sort=typecode, name=sort))
    return productions


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
    rename = _proviso_safe_names(assertion)
    substitute = (lambda tokens: tuple(rename.get(t, t) for t in tokens)) if rename else tuple

    return promote_from_source(
        system,
        label=assertion.label,
        statement=" ".join(substitute(assertion.tokens)),
        metavariables={
            rename.get(h.variable, h.variable): h.typecode for h in assertion.floatings
        },
        premises=tuple(" ".join(substitute(h.tokens)) for h in assertion.essentials),
        distinct=_distinct_provisos(assertion, database, system, rename),
    )


def _proviso_safe_names(assertion: Assertion) -> dict[str, str]:
    # Rename a metavariable whose name contains the character a proviso uses to
    # separate its arguments, and give back the mapping.
    #
    # `disjoint(left, right, sort)` is read by splitting on top-level commas, so
    # a metavariable with a comma *in its name* cannot be named in one. set.mm
    # spells its inner product `.,`, and `$d ., x` came out as
    # `disjoint(.,, x, setvar)` - four arguments where three were meant, refused
    # by the proviso parser, so the theorem never promoted and everything citing
    # it failed with it. 17 statements and the 52 that cite them.
    #
    # A metavariable's name is private to the promoted theorem: it names a slot,
    # and a citation fills that slot by unification, not by name. So renaming it
    # in the statement, the premises and the provisos together changes nothing
    # about what the theorem says or what it applies to - the same argument that
    # licenses `_uncollide` renaming a production's variable.
    # Every token the theorem already spells, not just its statement's. A
    # replacement colliding with a *constant* in a premise would leave that
    # constant's spelling alone while registering it as the metavariable, so the
    # premise would parse as depending on the metavariable and the theorem would
    # accept premises its Metamath assertion does not. Reported by Codex review.
    used = {h.variable for h in assertion.floatings}
    used.update(assertion.tokens)
    for hypothesis in assertion.mandatory:
        used.update(hypothesis.tokens)
    rename: dict[str, str] = {}
    for hypothesis in assertion.floatings:
        if "," not in hypothesis.variable:
            continue

        stem = hypothesis.variable.replace(",", "")
        index = 0
        while True:
            candidate = f"{stem}_{index}"
            if candidate not in used and candidate not in rename.values():
                rename[hypothesis.variable] = candidate
                break
            index += 1
    return rename


def _distinct_provisos(
    assertion: Assertion,
    database: Database,
    system: FormalSystem,
    rename: dict[str, str] | None = None,
) -> tuple[str, ...]:
    # A `$d x y z` constrains every *pair* among its variables, and Edifyce's
    # algebra takes one pair per proviso, so expand. Only variables the assertion
    # actually binds are kept: a $d naming something outside its metavariables
    # would fail to resolve, and constrains nothing here anyway.
    #
    # `$d` forbids the two substitutions sharing a **variable** - of any typecode,
    # not only the binder one - while leaving them free to share a *constant*:
    # `RR = RR` is permitted under `$d A B`, `C = C` is not. So the proviso is
    # restricted to the leaves that *are* the variables, which is exactly what the
    # `<typecode>_var` productions enumerate (see _variable_sort_productions);
    # a constant like `RR` is built by its own production and is not among them.
    #
    # One proviso per variable sort, conjoined. Restricting instead to the single
    # binder sort - which is what this did - silently dropped every `$d` over
    # class or wff variables, since none of their leaves are `setvar`.
    # `floating_typecodes` is a cached view; `_declared_variables` would rescan
    # the whole database, and this runs once per theorem promoted.
    variable_leaves = [
        name
        for name in (f"{typecode}_var" for typecode in database.floating_typecodes())
        if name in system.build_context.variables
    ]

    rename = rename or {}
    bound = {h.variable for h in assertion.floatings}
    provisos: list[str] = []
    for group in assertion.distinct:
        members = sorted(rename.get(v, v) for v in group if v in bound)
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                for sort in variable_leaves or [None]:
                    # No variable production at all: fall back to a sortless
                    # proviso, which also separates constants. Over-strict - it
                    # can refuse a legitimate proof, never admit an illegitimate
                    # one - and unreachable for any database declaring a `$v`.
                    arguments = f"{left}, {right}" + (f", {sort}" if sort else "")
                    proviso = f"disjoint({arguments})"
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
    limit = database.position(assertion.label)

    for label in labels:
        if label in database.hypotheses:
            if label not in assertion.active_hypotheses:
                raise MetamathError(
                    f"{assertion.label}: proof cites hypothesis {label!r}, "
                    "which is not in scope for it."
                )
            continue

        if label not in database.assertions:
            raise MetamathError(
                f"{assertion.label}: proof cites unknown label {label!r}."
            )
        if database.position(label) >= limit:
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
    _givens(assertion, system)

    return system, import_proof(database, label)


def _givens(assertion: Assertion, system: FormalSystem) -> list[str]:
    # Register `assertion`'s own `$e` hypotheses as premises of the proof about to
    # be checked, and report their labels so a caller can withdraw them again.
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
    return [h.label for h in assertion.essentials]


def _first_mention(database: Database) -> dict[str, int]:
    # For each variable, the earliest position at which some statement can mention
    # it - its own tokens, or those of a hypothesis active where it sits. This is
    # `_mentioned_variables`' rule read the other way round: a variable is in
    # `_mentioned_variables(before=L)` exactly when its first mention is at or
    # before `L`. One pass serves the whole walk.
    first: dict[str, int] = {}
    for index, label in enumerate(database.order):
        assertion = database.assertions[label]
        tokens = set(assertion.tokens)
        for hypothesis_label in assertion.active_hypotheses:
            tokens.update(database.hypotheses[hypothesis_label].tokens)
        for token in tokens & database.variables:
            first.setdefault(token, index)
    return first


def _grammar_schedule(database: Database) -> dict[int, list[tuple[str, str]]]:
    # When each production joins the grammar, as `{position: [(sort, name), ...]}`.
    #
    # Notation joins at the syntax axiom that declares it. A variable joins at its
    # first mention, and its `<typecode>_var` sub-sort joins the typecode at the
    # *earliest* of them - held back until then so an empty sub-sort is never a
    # branch of a live sort, but no later, or a variable whose leaf is already live
    # would not read as its typecode. `_declared_variables` yields `$f` declaration
    # order, which is not first-mention order once a `$f` is scoped.
    schedule: dict[int, list[tuple[str, str]]] = {}

    def at(position: int, sort: str, name: str) -> None:
        schedule.setdefault(position, []).append((sort, name))

    for assertion in _syntax_before(database, None):
        at(database.position(assertion.label), assertion.typecode, assertion.label)

    first = _first_mention(database)
    for typecode, members in _declared_variables(database).items():
        sub_sort = f"{typecode}_var"
        at(min(first[variable] for variable in members), typecode, sub_sort)
        for variable in members:
            leaf = variable_production_name(database, typecode, variable)
            at(first[variable], sub_sort, leaf)
    return schedule


def walk(
    database: Database, name: str = "Metamath"
) -> Iterator[tuple[str, FormalSystem, str]]:
    """Yield ``(label, system, proof_text)`` for every ``$p`` theorem, in file order.

    What :func:`import_theorem` establishes per theorem, established for a whole
    database in one pass. The scoping is the same and is the point: when a theorem
    is yielded, the system carries exactly the notation and the theorems that
    *precede* it, plus that theorem's own ``$e`` hypotheses as givens.

    The difference is cost. `import_theorem` rebuilds the system per theorem, which
    over a corpus is quadratic - `set.mm`'s grammar reaches 1,441 productions, and
    rebuilding it 47,546 times is not affordable. Here one system is built and then
    *grown*: each production is added to its sort at the position it becomes
    available, and each assertion is promoted once the theorem yielded for it has
    been checked.

    The yielded system is the walk's own and is mutated on every step, so a caller
    must finish with it before advancing. Sort *admission* is the one thing derived
    at whole-database scope: a union's kernel constructor fixes its branches when
    the system is built (``Constructor.admits``), before any of this replaying. It
    costs nothing, because admission is only ever asked about a term that already
    parsed, and parsing is scoped.
    """
    spec = build_spec(database, name)
    system = build_system(spec)
    context = system.build_context

    sorts = {sort: context.variables[sort] for sort in spec.sort_names()}
    for union in sorts.values():
        union.clear_patterns()

    schedule = _grammar_schedule(database)

    for index, label in enumerate(database.order):
        for sort, production in schedule.get(index, ()):
            sorts[sort].add_pattern(context.variables[production])

        assertion = database.assertions[label]
        if not assertion.is_logical:
            continue

        if assertion.proof:
            given = _givens(assertion, system)
            try:
                yield label, system, import_proof(database, label)
            finally:
                # Metamath labels are unique across hypotheses and assertions, so
                # each of these is the given just registered and nothing else.
                for hypothesis_label in given:
                    del system.promoted_theorems[hypothesis_label]

        system.promote(promoted_theorem(assertion, database, system))
