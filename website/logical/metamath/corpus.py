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

What the walk trades away is exactness of the *grammar* limit between rebuilds.
The system is rebuilt whenever a syntax axiom is declared, not on every theorem,
so within a run of theorems declaring no notation each is checked against the
grammar as of the run's first -- identical, since notation is what changes it.
The variable leaves are the exception: they grow with every statement, so they
are seeded once at the far end of the walk (``variable_scope``), which admits
more variable *names* than a given theorem could mention. That is the weakening
§1.1 already records; it adds no constructor, so it cannot capture a parse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..declarative import build_system
from ..promotion import promote_from_source
from .importer import build_spec, import_proof, promoted_theorem
from .parser import MetamathError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..declarative import SystemSpec
    from ..formal_system import FormalSystem
    from ..formal_system.proof import Proof
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
    """
    found = [a for a in database.iter_assertions() if a.is_logical and a.proof]
    return found if limit is None else found[:limit]


def corpus_spec(
    database: Database, limit: int | None = None, name: str = "Metamath"
) -> SystemSpec:
    """The grammar a walk of ``limit`` theorems ends with.

    The union of every grammar the walk checks against, because notation only
    accumulates -- so it is the one system a caller can store the whole walk's
    terms against (see :mod:`app.db.metamath_store`).
    """
    walked = theorems(database, limit)
    if not walked:
        raise MetamathError("Database declares no provable statements to walk.")
    horizon = walked[-1].label
    return build_spec(database, name, before=horizon, variable_scope=horizon)


def walk(
    database: Database, limit: int | None = None, name: str = "Metamath"
) -> Iterator[CheckedTheorem]:
    """Check each of ``database``'s first ``limit`` theorems, in file order.

    Yields one :class:`CheckedTheorem` per theorem as it is checked, so a caller
    can persist or report incrementally rather than hold the whole corpus.
    """
    walked = theorems(database, limit)
    if not walked:
        return
    horizon = walked[-1].label
    wanted = {a.label for a in walked}

    system: FormalSystem | None = None
    # The library promoted into `system`, in file order. Kept so a rebuild can
    # re-promote it: a PromotedTheorem holds patterns of the system it was built
    # against, so none of them survive one.
    library: list[Assertion] = []
    # Rebuild when the count of declared notation changes, which is the only
    # thing that changes the grammar a theorem is checked against.
    declared = 0
    built_with = -1

    for label in database.order[: database.position(horizon) + 1]:
        assertion = database.assertions[label]
        if assertion.declares_notation:
            declared += 1
            continue
        if not assertion.is_logical:
            continue

        if label in wanted:
            if system is None or built_with != declared:
                try:
                    rebuilt = build_system(
                        build_spec(database, name, before=label, variable_scope=horizon)
                    )
                except Exception as exc:  # noqa: BLE001 - reported, not fatal
                    # A prefix of the file the grammar cannot be built from --
                    # nothing yet says which sort a `|-` statement is written in,
                    # say. It is the prefix that is short, not the database, so
                    # the walk reports this theorem and carries on; `built_with`
                    # is left alone so the next one retries.
                    yield CheckedTheorem(
                        label, database.position(label), "", error=str(exc)
                    )
                    library.append(assertion)
                    continue
                system = rebuilt
                built_with = declared
                for earlier in library:
                    _promote(system, earlier, database)
            yield _check(database, assertion, system)

        library.append(assertion)
        if system is not None:
            # Promoted whatever the verdict was, exactly as `import_theorem`
            # would have: a rejected proof does not retract its statement from
            # the library, so a later theorem citing it fails for its own
            # reasons rather than for a missing label.
            _promote(system, assertion, database)


def _promote(system: FormalSystem, assertion: Assertion, database: Database) -> None:
    # A statement that cannot be promoted is dropped from the library rather than
    # aborting the walk: set.mm has a handful whose tokens defeat the proviso and
    # bracket scans (roadmap §1.2), and the theorems citing them are the ones
    # that should fail, not the 47,000 that do not.
    try:
        system.promote(promoted_theorem(assertion, database, system))
    except Exception:  # noqa: BLE001 - any promotion defect, reported by its citers
        pass


def _check(
    database: Database, assertion: Assertion, system: FormalSystem
) -> CheckedTheorem:
    position = database.position(assertion.label)
    try:
        source = import_proof(database, assertion.label)
    except Exception as exc:  # noqa: BLE001 - a decode/scope defect, not a verdict
        return CheckedTheorem(assertion.label, position, "", error=str(exc))

    givens = _register_hypotheses(system, assertion)
    try:
        proof = system.parse(source)
    except Exception as exc:  # noqa: BLE001 - the checker raises on malformed input
        return CheckedTheorem(assertion.label, position, source, error=str(exc))
    finally:
        # The block the hypotheses belong to closes with the theorem; leaving
        # them promoted would let a later theorem cite a given that was never in
        # scope for it.
        for label in givens:
            del system.promoted_theorems[label]

    return CheckedTheorem(assertion.label, position, source, proof=proof)


def _register_hypotheses(system: FormalSystem, assertion: Assertion) -> list[str]:
    # A theorem proves *under* its `$e` hypotheses, so the proof states them as
    # lines justified by the hypothesis label. Registering them is what makes
    # those lines resolve; the labels are returned so the caller can withdraw them.
    metavariables = {h.variable: h.typecode for h in assertion.floatings}
    registered: list[str] = []
    for hypothesis in assertion.essentials:
        try:
            system.promote(
                promote_from_source(
                    system,
                    label=hypothesis.label,
                    statement=" ".join(hypothesis.tokens),
                    metavariables=metavariables,
                )
            )
        except Exception:  # noqa: BLE001 - the premise line then fails to resolve
            continue
        registered.append(hypothesis.label)
    return registered
