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
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("regex")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db.metamath_store import import_corpus, layered_systems
from app.db.models import FormalSystem, Proof
from app.db.promoted_theorems import PromotedTheoremRow
from website.logical.metamath import parse
from website.logical.metamath.corpus import corpus_specs
from website.logical.metamath.setmm import LAYERS

from tests.test_metamath_layered_specs import CORPUS
from tests.test_metamath_persistence import _TABLES


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
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
    Base.metadata.create_all(plain_engine, tables=_TABLES)
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


# ---------------------------------------------------------------------------
# The spine builder on its own
# ---------------------------------------------------------------------------


def test_the_spine_is_wired_root_to_leaf(session, database) -> None:
    spine = layered_systems(session, corpus_specs(database, plan=LAYERS))

    assert [system.inherits_from_id for system in spine] == [
        None, spine[0].id, spine[1].id
    ]
    assert all(system.owner_id is None for system in spine)
