"""A reader for Metamath (``.mm``) source.

Metamath's surface language is tiny: whitespace-separated tokens, ``$( … $)``
comments, and a handful of statement keywords. This module turns that text into
the records an import needs, and nothing more - it does not verify proofs (that
is the point of importing: Edifyce's kernel does the checking).

The statement types and what they become here:

===========  ==========================================  ====================
Metamath     Meaning                                     Record
===========  ==========================================  ====================
``$c``       declare constant symbols                    ``Database.constants``
``$v``       declare variable symbols                    ``Database.variables``
``$f``       *floating* hypothesis: a variable's type    :class:`Hypothesis`
``$e``       *essential* hypothesis: a premise            :class:`Hypothesis`
``$a``       axiom (syntax **or** logical - see below)   :class:`Assertion`
``$p``       theorem, with a proof                       :class:`Assertion`
``$d``       distinct-variable constraint                ``Assertion.distinct``
``${ $}``    scope block over ``$f``/``$e``/``$d``       the scope stack
===========  ==========================================  ====================

Two distinctions carry the weight of an import:

*Syntax vs logic.* An ``$a`` whose typecode is the assertion typecode (``|-``)
states something *true*; any other typecode (``wff``, ``class``, ``setvar``)
declares *notation* - it is a grammar production, because Metamath has no parser
and builds well-formedness by proof. :attr:`Assertion.is_logical` separates them.

*Mandatory hypotheses.* Applying an assertion consumes, in declaration order, its
active ``$e`` hypotheses plus the ``$f`` hypotheses of every variable those and
its own statement mention. That ordered list (:attr:`Assertion.mandatory`) is
exactly what a compressed proof's stack machine pops, so it is computed here at
parse time rather than rediscovered later.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass, field

# The typecode marking an assertion of truth; every other typecode introduces
# notation. Metamath fixes no such keyword - `|-` is set.mm's convention - so it
# is a parameter of the reader rather than a constant of the language.
ASSERTION_TYPECODE = "|-"


class MetamathError(Exception):
    """Raised on malformed or unsupported Metamath source."""


@dataclass(frozen=True)
class Hypothesis:
    """A ``$f`` (floating) or ``$e`` (essential) hypothesis."""

    label: str
    typecode: str
    tokens: tuple[str, ...]
    floating: bool
    # Declaration order across the whole file, so an assertion's mandatory
    # hypotheses can be ordered without tracking the scope stack afterwards.
    position: int

    @property
    def variable(self) -> str:
        """The variable a floating hypothesis types (``$f class A`` -> ``A``)."""
        if not self.floating:
            raise MetamathError(f"{self.label} is not a floating hypothesis.")
        return self.tokens[0]


@dataclass(frozen=True)
class Assertion:
    """A ``$a`` axiom or ``$p`` theorem."""

    label: str
    typecode: str
    tokens: tuple[str, ...]
    mandatory: tuple[Hypothesis, ...]
    distinct: tuple[frozenset[str], ...] = ()
    # The raw proof tokens of a `$p` (still compressed); empty for a `$a`.
    proof: tuple[str, ...] = ()
    # Labels of every hypothesis active where this statement was declared - a
    # superset of `mandatory`, since a proof may also cite *optional* hypotheses
    # that are in scope but unmentioned by the statement. Recorded so a proof can
    # be checked to cite only what was actually in scope for it.
    active_hypotheses: tuple[str, ...] = ()
    # The `$( … $)` comment immediately preceding the statement, verbatim, or None.
    # Metamath has no description keyword: a statement is documented by the comment
    # before it, and that convention is the whole of the association. Kept raw here
    # so this module stays a reader - :mod:`~.comments` is what reads prose and
    # attributions out of it.
    comment: str | None = None

    @property
    def is_logical(self) -> bool:
        """Whether this asserts truth (``|-``) rather than declaring notation."""
        return self.typecode == ASSERTION_TYPECODE

    @property
    def is_axiom(self) -> bool:
        """Whether this is a ``$a`` (asserted) rather than a ``$p`` (proved)."""
        return not self.proof

    @property
    def declares_notation(self) -> bool:
        """Whether this introduces a grammar production.

        Only an *asserted* statement with a syntax typecode does. A ``$p`` with a
        syntax typecode is a proved *syntactic theorem* - set.mm's ``bj-0``,
        ``wff ( ( ph -> ps ) -> ch )``, is provable from ``wi`` and introduces no
        new notation. Reading one as a production invents a redundant constructor
        that overlaps the real nesting and makes the grammar ambiguous.
        """
        return self.is_axiom and not self.is_logical

    @property
    def essentials(self) -> tuple[Hypothesis, ...]:
        return tuple(h for h in self.mandatory if not h.floating)

    @property
    def floatings(self) -> tuple[Hypothesis, ...]:
        return tuple(h for h in self.mandatory if h.floating)


@dataclass(frozen=True)
class Commentary:
    """One ``$( … $)`` comment, and where in the file it sits.

    ``at`` is an index into :attr:`Database.order`: how many assertions were
    declared before this comment, and so the position of the first assertion it
    precedes. A comment after the last assertion has ``at == len(order)``.

    Metamath says what a comment is *about* by position and nothing else — the
    description of a statement is the comment before it — so a reader that wants
    to interpret a comment against the file's structure needs the position too.
    :mod:`~.sections` is the one that does: a header comment marks where a section
    begins, and "where" is exactly this.
    """

    body: str
    at: int


@dataclass
class Database:
    """The parsed contents of a Metamath file."""

    constants: set[str] = field(default_factory=set)
    variables: set[str] = field(default_factory=set)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    assertions: dict[str, Assertion] = field(default_factory=dict)
    # Assertion labels in file order - the order an import must follow, since a
    # theorem may only cite what precedes it.
    order: list[str] = field(default_factory=list)
    # Every `$( … $)` comment, in file order and with its position, including
    # those attached to a statement. The unattached ones are what carry a file's
    # front matter, its `$t` typesetting block (:mod:`~.typesetting`) and its
    # section headers (:mod:`~.sections`).
    commentary: list[Commentary] = field(default_factory=list)
    # Views derived from the fields above, built on first use. `parse` populates
    # a database and hands it over; nothing mutates one afterwards, so these stay
    # valid for its lifetime. They are cached because an import asks for them per
    # *theorem* while they are facts about the whole file - on set.mm, scanning
    # 50k assertions or 68k hypotheses again for each of them dominated the run.
    _syntax: list[Assertion] | None = field(default=None, repr=False, compare=False)
    _positions: dict[str, int] | None = field(default=None, repr=False, compare=False)
    _floating_typecodes: list[str] | None = field(default=None, repr=False, compare=False)
    _syntax_typecodes: set[str] | None = field(default=None, repr=False, compare=False)
    _typed_from: dict[tuple[str, str], int] | None = field(
        default=None, repr=False, compare=False
    )

    def logical_assertions(self) -> list[Assertion]:
        return [a for a in self.iter_assertions() if a.is_logical]

    def syntax_assertions(self) -> list[Assertion]:
        """The statements that *declare* notation, in file order."""
        if self._syntax is None:
            self._syntax = [a for a in self.iter_assertions() if a.declares_notation]
        return self._syntax

    def syntax_typecodes(self) -> set[str]:
        """Every typecode some syntax axiom builds a statement of."""
        if self._syntax_typecodes is None:
            self._syntax_typecodes = {a.typecode for a in self.syntax_assertions()}
        return self._syntax_typecodes

    def floating_typecodes(self) -> list[str]:
        """Every typecode some ``$f`` declares a variable at, in declaration order."""
        if self._floating_typecodes is None:
            seen: list[str] = []
            for hypothesis in self.hypotheses.values():
                if hypothesis.floating and hypothesis.typecode not in seen:
                    seen.append(hypothesis.typecode)
            self._floating_typecodes = seen
        return self._floating_typecodes

    def typed_from(self) -> dict[tuple[str, str], int]:
        """``(typecode, variable)`` -> the first position it is typed at.

        A ``$f`` is *scoped*: `${ vx $f class x $. … $}` types `x` as a class only
        inside that block, and a later block may type the same `x` as a `wff`. So
        availability is a property of the pair, not of the variable — read off each
        assertion's *active* floating hypotheses, which is exactly the set in scope
        where it sits.

        Active rather than mandatory, because a proof may use a variable from an
        optional floating hypothesis as a dummy and Metamath permits it: 14 of
        set.mm's theorems do, `ax7` among them, and their intermediate lines carry
        a variable the grammar would otherwise have no leaf for.
        """
        if self._typed_from is None:
            first: dict[tuple[str, str], int] = {}
            for index, label in enumerate(self.order):
                for name in self.assertions[label].active_hypotheses:
                    hypothesis = self.hypotheses[name]
                    if hypothesis.floating:
                        first.setdefault(
                            (hypothesis.typecode, hypothesis.variable), index
                        )
            self._typed_from = first
        return self._typed_from

    @property
    def comments(self) -> list[str]:
        """Every comment body, in file order — :attr:`commentary` without positions.

        What a consumer that only wants to *read* comments wants, and most do:
        the `$t` block is found by scanning bodies, and a statement's description
        comes off the statement. Position matters only to :mod:`~.sections`.
        """
        return [entry.body for entry in self.commentary]

    def position(self, label: str) -> int:
        """Index of assertion ``label`` in file order."""
        if self._positions is None:
            self._positions = {name: index for index, name in enumerate(self.order)}
        return self._positions[label]

    def iter_assertions(self) -> Iterator[Assertion]:
        return (self.assertions[label] for label in self.order)


def _tokenise(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Split ``text`` into tokens, keeping the ``$( … $)`` comments aside.

    Returns the tokens and, per comment in file order, the index of the token it
    immediately *precedes* - which is how a Metamath comment says what it is
    about: the description of a statement is the comment before it.

    Comments used to be discarded here. They carry most of what a `.mm` file
    knows beyond its mathematics - `set.mm` has 55,742 of them, 46,976 with a
    `(Contributed by …)` - and the `$t` typesetting block, which is the only
    machine-readable notation the file has, is itself a comment.

    Metamath forbids nesting, so a linear scan is correct; an unterminated
    comment is a hard error rather than a silent tail. Scanned by index rather
    than by re-slicing the remainder, because carrying the tail forward each time
    is quadratic over 51 MB and takes minutes.
    """
    tokens: list[str] = []
    comments: list[tuple[int, str]] = []
    position = 0
    while True:
        start = text.find("$(", position)
        if start == -1:
            tokens.extend(text[position:].split())
            return tokens, comments

        tokens.extend(text[position:start].split())
        end = text.find("$)", start + 2)
        if end == -1:
            raise MetamathError("Unterminated comment ($( with no $)).")
        comments.append((len(tokens), text[start + 2:end]))
        position = end + 2


class _Scope:
    """One ``${ … $}`` level: the hypotheses and $d constraints it introduces."""

    def __init__(self) -> None:
        self.hypotheses: list[Hypothesis] = []
        self.distinct: list[frozenset[str]] = []


def parse(text: str) -> Database:
    """Parse Metamath source into a :class:`Database`.

    Raises :class:`MetamathError` on malformed source. ``$[ … $]`` file
    inclusion is not supported - an import works on a self-contained database.
    """
    tokens, comments = _tokenise(text)
    database = Database()
    # The comment a statement is documented by is the nearest one before it, so a
    # later comment at the same token index wins.
    preceding = {index: body for index, body in comments}
    # The token index each assertion's label sits at, parallel to `order`. Kept so
    # a comment can be placed among the assertions once both are read (see the
    # `commentary` assembly at the end): both lists come out sorted by token
    # index, so the placement is a merge rather than a search.
    label_indices: list[int] = []
    scopes: list[_Scope] = [_Scope()]
    position = 0

    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token == "${":
            scopes.append(_Scope())
            index += 1
            continue

        if token == "$}":
            if len(scopes) == 1:
                raise MetamathError("Unbalanced $} (no open scope).")
            scopes.pop()
            index += 1
            continue

        if token == "$[":
            raise MetamathError("File inclusion ($[ ... $]) is not supported.")

        if token in ("$c", "$v", "$d"):
            body, index = _read_until(tokens, index + 1, "$.")
            if token == "$c":
                database.constants.update(body)
            elif token == "$v":
                database.variables.update(body)
            else:
                # `$d x y z` constrains every pair among the listed variables.
                scopes[-1].distinct.append(frozenset(body))
            continue

        # Anything else must be a label followed by a keyword.
        if index + 1 >= len(tokens):
            raise MetamathError(f"Dangling token {token!r} at end of file.")

        label, keyword = token, tokens[index + 1]
        label_index = index
        body, index = _read_until(tokens, index + 2, "$.")

        if keyword in ("$f", "$e"):
            if not body:
                raise MetamathError(f"{label}: empty {keyword} statement.")
            _reject_duplicate(label, database)
            hypothesis = Hypothesis(
                label=label,
                typecode=body[0],
                tokens=tuple(body[1:]),
                floating=keyword == "$f",
                position=position,
            )
            position += 1
            if hypothesis.floating and len(hypothesis.tokens) != 1:
                raise MetamathError(f"{label}: a $f statement types exactly one variable.")
            database.hypotheses[label] = hypothesis
            scopes[-1].hypotheses.append(hypothesis)
            continue

        if keyword in ("$a", "$p"):
            proof: tuple[str, ...] = ()
            if keyword == "$p":
                if "$=" not in body:
                    raise MetamathError(f"{label}: a $p statement needs a $= proof.")
                split = body.index("$=")
                body, proof = body[:split], tuple(body[split + 1:])

            if not body:
                raise MetamathError(f"{label}: empty {keyword} statement.")
            _reject_duplicate(label, database)

            statement = tuple(body[1:])
            active = [h for scope in scopes for h in scope.hypotheses]
            database.assertions[label] = Assertion(
                label=label,
                typecode=body[0],
                tokens=statement,
                mandatory=_mandatory(active, statement, database.variables),
                distinct=tuple(d for scope in scopes for d in scope.distinct),
                proof=proof,
                active_hypotheses=tuple(h.label for h in active),
                comment=preceding.get(label_index),
            )
            database.order.append(label)
            label_indices.append(label_index)
            continue

        raise MetamathError(f"{label}: unknown statement keyword {keyword!r}.")

    if len(scopes) != 1:
        raise MetamathError("Unbalanced ${ (scope left open at end of file).")

    database.commentary = [
        Commentary(body=body, at=bisect_left(label_indices, token_index))
        for token_index, body in comments
    ]
    return database


def _reject_duplicate(label: str, database: Database) -> None:
    # Labels are a single flat namespace in Metamath and must be unique. Silently
    # overwriting would lose the first statement while leaving its label in
    # `order`, so the second would be yielded twice and the first would vanish -
    # a corrupted database that still looks well-formed.
    if label in database.assertions or label in database.hypotheses:
        raise MetamathError(f"Duplicate label {label!r}.")


def _read_until(tokens: list[str], start: int, terminator: str) -> tuple[list[str], int]:
    # Collect tokens up to `terminator`, returning them and the index past it.
    end = start
    while end < len(tokens) and tokens[end] != terminator:
        end += 1
    if end >= len(tokens):
        raise MetamathError(f"Statement is missing its {terminator} terminator.")
    return tokens[start:end], end + 1


def _mandatory(
    active: list[Hypothesis], statement: tuple[str, ...], variables: set[str]
) -> tuple[Hypothesis, ...]:
    # An assertion's mandatory hypotheses, in declaration order: every active
    # essential hypothesis, plus the floating hypothesis of each variable
    # mentioned by the statement or by those essentials. Floating hypotheses for
    # variables the assertion never mentions are *not* mandatory - they are not
    # popped when it is applied - so they must be filtered out here or every
    # stack machine using this list would be misaligned.
    essentials = [h for h in active if not h.floating]

    mentioned: set[str] = {t for t in statement if t in variables}
    for hypothesis in essentials:
        mentioned.update(t for t in hypothesis.tokens if t in variables)

    floatings = [h for h in active if h.floating and h.variable in mentioned]

    return tuple(sorted([*essentials, *floatings], key=lambda h: h.position))
