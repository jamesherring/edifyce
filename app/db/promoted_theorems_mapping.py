"""Round trip between a system's citable library and its rows.

``store_theorem`` writes one promoted theorem — its statement, premises,
metavariables and provisos, plus the composed terms a build would otherwise have
to parse for. ``load_theorems`` reads back **only the labels asked for** and
promotes them against a compiled system.

**Loading is by label, never wholesale.** That is the difference between this and
every other mapping here. A system's grammar, rules and definitions are loaded
entire because a system has a bounded number of each; its library is not bounded —
set.mm contributes 49,000 theorems — and promoting one costs a parse of its
statement against the grammar. So a verify collects the labels its proof actually
cites and loads those, exactly as P1 loads the lemmas a proof references rather
than every proof in the system.

**The terms are a cache; the strings are the record.** A theorem is rebuilt from
its stored text whatever happens, and the stored statement/premise terms only let
that rebuild skip the parse. ``schema_digest`` says whether they still describe
the system, on the same contract as ``app/db/schema_terms.py``: a NULL or a stale
digest is a *miss*, which costs a parse and never a difference.

See docs/verification-from-rows.md, P4.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.promoted_theorems import (
    PromotedTheoremBindingRow,
    PromotedTheoremPremiseRow,
    PromotedTheoremRow,
)
from app.db.side_conditions import SideConditionRow
from app.db.side_conditions_mapping import (
    build_theorem_side_conditions,
    theorem_side_conditions_list,
)
from app.db.terms_mapping import prefetch_terms, store_term
from website.logical.matching import StringPattern
from website.logical.promotion import TheoremSpec, promote_spec

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from app.db.models import FormalSystem
    from app.db.systems import SymbolRow
    from website.logical.formal_system import FormalSystem as EngineSystem
    from website.logical.formal_system import PromotedTheorem
    from website.logical.kernel.terms import Term
    from website.logical.matching.context import Context
    from website.logical.matching.patterns import Pattern


def theorem_digest(library: str, spec: TheoremSpec) -> str:
    """What determines the terms ``spec``'s statement and premises compose to.

    ``library`` is :func:`~website.logical.declarative.library_digest` — the
    system half, computed once for a whole import or verify. This adds the
    theorem's own half: its statement, its premises, and the metavariables that
    decide which of their tokens are schematic rather than literal.

    Its *label* is absent, and its provisos are too: neither reaches the parse
    that composes the terms, so a renamed or re-constrained theorem keeps them.
    """
    return hashlib.sha256(
        json.dumps(
            [
                library,
                spec.statement,
                list(spec.premises),
                sorted(spec.metavariables.items()),
                spec.matching,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


def store_theorem(
    session: Session,
    system: FormalSystem,
    spec: TheoremSpec,
    symbols: Mapping[str, SymbolRow],
    *,
    position: int,
    primitive: bool,
    digest: str | None = None,
    promoted: PromotedTheorem | None = None,
    premise_labels: Sequence[str] = (),
) -> PromotedTheoremRow:
    """Write one promoted theorem's rows and return them (unsaved).

    ``symbols`` resolves a metavariable's sort name to its symbol row; the caller
    holds it because a library import resolves the same handful of sorts tens of
    thousands of times. ``promoted`` is the engine object the caller already
    built, whose composed terms are cached beside the text — omit it and the
    theorem stores its strings alone, which a later load then parses.
    ``digest`` must be :func:`theorem_digest` for ``spec``, and is required
    whenever ``promoted`` is given: it is what says the cached terms are current.
    ``premise_labels`` names each premise as the theorem's *own proof* cites it
    (a Metamath ``$e`` label), positionally; see
    :class:`~app.db.promoted_theorems.PromotedTheoremPremiseRow.label`.
    """
    if promoted is not None and digest is None:
        raise ValueError(
            "store_theorem needs the digest that guards the terms it is caching."
        )

    row = PromotedTheoremRow(
        system_id=system.id,
        position=position,
        label=spec.label,
        statement=spec.statement,
        primitive=primitive,
        matching=spec.matching,
        schema_digest=digest if promoted is not None else None,
        statement_term_id=(
            None if promoted is None
            else _term_id(session, system, promoted.deduction)
        ),
    )
    for index, premise in enumerate(spec.premises):
        row.premises.append(
            PromotedTheoremPremiseRow(
                position=index,
                statement=premise,
                label=(
                    premise_labels[index]
                    if index < len(premise_labels) else None
                ),
                term_id=(
                    None
                    if promoted is None or index >= len(promoted.antecedents)
                    else _term_id(session, system, promoted.antecedents[index])
                ),
            )
        )
    for index, (var, sort) in enumerate(spec.metavariables.items()):
        symbol = symbols.get(sort)
        if symbol is None:
            raise LookupError(
                f"Theorem {spec.label!r} binds {var!r} to sort {sort!r}, which the "
                "system declares no symbol for."
            )
        row.bindings.append(
            PromotedTheoremBindingRow(position=index, var=var, symbol=symbol)
        )

    build_theorem_side_conditions(
        row, list(spec.distinct), symbols, set(spec.metavariables)
    )
    session.add(row)
    return row


def _term_id(
    session: Session, system: FormalSystem, pattern: Pattern | None
) -> uuid.UUID | None:
    # Only a `StringPattern` carries a composed term; a schema that resolved to a
    # declared grammar pattern has none and needs none (see schema_terms._term_id
    # for the same reasoning on the rule side).
    if not isinstance(pattern, StringPattern) or pattern.schema_term is None:
        return None
    stored = store_term(session, system, pattern.schema_term)
    if stored.id is None:
        session.flush()
    return stored.id


def theorem_spec_from_row(row: PromotedTheoremRow) -> TheoremSpec:
    """The declarative form a stored theorem round-trips to."""
    return TheoremSpec(
        label=row.label,
        statement=row.statement,
        metavariables={b.var: b.symbol.name for b in row.bindings},
        premises=tuple(p.statement for p in row.premises),
        distinct=tuple(theorem_side_conditions_list(row)),
        matching=row.matching,
    )


def load_theorems(
    session: Session,
    system_id: uuid.UUID,
    labels: Iterable[str],
    built: EngineSystem,
    context: Context,
    library: str,
    hypotheses_of: uuid.UUID | None = None,
) -> dict[str, PromotedTheorem]:
    """Promote everything one proof may cite: the library entries it names, and
    the hypotheses of the entry it *establishes*.

    Labels with no row are simply absent from the result: a citation may name a
    rule, a line of a cited proof, or nothing at all, and it is the caller's job
    to over-collect rather than this function's to know which is which.

    ``hypotheses_of`` is the theorem this proof proves, when it proves one. A
    theorem proves *under* its ``$e`` hypotheses and its proof states them as
    lines citing their labels, so re-checking needs them registered — exactly as
    the walk registers them for one check and withdraws them
    (``corpus._givens``). They are reached only through the theorem that owns
    them, which is what keeps a bare ``|- ph`` from being citable by anybody
    else, and each becomes a zero-premise theorem over the owner's
    metavariables. A hypothesis wins a name clash with a cited theorem, matching
    the walk, where `_givens` promotes into the same namespace last.

    Both halves are one call because they are one query and, more to the point,
    one term sweep: done separately they each paid a recursive closure over
    `term_children` and a row fetch, which was a third of a re-check.

    ``library`` is :func:`~website.logical.declarative.library_digest` for the
    spec ``built`` was built from — what decides whether the stored terms may be
    used. ``context`` is where those terms' constructors resolve, as for a stored
    proof line.
    """
    wanted = list(dict.fromkeys(labels))
    if not wanted and hypotheses_of is None:
        return {}

    reachable = PromotedTheoremRow.label.in_(wanted) if wanted else false()
    if hypotheses_of is not None:
        reachable = or_(reachable, PromotedTheoremRow.id == hypotheses_of)

    rows = list(
        session.scalars(
            select(PromotedTheoremRow)
            .where(PromotedTheoremRow.system_id == system_id, reachable)
            .options(
                selectinload(PromotedTheoremRow.premises),
                # `joinedload` under the collection, not `selectinload`: a
                # binding's symbol and a proviso's sort are *many-to-one*, so
                # each is one more row on a query already being issued rather
                # than a round trip of its own. Two fewer per verify.
                selectinload(PromotedTheoremRow.bindings).joinedload(
                    PromotedTheoremBindingRow.symbol
                ),
                selectinload(PromotedTheoremRow.side_conditions).joinedload(
                    SideConditionRow.sort_symbol
                ),
            )
        )
    )
    if not rows:
        return {}

    owner = next((row for row in rows if row.id == hypotheses_of), None)
    # The owner is fetched to be *read for its hypotheses*, not to be citable:
    # a theorem's own statement is what its proof is establishing.
    cited = [row for row in rows if row.label in set(wanted)]

    specs = {row.label: theorem_spec_from_row(row) for row in cited}
    fresh = {
        row.label: row
        for row in cited
        if row.schema_digest is not None
        and row.schema_digest == theorem_digest(library, specs[row.label])
    }

    # Every cached term of every theorem asked for, in one sweep — and one memo
    # across all of them, so a subterm two statements share is rebuilt once.
    ids = [
        term_id
        for row in fresh.values()
        for term_id in (row.statement_term_id, *(p.term_id for p in row.premises))
        if term_id is not None
    ]
    if owner is not None:
        # A hypothesis's term is guarded by nothing of its own — it is the
        # owner's premise, and the owner's digest is what says whether the
        # owner's terms are current.
        ids += [p.term_id for p in owner.premises if p.term_id is not None]
    graph = prefetch_terms(session, ids)

    def term(term_id: uuid.UUID | None) -> Term | None:
        return graph.term(term_id, context)

    promoted: dict[str, PromotedTheorem] = {}
    for row in cited:
        current = fresh.get(row.label)
        promoted[row.label] = promote_spec(
            built,
            specs[row.label],
            statement_term=None if current is None else term(current.statement_term_id),
            premise_terms=(
                () if current is None
                else [term(premise.term_id) for premise in current.premises]
            ),
        )

    if owner is not None:
        promoted.update(_hypotheses(owner, built, context, term))
    return promoted


def _hypotheses(
    owner: PromotedTheoremRow,
    built: EngineSystem,
    context: Context,
    term: Callable[[uuid.UUID | None], Term | None],
) -> dict[str, PromotedTheorem]:
    # Each labelled premise of `owner`, as the zero-premise theorem `_givens`
    # builds — including its *default* `matching` rather than the owner's.
    # Inheriting would arguably be better, but only arguably: what matters is
    # that a hypothesis promoted from rows and one promoted by the walk are the
    # same object, and a divergence between those two paths is the bug class P2
    # shipped twice.
    metavariables = {b.var: b.symbol.name for b in owner.bindings}
    return {
        premise.label: promote_spec(
            built,
            TheoremSpec(
                label=premise.label,
                statement=premise.statement,
                metavariables=metavariables,
            ),
            statement_term=term(premise.term_id),
        )
        for premise in owner.premises
        if premise.label is not None
    }


def cited_labels(references: Iterable[str | None]) -> list[str]:
    """The theorem labels a set of citation strings could be naming.

    A citation is ``<label>`` or ``<label>, <line>, …`` — but it may equally name
    an inference rule, a definition, or a line of a cited proof, and which it is
    only the resolver knows (``Proof.get_reference``). So this over-collects on
    purpose: a label with no row costs one entry in an ``IN`` clause, while one
    missed costs the citation.
    """
    labels: list[str] = []
    for reference in references:
        if not reference:
            continue
        for candidate in (reference, reference.split(", ", 1)[0]):
            if candidate and candidate not in labels:
                labels.append(candidate)
    return labels
