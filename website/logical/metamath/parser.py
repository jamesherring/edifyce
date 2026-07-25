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
    # Views derived from the fields above, built on first use. `parse` populates
    # a database and hands it over; nothing mutates one afterwards, so these stay
    # valid for its lifetime. They are cached because an import asks for them per
    # *theorem* while they are facts about the whole file - on set.mm, scanning
    # 50k assertions or 68k hypotheses again for each of them dominated the run.
    _syntax: list[Assertion] | None = field(default=None, repr=False, compare=False)
    _positions: dict[str, int] | None = field(default=None, repr=False, compare=False)
    _floating_typecodes: list[str] | None = field(default=None, repr=False, compare=False)

    def logical_assertions(self) -> list[Assertion]:
        return [a for a in self.iter_assertions() if a.is_logical]

    def syntax_assertions(self) -> list[Assertion]:
        """The statements that *declare* notation, in file order."""
        if self._syntax is None:
            self._syntax = [a for a in self.iter_assertions() if a.declares_notation]
        return self._syntax

    def floating_typecodes(self) -> list[str]:
        """Every typecode some ``$f`` declares a variable at, in declaration order."""
        if self._floating_typecodes is None:
            seen: list[str] = []
            for hypothesis in self.hypotheses.values():
                if hypothesis.floating and hypothesis.typecode not in seen:
                    seen.append(hypothesis.typecode)
            self._floating_typecodes = seen
        return self._floating_typecodes

    def position(self, label: str) -> int:
        """Index of assertion ``label`` in file order."""
        if self._positions is None:
            self._positions = {name: index for index, name in enumerate(self.order)}
        return self._positions[label]

    def iter_assertions(self) -> Iterator[Assertion]:
        return (self.assertions[label] for label in self.order)


def _strip_comments(text: str) -> str:
    # Remove `$( ... $)` comments. Metamath forbids nesting, so a linear scan is
    # correct; an unterminated comment is a hard error rather than a silent tail.
    #
    # Scan by index rather than re-slicing the remainder: set.mm holds ~56k
    # comments in 51MB, so carrying the tail forward each time is quadratic and
    # takes minutes, against well under a second for this.
    out: list[str] = []
    position = 0
    while True:
        start = text.find("$(", position)
        if start == -1:
            out.append(text[position:])
            return "".join(out)

        out.append(text[position:start])
        end = text.find("$)", start + 2)
        if end == -1:
            raise MetamathError("Unterminated comment ($( with no $)).")
        # Keep a space so tokens either side never fuse across the comment.
        out.append(" ")
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
    tokens = _strip_comments(text).split()
    database = Database()
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
            )
            database.order.append(label)
            continue

        raise MetamathError(f"{label}: unknown statement keyword {keyword!r}.")

    if len(scopes) != 1:
        raise MetamathError("Unbalanced ${ (scope left open at end of file).")

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
