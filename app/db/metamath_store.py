"""Persist a Metamath import: the system, its proofs, and their line graphs.

The import produced proof *text* and threw the parse away. Every run therefore
re-read `.mm` source, rebuilt the grammar, re-parsed 47,000 proofs and kept none
of it — while `terms` / `proof_lines` sat there describing exactly that structure
(roadmap §6.5). This module closes that: it drives
:func:`~website.logical.metamath.corpus.walk` and, for each theorem the kernel
checked, writes the same rows a verify through the API writes
(:func:`~app.db.proofs_mapping.store_proof_lines`) — one ``proof_lines`` row per
line, its justification as ``proof_line_antecedents`` edges, and its formula
interned into the system's shared ``terms`` DAG.

**One system row for the whole walk.** The walk's grammar grows as set.mm
declares notation, but a term row is keyed by *constructor name* and interned per
system, so terms built under an early grammar and a late one share rows correctly
as long as the stored system is the union of both — which
:func:`~website.logical.metamath.corpus.corpus_spec` is. That is the whole point:
the corpus lands in one term graph, so a subterm shared by two theorems is one
row and the theorem search indexes them together.

**What is stored is the parse, not yet the means to repeat it.** A system row
holds a grammar, definitions, axioms and rules; it has nowhere to hold a
*promoted theorem*, and the Metamath library is 49,000 of them. So the stored
system is grammar-only, and re-parsing an imported proof against it fails on the
first citation — the rows record a check that happened, not one that can be
re-run from them. That is roadmap §3.2 (the axiom-vs-theorem split), which owns
the storage decision; until it lands, an import is deliberately **ownerless**, so
the owner-scoped proof routes cannot reach it — and in particular
``POST /proofs/{id}/verify`` cannot re-check it, record ``valid=False`` and drop
the imported structure on the way. ``test_metamath_persistence`` pins both halves.

Synchronous, like the rest of the mapping layer; an async caller reaches it
through ``AsyncSession.run_sync`` (see ``scripts/import_metamath.py``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.models import FormalSystem, Proof
from app.db.proofs_mapping import store_proof_lines
from app.db.systems_mapping import spec_to_system
from website.logical.metamath.corpus import corpus_spec, walk

if TYPE_CHECKING:
    from collections.abc import Callable

    from website.logical.metamath.corpus import CheckedTheorem
    from website.logical.metamath.parser import Database

# Kept short deliberately: the report is a summary, and a run where thousands
# fail should be diagnosed from the corpus, not from a list carried in memory.
_FAILURES_KEPT = 20


@dataclass
class ImportReport:
    """What one :func:`import_corpus` run stored.

    ``verified`` and ``rejected`` are both *stored*: a rejected proof is one the
    kernel checked and refused, and its structure is what says where it went
    wrong. ``failed`` never got that far — the stored proof did not decode, cited
    out of scope, reached a statement other than the declared one, or could not
    be written — so there is nothing to store for it.
    """

    system_id: uuid.UUID
    checked: int = 0
    verified: int = 0
    rejected: int = 0
    failed: int = 0
    lines: int = 0
    formulas: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def import_corpus(
    session: Session,
    database: Database,
    limit: int | None = None,
    name: str = "Metamath",
    batch: int | None = None,
    progress: Callable[[ImportReport, CheckedTheorem], None] | None = None,
) -> ImportReport:
    """Import ``database``'s first ``limit`` theorems into ``session``.

    The transaction is the caller's by default: nothing here commits, so an
    import composes with whatever else the caller is doing. Pass ``batch`` to
    hand that over — the run then commits and empties the identity map every that
    many theorems, which is what keeps a whole-corpus run's memory flat and its
    per-proof cost from growing with the transaction. ``progress`` is called
    after each theorem with the running report.

    The system is created ownerless; see this module's docstring for why.
    """
    if batch is not None and batch < 1:
        raise ValueError(f"batch must be at least 1 if given, not {batch}.")

    # Raises for a `limit` below 1 (`corpus.theorems`) before anything is written.
    system = spec_to_system(corpus_spec(database, limit, name))
    session.add(system)
    session.flush()
    report = ImportReport(system_id=system.id)

    for position, checked in enumerate(walk(database, limit, name)):
        report.checked += 1
        if checked.proof is None:
            _record_failure(report, checked.label, checked.error or "")
        else:
            # Contained per theorem, so one unstorable proof costs that proof
            # rather than the run: a whole-corpus pass is 23 minutes, and a
            # traceback in place of the report would discard what it learnt about
            # the tens of thousands that stored fine. The savepoint is what keeps
            # the rest of the batch — a plain rollback would take it too.
            #
            # Counted after it closes, not inside: leaving the block is what
            # flushes the line rows, so a write that fails there must not already
            # have been booked as stored.
            try:
                with session.begin_nested():
                    stored = _store(session, system, position, checked)
            except Exception as exc:  # noqa: BLE001 - reported, not fatal
                _record_failure(report, checked.label, str(exc))
            else:
                report.verified += stored.valid
                report.rejected += not stored.valid
                report.lines += stored.lines
                report.formulas += stored.formulas

        if progress is not None:
            progress(report, checked)
        if batch is not None and report.checked % batch == 0:
            system = _checkpoint(session, report)

    if batch is not None:
        session.commit()
    return report


def _record_failure(report: ImportReport, label: str, message: str) -> None:
    report.failed += 1
    if len(report.failures) < _FAILURES_KEPT:
        report.failures.append((label, message))


def _checkpoint(session: Session, report: ImportReport) -> FormalSystem:
    """Commit what is held and start again from an empty identity map.

    The map holds every line and term row written so far and nothing downstream
    reads them back, so dropping it is what keeps a long run's memory flat — and
    keeps the per-proof flush from scanning an ever-growing set. The system is
    re-attached because ``store_term`` interns against it.
    """
    session.commit()
    session.expunge_all()
    return session.get(FormalSystem, report.system_id)


@dataclass(frozen=True)
class _Stored:
    """What one theorem contributed, tallied only once its write succeeded."""

    valid: bool
    lines: int
    formulas: int


def _store(
    session: Session,
    system: FormalSystem,
    position: int,
    checked: CheckedTheorem,
) -> _Stored:
    engine_proof = checked.proof
    valid = bool(engine_proof.valid)

    proof = Proof(
        formal_system_id=system.id,
        # The Metamath label is the identity here, so it is both the display name
        # and the slug — imported labels are already URL-safe (letters, digits,
        # `-_.`) and unique across the database, which is what a slug wants.
        name=checked.label,
        slug=checked.label,
        source=checked.source,
        position=position,
        valid=valid,
        # Stored for the same reason the verify route stores it: `valid`,
        # `result` and the line rows are one artefact of one check, and a row
        # carrying two of the three is a state nothing else in the schema makes.
        result=engine_proof.data(),
    )
    session.add(proof)
    session.flush()

    # `replace=False`: the proof was created three lines ago, so there is no
    # earlier structure to clear, and the delete is not free to issue anyway.
    rows = store_proof_lines(session, proof, system, engine_proof, replace=False)

    return _Stored(
        valid=valid,
        lines=len(rows),
        formulas=sum(1 for row in rows if row.term is not None),
    )
