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
from website.logical.build_context import SchemaSlot
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


# One entry per system the round trip is exercised against, with how many slots
# it has worth caching. MIU is here at **zero**: its rules are string-rewriting
# over a single regex sort, so no template composes to anything and the cache is
# empty. That is the case where the phase must be *harmless* rather than useful,
# and asserting the zero is what says the other two aren't accidentally there.
_SYSTEMS = {
    "zfc": (scoped_zfc_spec, 3),
    "hilbert": (hilbert_spec, 4),
    "miu": (miu_spec, 0),
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
    factory, cacheable = _SYSTEMS[name]
    spec = factory()
    cold = build_spec(spec)["system"]

    _store(engine, spec)
    warm, served = _rebuild(engine)

    assert served == cacheable, "the cache served a different number of slots than stated"
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
    spec = _SYSTEMS[name][0]()
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


def _collide_axiom_with_production(spec: SystemSpec) -> None:
    """An axiom renamed onto a production's name.

    Lines, line parts and axioms share ``ctx.variables`` with the grammar, and are
    registered after it, so this leaves the name bound to the axiom's line type.
    Composing does not care — it parses against the sort unions, which hold the
    production objects — but a *stored* term resolves its constructors by name
    through that namespace, and finds the line type.
    """
    spec.axioms[0].name = "implication"


def _collide_line_part_with_production(spec: SystemSpec) -> None:
    """The same collision from a line part, which is registered the same way."""
    spec.lines[0].parts[0].name = "implication"
    spec.lines[0].shape = spec.lines[0].shape.replace("<reference>", "<implication>")


def _rename_line_harmlessly(spec: SystemSpec) -> None:
    """A rename that collides with nothing — the terms must survive it.

    The counterweight to the two above: the digest covers *collisions*, not every
    name bound outside the grammar, so an unrelated rename must not throw the
    system's schema terms away.
    """
    spec.lines[0].name = "claim"


# Each edit, paired with whether it is known to *move* a schema term in this
# fixture. The flag is asserted too: an edit that starts or stops moving one is a
# change in what composition depends on, and this is where that should surface
# rather than in a stale term nobody notices.
#
# Note the collisions move nothing: a cold build is completely unaffected by
# them. They are here for the end-to-end test below, which is the one that can
# see them.
_EDITS = [
    (_retemplate, True),
    (_rename_production, True),
    (_add_production, False),
    (_drop_brackets, False),
    (_retemplate_rule, True),
    (_rebind_rule, False),
    (_collide_axiom_with_production, False),
    (_collide_line_part_with_production, False),
    (_rename_line_harmlessly, False),
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


def _edited_rows(session: Session, edit) -> tuple[FormalSystem, SystemSpec]:
    """The rows an edit to the stored system would leave, terms and all.

    A part edit rewrites the parts and touches nothing on `rules` — including the
    columns this cache lives in — so the stored terms and digests carry straight
    over. That carry-over is the whole hazard, and reproducing it faithfully is
    what makes the tests below mean anything.
    """
    row = session.scalars(select(FormalSystem)).one()
    edited = system_to_spec(row)
    edit(edited)

    replacement = spec_to_system(edited)
    for stored, fresh in zip(row.rules, replacement.rules):
        fresh.schema_digest = stored.schema_digest
        fresh.deduction_term_id = stored.deduction_term_id
        fresh.subproof_derive_term_id = stored.subproof_derive_term_id
        fresh.subproof_assume_term_id = stored.subproof_assume_term_id
        fresh.subproof_fresh_term_id = stored.subproof_fresh_term_id
        for stored_a, fresh_a in zip(stored.antecedents, fresh.antecedents):
            fresh_a.term_id = stored_a.term_id
    return replacement, edited


@pytest.mark.parametrize("edit,_moves", _EDITS, ids=lambda v: getattr(v, "__name__", ""))
def test_a_warm_build_agrees_with_a_cold_one_after_any_edit(
    engine: Engine, edit, _moves
) -> None:
    """The property the whole phase rests on, checked through storage.

    The digest test above works on specs and asks a proxy question — did the
    digest move when the term did. This asks the real one: after an edit, does
    building *through* the stored terms give the same system as building without
    them. It is strictly stronger, and it is what catches an edit that changes no
    composed term but changes how a stored one is *read* back — a line or axiom
    renamed onto a production's name shadows it in the build namespace, so the
    cold build composes fine while the warm build resolves the stored
    constructor to a line type. Nothing about composition moves, so only this
    shape of test can see it.
    """
    _store(engine, hilbert_spec())

    with Session(engine) as session:
        replacement, edited = _edited_rows(session, edit)
        warm = build_spec(
            edited, schema_terms=load_schema_terms(session, replacement, edited)
        )
        cold = build_spec(edited)

    assert "errors" not in cold, cold.get("errors")
    assert "errors" not in warm, warm.get("errors")
    assert _schemas(warm["system"]) == _schemas(cold["system"])


@pytest.mark.parametrize(
    "edit,served",
    [
        # A grammar edit invalidates everything: a schema term names the
        # constructors it was built from.
        (_retemplate, 0),
        (_rename_production, 0),
        (_add_production, 0),
        # A collision does too, for a different reason — it changes what a stored
        # constructor *name* resolves to (see _shadowed_grammar_names).
        (_collide_axiom_with_production, 0),
        (_collide_line_part_with_production, 0),
        # ...but a rename that shadows nothing must keep them.
        (_rename_line_harmlessly, 4),
    ],
    ids=lambda v: getattr(v, "__name__", str(v)),
)
def test_which_edits_leave_the_stored_terms_readable(
    engine: Engine, edit, served: int
) -> None:
    """The cost side of the guard.

    The test above says a warm build is never *wrong*; this says it is not
    needlessly cold either. Invalidating on every name bound outside the grammar
    would pass that one and throw the cache away for an unrelated rename.
    """
    _store(engine, hilbert_spec())

    with Session(engine) as session:
        replacement, edited = _edited_rows(session, edit)
        assert len(load_schema_terms(session, replacement, edited)) == served


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


def test_a_slot_with_no_stored_term_is_a_miss_not_an_answer(engine: Engine) -> None:
    """A NULL term id must never be read as "this composes to nothing".

    It cannot be, because the same NULL means three different things: the
    template genuinely composes to nothing, the slot resolved to a declared
    grammar pattern instead of a composed one, or the term row was deleted and
    the FK set it null. Composing again settles all three; reading the absence as
    an answer settles the last two wrongly, and silently — a rule reduced to its
    flat projection stops matching the proofs it used to.
    """
    spec = hilbert_spec()
    spec.rules[0].deduction = "q"  # a bare metavariable: no structure to compose
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        loaded = load_schema_terms(session, row, system_to_spec(row))

    assert loaded(SchemaSlot(0, "deduction"), None) is None


def test_a_deleted_term_costs_a_re_compose_and_not_a_rule(engine: Engine) -> None:
    """What the ``ON DELETE SET NULL`` on the schema-term FKs actually promises.

    Deleting a term nulls the reference and leaves the digest matching. The rule
    must come back exactly as a cold build would have it — not as the flat
    projection a believed NULL would leave, which unifies against nothing the
    nested schema used to match.
    """
    spec = hilbert_spec()
    _store(engine, spec)
    cold = _schemas(build_spec(spec)["system"])

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        rule = next(r for r in row.rules if r.deduction_term_id is not None)
        # Exactly what `ON DELETE SET NULL` leaves behind, without disturbing the
        # rest of the graph: the reference goes, the digest stays.
        session.execute(
            update(RuleRow).where(RuleRow.id == rule.id).values(deduction_term_id=None)
        )
        session.commit()

        row = session.scalars(select(FormalSystem)).one()
        index = row.rules.index(rule)
        assert rule.schema_digest is not None, "the digest must survive the deletion"
        spec_now = system_to_spec(row)
        cache = load_schema_terms(session, row, spec_now)
        # The slot is genuinely unanswered — otherwise the comparison below would
        # pass on a cache that never lost anything.
        assert cache(SchemaSlot(index, "deduction"), None) is None
        warm = build_spec(spec_now, schema_terms=cache)["system"]

    assert _schemas(warm) == cold
    assert dict(cold[index][1])["deduction"] is not None, (
        "the erased slot composes to nothing, so nothing was recovered"
    )


def test_two_rules_sharing_a_label_do_not_cross_wire_their_terms(
    engine: Engine,
) -> None:
    """`add_inference_rule` replaces a rule of the same label, so a system with a
    duplicate builds to fewer rules than it has rows. Pairing rows to built rules
    by position would then attach one rule's terms to another's row — and the
    row that survives is the *later* one, so the mix-up is silent.

    A duplicate label is a defect in the system, but the API does not refuse one,
    and it verified fine before any of this existed. It must still.
    """
    spec = hilbert_spec()
    spec.rules[2].label = "MP"  # HS now shadows MP
    cold = build_spec(spec)["system"]
    assert len(cold.inference_rules) < len(spec.rules), "the fixture must shadow"

    _store(engine, spec)
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        warm = build_spec(
            spec_now, schema_terms=load_schema_terms(session, row, spec_now)
        )["system"]
        # The shadowed row keeps no digest: its rule object was composed and then
        # discarded, so there is nothing of its own to store.
        assert [r.schema_digest is None for r in row.rules] == [False, True, False]

    assert _schemas(warm) == _schemas(cold)


def test_antecedent_terms_follow_reading_order_not_the_position_column(
    engine: Engine,
) -> None:
    """A rule's antecedents are read back in ``position`` order and then
    *enumerated*, so the ordinal a build asks for is an index into that order and
    not the column's value. A system whose positions are not 0, 1, 2 … would
    otherwise store under one key and read under another — a permanent miss, or
    worse, a hit on the neighbouring slot.
    """
    spec = hilbert_spec()
    _store(engine, spec)

    with Session(engine) as session:
        # Spread the positions without changing their order.
        for rule in session.scalars(select(RuleRow)):
            for offset, antecedent in enumerate(rule.antecedents):
                antecedent.position = offset * 7 + 3
        session.commit()

        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        warm = build_spec(
            spec_now, schema_terms=load_schema_terms(session, row, spec_now)
        )["system"]
        served = len(load_schema_terms(session, row, spec_now))

    assert served > 0, "the spread positions served nothing, so nothing was tested"
    assert _schemas(warm) == _schemas(build_spec(spec)["system"])


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

        with pytest.raises(LookupError):
            source(SchemaSlot(index, "deduction"), context)
