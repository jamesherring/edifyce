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

from collections.abc import Iterator

import itertools
import uuid
from copy import copy
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db import spec_to_system, store_proof_lines
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
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
from tests.database import create_tables, database_url
from tests.zfc_systems import scoped_zfc_spec
from website.logical.declarative import (
    LinePart,
    LineSpec,
    Production,
    Rule,
    SystemSpec,
    build_spec,
)
from website.logical.promotion import TheoremSpec, promote_spec

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system.proof import Proof as EngineProof
    from website.logical.matching.context import Context

    # The compiled system a round trip runs against: its stored id, the engine
    # object built from those rows, and the context stored terms resolve in.
    Compiled = tuple[uuid.UUID, "EngineSystem", "Context"]

_TABLES = [
    model.__table__
    for model in (
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow,
        RuleRow, RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, TermRow, TermChildRow,
        ProofLineRow, ProofLineAntecedentRow,
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
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
def engine(tmp_path_factory) -> Iterator[Engine]:
    # `tmp_path_factory` rather than `tmp_path`: this schema is built once for the
    # module (the system is compiled once and the proofs are what vary), and
    # `tmp_path` is per-test. Nothing else in this module asks for a database, so
    # there is no function-scoped rebuild to drop it out from under these tests.
    url = database_url(tmp_path_factory.mktemp("round-trip"))
    create_tables(url, _TABLES)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def system(engine: Engine) -> Compiled:
    """One stored system, compiled once: the proofs are what vary."""
    with Session(engine) as session:
        row = spec_to_system(scoped_zfc_spec())
        session.add(row)
        session.commit()
        built = build_spec(system_to_spec(row))["system"]
        context = copy(built.context)
        context.variables.update(built.build_context.variables)
        return row.id, built, context


def _fingerprint(proof: EngineProof) -> list[tuple]:
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


def _round_trip(
    engine: Engine, system: Compiled, source: str, name: str
) -> tuple[EngineProof, EngineProof | None, uuid.UUID]:
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
def test_the_row_path_agrees_with_the_parse_path(
    engine: Engine, system: Compiled, name: str, source: str
) -> None:
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
def test_erasing_a_line_never_makes_a_proof_more_valid(
    engine: Engine, system: Compiled, name: str, source: str, column: str
) -> None:
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


# ---------------------------------------------------------------------------
# The string-rewriting regime (P5)
# ---------------------------------------------------------------------------
def _string_system() -> SystemSpec:
    """A system whose *only* string-matching schema is a promoted theorem.

    Deliberately no string-matching **rule**: that is what the row path used to
    ask about when deciding whether to recover a line's flat string, and a
    library entry is not one. `Mx ⊢ Mxx` also needs genuine associative matching
    — it concatenates a variable with itself, which the term unifier cannot
    express — so nothing but the flat string can justify the step.
    """
    return SystemSpec(
        name="Rewrite",
        productions=[Production(sort="w", name="raw", regex="[MIU]+")],
        lines=[LineSpec(
            name="statement", shape="<w> [<reference>]",
            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
            logical_sort="w",
        )],
        axioms=[Rule(label="AX", name="start", antecedents=[], deduction="MI",
                     bindings=[])],
    )


def _with_double(built: EngineSystem) -> EngineSystem:
    built.promote(promote_spec(built, TheoremSpec(
        label="DOUBLE", statement="Mxx", metavariables={"x": "w"},
        premises=("Mx",), matching="string",
    )))
    return built


@pytest.mark.parametrize(
    "source,valid",
    [
        ("MI\nMII [DOUBLE, 1]", True),
        ("MI\nMIII [DOUBLE, 1]", False),
    ],
)
def test_a_string_matched_theorem_checks_the_same_from_rows(
    engine: Engine, source: str, valid: bool
) -> None:
    """A flat string is *derived* from the term, not stored and not guessed at.

    The row path used to decide whether to recover one by asking whether the
    system had a string-matching **inference rule**. A promoted theorem carries
    the same `matching` and is not a rule — and is resolved *after* a proof's
    lines are populated, so the question was being asked before its answer
    existed. A proof that verified when parsed failed when checked from its rows.
    """
    spec = _string_system()
    with Session(engine) as session:
        row = spec_to_system(spec)
        session.add(row)
        session.commit()
        stored = system_to_spec(row)

        parsed = _with_double(build_spec(stored)["system"]).parse(source)
        assert parsed.valid is valid, "the fixture proof lacks its stated verdict"

        proof_row = Proof(
            formal_system_id=row.id, name="rw", slug="rw", source=source
        )
        session.add(proof_row)
        session.flush()
        store_proof_lines(session, proof_row, row, parsed, replace=False)
        session.commit()

        built = _with_double(build_spec(stored)["system"])
        context = copy(built.context)
        context.variables.update(built.build_context.variables)
        loaded = load_proof_for_check(session, proof_row.id, built, context)

    assert _fingerprint(loaded) == _fingerprint(parsed)
    assert loaded.valid is parsed.valid


def test_a_rendered_formula_string_is_the_one_the_parse_recorded(
    engine: Engine, system: Compiled
) -> None:
    """What makes deriving the string sound rather than merely convenient.

    A term renders through its constructor's template pieces and a ground leaf
    renders its own literal, so a render can only differ from the source if a
    template *literal* matched text it does not equal — and the matcher accepts
    no such spelling. Asserted here rather than argued for, over every line shape
    the round trip already composes proofs from.
    """
    _system_id, built, _context = system
    checked = 0
    for _name, source in _sources():
        for line in built.parse(source).proof_lines:
            if line.formula_term is None:
                continue
            checked += 1
            # `_formula_string` is what the parse recorded; the property falls
            # back to the render only when it is absent.
            assert line._formula_string == line.formula_term.to_string()
    assert checked > 0, "no formula-bearing line was examined"
