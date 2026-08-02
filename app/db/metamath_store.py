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

**The library is stored too**, so an imported proof can be re-checked from its
rows rather than only described by them. Every assertion the walk promotes — the
1,559 logical ``$a`` as much as the 47,546 ``$p`` — is written to
``promoted_theorems`` with the term its statement composed to, and a verify then
resolves the labels a proof cites and no more (roadmap §3.2; P4 of
docs/verification-from-rows.md). The walk is what hands them over, because
promotion parses a statement against the grammar *as of that statement's own
position* and only the walk holds it.

An import stays **ownerless** all the same. That was a guard while the library
was missing — the owner-scoped proof routes could not reach an import, so
``POST /proofs/{id}/verify`` could not re-check it, record ``valid=False`` and
drop the imported structure. It is now a statement about provenance rather than a
guard: a corpus belongs to no user. ``test_metamath_persistence`` pins it.

Synchronous, like the rest of the mapping layer; an async caller reaches it
through ``AsyncSession.run_sync`` (see ``scripts/import_metamath.py``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.descriptions_mapping import store_descriptions
from app.db.models import FormalSystem, Proof
from app.db.promoted_theorems_mapping import store_theorem, theorem_digest
from app.db.notations_mapping import store_notation
from app.db.proofs_mapping import store_proof_lines
from app.db.systems_mapping import spec_to_system
from website.logical.declarative import build_system, library_digest
from website.logical.metamath.corpus import corpus_spec, walk
from website.logical.metamath.comments import read_comment
from website.logical.metamath.display import notation_constructors, unicode_projection
from website.logical.metamath.typesetting import typesetting_of
from website.logical.rendering import total_projection
from website.logical.metamath.importer import LibraryEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from website.logical.declarative import SystemSpec
    from website.logical.metamath.comments import Description
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
    # Constructors given a spelling in the stored `unicode` notation, or 0 for a
    # database carrying no `$t` block to derive one from.
    notation: int = 0
    # Labels this run stored a description for. Not the same as `checked`: a `$a`
    # is documented and never checked, and a comment that is only an attribution
    # still counts.
    described: int = 0
    # The citable library this run stored: every assertion the walk promoted,
    # and how many of those are primitives of the imported system.
    # ``theorems_failed`` is counted apart from ``failed`` because it is a
    # different thing going wrong — a theorem that would not *store* against a
    # proof that would not *check* — and adding them would make either number
    # unreadable.
    theorems: int = 0
    primitives: int = 0
    theorems_failed: int = 0
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
    spec = corpus_spec(database, limit, name)
    system = spec_to_system(spec)
    session.add(system)
    session.flush()
    report = ImportReport(system_id=system.id)
    library = _Library(session, system, report, library_digest(spec))
    # Read once, up front, and used twice: every documented label gets a row, and
    # a `$p`'s own title comes off the same parse. Metamath documents a statement
    # by the comment before it, so this is the whole of the association.
    descriptions = {
        label: read_comment(assertion.comment)
        for label, assertion in database.assertions.items()
        if assertion.comment is not None
    }

    for position, checked in enumerate(walk(database, limit, name, library.store)):
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
                    stored = _store(
                        session, system, position, checked, descriptions
                    )
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
            library.rebind(system)

    _link_proofs_to_theorems(session, report.system_id, library.ids)
    report.described = store_descriptions(session, report.system_id, descriptions)
    report.notation = _store_notation(session, database, spec, report.system_id)
    if batch is not None:
        session.commit()
    return report


def _store_notation(
    session: Session, database: Database, spec: SystemSpec, system_id: uuid.UUID
) -> int:
    # The motivating case for notations, and the reason they are stored at all: a
    # `.mm` file carries its own readable spellings in a `$t` block, and without
    # somewhere to put them an imported corpus can only ever be read as ASCII.
    #
    # Derived here because deriving needs what only an import has - the file's
    # `$t` and the grammar the file built. A reader has rows.
    typesetting = typesetting_of(database.comments)
    if typesetting is None or not typesetting.unicode:
        # A `$t` block need not declare `althtmldef` at all - it may carry only
        # `latexdef`/`htmldef`, or nothing but site configuration - and a block
        # that declares no Unicode is as good as no block. Checked before the
        # build, which is the expensive half.
        return 0

    engine = build_system(spec)
    spellings = unicode_projection(engine, typesetting)
    if not spellings.templates:
        # Declared, but about tokens this grammar's productions never use. Storing
        # the completion anyway would advertise a `unicode` notation that re-spells
        # nothing - every constructor at its source template, which is what a
        # reader already gets by asking for no notation at all.
        return 0

    projection = total_projection(
        notation_constructors(engine.build_context, engine.definitions),
        spellings,
    )
    return store_notation(session, system_id, projection)


def _link_proofs_to_theorems(
    session: Session, system_id: uuid.UUID, ids: dict[str, uuid.UUID]
) -> None:
    """Point each proof at the library entry it establishes.

    Done after the walk rather than during it, because the walk promotes a
    theorem *after* checking its proof — that ordering is what stops a theorem
    justifying itself, so the row a proof would point at does not exist yet when
    the proof is written. The name is the join: an import creates both from one
    Metamath ``$p``, so ``proofs.name`` is the theorem's label by construction.
    """
    if not ids:
        return
    for name, theorem_id in ids.items():
        session.execute(
            sa_update(Proof)
            .where(Proof.formal_system_id == system_id, Proof.name == name)
            .values(theorem_id=theorem_id)
        )


class _Library:
    """Writes each assertion the walk promotes into ``promoted_theorems``.

    Held as an object rather than a closure because a batched run *rebinds* the
    system: ``_checkpoint`` empties the identity map and re-fetches it, and the
    symbol table a metavariable's sort resolves through has to follow.

    Contained per theorem, like the proof writes: an assertion whose sort the
    system does not declare, or whose statement will not store, costs itself and
    is reported — not the run. It also stays *out* of the library rather than
    landing there without its terms, so a later verify fails on the citation
    rather than on a half-written row.
    """

    def __init__(
        self,
        session: Session,
        system: FormalSystem,
        report: ImportReport,
        digest: str,
    ) -> None:
        self._session = session
        self._report = report
        self._digest = digest
        # Label -> stored id, so a proof can be linked to the theorem it
        # establishes. Ids survive a checkpoint; the ORM objects do not.
        self.ids: dict[str, uuid.UUID] = {}
        self.rebind(system)

    def rebind(self, system: FormalSystem) -> None:
        self._system = system
        self._symbols = {symbol.name: symbol for symbol in system.symbols}

    def store(self, entry: LibraryEntry) -> None:
        try:
            with self._session.begin_nested():
                row = store_theorem(
                    self._session,
                    self._system,
                    entry.spec,
                    self._symbols,
                    position=self._report.theorems,
                    primitive=entry.primitive,
                    digest=theorem_digest(self._digest, entry.spec),
                    promoted=entry.theorem,
                    premise_labels=entry.premise_labels,
                )
                self._session.flush()
                self.ids[entry.spec.label] = row.id
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            self._report.theorems_failed += 1
            if len(self._report.failures) < _FAILURES_KEPT:
                self._report.failures.append((entry.spec.label, str(exc)))
            return
        self._report.theorems += 1
        self._report.primitives += entry.primitive


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
    descriptions: Mapping[str, Description],
) -> _Stored:
    engine_proof = checked.proof
    valid = bool(engine_proof.valid)
    described = descriptions.get(checked.label)

    proof = Proof(
        formal_system_id=system.id,
        # The Metamath label is the identity here, so it is both the display name
        # and the slug — imported labels are already URL-safe (letters, digits,
        # `-_.`) and unique across the database, which is what a slug wants.
        name=checked.label,
        slug=checked.label,
        # The title and the prose are the proof's own copy, editable by whoever
        # comes to own it; `label_descriptions` keeps the corpus's record of what
        # the file said, and covers the labels that are not proofs at all.
        title=described.title or None if described else None,
        description=described.text or None if described else None,
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
