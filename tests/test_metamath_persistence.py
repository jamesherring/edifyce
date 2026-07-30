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

from copy import copy

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, func, select
from sqlalchemy import distinct as distinct_
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db import Base, cited_labels, load_proof_for_check, load_term, load_theorems
from app.db.promoted_theorems_mapping import load_hypotheses
from website.logical.declarative import build_spec, library_digest
from website.logical.formal_system.proof import Proof as EngineProof
from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db import metamath_store
from app.db.metamath_store import import_corpus
from app.db.models import FormalSystem, Proof
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
        Proof, ProofLineRow, ProofLineAntecedentRow, TermRow, TermChildRow,
        # The citable library an import now writes alongside the proofs.
        PromotedTheoremRow, PromotedTheoremPremiseRow, PromotedTheoremBindingRow,
    )
]


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    with Session(engine) as session:
        yield session


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

    for row in _lines(session, "a2i"):
        formula = row.display.split(" [")[0]
        assert load_term(row.term, context).to_string() == formula


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


def test_an_import_is_ownerless_so_no_verify_can_overwrite_it(session, imported):
    # A stored system holds a grammar, definitions, axioms and rules — it has
    # nowhere to hold a *promoted theorem*, which is what the Metamath library is
    # made of (roadmap §3.2). So an imported proof cannot be re-checked from its
    # own rows, and the danger is a verify that tries: `_record_verdict` would
    # write `valid=False` and call `store_proof_lines`, whose first act is to drop
    # the imported structure.
    #
    # Ownerlessness is the guard. `POST /proofs/{id}/verify` writes back only for
    # `user is not None and proof.owner_id == user.id`, and reads at all only for
    # a published proof or its owner — neither of which an import produces.
    system = session.scalars(select(FormalSystem)).one()
    assert system.owner_id is None
    assert system.published_at is None
    assert all(p.owner_id is None for p in session.scalars(select(Proof)))
    assert all(p.published_at is None for p in session.scalars(select(Proof)))

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
    assert session.scalars(select(Proof.name)).all() == ["mp2", "2a1i", "a2i"]


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
    assert session.scalars(select(Proof.name)).all() == ["mp2", "a1i"]


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
    assert session.scalars(select(Proof.name)).all() == ["mp2", "2a1i", "a2i"]
    assert report.lines == len(session.scalars(select(ProofLineRow)).all())


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
    library = library_digest(spec)

    for name in IMPORTED:
        proof_row = session.scalar(select(Proof).where(Proof.name == name))
        root = EngineProof(formal_system=built)

        assert proof_row.theorem_id is not None, f"{name} was not linked to its theorem"

        def resolve(populated, _built=built, _ctx=context, _lib=library, _row=proof_row):
            labels = cited_labels(line.reference_string for line in populated.proof_lines)
            promoted = load_theorems(
                session, imported.system_id, labels, _built, _ctx, _lib
            )
            # A theorem proves under its own `$e` hypotheses, reachable only
            # through the theorem this proof establishes.
            promoted.update(load_hypotheses(session, _row.theorem_id, _built, _ctx))
            for theorem in promoted.values():
                _built.promote(theorem)

        checked = load_proof_for_check(
            session, proof_row.id, built, context, proof=root, before_check=resolve
        )
        assert checked is not None, f"{name} stored no lines"
        assert checked.valid is True, [
            (line.display, line.invalid_message) for line in checked.proof_lines
        ]
        assert checked.valid == proof_row.valid


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
        session, imported.system_id, ["ax-1", "ax-mp"], built, context,
        library_digest(spec),
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
        session, imported.system_id, ["ax-1", "no-such-label", "ax-mp, 1, 2"],
        built, context, library_digest(spec),
    )
    assert set(loaded) == {"ax-1"}


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
        session, imported.system_id, ["mp2.1", "mp2.2"], built, context,
        library_digest(spec),
    ) == {}

    # Reached through their owner, they are exactly what the walk promoted.
    hypotheses = load_hypotheses(session, mp2.id, built, context)
    assert set(hypotheses) == {"mp2.1", "mp2.2", "mp2.3"}
    assert all(h.antecedents == () for h in hypotheses.values())
