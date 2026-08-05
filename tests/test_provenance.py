"""Where a proof's dependencies say it belongs, as against where it was filed.

D6 of docs/system-relationships-roadmap.md (§5.5, §7.2). A layer plan files a
theorem by *subject matter* — the section header it sits under — and that is not
the same as what it depends on. `app.db.provenance` follows the citation graph
transitively and says which layer each proof actually reaches, which is the check
on whether the boundaries were drawn in the right place.

The fixture is shaped to separate the two questions the module reports on, since
a corpus where they always agree would pin neither:

- `fol-via-pc` is filed in first-order logic and bottoms out in a propositional
  axiom, so it *could have been* a PC theorem;
- `zf-via-fol` cites that first-order lemma, so it cannot move to PC — the lemma
  is not there — and yet assumes nothing first-order either. Its deepest
  **citation** and its deepest **axiom** are different layers, which is the whole
  reason the module answers both.

Every proof here cites through at least one other proof, so the traversal being
transitive is what the assertions rest on rather than something they take on
trust.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("regex")

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.db import Base
from app.db.metamath_store import import_corpus
from app.db.models import FormalSystem, Proof
from app.db.promoted_theorems import PromotedTheoremRow
from app.db.provenance import Provenance, by_layer, provenance
from website.logical.metamath import parse
from website.logical.metamath.setmm import LAYERS

from tests.test_metamath_layered_specs import PART, SECTION

PC = "Propositional calculus"
FOL = "First-order logic"
ZF = "ZF set theory"

# `set.mm`'s own section titles, so the shipped plan opens the layers. Each proof
# is a compressed one, the only form the importer reads.
CORPUS = f"""
$c |- wff class ( ) -> A. e. $.
$v ph ps x A $.
wph $f wff ph $.
wps $f wff ps $.
vx $f class x $.
cA $f class A $.

$( {PART}
   LOGIC
   {PART} $)
$( {SECTION}
   Pre-logic
   {SECTION} $)
wi $a wff ( ph -> ps ) $.
$( {SECTION}
   Propositional calculus
   {SECTION} $)
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
pc-thm $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.

$( {SECTION}
   Predicate calculus with equality:  Tarski's system S2
   {SECTION} $)
wal $a wff A. x ph $.
ax-4 $a |- ( A. x ph -> ph ) $.
$( Filed in first-order logic and proved from a *propositional* theorem, so its
   deepest dependency is a layer shallower than the one holding it. $)
fol-via-pc $p |- ( ph -> ( ps -> ph ) ) $= ( pc-thm ) ABC $.
$( And one that does use its own layer, for the contrast. $)
fol-via-ax4 $p |- ( A. x ph -> ph ) $= ( ax-4 ) ABC $.

$( {PART}
   SET THEORY
   {PART} $)
$( {SECTION}
   ZF Set Theory - start with the Axiom of Extensionality
   {SECTION} $)
wcel $a wff A e. A $.
ax-ext $a |- ( A e. A -> A e. A ) $.
$( Cites a first-order lemma, so it is pinned to FOL — and that lemma rests on a
   propositional axiom, so it assumes nothing first-order. The two answers differ
   here and nowhere else in this fixture. $)
zf-via-fol $p |- ( ph -> ( ps -> ph ) ) $= ( fol-via-pc ) ABC $.
zf-via-ext $p |- ( A e. A -> A e. A ) $= ( ax-ext ) AB $.
"""


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def imported(session: Session) -> Session:
    import_corpus(session, parse(CORPUS), name="Corpus", plan=LAYERS)
    return session


def reports(session: Session) -> dict[str, Provenance]:
    return {report.proof: report for report in provenance(session)}


def test_the_fixture_is_the_three_layers_it_claims_to_be(imported: Session) -> None:
    # Guarding the guard. Every assertion below is about a *boundary*, and a plan
    # whose titles the file does not open gives one system — at which point the
    # depths are all zero and nothing here can fail (the shape D4 and D5 each hit).
    filed = {report.proof: report.filed_in for report in provenance(imported)}
    assert filed == {
        "pc-thm": PC,
        "fol-via-pc": FOL,
        "fol-via-ax4": FOL,
        "zf-via-fol": ZF,
        "zf-via-ext": ZF,
    }


def test_a_theorem_reports_the_axiom_it_rests_on_through_a_lemma(
    imported: Session,
) -> None:
    # The transitive half. `pc-thm` is not an axiom, so a report that followed
    # only *direct* citations would say `fol-via-pc` rests on nothing.
    report = reports(imported)["fol-via-pc"]

    assert report.axioms == ("ax-1",)
    assert report.deepest_axiom == PC


def test_a_proof_filed_above_everything_it_uses_says_so(imported: Session) -> None:
    # §5.5's headline: a theorem in first-order logic that touches nothing above
    # propositional calculus *is* a propositional theorem.
    report = reports(imported)["fol-via-pc"]

    assert report.filed == 1
    assert report.cited_depth == 0
    assert report.depends_only_on_shallower
    assert not report.needs_its_own_axioms


def test_a_proof_that_uses_its_own_layer_is_not_reported_as_lower(
    imported: Session,
) -> None:
    # The contrast that stops the assertion above from being about every proof.
    report = reports(imported)["fol-via-ax4"]

    assert report.deepest_axiom == FOL
    assert report.needs_its_own_axioms
    assert not report.depends_only_on_shallower


def test_the_deepest_citation_and_the_deepest_axiom_are_different_questions(
    imported: Session,
) -> None:
    # Why the module answers both. `zf-via-fol` cannot be re-filed in PC — the
    # first-order lemma it cites is not there — and yet it assumes nothing
    # first-order, so a report of either alone would say something false about it.
    report = reports(imported)["zf-via-fol"]

    assert (report.deepest_cited, report.deepest_axiom) == (FOL, PC)
    assert report.axioms == ("ax-1",)
    # Filed in ZF, pinned no deeper than FOL: it could be filed lower, but not as
    # low as its axioms alone would allow.
    assert report.depends_only_on_shallower
    assert report.cited_depth == 1
    assert report.axiom_depth == 0


def test_nothing_in_a_corpus_in_dependency_order_is_misfiled(imported: Session) -> None:
    # `set.mm` declares a label before the proof citing it and every boundary is
    # a position in the file, so a positional plan cannot file a proof above what
    # it depends on. The next test gives the check something to find.
    assert [report.proof for report in provenance(imported) if report.misfiled] == []


def test_a_proof_moved_below_its_dependency_is_reported_as_misfiled(
    imported: Session,
) -> None:
    # The invalid case §7.2's D6 asks for: a theorem depending on a layer deeper
    # than the one holding it. Not producible by a positional plan, so it is made
    # by moving a stored proof — which is what a plan deciding layers by anything
    # other than file position would do.
    spine = list(
        imported.scalars(select(FormalSystem).order_by(FormalSystem.created_at))
    )
    stranded = imported.scalar(select(Proof).where(Proof.name == "zf-via-ext"))
    stranded.formal_system_id = spine[1].id  # into FOL, above the ZF axiom it uses
    imported.flush()

    report = reports(imported)["zf-via-ext"]
    assert report.misfiled
    assert (report.filed_in, report.deepest_cited) == (FOL, ZF)
    assert by_layer(provenance(imported))[1].misfiled == 1


def test_a_label_shadowed_by_a_nearer_layer_resolves_to_the_nearer_one(
    imported: Session,
) -> None:
    # A label is unique per *system*, not per database, so a citation resolves
    # nearest-first — `LibraryChain`'s rule, and the one the checker itself
    # applied. `fol-via-pc` cites `pc-thm` directly; declaring a first-order
    # `pc-thm` over the top must make it mean *that* one.
    spine = list(
        imported.scalars(select(FormalSystem).order_by(FormalSystem.created_at))
    )
    root = imported.scalar(
        select(PromotedTheoremRow).where(PromotedTheoremRow.label == "pc-thm")
    )
    imported.add(
        PromotedTheoremRow(
            system_id=spine[1].id,
            label=root.label,
            statement=root.statement,
            # Primitive, so the traversal stops there and the assertion is about
            # which entry was resolved rather than about what lies below it.
            primitive=True,
        )
    )
    imported.flush()

    assert reports(imported)["fol-via-pc"].deepest_axiom == FOL
    # And `pc-thm` itself, filed in the root, cannot see the new entry — which is
    # what makes this about the chain rather than about the label.
    assert reports(imported)["pc-thm"].deepest_axiom == PC


def test_the_report_never_reads_proof_source(imported: Session) -> None:
    # §7.2's D6: the report is a graph query over rows. Blanking the source (and
    # the stored verdict blob beside it) must change nothing — an assertion about
    # behaviour rather than about which modules were imported, and the only kind
    # that stays true when someone adds a shortcut later.
    before = provenance(imported)
    imported.execute(update(Proof).values(source="", result=None))
    imported.flush()

    assert provenance(imported) == before
    # And the report was not empty, so "unchanged" is not "nothing either way".
    assert len(before) == 5


def test_the_per_layer_report_counts_each_theorem_once(imported: Session) -> None:
    # The shape §7.2 asks for: per layer, how many theorems depend on their own
    # layer's axioms rather than a shallower one.
    layers = by_layer(provenance(imported))

    assert [(layer.name, layer.depth) for layer in layers] == [
        (PC, 0), (FOL, 1), (ZF, 2)
    ]
    assert [layer.proofs for layer in layers] == [1, 2, 2]
    assert [layer.own_axioms for layer in layers] == [1, 1, 1]
    assert [layer.lower_axioms for layer in layers] == [0, 1, 1]
    assert [layer.only_shallower for layer in layers] == [0, 1, 1]
    # Every theorem falls in exactly one of the three axiom buckets.
    for layer in layers:
        assert layer.own_axioms + layer.lower_axioms + layer.no_axioms == layer.proofs


def test_a_proof_that_cites_no_library_entry_reaches_nothing(
    session: Session,
) -> None:
    # "Depends on nothing" and "depends on the root" are different facts, and
    # folding the first into the second would report an unproved stub as a
    # propositional theorem. Counted apart in `no_axioms`.
    import_corpus(session, parse(CORPUS), name="Corpus", plan=LAYERS)
    lonely = session.scalar(select(Proof).where(Proof.name == "pc-thm"))
    for line in lonely.line_rows:
        line.rule = None
    session.flush()

    report = reports(session)["pc-thm"]
    assert (report.deepest_cited, report.deepest_axiom) == (None, None)
    assert report.axioms == ()
    assert by_layer(provenance(session))[0].no_axioms == 1
    # **From the corpus run.** Reaching nothing does not make a *root* theorem
    # movable: there is no shallower layer to move it to. Reported as movable,
    # the root's column read 2 on a `set.mm` slice whose right answer is 0.
    assert not report.depends_only_on_shallower


def test_a_theorem_that_cites_nothing_can_still_move_off_a_deeper_layer(
    session: Session,
) -> None:
    # The other half of that fix, so it is a rule about the *root* and not a rule
    # about citing nothing: a first-order theorem resting on no library entry
    # really could have been filed in propositional calculus.
    import_corpus(session, parse(CORPUS), name="Corpus", plan=LAYERS)
    lonely = session.scalar(select(Proof).where(Proof.name == "fol-via-ax4"))
    for line in lonely.line_rows:
        line.rule = None
    session.flush()

    report = reports(session)["fol-via-ax4"]
    assert report.deepest_cited is None
    assert report.depends_only_on_shallower
