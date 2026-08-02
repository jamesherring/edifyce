"""A build that reads stored definition-form terms is the *same* build.

The counterpart of ``tests/test_schema_terms.py`` for the last string-to-term
seam: a definition's two surface forms were parsed on every build, and are now
stored as kernel terms (``app/db/definition_terms.py``). The same two properties
have to hold, pulling the same two ways:

* **Agreement.** A system built from stored forms must be indistinguishable from
  one that parsed them — the same kernel definition, the same binders, the same
  verdicts on the same proofs.
* **Inertness.** A stored term that no longer matches its system must not be
  read. The digest decides that, so these tests are mostly about its *reach*.

One failure mode is specific to definitions and has no analogue among rule
schemas: the stored term stops *before* binder placement. ``bind_scoped`` binds
ground leaves sitting in binder slots, so a form stored after it has none left
and would rebuild with an empty ``fresh`` — a definition quietly stripped of its
capture-avoidance proviso, on a path where every proof still checks. The binder
tests below are what would catch that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.db import Base, spec_to_system
from app.db.definition_terms import load_definition_terms, store_definition_terms
from app.db.models import FormalSystem, OAuthAccount, Proof, ProofFolder, Theorem, User
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
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
from app.db.terms_mapping import digest_term, store_term
from tests.database import enable_foreign_keys
from tests.spec_helpers import (
    axiom,
    brackets,
    defn,
    hyp_rule,
    statement_line,
    template_prod,
)
import website.logical.formal_system.definitions as definitions_module
from website.logical.declarative import (
    Production,
    SystemSpec,
    build_spec,
    definition_digest,
    layered_spec,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from website.logical.formal_system import FormalSystem as EngineSystem

_TABLES = [
    model.__table__
    for model in (
        User, OAuthAccount,
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow,
        ProductionBindingScopeRow, LineRow, LinePartRow, DefinitionRow,
        DefinitionBindingRow, DefinitionFreshRow, AxiomRow, AxiomBindingRow,
        RuleRow, RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        ProofFolder, Proof, Theorem, TermRow, TermChildRow,
        ProofLineRow, ProofLineAntecedentRow,
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
    )
]


def _setvar_prod() -> Production:
    return Production(sort="setvar", name="var", regex="[a-z]")


def subset_spec() -> SystemSpec:
    """df-subset over a first-order grammar, with a *declared* binder.

    Two definitions, the second stated over the first's notation, so the block
    exercises the thing that makes the digest whole-block: `(x ⊄ y)` parses only
    because `(x ⊆ y)` is already defined.
    """
    return SystemSpec(
        name="SetTheory",
        brackets=brackets(),
        productions=[
            _setvar_prod(),
            template_prod("formula", "membership", "(x ∈ y)",
                          [("x", "setvar"), ("y", "setvar")]),
            template_prod("formula", "implication", "(p → q)",
                          [("p", "formula"), ("q", "formula")]),
            template_prod("formula", "negation", "¬p", [("p", "formula")]),
            template_prod("formula", "forall", "∀x.phi",
                          [("x", "setvar"), ("phi", "formula")]),
        ],
        lines=[statement_line()],
        definitions=[
            defn("formula", "df_subset", "(x ⊆ y)", "∀z.((z ∈ x) → (z ∈ y))",
                 [("x", "setvar"), ("y", "setvar")], fresh=[("z", "setvar")],
                 label="dfsub"),
            defn("formula", "df_notsubset", "(x ⊄ y)", "¬(x ⊆ y)",
                 [("x", "setvar"), ("y", "setvar")], label="dfnsub"),
        ],
        rules=[hyp_rule()],
    )


def scoped_spec() -> SystemSpec:
    """The same definition with the binder *inferred* from the grammar's slots.

    No `fresh` clause: `∀x.phi` declares that its `x` slot scopes over `phi`, so
    `bind_scoped` places the binder. This is the case a post-binding stored term
    would silently break, and it is not reachable through `subset_spec`, whose
    binder is declared and placed by name.
    """
    spec = subset_spec()
    spec.productions = [
        template_prod("formula", "forall", "∀x.phi",
                      [("x", "setvar"), ("phi", "formula")],
                      scopes_over={"x": ["phi"]})
        if prod.name == "forall" else prod
        for prod in spec.productions
    ]
    spec.definitions = [
        defn("formula", "df_subset", "(x ⊆ y)", "∀z.((z ∈ x) → (z ∈ y))",
             [("x", "setvar"), ("y", "setvar")], label="dfsub"),
    ]
    return spec


_SYSTEMS = {"declared": subset_spec, "scoped": scoped_spec}


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://")
    enable_foreign_keys(engine)
    Base.metadata.create_all(engine, tables=_TABLES)
    return engine


def _store(engine: Engine, spec: SystemSpec) -> None:
    """Store ``spec``, build it cold, and write back the forms that build parsed."""
    with Session(engine) as session:
        row = spec_to_system(spec)
        session.add(row)
        session.flush()
        spec_now = system_to_spec(row)
        cache = load_definition_terms(session, row, spec_now)
        built = build_spec(spec_now)["system"]
        store_definition_terms(session, row, built, cache)
        session.commit()


def _rebuild(engine: Engine) -> tuple[EngineSystem, int]:
    """Build the stored system *through* the cache, and say how many slots it served."""
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec = system_to_spec(row)
        source = load_definition_terms(session, row, spec)
        built = build_spec(spec, definition_terms=source)["system"]
        return built, len(source)


def _shape(system: EngineSystem) -> list[tuple]:
    """Everything about a system's definitions that a stored form could corrupt."""
    return [
        (
            d.label,
            digest_term(d.higher),
            digest_term(d.lower),
            tuple(
                (b.name, b.sort.name, digest_term(b.default), b.declared, b.scoped,
                 b.enclosing)
                for b in d.fresh
            ),
            repr(d.condition),
        )
        for d in system.definitions
    ]


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_SYSTEMS))
def test_a_cached_build_produces_the_same_definitions(engine: Engine, name: str) -> None:
    spec = _SYSTEMS[name]()
    cold = build_spec(spec)["system"]

    _store(engine, spec)
    warm, served = _rebuild(engine)

    # Two form slots per definition, plus one per *declared* binder. The scoped
    # fixture declares none — its binder is inferred, and an inferred binder's
    # default is a leaf already in the parsed form, so there is nothing to store.
    declared_binders = sum(len(d.fresh) for d in spec.definitions)
    assert served == 2 * len(spec.definitions) + declared_binders
    assert _shape(warm) == _shape(cold)


@pytest.mark.parametrize("name", list(_SYSTEMS))
def test_the_binders_survive_the_round_trip(engine: Engine, name: str) -> None:
    # The failure a post-binding stored term would cause, pinned on its own: a
    # definition rebuilt from rows must still carry its binder, or every unfold
    # stops being capture-avoiding while every proof still checks.
    spec = _SYSTEMS[name]()
    _store(engine, spec)
    warm, _served = _rebuild(engine)

    subset = next(d for d in warm.definitions if d.label == "dfsub")
    assert [b.name for b in subset.fresh] == ["z"]
    assert subset.fresh[0].sort.name == "setvar"


@pytest.mark.parametrize(
    "source,valid",
    [
        ("(a ⊆ b) [HYP]\n∀z.((z ∈ a) → (z ∈ b)) [dfsub, 1]", True),
        # The unfold refused: the target is not what the definition unfolds to.
        ("(a ⊆ b) [HYP]\n∀z.((z ∈ b) → (z ∈ a)) [dfsub, 1]", False),
    ],
)
def test_a_cached_build_checks_definitional_steps_the_same(
    engine: Engine, source: str, valid: bool
) -> None:
    spec = subset_spec()
    _store(engine, spec)
    warm, _served = _rebuild(engine)

    cold_proof = build_spec(spec)["system"].parse(source)
    warm_proof = warm.parse(source)

    assert cold_proof.valid is valid, "the fixture proof does not have its stated verdict"
    assert warm_proof.valid is cold_proof.valid
    assert [line.valid for line in warm_proof.proof_lines] == [
        line.valid for line in cold_proof.proof_lines
    ]


def test_a_served_form_is_not_parsed_at_all(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Everything above would still pass if the cache were consulted and its answer
    # thrown away — agreement is exactly what a build that ignored it would show.
    # So: poison the one call every definition-form parse goes through, and require
    # the warm build to succeed anyway. Nothing but the rows can be feeding it.
    _store(engine, subset_spec())

    def exploding(*args: object, **kwargs: object) -> None:
        raise AssertionError("a definition read the grammar despite a stored term")

    # `from_match` rather than `abstract`: every term `parse_definition` derives
    # goes through it — both forms *and* each declared binder's default, which
    # `abstract` alone would not have covered.
    monkeypatch.setattr(definitions_module, "from_match", exploding)
    warm, served = _rebuild(engine)
    assert served == 5, "two forms per definition, plus df_subset's declared binder"
    assert [d.label for d in warm.definitions] == ["dfsub", "dfnsub"]


def test_a_declared_binders_default_round_trips(engine: Engine) -> None:
    # A binder is stored abstractly as a `Bound`, so it has no name; `default` is
    # the leaf it falls back to when an unfold chooses none. Deriving it means
    # parsing the declared name against the binder's own sort — the third grammar
    # read a definition makes, and now stored beside the two forms.
    _store(engine, subset_spec())
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        by_name = {d.name: d for d in row.definitions}
        (binder,) = by_name["df_subset"].fresh
        assert binder.var == "z"
        assert binder.term_id is not None, "a declared binder's default is stored"
        # The other definition declares no binder, so it has no `fresh` row at all.
        assert list(by_name["df_notsubset"].fresh) == []

    warm, _served = _rebuild(engine)
    subset = next(d for d in warm.definitions if d.label == "dfsub")
    (fresh,) = subset.fresh
    cold = next(
        d for d in build_spec(subset_spec())["system"].definitions if d.label == "dfsub"
    )
    assert digest_term(fresh.default) == digest_term(cold.fresh[0].default)


def test_an_inferred_binder_stores_no_default_and_is_not_a_hole(engine: Engine) -> None:
    # A binder the grammar places (`scopes_over`) is not declared, so there is no
    # `fresh` row and nothing to store — and that NULL must not read as a hole the
    # store keeps trying to fill, or every verify would rewrite the definition.
    _store(engine, scoped_spec())
    with Session(engine) as session:
        (row,) = session.scalars(select(DefinitionRow)).all()
        assert list(row.fresh) == []
        assert row.term_digest is not None

        spec_now = system_to_spec(session.scalars(select(FormalSystem)).one())
        cache = load_definition_terms(session, row.system, spec_now)
        built = build_spec(spec_now, definition_terms=cache)["system"]
        assert store_definition_terms(session, row.system, built, cache) == 0

    # The binder still arrives, inferred from the stored form's ground leaf.
    warm, _served = _rebuild(engine)
    (subset,) = warm.definitions
    assert [(b.name, b.declared, b.scoped) for b in subset.fresh] == [("z", False, True)]


def test_a_layered_definition_reads_its_own_stored_form(engine: Engine) -> None:
    # `(x ⊄ y)` unfolds to `¬(x ⊆ y)`, whose own constructor is the *first*
    # definition's notation. Its stored term therefore names a defined form, which
    # only resolves because the notation is registered before the term is read —
    # the reason the cache is consulted where it is and not at the top of the walk.
    _store(engine, subset_spec())
    warm, served = _rebuild(engine)
    assert served == 5

    notsubset = next(d for d in warm.definitions if d.label == "dfnsub")
    (inner,) = notsubset.lower.children.values()
    assert inner.constructor.name == "formula:(x ⊆ y)"
    # And the same term a cold build derives, not merely something ⊆-shaped.
    cold = build_spec(subset_spec())["system"]
    assert _shape(warm) == _shape(cold)


# ---------------------------------------------------------------------------
# Inertness: what the digest must reach
# ---------------------------------------------------------------------------


def _retemplate(spec: SystemSpec) -> None:
    # A production the defining forms are parsed against.
    spec.productions = [
        template_prod("formula", "membership", "(x ∈∈ y)",
                      [("x", "setvar"), ("y", "setvar")])
        if prod.name == "membership" else prod
        for prod in spec.productions
    ]


def _reword_lower(spec: SystemSpec) -> None:
    spec.definitions[0].lower = "∀z.((z ∈ y) → (z ∈ x))"


def _reword_higher(spec: SystemSpec) -> None:
    spec.definitions[0].higher = "(x ⊑ y)"
    spec.definitions[1].lower = "¬(x ⊑ y)"


def _drop_fresh(spec: SystemSpec) -> None:
    spec.definitions[0].fresh = []


def _rebind(spec: SystemSpec) -> None:
    spec.definitions[0].bindings = [("x", "setvar"), ("y", "formula")]


def _reorder(spec: SystemSpec) -> None:
    # An insertion at the front moves every slot index, which is exactly what a
    # per-definition digest would have missed.
    spec.definitions.insert(
        0,
        defn("formula", "df_ne", "(x ≠ y)", "¬(x ∈ y)",
             [("x", "setvar"), ("y", "setvar")], label="dfne"),
    )


def _scope_a_slot(spec: SystemSpec) -> None:
    # `scopes_over` decides which leaves become binders, so it changes the very
    # term this cache stores even though no form's text moves.
    spec.productions = [
        template_prod("formula", "forall", "∀x.phi",
                      [("x", "setvar"), ("phi", "formula")],
                      scopes_over={"x": ["phi"]})
        if prod.name == "forall" else prod
        for prod in spec.productions
    ]


def _rename_label(spec: SystemSpec) -> None:
    spec.definitions[0].label = "renamed"


def _reprovision(spec: SystemSpec) -> None:
    spec.definitions[0].provisos = ["disjoint(x, y, setvar)"]


@pytest.mark.parametrize(
    "edit,moves",
    [
        (_retemplate, True),
        (_reword_lower, True),
        (_reword_higher, True),
        (_drop_fresh, True),
        (_rebind, True),
        (_reorder, True),
        (_scope_a_slot, True),
        # Neither is read by either parse: a label names the definition and a
        # proviso becomes its `condition`, attached after the forms are built.
        (_rename_label, False),
        (_reprovision, False),
    ],
)
def test_which_edits_move_the_definition_digest(edit, moves: bool) -> None:
    before = subset_spec()
    after = subset_spec()
    edit(after)
    assert (definition_digest(before) != definition_digest(after)) is moves


@pytest.mark.parametrize(
    "edit",
    [_retemplate, _reword_lower, _reword_higher, _drop_fresh, _rebind, _reorder,
     _scope_a_slot, _rename_label, _reprovision],
)
def test_a_warm_build_agrees_with_a_cold_one_after_any_edit(
    engine: Engine, edit
) -> None:
    # The property the digest exists for, stated without reference to it: whatever
    # the edit, reading whatever is stored must not change the outcome. An edit
    # that moves the digest makes the rows inert; one that does not must leave
    # terms that are still correct.
    #
    # Outcome, not system: two of these edits make the spec unbuildable (an
    # undeclared binder, a parameter at the wrong sort), and a stored term must
    # not rescue a build that should fail — which is the sharper half of the
    # property, so they are kept rather than filtered out.
    _store(engine, subset_spec())

    edited = subset_spec()
    edit(edited)
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        source = load_definition_terms(session, row, edited)
        warm = build_spec(edited, definition_terms=source)

    cold = build_spec(edited)
    assert ("errors" in warm) == ("errors" in cold)
    if "errors" in cold:
        assert warm["errors"] == cold["errors"]
    else:
        assert _shape(warm["system"]) == _shape(cold["system"])


# ---------------------------------------------------------------------------
# The cache's own contract
# ---------------------------------------------------------------------------


def test_storing_is_idempotent(engine: Engine) -> None:
    spec = subset_spec()
    _store(engine, spec)
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        cache = load_definition_terms(session, row, spec_now)
        built = build_spec(spec_now, definition_terms=cache)["system"]
        assert store_definition_terms(session, row, built, cache) == 0


def test_a_deleted_term_costs_a_re_parse_and_not_a_definition(engine: Engine) -> None:
    # The "a missing term is a miss, never an answer" half. Deleting the term a
    # definition points at must leave the definition itself intact — the FK is SET
    # NULL — and the NULL that follows must be read as "parse it", *not* as "this
    # form parses to nothing", even though the digest still matches.
    #
    # One definition, so the deleted root is nothing else's subterm: `df_subset`'s
    # defined form is also a subterm of `df_notsubset`'s defining form, and
    # deleting a *shared* subterm truncates its other parent. That is a hazard of
    # the term store rather than of this cache — nothing sweeps terms today — and
    # fabricating it here would test a state the schema cannot reach.
    spec = scoped_spec()
    _store(engine, spec)
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        (definition,) = row.definitions
        target = definition.lower_term_id
        session.execute(sa_delete(TermChildRow).where(
            TermChildRow.parent_id == target
        ))
        session.execute(sa_delete(TermRow).where(TermRow.id == target))
        session.commit()

        refreshed = session.scalars(select(DefinitionRow)).one()
        assert refreshed.lower_term_id is None, "the FK must SET NULL, not cascade"
        assert refreshed.term_digest is not None, "the digest still matches"

    warm, served = _rebuild(engine)
    assert served == 1, "the surviving `higher` term is still served"
    assert _shape(warm) == _shape(build_spec(spec)["system"])


def test_a_dropped_definition_stores_nothing_and_stays_droppable(engine: Engine) -> None:
    # A definition whose defining form matches nothing is dropped by the build, so
    # it derives no forms. Its row must keep a NULL digest — recording one would
    # claim terms it never had.
    spec = subset_spec()
    spec.definitions.append(
        defn("formula", "df_bad", "(x ⊞ y)", "(x ⊟ y)",
             [("x", "setvar"), ("y", "setvar")], label="dfbad")
    )
    _store(engine, spec)

    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        stored = {d.name: (d.term_digest, d.higher_term_id) for d in row.definitions}
    assert stored["df_bad"] == (None, None)
    assert stored["df_subset"][0] is not None

    warm, _served = _rebuild(engine)
    assert [d.label for d in warm.definitions] == ["dfsub", "dfnsub"]


def test_a_swept_term_is_written_again_rather_than_left_a_hole(engine: Engine) -> None:
    # A matching digest is not enough to skip the write. `ON DELETE SET NULL`
    # leaves the digest intact and the term id NULL, so a store that skipped on
    # the digest alone would never fill the hole — and that form would be reparsed
    # on every verify for the life of the system. Unlike a rule's schema slot, a
    # NULL here can only be a hole: a registered definition always derives both.
    spec = scoped_spec()
    _store(engine, spec)
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        (definition,) = row.definitions
        target = definition.lower_term_id
        session.execute(sa_delete(TermChildRow).where(TermChildRow.parent_id == target))
        session.execute(sa_delete(TermRow).where(TermRow.id == target))
        session.commit()

    # A verify that reparses the missing form must also write it back.
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        spec_now = system_to_spec(row)
        cache = load_definition_terms(session, row, spec_now)
        built = build_spec(spec_now, definition_terms=cache)["system"]
        assert store_definition_terms(session, row, built, cache) == 1
        session.commit()

    # And the next build is served both slots again — the cache healed.
    _warm, served = _rebuild(engine)
    assert served == 2


def test_a_shadowed_production_name_still_resolves_from_rows(engine: Engine) -> None:
    # `ctx.variables` is one namespace: an axiom named after a production leaves
    # the axiom's LineType under that key. Composing is indifferent (it parses
    # against the sort unions), but a *stored* term names its constructors by name
    # — so before `terms_mapping._in_grammar`, such a system verified once and then
    # failed on every later verify with an AttributeError, once its terms existed.
    spec = scoped_spec()
    spec.axioms = [axiom("MEMB", "membership", "(a ∈ a)")]
    assert "errors" not in build_spec(spec), "the fixture must build cold"

    _store(engine, spec)
    warm, served = _rebuild(engine)
    assert served == 2
    assert _shape(warm) == _shape(build_spec(spec)["system"])


def test_a_layers_own_slots_are_the_ones_it_reads_and_writes(engine: Engine) -> None:
    # A system that inherits is built from its whole *chain's* spec, so this
    # layer's `definitions[i]` is `spec.definitions[offset + i]`. Get the offset
    # wrong and a child reads an ancestor's slot as its own — which is not a crash
    # but a definition of the wrong thing, since every form in the chain parses
    # against the same grammar and so resolves happily.
    #
    # Two layers, each with a definition, and the parent's comes first in the
    # layered spec. `df_notsubset` (the child's) must be served the child's forms.
    parent = subset_spec()
    parent.definitions = [parent.definitions[0]]      # just df_subset
    child = SystemSpec(
        name="Child",
        definitions=[subset_spec().definitions[1]],   # just df_notsubset
    )
    chain = layered_spec([parent, child])
    offset = len(parent.definitions)

    with Session(engine) as session:
        row = spec_to_system(child)
        session.add(row)
        session.flush()
        cache = load_definition_terms(session, row, chain, offset)
        built = build_spec(chain)["system"]
        assert store_definition_terms(session, row, built, cache, offset) == 1
        session.commit()

        # The child's row holds the child's forms — the ones at the offset slot,
        # not the parent's at slot 0.
        (stored,) = session.scalars(select(DefinitionRow)).all()
        assert stored.name == "df_notsubset"
        parsed = built.definition_forms[offset]
        assert stored.higher_term_id == store_term(session, row, parsed.higher).id
        assert stored.lower_term_id == store_term(session, row, parsed.lower).id

    # And a warm build of the chain reads them back at that slot, unchanged.
    with Session(engine) as session:
        row = session.scalars(select(FormalSystem)).one()
        source = load_definition_terms(session, row, chain, offset)
        assert len(source) == 2, "the child's two forms, and only those"
        warm = build_spec(chain, definition_terms=source)["system"]

    assert _shape(warm) == _shape(build_spec(chain)["system"])


def test_a_system_with_stored_definition_terms_can_still_be_deleted(
    engine: Engine,
) -> None:
    # The FK is SET NULL rather than RESTRICT, and the system cascade has to win
    # over it; foreign keys are enforced on this engine, so this is a real check.
    _store(engine, subset_spec())
    with Session(engine) as session:
        session.delete(session.scalars(select(FormalSystem)).one())
        session.commit()
        assert session.scalars(select(DefinitionRow)).all() == []
