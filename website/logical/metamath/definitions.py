"""Deciding which of a Metamath database's logical ``$a`` are *definitions*.

Metamath does not distinguish them. A definition and an axiom are both ``$a``,
and a `df-` prefix is a naming convention its verifier never reads - soundness of
the definitional ones is left to an *external* checker. Importing every logical
``$a`` as an axiom is therefore faithful and fully verifiable, which is what the
import did; what it gives up is conservativity-by-construction, which Edifyce's
``Define`` supplies for free, and definitional steps (``[Def, n]``) in a proof.

It also overstates the basis. On `set.mm` that is 1,433 `df-` statements declared
primitives of the imported system - far more than `set.mm` itself assumes.

What makes a definition, here
-----------------------------
Nothing about the *label*. Two structural tests, in order, and then the kernel:

1. The statement's root is a **declared definitional equivalence**. Which
   production that is has to be *told* to the classifier (``equivalences``), not
   inferred: arity and slot sorts do not distinguish `↔` from `→`, and reading a
   one-way implication as a definition would licence the reverse rewrite and
   strengthen the theory. Nothing is a definition under the default empty set, so
   a caller that says nothing gets the old all-axioms import.
2. Its left side is **not a bare metavariable**, which defines nothing.
3. Its left side is **built from notation not yet in use**. This is what makes it
   a *definition* rather than an equation between things that already exist, and
   it is the test that does the real work: on `set.mm` it separates the genuine
   definitions from `ax-i2m1` (``( ( i x. i ) + 1 ) = 0``), the reflexivity
   axioms (``A = A``), and - the interesting case - `df-clab`, `df-cleq` and
   `df-clel`, whose left sides are ordinary ``e.``/``=`` and which are genuinely
   axioms connecting class notation to set theory, whatever their names suggest.

Then the refusals, for what a `Definition` cannot faithfully carry: a defining form
built from the very form being defined (a recursive alias, not something
eliminable), a metavariable the proviso syntax cannot name, and the two below.
A `$d` *can* be carried, as the definition's condition, and must be: 1,033 of
set.mm's definition-shaped statements have one.

A `$e` is carried too, as a `Justification`. A definition holds unconditionally,
so a hypothesis has to be settled once and for all rather than per unfold - and
`set.mm` shows how, because it does it itself: `df-sb`'s `$e sbjust.1` is stated
verbatim by `sbjust`, a `$p` proved earlier in the file. So the hypothesis is
discharged by *citation*, and this module's part is only to find the citation -
a proved statement token-identical to the hypothesis, ahead of it in the file.
Whether it really discharges the obligation is settled structurally when the
definition is registered (`declarative._discharge_justification`), not here.

Binding slots, and why they decide most of this
-----------------------------------------------
**A defining form may not introduce a variable the defined form does not supply.**
`df-tru` is ``|- ( T. <-> ( A. x x = x -> A. x x = x ) )`` - `x` is quantified in
the defining form and `T.` has no room for it - and *1,123 of set.mm's 1,433*
`df-` statements are that shape. Refused, this was by far the largest refusal;
admitted, it is most of the corpus's definitions.

Each is sound in Metamath and is sound here, because the defining form *binds* the
variable: a `Definition` says so with a `fresh` clause, which is what makes the
unfold capture-avoiding. A `fresh` clause is inferred from the grammar's binding
slots (``Production.scopes_over``), and a `.mm` file carries no trace of them -
nothing in ``A. x ph`` says the first slot binds in the second. So the slots are
*declared* per database (:mod:`~.setmm`), and where none are, this module cannot
tell a bound `x` from one left free and refuses, which is the safe direction and
exactly how it behaved before they could be declared.

Two consequences run through what follows. The introduced-variable test asks
:func:`~website.logical.kernel.definitions.bind_scoped` - the same call
``parse_definition`` makes to infer a `fresh` clause - rather than re-deriving the
scopes, so its answer and registration's are one answer. And a definition's
`bindings` carry only what the *defined* form supplies: a binder declared among
them would parse to a `Var` in the context the forms are re-read in, `bind_scoped`
skips `Var`s by design, and the binder would never be placed. That last cost 242
of set.mm's 1,335 candidates until it was found by running the whole corpus.

It is refused *here* rather than left to the kernel because the kernel refuses by
raising, which aborts a whole import; the contract of this module is that doubt
costs an axiom, not a build.

None of the shape tests is load-bearing alone, and the reason test 1 names its
relation rather than describing it is that describing it failed twice. Matching on
"two slots of one sort" admits `→` as readily as `↔`; test 3 then admits `ax-1`
(``|- ( ph -> ( ps -> ph ) )``) as ``ph := ( ps -> ph )``, because `ph` is notation
not yet in use the first time it appears, which is what test 2 is for. That much
was found by running the classifier over `set.mm`. It still admitted
``|- ( NEW ph ps -> ph )`` as ``NEW ph ps := ph`` - a fresh compound antecedent
rather than a bare metavariable, so test 2 does not fire - which is what made
declaring the relation the only defensible reading. Nor is the set of them trusted
to be complete.

**The default on any doubt is axiom**, which costs a longer proof rather than an
unsound one - and that is a promise about *behaviour*, not only about the verdict:
what this module returns, registration accepts. A definition handed back that the
kernel then refuses would abort the import of a whole corpus over one statement,
which is the opposite of falling back. So each refusal above that mirrors a kernel
one is made here first.

What is behind that default is less than it sounds: the kernel refuses a
definition whose defining form introduces a leaf the defined form does not supply
- the capture half of admissibility - and that is all. Non-circularity and
conservativity are untreated there, as in Metamath (see AGENTS.md), so the
circularity refusal above has nothing behind it and every other gap of that kind
is this module's to close.

`df-bi` shows why the tests have to be structural. It defines ``<->`` and so
cannot use it: its statement is a nest of negated implications, root ``-.``, and
it falls to axiom exactly as it should.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..declarative import Definition, Justification
from ..formal_system import statement_term
from ..kernel.definitions import bind_scoped
from ..kernel.terms import Node
from ..promotion import promote_from_source
from .importer import _distinct_provisos, _proviso_safe_names

if TYPE_CHECKING:
    from ..formal_system import FormalSystem
    from ..kernel.terms import Term
    from .parser import Assertion, Database, Hypothesis


@dataclass(frozen=True)
class Classified:
    """What one logical ``$a`` turned out to be.

    ``definition`` is the spec to declare when the assertion is definitional, and
    None when it is an axiom - in which case ``reason`` says which test refused
    it, so a bulk import can report *why* it left something primitive rather than
    leaving the answer to be re-derived.
    """

    label: str
    definition: Definition | None = None
    reason: str = ""

    @property
    def is_definition(self) -> bool:
        return self.definition is not None


def statement_of(assertion: Assertion, system: FormalSystem) -> Term | None:
    """``assertion``'s statement as a term of ``system``, or None if it will not
    parse against the grammar as it stands.

    Read with **no** metavariables, so each Metamath variable parses to the atom
    production that declares it rather than staying schematic. That is the reading
    every test here is stated over, and the one the shape tests need: `_sides`
    asks what the root's operands *are*, and a `Var` would answer nothing.

    Promotion rather than a proof-line parse because it composes the term at the
    system's logical sorts, which is the same question without a dependency on how
    a proof line happens to be shaped.
    """
    try:
        theorem = promote_from_source(
            system, label=assertion.label, statement=" ".join(assertion.tokens),
            metavariables={},
        )
    except Exception:  # noqa: BLE001 - an unparsable statement is a refusal, not a fault
        return None
    return statement_term(theorem.deduction)


def constructors_used(term: Term) -> set[str]:
    """Every constructor name appearing anywhere in ``term``.

    A :class:`~website.logical.kernel.terms.Var` contributes none - it stands for
    a term rather than naming a production - so only nodes are read.
    """
    names: set[str] = set()
    stack = [term]
    while stack:
        node = stack.pop()
        if isinstance(node, Node):
            names.add(node.constructor.name)
            stack.extend(node.children.values())
    return names


def _sides(term: Term) -> tuple[Node, Node] | None:
    # The two operands of a relation between two things of one sort, or None if
    # the term is not one. The slots must agree in sort: that is what tells `=`
    # and `↔` from a production that merely happens to take two arguments.
    if not isinstance(term, Node):
        return None

    slots = term.constructor.slots
    if len(slots) != 2 or slots[0] == slots[1]:
        return None

    sorts = term.constructor.slot_sorts
    if slots[0] not in sorts or sorts[slots[0]] is not sorts[slots[1]]:
        return None

    left, right = term.children[slots[0]], term.children[slots[1]]
    if not isinstance(left, Node) or not isinstance(right, Node):
        return None

    return left, right


def variables_used(term: Term, variables: set[str]) -> set[str]:
    """Which of ``variables`` appear as leaves of ``term``.

    A Metamath metavariable is a *ground* leaf here, not a
    :class:`~website.logical.kernel.terms.Var`: the imported grammar declares one
    atom production per declared variable (``importer._variable_productions``), so
    `ph` in a parsed statement is a nullary node whose literal is its name. Which
    of them is a metavariable is therefore the caller's to say, from the ``$f``
    hypotheses, and not readable off the term.
    """
    found: set[str] = set()
    stack = [term]
    while stack:
        node = stack.pop()
        if isinstance(node, Node):
            if node.literal in variables:
                found.add(node.literal)
            stack.extend(node.children.values())
    return found


def _proved_statement(
    hypothesis: Hypothesis, before: int, database: Database
) -> str | None:
    # The label of a `$p` proved before position ``before`` whose statement is
    # exactly ``hypothesis``', or None. Token identity is the whole test: `set.mm`
    # states a justification theorem and the hypothesis citing it verbatim, and
    # anything looser would be this module guessing at what discharges what when
    # the engine settles that structurally at registration.
    #
    # A candidate under `$e` hypotheses of its own is skipped: it settles its
    # statement only *given* something else, which is the obligation again one
    # step back, and the engine refuses it for that reason. Skipping here keeps
    # the module's contract - fall back to axiom, never hand back a definition
    # registration is bound to reject.
    for label in database.order[:before]:
        candidate = database.assertions.get(label)
        if candidate is None or candidate.is_axiom or not candidate.is_logical:
            continue
        if candidate.essentials:
            continue
        if candidate.typecode == hypothesis.typecode and candidate.tokens == hypothesis.tokens:
            return label
    return None


def _justification(assertion: Assertion, database: Database) -> Justification | None | str:
    # How ``assertion``'s ``$e`` hypotheses are discharged: None when it has
    # none, a :class:`Justification` when the one it has is already proved, and a
    # refusal *reason* otherwise.
    #
    # A definition holds unconditionally, so a `$a` under a hypothesis needs that
    # hypothesis settled once and for all. A `Definition` carries one obligation,
    # which is one more than `set.mm` ever needs (`df-sb` and `df-mo` have a
    # single `$e` each), so several are refused rather than guessed at.
    essentials = assertion.essentials
    if not essentials:
        return None
    if len(essentials) > 1:
        premises = ", ".join(h.label for h in essentials)
        return f"holds only under several hypotheses ({premises})"

    hypothesis = essentials[0]
    proved = _proved_statement(hypothesis, database.position(assertion.label), database)
    if proved is None:
        return (
            f"holds only under hypothesis {hypothesis.label}, which nothing "
            "proved before it states"
        )
    return Justification(label=proved, statement=" ".join(hypothesis.tokens))


def classify(
    assertion: Assertion,
    statement: Term | None,
    in_use: set[str],
    database: Database,
    system: FormalSystem,
    equivalences: frozenset[str] = frozenset(),
) -> Classified:
    """Decide whether ``assertion`` is a definition, given what precedes it.

    ``statement`` is the parsed statement (None if it did not parse) and
    ``in_use`` the constructor names every *earlier* logical assertion used -
    both supplied by the caller, because a walk already has them and re-deriving
    either per assertion would re-parse the corpus. ``database`` and ``system``
    are needed only to render a ``$d`` into proviso syntax.

    ``equivalences`` names the productions that mean *definitional equivalence* in
    this database - `set.mm`'s are `wb` and `wceq`. It is declared rather than
    inferred because nothing structural distinguishes an equivalence from an
    implication, and it defaults to empty, so a caller that names none imports
    every logical ``$a`` as an axiom exactly as before.
    """
    if statement is None:
        return Classified(assertion.label, reason="statement does not parse")

    root = statement.constructor.name if isinstance(statement, Node) else "a variable"
    if root not in equivalences:
        return Classified(
            assertion.label,
            reason=f"root is not a declared definitional equivalence ({root})",
        )

    sides = _sides(statement)
    if sides is None:
        return Classified(
            assertion.label,
            reason=f"not a relation between two things of one sort (root {root})",
        )

    higher, lower = sides
    defined = higher.to_string()
    if defined in {h.variable for h in assertion.floatings}:
        # A bare metavariable defines nothing. Without this, `ax-1`
        # (``|- ( ph -> ( ps -> ph ) )``) reads as ``ph := ( ps -> ph )``: an
        # implication has the same shape as a biconditional, and `ph` is
        # "notation not yet in use" the first time it is seen. Found by running
        # the classifier over `set.mm` rather than by reasoning about it.
        return Classified(
            assertion.label,
            reason=f"defined side is a bare metavariable ({defined})",
        )

    head = higher.constructor.name
    if head in in_use:
        return Classified(
            assertion.label,
            reason=f"defined side is built from notation already in use ({head})",
        )

    if head in constructors_used(lower):
        # A recursive alias, not an eliminable definition. `in_use` cannot catch
        # this: it holds what *earlier* assertions used, and the defining form is
        # part of this one. The builder does now refuse it
        # (`declarative._require_a_non_circular_definition`), and catches the
        # mutual case this test cannot see - but it refuses by *raising*, which
        # aborts the import. Kept here for the same reason as the binding-slot
        # wall above: doubt costs an axiom, not a build.
        return Classified(
            assertion.label,
            reason=f"defining side is built from the form being defined ({head})",
        )

    justification = _justification(assertion, database)
    if isinstance(justification, str):
        return Classified(assertion.label, reason=justification)

    if _proviso_safe_names(assertion):
        # A metavariable the proviso syntax cannot name (set.mm's `.,`). The
        # promotion path renames it, but a rename would have to reach the defined
        # and defining forms too, which are rendered from the parsed term.
        return Classified(
            assertion.label,
            reason="a metavariable cannot be named in a proviso",
        )

    variables = {h.variable for h in assertion.floatings}
    supplied = variables_used(higher, variables)

    # A leaf sitting in a *binder* slot is bound, not introduced. Which slots bind
    # is the grammar's to say (`Production.scopes_over`, declared per database by
    # the importer's caller), and `bind_scoped` is what reads it off a parsed
    # defining form - the very call `parse_definition` makes to infer the `fresh`
    # clause. Asking it here rather than re-deriving the scopes keeps the two
    # answers one answer: what this admits is what registration will accept.
    #
    # Silent on a grammar declaring no binding slots, which is what a `.mm` file
    # says on its own, so an import that declares none classifies exactly as it did
    # before they existed.
    try:
        bound, placed = bind_scoped(lower, 0)
    except ValueError as exc:
        # A defining form two of whose *sibling* binder slots hold the same leaf.
        # The kernel refuses it rather than resolving by declaration order, and
        # rightly - neither slot shadows the other, so an occurrence in the scope
        # they share belongs to neither. But it refuses by raising, and this is the
        # module that must not: an assertion no definition can be made of is an
        # axiom, not a reason to abandon the corpus.
        return Classified(assertion.label, reason=f"binders cannot be placed: {exc}")

    introduced = sorted(variables_used(bound, variables) - supplied)
    if introduced:
        # A variable the defining form uses, the defined form does not supply, and
        # no binder of the defining form binds. The unfold would conjure it, and
        # under a binder of the same name that silently rebinds it - the capture
        # half of admissibility, which the kernel refuses
        # (`kernel.definitions.unbound_parameters`).
        listed = ", ".join(repr(name) for name in introduced)
        return Classified(
            assertion.label,
            reason=f"defining side introduces {listed}, which the defined side does not supply",
        )

    # A binder is resolvable too: an unfold settles the leaf each one takes and
    # exposes it under the binder's own name, so a proviso may constrain it
    # (`kernel.definitions._condition_binding`). Only where the name is
    # unambiguous - binders are placed per occurrence, so two of them may share a
    # spelling, and then a proviso naming it could not say which. That is the same
    # rule `declarative._check_condition_is_checkable` applies, stated here so the
    # classifier refuses what registration would.
    names = [binder.name for binder in placed]
    resolvable = supplied | {name for name in names if names.count(name) == 1}

    constrained = {v for group in assertion.distinct for v in group if v in variables}
    orphaned = sorted(constrained - resolvable)
    if orphaned:
        # A `$d` over a variable neither the defined form supplies nor a binder
        # names. Its proviso is checked against what an unfold determines, so there
        # would be nothing to resolve it against; carrying it anyway makes every
        # unfold raise, and dropping it silently widens what the definition
        # admits. Neither is faithful, so this stays an axiom.
        listed = ", ".join(repr(name) for name in orphaned)
        return Classified(
            assertion.label,
            reason=f"a $d constrains {listed}, which the defined side does not supply",
        )

    sort = statement.constructor.slot_sorts[statement.constructor.slots[0]]
    return Classified(
        assertion.label,
        definition=Definition(
            sort=sort.name,
            name=assertion.label,
            higher=defined,
            lower=lower.to_string(),
            # Only the variables the *defined* form supplies. A definition's
            # parameters are its defined form's slots — what a use of the notation
            # provides — and the rest of the `$f` variables are the defining form's
            # binders, which are a different thing and must not be declared here.
            #
            # It is not a tidiness point. A declared binding becomes a
            # *metavariable* in the context the forms are re-parsed against, so a
            # binder declared as one parses to a `Var`, and `bind_scoped` skips
            # `Var`s by design — they are parameters the defined form supplies. The
            # binder is then never placed, `unbound_parameters` reports it free,
            # and registration refuses a definition the classifier admitted. That
            # cost 242 of set.mm's 1,335 candidates before this line read this way.
            bindings=[
                (h.variable, h.typecode)
                for h in assertion.floatings
                if h.variable in supplied
            ],
            # A `$d` restricts which substitutions the definition admits, so it
            # has to travel with it: 1,033 of set.mm's definition-shaped
            # statements carry one, and
            # dropping them would licence exactly the captures Metamath forbids.
            condition="; ".join(_distinct_provisos(assertion, database, system))
            or None,
            label=assertion.label,
            justification=justification,
        ),
    )
