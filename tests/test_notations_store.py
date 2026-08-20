"""A system's named notations, stored and read back.

A grammar fixes how a term is *written*; a notation is how it may be *read*, and
a system may carry several at once. They persist as render-step rows so that a
reader — who has a database and no grammar — can show a proof in any of them
without rebuilding the system, which on a corpus-sized grammar is seconds.

The load-bearing test here is the last one: the storage-side fold and the
engine's own fold must agree, since they are the same operation over two shapes.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import TypeVar

import pytest

pytest.importorskip("regex")
pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.metamath_store import import_corpus
from app.db.models import FormalSystem
from app.db.notations_mapping import (
    load_notation,
    notation_names,
    render_stored,
    store_notation,
)
from app.db.proof_lines import ProofLineRow
from app.db.systems import (
    NotationPieceRow,
    NotationRulePieceRow,
    NotationRulePinRow,
    NotationRuleRow,
)
from app.db.terms_mapping import prefetch_terms
from tests.database import async_url, throwaway_database
from website.logical.declarative import build_system
from website.logical.metamath import build_spec, parse
from website.logical.metamath.definitions import statement_of
from website.logical.metamath.display import (
    applicable_rules,
    notation_constructors,
    projection_for,
    unicode_projection,
    with_rules,
)
from website.logical.metamath.typesetting import typesetting_of
from website.logical.rendering import Projection, Rule, render, total_projection

# A `.mm` carrying its own readable spellings, which is the case notations exist
# for: without somewhere to put a `$t` block, an imported corpus reads as ASCII
# for ever.
SOURCE = r"""
$( $t
  althtmldef "e." as ' &isin; ';
  althtmldef "->" as ' &rarr; ';
  althtmldef "RR" as '&#8477;';
  althtmldef "A." as '&forall;';
$)
$c |- wff class setvar ( ) -> e. A. RR $.
$v ph ps x A B $.
wph $f wff ph $.
wps $f wff ps $.
vx $f setvar x $.
cA $f class A $.
cB $f class B $.
cr $a class RR $.
cv $a class x $.
wi $a wff ( ph -> ps ) $.
wcel $a wff A e. B $.
wal $a wff A. x ph $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
id $p |- ( ph -> ( ps -> ph ) ) $= ( ax-1 ) ABC $.
"""


T = TypeVar("T")


@contextmanager
def database() -> Iterator[Session]:
    engine = create_engine(throwaway_database())
    try:
        with Session(engine) as session:
            yield session
    finally:
        # A context manager rather than a bare `Session`, so the engine behind it
        # is closed too. On SQLite that only tidied up; against a real database an
        # engine left open per test holds a connection until the run ends.
        engine.dispose()


def run(work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """``work`` against an async session, for the halves of this module that are.

    Storing a notation is synchronous because the one thing that derives one is an
    import; reading it is async, beside the API that does the reading. So a test
    covering both ends needs both, and the schema is built through the synchronous
    driver before the async one connects to the same database.
    """

    async def go() -> T:
        engine = create_async_engine(
            async_url(throwaway_database()), poolclass=NullPool
        )
        try:
            async with AsyncSession(engine) as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_an_import_stores_the_files_own_notation() -> None:
    # The motivating case. A `$t` block is the only machine-readable notation a
    # `.mm` has, and deriving it needs the file *and* the grammar it built — which
    # is why an import stores it rather than a reader deriving it.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        assert report.notation > 0
        rows = session.scalars(
            select(NotationPieceRow)
            .where(NotationPieceRow.constructor == "wcel")
            .order_by(NotationPieceRow.position)
        ).all()
        assert [(r.kind, r.text) for r in rows] == [
            ("slot", "A"), ("lit", " ∈ "), ("slot", "B")
        ]
        assert {r.notation for r in rows} == {"unicode"}


def test_a_database_with_no_typesetting_stores_none() -> None:
    # Optional, and silently so: a `.mm` written for checking rather than
    # publishing carries no `$t`, and that is not a failed import.
    with database() as session:
        report = import_corpus(session, parse(SOURCE.split("$)")[1]), name="t")
        session.commit()

        assert report.notation == 0
        assert session.scalars(select(NotationPieceRow)).all() == []


def test_each_map_a_block_declares_becomes_its_own_notation() -> None:
    # A `$t` block need not carry every map: `set.mm` declares all three over the
    # same tokens, and a file may declare only one. Each is independent, so a file
    # that declares only `latexdef` gets a `latex` reading and no `unicode` one.
    latex_only = SOURCE.replace("althtmldef", "latexdef")
    with database() as session:
        report = import_corpus(session, parse(latex_only), name="t")
        session.commit()

        assert report.notation > 0
        found = session.scalars(select(NotationPieceRow.notation).distinct()).all()
        assert list(found) == ["latex"]


def test_a_block_declaring_both_maps_stores_both_readings() -> None:
    # The set.mm case: one file, two readings of the same terms, neither costing
    # a second copy of a term.
    both = SOURCE.replace(
        """  althtmldef "e." as ' &isin; ';""",
        """  althtmldef "e." as ' &isin; ';\n  latexdef "e." as "\\in";""",
    )
    with database() as session:
        import_corpus(session, parse(both), name="t")
        session.commit()

        found = session.scalars(select(NotationPieceRow.notation).distinct()).all()
        assert sorted(found) == ["latex", "unicode"]


def test_a_typesetting_block_about_other_tokens_stores_none() -> None:
    # The same conclusion one step later, and the reason the guard is on the
    # derived projection and not only on the token map: a `$t` may declare plenty
    # of Unicode for tokens no production of *this* grammar uses, which re-spells
    # nothing just as surely.
    foreign = SOURCE.replace('"e."', '"NOTATOKEN"').replace('"->"', '"NORTHIS"')
    foreign = foreign.replace('"RR"', '"NORTHAT"').replace('"A."', '"NORTHEOTHER"')
    with database() as session:
        report = import_corpus(session, parse(foreign), name="t")
        session.commit()

        assert report.notation == 0
        assert session.scalars(select(NotationPieceRow)).all() == []


def test_storing_a_notation_replaces_the_one_before_it() -> None:
    # A notation is derived wholesale from a source that knows the whole grammar,
    # so a re-derivation dropping a constructor must drop its rows. Merging would
    # leave the old spelling behind and make the stored notation a history.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        store_notation(
            session,
            report.system_id,
            Projection(templates={"wcel": (("lit", "IN"),)}, name="unicode"),
        )
        session.commit()

        rows = session.scalars(select(NotationPieceRow)).all()
        assert {r.constructor for r in rows} == {"wcel"}


def test_two_notations_coexist() -> None:
    # The point of naming them: one checked term, read several ways, with no
    # second copy of the term and no re-parse.
    with database() as session:
        report = import_corpus(session, parse(SOURCE), name="t")
        store_notation(
            session,
            report.system_id,
            Projection(
                templates={"wcel": (("slot", "A"), ("lit", " \\in "), ("slot", "B"))},
                name="latex",
            ),
        )
        session.commit()

        found = session.scalars(select(NotationPieceRow.notation).distinct()).all()
        assert sorted(found) == ["latex", "unicode"]


def test_a_constructor_the_notation_does_not_name_renders_empty() -> None:
    # Why a *stored* notation is completed against the grammar
    # (`total_projection`): a reader has rows and no system, so a constructor the
    # notation skips has no source template to fall back to. The gap shows as a
    # hole rather than failing the page — but it is a hole, which is what makes
    # completing a derived notation part of storing it rather than a nicety.
    with database() as session:
        import_corpus(session, parse(SOURCE), name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        graph = prefetch_terms(session, [r.term_id for r in rows])
        partial = Projection(templates={"wcel": (("lit", "IN"),)}, name="partial")
        assert render_stored(graph, rows[0].term_id, partial) == ""


def test_the_stored_fold_agrees_with_the_engines_own() -> None:
    """The two folds must not drift.

    `rendering.render` walks rebuilt kernel terms; `render_stored` walks the rows,
    so that showing a proof costs a query rather than a system rebuild. They are
    the same operation over two shapes, and nothing but this checks that they stay
    the same answer.
    """
    parsed = parse(SOURCE)
    engine = build_system(build_spec(parsed, name="t"))
    typesetting = typesetting_of(parsed.comments)
    projection = total_projection(
        notation_constructors(engine.build_context, engine.definitions),
        unicode_projection(engine, typesetting),
    )

    with database() as session:
        import_corpus(session, parsed, name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        assert rows, "the fixture's proof should store at least one formula"
        graph = prefetch_terms(session, [r.term_id for r in rows])

        for row in rows:
            # The engine's answer, from the term the grammar rebuilds.
            term = statement_of(parsed.assertions["ax-1"], engine)
            assert render_stored(graph, row.term_id, projection) == render(
                term, projection
            )
        # And it is genuinely the projected spelling, not the source one.
        assert render_stored(graph, rows[0].term_id, projection) == (
            "( ph → ( ps → ph ) )"
        )


# A `.mm` that applies things generically, which is the shape a rule exists for:
# `( F ` A )` is one production whatever `F` is, so `sqrt` is an *operand* and no
# template for `cfv` or for `csqrt` says `\sqrt{A}`.
APPLICATION = r"""
$( $t
  latexdef "e." as "\in";
  latexdef "sqrt" as "\surd";
  latexdef "RR" as "\mathbb{R}";
$)
$c |- wff class ( ) ` e. sqrt RR $.
$v A B F $.
cA $f class A $.
cB $f class B $.
cF $f class F $.
csqrt $a class sqrt $.
cr $a class RR $.
cfv $a class ( F ` A ) $.
wcel $a wff A e. B $.
ax-s $a |- ( sqrt ` A ) e. RR $.
th $p |- ( sqrt ` A ) e. RR $= ( ax-s ) AB $.
"""

SQRT = Rule(
    name="sqrt",
    constructor="cfv",
    pins={"F": "csqrt"},
    pieces=(("lit", r"\sqrt{"), ("slot", "A"), ("lit", "}")),
)


def test_a_rule_survives_the_round_trip() -> None:
    async def work(session: AsyncSession) -> None:
        report = await session.run_sync(
            lambda sync: import_corpus(sync, parse(APPLICATION), name="t")
        )
        await session.run_sync(
            lambda sync: store_notation(
                sync, report.system_id, Projection(name="latex", rules=(SQRT,))
            )
        )
        await session.commit()

        loaded = await load_notation(session, report.system_id, "latex")
        assert loaded is not None
        assert loaded.rules == (SQRT,)

    run(work)


def test_a_notation_of_rules_alone_is_still_a_notation() -> None:
    # Nothing requires both halves. A projection that re-spells no production by
    # name but matches a shape is a reading a system offers, so it must be listed
    # and must load.
    async def work(session: AsyncSession) -> None:
        report = await session.run_sync(
            lambda sync: import_corpus(sync, parse(APPLICATION), name="t")
        )
        await session.run_sync(
            lambda sync: store_notation(
                sync, report.system_id, Projection(name="shapes", rules=(SQRT,))
            )
        )
        await session.commit()

        assert "shapes" in await notation_names(session, report.system_id)
        assert await load_notation(session, report.system_id, "shapes") is not None

    run(work)


def test_storing_a_notation_replaces_its_rules_too() -> None:
    # Same reason the pieces are replaced: a notation is derived wholesale, so a
    # re-derivation that dropped a rule must drop its rows rather than leave the
    # old shape matching for ever.
    with database() as session:
        report = import_corpus(session, parse(APPLICATION), name="t")
        store_notation(
            session, report.system_id, Projection(name="latex", rules=(SQRT,))
        )
        session.commit()
        store_notation(session, report.system_id, Projection(name="latex"))
        session.commit()

        assert session.scalars(select(NotationRuleRow)).all() == []
        assert session.scalars(select(NotationRulePinRow)).all() == []
        assert session.scalars(select(NotationRulePieceRow)).all() == []


def test_the_stored_fold_applies_rules_as_the_engines_own_does() -> None:
    """The load-bearing agreement, extended to rules.

    A rule matches a *shape*, and the two folds walk different shapes — kernel
    terms one side, rows the other. Nothing but this checks that they agree about
    what matching means.
    """
    parsed = parse(APPLICATION)
    engine = build_system(build_spec(parsed, name="t"))
    constructors = notation_constructors(engine.build_context, engine.definitions)
    projection = total_projection(
        constructors,
        with_rules(
            projection_for(
                engine.build_context,
                dict(typesetting_of(parsed.comments).latex),
                name="latex",
                definitions=engine.definitions,
            ),
            applicable_rules([SQRT], constructors),
        ),
    )

    with database() as session:
        import_corpus(session, parsed, name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        assert rows, "the fixture's proof should store at least one formula"
        graph = prefetch_terms(session, [r.term_id for r in rows])
        term = statement_of(parsed.assertions["ax-s"], engine)

        for row in rows:
            assert render_stored(graph, row.term_id, projection) == render(
                term, projection
            )
        # And the rule genuinely fired: no `\surd` survives, which is the thing no
        # per-production template can arrange.
        assert render_stored(graph, rows[0].term_id, projection) == (
            r"\sqrt{A} \in \mathbb{R}"
        )


def test_an_import_stores_the_rules_it_is_given() -> None:
    # Passed in rather than reached for, like the overrides: a curated table is a
    # fact about one library, and this importer imports any `.mm`.
    with database() as session:
        import_corpus(session, parse(APPLICATION), name="t", rules={"latex": [SQRT]})
        session.commit()

        stored = session.scalars(select(NotationRuleRow)).all()
        assert [(r.notation, r.name, r.constructor) for r in stored] == [
            ("latex", "sqrt", "cfv")
        ]
        assert [(p.slot, p.constructor) for p in stored[0].pins] == [("F", "csqrt")]


def test_a_child_system_inherits_and_may_replace_a_rule() -> None:
    # Layered as the templates are, and by rule *name*: a child re-stating "sqrt"
    # wins, and anything it did not mention keeps the ancestor's shape.
    other = Rule(
        name="other",
        constructor="cfv",
        pins={"F": "cr"},
        pieces=(("lit", "R("), ("slot", "A"), ("lit", ")")),
    )
    replacement = Rule(
        name="sqrt",
        constructor="cfv",
        pins={"F": "csqrt"},
        pieces=(("lit", "ROOT "), ("slot", "A")),
    )

    def store(sync: Session) -> tuple[uuid.UUID, uuid.UUID]:
        report = import_corpus(sync, parse(APPLICATION), name="t")
        store_notation(
            sync, report.system_id, Projection(name="latex", rules=(SQRT, other))
        )
        child = FormalSystem(
            name="child", slug="child", inherits_from_id=report.system_id
        )
        sync.add(child)
        sync.flush()
        store_notation(
            sync, child.id, Projection(name="latex", rules=(replacement,))
        )
        return report.system_id, child.id

    async def work(session: AsyncSession) -> None:
        _parent, child_id = await session.run_sync(store)
        await session.commit()

        loaded = await load_notation(session, child_id, "latex")
        assert loaded is not None
        by_name = {rule.name: rule for rule in loaded.rules}
        assert by_name["sqrt"] == replacement
        assert by_name["other"] == other

    run(work)


# A slot label with a dot in it, which is not exotic: `set.mm` names class
# variables `.+`, `.x.`, `.0.`, and `seq M ( .+ , F )` is a production whose slot
# is one of them. A rule's steps are paths and a template's are labels, so reading
# every step as a path would print `.+` where the operand belongs.
DOTTED = r"""
$( $t
  latexdef "e." as "\in";
  latexdef "seq" as "\mathrm{seq}";
  latexdef "RR" as "\mathbb{R}";
$)
$c |- wff class ( ) , seq e. RR $.
$v A B .+ F $.
cA $f class A $.
cB $f class B $.
cpl $f class .+ $.
cF $f class F $.
cr $a class RR $.
cseq $a class seq A ( .+ , F ) $.
wcel $a wff A e. B $.
ax-q $a |- seq RR ( RR , RR ) e. RR $.
th $p |- seq RR ( RR , RR ) e. RR $= ( ax-q ) A $.
"""


def test_a_dotted_slot_label_is_a_label_and_not_a_path() -> None:
    parsed = parse(DOTTED)
    engine = build_system(build_spec(parsed, name="t"))
    constructors = notation_constructors(engine.build_context, engine.definitions)
    projection = total_projection(
        constructors,
        projection_for(
            engine.build_context,
            dict(typesetting_of(parsed.comments).latex),
            name="latex",
            definitions=engine.definitions,
        ),
    )

    with database() as session:
        import_corpus(session, parsed, name="t")
        session.commit()

        rows = session.scalars(
            select(ProofLineRow).where(ProofLineRow.term_id.is_not(None))
        ).all()
        graph = prefetch_terms(session, [r.term_id for r in rows])
        term = statement_of(parsed.assertions["ax-q"], engine)
        shown = render(term, projection)

        # The `.+` slot renders its operand, not its own name.
        assert ".+" not in shown, shown
        assert shown == (
            r"\mathrm{seq} \mathbb{R} ( \mathbb{R} , \mathbb{R} ) \in \mathbb{R}"
        )
        assert render_stored(graph, rows[0].term_id, projection) == shown


def test_a_rule_may_pin_and_render_a_dotted_slot_label() -> None:
    # The other half: within a rule the steps *are* paths, and a whole label that
    # is a child wins over splitting it — otherwise a rule could never address one
    # of `set.mm`'s dotted variables.
    parsed = parse(DOTTED)
    engine = build_system(build_spec(parsed, name="t"))
    rule = Rule(
        name="fold",
        constructor="cseq",
        pins={".+": "cr"},
        pieces=(("lit", "fold("), ("slot", "A"), ("lit", ", "), ("slot", "F"),
                ("lit", ")")),
    )
    constructors = notation_constructors(engine.build_context, engine.definitions)

    assert applicable_rules([rule], constructors) == [rule]
    term = statement_of(parsed.assertions["ax-q"], engine)
    assert render(term, Projection(name="x", rules=(rule,))) == "fold(RR, RR) e. RR"


def test_a_notation_can_be_stored_twice() -> None:
    # Re-deriving a notation is ordinary — an import re-run, an override edited —
    # and the rules are keyed by name, so the stale rows have to be gone before
    # their replacements are inserted rather than in the same flush.
    with database() as session:
        report = import_corpus(session, parse(APPLICATION), name="t")
        for _ in range(2):
            store_notation(
                session, report.system_id, Projection(name="latex", rules=(SQRT,))
            )
            session.commit()

        stored = session.scalars(select(NotationRuleRow)).all()
        assert [r.name for r in stored] == ["sqrt"]
