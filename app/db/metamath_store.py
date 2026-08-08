"""Persist a Metamath import: the system, its proofs, and their line graphs.

The import produced proof *text* and threw the parse away. Every run therefore
re-read `.mm` source, rebuilt the grammar, re-parsed 47,000 proofs and kept none
of it — while `terms` / `proof_lines` sat there describing exactly that structure
(roadmap §6.5). This module closes that: it drives
:func:`~website.logical.metamath.corpus.walk` and, for each theorem the kernel
checked, writes the same rows a verify through the API writes
(:func:`~app.db.proofs_mapping.store_proof_lines`) — one ``proof_lines`` row per
line, its justification as ``proof_line_antecedents`` edges, and its formula
interned into the system's shared ``terms`` DAG.

**One system row for the whole walk.** The walk's grammar grows as set.mm
declares notation, but a term row is keyed by *constructor name* and interned per
system, so terms built under an early grammar and a late one share rows correctly
as long as the stored system is the union of both — which
:func:`~website.logical.metamath.corpus.corpus_spec` is. That is the whole point:
the corpus lands in one term graph, so a subterm shared by two theorems is one
row and the theorem search indexes them together.

**The library is stored too**, so an imported proof can be re-checked from its
rows rather than only described by them. Every assertion the walk promotes — the
1,559 logical ``$a`` as much as the 47,546 ``$p`` — is written to
``promoted_theorems`` with the term its statement composed to, and a verify then
resolves the labels a proof cites and no more (roadmap §3.2; P4 of
docs/verification-from-rows.md). The walk is what hands them over, because
promotion parses a statement against the grammar *as of that statement's own
position* and only the walk holds it.

An import stays **ownerless** all the same. That was a guard while the library
was missing — the owner-scoped proof routes could not reach an import, so
``POST /proofs/{id}/verify`` could not re-check it, record ``valid=False`` and
drop the imported structure. It is now a statement about provenance rather than a
guard: a corpus belongs to no user. ``test_metamath_persistence`` pins it.

Ownerless but **published**, and the two have to be said separately because
ownerlessness is what once made them one. Publication is the only thing that
makes a system or a proof readable by someone who does not own it, so an import
that leaves it unset writes a corpus no reader can open — every layer a draft
nobody owns, every verified proof invisible to the listings and 404 on its own
route. The systems are published as they are created (`layered_systems` says
why it cannot wait); the proofs are published in one step once the run is
complete (`_publish` says why it must). The write-back guard is unaffected: it
reads ``owner_id``, which is still null.

Synchronous, like the rest of the mapping layer; an async caller reaches it
through ``AsyncSession.run_sync`` (see ``scripts/import_metamath.py``).
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import bindparam
from sqlalchemy import or_ as sa_or
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.avoidances_mapping import store_avoidances
from app.db.descriptions_mapping import store_descriptions
from app.db.models import FormalSystem, Proof
from app.db.promoted_theorems_mapping import store_theorem, theorem_digest
from app.db.notations_mapping import store_notation
from app.db.outline_mapping import store_outline
from app.db.proofs_mapping import store_proof_lines
from app.db.systems_mapping import spec_to_system
from website.logical.declarative import build_system, layered_spec, library_digest
from website.logical.metamath.corpus import (
    corpus_layers,
    corpus_specs,
    theorems,
    walk,
)
from website.logical.metamath.comments import read_comment
from website.logical.metamath.markup import by_keyword, markup_of
from website.logical.metamath.display import (
    applicable,
    applicable_rules,
    notation_constructors,
    projection_for,
    with_overrides,
    with_rules,
)
from website.logical.metamath.sections import outline
from website.logical.metamath.typesetting import as_text, typesetting_of
from website.logical.rendering import total_projection
from website.logical.metamath.importer import LibraryEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from app.db.systems import SymbolRow
    from website.logical.declarative import SystemSpec
    from website.logical.metamath.sections import Layer, Section
    from website.logical.metamath.comments import Description
    from website.logical.metamath.corpus import CheckedTheorem
    from website.logical.kernel.constructors import Piece
    from website.logical.metamath.parser import Database
    from website.logical.rendering import Rule

# Kept short deliberately: the report is a summary, and a run where thousands
# fail should be diagnosed from the corpus, not from a list carried in memory.
_FAILURES_KEPT = 20


@dataclass
class LayerReport:
    """One layer's share of a spined import (D4, §7.3).

    Counted rather than derived by a reader, because the only thing that knows
    which layer an assertion belongs to is the run: the boundary is a position in
    the file, and a stored row keeps the system it landed in and not the section
    that put it there.

    Every field here is something the split *moves*. What it does not move —
    notation, which is one declaration about the whole file and lives on the root
    — stays on :class:`ImportReport`, so a per-layer figure never implies a
    per-layer `$t`.
    """

    name: str
    system_id: uuid.UUID
    # Proofs filed here: the theorems whose own section falls in this layer,
    # verified and rejected alike, since both are stored.
    proofs: int = 0
    # Promoted entries, and how many of those are primitives *of this layer* — a
    # `$a` declared here rather than inherited.
    theorems: int = 0
    primitives: int = 0
    # Folders drawn from the section headers this layer covers, and labels it
    # documents.
    sections: int = 0
    described: int = 0


@dataclass
class ImportReport:
    """What one :func:`import_corpus` run stored.

    ``verified`` and ``rejected`` are both *stored*: a rejected proof is one the
    kernel checked and refused, and its structure is what says where it went
    wrong. ``failed`` never got that far — the stored proof did not decode, cited
    out of scope, reached a statement other than the declared one, or could not
    be written — so there is nothing to store for it.
    """

    # The system this import is *of*: the deepest layer, which is the one a
    # citation resolves from since its chain reaches everything above it. For an
    # unlayered import — the default — it is the only system there is, which is
    # what keeps every existing caller reading the same field.
    system_id: uuid.UUID
    # Every layer, root first, for a caller that wants the spine rather than the
    # leaf. One entry when no plan was given.
    system_ids: list[uuid.UUID] = field(default_factory=list)
    # The same spine, with each layer's share of what was stored. One entry for
    # an unlayered import, carrying the whole run — so a reader never has to ask
    # whether a plan was given before reading it.
    layers: list[LayerReport] = field(default_factory=list)
    checked: int = 0
    verified: int = 0
    rejected: int = 0
    failed: int = 0
    lines: int = 0
    formulas: int = 0
    # Constructors given a spelling across every stored notation, or 0 for a
    # database carrying no `$t` block to derive one from. A file declaring both
    # `althtmldef` and `latexdef` stores two notations and counts both.
    notation: int = 0
    # Labels this run stored a description for. Not the same as `checked`: a `$a`
    # is documented and never checked, and a comment that is only an attribution
    # still counts.
    described: int = 0
    # Folders made from the file's section headers, or 0 for a `.mm` that draws
    # no outline — which is most of them outside a published corpus.
    sections: int = 0
    # `$j usage … avoids …` edges: how many statements-a-proof-does-without this
    # run recorded. 3,107 for the whole of `set.mm`, and 0 for a file carrying no
    # `$j` at all, which is most of them.
    avoidances: int = 0
    # The citable library this run stored: every assertion the walk promoted,
    # and how many of those are primitives of the imported system.
    # ``theorems_failed`` is counted apart from ``failed`` because it is a
    # different thing going wrong — a theorem that would not *store* against a
    # proof that would not *check* — and adding them would make either number
    # unreadable.
    theorems: int = 0
    primitives: int = 0
    theorems_failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def import_corpus(
    session: Session,
    database: Database,
    limit: int | None = None,
    name: str = "Metamath",
    batch: int | None = None,
    progress: Callable[[ImportReport, CheckedTheorem], None] | None = None,
    overrides: Mapping[str, Mapping[str, tuple[Piece, ...]]] | None = None,
    rules: Mapping[str, Sequence[Rule]] | None = None,
    *,
    plan: Sequence[Layer] = (),
    owner: uuid.UUID | None = None,
    source: str | None = None,
) -> ImportReport:
    """Import ``database``'s first ``limit`` theorems into ``session``.

    The transaction is the caller's by default: nothing here commits, so an
    import composes with whatever else the caller is doing. Pass ``batch`` to
    hand that over — the run then commits and empties the identity map every that
    many theorems, which is what keeps a whole-corpus run's memory flat and its
    per-proof cost from growing with the transaction. ``progress`` is called
    after each theorem with the running report.

    ``overrides`` re-spells named productions in a named notation by hand, where
    the faithful re-spelling reads badly, and ``rules`` does the same for the
    spellings that span two productions — `( sqrt ` A )` as `\\sqrt{A}`, which is
    `cfv` applied to a constant and so reachable by no per-production template.
    Both are defaulted to nothing and passed in, like the binder table
    `corpus_spec` takes: a curated table is a fact about one library
    (`setmm.DISPLAY_OVERRIDES` and `setmm.DISPLAY_RULES` are `set.mm`'s), and this
    module imports any `.mm`. `display.applicable` and `display.applicable_rules`
    drop what this grammar cannot use, so handing over the wrong library's tables
    costs nothing rather than storing nonsense.

    ``plan`` splits the corpus into a **spine of systems** rather than one
    (D3, §7.2): `corpus_specs` says what each layer declares, `layered_systems`
    makes the rows, and each theorem is stored against the layer its own section
    falls in. A citation then resolves through the spine (§5.2), so the emitted
    proof sources do not change — which is the whole of "preserving references".
    Empty by default, which is exactly today's single system.

    ``owner`` hands the whole import — every layer and every proof — to one user,
    and is how a corpus stops being a shared library and becomes somebody's. It
    defaults to none, which is the case this module's docstring argues for and
    still the right one for a public corpus.

    Passing it **gives up the guard that ownerlessness is**. The owner-scoped
    routes can then reach the import, so `POST /proofs/{id}/verify` will re-check
    an imported proof and write the verdict back — and a verify that comes out
    `False` calls `store_proof_lines`, whose first act is to drop the imported
    structure. That is a deliberate trade (`scripts/restore_proofs.py` makes it on
    purpose, to reach the owner-only apply path), not an oversight, and it is why
    this is an argument rather than a default.

    Folders stay ownerless either way: an outline is the file's structure, and
    `get_system_folders` reads an *owned* folder as a user's private one — the
    system's own ownership already says who may see the tree.

    ``source`` names the `.mm` file, for the provenance sentence every layer
    carries (:func:`metamath_provenance`). It is the only thing about the origin
    a `Database` does not already hold, and an import is the one moment it is
    known — a reader has rows.
    """
    if batch is not None and batch < 1:
        raise ValueError(f"batch must be at least 1 if given, not {batch}.")

    # Raises for a `limit` below 1 (`corpus.theorems`) before anything is written.
    specs = corpus_specs(database, limit, name, plan=plan)
    # The whole corpus's grammar, which is what a notation is derived against —
    # rebuilt from the layers rather than by a second `corpus_spec`, since
    # `build_spec` is the expensive half of an import and `corpus_specs`
    # guarantees the two declare the same thing.
    spec = specs[0] if len(specs) == 1 else layered_spec(list(specs))
    # One instant for the whole run, so a corpus reads as published at a moment
    # rather than smeared across the twenty-odd minutes it takes to write — which
    # matters because `/proofs/public` orders by it.
    published = datetime.now(tz=UTC)
    spine = layered_systems(
        session,
        specs,
        metamath_provenance(source),
        published=published,
        owner=owner,
    )
    # The **deepest** layer is the system this import is "of": it is the one a
    # citation resolves from, since its chain reaches every layer above it, and
    # for an unlayered import it is the only one there is.
    system = spine[-1]
    report = ImportReport(
        system_id=system.id, system_ids=[layer.id for layer in spine]
    )
    # Read once, up front, and used twice: every documented label gets a row, and
    # a `$p`'s own title comes off the same parse. Metamath documents a statement
    # by the comment before it, so this is the whole of the association.
    descriptions = _descriptions_of(database, limit)
    # Before the walk, because a proof is filed as it is stored and the folder has
    # to exist by then. Bounded by the same horizon as everything else: a section
    # opening past the last walked theorem covers nothing this import contains.
    horizon = database.position(theorems(database, limit)[-1].label)
    layers = _Layers(
        session,
        database,
        spine,
        specs,
        report,
        sections=[s for s in outline(database) if s.at <= horizon],
        limit=limit,
        plan=plan,
    )
    library = layers.library
    report.sections = layers.sections

    for position, checked in enumerate(walk(database, limit, name, library.store)):
        # `layer`, not `owner`: this is which system of the spine the label
        # belongs to. The import's *owner* is a user, and is the argument above.
        layer = layers.index_of(checked.label)
        report.checked += 1
        if checked.proof is None:
            _record_failure(report, checked.label, checked.error or "")
        else:
            # Contained per theorem, so one unstorable proof costs that proof
            # rather than the run: a whole-corpus pass is 23 minutes, and a
            # traceback in place of the report would discard what it learnt about
            # the tens of thousands that stored fine. The savepoint is what keeps
            # the rest of the batch — a plain rollback would take it too.
            #
            # Counted after it closes, not inside: leaving the block is what
            # flushes the line rows, so a write that fails there must not already
            # have been booked as stored.
            try:
                with session.begin_nested():
                    stored = _store(
                        session,
                        layers.system_at(layer),
                        position,
                        checked,
                        descriptions,
                        layers.folder_for(layer, checked.label),
                        owner,
                    )
            except Exception as exc:  # noqa: BLE001 - reported, not fatal
                _record_failure(report, checked.label, str(exc))
            else:
                report.verified += stored.valid
                report.rejected += not stored.valid
                report.lines += stored.lines
                report.formulas += stored.formulas
                report.layers[layer].proofs += 1

        if progress is not None:
            progress(report, checked)
        if batch is not None and report.checked % batch == 0:
            _checkpoint(session)
            layers.rebind()

    _link_proofs_to_theorems(session, report.system_ids, library.ids)
    report.described = layers.describe(descriptions)
    report.avoidances = layers.avoid(_avoidances_of(database, limit))
    # On the **root**, not the leaf: a `$t` block is one declaration about the
    # whole file rather than something each layer has its own of, and a notation
    # is read root-first up the chain (`notations_mapping.notation_layers`), so
    # the root is the one place every layer of the spine can see it from. For an
    # unlayered import the root *is* the leaf, so nothing moves.
    report.notation = _store_notation(
        session, database, spec, report.system_ids[0], overrides or {}, rules or {}
    )
    # Last, so nothing is readable until everything above it has landed.
    _publish(session, report.system_ids, published)
    if batch is not None:
        session.commit()
    return report


def metamath_provenance(source: str | None = None) -> str:
    """The sentence an import records on every system it writes.

    Composed here rather than asked of the caller because it is the same fact
    every time: the rows came out of a `.mm` file, and a reader of one of the
    47,000 proofs has no other way to learn that. ``source`` is the file's name
    when the caller knows it — a corpus is identified by which database it is
    (`set.mm`, `iset.mm`), and the parse itself carries no name.
    """
    library = f"{source} library" if source else "library"
    return f"Imported from Metamath's {library}. See https://us.metamath.org/"


def layered_systems(
    session: Session,
    specs: Sequence[SystemSpec],
    provenance: str | None = None,
    *,
    published: datetime | None = None,
    owner: uuid.UUID | None = None,
) -> list[FormalSystem]:
    """One ``formal_systems`` row per layer, wired into a spine, root first.

    D3's store half (docs/system-relationships-roadmap.md §7.2). `corpus_specs`
    says what each layer declares; this is where those become rows a citation can
    resolve through — each layer inheriting the one before it, so a theorem
    proved in propositional calculus is citable in a first-order proof by §5.2
    and nothing else has to be said.

    **Every layer is published**, at creation rather than "on completion" as §7.2
    sketched. Completion is too late for the layers that are inherited from: a
    child's terms are interned against its own chain from the first theorem
    stored, so the chain has to exist and be readable before the walk reaches the
    child at all. And nothing is lost by publishing early, since an imported
    layer's grammar is fixed by the file the moment it is written — there is no
    draft period during which it could still move, which is the thing the flag
    protects against.

    The deepest layer used to be left a draft on the grounds that nothing
    inherits from it, which reads as a tidy consequence of §5.1 and is in
    practice how a corpus disappears: publication is also what makes a system
    *readable*, an import is ownerless, and so the layer holding the bulk of the
    corpus (7,325 of `set.mm`'s first 10,000 theorems) was visible to nobody at
    all. The same "its grammar cannot move" argument applies to it, so it is
    published on the same terms as the rest.

    Ownerless by default, like the single-system import and for the reason this
    module's docstring gives: nobody owns the corpus. ``owner`` overrides that for
    the whole spine — see `import_corpus` for what handing it over costs.

    ``provenance`` lands on **every** layer rather than on the leaf, because a
    theorem is filed in the layer its own section falls in: a proof of a
    propositional-calculus lemma sits on the root, and it came from the same
    file as one on the leaf.
    """
    published = published or datetime.now(tz=UTC)
    spine: list[FormalSystem] = []
    for spec in specs:
        system = spec_to_system(spec)
        system.provenance = provenance
        system.inherits_from_id = spine[-1].id if spine else None
        system.published_at = published
        system.owner_id = owner
        session.add(system)
        # Per layer rather than once at the end: the next layer needs this one's
        # id to inherit from, which only exists after a flush.
        session.flush()
        spine.append(system)
    return spine


def _descriptions_of(
    database: Database, limit: int | None
) -> dict[str, Description]:
    """Every documented label the imported system actually declares.

    Bounded by the same horizon the grammar is: ``corpus_spec`` builds the system
    from what is declared *before the last walked theorem*, so a label past that
    point is not part of this system and describing it would attach prose to
    something the rows do not contain. A `limit` is how a caller imports a prefix
    of a corpus, and this has to cut where that cuts.

    Read in file order (``iter_assertions``), because the horizon is a position
    rather than a set — the same way ``theorems`` finds it.
    """
    horizon = theorems(database, limit)[-1].label
    found: dict[str, Description] = {}
    for assertion in database.iter_assertions():
        if assertion.comment is not None:
            found[assertion.label] = read_comment(assertion.comment)
        if assertion.label == horizon:
            break
    return found


def _avoidances_of(
    database: Database, limit: int | None
) -> dict[str, tuple[str, ...]]:
    """Each label's ``$j usage … avoids …`` declaration, within the horizon.

    Bounded exactly as the descriptions are, and for the same reason: a `limit` is
    how a caller imports a *prefix* of a corpus, and a directive about a statement
    past that point is about something these rows do not contain.

    A `.mm` with no ``$j`` yields nothing, which is most of them — the whole
    mechanism is optional, so an import of a file that declares none behaves as it
    did before this existed.
    """
    horizon = database.position(theorems(database, limit)[-1].label)
    found: dict[str, tuple[str, ...]] = {}
    for directive in by_keyword(markup_of(database.comments), "usage"):
        label = directive.subject
        avoided = directive.clause("avoids")
        # A directive naming a label this database does not declare says nothing
        # about this import; one past the horizon is outside it. `position` would
        # raise on the first, so membership is asked before the cut.
        if label is None or not avoided or label not in database.assertions:
            continue
        if database.position(label) <= horizon:
            found[label] = avoided
    return found


def _store_notation(
    session: Session,
    database: Database,
    spec: SystemSpec,
    system_id: uuid.UUID,
    overrides: Mapping[str, Mapping[str, tuple[Piece, ...]]],
    rules: Mapping[str, Sequence[Rule]],
) -> int:
    """Store every notation this file describes, returning how many templates.

    The motivating case for notations, and the reason they are stored at all: a
    `.mm` file carries its own readable spellings in a `$t` block, and without
    somewhere to put them an imported corpus can only ever be read as ASCII.

    Derived here because deriving needs what only an import has — the file's `$t`
    and the grammar the file built. A reader has rows.

    ``overrides`` is the editorial layer, by notation name then constructor
    (`setmm.DISPLAY_OVERRIDES`): a token map re-spells a production's tokens and
    leaves its shape alone, which is right nearly everywhere and wrong in the few
    places a hand-written template fixes. ``rules`` is the same layer for what a
    per-production template cannot say at all (`setmm.DISPLAY_RULES`).
    """
    typesetting = typesetting_of(database.comments)
    if typesetting is None:
        return 0

    # A `$t` block need not declare a map this reads. `htmldef` is deliberately not
    # among them: it is HTML built for `set.mm`'s own site, and `as_text` of it
    # gives back roughly what `althtmldef` already does, so a third near-duplicate
    # notation would cost rows and say nothing new.
    declared = {
        "unicode": {
            token: as_text(value) for token, value in typesetting.unicode.items()
        },
        "latex": dict(typesetting.latex),
    }
    if not any(declared.values()):
        # Checked before the build, which is the expensive half: a block carrying
        # only `htmldef`, or nothing but site configuration, must not pay for a
        # whole-corpus compile to store nothing.
        return 0

    engine = build_system(spec)
    constructors = notation_constructors(engine.build_context, engine.definitions)
    stored = 0
    # `unicode` first, since it is the one a reader is offered by default. The two
    # are independent: a file declaring only `latexdef` gets only a `latex` one.
    for name, tokens in declared.items():
        if not tokens:
            continue
        spellings = with_rules(
            with_overrides(
                projection_for(
                    engine.build_context,
                    tokens,
                    name=name,
                    definitions=engine.definitions,
                ),
                applicable(overrides.get(name, {}), constructors),
            ),
            applicable_rules(rules.get(name, ()), constructors),
        )
        if not (spellings.templates or spellings.rules):
            # Declared, but about tokens this grammar's productions never use, and
            # with no rule applying either. Storing the completion anyway would
            # advertise a notation that re-spells nothing — every constructor at
            # its source template, which is what a reader already gets by asking
            # for no notation at all.
            continue
        stored += store_notation(
            session, system_id, total_projection(constructors, spellings)
        )
    return stored


def _link_proofs_to_theorems(
    session: Session, system_ids: Sequence[uuid.UUID], ids: dict[str, uuid.UUID]
) -> None:
    """Point each proof at the library entry it establishes.

    Done after the walk rather than during it, because the walk promotes a
    theorem *after* checking its proof — that ordering is what stops a theorem
    justifying itself, so the row a proof would point at does not exist yet when
    the proof is written. The name is the join: an import creates both from one
    Metamath ``$p``, so ``proofs.name`` is the theorem's label by construction.

    Scoped to the **whole spine**, not the deepest layer: a layered import files
    each proof against the layer its own section falls in, so a filter naming one
    system would link that layer's proofs and leave every other layer's
    ``theorem_id`` null (found in review). One system for an unlayered import,
    where this is the filter it always was.
    """
    if not ids or not system_ids:
        # `system_ids` too, and not only for symmetry: an empty `sa_or()` compiles
        # away entirely, so the scope would silently widen to every system rather
        # than narrow to none, which is how the `.in_()` this replaced degraded.
        return
    # One statement carrying every pair, rather than one statement per pair. The
    # *deferral* above is necessary; issuing it a theorem at a time was not, and
    # on a corpus that is one round trip per `$p` — the cost of a remote database
    # being latency rather than work.
    #
    # Against the **table** rather than the mapped class: handed an ORM entity
    # and a list of parameter sets, SQLAlchemy reads the call as a bulk update by
    # primary key and ignores the criteria above. The Core form keeps the WHERE
    # and still goes out as one `executemany`.
    #
    # The system scope is spelled as an `OR` of equalities rather than `IN`: an
    # `IN` compiles to an *expanding* parameter, which `executemany` cannot carry.
    # A spine is a handful of layers, so the two are the same query.
    table = Proof.__table__
    session.execute(
        sa_update(table)
        .where(
            sa_or(*(table.c.formal_system_id == sid for sid in system_ids)),
            table.c.name == bindparam("linked_name"),
        )
        .values(theorem_id=bindparam("linked_theorem_id")),
        [
            {"linked_name": name, "linked_theorem_id": theorem_id}
            for name, theorem_id in ids.items()
        ],
    )
    # A Core update leaves the identity map alone, so the synchronisation the
    # per-statement ORM version did for free is done here instead of lost. It
    # matters because an unbatched import never commits — the transaction is the
    # caller's — so a `Proof` already loaded would keep a stale `theorem_id`.
    for loaded in list(session.identity_map.values()):
        if isinstance(loaded, Proof):
            session.expire(loaded, ["theorem_id"])


def _publish(
    session: Session, system_ids: Sequence[uuid.UUID], published: datetime
) -> None:
    """Publish every proof of this import that verified — once, at the end.

    Publication is what makes a proof readable by someone who does not own it,
    and an import owns nothing, so without this a corpus stores tens of thousands
    of verified proofs nobody can open. It satisfies the same three conditions
    `_require_publishable` asks of the interactive path: the system is published
    (`layered_systems` publishes every layer), the proof verifies — a rejected one
    is left out by the filter here — and it has no reference links that could
    still be drafts, since a corpus cites through `promoted_theorems` rather than
    proof-to-proof.

    **At the end, and not as each proof is written**, which is where it started
    and is wrong for a batched run: `_checkpoint` commits every ``batch``
    theorems, so a publishing `_store` makes each batch world-visible as it lands
    — and an import that then dies leaves a *partial* corpus published, its proofs
    not yet pointed at the library entries they establish (`theorem_id` is set
    below the walk, not in it). Committed batches cannot be rolled back, so the
    only defence is not to publish until there is something whole to publish
    (found in review). Publication is one statement over rows that are already
    written, so deferring it costs a single round trip and buys atomicity: a run
    that fails anywhere leaves everything a draft, which is the safe state.

    Ordered after `_link_proofs_to_theorems` for the same reason — a proof becomes
    readable only once it is complete.

    Ownerlessness is untouched, and it is ownerlessness rather than this flag that
    stops `POST /proofs/{id}/verify` writing back over the imported structure.
    """
    if not system_ids:
        # The same guard `_link_proofs_to_theorems` makes and for the same reason:
        # an empty `sa_or()` compiles away, so the scope would silently widen from
        # none to *every* system — and the widening here publishes every valid
        # proof in the database rather than leaving some `theorem_id` null.
        # Unreachable while `corpus_specs` always yields a spec, which is exactly
        # the kind of invariant a guard is cheap insurance against.
        return
    table = Proof.__table__
    session.execute(
        sa_update(table)
        .where(
            sa_or(*(table.c.formal_system_id == sid for sid in system_ids)),
            table.c.valid.is_(True),
        )
        .values(published_at=published)
    )
    # Core again, so the identity map needs the same hand-synchronisation
    # `_link_proofs_to_theorems` explains.
    for loaded in list(session.identity_map.values()):
        if isinstance(loaded, Proof):
            session.expire(loaded, ["published_at"])


class _Layers:
    """The spine, and which of its systems each assertion belongs to.

    A layered import writes into several systems rather than one, and everything
    a read path reaches *by system id* has to follow the split — otherwise a
    proof filed against its own layer loses whatever stayed on the leaf. That is
    the **library** (a promoted theorem belongs to the layer that declared it),
    the **outline** (`GET /formal-systems/{id}/folders` is system-scoped, both
    for the folders and for the per-folder proof counts) and the
    **descriptions** (`load_description` looks a label up under one system and
    walks no chain). Each is partitioned here, by the same boundaries that
    decided which specs exist.

    So is the **digest** each layer's terms are guarded by — which for a layer of
    a chain is its *effective* digest, its ancestors' parts in front of its own,
    exactly as `LibraryChain` expects (§3.1). A single `library_digest(spec)`
    would be right for the root and wrong for everything below it.

    And so is the **symbol table** a promoted theorem's side conditions resolve a
    sort through, for the same reason and with real teeth: `wff_var` is declared
    where the `$f` for a `wff` is, which on `set.mm` is the propositional layer,
    while the theorems carrying a `$d` over a `wff` metavariable run all the way
    up. A layer that offered only its own symbols therefore refused **354 of
    set.mm's first 2,676 promotions** — see `_effective_symbols`.

    Notation is the exception, and stays on the root: see `import_corpus`.

    For an unlayered import this is one system and one library, and every lookup
    below is a constant.
    """

    def __init__(
        self,
        session: Session,
        database: Database,
        spine: Sequence[FormalSystem],
        specs: Sequence[SystemSpec],
        report: ImportReport,
        *,
        sections: Sequence[Section],
        limit: int | None,
        plan: Sequence[Layer],
    ) -> None:
        self._session = session
        self._database = database
        self._spine = list(spine)
        self._ids = [system.id for system in spine]
        opens = [at for _name, at in corpus_layers(database, limit, plan=plan)]
        self._of_label = _layer_of_label(database, opens)
        self._of_position = _layer_of_position(opens)
        # The per-layer breakdown (§7.3), counted as the run goes: only the run
        # knows which layer an assertion belongs to, since a stored row keeps the
        # system it landed in and not the section that put it there.
        report.layers = [
            LayerReport(name=system.name, system_id=system.id) for system in spine
        ]
        self._reports = report.layers
        # Each layer's *effective* digest: its own spec layered onto its
        # ancestors', which is what guards the terms it interns.
        digests = [
            library_digest(layered_spec(list(specs[: index + 1])))
            for index in range(len(specs))
        ]
        self._libraries = [
            _Library(session, report, share, digest)
            for share, digest in zip(self._reports, digests)
        ]
        # Bound **before** `self.library` is published, not after the folders are
        # written: a `_Library` is unusable until it holds a system, and
        # `_Routed.store` swallows what goes wrong into `theorems_failed`, so a
        # caller reaching one in that window would lose promotions silently
        # rather than raise (found in review).
        self._bind()
        # One entry point for the walk, which knows nothing about layers: it
        # hands over a promoted assertion and this routes it. Built **once** and
        # rebound in place — the walk is handed `library.store` before the first
        # checkpoint, so a rebind that replaced this object would leave the walk
        # writing through a detached one for the rest of the run (found in
        # review), and would drop the label→id map besides.
        self.library = _Routed(self._libraries, self._of_label)
        # Each layer's own share of the file's section headers, so a layer lists
        # the sections it covers and a proof's folder sits in the proof's own
        # system. A layer opens *at* a header, so its first section is the root
        # of its own tree.
        self._folders = [
            store_outline(
                session,
                system.id,
                [s for s in sections if self._of_position(s.at) == index],
            )
            for index, system in enumerate(spine)
        ]
        for share, stored in zip(self._reports, self._folders):
            share.sections = len(stored)

    def rebind(self) -> None:
        """Re-attach after a checkpoint emptied the identity map.

        In place, for both the spine and every library on it: the objects are
        already referenced elsewhere — `walk` holds the routed `store`, and the
        libraries hold the ids `_link_proofs_to_theorems` needs — so replacing
        them would orphan exactly what the run is accumulating.
        """
        self._spine = [
            self._session.get(FormalSystem, layer) for layer in self._ids
        ]
        self._bind()

    def _bind(self) -> None:
        # Hand each library its layer's system and that layer's *effective*
        # symbol table. Done in one place so a checkpoint cannot re-attach one
        # without the other.
        for library, system, symbols in zip(
            self._libraries, self._spine, _effective_symbols(self._spine)
        ):
            library.rebind(system, symbols)

    @property
    def sections(self) -> int:
        """Folders stored, across every layer."""
        return sum(len(stored) for stored in self._folders)

    def index_of(self, label: str) -> int:
        """Which layer ``label``'s own section puts it in.

        The index, not the system, because a caller needs both that layer's
        system *and* its share of the report and must not look the same label up
        twice to get them.
        """
        return self._of_label(label)

    def system_at(self, index: int) -> FormalSystem:
        return self._spine[index]

    def folder_for(self, index: int, label: str) -> uuid.UUID | None:
        """The folder ``label`` is filed in, within its own layer's outline."""
        return self._folders[index].folder_for(self._database.position(label))

    def describe(self, descriptions: Mapping[str, Description]) -> int:
        """Store each label's prose against the layer that declares it."""
        split: list[dict[str, Description]] = [{} for _ in self._ids]
        for label, description in descriptions.items():
            split[self._of_label(label)][label] = description
        total = 0
        for system_id, share, report in zip(self._ids, split, self._reports):
            report.described = store_descriptions(self._session, system_id, share)
            total += report.described
        return total

    def avoid(self, avoidances: Mapping[str, Sequence[str]]) -> int:
        """Store each `$j usage … avoids …` against the layer that declares it.

        Split by the same rule the prose is, and for the same reason: a read
        reaches these by system id, so a directive filed against the wrong layer
        is a directive nobody finds.
        """
        split: list[dict[str, Sequence[str]]] = [{} for _ in self._ids]
        for label, targets in avoidances.items():
            split[self._of_label(label)][label] = targets
        return sum(
            store_avoidances(self._session, system_id, share)
            for system_id, share in zip(self._ids, split)
        )


class _Routed:
    """A `_Library` face for the walk, dispatching on the assertion's layer.

    The walk is handed one ``store`` callable and must stay unaware that there is
    more than one system to store into — layering is a fact about how a corpus is
    filed, not about how it is checked, and `corpus.walk` checks it exactly as it
    did before (§7.2's "the emitted proof text does not change").
    """

    def __init__(
        self, libraries: Sequence[_Library], of_label: Callable[[str], int]
    ) -> None:
        self._libraries = list(libraries)
        self._of_label = of_label

    @property
    def ids(self) -> dict[str, uuid.UUID]:
        """Every label stored, across every layer, as `_link_proofs_to_theorems`
        wants it: a proof is linked to its theorem by id, and which layer either
        sits in is not something that query needs to know."""
        found: dict[str, uuid.UUID] = {}
        for library in self._libraries:
            found.update(library.ids)
        return found

    def store(self, entry: LibraryEntry) -> None:
        self._libraries[self._of_label(entry.spec.label)].store(entry)


def _effective_symbols(spine: Sequence[FormalSystem]) -> list[dict[str, SymbolRow]]:
    """Each layer's symbol table as its own grammar sees it, root first.

    A child's effective system is its ancestors' parts followed by its own
    (`layered_spec`), so its *sorts* are theirs as well — and a promoted
    theorem's side conditions name a sort, which `side_conditions_mapping`
    resolves to a real `symbols` FK. The row it should point at is the
    ancestor's, not a copy: §5.1's guarantee is cheap precisely because a child's
    primitives **are** the ancestor's rows.

    Found by running the corpus. `wff_var` is declared wherever the `$f` for a
    `wff` is — the propositional layer, on `set.mm` — while the theorems carrying
    a `$d` over a `wff` metavariable run to the top of the file. Giving each
    layer only its own symbols refused 354 of the first 2,676 promotions with
    "Side-condition sort 'wff_var' is not a symbol of the system", and the
    fixture could not see it: every one of its `$f`s sits in the preamble, so
    they all land in the root and every layer's own table happens to be enough.

    Nearest wins, which costs nothing here — `layered_spec` refuses a name
    redeclared across a chain — but is the rule the rest of the spine follows and
    so is the one to write.
    """
    tables: list[dict[str, SymbolRow]] = []
    effective: dict[str, SymbolRow] = {}
    for system in spine:
        effective = effective | {symbol.name: symbol for symbol in system.symbols}
        tables.append(effective)
    return tables


def _layer_of_position(opens: Sequence[int]) -> Callable[[int], int]:
    # Which layer a position in ``Database.order`` falls in, as an index into the
    # spine.
    #
    # ``opens`` is `corpus.corpus_layers`' — the same list that decided which
    # specs exist, rather than the boundaries re-derived here. Re-deriving them
    # could disagree with the rows actually created: a plan layer the file does
    # not open is not among them, and neither is one the walk never reaches or
    # one sharing its start with the next.
    if len(opens) == 1:
        return lambda _at: 0
    starts = list(opens)
    return lambda at: max(bisect_right(starts, at) - 1, 0)


def _layer_of_label(
    database: Database, opens: Sequence[int]
) -> Callable[[str], int]:
    # The same question asked of a label rather than a position. Separate because
    # a *section* header has a position and no label, and the outline is
    # partitioned by the same boundaries the assertions are.
    of_position = _layer_of_position(opens)
    if len(opens) == 1:
        return lambda _label: 0
    return lambda label: of_position(database.position(label))


class _Library:
    """Writes each assertion the walk promotes into ``promoted_theorems``.

    Held as an object rather than a closure because a batched run *rebinds* the
    system: ``_checkpoint`` empties the identity map and re-fetches it, and the
    symbol table a metavariable's sort resolves through has to follow.

    Contained per theorem, like the proof writes: an assertion whose sort the
    system does not declare, or whose statement will not store, costs itself and
    is reported — not the run. It also stays *out* of the library rather than
    landing there without its terms, so a later verify fails on the citation
    rather than on a half-written row.
    """

    def __init__(
        self,
        session: Session,
        report: ImportReport,
        share: LayerReport,
        digest: str,
    ) -> None:
        self._session = session
        self._report = report
        self._share = share
        self._digest = digest
        # Label -> stored id, so a proof can be linked to the theorem it
        # establishes. Ids survive a checkpoint; the ORM objects do not.
        self.ids: dict[str, uuid.UUID] = {}

    def rebind(self, system: FormalSystem, symbols: Mapping[str, SymbolRow]) -> None:
        # `symbols` is the layer's *effective* table, not `system.symbols`: see
        # `_effective_symbols` for the 354 promotions that told us so.
        self._system = system
        self._symbols = symbols

    def store(self, entry: LibraryEntry) -> None:
        try:
            with self._session.begin_nested():
                row = store_theorem(
                    self._session,
                    self._system,
                    entry.spec,
                    self._symbols,
                    position=self._report.theorems,
                    primitive=entry.primitive,
                    digest=theorem_digest(self._digest, entry.spec),
                    promoted=entry.theorem,
                    premise_labels=entry.premise_labels,
                )
                self._session.flush()
                self.ids[entry.spec.label] = row.id
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            self._report.theorems_failed += 1
            if len(self._report.failures) < _FAILURES_KEPT:
                self._report.failures.append((entry.spec.label, str(exc)))
            return
        self._report.theorems += 1
        self._report.primitives += entry.primitive
        self._share.theorems += 1
        self._share.primitives += entry.primitive


def _record_failure(report: ImportReport, label: str, message: str) -> None:
    report.failed += 1
    if len(report.failures) < _FAILURES_KEPT:
        report.failures.append((label, message))


def _checkpoint(session: Session) -> None:
    """Commit what is held and start again from an empty identity map.

    The map holds every line and term row written so far and nothing downstream
    reads them back, so dropping it is what keeps a long run's memory flat — and
    keeps the per-proof flush from scanning an ever-growing set. Re-attaching the
    systems is `_Layers.rebind`'s job, because ``store_term`` interns against
    them and there may be more than one.
    """
    session.commit()
    session.expunge_all()


@dataclass(frozen=True)
class _Stored:
    """What one theorem contributed, tallied only once its write succeeded."""

    valid: bool
    lines: int
    formulas: int


def _store(
    session: Session,
    system: FormalSystem,
    position: int,
    checked: CheckedTheorem,
    descriptions: Mapping[str, Description],
    folder_id: uuid.UUID | None,
    owner: uuid.UUID | None,
) -> _Stored:
    engine_proof = checked.proof
    valid = bool(engine_proof.valid)
    described = descriptions.get(checked.label)

    proof = Proof(
        formal_system_id=system.id,
        # Null unless the caller asked for an owned import; `import_corpus` says
        # what that gives up.
        owner_id=owner,
        # The Metamath label is the identity here, so it is both the display name
        # and the slug — imported labels are already URL-safe (letters, digits,
        # `-_.`) and unique across the database, which is what a slug wants.
        name=checked.label,
        slug=checked.label,
        # The title is the proof's own copy, editable by whoever comes to own it.
        # The *prose* is not copied: `description` rides on every `ProofSummary`,
        # so a corpus comment here would put a page of text in each row of a
        # 47,000-proof listing. `label_descriptions` holds it — read on the single
        # proof, where there is somewhere to put it, and where it also answers for
        # the labels that are not proofs at all.
        title=described.title or None if described else None,
        # Where the file filed it: the deepest section header before it.
        folder_id=folder_id,
        source=checked.source,
        position=position,
        valid=valid,
        # Written as a draft, and published by `_publish` once the run finishes;
        # see there for why the two are not one step.
        # Stored for the same reason the verify route stores it: `valid`,
        # `result` and the line rows are one artefact of one check, and a row
        # carrying two of the three is a state nothing else in the schema makes.
        result=engine_proof.data(),
    )
    session.add(proof)
    session.flush()

    # `replace=False`: the proof was created three lines ago, so there is no
    # earlier structure to clear, and the delete is not free to issue anyway.
    rows = store_proof_lines(session, proof, system, engine_proof, replace=False)

    return _Stored(
        valid=valid,
        lines=len(rows),
        formulas=sum(1 for row in rows if row.term is not None),
    )
