"""A checked engine :class:`Proof` to ``proof_lines`` rows, and back.

The counterpart to :mod:`app.db.systems_mapping` on the proof side, and the
consumer of :mod:`app.db.terms_mapping` on the storage side: where a system is
rebuilt *from* rows, a proof's structure is written *to* them once the engine has
checked it. Each formula-bearing line already carries its kernel term — the
parser hands the parse to the kernel as it goes — so storing a proof is interning
those terms into the system's shared term graph, landing a proof's statements in
the same DAG the theorem search indexes.

:func:`store_proof_lines` writes that; :func:`load_proof_lines` reads it back.
The read direction is what makes the rows load-bearing rather than a render:
verifying a proof now takes its lemmas from *their* rows instead of re-parsing
and re-checking them (``docs/verification-from-rows.md``). So the snapshot is no
longer merely derived — it is the parse, and everything that invalidates a
verdict (:func:`clear_proof_lines`, :func:`discard_system_checks`, the routes'
dependent invalidation) is what keeps it honest. Two writes replace rather than
accumulate.

Synchronous (a :class:`~sqlalchemy.orm.Session`), like ``terms_mapping`` — the
async routes reach it through ``AsyncSession.run_sync``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.models import Proof as ProofRow
from app.db.proof_lines import (
    ANTECEDENT_ROLE_ANTECEDENT,
    ANTECEDENT_ROLE_EXTRA,
    ANTECEDENT_ROLE_SUBPROOF,
    ProofLineAntecedentRow,
    ProofLineRow,
)
from app.db.terms import TermRow
from app.db.terms_mapping import TermGraph, prefetch_terms, store_term
from website.logical.formal_system.diagnostics import Failure, SlotReport
from website.logical.formal_system.proof import Proof as EngineProof
from website.logical.formal_system.proof import ProofLine as EngineProofLine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from app.db.models import FormalSystem, Proof
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system.line_type import LineType
    from website.logical.formal_system.proof import ProofLine
    from website.logical.matching.context import Context

    # A lemma this proof may cite, paired with its stored id. A sequence of live
    # objects rather than a map keyed by `id()`: an id is only meaningful while
    # the object it names is alive, and CPython reuses the ids of collected ones.
    CitedProofs = Sequence[tuple[EngineProof, uuid.UUID]]


def clear_proof_lines(session: Session, proof_ids: list[uuid.UUID]) -> None:
    """Drop the stored structure of every proof in ``proof_ids``.

    Called wherever a cached verdict is invalidated: the rows describe a *checked*
    proof, so an edited (or newly unchecked) proof must not keep a snapshot that
    no longer describes its source. The antecedent edges and any nested scope rows
    go with the lines by FK cascade.
    """
    if not proof_ids:
        return
    session.execute(sa_delete(ProofLineRow).where(ProofLineRow.proof_id.in_(proof_ids)))


def discard_system_checks(session: Session, system_id: uuid.UUID) -> None:
    """Drop every check derived from ``system_id``'s current definition.

    A proof means nothing apart from the system it was checked against, so
    editing that system's grammar, definitions or rules invalidates every proof
    in it — the cached verdict *and* the structure, whose terms and rule labels
    name productions the system may no longer have. A **published** system is
    frozen (`systems.require_editable_system`), so this only ever runs for a
    draft, whose proofs re-verify on demand.
    """
    proof_ids = list(
        session.scalars(select(ProofRow.id).where(ProofRow.formal_system_id == system_id))
    )
    if not proof_ids:
        return
    session.execute(
        sa_update(ProofRow).where(ProofRow.id.in_(proof_ids)).values(valid=None, result=None)
    )
    clear_proof_lines(session, proof_ids)


def store_proof_lines(
    session: Session,
    proof: Proof,
    system: FormalSystem,
    engine_proof: EngineProof,
    cited_proofs: CitedProofs = (),
    replace: bool = True,
) -> list[ProofLineRow]:
    """Replace ``proof``'s stored structure with ``engine_proof``'s.

    ``system`` is the row the terms are interned against — the proof's own formal
    system, passed in because the caller already has it loaded.

    ``cited_proofs`` pairs each *other* proof whose lines this one may cite (the
    lemmas seeded into ``reference_context``) with its stored id. A citation
    reaching into one of those is recorded by proof id and citation number rather
    than by a foreign key, since that proof owns its own line rows.

    ``replace`` clears the proof's existing rows first, which every *re*-check
    needs and a proof created moments ago does not. It is not free to skip
    pointlessly: the delete's identity-map synchronisation walks the pending
    rows, so a bulk import (which never has anything to replace) pays it for
    every proof and degrades as its transaction grows.
    """
    if replace:
        # The delete runs as a statement, so it is on the wire before any of the
        # ORM inserts below — which flush later — can reach it.
        clear_proof_lines(session, [proof.id])

    # Safe to key by identity: `cited_proofs` holds every proof it names for the
    # duration of the call, so no entry can outlive its object.
    cited = {id(engine): pid for engine, pid in cited_proofs}
    # A compiled definition carries no row id (it is built from the spec), so an
    # applied one is matched back by the pair that identifies it in the term
    # graph too: its higher template and the sort it inhabits. Template alone
    # would not do — two definitions may share one across different sorts.
    definition_ids = {
        (row.higher, row.symbol.name): row.id for row in system.definitions
    }
    rows: list[ProofLineRow] = []
    # Engine lines are identified by object id: `ProofLine` has no natural key,
    # and `list.index` on `proof_lines` would be quadratic (and wrong for two
    # equal-text lines, since `ProofLine.__eq__` is identity but `index` is not
    # guaranteed to be the line we mean).
    row_of: dict[int, ProofLineRow] = {}

    for position, line in enumerate(engine_proof.proof_lines):
        line_type = line.line_type
        row = ProofLineRow(
            proof_id=proof.id,
            position=position,
            number=line.number,
            indent=line.indent,
            display=line.display,
            line_type=line_type.name if line_type is not None else None,
            behaviour=line_type.behaviour if line_type is not None else None,
            label=line.label,
            reference=line.reference_string_display,
            rule=line.inference_rule.label if line.inference_rule is not None else None,
            definition_id=_definition_id(line, definition_ids),
            term=_line_term(session, system, line),
            valid=bool(line.valid),
            invalid_message=line.invalid_message,
            failure_code=line.failure.code if line.failure is not None else None,
            failure_detail=line.failure.as_dict() if line.failure is not None else None,
            warning_message=line.warning_message,
            opens_scope=line.opened_scope.kind if line.opened_scope is not None else None,
        )
        session.add(row)
        rows.append(row)
        row_of[id(line)] = row

    # The scope and antecedent links point at other line rows, so they are wired
    # in a second pass — a line may cite one written after it only in the sense
    # that every row must exist first.
    for line, row in zip(engine_proof.proof_lines, rows):
        # A subproof's opener is recorded in the *enclosing* scope, not in the
        # one it opens: a discharge names the subproof from outside by citing the
        # opener, and it keeps the scope chain a tree that terminates when walked
        # upward (a line pointing at itself would not).
        scope = line.opened_scope.parent if line.opened_scope is not None else line.scope
        opener = scope.assumption if scope is not None else None
        if opener is not None:
            row.scope = row_of.get(id(opener))
        row.antecedents = list(_antecedent_rows(line, row_of, cited))

    return rows


def load_proof_lines(
    session: Session,
    proof_ids: Sequence[uuid.UUID],
    system: EngineSystem,
    context: Context,
) -> dict[uuid.UUID, EngineProof]:
    """Rebuild several checked proofs' citable lines from their stored rows.

    The inverse of :func:`store_proof_lines`, and what the rows were written for:
    a proof citing these as lemmas needs their numbered lines and formulae, and
    all of that is stored — so it needs no source text, no parse, and no
    re-check. This is the read half of ``docs/verification-from-rows.md``'s P1.

    **Batched deliberately.** Reading a proof back costs a couple of round trips
    and almost no CPU, so done one proof at a time it is *latency* — and against
    a short proof in a small grammar that loses to simply re-parsing it. Taking
    the whole reference closure at once makes it two queries for the lot, which
    is what makes reading rows beat re-parsing however many lemmas are cited.

    What comes back is each proof as a **citable surface**, not a re-checkable
    object. The lines carry their formulae, types and verdicts; they do not carry
    the antecedent edges or scope tree that justified them, because nothing here
    re-derives a verdict that was already recorded — the citing proof reads a
    cited line's formula and nothing else. ``valid`` and ``has_warnings`` are read
    off the lines rather than off ``proofs``, which is exactly how
    ``FormalSystem.check_proof`` defines them and cannot disagree with the
    structure being returned.

    A proof with no stored lines is **absent from the result**: it has never been
    verified, or its snapshot was invalidated. Either way it is not a usable
    lemma, and saying so is the whole guarantee — a proof may rest only on a
    lemma that stands.
    """
    if not proof_ids:
        return {}

    rows = list(
        session.scalars(
            select(ProofLineRow)
            .where(ProofLineRow.proof_id.in_(proof_ids))
            .order_by(ProofLineRow.proof_id, ProofLineRow.position)
        )
    )
    if not rows:
        return {}

    # One sweep for every term of every proof, before any of it is walked:
    # rebuilding a term through lazy relationships costs a query per node, which
    # is what would make reading rows slower than the parse they replace. The
    # graph memoises as it rebuilds, and term rows are interned per system, so a
    # subterm shared across a proof's lines — or across the proofs citing it — is
    # built once for the batch.
    graph = prefetch_terms(
        session, [row.term_id for row in rows if row.term_id is not None]
    )
    line_types = {line_type.name: line_type for line_type in system.line_types}

    proofs: dict[uuid.UUID, EngineProof] = {}
    for row in rows:
        proof = proofs.get(row.proof_id)
        if proof is None:
            proof = proofs[row.proof_id] = EngineProof(formal_system=system)
        _adopt_verdict(
            proof, _load_line(proof, row, line_types, context, graph), row
        )

    for proof in proofs.values():
        proof.valid = all(line.valid for line in proof.proof_lines)
        proof.has_warnings = any(
            line.warning_message is not None for line in proof.proof_lines
        )
    return proofs


@dataclass(frozen=True)
class PendingCitations:
    """What a proof's citations still want from the database, in two parts.

    Returned by ``load_proof_for_check``'s ``resolve_citations`` hook: the term
    roots the caller needs, and what to do once they have been loaded. Two parts
    rather than one callback because a proof's own lines need a sweep anyway, and
    the whole point is that there be *one* — so the caller has to be able to name
    its roots before any term is built, and to be handed the result after.

    That it can is a fact about the schema rather than about this interface: a
    line's citation is ``proof_lines.reference``, a plain column, so what a proof
    cites — and therefore which theorems, and therefore which of their terms — is
    settled by rows alone.
    """

    term_ids: Sequence[uuid.UUID]
    resolve: Callable[[TermGraph], None]


def load_proof_for_check(
    session: Session,
    proof_id: uuid.UUID,
    system: EngineSystem,
    context: Context,
    proof: EngineProof | None = None,
    resolve_citations: Callable[[Sequence[str | None]], PendingCitations] | None = None,
) -> EngineProof | None:
    """Rebuild a proof from its rows *for re-checking*, with no parse at all.

    ``docs/verification-from-rows.md``'s P2, and where the contract inversion
    actually lands. `FormalSystem.read_line` reads four things off the grammar —
    the line type, the formula as a term, its flat string, and the citation
    string — and every one of them is stored, so a proof that has been checked
    once needs the text for nothing. The lines are populated from the rows and
    handed to `FormalSystem.check_proof`, which numbers, scopes and justifies
    them exactly as it does after a parse.

    Note what is *not* taken from the rows: the verdict. Numbering, scope and
    justification are all re-derived, so a stored row cannot assert a line valid
    — it can only supply what the line says. That is what keeps this a check and
    not a cache read, and it is why re-verifying is idempotent rather than
    merely repeatable.

    Pass ``proof`` to supply one with its ``reference_context`` already seeded
    (the lemmas it may cite). ``None`` back means the proof has no stored lines:
    it has never been checked, or its snapshot was invalidated, so there is
    nothing to check and the caller must parse.

    ``resolve_citations`` is how a system with an unbounded library gets its
    theorems into the same term sweep as the proof's own lines. It is handed the
    stored citations — before any line is built, because a citation is a column
    and needs no term to be read — and returns the roots it wants plus what to do
    with them (see :class:`PendingCitations`).
    """
    rows = list(
        session.scalars(
            select(ProofLineRow)
            .where(ProofLineRow.proof_id == proof_id)
            .order_by(ProofLineRow.position)
        )
    )
    if not rows:
        return None

    pending = (
        None if resolve_citations is None
        else resolve_citations([row.reference for row in rows])
    )
    # One sweep for the proof's lines *and* whatever its citations resolved to.
    # Two sweeps was two recursive closures over `term_children` for one check,
    # and they share far more than they do not: a lemma's statement is a line of
    # the proof citing it, interned to the very same row.
    roots = [row.term_id for row in rows if row.term_id is not None]
    if pending is not None:
        roots.extend(pending.term_ids)
    graph = prefetch_terms(session, roots)
    line_types = {line_type.name: line_type for line_type in system.line_types}

    if proof is None:
        proof = EngineProof(formal_system=system)
    for row in rows:
        _load_line(proof, row, line_types, context, graph)

    if pending is not None:
        pending.resolve(graph)
    return system.check_proof(proof, context)


def _load_line(
    proof: EngineProof,
    row: ProofLineRow,
    line_types: dict[str, LineType],
    context: Context,
    graph: TermGraph,
) -> EngineProofLine:
    # `indent` and `display` are stored apart precisely so the source line
    # reconstructs; ProofLine derives its own `indent` and `empty` from text.
    line = EngineProofLine(
        proof=proof,
        text=" " * row.indent + row.display,
        context=context,
        reference_string=row.reference,
        label=row.label,
    )
    line.line_type = line_types.get(row.line_type) if row.line_type else None
    if row.term_id is not None:
        # The flat string the string-rewriting path reads is *derived* from the
        # term (ProofLine.formula_string), so it is neither stored a second time
        # nor guessed at here — this used to ask whether the system had a
        # string-matching rule, which a promoted theorem is not.
        term = graph.term(row.term_id, context)
        if term is None:
            raise LookupError(
                f"Proof line {row.id} names term {row.term_id}, which has no row."
            )
        line.formula_term = term
    proof.proof_lines.append(line)
    return line


def _adopt_verdict(proof: EngineProof, line: EngineProofLine, row: ProofLineRow) -> None:
    """Take the line's *recorded* verdict and citation number from its row.

    For a lemma, which is read to be cited and never re-checked. A proof being
    re-checked instead has `FormalSystem.check_proof` derive both — the number
    through `assign_line_number`, so it agrees with the scope tree being built
    beside it.
    """
    line.valid = row.valid
    line.invalid_message = row.invalid_message
    line.failure = failure_from_row(row)
    line.warning_message = row.warning_message
    line.number = row.number

    if row.number is not None:
        proof.numbered_lines.append(line)
        if row.number != len(proof.numbered_lines):
            # `get_proof_line` indexes `numbered_lines[n - 1]`, so a gap here
            # would silently resolve a citation to the wrong line. Rows are
            # written in the order numbers were assigned, so this cannot happen —
            # raise rather than let it pass if it ever does.
            raise ValueError(
                f"Proof {row.proof_id}: line numbering is not contiguous "
                f"({row.number} at position {len(proof.numbered_lines)})."
            )
    if row.label is not None:
        # What `ProofLine.execute` does for a labelled line: its own proof cites
        # it by name, and a proof citing into this one may too.
        proof.reference_context[row.label] = line


def _mapping_list(value: object) -> list[dict]:
    # A stored list of records, or nothing. See `failure_from_row` on why a
    # malformed detail is dropped rather than raised on.
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def failure_from_row(row: ProofLineRow) -> Failure | None:
    """Rebuild a line's :class:`Failure` from its stored columns.

    The detail is stored as the JSON `Failure.as_dict` produces, so this is that
    shape read back. Nothing here raises on a detail that is not that shape: a row
    written by an older build carries fewer keys, one written by a newer build
    carries more, and a *diagnosis* must never be the thing that stops a proof
    loading. A malformed slot is dropped rather than guessed at.
    """
    if row.failure_code is None:
        return None
    detail = row.failure_detail if isinstance(row.failure_detail, dict) else {}
    slots = tuple(
        SlotReport(
            index=int(slot["index"]),
            schema=str(slot["schema"]),
            candidates=tuple(_int_list(slot.get("candidates"))),
        )
        for slot in _mapping_list(detail.get("slots"))
        if "index" in slot and "schema" in slot
    )
    return Failure(
        # Narrowed at a trust boundary: the column is text and the vocabulary is
        # a Literal. A code this build does not know still round-trips as data.
        code=row.failure_code,  # type: ignore[arg-type]
        message=row.invalid_message or str(detail.get("message", "")),
        rule=detail.get("rule"),
        reference=detail.get("reference"),
        lines=tuple(int(n) for n in _int_list(detail.get("lines"))),
        expected=detail.get("expected"),
        given=detail.get("given"),
        slots=slots,
        proviso=detail.get("proviso"),
        definitions=tuple(str(name) for name in _str_list(detail.get("definitions"))),
    )


def _definition_id(
    line: ProofLine, definition_ids: dict[tuple[str, str], uuid.UUID]
) -> uuid.UUID | None:
    """The row id of the definition this line applied, or ``None`` if it applied
    none. A miss means the system's rows no longer describe the definition the
    check used — the attribution is dropped rather than guessed at.

    An applied definition is a kernel one, so its defined form is a *term*: its
    surface string is the stored ``higher`` template (rendering a schema spells
    each parameter by name, which is how the template was written), and the sort
    it inhabits is the stored symbol."""
    definition = line.applied_definition
    if definition is None:
        return None

    higher = definition.higher
    # A node records a `sort` only when its constructor is not itself a member of
    # the sort it inhabits — which is exactly what a defined form is — so falling
    # back to the constructor's own name covers the rest.
    sort_name = higher.sort.name if higher.sort is not None else higher.constructor.name
    return definition_ids.get((higher.to_string(), sort_name))


def _line_term(
    session: Session, system: FormalSystem, line: ProofLine
) -> TermRow | None:
    """The line's formula as an interned term row, or ``None`` if it bears none.

    A blank line, commentary, and a line that matched no line type all have no
    formula — those are stored with a null term rather than skipped, so the rows
    still reconstruct the source line for line.

    The line already holds its kernel term: the parser hands the parse to the
    kernel as it goes, so there is no ``Match`` left here to project.
    """
    if line.formula_term is None:
        return None
    return store_term(session, system, line.formula_term)


def _antecedent_rows(
    line: ProofLine,
    row_of: dict[int, ProofLineRow],
    cited: dict[int, uuid.UUID],
) -> Iterator[ProofLineAntecedentRow]:
    """The justification edges of one line, in citation order.

    Declared antecedent slots first, then any surplus lines the rule tolerated,
    then the subproof a discharge consumed (recorded by its opener, since a
    discharge cites a block).
    """
    sources = [
        *((ANTECEDENT_ROLE_ANTECEDENT, ant) for ant in line.antecedents),
        *((ANTECEDENT_ROLE_EXTRA, ant) for ant in line.extra_antecedents),
    ]
    discharged = line.discharged_scope
    if discharged is not None and discharged.assumption is not None:
        sources.append((ANTECEDENT_ROLE_SUBPROOF, discharged.assumption))

    for position, (role, antecedent) in enumerate(sources):
        edge = ProofLineAntecedentRow(position=position, role=role)
        own_row = row_of.get(id(antecedent))
        if own_row is not None:
            edge.antecedent_line = own_row
        else:
            # A line of a cited lemma. Its proof id may be absent if the caller
            # seeded a proof it did not identify; the citation number alone still
            # records what was cited.
            edge.antecedent_proof_id = cited.get(id(antecedent.proof))
            edge.antecedent_number = antecedent.number
        yield edge
