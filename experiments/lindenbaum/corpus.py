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

**More than one system may be read at once**, and for a layered import that is
the point: the shared dev database holds the same `set.mm` prefix as three
cumulative layers — propositional calculus, first-order logic, ZF — each with its
own interned term rows. The theorems are the same theorems, and the layers are
cumulative, so ⊢Aᵢ holds in the top layer whichever one declared it. Term indices
are global across the systems read, and the alpha key is computed here from
constructor names shared by all three, so a compound may mix layers.

Every column is selected as text or a number: one of the two transports returns
raw text for everything, so the coercions below are the single place types are
decided rather than something a driver does differently on each side.

The result is cached to a pickle, because re-running the analysis is cheap and
re-reading the corpus is not.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from experiments.lindenbaum.transport import Query, paged, uuid_list

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _int(value: Any) -> int:
    return int(value)


def _bool(value: Any) -> bool:
    # `t`/`f` over the HTTP transport, a real bool over psycopg.
    return value in (True, "t", "true", 1, "1")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


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
    #: Which layer declared it, for a layered import.
    system: str

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

    systems: list[str]
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


def _section_paths(query: Query, systems: str) -> dict[str, str]:
    """Folder id → its path, joined by ``/``.

    A `.mm` outline is stored as the folder tree it already is, so a theorem's
    "family" is its folder — but a top-level chapter has hundreds of theorems and
    a leaf section a handful, so the caller picks the depth. The full path is
    returned and truncated there.
    """
    rows = query(
        "select id::text, parent_id::text, name from proof_folders "
        f"where formal_system_id in ({systems})"
    )
    parent = {str(row[0]): _text(row[1]) for row in rows}
    name = {str(row[0]): str(row[2]) for row in rows}

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


def _choose_systems(query: Query, wanted: Sequence[str] | None) -> list[tuple[str, str]]:
    """The (id, name) of each system to read: those named, or every non-empty one."""
    rows = query(
        "select f.id::text, f.name, count(t.id) as theorems "
        "from formal_systems f "
        "left join promoted_theorems t on t.system_id = f.id "
        "group by f.id, f.name order by theorems desc"
    )
    available = [(str(row[0]), str(row[1]), _int(row[2])) for row in rows]
    if wanted is None:
        chosen = [(i, n) for i, n, count in available if count]
    else:
        by_name = {n: i for i, n, _ in available}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            have = ", ".join(repr(n) for _, n, _ in available)
            raise RuntimeError(f"no system named {missing}; have {have}")
        chosen = [(by_name[name], name) for name in wanted]
    if not chosen:
        raise RuntimeError("no system in this database holds any theorem")
    return chosen


def read_corpus(query: Query, systems: Sequence[str] | None = None) -> Corpus:
    """Read the named systems — or every non-empty one — as a single corpus."""
    chosen = _choose_systems(query, systems)
    scope = uuid_list(identifier for identifier, _ in chosen)
    system_of = dict(chosen)

    term_rows = list(
        paged(
            query,
            "select id::text, kind, constructor, literal, var_name, bound_index, "
            "alpha_digest, sort from terms "
            f"where formal_system_id in ({scope}) {{page}}",
            "id",
        )
    )
    index = {str(row[0]): position for position, row in enumerate(term_rows)}
    kind = [str(row[1]) for row in term_rows]
    constructor = [_text(row[2]) for row in term_rows]
    literal = [_text(row[3]) for row in term_rows]
    var_name = [_text(row[4]) for row in term_rows]
    bound_index = [None if row[5] is None else _int(row[5]) for row in term_rows]
    alpha_digest = [_text(row[6]) for row in term_rows]
    sort = [_text(row[7]) for row in term_rows]

    edges: list[list[tuple[int, int]]] = [[] for _ in term_rows]
    seen_edges: set[tuple[str, str]] = set()
    for parent_id, slot, child_id, position in paged(
        query,
        "select c.parent_id::text, c.slot, c.child_id::text, c.position "
        "from term_children c join terms t on t.id = c.parent_id "
        f"where t.formal_system_id in ({scope}) {{page}}",
        "c.parent_id",
        unique=False,
    ):
        edge = (str(parent_id), str(slot))
        if edge in seen_edges:
            continue
        seen_edges.add(edge)
        edges[index[str(parent_id)]].append((_int(position), index[str(child_id)]))
    children = [tuple(child for _, child in sorted(slots)) for slots in edges]

    sections = _section_paths(query, scope)
    theorem_rows = query(
        """
        select t.label, t.position, t.statement_term_id::text, t.primitive,
               coalesce(premise.count, 0), p.folder_id::text, t.system_id::text
        from promoted_theorems t
        -- An imported theorem's `proved_by_id` is not populated by the corpus
        -- walk, but a proof carries the label as its name and the pair is unique
        -- per system, so the outline is reachable by name.
        left join proofs p
               on p.name = t.label and p.formal_system_id = t.system_id
        left join (
            select theorem_id, count(*) as count
            from promoted_theorem_premises group by theorem_id
        ) premise on premise.theorem_id = t.id
        """
        + f"where t.system_id in ({scope}) order by t.position"
    )
    theorems = [
        Theorem(
            label=str(label),
            position=_int(position),
            term=index[str(term_id)] if term_id is not None else -1,
            primitive=_bool(primitive),
            premises=_int(premises),
            section=sections.get(str(folder), "") if folder is not None else "",
            system=system_of[str(system_id)],
        )
        for label, position, term_id, primitive, premises, folder, system_id in (
            theorem_rows
        )
    ]

    cited: dict[str, list[str]] = {}
    for target, source in query(
        "select distinct line.rule, p.name from proof_lines line "
        "join proofs p on p.id = line.proof_id "
        f"where line.rule is not null and p.formal_system_id in ({scope})"
    ):
        cited.setdefault(str(source), []).append(str(target))

    return Corpus(
        systems=[name for _, name in chosen],
        kind=kind,
        constructor=constructor,
        literal=literal,
        var_name=var_name,
        bound_index=bound_index,
        sort=sort,
        alpha_digest=alpha_digest,
        children=children,
        theorems=theorems,
        cites={source: tuple(sorted(set(targets))) for source, targets in cited.items()},
    )
