"""A Metamath import keeps its parse: the corpus walk, and the rows it stores.

Two things are proved here, and they are the two halves of roadmap §6.5.

**The walk** (:mod:`website.logical.metamath.corpus`) checks a whole database in
one ordered pass — grammar extended as notation is declared, each theorem checked
against only what precedes it, then promoted — where ``import_theorem`` rebuilds
the world per theorem. Ordering and hypothesis scoping must survive that.

**The rows** (:mod:`app.db.metamath_store`) are the point of the exercise. An
import used to produce proof text and discard the parse, so the corpus was
re-read and re-parsed in full on every run while ``terms`` / ``proof_lines`` sat
empty. After an import the structure is *in the database*: a row per line, its
justification as edges, its formula as an interned kernel term that reloads
without the ``.mm`` file, the grammar, or the checker.

The fragment is quoted from set.mm — the statements, the ``${ … $}`` scoping and
the verbatim compressed proofs — so what is imported is the real thing.
"""

from __future__ import annotations

import re
from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, event, func, select
from sqlalchemy import distinct as distinct_
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db import (
    PendingCitations,
    cited_labels,
    load_proof_for_check,
    load_theorems,
    prefetch_terms,
    read_library,
)
from website.logical.declarative import build_spec, library_digest
from website.logical.formal_system.proof import Proof as EngineProof
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.promoted_theorems_mapping import LibraryChain, read_theorems
from app.db import metamath_store
from app.db.metamath_store import import_corpus
from app.db.models import FormalSystem, Proof, ProofFolder
from app.db.claims import LabelClaimRow
from tests.database import create_tables, database_url, throwaway_database
from app.db.descriptions import (
    LabelAttributionRow,
    LabelDescriptionRow,
    LabelCitationRow,
    LabelReferenceRow,
)
from app.db.proof_lines import ProofLineAntecedentRow, ProofLineRow
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
from app.db.side_conditions import SideConditionRow
from app.db.systems_mapping import system_to_spec
from app.db.terms import TermChildRow, TermRow
from website.logical.declarative import build_spec as build_from_spec
from website.logical.declarative import build_system
from website.logical.metamath import parse, promote_assertions
from website.logical.metamath import corpus
from website.logical.metamath.corpus import corpus_spec, theorems, walk

# set.mm's opening propositional fragment: `wn`/`wi` for the grammar, the three
# Hilbert axioms, and five theorems with their stored compressed proofs. `2a1i`
# cites `a1i`, so the library is genuinely used and not just present.
PROPOSITIONAL = r"""
$c |- wff ( ) -> -. $.
$v ph ps ch $.
wph $f wff ph $.
wps $f wff ps $.
wch $f wff ch $.

wn $a wff -. ph $.
wi $a wff ( ph -> ps ) $.

${
  min $e |- ph $.
  maj $e |- ( ph -> ps ) $.
  ax-mp $a |- ps $.
$}
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
ax-2 $a |- ( ( ph -> ( ps -> ch ) ) -> ( ( ph -> ps ) -> ( ph -> ch ) ) ) $.

${
  mp2.1 $e |- ph $.
  mp2.2 $e |- ps $.
  mp2.3 $e |- ( ph -> ( ps -> ch ) ) $.
  mp2 $p |- ch $= ( wi ax-mp ) BCEABCGDFHH $.
$}
${
  a1i.1 $e |- ph $.
  a1i $p |- ( ps -> ph ) $= ( wi ax-1 ax-mp ) ABADCABEF $.
$}
${
  2a1i.1 $e |- ph $.
  2a1i $p |- ( ps -> ( ch -> ph ) ) $= ( wi a1i ) CAEBACDFF $.
$}
${
  a2i.1 $e |- ( ph -> ( ps -> ch ) ) $.
  a2i $p |- ( ( ph -> ps ) -> ( ph -> ch ) ) $=
    ( wi ax-2 ax-mp ) ABCEEABEACEEDABCFG $.
$}
"""

IMPORTED = ["mp2", "a1i", "2a1i", "a2i"]


@pytest.fixture(scope="module")
def database():
    return parse(PROPOSITIONAL)


# Everything an import writes: the system's own decomposition, its proofs, their
# line graphs, and the term graph the formulas intern into. `theorems` is left
# out because it carries a pgvector column SQLite cannot create — and an import
# writes none.
_TABLES = [
    model.__table__
    for model in (
        FormalSystem, BracketRow, SymbolRow, ProductionBindingRow, ProductionBindingScopeRow,
        LineRow, LinePartRow, DefinitionRow, DefinitionBindingRow,
        DefinitionFreshRow, AxiomRow, AxiomBindingRow, RuleRow,
        RuleAntecedentRow, RuleBindingRow, SideConditionRow,
        # `ProofFolder` before `Proof`: an import files each proof under the
        # section header covering it, so the outline is part of what it writes.
        ProofFolder, Proof, ProofLineRow, ProofLineAntecedentRow, TermRow, TermChildRow,
        # The citable library an import now writes alongside the proofs.
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
        # And what the file says about each label it names.
        LabelDescriptionRow, LabelAttributionRow, LabelReferenceRow,
        LabelCitationRow,
        LabelClaimRow,
    )
]


@pytest.fixture
def session(tmp_path):
    url = database_url(tmp_path)
    create_tables(url, _TABLES)
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture
def imported(session, database):
    return import_corpus(session, database, name="Propositional")


# ---------------------------------------------------------------------------
# The ordered walk
# ---------------------------------------------------------------------------
def test_the_walk_checks_every_theorem(database):
    checked = list(walk(database))

    assert [c.label for c in checked] == IMPORTED
    assert all(c.verified for c in checked), [
        (c.label, c.error, c.source) for c in checked if not c.verified
    ]


def test_a_syntactic_theorem_is_not_walked():
    # A `$p` with a syntax typecode (set.mm's `bj-0`) asserts no truth: there is
    # nothing for the kernel to check and nothing to promote, so the walk must
    # not offer it as a theorem — nor read it as notation.
    database = parse(
        r"""
$c |- wff ( ) -> $.
$v ph ps ch $.
wph $f wff ph $.
wps $f wff ps $.
wch $f wff ch $.
wi $a wff ( ph -> ps ) $.
bj-0 $p wff ( ( ph -> ps ) -> ch ) $= ( wi ) ABCDD $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
"""
    )
    assert [a.label for a in theorems(database)] == []


def test_a_theorems_givens_are_withdrawn_when_its_check_is_done(database):
    # A theorem's `$e` hypotheses are registered as givens so its premise lines
    # resolve, and `a1i.1` — a bare `|- ph` with `ph` schematic — proves anything
    # at all. They belong to its `${ … $}` block, so the walk (which, unlike
    # `import_theorem`, reuses one system for the whole file) must take them back
    # out again.
    system = build_system(corpus_spec(database, name="Propositional"))
    promote_assertions(database, system, before="a1i")

    checked = corpus._check(database, database.assertions["a1i"], system)

    assert checked.verified is True
    assert "a1i.1" not in system.promoted_theorems
    assert system.parse("( ps -> ch ) [a1i.1]").proof_lines[0].valid is False


def test_a_theorem_is_checked_against_only_what_precedes_it():
    # `2a1i` cites `a1i`, which the walk promoted after checking it. Move `a1i`
    # after it and the citation must fail: promotion follows the walk, so a
    # theorem declared later is not in the library when an earlier one is checked.
    a1i = (
        "${\n  a1i.1 $e |- ph $.\n"
        "  a1i $p |- ( ps -> ph ) $= ( wi ax-1 ax-mp ) ABADCABEF $.\n$}\n"
    )
    assert a1i in PROPOSITIONAL
    checked = {c.label: c for c in walk(parse(PROPOSITIONAL.replace(a1i, "") + a1i))}

    assert checked["a1i"].verified is True
    assert checked["2a1i"].error is not None
    assert "declared later" in checked["2a1i"].error


def test_a_prefix_with_no_grammar_is_reported_not_fatal():
    # A theorem stated before anything says which sort a `|-` statement is
    # written in cannot be checked. It is the *prefix* that is short, not the
    # database, so the walk reports it and carries on to the theorems that can be.
    database = parse(
        r"""
$c |- expr ( ) -> $.
$v p q $.
vp $f expr p $.
vq $f expr q $.
${
  early.1 $e |- p $.
  early $p |- p $= ( ) B $.
$}
imp $a expr ( p -> q ) $.
${
  late.1 $e |- p $.
  late $p |- p $= ( ) B $.
$}
"""
    )
    checked = {c.label: c for c in walk(database)}

    assert "cannot be told" in checked["early"].error
    assert checked["late"].verified is True


def test_the_stored_grammar_is_the_union_the_walk_ended_with(database):
    spec = corpus_spec(database, name="Propositional")

    # Notation, then a leaf per `$v` variable, then the shapeless production
    # including their `wff_var` sub-sort into `wff`.
    assert [p.name for p in spec.productions] == [
        "wn", "wi", "wff_var_ph", "wff_var_ps", "wff_var_ch", "wff_var",
    ]


# ---------------------------------------------------------------------------
# What lands in the database
# ---------------------------------------------------------------------------
def test_every_checked_theorem_is_stored_as_a_proof(session, database, imported):
    assert (imported.checked, imported.verified, imported.rejected) == (4, 4, 0)

    stored = session.scalars(select(Proof).order_by(Proof.position)).all()
    assert [p.name for p in stored] == IMPORTED
    assert all(p.valid for p in stored)
    # The source is the imported proof text, and it is what the rows describe.
    assert stored[1].source == "ph [a1i.1]\n( ph -> ( ps -> ph ) ) [ax-1]\n" \
        "( ps -> ph ) [ax-mp, 1, 2]"


def test_a_proof_stores_one_row_per_line_with_its_rule(session, imported):
    rows = _lines(session, "mp2")

    assert [(r.number, r.display, r.rule, r.valid) for r in rows] == [
        (1, "ps [mp2.2]", "mp2.2", True),
        (2, "ph [mp2.1]", "mp2.1", True),
        (3, "( ph -> ( ps -> ch ) ) [mp2.3]", "mp2.3", True),
        (4, "( ps -> ch ) [ax-mp, 2, 3]", "ax-mp", True),
        (5, "ch [ax-mp, 1, 4]", "ax-mp", True),
    ]
    # `rule` is not `reference` re-read: a promoted theorem resolves to an
    # ephemeral rule that appears in no system's rule list, so which theorem
    # justified a line is recoverable from nowhere else.
    assert rows[3].reference == "ax-mp, 2, 3"


def test_the_justification_graph_is_stored_as_edges(session, imported):
    # The point of the exercise on the proof side: "which lines is this one
    # derived from" is an edge, not a citation string waiting to be re-parsed.
    rows = _lines(session, "mp2")
    by_id = {row.id: row.number for row in rows}
    edges = {
        row.number: [by_id[e.antecedent_line_id] for e in row.antecedents]
        for row in rows
        if row.antecedents
    }

    assert edges == {4: [2, 3], 5: [1, 4]}
    # ...and in the rule's antecedent-slot order, which is what `position` keeps:
    # `ax-mp`'s minor premise first, then its major.
    assert [e.position for e in rows[4].antecedents] == [0, 1]


def test_every_formula_line_carries_an_interned_term(session, imported):
    rows = _lines(session, "a2i")

    assert all(row.term_id is not None for row in rows)
    assert imported.formulas == imported.lines


def test_a_stored_term_reloads_without_the_mm_file(session, imported):
    # The claim §6.5 makes: after an import the parse is *in the database*. The
    # system is rebuilt from its rows (no `.mm`, no importer), and each stored
    # term reloads into a live kernel term that renders the formula the line
    # states — so nothing here re-parses the proof source.
    system = session.scalars(select(FormalSystem)).one()
    built = build_from_spec(system_to_spec(system))
    assert "errors" not in built, built.get("errors")
    context = copy(built["system"].context)
    context.variables.update(built["system"].build_context.variables)

    rows = _lines(session, "a2i")
    graph = prefetch_terms(session, [row.term_id for row in rows])
    for row in rows:
        formula = row.display.split(" [")[0]
        assert graph.term(row.term_id, context).to_string() == formula


def test_equal_subterms_are_one_row_across_the_whole_corpus(session, imported):
    # Interning is per system, so the corpus lands in *one* term graph: the
    # formula `ph`, stated by three of the four proofs, is a single row.
    #
    # Counted over the *lines'* terms rather than over `terms` as a whole: the
    # library's statements intern into the same graph (app/db/promoted_theorems.py)
    # and would otherwise be counted as though the proofs had stated them.
    total_formulas = session.scalar(
        select(func.count()).select_from(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
    )
    distinct = session.scalar(
        select(func.count(distinct_(ProofLineRow.term_id))).where(
            ProofLineRow.term_id.is_not(None)
        )
    )

    assert total_formulas > distinct

    ph = session.scalars(
        select(TermRow).where(TermRow.literal == "ph", TermRow.kind == "node")
    ).all()
    assert len(ph) == 1


def test_an_import_records_where_it_came_from(session, database):
    # On the system, once, rather than on each of its proofs: 47,000 copies of
    # one sentence is what the column exists to avoid. A reader of a proof
    # already fetches its system, so it costs no request there either.
    import_corpus(session, database, name="Propositional", source="set.mm")

    system = session.scalars(select(FormalSystem)).one()
    assert system.provenance == (
        "Imported from Metamath's set.mm library. See https://us.metamath.org/"
    )


def test_provenance_names_the_library_only_when_the_caller_knows_it(session, database):
    # A `Database` is a parse and carries no file name, so an in-memory import —
    # every test here, and the diagnostic scripts — still says where the rows
    # came from without inventing which database it was.
    import_corpus(session, database, name="Propositional")

    system = session.scalars(select(FormalSystem)).one()
    assert system.provenance == (
        "Imported from Metamath's library. See https://us.metamath.org/"
    )


def test_an_import_is_ownerless_so_no_verify_can_overwrite_it(session, imported):
    # A stored system holds a grammar, definitions, axioms and rules — it has
    # nowhere to hold a *promoted theorem*, which is what the Metamath library is
    # made of (roadmap §3.2). So an imported proof cannot be re-checked from its
    # own rows, and the danger is a verify that tries: `_record_verdict` would
    # write `valid=False` and call `store_proof_lines`, whose first act is to drop
    # the imported structure.
    #
    # Ownerlessness is the guard, and it is the whole of it: `POST
    # /proofs/{id}/verify` writes back only for `user is not None and
    # proof.owner_id == user.id`. Publication decides who may *read*, which is a
    # separate question and one an import now answers yes to — so this asserts the
    # two apart rather than leaning on a draft to keep readers out.
    system = session.scalars(select(FormalSystem)).one()
    assert system.owner_id is None
    assert system.published_at is not None
    proofs = list(session.scalars(select(Proof)))
    assert all(p.owner_id is None for p in proofs)
    # Published exactly when it verified: publishing a rejected proof would put a
    # world-readable proof of nothing on the shelf.
    assert all((p.published_at is not None) == bool(p.valid) for p in proofs)
    assert any(p.published_at is not None for p in proofs)

    # The gap itself, pinned so §3.2 closing it is a visible change: the stored
    # system carries the grammar and nothing citable.
    spec = system_to_spec(system)
    assert sorted(p.name for p in spec.productions) == [
        "wff_var", "wff_var_ch", "wff_var_ph", "wff_var_ps", "wi", "wn",
    ]
    assert (spec.rules, spec.axioms) == ([], [])

    rebuilt = build_from_spec(spec)["system"]
    proof = session.scalars(select(Proof).where(Proof.name == "a1i")).one()
    assert proof.valid is True
    assert rebuilt.parse(proof.source).valid is False


def test_a_given_that_will_not_register_is_a_failure_not_a_rejection(
    session, database, monkeypatch
):
    # A theorem proves *under* its `$e` hypotheses. Checking one without a given
    # it needs does not refute it — it never checked it — so booking that as a
    # kernel rejection would file an import defect of ours as mathematics that
    # failed, and store `valid=False` against a theorem set.mm proves.
    real = corpus.promote_from_source

    def refuse(system, *, label, **kwargs):
        if label == "a1i.1":
            raise RuntimeError("cannot promote this given")
        return real(system, label=label, **kwargs)

    monkeypatch.setattr(corpus, "promote_from_source", refuse)
    report = import_corpus(session, database, name="Propositional")

    assert (report.verified, report.rejected, report.failed) == (3, 0, 1)
    assert report.failures == [("a1i", "cannot promote this given")]
    assert "a1i" not in session.scalars(select(Proof.name)).all()


def test_a_theorem_that_never_reached_the_kernel_is_reported_not_stored(session):
    # A proof that terminates on some *other* well-formed result is refused by
    # the importer, so there is no checked proof to store — the walk records why
    # and carries on rather than aborting the corpus.
    database = parse(PROPOSITIONAL.replace("( wi ax-1 ax-mp ) ABADCABEF", "( ax-1 ) A"))
    report = import_corpus(session, database, name="Propositional")

    assert (report.checked, report.verified, report.failed) == (4, 3, 1)
    assert report.failures[0][0] == "a1i"
    assert "proof concludes" in report.failures[0][1]
    # Ordered by the corpus's own position: the assertion is about *which*
    # proofs were stored, and an unordered select has no order to rely on.
    assert session.scalars(
        select(Proof.name).order_by(Proof.position)
    ).all() == ["mp2", "2a1i", "a2i"]


def test_committing_in_batches_stores_the_same_graph(session, database):
    # A whole-corpus run commits and empties the identity map periodically to
    # keep memory flat, which re-attaches the system between batches. Interning
    # is a read-then-insert against that system, so a term first seen in an
    # earlier batch must still be found rather than inserted twice.
    report = import_corpus(session, database, name="Propositional", batch=1)

    assert (report.checked, report.verified, report.lines) == (4, 4, 14)
    digests = session.scalars(select(TermRow.digest)).all()
    assert len(digests) == len(set(digests))
    assert [(r.number, r.rule) for r in _lines(session, "2a1i")] == [
        (1, "2a1i.1"), (2, "a1i"), (3, "a1i"),
    ]


def test_the_limit_stops_the_walk(session, database):
    report = import_corpus(session, database, limit=2, name="Propositional")

    assert report.checked == 2
    assert session.scalars(
        select(Proof.name).order_by(Proof.position)
    ).all() == ["mp2", "a1i"]


def test_a_nonsense_limit_or_batch_is_refused_before_anything_is_written(
    session, database
):
    # `walk` would fall silently empty on `limit=0` while `corpus_spec` blamed the
    # database for declaring no theorems, so the two entry points disagreed about
    # a caller's mistake. Both now refuse it, and neither leaves a system row.
    for bad in ({"limit": 0}, {"limit": -1}):
        with pytest.raises(ValueError, match="limit must be at least 1"):
            import_corpus(session, database, name="Propositional", **bad)

    # `batch` reached a `% batch` unguarded: zero raised ZeroDivisionError partway
    # through, and a negative one committed on every theorem instead of never.
    for bad in (0, -5):
        with pytest.raises(ValueError, match="batch must be at least 1"):
            import_corpus(session, database, name="Propositional", batch=bad)

    assert session.scalars(select(FormalSystem.id)).all() == []


def test_nothing_is_committed_unless_a_batch_size_asks_for_it(session, database):
    # The transaction is the caller's: `import_corpus` is public API, so
    # committing (and expunging) a session it was merely handed would take
    # unrelated work with it. Passing `batch` is what hands that over.
    import_corpus(session, database, name="Propositional")
    assert session.in_transaction()

    session.rollback()
    assert session.scalars(select(Proof.name)).all() == []


def test_an_unstorable_theorem_costs_that_theorem_not_the_run(
    session, database, monkeypatch
):
    # A whole-corpus pass is 23 minutes and commits as it goes, so a raise on one
    # proof must not replace the report with a traceback. The savepoint is what
    # keeps the rest of the batch: a plain rollback would discard it too.
    real = metamath_store.store_proof_lines

    def explode(session_, proof, *args, **kwargs):
        if proof.name == "a1i":
            raise RuntimeError("no room at the inn")
        return real(session_, proof, *args, **kwargs)

    monkeypatch.setattr(metamath_store, "store_proof_lines", explode)
    report = import_corpus(session, database, name="Propositional")

    assert (report.checked, report.verified, report.failed) == (4, 3, 1)
    assert report.failures == [("a1i", "no room at the inn")]
    # The counters describe what is *stored*, so the failed proof is in neither
    # the tallies nor the tables — while its neighbours in the batch survive.
    # Ordered by the corpus's own position: the assertion is about *which*
    # proofs were stored, and an unordered select has no order to rely on.
    assert session.scalars(
        select(Proof.name).order_by(Proof.position)
    ).all() == ["mp2", "2a1i", "a2i"]
    assert report.lines == len(session.scalars(select(ProofLineRow)).all())


def test_a_proof_citing_an_entry_that_did_not_store_keeps_the_flag_down(
    session, database, monkeypatch
):
    # `citations_stored` is a *claim* that every citation's resolution is on the
    # line. The walk promotes into the in-memory system before it stores, so a
    # library row that fails to write leaves a proof that checked fine citing a
    # label with no entry behind it — and recording null there would read as
    # "this line cited a rule" and drop the dependency, where the label path
    # still reports it as unresolved. Only `a1i` cites `ax-1`, so the rest of the
    # corpus is the control.
    real = metamath_store.store_theorem

    def refuse(session_, system, spec, *args, **kwargs):
        if spec.label == "ax-1":
            raise RuntimeError("no room at the inn")
        return real(session_, system, spec, *args, **kwargs)

    monkeypatch.setattr(metamath_store, "store_theorem", refuse)
    import_corpus(session, database, name="Propositional")

    flags = dict(session.execute(select(Proof.name, Proof.citations_stored)).all())
    assert flags["a1i"] is False
    assert all(flags[name] is True for name in ("mp2", "2a1i", "a2i"))
    # And nothing was half-written: the flag being down means the columns it
    # speaks for were left alone.
    assert all(
        line.theorem_id is None
        for line in session.scalars(
            select(ProofLineRow).join(Proof).where(Proof.name == "a1i")
        )
    )


def _lines(session: Session, proof: str) -> list[ProofLineRow]:
    return list(
        session.scalars(
            select(ProofLineRow)
            .join(Proof)
            .where(Proof.name == proof)
            .order_by(ProofLineRow.position)
        )
    )


# ---------------------------------------------------------------------------
# The library, and re-checking from it
# ---------------------------------------------------------------------------
def test_the_library_is_stored_and_says_which_entries_are_primitive(session, imported):
    # Both kinds land in one table (app/db/promoted_theorems.py), so the split
    # that lets an imported system say what it *assumes* is a column rather than
    # a namespace. The fragment has three logical `$a` and four `$p`.
    rows = list(
        session.scalars(select(PromotedTheoremRow).order_by(PromotedTheoremRow.position))
    )
    assert [r.label for r in rows] == ["ax-mp", "ax-1", "ax-2", "mp2", "a1i", "2a1i", "a2i"]
    assert [r.label for r in rows if r.primitive] == ["ax-mp", "ax-1", "ax-2"]
    assert (imported.theorems, imported.primitives) == (7, 3)

    # `ax-mp` is the shape everything else is checked against: two premises, a
    # bare metavariable conclusion, three metavariables typed by the grammar.
    ax_mp = next(r for r in rows if r.label == "ax-mp")
    assert ax_mp.statement == "ps"
    assert [p.statement for p in ax_mp.premises] == ["ph", "( ph -> ps )"]
    assert {b.var: b.symbol.name for b in ax_mp.bindings} == {"ph": "wff", "ps": "wff"}


def test_an_imported_theorem_re_checks_from_its_rows_alone(session, imported):
    """P4's measure: rebuild the system from rows, resolve what a proof cites out
    of the stored library, and get the verdict the import recorded — with the
    ``.mm`` file gone and no statement parsed.

    Before the library was stored this could not run at all: the system rebuilt
    from rows had no `ax-mp` to resolve, so every imported proof failed on its
    first citation.
    """
    system = session.get(FormalSystem, imported.system_id)
    spec = system_to_spec(system)
    built = build_spec(spec)["system"]
    context = copy(built.context)
    context.variables.update(built.build_context.variables)
    library = LibraryChain.of(imported.system_id, library_digest(spec))

    for name in IMPORTED:
        proof_row = session.scalar(select(Proof).where(Proof.name == name))
        root = EngineProof(formal_system=built)

        assert proof_row.theorem_id is not None, f"{name} was not linked to its theorem"

        def resolve(references, _built=built, _ctx=context, _lib=library, _row=proof_row):
            # `hypotheses_of` also brings the `$e` hypotheses this proof proves
            # under, reachable only through the theorem it establishes.
            pending = read_library(
                session, _lib, cited_labels(references),
                hypotheses_of=_row.theorem_id,
            )

            def promote(graph, _p=pending, _b=_built, _c=_ctx):
                for theorem in _p.promote(_b, _c, graph).values():
                    _b.promote(theorem)

            return PendingCitations(pending.term_ids, promote)

        checked = load_proof_for_check(
            session, proof_row.id, built, context, proof=root,
            resolve_citations=resolve,
        )
        assert checked is not None, f"{name} stored no lines"
        assert checked.valid is True, [
            (line.display, line.invalid_message) for line in checked.proof_lines
        ]
        assert checked.valid == proof_row.valid


def test_a_re_check_sweeps_the_term_graph_once(session, imported):
    """A proof's own lines and the theorems it cites are *one* closure query.

    Two was the natural shape — the lines are loaded, then what they cite is
    resolved — and it cost a second recursive walk of `term_children` for one
    check. It is avoidable because a citation is `proof_lines.reference`, a plain
    column: what a proof cites is settled before any term is built, so both sets
    of roots are known in time to be swept together. They overlap heavily, since
    a lemma's statement is a line of the proof citing it, interned to one row.

    Pinned by counting, because nothing about the result changes if it regresses
    — the same terms arrive either way, just in two round trips instead of one,
    which no assertion on the verdict could see.
    """
    system = session.get(FormalSystem, imported.system_id)
    spec = system_to_spec(system)
    built = build_spec(spec)["system"]
    context = copy(built.context)
    context.variables.update(built.build_context.variables)
    library = LibraryChain.of(imported.system_id, library_digest(spec))

    # `a2i` cites `ax-2` and `ax-mp` and proves under a hypothesis of its own, so
    # it exercises both halves of what a citation can resolve to.
    proof_row = session.scalar(select(Proof).where(Proof.name == "a2i"))
    sweeps: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, ctx, many):  # noqa: ANN001, ANN202
        if "reachable_terms" in statement:
            sweeps.append(statement)

    def resolve(references):
        pending = read_library(
            session, library, cited_labels(references),
            hypotheses_of=proof_row.theorem_id,
        )

        def promote(graph):
            for theorem in pending.promote(built, context, graph).values():
                built.promote(theorem)

        return PendingCitations(pending.term_ids, promote)

    checked = load_proof_for_check(
        session, proof_row.id, built, context,
        proof=EngineProof(formal_system=built), resolve_citations=resolve,
    )
    assert checked is not None and checked.valid is True
    assert len(sweeps) == 1, f"{len(sweeps)} term sweeps for one re-check"


def test_a_stored_theorem_carries_the_term_its_statement_composed_to(session, imported):
    # The cache half (P3's contract, applied to the library): a theorem whose
    # digest still matches is promoted with no parse. Only a *compound* statement
    # composes to a term — `ax-mp` concludes the bare metavariable `ps`, which
    # has no structure to compose and correctly stores none.
    rows = {r.label: r for r in session.scalars(select(PromotedTheoremRow))}
    assert rows["ax-1"].statement_term_id is not None
    assert rows["ax-mp"].statement_term_id is None
    assert all(r.schema_digest is not None for r in rows.values())

    # A grammar edit moves the digest, so the terms stop being read and the
    # statements are composed again — the same inert-not-wrong contract the rule
    # schemas have.
    spec = system_to_spec(session.get(FormalSystem, imported.system_id))
    moved = system_to_spec(session.get(FormalSystem, imported.system_id))
    moved.productions[0].name = "renamed"
    assert library_digest(spec) != library_digest(moved)


def test_a_theorem_whose_digest_moved_is_promoted_by_parsing_instead(session, imported):
    # The cache is a cache: strip the digests and everything still re-checks,
    # having composed the statements again. Same contract as the rule schema
    # terms — a miss costs a parse and never a difference.
    session.execute(sa_update(PromotedTheoremRow).values(schema_digest=None))
    session.commit()

    system = session.get(FormalSystem, imported.system_id)
    spec = system_to_spec(system)
    built = build_spec(spec)["system"]
    context = copy(built.context)
    context.variables.update(built.build_context.variables)

    loaded = load_theorems(
        session, LibraryChain.of(imported.system_id, library_digest(spec)),
        ["ax-1", "ax-mp"], built, context,
    )
    assert set(loaded) == {"ax-1", "ax-mp"}
    # `ax-1`'s conclusion is compound, so composing it is what the cache saved;
    # the parse must reach the same nested term rather than a flat projection.
    assert loaded["ax-1"].deduction.schema_term is not None


def test_a_cited_label_with_no_theorem_row_is_simply_absent(session, imported):
    # `cited_labels` over-collects on purpose — a citation may name a rule, a
    # definition, or a line of a cited proof — so the loader must be indifferent
    # to a label it holds nothing for rather than treating it as a miss to report.
    system = session.get(FormalSystem, imported.system_id)
    spec = system_to_spec(system)
    built = build_spec(spec)["system"]
    context = copy(built.context)
    context.variables.update(built.build_context.variables)

    loaded = load_theorems(
        session, LibraryChain.of(imported.system_id, library_digest(spec)),
        ["ax-1", "no-such-label", "ax-mp, 1, 2"], built, context,
    )
    assert set(loaded) == {"ax-1"}


def test_a_degenerate_ask_reads_no_library_at_all(session, imported):
    """Neither "no labels" nor "no owner" may widen to the whole library.

    `read_theorems` asks for both in one statement — an expanding `IN` for the
    labels and a bound `owner` that is `NULL` when there is none — precisely so
    that neither has to be a separate query. Both degenerate cases must therefore
    render *false* rather than true. Get it wrong and nothing is incorrect (the
    caller filters by what it asked for either way), which is what makes this
    worth pinning: it would show up only as every verify scanning 49,000 rows.
    """
    system_id = imported.system_id
    total = session.scalar(
        select(func.count()).select_from(PromotedTheoremRow)
        .where(PromotedTheoremRow.system_id == system_id)
    )
    assert total > 1, "the fixture must have a library to over-read"

    # No labels and no owner: nothing is reachable.
    assert read_theorems(session, [system_id], []) == []

    # Labels but no owner: the `owner` half must not match a row.
    assert [t.label for t in read_theorems(session, [system_id], ["ax-1"])] == ["ax-1"]

    # An owner but no labels: the `labels` half must not match a row.
    mp2 = session.scalar(
        select(PromotedTheoremRow).where(PromotedTheoremRow.label == "mp2")
    )
    assert [t.label for t in read_theorems(session, [system_id], [], mp2.id)] == ["mp2"]


def test_a_hypothesis_is_reachable_only_through_the_theorem_that_owns_it(
    session, imported
):
    """A `$e` promoted for anyone is a bare `|- ph` that proves anything.

    The walk keeps that from happening in *time* — promoted for one check, then
    withdrawn. Storage has to keep it from happening in *reach*, which is why a
    hypothesis is a column on its theorem rather than a library entry.
    """
    system = session.get(FormalSystem, imported.system_id)
    spec = system_to_spec(system)
    built = build_spec(spec)["system"]
    context = copy(built.context)
    context.variables.update(built.build_context.variables)

    # `mp2` proves under three hypotheses, labelled `mp2.1`…`mp2.3`.
    mp2 = session.scalar(
        select(PromotedTheoremRow).where(PromotedTheoremRow.label == "mp2")
    )
    assert [p.label for p in mp2.premises] == ["mp2.1", "mp2.2", "mp2.3"]

    # Cited as a theorem, they resolve to nothing: no library row bears the name.
    assert load_theorems(
        session, LibraryChain.of(imported.system_id, library_digest(spec)),
        ["mp2.1", "mp2.2"], built, context,
    ) == {}

    # Reached through their owner, they are exactly what the walk promoted.
    hypotheses = load_theorems(
        session, LibraryChain.of(imported.system_id, library_digest(spec)), [],
        built, context, hypotheses_of=mp2.id,
    )
    assert set(hypotheses) == {"mp2.1", "mp2.2", "mp2.3"}
    assert all(h.antecedents == () for h in hypotheses.values())
    # The owner itself is read for its hypotheses, not made citable by it.
    assert "mp2" not in hypotheses


# ---------------------------------------------------------------------------
# Write batching: the round trips an import makes, not just the rows it writes
# ---------------------------------------------------------------------------


def _statements(engine) -> list[tuple[str, int]]:
    """Every statement this engine issues, as (shape, rows carried).

    Counted rather than timed. "One statement per line" versus "one statement for
    the lines" is exact, and a wall-clock assertion would be flaky about a fact
    that is not.
    """
    seen: list[tuple[str, int]] = []

    @event.listens_for(engine, "after_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        head = " ".join(statement.split())
        verb = head.split(" ", 1)[0].upper()
        match = re.search(r"(?:INTO|FROM|UPDATE)\s+([a-z_]+)", head, re.I)
        rows = len(parameters) if executemany and parameters is not None else 1
        seen.append((f"{verb} {match.group(1) if match else ''}".strip(), rows))

    return seen


def _count(seen: list[tuple[str, int]], shape: str) -> tuple[int, int]:
    """How many statements of this shape were issued, and how many rows they carried."""
    matching = [rows for kind, rows in seen if kind == shape]
    return len(matching), sum(matching)


def test_a_proof_s_lines_are_written_in_one_statement(database):
    """A line per statement is a round trip per line, and a remote database is
    latency rather than work.

    The lines used to flush one at a time because interning a formula issues a
    `SELECT`, that `SELECT` autoflushed, and it ran *between* the rows being
    created. Interning every formula first is what lets them go together.
    """
    engine = create_engine(throwaway_database(_TABLES))
    # After the schema exists, so the counter sees the import's statements and
    # not the DDL.
    seen = _statements(engine)
    with Session(engine) as session:
        report = import_corpus(session, database, name="P")
        session.commit()

    statements, rows = _count(seen, "INSERT proof_lines")
    assert rows == report.lines
    # One per *proof*, not one per line — four proofs in the fragment.
    assert statements == len(IMPORTED)


def test_writing_a_proof_never_reads_back_the_edges_it_is_about_to_write(database):
    # A freshly created row's antecedent collection is empty by construction, but
    # assigning to it on a *persistent* row makes SQLAlchemy load the collection
    # it is about to replace. That was a wasted round trip per line.
    engine = create_engine(throwaway_database(_TABLES))
    # After the schema exists, so the counter sees the import's statements and
    # not the DDL.
    seen = _statements(engine)
    with Session(engine) as session:
        import_corpus(session, database, name="P")
        session.commit()

    assert _count(seen, "SELECT proof_line_antecedents") == (0, 0)


def test_the_deferred_proof_writes_do_not_grow_with_the_corpus(database):
    # Two writes to `proofs` happen after the walk rather than during it, for
    # different reasons — the theorem link because a proof cannot point at a
    # theorem promoted after it, publication because a batched run must not make a
    # partial corpus visible. Neither has to be issued a theorem at a time, and
    # this is what says so: a constant number of statements, whatever the corpus.
    engine = create_engine(throwaway_database(_TABLES))
    # After the schema exists, so the counter sees the import's statements and
    # not the DDL.
    seen = _statements(engine)
    with Session(engine) as session:
        import_corpus(session, database, name="P")
        session.commit()

    statements, rows = _count(seen, "UPDATE proofs")
    assert statements == 2
    # The link carries a parameter set per `$p`; publication is one statement over
    # the lot, so the executed-row count is dominated by the former either way.
    assert rows >= len(IMPORTED)


def test_a_comments_cross_reference_lands_beside_the_proof(session):
    # The whole path in one go: parse, extract, store, and a span that still cuts
    # its own markup out of the prose it was stored with. Its own source rather
    # than the shared fragment, which other tests here match literally.
    documented = PROPOSITIONAL.replace(
        "ax-1 $a", "$( Axiom _Simp_, used by ~ a1i . $)\nax-1 $a", 1
    )
    import_corpus(session, parse(documented), name="Documented")

    (row,) = session.scalars(
        select(LabelDescriptionRow).where(LabelDescriptionRow.label == "ax-1")
    ).all()

    (reference,) = row.references
    assert reference.target == "a1i"
    assert row.text[reference.start_offset : reference.end_offset] == "~ a1i"


def test_an_avoids_declaration_is_stored_against_the_label_it_names(session):
    # `$j usage 'X' avoids 'Y';` — a result about the *proof*, and the only place
    # it is written down: `ax-2` is nowhere in `a1i`'s citations, that being the
    # point of declaring it.
    declaring = PROPOSITIONAL + "$( $j usage 'a1i' avoids 'ax-2'; $)\n"
    report = import_corpus(session, parse(declaring), name="Declaring")

    assert report.claims == 1
    (row,) = session.scalars(select(LabelClaimRow)).all()
    assert (row.subject, row.kind, row.object) == ("a1i", "usage_avoids", "ax-2")


def test_a_directive_with_no_preposition_claims_about_each_argument(session):
    # `primitive 'wn' 'wi';` says the same thing about both and names no object,
    # which is the second of the two shapes a `$j` directive takes.
    declaring = PROPOSITIONAL + "$( $j primitive 'a1i' 'mp2'; $)\n"
    report = import_corpus(session, parse(declaring), name="Primitive")

    assert report.claims == 2
    rows = session.scalars(select(LabelClaimRow).order_by(LabelClaimRow.subject)).all()
    assert [(r.subject, r.kind, r.object) for r in rows] == [
        ("a1i", "primitive", None),
        ("mp2", "primitive", None),
    ]


def test_a_restatement_is_stored_as_the_relation_the_file_writes(session):
    # The 29 that pair an axiom with the theorem deriving it — `ax-sep` restates
    # `axsep` — and the reason the kind keeps its preposition.
    declaring = PROPOSITIONAL + "$( $j restatement 'a1i' of 'mp2'; $)\n"
    import_corpus(session, parse(declaring), name="Restating")

    (row,) = session.scalars(select(LabelClaimRow)).all()
    assert (row.subject, row.kind, row.object) == ("a1i", "restatement_of", "mp2")


def test_a_directive_whose_values_are_not_names_is_skipped(session):
    # `varcolorcode` is a colour table for Metamath's own site, and `garden_path`
    # is written in bare math tokens. Neither claims anything about a label.
    declaring = (
        PROPOSITIONAL
        + "$( $j varcolorcode 'wff' as '0000FF'; garden_path ( A => ( ph ; $)\n"
    )
    report = import_corpus(session, parse(declaring), name="Presentation")

    assert report.claims == 0


def test_a_file_declaring_none_stores_none(session, imported):
    # The mechanism is optional and most `.mm` files carry no `$j` at all, so an
    # import of one behaves exactly as it did before this existed.
    assert imported.claims == 0
    assert session.scalars(select(LabelClaimRow)).all() == []


def test_a_declaration_about_a_label_past_the_horizon_is_not_stored(session):
    # A `limit` imports a *prefix*, and a directive about a statement past the cut
    # is about something these rows do not contain.
    declaring = PROPOSITIONAL + "$( $j usage 'a2i' avoids 'ax-1'; $)\n"
    report = import_corpus(session, parse(declaring), limit=2, name="Prefix")

    assert report.claims == 0


def test_a_claim_about_an_object_past_the_horizon_is_still_stored(session):
    # Only the *subject* is filtered. An object is frequently not an assertion at
    # all — `primitive 'wn'` names a syntax constructor — and what the claim says
    # about its subject is true whether or not the object came along.
    declaring = PROPOSITIONAL + "$( $j usage 'mp2' avoids 'a2i'; $)\n"
    report = import_corpus(session, parse(declaring), limit=1, name="Object")

    assert report.claims == 1


def test_a_declaration_naming_a_label_the_file_lacks_is_ignored(session):
    # A `$j` may name anything; a directive about a label this database does not
    # declare says nothing about this import, and `position` would raise on it.
    declaring = PROPOSITIONAL + "$( $j usage 'nosuchlabel' avoids 'ax-1'; $)\n"
    report = import_corpus(session, parse(declaring), name="Stray")

    assert report.claims == 0


def test_a_claim_about_a_typecode_rather_than_a_label_is_not_stored(session):
    """`syntax 'wff';` and `bound 'setvar';` name sorts, and a subject is a label.

    Five of set.mm's 3,364 claims are these, and nothing is lost by excluding
    them: they restate what the built system already models structurally, and
    `tests/test_setmm_against_its_markup.py` checks those declarations against
    what the grammar derives. Pinned so the exclusion stays deliberate rather
    than becoming an accident of the horizon filter (found in review).
    """
    declaring = PROPOSITIONAL + "$( $j syntax 'wff'; bound 'setvar'; $)\n"
    report = import_corpus(session, parse(declaring), name="Sorts")

    assert report.claims == 0


# ---------------------------------------------------------------------------
# Hypotheses are documented labels
# ---------------------------------------------------------------------------

DOCUMENTED_HYPOTHESES = PROPOSITIONAL.replace(
    "${\n  min $e |- ph $.",
    "${\n  $( Minor premise for modus ponens. $)\n  min $e |- ph $.",
).replace(
    "  maj $e |- ( ph -> ps ) $.",
    "  $( Major premise for modus ponens. $)\n  maj $e |- ( ph -> ps ) $.",
)


def test_a_documented_hypothesis_is_stored_like_any_other_label(session):
    # `label_descriptions` is keyed by label and a hypothesis has one, so this
    # needs no new table — what it needed was the parser keeping the comment.
    import_corpus(session, parse(DOCUMENTED_HYPOTHESES), name="Hypotheses")

    rows = {
        row.label: row
        for row in session.scalars(select(LabelDescriptionRow))
    }
    assert rows["min"].text == "Minor premise for modus ponens."
    assert rows["maj"].text == "Major premise for modus ponens."


def test_a_hypothesis_declared_past_the_horizon_is_not_described(session):
    """The cut is where the hypothesis was *declared*, not who uses it.

    Bounding by use instead looks equivalent and is not: a floating hypothesis
    that is only ever optional can still be cited by a proof as a dummy variable,
    and filing by first user puts a file-scope `$f` on whichever layer first
    mentions it (found in review).
    """
    unused = PROPOSITIONAL + (
        "$v unusedvar $.\n$( Declared after the last theorem. $)\n"
        "wunused $f wff unusedvar $.\n"
    )
    import_corpus(session, parse(unused), name="Unused")

    described = {row.label for row in session.scalars(select(LabelDescriptionRow))}
    assert "wunused" not in described


def test_a_hypothesis_no_assertion_uses_is_still_described(session):
    # Declared inside the horizon and mandatory for nothing. It is a label this
    # system declares, so its prose belongs to it — bounding by use would drop it.
    unused = PROPOSITIONAL.replace(
        "wn $a wff -. ph $.",
        "$( A variable nothing needs. $)\nwspare $f wff ps $.\nwn $a wff -. ph $.",
    )
    import_corpus(session, parse(unused), name="Spare")

    described = {row.label for row in session.scalars(select(LabelDescriptionRow))}
    assert "wspare" in described


def test_a_hypothesis_description_is_bounded_by_the_horizon(session):
    """A hypothesis reaches this system through the assertions that use it.

    `a2i.1` belongs to `a2i`, the last theorem in the fixture, so a one-theorem
    prefix does not contain it. `min` and `maj` belong to `ax-mp`, which is
    declared *before* the first theorem and so is inside any prefix — which is
    what the first cut of this test got wrong about its own fixture.
    """
    documented = DOCUMENTED_HYPOTHESES.replace(
        "  a2i.1 $e |- ( ph -> ( ps -> ch ) ) $.",
        "  $( The premise of a2i. $)\n  a2i.1 $e |- ( ph -> ( ps -> ch ) ) $.",
    )
    import_corpus(session, parse(documented), limit=1, name="Prefix")

    described = {row.label for row in session.scalars(select(LabelDescriptionRow))}
    assert "a2i.1" not in described
    # And the ones belonging to a statement inside the prefix are kept.
    assert {"min", "maj"} <= described
