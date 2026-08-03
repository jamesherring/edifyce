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

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("regex")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db.descriptions import LabelDescriptionRow
from app.db.metamath_store import import_corpus, layered_systems
from app.db.models import FormalSystem, Proof, ProofFolder
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.systems import (
    NotationPieceRow,
    NotationRulePieceRow,
    NotationRulePinRow,
    NotationRuleRow,
)
from website.logical.metamath import parse
from website.logical.metamath.corpus import corpus_specs
from website.logical.metamath.setmm import LAYERS

from tests.test_metamath_layered_specs import CORPUS
from tests.test_metamath_persistence import _TABLES


# The persistence suite's tables, plus the notation ones: this fixture carries a
# `$t` block, so an import here derives a notation and has somewhere to put it.
_STORE_TABLES = _TABLES + [
    model.__table__
    for model in (
        NotationPieceRow, NotationRuleRow, NotationRulePinRow, NotationRulePieceRow
    )
]


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_STORE_TABLES)
    with Session(engine) as handle:
        yield handle


@pytest.fixture
def database():
    return parse(CORPUS)


def systems(session) -> list[FormalSystem]:
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
    assert linked == {"pc-thm": True, "fol-thm": True, "zf-thm": True}


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
    assert report.theorems == 6
    assert all(proof.theorem_id is not None for proof in session.scalars(select(Proof)))


# ---------------------------------------------------------------------------
# The spine builder on its own
# ---------------------------------------------------------------------------


def test_the_spine_is_wired_root_to_leaf(session, database) -> None:
    spine = layered_systems(session, corpus_specs(database, plan=LAYERS))

    assert [system.inherits_from_id for system in spine] == [
        None, spine[0].id, spine[1].id
    ]
    assert all(system.owner_id is None for system in spine)
