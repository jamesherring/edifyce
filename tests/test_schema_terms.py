"""A build that reads stored schema terms is the *same* build.

P3 moves a rule's schema-template parse off the read path by storing the term it
composes to (``app/db/schema_terms.py``). Two things have to hold, and they pull
in opposite directions:

* **Agreement.** A system built from stored terms must be indistinguishable from
  one built by composing them — the same term at every slot, and the same
  verdicts on the same proofs. Anything less and a cached system checks proofs a
  cold one would not.
* **Inertness.** A stored term that no longer matches its system must not be
  read. The digest is what decides that, so what these tests actually pin down is
  the digest's *reach*: every edit that can change a composed term must change
  the digest that guards it.

The second is where P1 and P2 each went wrong, in the same shape both times: a
stored value that had stopped being true was believed anyway. The difference here
is that the fallback is composing the template again — the very thing the build
did before any of this — so a *missed* cache costs time, and only a wrongly-*hit*
one could cost correctness.
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system
from app.db.models import FormalSystem, OAuthAccount, Proof, ProofFolder, User
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
from app.db.schema_terms import load_schema_terms, store_schema_terms
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
from app.db.terms_mapping import digest_term
from tests.database import enable_foreign_keys
from tests.miu_system import miu_spec
from tests.zfc_systems import scoped_zfc_spec
from website.logical.declarative import build_spec, schema_digests
from website.logical.matching import StringPattern

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from website.logical.declarative import SystemSpec
    from website.logical.formal_system import FormalSystem as EngineSystem

_TABLES = [
    model.__table__
    for model in (
        # `users` is here only because foreign keys are enforced below and
        # `formal_systems.owner_id` points at it; nothing here authors an account.
        User, OAuthAccount,
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow,
        RuleRow, RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, TermRow, TermChildRow,
        ProofLineRow, ProofLineAntecedentRow,
    )
]


def hilbert_spec() -> SystemSpec:
    """A Hilbert-style propositional system: nested axioms, one detachment rule.

    Deliberately unlike the ZFC fixture. Its rule schemas nest two levels
    (``(p → (q → p))``), which is what composition exists for — a flat projection
    of that template would be one production, not three — and it declares no
    subproof at all, so the discharge slots are exercised as *absent* rather than
    merely unused.
    """
    from website.logical.declarative import (
        LinePart, LineSpec, Production, Rule, SystemSpec,
    )

    return SystemSpec(
        name="Hilbert",
        brackets=[("(", ")")],
        productions=[
            Production(sort="formula", name="atom", atom_base="p"),
            Production(sort="formula", name="implication", template="(a → b)",
                       bindings=[("a", "formula"), ("b", "formula")]),
            Production(sort="formula", name="negation", template="¬a",
                       bindings=[("a", "formula")]),
        ],
        lines=[LineSpec(
            name="statement",
            shape="<formula> [<reference>]",
            parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.]+")],
            logical_sort="formula",
        )],
        axioms=[
            Rule(label="A1", name="axiom one", antecedents=[],
                 deduction="(p → (q → p))",
                 bindings=[("p", "formula"), ("q", "formula")]),
        ],
        rules=[
            Rule(label="HYP", name="hypothesis", antecedents=[], deduction="p",
                 bindings=[("p", "formula")]),
            Rule(label="MP", name="modus ponens",
                 antecedents=["(p → q)", "p"], deduction="q",
                 bindings=[("p", "formula"), ("q", "formula")]),
            Rule(label="HS", name="hypothetical syllogism",
                 antecedents=["(p → q)", "(q → r)"], deduction="(p → r)",
                 bindings=[("p", "formula"), ("q", "formula"), ("r", "formula")]),
        ],
    )


# One entry per system the round trip is exercised against. MIU is here because
# its rules are string-matching: they carry schemas like every other rule and are
# stored the same way, but nothing ever unifies against the terms — so it is the
# case where the cache must be *harmless* rather than useful.
_SYSTEMS = {
    "zfc": scoped_zfc_spec,
    "hilbert": hilbert_spec,
    "miu": miu_spec,
}


@pytest.fixture()
def engine(tmp_path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'schema-terms.db'}")
    # Before the first connection is opened: SQLite takes the pragma per
    # connection, and the pool hands out the one `create_all` made.
    enable_foreign_keys(engine)
    Base.metadata.create_all(engine, tables=_TABLES)
    return engine


def _schemas(built: EngineSystem) -> list[tuple]:
    """Every rule-schema term of a built system, as comparable digests.

    Terms are interned per process, so two builds of the same system return the
    *same* object at each slot and `is` would pass without proving anything about
    what was stored. Digested rather than rendered, because rendering shows the
    surface notation and not the constructor behind it — two grammars that spell
    a connective the same way compose to terms that print identically and unify
    differently, which is exactly the divergence worth catching.
    """
    rendered = []
    for rule in built.inference_rules:
        subproof = rule.subproof_schema
        patterns = [
            ("deduction", rule.deduction),
            *((f"antecedent{i}", p) for i, p in enumerate(rule.antecedents)),
            ("derive", None if subproof is None else subproof.conclusion),
            ("assume", None if subproof is None else subproof.assumption),
            ("fresh", None if subproof is None else subproof.fresh),
        ]
        rendered.append((
            rule.label,
            tuple(
                (
                    slot,
                    None
                    if not isinstance(p, StringPattern) or p.schema_term is None
                    else digest_term(p.schema_term),
                )
                for slot, p in patterns
            ),
        ))
    return rendered


def _store(engine: Engine, spec: SystemSpec) -> None:
    """Store ``spec``, build it cold, and write back the terms that build composed."""
    with Session(engine) as session:
        row = spec_to_system(spec)
        session.add(row)
        session.flush()
        spec_now = system_to_spec(row)
        cache = load_schema_terms(session, row, spec_now)
        built = build_spec(spec_now)["system"]
        store_schema_terms(session, row, built, cache)
        session.commit()


def _rebuild(engine: Engine) -> tuple[EngineSystem, int]:
    """Build the stored system *through* the cache, and say how many slots it served."""
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec = system_to_spec(row)
        source = load_schema_terms(session, row, spec)
        built = build_spec(spec, schema_terms=source)["system"]
        assert "errors" not in build_spec(spec), "the fixture system must build"
        return built, len(source)


@pytest.mark.parametrize("name", list(_SYSTEMS))
def test_a_cached_build_composes_the_same_terms(engine: Engine, name: str) -> None:
    spec = _SYSTEMS[name]()
    cold = build_spec(spec)["system"]

    _store(engine, spec)
    warm, served = _rebuild(engine)

    assert served > 0, "nothing was stored, so the comparison proves nothing"
    assert _schemas(warm) == _schemas(cold)


@pytest.mark.parametrize(
    "name,source,valid",
    [
        # A proof that stands, and one that does not, per system: agreement on
        # the verdict is only worth something if both verdicts are reachable.
        ("zfc", "assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → x ∈ y) [CP, 1]", True),
        ("zfc", "assume x ∈ y\n    x ∈ y [R, 1]\n(x ∈ y → ¬x ∈ y) [CP, 1]", False),
        ("hilbert", "p_0 [HYP]\n(p_0 → p_1) [HYP]\np_1 [MP, 2, 1]", True),
        ("hilbert", "p_0 [HYP]\n(p_0 → p_1) [HYP]\np_2 [MP, 2, 1]", False),
        ("miu", "MI\nMII [R2, 1]", True),
        ("miu", "MI\nMIII [R2, 1]", False),
    ],
)
def test_a_cached_build_checks_proofs_the_same(
    engine: Engine, name: str, source: str, valid: bool
) -> None:
    spec = _SYSTEMS[name]()
    _store(engine, spec)
    warm, _served = _rebuild(engine)

    cold_proof = build_spec(spec)["system"].parse(source)
    warm_proof = warm.parse(source)

    assert cold_proof.valid is valid, "the fixture proof does not have its stated verdict"
    assert warm_proof.valid is cold_proof.valid
    assert [line.valid for line in warm_proof.proof_lines] == [
        line.valid for line in cold_proof.proof_lines
    ]


# Edits that must all reach the digest. Each takes a spec and changes one thing
# that composition reads, in a way that leaves the system still buildable — the
# point is that a stale term is *not consulted*, not that the build fails.
def _retemplate(spec: SystemSpec) -> None:
    """A production's notation: the same template now parses to a different tree."""
    implication = next(p for p in spec.productions if p.name == "implication")
    implication.template = "(a ⊃ b)"


def _rename_production(spec: SystemSpec) -> None:
    """A production's *name*, which is the constructor a stored term cites."""
    implication = next(p for p in spec.productions if p.name == "implication")
    implication.name = "arrow"


def _add_production(spec: SystemSpec) -> None:
    """A new member of the sort, which a template may now parse through instead."""
    from website.logical.declarative import Production

    spec.productions.append(
        Production(sort="formula", name="conjunction", template="(a ∧ b)",
                   bindings=[("a", "formula"), ("b", "formula")])
    )


def _drop_brackets(spec: SystemSpec) -> None:
    """The bracket *declaration*, which the build derives the real map from.

    Undeclaring `()` on a system that writes parens changes nothing: the build
    falls back to them anyway. So this is the case for digesting the derived map
    rather than what the author wrote — the terms stay valid and stay read.
    """
    spec.brackets = []


def _retemplate_rule(spec: SystemSpec) -> None:
    """A rule's own schema, leaving every other rule's alone."""
    spec.rules[0].deduction = "¬" + spec.rules[0].deduction


def _rebind_rule(spec: SystemSpec) -> None:
    """A rule's metavariables — same template text, different schematic reading."""
    spec.rules[0].bindings = [(var, sort) for var, sort in spec.rules[0].bindings][:-1]


# Each edit, paired with whether it is known to *move* a schema term in this
# fixture. The flag is asserted too: an edit that starts or stops moving one is a
# change in what composition depends on, and this is where that should surface
# rather than in a stale term nobody notices.
_EDITS = [
    (_retemplate, True),
    (_rename_production, True),
    (_add_production, False),
    (_drop_brackets, False),
    (_retemplate_rule, True),
    (_rebind_rule, False),
]


@pytest.mark.parametrize("edit,moves", _EDITS, ids=lambda v: getattr(v, "__name__", ""))
def test_an_edit_that_changes_a_schema_term_changes_its_digest(edit, moves) -> None:
    """The guard's reach, checked against composition itself.

    For each edit: compose both ways and compare. Wherever a term *moved*, its
    rule's digest must have moved too — otherwise the stored term would be
    served for a system it no longer describes, which is the one way this cache
    can be unsound rather than merely cold. The converse is not required: the
    digest is deliberately coarser than composition, so an edit that leaves every
    term where it was may still invalidate them all.
    """
    before = hilbert_spec()
    after = hilbert_spec()
    edit(after)

    cold = _schemas(build_spec(before)["system"])
    edited = _schemas(build_spec(after)["system"])
    before_digests = schema_digests(before)
    after_digests = schema_digests(after)

    moved = [i for i, (a, b) in enumerate(zip(cold, edited)) if a != b]
    assert bool(moved) is moves, (
        f"{edit.__name__} moves {len(moved)} schema term(s); the case says "
        f"{'it should' if moves else 'it should not'}"
    )
    for index in moved:
        assert before_digests[index] != after_digests[index], (
            f"rule {index} composes differently after {edit.__name__} "
            f"but keeps its digest, so a stale term would be served"
        )


@pytest.mark.parametrize(
    "edit", [_retemplate, _rename_production, _add_production],
    ids=lambda f: f.__name__.lstrip("_"),
)
def test_a_grammar_edit_leaves_every_stored_term_unread(engine: Engine, edit) -> None:
    """End to end: edit the *rows*, and the stored terms stop being served.

    The digest test above works on specs; this one goes through storage, because
    a digest that is right and a lookup that ignores it would still be a bug.
    """
    spec = hilbert_spec()
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        assert len(load_schema_terms(session, row, system_to_spec(row))) > 0

        edited = system_to_spec(row)
        edit(edited)
        # The rows the edit would produce, against the terms already stored.
        replacement = spec_to_system(edited)
        for stored_rule, fresh_rule in zip(row.rules, replacement.rules):
            fresh_rule.schema_digest = stored_rule.schema_digest
            fresh_rule.deduction_term_id = stored_rule.deduction_term_id

        assert len(load_schema_terms(session, replacement, edited)) == 0


def test_storing_is_idempotent(engine: Engine) -> None:
    """A settled system writes nothing on later builds, which is what makes
    storing-on-every-verify affordable."""
    spec = scoped_zfc_spec()
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        current = system_to_spec(row)
        cache = load_schema_terms(session, row, current)
        built = build_spec(current, schema_terms=cache)["system"]
        assert store_schema_terms(session, row, built, cache) == 0


def test_a_rule_whose_template_composes_to_nothing_is_a_hit(engine: Engine) -> None:
    """The expensive miss stays a hit.

    A template nothing parses costs a failed parse at *every* sort, and composes
    to None. Stored as a NULL term id, that is indistinguishable from "never
    composed" — which is exactly why the digest, not the id, is what says whether
    a slot is answered.
    """
    spec = hilbert_spec()
    spec.rules[0].deduction = "q"  # a bare metavariable: no structure to compose
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        loaded = load_schema_terms(session, row, system_to_spec(row))

    from website.logical.build_context import SchemaSlot

    answered = loaded(SchemaSlot(0, "deduction"), None)
    assert answered is not None, "a stored slot with no term must still answer"
    assert answered.term is None


def test_a_system_with_stored_schema_terms_can_still_be_deleted(engine: Engine) -> None:
    """The FKs into ``terms`` must not outlive the system they belong to.

    ``term_children.child_id`` is deliberately NO ACTION, so a system's cascade
    already walks a graph with edges pointing back into it; adding four more
    references from ``rules`` is the kind of thing that turns a working cascade
    into a constraint violation.
    """
    _store(engine, scoped_zfc_spec())

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        # A statement delete, not the ORM cascade: the point is the database's
        # own referential actions, which is what the delete route relies on.
        session.execute(sa_delete(FormalSystem).where(FormalSystem.id == row.id))
        session.commit()

    with Session(engine) as session:
        assert session.scalars(select(TermRow)).all() == []
        assert session.scalars(select(RuleRow)).all() == []


def test_a_stored_term_that_no_longer_resolves_is_not_silently_believed(
    engine: Engine,
) -> None:
    """Corruption the digest cannot see still fails loudly.

    The digest covers the grammar and the templates, so a term that cites a
    constructor the system does not have can only come from a defect in what
    wrote it. Loading it raises rather than quietly substituting something else —
    the row is a derivation, and a derivation that does not typecheck is not a
    weaker answer, it is a wrong one.
    """
    spec = hilbert_spec()
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        # HS, whose deduction `(p → r)` is the one with structure to corrupt —
        # HYP and MP both deduce a bare metavariable, which composes to nothing.
        index, rule = next(
            (i, r) for i, r in enumerate(row.rules) if r.deduction_term_id is not None
        )
        session.execute(
            update(TermRow)
            .where(TermRow.id == rule.deduction_term_id)
            .values(constructor="no_such_production")
        )
        session.commit()

        spec_now = system_to_spec(row)
        source = load_schema_terms(session, row, spec_now)
        built = build_spec(spec_now)["system"]
        context = copy(built.context)
        context.variables.update(built.build_context.variables)

        from website.logical.build_context import SchemaSlot

        with pytest.raises(LookupError):
            source(SchemaSlot(index, "deduction"), context)
