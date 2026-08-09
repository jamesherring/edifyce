"""Reading a stored corpus out of the database as plain arrays.

The experiment needs three things from a system that has been imported: every
theorem's **conclusion term** as a DAG, which theorems are *closed* (assertable
on their own, with no hypotheses), and the **citation graph** between them. All
three are already rows — `terms`/`term_children`, `promoted_theorem_premises`,
and `proof_lines.rule` — so this module is a handful of queries and a
densification of the UUID keys into integer indices.

Dense integer ids matter: the analysis is numeric, and a UUID-keyed dict lookup
per node in a walk over a few hundred thousand subterms is most of the runtime.
Everything downstream indexes into the arrays here.

The result is cached to a pickle, because re-running the analysis is cheap and
re-reading the corpus is not.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text

from app.db.session import psycopg_url

if TYPE_CHECKING:
    from pathlib import Path

# `proof_lines.rule` names whatever justified the line. Most names resolve to a
# promoted theorem; the ones that do not are the system's own inference rules,
# and they are dropped rather than added as pseudo-nodes — the citation graph is
# meant to be theorem-to-theorem.
_CITATION_SQL = """
select distinct line.rule, p.name
from proof_lines line
join proofs p on p.id = line.proof_id
where line.rule is not null and p.formal_system_id = :system_id
"""


@dataclass(frozen=True, slots=True)
class Theorem:
    """One entry of a system's citable library."""

    label: str
    position: int
    #: Index into :attr:`Corpus.kind` etc., or ``-1`` when no term was stored.
    term: int
    #: True for a `$a` — an axiom the corpus declared rather than proved.
    primitive: bool
    #: A theorem with hypotheses asserts a *rule*, not `⊢ φ`. Only a theorem
    #: with none of them can serve as a generator; see `formulas.py`.
    premises: int
    #: The corpus section it was declared in — the experiment's "family".
    section: str

    @property
    def closed(self) -> bool:
        return self.premises == 0 and self.term >= 0


@dataclass
class Corpus:
    """A system's terms, theorems and citation graph, densely indexed.

    The term DAG is held as parallel arrays rather than objects: every walk over
    it is hot, and a walk that indexes into lists beats one that chases
    attributes on a few hundred thousand instances.
    """

    system: str
    #: Per term index: ``node`` | ``var`` | ``bound``.
    kind: list[str]
    constructor: list[str | None]
    literal: list[str | None]
    var_name: list[str | None]
    bound_index: list[int | None]
    #: A variable's sort: two variables of different sorts are not alpha-variants.
    sort: list[str | None]
    #: The engine's own alpha-invariant hash, kept only so the experiment's
    #: independently-computed key can be checked against it.
    alpha_digest: list[str | None]
    #: Child indices in slot order.
    children: list[tuple[int, ...]]
    theorems: list[Theorem]
    #: Citing label → the labels its proof cites.
    cites: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def closed_theorems(self) -> list[Theorem]:
        return [t for t in self.theorems if t.closed]

    def save(self, path: Path) -> None:
        path.write_bytes(pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL))

    @staticmethod
    def load(path: Path) -> Corpus:
        return pickle.loads(path.read_bytes())


def _section_paths(connection, system_id: str) -> dict[str, str]:
    """Folder id → its path, joined by ``/``.

    A `.mm` outline is stored as the folder tree it already is, so a theorem's
    "family" is its folder — but a top-level chapter has hundreds of theorems and
    a leaf section a handful, so the caller picks the depth. The full path is
    returned and truncated there.
    """
    rows = connection.execute(
        text(
            "select id::text, parent_id::text, name from proof_folders "
            "where formal_system_id = :system_id"
        ),
        {"system_id": system_id},
    ).all()
    parent = {row[0]: row[1] for row in rows}
    name = {row[0]: row[2] for row in rows}

    def path(folder: str) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        current: str | None = folder
        while current is not None and current not in seen:
            seen.add(current)
            parts.append(name[current])
            current = parent.get(current)
        return "/".join(reversed(parts))

    return {folder: path(folder) for folder in name}


def read_corpus(database_url: str, system_name: str | None = None) -> Corpus:
    """Read the (single, or named) imported system out of `database_url`."""
    # psycopg 3, not psycopg2: the project's synchronous driver, and the one the
    # Metamath importer writes the corpus with.
    engine = create_engine(psycopg_url(database_url), future=True)
    with engine.connect() as connection:
        systems = connection.execute(
            text("select id::text, name from formal_systems order by created_at")
        ).all()
        if not systems:
            raise RuntimeError(f"no formal system in {database_url}")
        chosen = next(
            (s for s in systems if system_name is None or s[1] == system_name), None
        )
        if chosen is None:
            names = ", ".join(repr(s[1]) for s in systems)
            raise RuntimeError(f"no system named {system_name!r}; have {names}")
        system_id, system_label = chosen

        term_rows = connection.execute(
            text(
                "select id::text, kind, constructor, literal, var_name, bound_index, "
                "alpha_digest, sort from terms "
                "where formal_system_id = :system_id order by id"
            ),
            {"system_id": system_id},
        ).all()
        index = {row[0]: position for position, row in enumerate(term_rows)}
        kind = [row[1] for row in term_rows]
        constructor = [row[2] for row in term_rows]
        literal = [row[3] for row in term_rows]
        var_name = [row[4] for row in term_rows]
        bound_index = [row[5] for row in term_rows]
        alpha_digest = [row[6] for row in term_rows]
        sort = [row[7] for row in term_rows]

        edges: list[list[tuple[int, int]]] = [[] for _ in term_rows]
        child_rows = connection.execute(
            text(
                "select c.parent_id::text, c.child_id::text, c.position "
                "from term_children c join terms t on t.id = c.parent_id "
                "where t.formal_system_id = :system_id"
            ),
            {"system_id": system_id},
        ).all()
        for parent_id, child_id, position in child_rows:
            edges[index[parent_id]].append((position, index[child_id]))
        children = [tuple(child for _, child in sorted(slots)) for slots in edges]

        sections = _section_paths(connection, system_id)
        theorem_rows = connection.execute(
            text(
                """
                select t.label, t.position, t.statement_term_id::text, t.primitive,
                       coalesce(premise.count, 0), p.folder_id::text
                from promoted_theorems t
                -- An imported theorem's `proved_by_id` is not populated by the
                -- corpus walk, but a proof carries the label as its name and the
                -- pair is unique per system, so the outline is reachable by name.
                left join proofs p
                       on p.name = t.label and p.formal_system_id = t.system_id
                left join (
                    select theorem_id, count(*) as count
                    from promoted_theorem_premises group by theorem_id
                ) premise on premise.theorem_id = t.id
                where t.system_id = :system_id
                order by t.position
                """
            ),
            {"system_id": system_id},
        ).all()
        theorems = [
            Theorem(
                label=label,
                position=position,
                term=index[term_id] if term_id is not None else -1,
                primitive=primitive,
                premises=premises,
                section=sections.get(folder, "") if folder is not None else "",
            )
            for label, position, term_id, primitive, premises, folder in theorem_rows
        ]

        cited: dict[str, list[str]] = {}
        for target, source in connection.execute(
            text(_CITATION_SQL), {"system_id": system_id}
        ):
            cited.setdefault(source, []).append(target)

    engine.dispose()
    return Corpus(
        system=system_label,
        kind=kind,
        constructor=constructor,
        literal=literal,
        var_name=var_name,
        bound_index=bound_index,
        alpha_digest=alpha_digest,
        sort=sort,
        children=children,
        theorems=theorems,
        cites={source: tuple(sorted(set(targets))) for source, targets in cited.items()},
    )
