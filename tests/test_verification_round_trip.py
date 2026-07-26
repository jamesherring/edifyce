"""Checking a proof from its rows is the *same* check as parsing it.

Two bugs found in review shared one shape, and this module exists because a
third would mean the shape was never really covered
(``docs/verification-from-rows.md``, P2). Both were a verdict the parse path
reaches by noticing something is **missing** — a line matching no line type, a
line whose formula would not project — which the row path could not reach,
because a row records the absence without the reason for it. Both let a proof
that had failed come back *valid*.

So rather than more hand-picked cases, two properties:

* **Agreement.** Compose proofs from a pool of line shapes and check every one
  both ways. The parse path and the row path must agree on every field of every
  line, not merely on the verdict — a line agreeing by accident hides a
  divergence in the one beside it.
* **Monotonicity.** Take away part of a stored line and re-check. Removing
  information must never make a proof *more* valid. This is the bug class stated
  directly: an absence in a row must never be read as assent, whatever the
  absence and whichever line it is on.

Run against the engine and the mapping rather than through the API, so a few
hundred proofs cost a second rather than a minute.
"""

from __future__ import annotations

import itertools
from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system, store_proof_lines
from app.db.models import FormalSystem, Proof, ProofFolder
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.proofs_mapping import load_proof_for_check
from app.db.side_conditions import SideConditionRow
from app.db.systems import (
    AxiomBindingRow,
    AxiomRow,
    BracketRow,
    DefinitionBindingRow,
    DefinitionFreshRow,
    DefinitionRow,
    LinePartRow,
    LineRow,
    ProductionBindingRow,
    ProductionBindingScopeRow,
    RuleAntecedentRow,
    RuleBindingRow,
    RuleRow,
    SymbolRow,
)
from app.db.systems_mapping import system_to_spec
from app.db.terms import TermChildRow, TermRow
from tests.zfc_systems import scoped_zfc_spec
from website.logical.declarative import build_spec

_TABLES = [
    model.__table__
    for model in (
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow,
        RuleRow, RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, TermRow, TermChildRow,
        ProofLineRow, ProofLineAntecedentRow,
    )
]

# Line shapes to compose proofs from. Chosen to span what the checker can decide
# about a line — and, deliberately, the ways a line can fail *quietly*: matching
# no line type at all, or matching one and citing nothing that resolves. A pool
# of proofs that only fail loudly is exactly what missed both bugs.
_SHAPES = {
    "membership": "x ∈ y [R, 1]",
    "hypothesis": "assume x ∈ y",
    "variable": "let z",
    "discharge": "(x ∈ y → x ∈ y) [CP, 1]",
    "generalise": "∀z x ∈ y [UG, 1]",
    "unparseable": "this is not a formula",
    "unknown-rule": "x ∈ y [NOPE]",
    "absent-line": "x ∈ y [R, 99]",
    "no-citation": "x ∈ y",
    "blank": "",
    "indented": "    x ∈ y [R, 1]",
}


@pytest.fixture(scope="module")
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    return engine


@pytest.fixture(scope="module")
def system(engine):
    """One stored system, compiled once: the proofs are what vary."""
    with Session(engine) as session:
        row = spec_to_system(scoped_zfc_spec())
        session.add(row)
        session.commit()
        built = build_spec(system_to_spec(row))["system"]
        context = copy(built.context)
        context.variables.update(built.build_context.variables)
        return row.id, built, context


def _fingerprint(proof) -> list[tuple]:
    """Everything the checker decided about every line, in source order.

    The whole line, not the verdict: a divergence usually shows first in *which*
    rule justified a line or where it landed in the scope tree, and only later
    in whether the proof stands.
    """
    numbers = {id(line): line.number for line in proof.proof_lines}
    return [
        (
            line.number,
            line.display,
            line.indent,
            line.line_type.name if line.line_type is not None else None,
            line.valid,
            line.invalid_message,
            line.warning_message,
            line.inference_rule.label if line.inference_rule is not None else None,
            line.formula_term.to_string() if line.formula_term is not None else None,
            tuple(numbers.get(id(a)) for a in line.antecedents),
            line.opened_scope.kind if line.opened_scope is not None else None,
            numbers.get(id(line.scope.assumption)) if line.scope is not None
            and line.scope.assumption is not None else None,
        )
        for line in proof.proof_lines
    ]


def _round_trip(engine, system, source: str, name: str):
    """Check ``source`` by parsing it, store that, then check it from the rows."""
    system_id, built, context = system
    with Session(engine) as session:
        parsed = built.parse(source)

        proof_row = Proof(
            formal_system_id=system_id, name=name, slug=name, source=source
        )
        session.add(proof_row)
        session.flush()
        system_row = session.get(FormalSystem, system_id)
        store_proof_lines(session, proof_row, system_row, parsed, replace=False)
        session.commit()

        loaded = load_proof_for_check(session, proof_row.id, built, context)
        return parsed, loaded, proof_row.id


def _sources() -> list[tuple[str, str]]:
    # Every shape alone and every ordered pair, plus the three-line combinations
    # that need a subproof to be opened *and* closed — a discharge is the one
    # thing a shorter proof cannot exercise.
    names = list(_SHAPES)
    cases = [(n, _SHAPES[n]) for n in names]
    cases += [
        (f"{a}+{b}", f"{_SHAPES[a]}\n{_SHAPES[b]}")
        for a, b in itertools.product(names, repeat=2)
    ]
    cases += [
        (f"scoped:{tail}", f"assume x ∈ y\n    x ∈ y [R, 1]\n{_SHAPES[tail]}")
        for tail in names
    ]
    cases += [
        (f"var-scoped:{tail}", f"let z\n    x ∈ y [R, 1]\n{_SHAPES[tail]}")
        for tail in names
    ]
    return cases


@pytest.mark.parametrize("name,source", _sources(), ids=lambda v: v if isinstance(v, str) else "")
def test_the_row_path_agrees_with_the_parse_path(engine, system, name, source):
    slug = name.replace("+", "-").replace(":", "-")
    parsed, loaded, _ = _round_trip(engine, system, source, slug)

    assert loaded is not None, "a checked proof stored no lines"
    assert _fingerprint(loaded) == _fingerprint(parsed)
    assert loaded.valid == parsed.valid
    assert loaded.has_warnings == parsed.has_warnings


# The columns a line's *content* lives in. Nulling one is what a failed parse
# leaves behind — a line type with no term, or no line type at all — and is the
# shape both review bugs took.
_ERASURES = ("term_id", "line_type")


@pytest.mark.parametrize("column", _ERASURES)
@pytest.mark.parametrize(
    "name,source",
    [
        # Proofs that actually stand, so an erasure has something to take away.
        ("conditional", "assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → x ∈ y) [CP, 1]"),
        # Nested: a fresh variable *and* an assumption, discharged by UG over CP,
        # so erasure is measured against a scope tree more than one deep.
        (
            "generalised",
            "let x\n"
            "    assume x ∈ c\n"
            "        x ∈ c [R, 2]\n"
            "    (x ∈ c → x ∈ c) [CP, 2]\n"
            "∀x (x ∈ c → x ∈ c) [UG, 1]",
        ),
    ],
)
def test_erasing_a_line_never_makes_a_proof_more_valid(engine, system, name, source, column):
    """The bug class, stated directly.

    Take a proof that stands, remove one line's content from its row, and check
    it again. A row that has *lost* information must never buy a line a verdict
    it could not have earned — which is precisely what a null line type, and
    then a null term, each did in turn.
    """
    system_id, built, context = system
    _parsed, loaded, proof_id = _round_trip(
        engine, system, source, f"erase-{name}-{column}"
    )
    assert loaded.valid is True, "the base proof must stand for erasure to mean anything"

    with Session(engine) as session:
        positions = list(
            session.scalars(
                select(ProofLineRow.position)
                .where(ProofLineRow.proof_id == proof_id)
                .order_by(ProofLineRow.position)
            )
        )

    for position in positions:
        with Session(engine) as session:
            before = session.scalars(
                select(ProofLineRow).where(
                    ProofLineRow.proof_id == proof_id,
                    ProofLineRow.position == position,
                )
            ).one()
            erased = getattr(before, column)
            if erased is None:
                continue  # nothing to take away on this line
            session.execute(
                update(ProofLineRow)
                .where(ProofLineRow.proof_id == proof_id,
                       ProofLineRow.position == position)
                .values(**{column: None})
            )
            session.commit()

            damaged = load_proof_for_check(session, proof_id, built, context)
            assert damaged.valid is False, (
                f"erasing {column} on line {position} left the proof valid"
            )
            assert damaged.proof_lines[position].valid is False, (
                f"erasing {column} on line {position} left that line valid"
            )

            # Put it back, so each erasure is measured against the intact proof.
            session.execute(
                update(ProofLineRow)
                .where(ProofLineRow.proof_id == proof_id,
                       ProofLineRow.position == position)
                .values(**{column: erased})
            )
            session.commit()
