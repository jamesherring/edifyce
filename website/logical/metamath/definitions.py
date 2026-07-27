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

1. The statement is a **relation between two things of one sort**: its root
   production takes exactly two slots of the same sort and yields the logical
   sort. That admits `=` and `↔` without naming either, which matters because
   the vocabulary is the imported system's, not ours.
2. Its left side is **not a bare metavariable**, which defines nothing.
3. Its left side is **built from notation not yet in use**. This is what makes it
   a *definition* rather than an equation between things that already exist, and
   it is the test that does the real work: on `set.mm` it separates the genuine
   definitions from `ax-i2m1` (``( ( i x. i ) + 1 ) = 0``), the reflexivity
   axioms (``A = A``), and - the interesting case - `df-clab`, `df-cleq` and
   `df-clel`, whose left sides are ordinary ``e.``/``=`` and which are genuinely
   axioms connecting class notation to set theory, whatever their names suggest.

Then three refusals for what a `Definition` cannot faithfully carry: a defining
form built from the very form being defined (a recursive alias, not something
eliminable), an assertion holding only under `$e` hypotheses (a definition holds
unconditionally, and there is nowhere to put a premise), and a metavariable the
proviso syntax cannot name. A `$d` *can* be carried, as the definition's
condition, and must be: 1,033 of set.mm's definition-shaped statements have one.

None of the shape tests is load-bearing alone. Test 1 admits an implication,
since `( ph -> ps )` has the shape of a biconditional; test 3 then admits `ax-1`,
because `ph` is notation not yet in use the first time it appears - which is why
test 2 is there, and which was found by running the classifier over `set.mm`
rather than by reasoning about it. Nor is the set of them trusted to be complete.

**The default on any doubt is axiom**, which costs a longer proof rather than an
unsound one. What is *behind* that default is worth stating precisely, because it
is less than it sounds: the kernel refuses a definition whose defining form
introduces a leaf the defined form does not supply - the capture half of
admissibility - and that is all. Non-circularity and conservativity are untreated
there, as in Metamath (see AGENTS.md), so the circularity refusal above has
nothing behind it and every other gap of that kind is this module's to close.

`df-bi` shows why the tests have to be structural. It defines ``<->`` and so
cannot use it: its statement is a nest of negated implications, root ``-.``, and
it falls to axiom exactly as it should.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..declarative import Definition
from ..kernel.terms import Node
from .importer import _distinct_provisos, _proviso_safe_names

if TYPE_CHECKING:
    from ..formal_system import FormalSystem
    from ..kernel.terms import Term
    from .parser import Assertion, Database


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


def classify(
    assertion: Assertion,
    statement: Term | None,
    in_use: set[str],
    database: Database,
    system: FormalSystem,
) -> Classified:
    """Decide whether ``assertion`` is a definition, given what precedes it.

    ``statement`` is the parsed statement (None if it did not parse) and
    ``in_use`` the constructor names every *earlier* logical assertion used -
    both supplied by the caller, because a walk already has them and re-deriving
    either per assertion would re-parse the corpus. ``database`` and ``system``
    are needed only to render a ``$d`` into proviso syntax.
    """
    if statement is None:
        return Classified(assertion.label, reason="statement does not parse")

    sides = _sides(statement)
    if sides is None:
        root = statement.constructor.name if isinstance(statement, Node) else "a variable"
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
        # part of this one. Nor can the kernel, which checks the capture half of
        # admissibility and leaves non-circularity untreated, as Metamath does -
        # so this is the one refusal with nothing behind it.
        return Classified(
            assertion.label,
            reason=f"defining side is built from the form being defined ({head})",
        )

    if assertion.essentials:
        # A definition holds unconditionally; a `$a` under `$e` hypotheses does
        # not. `Definition` has nowhere to put a premise, so folding one in would
        # licence unfolds the Metamath assertion forbids.
        premises = ", ".join(h.label for h in assertion.essentials)
        return Classified(
            assertion.label,
            reason=f"holds only under hypotheses ({premises})",
        )

    if _proviso_safe_names(assertion):
        # A metavariable the proviso syntax cannot name (set.mm's `.,`). The
        # promotion path renames it, but a rename would have to reach the defined
        # and defining forms too, which are rendered from the parsed term.
        return Classified(
            assertion.label,
            reason="a metavariable cannot be named in a proviso",
        )

    sort = statement.constructor.slot_sorts[statement.constructor.slots[0]]
    return Classified(
        assertion.label,
        definition=Definition(
            sort=sort.name,
            name=assertion.label,
            higher=defined,
            lower=lower.to_string(),
            bindings=[(h.variable, h.typecode) for h in assertion.floatings],
            # A `$d` restricts which substitutions the definition admits, so it
            # has to travel with it: 1,033 of set.mm's definitions carry one, and
            # dropping them would licence exactly the captures Metamath forbids.
            condition="; ".join(_distinct_provisos(assertion, database, system))
            or None,
            label=assertion.label,
        ),
    )
