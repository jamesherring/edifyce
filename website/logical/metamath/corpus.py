"""One ordered pass over a Metamath database, checking each theorem in place.

:func:`~.importer.import_theorem` builds a whole system *per theorem*: the right
shape for checking one proof, and quadratic for checking a library, since the
grammar is rebuilt and every preceding assertion re-promoted once per theorem.
This module keeps the same discipline and pays that cost once -- walk the file in
declaration order, check each theorem against only the notation and theorems that
precede it, then promote it into the running system.

Two properties `import_theorem` enforces are enforced here too, and for the same
reasons (see the roadmap, §1): a theorem is checked against only what precedes
it, and its own ``$e`` hypotheses are registered as givens for the length of its
check and withdrawn afterwards, so nothing later can cite a hypothesis that was
scoped to somebody else's block.

The grammar limit is exact, and nothing is traded for it. One system is built
covering the whole walk and then *grown*: every production is declared up front
and admitted to its sort at the position it becomes available, notation at the
syntax axiom that declares it and a variable at its first mention
(:func:`~.importer.grammar_schedule`).

Rebuilding the system when notation is declared would be simpler, and is what
this did. It costs the library: a ``PromotedTheorem`` holds patterns of the system
it was built against, so none survive a rebuild and every one has to be
re-promoted. Over set.mm that is 255 rebuilds and 3.2M re-promotions across the
first 20,000 theorems, against 20,544 promotions here -- quadratic in the corpus,
and by measurement the whole cost of the pass (5,234s before, 330s after).

The one thing a single build cannot scope is the *logical sort*, since the line
type is fixed when the system is built. A theorem stated before any prefix could
name that sort is reported rather than checked, which is the same refusal
:func:`~.importer._logical_sort` makes when the system is built from the prefix.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..declarative import DeclarativeError, build_system, register_definition
from ..promotion import promote_from_source
from .definitions import Classified, classify, constructors_used, statement_of
from .importer import (
    GrammarSchedule,
    LibraryEntry,
    build_spec,
    grammar_schedule,
    import_proof,
    register,
)
from .parser import MetamathError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from ..declarative import SystemSpec
    from ..formal_system import FormalSystem
    from ..formal_system.proof import Proof
    from ..kernel.terms import Term
    from .parser import Assertion, Database


@dataclass
class CheckedTheorem:
    """One theorem of the walk, as far as it got.

    ``proof`` is the engine's verdict object -- present whenever the import
    produced text the system could parse, whatever that verdict was, since a
    *rejected* proof is still a checked one and its structure is worth keeping.
    ``error`` is set instead when the theorem never reached the kernel at all:
    its stored proof failed to decode, cited something out of scope, or reached a
    statement other than the one declared.
    """

    label: str
    position: int
    source: str
    proof: Proof | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        return self.proof is not None and bool(self.proof.valid)


def theorems(database: Database, limit: int | None = None) -> list[Assertion]:
    """The provable statements a walk checks, in file order.

    A ``$p`` with a *syntax* typecode (set.mm's ``bj-0``) is not one: it asserts
    no truth, so there is nothing for the kernel to check and nothing to promote.

    A ``limit`` below 1 is a caller's error, not a property of the database, and
    is rejected here so every entry point reports it the same way -- ``walk``
    would otherwise fall silently empty while ``corpus_spec`` blamed the file.
    """
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be at least 1 if given, not {limit}.")
    found = [a for a in database.iter_assertions() if a.is_logical and a.proof]
    return found if limit is None else found[:limit]


def corpus_spec(
    database: Database,
    limit: int | None = None,
    name: str = "Metamath",
    binders: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> SystemSpec:
    """The grammar a walk of ``limit`` theorems ends with.

    The union of every grammar the walk checks against, because notation only
    accumulates -- so it is the one system a caller can store the whole walk's
    terms against (see :mod:`app.db.metamath_store`).

    ``binders`` must be whatever :func:`walk` is given, and is on the signature so
    a caller can say so: the stored grammar has to be the one the walk checked
    against, and binding slots are part of a grammar. Nothing today passes either
    -- ``import_corpus`` opts into neither -- so the two agree by both being empty.
    """
    walked = theorems(database, limit)
    if not walked:
        raise MetamathError("Database declares no provable statements to walk.")
    horizon = walked[-1].label
    return build_spec(
        database, name, before=horizon, variable_scope=horizon, binders=binders
    )


def walk(
    database: Database,
    limit: int | None = None,
    name: str = "Metamath",
    registered: Callable[[LibraryEntry], None] | None = None,
    equivalences: frozenset[str] = frozenset(),
    classified: Callable[[Classified], None] | None = None,
    binders: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    restatements: Mapping[str, str] | None = None,
) -> Iterator[CheckedTheorem]:
    """Check each of ``database``'s first ``limit`` theorems, in file order.

    Yields one :class:`CheckedTheorem` per theorem as it is checked, so a caller
    can persist or report incrementally rather than hold the whole corpus.

    ``registered`` is called with every assertion that joins the library, axioms
    included, in the order they join. A caller storing the corpus needs that:
    promotion parses a statement against the grammar *as of its own position*, so
    only the walk is in a position to hand over what it built (see
    ``app/db/promoted_theorems_mapping.py``). Nothing here reads it back.

    ``equivalences`` names the productions meaning *definitional equivalence* in
    this database (`set.mm`'s are `wb` and `wceq`). Naming them is what lets a
    logical ``$a`` be imported as a **definition** as well as an axiom; naming
    none - the default - imports every one as an axiom exactly as before. See
    :mod:`~.definitions`, and ``classified`` for the per-assertion verdicts.

    ``restatements`` names, per assertion, a proved theorem stating the same
    definition with an equivalence at its root - for the one assertion that cannot
    state itself, `set.mm`'s `df-bi`. :mod:`~.setmm` has it.

    ``binders`` declares which slots of a syntax axiom bind, and over which others
    (:func:`~.importer.build_spec`). It decides far more of the classification than
    ``equivalences`` does: a definition whose defining form binds a dummy needs a
    ``fresh`` clause, which is inferred from these, and without them 1,123 of
    `set.mm`'s definition-shaped statements stay axioms. :mod:`~.setmm` has both.
    """
    walked = theorems(database, limit)
    if not walked:
        return
    horizon = walked[-1].label
    wanted = {a.label for a in walked}

    # One system for the whole walk, built to the far end and then *grown*: each
    # production is admitted to its sort at the position it becomes available.
    #
    # Rebuilding when notation is declared would be simpler, and is what this did.
    # It costs the library, though: a `PromotedTheorem` holds patterns of the
    # system it was built against, so none survive a rebuild and all of them have
    # to be re-promoted. Over set.mm that is 255 rebuilds and 3.2M re-promotions in
    # the first 20,000 theorems against 20,544 promotions here - quadratic in the
    # corpus, and the whole cost of the pass.
    schedule = grammar_schedule(database, before=horizon)
    try:
        system = build_system(
            build_spec(
                database, name, before=horizon, variable_scope=horizon,
                binders=binders,
            )
        )
    except Exception as exc:  # noqa: BLE001 - reported per theorem, not fatal
        for assertion in walked:
            yield CheckedTheorem(
                assertion.label, database.position(assertion.label), "", error=str(exc)
            )
        return

    _reset_sorts(system, schedule)
    admitted = 0
    # The constructor names every logical assertion *so far* has used, which is
    # what tells a definition (notation given meaning for the first time) from an
    # equation between things the theory already reasons about. Accumulated here
    # because only the walk sees the order.
    in_use: set[str] = set()

    for label in database.order[: database.position(horizon) + 1]:
        assertion = database.assertions[label]
        if not assertion.is_logical:
            continue

        # Admitted at every logical assertion, not only the checked ones: an
        # axiom is promoted here too, and a `PromotedTheorem` is built by parsing
        # its statement, so it needs the grammar as of its own position.
        position = database.position(label)
        admitted = _admit(system, schedule, admitted, position)

        if label in wanted:
            if schedule.logical_from is None or position < schedule.logical_from:
                # Nothing yet says which sort a `|-` statement is written in. The
                # line type was built from the grammar the walk *ends* with, so
                # reading this one would borrow a sort nothing has declared - the
                # forward leak the ordering exists to prevent, and the same refusal
                # `_logical_sort` makes when the system is built from the prefix.
                yield CheckedTheorem(
                    label, position, "",
                    error=(
                        "Database declares no syntax axioms and no sort named "
                        "'wff' or 'formula', so which sort a '|-' statement is "
                        "written in cannot be told."
                    ),
                )
                _promote(system, assertion, database, registered)
                continue
            yield _check(database, assertion, system)

        # Definitions before the rule, and it has to be that way round: a
        # definition may only give meaning to a symbol the system does not
        # already reason with (`declarative._require_a_fresh_defined_form`), and
        # this assertion's own rule mentions the very symbol it defines. Register
        # the rule first and every definition refuses itself.
        statement = _classify(
            assertion, database, system, in_use, equivalences, classified, restatements
        )

        # Promoted whatever the verdict was, exactly as `import_theorem`
        # would have: a rejected proof does not retract its statement from
        # the library, so a later theorem citing it fails for its own
        # reasons rather than for a missing label.
        _promote(system, assertion, database, registered)

        if statement is not None:
            in_use |= constructors_used(statement)


def _classify(
    assertion: Assertion,
    database: Database,
    system: FormalSystem,
    in_use: set[str],
    equivalences: frozenset[str],
    report: Callable[[Classified], None] | None,
    restatements: Mapping[str, str] | None = None,
) -> Term | None:
    # Decide what this assertion is and, when it is a definition, register it.
    # Returns its statement term for the caller to fold into `in_use`, or None if
    # it did not parse.
    #
    # Only an asserted statement can be a definition: a `$p` is *derived*, so
    # whatever it says is already a consequence and abbreviating it defines
    # nothing. Skipping them also skips 47,000 statement parses.
    if not equivalences or not assertion.is_axiom:
        return None

    statement = statement_of(assertion, system)
    verdict = classify(
        assertion, statement, in_use, database, system, equivalences, restatements
    )
    if verdict.is_definition:
        try:
            register_definition(verdict.definition, system)
        except DeclarativeError as exc:
            # The classifier promises what it returns will register, so this is a
            # defect rather than a verdict — but one assertion's is not worth
            # abandoning the corpus for, and the assertion stays an axiom either
            # way. Reported through `classified` so a caller can count them.
            verdict = Classified(assertion.label, reason=f"refused on registration: {exc}")
    if report is not None:
        report(verdict)
    return statement


def _reset_sorts(system: FormalSystem, schedule: GrammarSchedule) -> None:
    # Empty every sort the schedule fills. `build_spec` was given the walk's far
    # end, so it declared the whole grammar *and* filled each sort with all of it;
    # the schedule refills them in order. Emptying `patterns` directly would leave
    # the flattening memos keyed to a membership that no longer holds, which is
    # what `clear_patterns` exists for.
    context = system.build_context
    for sort in schedule.sorts:
        context.variables[sort].clear_patterns()


def _admit(
    system: FormalSystem, schedule: GrammarSchedule, admitted: int, position: int
) -> int:
    # Admit every production scheduled at or before `position` and not already in,
    # and report the watermark to resume from.
    context = system.build_context
    for at in range(admitted, position + 1):
        for sort, production in schedule.entries.get(at, ()):
            union = context.variables[sort]
            if context.variables[production] not in union.patterns:
                union.add_pattern(context.variables[production])
    return position + 1


def _promote(
    system: FormalSystem,
    assertion: Assertion,
    database: Database,
    registered: Callable[[LibraryEntry], None] | None = None,
) -> None:
    # A statement that cannot be promoted is dropped from the library rather than
    # aborting the walk: set.mm has a handful whose tokens defeat the proviso and
    # bracket scans (roadmap §1.2), and the theorems citing them are the ones
    # that should fail, not the 47,000 that do not.
    #
    # A dropped statement is not reported to `registered` either: it never joined
    # the library, so storing it would leave a citable row for a theorem this walk
    # refused to make citable.
    try:
        entry = register(assertion, database, system)
    except Exception:  # noqa: BLE001 - any promotion defect, reported by its citers
        return
    if registered is not None:
        registered(entry)


def _check(
    database: Database, assertion: Assertion, system: FormalSystem
) -> CheckedTheorem:
    position = database.position(assertion.label)
    try:
        source = import_proof(database, assertion.label)
    except Exception as exc:  # noqa: BLE001 - a decode/scope defect, not a verdict
        return CheckedTheorem(assertion.label, position, "", error=str(exc))

    try:
        with _givens(system, assertion):
            proof = system.parse(source)
    except Exception as exc:  # noqa: BLE001 - the checker raises on malformed input
        # A given that would not register belongs here too, not in the verdict: a
        # theorem checked without one of its own hypotheses is not *refuted*, it
        # was never checked. Reporting it as a rejection would book an import
        # defect of ours as mathematics that failed.
        return CheckedTheorem(assertion.label, position, source, error=str(exc))

    return CheckedTheorem(assertion.label, position, source, proof=proof)


@contextmanager
def _givens(system: FormalSystem, assertion: Assertion) -> Iterator[None]:
    # A theorem proves *under* its `$e` hypotheses, so the proof states them as
    # lines justified by the hypothesis label; registering them is what makes
    # those lines resolve. The block they belong to closes with the theorem, so
    # they are withdrawn on the way out - the walk, unlike `import_theorem`,
    # reuses one system for the whole file, and a `$e` left promoted is a bare
    # `|- ph` that proves anything a later theorem cares to cite it for.
    #
    # Withdrawal covers a *partial* registration too, which is why the labels are
    # tracked as they are added rather than returned at the end.
    metavariables = {h.variable: h.typecode for h in assertion.floatings}
    registered: list[str] = []
    try:
        for hypothesis in assertion.essentials:
            system.promote(
                promote_from_source(
                    system,
                    label=hypothesis.label,
                    statement=" ".join(hypothesis.tokens),
                    metavariables=metavariables,
                )
            )
            registered.append(hypothesis.label)
        yield
    finally:
        for label in registered:
            del system.promoted_theorems[label]
