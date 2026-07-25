"""Project a checked engine :class:`Proof` into ``proof_lines`` rows.

The counterpart to :mod:`app.db.systems_mapping` on the proof side, and the
consumer of :mod:`app.db.terms_mapping` on the storage side: where a system is
rebuilt *from* rows, a proof's structure is written *to* them once the engine has
checked it. Each formula-bearing line is projected to a kernel term
(:func:`~website.logical.kernel.terms.from_match`) and interned into the system's
shared term graph, so a proof's statements land in the same DAG the theorem
search indexes.

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
from sqlalchemy.orm import Session

from app.db.terms import TermRow

from app.db.proof_lines import (
    ANTECEDENT_ROLE_ANTECEDENT,
    ANTECEDENT_ROLE_EXTRA,
    ANTECEDENT_ROLE_SUBPROOF,
    ProofLineAntecedentRow,
    ProofLineRow,
)
from app.db.terms_mapping import store_term
from website.logical.kernel.terms import from_match

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


def _line_term(
    session: Session, system: FormalSystem, line: ProofLine
) -> TermRow | None:
    """The line's formula as an interned term row, or ``None`` if it bears none.

    A blank line, commentary, and a line that matched no line type all have no
    formula — those are stored with a null term rather than skipped, so the rows
    still reconstruct the source line for line.
    """
    if line.formula is None:
        return None
    return store_term(session, system, from_match(line.formula, line.context))


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
