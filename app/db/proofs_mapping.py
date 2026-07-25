"""Project a checked engine :class:`Proof` into ``proof_lines`` rows.

The counterpart to :mod:`app.db.systems_mapping` on the proof side, and the
consumer of :mod:`app.db.terms_mapping` on the storage side: where a system is
rebuilt *from* rows, a proof's structure is written *to* them once the engine has
checked it. Each formula-bearing line already carries its kernel term — the
parser hands the parse to the kernel as it goes — so storing a proof is interning
those terms into the system's shared term graph, landing a proof's statements in
the same DAG the theorem search indexes.

The snapshot is derived from ``proofs.source``, never authoritative:
:func:`clear_proof_lines` drops it wherever the cached verdict is invalidated,
and the next verify rewrites it. Two calls therefore replace rather than
accumulate.

Synchronous (a :class:`~sqlalchemy.orm.Session`), like ``terms_mapping`` — the
async routes reach it through ``AsyncSession.run_sync``.
"""

from __future__ import annotations

import uuid
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
from app.db.terms_mapping import store_term

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from app.db.models import FormalSystem, Proof
    from website.logical.formal_system.proof import Proof as EngineProof
    from website.logical.formal_system.proof import ProofLine

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
) -> list[ProofLineRow]:
    """Replace ``proof``'s stored structure with ``engine_proof``'s.

    ``system`` is the row the terms are interned against — the proof's own formal
    system, passed in because the caller already has it loaded.

    ``cited_proofs`` pairs each *other* proof whose lines this one may cite (the
    lemmas seeded into ``reference_context``) with its stored id. A citation
    reaching into one of those is recorded by proof id and citation number rather
    than by a foreign key, since that proof owns its own line rows.
    """
    # The delete runs as a statement, so it is on the wire before any of the ORM
    # inserts below — which flush later — can reach it.
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
