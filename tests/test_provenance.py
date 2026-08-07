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
from app.db.promoted_theorems import PromotedTheoremPremiseRow, PromotedTheoremRow
from app.db.provenance import Provenance, by_layer, provenance
from app.db.systems import DefinitionRow, RuleRow, SymbolRow
from app.db.terms import TermRow
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
$( Proved from a *propositional* axiom and yet stated with ZF's own `e.`, so
   nothing it cites needs this layer and its notation does. `set.mm`'s `sptruw`
   is this shape, and the citation graph alone calls it movable. $)
zf-grammar-pinned $p |- ( A e. A -> ( ph -> A e. A ) ) $= ( wcel ax-1 ) BCAD $.
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
        "zf-grammar-pinned": ZF,
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


def test_notation_pins_a_proof_its_citations_would_let_go(imported: Session) -> None:
    # The grammar half, and the case the citation graph alone gets wrong.
    # `zf-grammar-pinned` is proved from a propositional axiom, so nothing it
    # cites needs ZF — and it is *stated* with `e.`, which ZF declares, so it
    # cannot be filed anywhere shallower. `set.mm`'s `sptruw` is this shape.
    report = reports(imported)["zf-grammar-pinned"]

    assert report.deepest_cited == PC
    assert report.depends_only_on_shallower
    assert report.deepest_grammar == ZF
    assert report.grammar_depth == report.filed
    assert not report.could_be_filed_lower


def test_a_proof_shallow_in_both_can_really_move(imported: Session) -> None:
    # The contrast, so the assertion above is about *notation* and not about
    # every proof: `fol-via-pc` is propositional in what it cites and in what it
    # is written in, and moving it to PC would leave nothing behind.
    report = reports(imported)["fol-via-pc"]

    assert (report.deepest_cited, report.deepest_grammar) == (PC, PC)
    assert report.could_be_filed_lower


def test_a_proof_pinned_by_a_lemma_is_not_movable_either(imported: Session) -> None:
    # And the third way to be held in place, which neither of the two above is:
    # `zf-via-fol` is written in propositional notation and rests on a
    # propositional axiom, but cites a *first-order* lemma. It can leave ZF; it
    # cannot reach PC, which is why `could_be_filed_lower` is about the layer
    # below rather than about the root.
    report = reports(imported)["zf-via-fol"]

    assert (report.deepest_cited, report.deepest_grammar) == (FOL, PC)
    assert report.could_be_filed_lower
    assert report.cited_depth == 1


def test_notation_a_definition_introduces_pins_a_proof_too(
    imported: Session,
) -> None:
    # **From review.** A defined form's constructor is `f"{sort}:{higher}"`, and
    # the `:` is deliberate — a declared production's name is forced to
    # `[A-Za-z0-9_]+`, so the pair keeps defined notation out of the productions'
    # namespace. A lookup against `symbols` alone therefore never matches one,
    # and the walk fell back to the *sort*, declared at the root: a proof written
    # in a deep layer's own abbreviation reported as movable all the way down.
    spine = list(
        imported.scalars(select(FormalSystem).order_by(FormalSystem.created_at))
    )
    sort = imported.scalar(
        select(SymbolRow).where(
            SymbolRow.system_id == spine[1].id, SymbolRow.name == "wff"
        )
    )
    imported.add(
        DefinitionRow(
            system_id=spine[1].id,
            position=0,
            symbol_id=sort.id,
            name="subset",
            higher="A C_ A",
            lower="A e. A",
        )
    )
    # `fol-via-pc` cites only propositional theorems, so nothing but the notation
    # can hold it in first-order logic — and now a line of it is written in that
    # layer's own abbreviation.
    written = imported.scalar(select(Proof).where(Proof.name == "fol-via-pc"))
    line = next(row for row in written.line_rows if row.term_id is not None)
    imported.get(TermRow, line.term_id).constructor = f"{sort.name}:A C_ A"
    imported.flush()

    report = reports(imported)["fol-via-pc"]
    assert report.deepest_grammar == FOL
    assert report.depends_only_on_shallower
    assert not report.could_be_filed_lower


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
    # Not "could be filed lower": what it cites is reachable from nowhere on its
    # chain, shallower least of all.
    assert not report.depends_only_on_shallower

    fol = by_layer(provenance(imported))[1]
    assert fol.misfiled == 1
    # **From review.** A misfiled proof used to fall through every axiom bucket,
    # so the layer printed three proofs whose columns summed to two.
    assert fol.own_axioms + fol.lower_axioms + fol.no_axioms + fol.misfiled == (
        fol.proofs
    )


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


def test_a_label_another_corpus_declares_is_not_a_dependency(
    imported: Session,
) -> None:
    # **From review, and the worst of what it found.** `proof_lines.rule` holds
    # whatever justified the line, which for an ordinary inference rule is a name
    # like `MP` that any system may declare. Resolving the out-of-chain fallback
    # database-wide turned that coincidence of spelling into a dependency on an
    # unrelated corpus — and, since that corpus is off the chain, into a misfiled
    # hard failure. The fallback is keyed by the tree's root for exactly this.
    stranger = FormalSystem(name="Someone else's logic", slug="stranger")
    imported.add(stranger)
    imported.flush()
    imported.add(
        PromotedTheoremRow(
            system_id=stranger.id, label="MP", statement="|- ph", primitive=True
        )
    )
    cites_a_rule = imported.scalar(select(Proof).where(Proof.name == "pc-thm"))
    for line in cites_a_rule.line_rows:
        line.rule = "MP"  # a rule of its own system, not a promoted theorem
    imported.flush()

    report = reports(imported)["pc-thm"]
    assert report.axioms == ()
    assert report.deepest_axiom is None
    assert not report.misfiled


def test_a_rule_of_the_proofs_own_chain_is_not_a_citation_of_a_sibling(
    imported: Session,
) -> None:
    # **From review, the second round.** Keying the fallback by the tree's root
    # stops one corpus reaching another, and leaves two *branches of one tree*
    # colliding: a proof citing its own inference rule `R` found a sibling's
    # promoted `R` under the same root and was called misfiled for it. A rule
    # its chain declares resolves to no layer and drops out instead.
    spine = list(
        imported.scalars(select(FormalSystem).order_by(FormalSystem.created_at))
    )
    imported.add(
        RuleRow(
            system_id=spine[0].id, position=99, label="R", name="R",
            deduction="|- ph",
        )
    )
    sibling = FormalSystem(
        name="A sibling branch", slug="sibling", inherits_from_id=spine[0].id
    )
    imported.add(sibling)
    imported.flush()
    imported.add(
        PromotedTheoremRow(
            system_id=sibling.id, label="R", statement="|- ph", primitive=True
        )
    )
    cites_its_rule = imported.scalar(select(Proof).where(Proof.name == "fol-via-ax4"))
    for line in cites_its_rule.line_rows:
        line.rule = "R"
    imported.flush()

    report = reports(imported)["fol-via-ax4"]
    assert not report.misfiled
    assert (report.deepest_cited, report.axioms) == (None, ())


def test_a_hypothesis_of_the_theorem_being_proved_is_not_a_citation(
    imported: Session,
) -> None:
    # The other thing a chain explains without any library entry. A Metamath `$e`
    # is citable only from inside the block declaring it, so it is a column on
    # the theorem rather than an entry of its own — and a proof citing one
    # depends on no layer. Left in, it would fall through to the fallback on the
    # same coincidence of spelling a rule does.
    spine = list(
        imported.scalars(select(FormalSystem).order_by(FormalSystem.created_at))
    )
    proof = imported.scalar(select(Proof).where(Proof.name == "fol-via-ax4"))
    imported.add(
        PromotedTheoremPremiseRow(
            theorem_id=proof.theorem_id, position=0, statement="|- ph", label="hyp.1"
        )
    )
    sibling = FormalSystem(
        name="A sibling branch", slug="sibling", inherits_from_id=spine[0].id
    )
    imported.add(sibling)
    imported.flush()
    imported.add(
        PromotedTheoremRow(
            system_id=sibling.id, label="hyp.1", statement="|- ph", primitive=True
        )
    )
    for line in proof.line_rows:
        line.rule = "hyp.1"
    imported.flush()

    assert not reports(imported)["fol-via-ax4"].misfiled


def test_the_reports_come_back_in_a_stable_order(imported: Session) -> None:
    # **From review.** Callers compare whole reports for equality — the assertion
    # below, and `scripts/check_provenance.py` — across a bulk `UPDATE proofs`.
    # An unordered scan is stable on SQLite's rowid and is not on Postgres, where
    # the update reorders it and the comparison fails for a reason that has
    # nothing to do with what it claims to test.
    # Corpus order, which `position` records — so the order is also the one a
    # reader expects rather than merely a repeatable one.
    assert [report.proof for report in provenance(imported)] == [
        name
        for name, in imported.execute(
            select(Proof.name).order_by(Proof.position, Proof.id)
        )
    ]
    assert [report.proof for report in provenance(imported)] == [
        "pc-thm", "fol-via-pc", "fol-via-ax4", "zf-via-fol", "zf-via-ext",
        "zf-grammar-pinned",
    ]


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
    assert len(before) == 6


def test_the_per_layer_report_counts_each_theorem_once(imported: Session) -> None:
    # The shape §7.2 asks for: per layer, how many theorems depend on their own
    # layer's axioms rather than a shallower one.
    layers = by_layer(provenance(imported))

    assert [(layer.name, layer.depth) for layer in layers] == [
        (PC, 0), (FOL, 1), (ZF, 2)
    ]
    assert [layer.proofs for layer in layers] == [1, 2, 3]
    assert [layer.own_axioms for layer in layers] == [1, 1, 1]
    assert [layer.lower_axioms for layer in layers] == [0, 1, 2]
    assert [layer.only_shallower for layer in layers] == [0, 1, 2]
    # And the notation half: of ZF's two whose citations are all shallower, one
    # is held there by its own `e.` and cannot actually move.
    assert [layer.could_be_lower for layer in layers] == [0, 1, 1]
    # Every theorem falls in exactly one bucket, misfiled included.
    for layer in layers:
        assert layer.own_axioms + layer.lower_axioms + layer.no_axioms + (
            layer.misfiled
        ) == layer.proofs


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
