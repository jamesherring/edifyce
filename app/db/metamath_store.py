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
    wrong. ``failed`` never reached the kernel — the stored proof did not decode,
    cited out of scope, or reached a statement other than the declared one — so
    there is nothing to store for it.
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
    owner_id: uuid.UUID | None = None,
    batch: int = 50,
    progress: Callable[[ImportReport, CheckedTheorem], None] | None = None,
) -> ImportReport:
    """Import ``database``'s first ``limit`` theorems into ``session``.

    ``batch`` commits (and empties the identity map) every that many theorems, so
    a long run's memory stays flat and a crash keeps what it had already stored.
    ``progress`` is called after each theorem with the running report.
    """
    system = spec_to_system(corpus_spec(database, limit, name))
    system.owner_id = owner_id
    session.add(system)
    session.flush()
    report = ImportReport(system_id=system.id)

    for position, checked in enumerate(walk(database, limit, name)):
        report.checked += 1
        if checked.proof is None:
            report.failed += 1
            if len(report.failures) < _FAILURES_KEPT:
                report.failures.append((checked.label, checked.error or ""))
        else:
            _store(session, system, report, position, checked)

        if progress is not None:
            progress(report, checked)
        if report.checked % batch == 0:
            session.commit()
            # The mapping holds every line and term row written so far, and
            # nothing downstream reads them back. Dropping it is what keeps a
            # whole-corpus run's memory flat; the system is re-attached because
            # `store_term` interns against it.
            session.expunge_all()
            system = session.get(FormalSystem, report.system_id)

    session.commit()
    return report


def _store(
    session: Session,
    system: FormalSystem,
    report: ImportReport,
    position: int,
    checked: CheckedTheorem,
) -> None:
    engine_proof = checked.proof
    valid = bool(engine_proof.valid)
    if valid:
        report.verified += 1
    else:
        report.rejected += 1

    proof = Proof(
        formal_system_id=system.id,
        owner_id=system.owner_id,
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

    rows = store_proof_lines(session, proof, system, engine_proof)
    report.lines += len(rows)
    report.formulas += sum(1 for row in rows if row.term is not None)
