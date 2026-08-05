"""A corpus imported as a **spine of systems** rather than one.

D3's store half (docs/system-relationships-roadmap.md §7.2). The spec half
(`corpus_specs`) says what each layer declares; this is where those become rows
a citation resolves through — one `formal_systems` row per layer, wired by
`inherits_from_id`, and each theorem stored against the layer its own section
falls in.

**What must not change is the import.** The walk checks exactly what it checked
before — layering is a fact about how a corpus is *filed*, not about how it is
*verified* — so the theorem count, the per-theorem verdicts and the emitted proof
sources are the same either way. That is §7.2's "the emitted proof text does not
change", and it is what these tests assert against an unlayered run of the same
file rather than against remembered numbers.

**What must move is everything a read path reaches by system id**, since a proof
filed against its own layer loses whatever stayed on the leaf: the library, the
outline (`GET /formal-systems/{id}/folders` is system-scoped both for the folders
and for the proof counts) and the descriptions (`load_description` walks no
chain). The one exception is a **notation**, which is read root-first *up* the
chain and so belongs on the root, where every layer can see it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("regex")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db.descriptions import LabelDescriptionRow
from app.db.metamath_store import import_corpus, layered_systems
from app.db.models import FormalSystem, Proof, ProofFolder
from app.db.proof_lines import ProofLineRow
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.definition_terms import load_definition_terms
from app.db.proofs_mapping import PendingCitations, load_proof_for_check
from app.db.promoted_theorems_mapping import cited_labels, read_library
from app.db.schema_terms import load_schema_terms
from app.db.terms_mapping import term_context
from app.db.systems_mapping import (
    effective_library,
    inherited_definition_count,
    inherited_rule_count,
)
from app.db.systems import (
    NotationPieceRow,
    NotationRulePieceRow,
    NotationRulePinRow,
    NotationRuleRow,
)
from website.logical.declarative import build_spec
from website.logical.formal_system import Proof as EngineProof
from website.logical.metamath import parse
from website.logical.metamath.corpus import corpus_specs
from website.logical.metamath.sections import Layer
from website.logical.metamath.setmm import LAYERS

from scripts.check_layering import unreachable_citations

from tests.test_metamath_layered_specs import CORPUS, SECTION
from tests.test_metamath_persistence import _TABLES

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from website.logical.metamath.parser import Database


# The persistence suite's tables, plus the notation ones: this fixture carries a
# `$t` block, so an import here derives a notation and has somewhere to put it.
_STORE_TABLES = _TABLES + [
    model.__table__
    for model in (
        NotationPieceRow, NotationRuleRow, NotationRulePinRow, NotationRulePieceRow
    )
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_STORE_TABLES)
    with Session(engine) as handle:
        yield handle


@pytest.fixture
def database() -> Database:
    return parse(CORPUS)


def systems(session: Session) -> list[FormalSystem]:
    """Every stored system, root first."""
    rows = list(session.scalars(select(FormalSystem)))
    spine = [row for row in rows if row.inherits_from_id is None]
    while True:
        child = next((r for r in rows if r.inherits_from_id == spine[-1].id), None)
        if child is None:
            return spine
        spine.append(child)


# ---------------------------------------------------------------------------
# The spine
# ---------------------------------------------------------------------------


def test_a_layered_import_stores_one_system_per_layer(session, database) -> None:
    report = import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = systems(session)
    assert [system.name for system in spine] == [
        "Propositional calculus", "First-order logic", "ZF set theory"
    ]
    # Root first, and the report's `system_id` is the **deepest** — the one a
    # citation resolves from, since its chain reaches everything above it.
    assert report.system_ids == [system.id for system in spine]
    assert report.system_id == spine[-1].id


def test_a_layer_is_published_exactly_when_something_inherits_from_it(
    session, database
) -> None:
    # §5.1's rule, not a new one: a parent must be frozen before a child builds
    # on it. The deepest layer has no child, which is also what makes an
    # unlayered import — one system, no children — behave as it did before.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = systems(session)
    assert all(system.published_at is not None for system in spine[:-1])
    assert spine[-1].published_at is None


def test_an_unlayered_import_is_still_one_unpublished_system(session, database) -> None:
    # The contract that keeps this additive, asserted rather than assumed.
    report = import_corpus(session, database, name="Corpus")

    stored = list(session.scalars(select(FormalSystem)))
    assert len(stored) == 1
    assert stored[0].published_at is None and stored[0].inherits_from_id is None
    assert report.system_ids == [report.system_id]


# ---------------------------------------------------------------------------
# What the split moves, and what it must not
# ---------------------------------------------------------------------------


def test_a_theorem_is_stored_against_the_layer_its_section_falls_in(
    session, database
) -> None:
    # The partition, on the rows. Each proof lands in its own layer's system —
    # which is the whole point, since a proof filed in the layer below would make
    # that layer's provenance a lie.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system.name for system in systems(session)}
    filed = {
        proof.name: spine[proof.formal_system_id]
        for proof in session.scalars(select(Proof))
    }
    assert filed == {
        "pc-thm": "Propositional calculus",
        "fol-thm": "First-order logic",
        # The cross-layer one: filed in first-order logic, citing propositional.
        "fol-cites-pc": "First-order logic",
        "zf-thm": "ZF set theory",
    }


def test_the_library_is_split_the_same_way(session, database) -> None:
    # A promoted theorem belongs to the layer that declared it, for the same
    # reason a proof does — and a citation still resolves, because a child's
    # library is its ancestors' (§5.2).
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system.name for system in systems(session)}
    where = {
        row.label: spine[row.system_id]
        for row in session.scalars(select(PromotedTheoremRow))
    }
    assert where["ax-1"] == "Propositional calculus"
    assert where["ax-4"] == "First-order logic"
    assert where["ax-ext"] == "ZF set theory"


def test_layering_changes_nothing_about_what_was_checked(session, database) -> None:
    # **The headline**, and §7.2's "the emitted proof text does not change".
    # Same theorems, same verdicts, byte-identical sources — asserted against an
    # unlayered run of the same file rather than against remembered numbers, so
    # the two cannot drift apart.
    layered = import_corpus(session, database, name="Corpus", plan=LAYERS)
    sources = {
        proof.name: (proof.source, proof.valid)
        for proof in session.scalars(select(Proof))
    }

    plain_engine = create_engine("sqlite://")
    Base.metadata.create_all(plain_engine, tables=_STORE_TABLES)
    with Session(plain_engine) as plain:
        unlayered = import_corpus(plain, parse(CORPUS), name="Corpus")
        plain_sources = {
            proof.name: (proof.source, proof.valid)
            for proof in plain.scalars(select(Proof))
        }

    assert (layered.checked, layered.verified, layered.rejected, layered.failed) == (
        unlayered.checked, unlayered.verified, unlayered.rejected, unlayered.failed
    )
    assert layered.theorems == unlayered.theorems
    assert sources == plain_sources
    # And the same *derived* rows, since a partition moves where something is
    # stored and never how much of it there is. Each of the three has its own
    # rule below — the outline and the descriptions follow the split, the
    # notation does not — but all three are conserved.
    assert (layered.sections, layered.described, layered.notation) == (
        unlayered.sections, unlayered.described, unlayered.notation
    )


def test_every_layers_proofs_are_linked_to_their_theorems(session, database) -> None:
    # `_link_proofs_to_theorems` used to filter on the deepest system, which with
    # a spine linked that layer's proofs and left every other layer's
    # `theorem_id` null (found in review) — so `GET /proofs/{id}` would show a
    # propositional theorem as establishing nothing.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    linked = {
        proof.name: proof.theorem_id is not None
        for proof in session.scalars(select(Proof))
    }
    assert linked == {
        "pc-thm": True, "fol-thm": True, "fol-cites-pc": True, "zf-thm": True
    }


def test_a_proofs_folder_belongs_to_the_proofs_own_layer(session, database) -> None:
    # The outline follows the split too, because the read is system-scoped at
    # both ends: `GET /formal-systems/{id}/folders` lists a system's own folders
    # and counts a system's own proofs. Storing it whole against the leaf (which
    # is what the first cut did, found in review) leaves every ancestor with an
    # empty outline and the leaf reporting 0 proofs in each of its folders.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system.name for system in systems(session)}
    folders = {folder.id: folder for folder in session.scalars(select(ProofFolder))}
    filed = {
        proof.name: spine[folders[proof.folder_id].formal_system_id]
        for proof in session.scalars(select(Proof))
    }
    assert filed == {
        "pc-thm": "Propositional calculus",
        "fol-thm": "First-order logic",
        # The cross-layer one: filed in first-order logic, citing propositional.
        "fol-cites-pc": "First-order logic",
        "zf-thm": "ZF set theory",
    }
    # Every layer holds some of the outline, which is the other half of it: a
    # split that filed the proofs right but left a layer with no folders at all
    # would satisfy the line above and still serve an empty tree.
    assert {spine[folder.formal_system_id] for folder in folders.values()} == set(
        spine.values()
    )


def test_a_labels_description_belongs_to_the_layer_that_declares_it(
    session, database
) -> None:
    # `load_description` looks a label up under one system id and walks no chain
    # (deliberately — a child cannot describe a label it does not declare), so
    # prose left on the leaf is prose an ancestor-layer proof can never show.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system.name for system in systems(session)}
    where = {
        row.label: spine[row.formal_system_id]
        for row in session.scalars(select(LabelDescriptionRow))
    }
    assert where["ax-1"] == "Propositional calculus"
    assert where["wal"] == "First-order logic"
    assert where["wcel"] == "ZF set theory"


def test_the_notation_is_stored_once_on_the_root(session, database) -> None:
    # The one thing that does *not* follow the split. A `$t` block is a single
    # declaration about the whole file, and a notation is read root-first up the
    # chain (`notations_mapping.notation_layers`), so the root is the one place
    # every layer can see it from — on the leaf it would be invisible to all its
    # ancestors, which for an imported corpus is every notation there is.
    report = import_corpus(session, database, name="Corpus", plan=LAYERS)

    assert report.notation > 0
    root = systems(session)[0]
    holders = {
        row.formal_system_id for row in session.scalars(select(NotationPieceRow))
    }
    assert holders == {root.id}


def test_a_batched_layered_run_stores_the_same_rows(session, database) -> None:
    # A checkpoint empties the identity map and re-fetches the system; with a
    # spine there are several to re-fetch, and a run that reattached only one
    # would start writing every later theorem against the wrong layer.
    import_corpus(session, database, name="Corpus", plan=LAYERS, batch=1)

    spine = {system.id: system.name for system in systems(session)}
    filed = {
        proof.name: spine[proof.formal_system_id]
        for proof in session.scalars(select(Proof))
    }
    assert filed == {
        "pc-thm": "Propositional calculus",
        "fol-thm": "First-order logic",
        # The cross-layer one: filed in first-order logic, citing propositional.
        "fol-cites-pc": "First-order logic",
        "zf-thm": "ZF set theory",
    }


@pytest.mark.parametrize("plan", [(), LAYERS], ids=["unlayered", "layered"])
def test_a_checkpoint_leaves_the_library_writing_through_a_live_session(
    session, database, plan
) -> None:
    # A **batched** run is the only one this reaches, and it is what a real
    # import is: `scripts/import_metamath.py` defaults to `--batch 50`.
    #
    # `walk` is handed one `store` callable before the first checkpoint and holds
    # it for the whole run. Rebinding by *rebuilding* the routing object
    # therefore reattaches nothing the walk can see — every later assertion is
    # written against a `FormalSystem` `expunge_all` detached, and the whole
    # library after theorem one is lost (found in review). The label→id map goes
    # with it, so the proofs are left unlinked too.
    report = import_corpus(session, database, name="Corpus", plan=plan, batch=1)

    assert (report.theorems_failed, report.failures) == (0, [])
    assert report.theorems == 7
    assert all(proof.theorem_id is not None for proof in session.scalars(select(Proof)))


def test_the_report_breaks_the_run_down_by_layer(session, database) -> None:
    # §7.3's per-layer breakdown, which is what `--setmm-layers` prints. Counted
    # as the run goes rather than derived by a reader, because a stored row keeps
    # the system it landed in and not the section that put it there.
    report = import_corpus(session, database, name="Corpus", plan=LAYERS)

    assert [layer.name for layer in report.layers] == [
        "Propositional calculus", "First-order logic", "ZF set theory"
    ]
    assert [layer.system_id for layer in report.layers] == report.system_ids
    # One proof each, and the shares add up to the totals — which is the property
    # that says the breakdown is a partition rather than three tallies.
    assert [layer.proofs for layer in report.layers] == [1, 2, 1]
    assert sum(layer.proofs for layer in report.layers) == (
        report.verified + report.rejected
    )
    for field_name in ("theorems", "primitives", "sections", "described"):
        assert sum(getattr(layer, field_name) for layer in report.layers) == getattr(
            report, field_name if field_name != "sections" else "sections"
        ), field_name


def test_an_unlayered_run_reports_one_layer_carrying_everything(
    session, database
) -> None:
    # So a reader never has to ask whether a plan was given before reading the
    # breakdown. The script prints it only for a spine, but the field is always
    # populated and always sums to the totals.
    report = import_corpus(session, database, name="Corpus")

    assert len(report.layers) == 1
    only = report.layers[0]
    assert only.name == "Corpus" and only.system_id == report.system_id
    assert (only.proofs, only.theorems, only.sections, only.described) == (
        report.verified + report.rejected,
        report.theorems,
        report.sections,
        report.described,
    )


def test_a_plan_whose_layers_share_a_name_still_files_each_proof_in_its_own(
    session, database
) -> None:
    # The store-side consequence of the `corpus_layers` fix (found in review).
    # A `Layer`'s name is a display name and nothing prohibits two of them being
    # the same; pairing the boundaries back with their positions by name kept
    # only the last, so `corpus_specs` emitted three layers and every one but the
    # last filed its theorems in the **root** — under a grammar that does not
    # declare their notation, which a row-based reload then cannot rebuild.
    plan = tuple(Layer(name="Logic", starts_with=layer.starts_with) for layer in LAYERS)

    import_corpus(session, database, name="Corpus", plan=plan)

    spine = systems(session)
    assert [system.name for system in spine] == ["Logic", "Logic", "Logic"]
    filed = {
        proof.name: spine.index(
            next(s for s in spine if s.id == proof.formal_system_id)
        )
        for proof in session.scalars(select(Proof))
    }
    assert filed == {"pc-thm": 0, "fol-thm": 1, "fol-cites-pc": 1, "zf-thm": 2}


# A corpus whose `$f` declarations sit **inside** a layer rather than in the
# preamble, and which states a `$d` over a metavariable typed in the layer below.
#
# That is `set.mm`'s own shape and the shared `CORPUS` above is not: its variables
# are all declared before any layer opens, so they all land in the root and every
# layer's own symbol table happens to be enough. Here `wff_var` is the
# propositional layer's, and `ax-5`'s disjoint-variable condition — stated in the
# first-order layer over `ph` — has to resolve through it.
SCOPED_VARIABLES = f"""
$c |- wff class ( ) -> A. $.
$v ph ps x $.

$( {SECTION}
   Pre-logic
   {SECTION} $)
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
pc-thm $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.

$( {SECTION}
   Predicate calculus with equality:  Tarski's system S2
   {SECTION} $)
vx $f class x $.
wal $a wff A. x ph $.
${{
  $d x ph $.
  ax-5 $a |- ( ph -> A. x ph ) $.
$}}
fol-thm $p |- ( ph -> A. x ph ) $= ( ax-5 ) ABC $.
"""


def test_a_layer_resolves_a_proviso_sort_through_its_ancestors(session) -> None:
    # **From the corpus run** (`scripts/check_layering.py`, §8's D4). A promoted
    # theorem's side conditions name a sort, which `side_conditions_mapping`
    # resolves to a real `symbols` FK — and a layer that offered only its *own*
    # symbols could not resolve one its ancestor declares. On `set.mm` that is
    # `wff_var`, declared in the propositional layer while the theorems carrying
    # a `$d` over a `wff` run to the top of the file: **354 of the first 2,676
    # promotions were refused** with "Side-condition sort 'wff_var' is not a
    # symbol of the system", and every proof citing one of them lost its library
    # entry.
    #
    # The symbol row it points at is the *ancestor's*, not a copy — §5.1's
    # guarantee is cheap precisely because a child's primitives are the
    # ancestor's rows.
    database = parse(SCOPED_VARIABLES)
    plan = (
        Layer(name="Propositional calculus", starts_with="Pre-logic"),
        Layer(name="First-order logic", starts_with="Predicate calculus with equality"),
    )

    report = import_corpus(session, database, name="Corpus", plan=plan)

    assert (report.theorems_failed, report.failures) == (0, [])
    stored = {row.label for row in session.scalars(select(PromotedTheoremRow))}
    assert "ax-5" in stored
    # And it is filed in the layer that states it, resolving a sort that is not
    # that layer's own — which is the whole of the case.
    spine = {system.id: system.name for system in systems(session)}
    where = {
        row.label: spine[row.system_id]
        for row in session.scalars(select(PromotedTheoremRow))
    }
    assert where["ax-5"] == "First-order logic"
    assert where["ax-1"] == "Propositional calculus"


# ---------------------------------------------------------------------------
# The spine builder on its own
# ---------------------------------------------------------------------------


def test_the_spine_is_wired_root_to_leaf(session, database) -> None:
    spine = layered_systems(session, corpus_specs(database, plan=LAYERS))

    assert [system.inherits_from_id for system in spine] == [
        None, spine[0].id, spine[1].id
    ]
    assert all(system.owner_id is None for system in spine)


def test_a_citation_resolves_through_the_chain_and_hits_its_cache(
    session: Session, database: Database
) -> None:
    """**D5's first invariant, and the first read of D3's per-layer digests.**

    A stored theorem's terms are guarded by the digest of the system they were
    composed against — for an ancestor's entry, the *ancestor's*, which is what
    `LibraryChain` carries a digest per layer for. Nothing had ever read those
    back: `_Layers` wrote them and the read path recomputes its own from the
    rows, so a disagreement was invisible until something compared the two.

    `read_library`'s `fresh` is exactly the set whose stored digest still
    matches. Anything outside it re-parses — silently, since a stale digest is a
    miss and never a wrong answer, which is how this went unnoticed for the whole
    life of P4.

    Measured on `set.mm` at N = 2,676: 8,581 citations resolved through the
    spine, **0 of them cached** before `symbols.inclusion_position` and **all
    8,581** after — including **1,486 that cross a layer boundary**, which is the
    case a per-layer digest exists for and a corpus-wide one would get wrong.
    """
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system for system in systems(session)}
    parent = {i: s.inherits_from_id for i, s in spine.items()}

    def chain(system_id: uuid.UUID | None) -> list[FormalSystem]:
        walked: list[FormalSystem] = []
        while system_id is not None:
            walked.append(spine[system_id])
            system_id = parent[system_id]
        return list(reversed(walked))

    references: dict[uuid.UUID, list[str | None]] = {}
    for line in session.scalars(select(ProofLineRow)):
        references.setdefault(line.proof_id, []).append(line.reference)

    resolved = cached = crossed = 0
    for proof in session.scalars(select(Proof)):
        # The label set the *read path* uses — `cited_labels` over the stored
        # `reference` column, not `proof_lines.rule`, which is a different thing
        # and null for a definitional step (`_recheck` below does the same).
        labels = cited_labels(references.get(proof.id, ()))
        if not labels:
            continue
        _spec, library = effective_library(chain(proof.formal_system_id))
        pending = read_library(
            session, library, labels, hypotheses_of=proof.theorem_id
        )
        resolved += len(pending.cited)
        cached += len(pending.fresh)
        crossed += sum(
            1 for entry in pending.cited
            if entry.system_id != proof.formal_system_id
        )

    # Every citation this fixture makes is cached, and *some of them reach an
    # ancestor* — without which `LibraryChain`'s per-layer digest would never be
    # exercised and this test would pin nothing it claims to (found in review).
    assert resolved > 0 and cached == resolved
    assert crossed > 0


def _recheck(
    session: Session, proof: Proof, chain: Sequence[FormalSystem]
) -> EngineProof | None:
    """Re-check one stored proof entirely from its rows, through its own chain.

    The `POST /proofs/{id}/verify` row path (`app/routers/proofs.py`) with the
    HTTP and the ownership taken away: build the effective system from the
    stored parts, rebuild the lines from `proof_lines`, and resolve what they
    cite through `LibraryChain`. The verdict is *not* read back — numbering,
    scope and justification are all re-derived — so this is a re-check that
    happens to skip the parse, which is the whole of P2.
    """
    spec, library = effective_library(chain)
    build = build_spec(
        spec,
        schema_terms=load_schema_terms(
            session, chain[-1], spec, inherited_rule_count(chain)
        ),
        definition_terms=load_definition_terms(
            session, chain[-1], spec, inherited_definition_count(chain)
        ),
    )
    assert "errors" not in build, build.get("errors")
    compiled = build["system"]
    context = term_context(compiled)

    def cited(references: Sequence[str | None]) -> PendingCitations:
        pending = read_library(
            session, library, cited_labels(references),
            hypotheses_of=proof.theorem_id,
        )
        return PendingCitations(
            pending.term_ids,
            lambda graph: [
                compiled.promote(theorem)
                for theorem in pending.promote(compiled, context, graph).values()
            ],
        )

    # `proof=` seeds the lemmas a proof may cite by alias, which the router
    # takes from `proof_references`. An import creates none — a Metamath proof
    # cites labels, not other proofs — but passing the root rather than letting
    # one be made keeps this the same call the router makes, so a proof that did
    # carry references would not silently re-check against fewer of them.
    root = EngineProof(formal_system=compiled)
    root.reference_context = {}
    return load_proof_for_check(
        session, proof.id, compiled, context, proof=root, resolve_citations=cited
    )


def test_a_stored_layered_proof_rechecks_to_the_verdict_the_import_gave_it(
    session: Session, database: Database
) -> None:
    """**D5's pinned item**, and it needed the cache to work to mean anything.

    A layered import's proofs are stored against their own layers, and their
    citations reach across the spine. Re-checking one from its rows therefore
    exercises the whole read path at once — the effective spec built from the
    chain's parts, the lines rebuilt from `proof_lines`, and the library resolved
    nearest-first with each layer's own digest guarding its own cached terms.

    Against a digest that never matched, this test would still have passed: the
    citations would have re-parsed and reached the same answer, which is exactly
    what makes a cache's failure silent. It is only after `inclusion_position`
    that a green result here says the thing it appears to say.
    """
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    spine = {system.id: system for system in systems(session)}
    parent = {i: s.inherits_from_id for i, s in spine.items()}

    def chain(system_id: uuid.UUID | None) -> list[FormalSystem]:
        walked: list[FormalSystem] = []
        while system_id is not None:
            walked.append(spine[system_id])
            system_id = parent[system_id]
        return list(reversed(walked))

    rechecked = {}
    for proof in session.scalars(select(Proof)):
        loaded = _recheck(session, proof, chain(proof.formal_system_id))
        assert loaded is not None, f"{proof.name} stored no lines"
        rechecked[proof.name] = (bool(loaded.valid), bool(proof.valid))

    # Every layer's proof, re-checked from rows, agrees with what the import
    # stored — including the two whose citations cross a layer boundary.
    assert rechecked == {
        "pc-thm": (True, True),
        "fol-thm": (True, True),
        "fol-cites-pc": (True, True),
        "zf-thm": (True, True),
    }


def test_the_same_slice_imported_twice_gives_the_same_partition(
    session: Session, database: Database
) -> None:
    # D5's other pinned item. Nothing in the split may depend on anything but the
    # file and the plan — not on a uuid, not on which layer happened to be
    # flushed first. Asserted on the *names*, since the ids differ between runs
    # by construction and are the one thing that must.
    #
    # Both runs share a process, so this cannot see a `PYTHONHASHSEED`-dependent
    # ordering; what it does cover is everything the run itself decides, which is
    # where a partition would realistically drift.
    first = import_corpus(session, database, name="Corpus", plan=LAYERS)
    spine = {system.id: system.name for system in systems(session)}
    partition = {
        proof.name: spine[proof.formal_system_id]
        for proof in session.scalars(select(Proof))
    }

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_STORE_TABLES)
    try:
        with Session(engine) as again:
            second = import_corpus(again, parse(CORPUS), name="Corpus", plan=LAYERS)
            twice = {system.id: system.name for system in systems(again)}
            repeated = {
                proof.name: twice[proof.formal_system_id]
                for proof in again.scalars(select(Proof))
            }
    finally:
        engine.dispose()

    # Non-vacuous: there is a partition to compare, and it has more than one part.
    assert len(partition) == first.checked > 0
    assert len(set(partition.values())) > 1
    assert repeated == partition
    assert [layer.name for layer in second.layers] == [
        layer.name for layer in first.layers
    ]
    assert [layer.proofs for layer in second.layers] == [
        layer.proofs for layer in first.layers
    ]


def test_no_citation_is_stranded_where_its_proof_cannot_reach_it(
    session: Session, database: Database
) -> None:
    # **D5's misfiled-plan guard.** §5.2 says a citation resolves against the
    # proof's own layer and then its ancestors' — never a sibling's, never a
    # descendant's. A proof filed where it cannot see what it cites is stored as
    # verified and is *not* re-verifiable, which is a lie in the database rather
    # than a failure of the run, and so is exactly what nothing notices.
    import_corpus(session, database, name="Corpus", plan=LAYERS)

    assert unreachable_citations(session) == ()


def test_a_proof_moved_out_of_reach_of_its_citation_is_caught(
    session: Session, database: Database
) -> None:
    # The same guard, given something to find. A positional partition cannot
    # produce this — `set.mm`'s order guarantees a cited label is declared before
    # the proof citing it, and every boundary is a file position — so it is
    # exercised by moving a stored proof after the fact, which is what a plan
    # deciding layers by anything other than position would do.
    import_corpus(session, database, name="Corpus", plan=LAYERS)
    spine = systems(session)

    stranded = session.scalar(select(Proof).where(Proof.name == "zf-thm"))
    stranded.formal_system_id = spine[1].id  # up one layer, out of ZF's sight
    session.flush()

    caught = unreachable_citations(session)
    assert [(u.proof, u.label, u.declared_in) for u in caught] == [
        ("zf-thm", "ax-ext", ("ZF set theory",))
    ]
    assert caught[0].filed_in == "First-order logic"


def test_a_label_declared_in_two_layers_is_reachable_from_either(
    session: Session, database: Database
) -> None:
    # A label is unique per *system*, not per database — `_nearest` exists
    # because a spine may declare one twice — so "where is this label declared?"
    # has more than one answer, and a citation is stranded only when the chain
    # reaches *none* of them. Keyed by label alone the guard answers with
    # whichever row the query returned last, which invents a failure as readily
    # as it hides one (found in review).
    import_corpus(session, database, name="Corpus", plan=LAYERS)
    spine = systems(session)

    # `fol-thm` cites `ax-4`, which its own layer declares. Promote a second
    # `ax-4` in the *leaf*, which the first-order layer cannot see: the citation
    # is still reachable through FOL's own copy, and calling it stranded because
    # a descendant happens to share the spelling would be a false alarm.
    own = session.scalar(
        select(PromotedTheoremRow).where(PromotedTheoremRow.label == "ax-4")
    )
    session.add(
        PromotedTheoremRow(
            system_id=spine[-1].id,
            label=own.label,
            statement=own.statement,
            primitive=own.primitive,
        )
    )
    session.flush()

    assert unreachable_citations(session) == ()
