"""The :class:`Proof` and its :class:`ProofLine` members."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..graphs import saturating_matching
from ..kernel.definitions import check_definitional_step
from ..kernel.side_conditions import Not, Occurs
from .diagnostics import Failure, numbers

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..kernel.definitions import Definition
    from ..kernel.terms import Term
    from ..matching.context import Context
    from .diagnostics import FailureCode, SlotReport
    from .rules import InferenceRule


# Generous upper bound on how many antecedents a single line may cite. The
# assignment search is pruned and fast-rejected (see Proof._first_valid_assignment),
# so this is only a guard against a pathological citation, not the old factorial
# permutation limit.
#
# It was 16, on the reasoning that no real proof approaches it. Real proofs do:
# 437 of set.mm's assertions take more than 16 essential hypotheses, so a proof
# applying one cites more than 16 lines, and the largest (`aks6d1c2lem3`) takes
# 35. A citation that big is still cheap here, because a proof imported from
# Metamath cites in the rule's own hypothesis order, so the first assignment the
# search tries is the one that works.
MAX_CITED_ANTECEDENTS = 64

# How many binding assignments a *diagnosis* will enumerate before giving up on
# naming the proviso that blocked (see `Proof._binding_assignments`). A failed
# citation with many admissible orderings is exactly where the search is
# expensive, and this runs after the line has already failed — a slower, sharper
# answer is worth having, an unbounded one is not.
_EXPLAINED_ASSIGNMENTS = 8

# The justification keyword for a definitional step: a line cited as
# `[Def, <line>]` claims to be the cited line with one definition unfolded (or
# folded) at a single position. The checker searches the definitions in scope
# for one that relates the two lines (the elaboration-layer role the kernel
# leaves open - see kernel.definitions). An inference rule of the same label
# still wins, since rules are resolved first, so a system is free to repurpose
# the keyword.
DEFINITION_KEY = "Def"

# The justification keyword for an **open goal**: a line cited `[?]` states a
# formula it does not claim to have proved. Later lines may cite it and check
# against it — that is what makes a proof writable top-down — and the proof as a
# whole stays invalid until it is filled, so nothing is claimed on its strength
# (see docs/authoring-and-ingestion-roadmap.md §8).
#
# A keyword rather than a line type, following `DEFINITION_KEY`: an inference rule
# of the same label still wins, since rules are resolved first, so a system is free
# to repurpose it. The one thing a hole inherits from the grammar is that the
# system's *reference part* must admit these characters — the Metamath importer's
# `_REFERENCE_REGEX` is widened for it, and a hand-authored system declares its own.
HOLE_KEY = "?"

# What separates a citation's parts: `[MP, 4, 6]` is the rule `MP` applied to
# lines 4 and 6. A constant because two places need to agree about it — the
# reader below, and `citation_text`, which composes one from a rule and some line
# numbers so a caller need not know a system's citation syntax to write one.
CITATION_SEPARATOR = ", "


def citation_text(rule: str, antecedents: Sequence[int] = ()) -> str:
    """The citation text a rule applied to some lines is written as.

    ``citation_text("MP", [4, 6])`` is ``"MP, 4, 6"`` — the *reference* only, not
    the brackets around it, which belong to the line type's shape.

    Trivial, and it exists so a caller proposing a justification *structurally*
    never has to know a system's citation syntax: a label and some integers are
    already unambiguous, and making a client format them is exactly where a
    projection creeps back into a structured path. A free function rather than a
    `FormalSystem` method because it needs no grammar — which matters, since a
    caller that wanted only this would otherwise have to build one.
    """
    return CITATION_SEPARATOR.join([rule, *(str(n) for n in antecedents)])


class Subproof:
    """A scoped block of a proof, opened by a scope line and closed by dedent.

    Subproofs are the unit of natural-deduction discharge. A subproof opened by
    an assumption line (``kind == "assumption"``) is what conditional proof and
    reductio discharge; one opened by a fresh-variable line
    (``kind == "variable"``) is what universal generalisation discharges.

    Only ``scope``-declaring line types create these, so systems that use none
    keep a single root subproof and are wholly unaffected. The root has no
    opener (``assumption is None``) and ``open_indent == -1`` so it is never
    closed.
    """

    def __init__(
        self,
        parent: Subproof | None = None,
        opener: ProofLine | None = None,
        kind: str | None = None,
        open_indent: int = -1,
    ) -> None:

        # The enclosing subproof (None for the proof root).
        self.parent = parent

        # The line that opened this subproof - a hypothesis for an "assumption"
        # scope, a fresh-variable declaration for a "variable" scope.
        self.assumption = opener

        # "assumption", "variable", or None for the root.
        self.kind = kind

        # The indentation of the opener; lines indented further belong here.
        self.open_indent = open_indent

        # The lines directly in this subproof (opener first), and nested subproofs.
        self.lines: list[ProofLine] = []
        self.children: list[Subproof] = []

    @property
    def conclusion(self) -> ProofLine | None:
        # The subproof's result: its last formula-bearing logical line.
        for line in reversed(self.lines):
            if line.line_type is not None and line.line_type.behaviour == "logical" \
                    and line.formula_term is not None:
                return line
        return None

    @property
    def eigenvariable(self) -> Term | None:
        # The fresh variable a "variable" subproof introduces (its opener's
        # formula term), or None for other kinds.
        if self.kind != "variable" or self.assumption is None:
            return None
        return self.assumption.formula_term

    def is_ancestor_of(self, other: Subproof | None) -> bool:
        # Whether this subproof encloses `other` (reflexively).
        scope = other
        while scope is not None:
            if scope is self:
                return True
            scope = scope.parent
        return False

    def enclosing_assumptions(self) -> list[ProofLine]:
        # Every hypothesis still in force around this subproof: the opening
        # assumptions of this scope and all its ancestors. These are what an
        # eigenvariable must stay clear of.
        assumptions: list[ProofLine] = []
        scope: Subproof | None = self
        while scope is not None:
            if scope.kind == "assumption" and scope.assumption is not None:
                assumptions.append(scope.assumption)
            scope = scope.parent
        return assumptions

    def eigenvariable_is_fresh(self, context: Context) -> bool:
        # Freshness for universal generalisation: the eigenvariable must not
        # occur in any hypothesis still in force around this subproof. Checked
        # structurally on kernel terms via the closed side-condition algebra
        # (kernel.side_conditions) - the graph representation, not strings. This
        # is the algebra's own worked example: Not(Occurs("x", "phi")).
        eigenvariable_term = self.eigenvariable
        if eigenvariable_term is None:
            return False

        fresh = Not(Occurs("eigenvariable", "hypothesis"))

        for assumption in self.enclosing_assumptions():
            if assumption.formula_term is None:
                continue

            binding = {
                "eigenvariable": eigenvariable_term,
                "hypothesis": assumption.formula_term,
            }
            if not fresh.check(binding, context):
                return False

        return True


def _proof_lines(items: Iterable[object]) -> list[ProofLine]:
    # The proof lines among a resolved citation's antecedents. A reference may
    # resolve to other things (a whole proof, a folder), which a diagnosis has
    # nothing to say about and must not trip over.
    return [item for item in items if isinstance(item, ProofLine)]


def line_is_accessible(citing_line: ProofLine, cited_line: ProofLine) -> bool:
    # A line may cite another only if the cited line lives in the citing line's
    # own subproof or an enclosing one - never inside a closed sibling subproof.
    # This is the natural-deduction reiteration restriction, and it is what
    # makes discharge sound. With no subproofs every line is in the root scope,
    # so this is always True and legacy systems are unaffected.

    # A cited line from a *different* proof is an imported result: its
    # admissibility is settled by import validation, not by this proof's scope
    # tree (the two proofs have unrelated scope roots). Ordinary cross-proof
    # citation is already guarded by the antecedent-ordering check in
    # InferenceRule.check, so scope restriction simply does not apply here.
    if cited_line.proof is not citing_line.proof:
        return True

    cited_scope = cited_line.scope
    citing_scope = citing_line.scope

    if cited_scope is None or citing_scope is None:
        return True

    return cited_scope.is_ancestor_of(citing_scope)


@dataclass(eq=False)
class InferenceReference:
    """A reference that resolves to an inference rule application.

    Returned by :meth:`Proof.get_reference` when a reference string names an
    inference rule (optionally with antecedent lines).
    """

    inference_rule: object
    key: str
    antecedents: list = field(default_factory=list)


@dataclass(eq=False)
class DefinitionReference:
    """A reference that resolves to a definitional-step justification.

    Returned by :meth:`Proof.get_reference` when a reference names a definition
    (or the generic :data:`DEFINITION_KEY` keyword) and cites the single source
    line the step unfolds from or folds to. ``definition`` is the specific named
    definition to apply, or ``None`` for the generic keyword - in which case the
    applicable definition is searched for at check time (see
    :meth:`Proof.check_definitional_line`).
    """

    key: str
    source: "ProofLine"
    definition: object = None


@dataclass(eq=False)
class HoleReference:
    """A reference that declares the line an **open goal** rather than justifying it.

    Returned by :meth:`Proof.get_reference` for :data:`HOLE_KEY`. It carries only
    the keyword because a hole cites nothing — that is what makes it a hole.
    """

    key: str


class Proof:
    """A proof in a formal system."""

    def __init__(self, formal_system, result=None):

        # The system in which this proof belongs
        self.formal_system = formal_system

        # The proof result
        self.result = result

        # Whether the proof is valid
        self.valid = None

        # Any warnings for the proof
        self.has_warnings = False

        # The proof lines leading to the result
        self.proof_lines = []

        # The subset of `proof_lines` a citation can name, in citation order, so
        # `numbered_lines[n - 1]` is the line written `n`. Kept separate from
        # `proof_lines` (which holds every physical line, blanks included) so
        # that adding a blank line or a comment never renumbers the steps below.
        self.numbered_lines = []

        # Labelled lines, plus any lemma proofs the caller pre-seeds under an
        # alias so this proof can cite them (see app/routers/proofs.py).
        self.reference_context = {}

        # The root subproof and the live scope stack, built during parsing.
        # `root_scope` stays None until the first line is assigned, so a proof
        # that never uses scopes carries no subproof machinery.
        self.root_scope = None
        self._scope_stack = None

    def assign_scope(self, proof_line: ProofLine) -> None:
        # Place a line in its subproof, opening a new one if the line is a scope
        # opener. Called in source order, so by the time a discharge line is
        # reached the subproofs it cites are already built and closed.

        line_type = proof_line.line_type

        # Commentary takes no part in the proof's structure. Skipping it here is
        # what stops an unindented note from dedenting out of the subproof it
        # sits in and silently closing it — the author would then get an
        # out-of-scope error on a line they never touched. Blank lines are
        # skipped before this point for the same reason.
        if line_type is not None and line_type.behaviour == "comment":
            return

        if self.root_scope is None:
            self.root_scope = Subproof(kind=None, open_indent=-1)
            self._scope_stack = [self.root_scope]

        stack = self._scope_stack

        # Dedenting past a subproof's opener closes it.
        while len(stack) > 1 and proof_line.indent <= stack[-1].open_indent:
            stack.pop()

        if line_type is not None and line_type.scope in ("assumption", "variable"):
            sub = Subproof(
                parent=stack[-1],
                opener=proof_line,
                kind=line_type.scope,
                open_indent=proof_line.indent,
            )
            stack[-1].children.append(sub)
            proof_line.opened_scope = sub
            proof_line.scope = sub
            sub.lines.append(proof_line)
            stack.append(sub)
        else:
            proof_line.scope = stack[-1]
            stack[-1].lines.append(proof_line)

    def get_proof_line(self, line_number):
        # Get a proof line by citation number (1-based, as written in proofs).
        # Not a text-line index: blank lines and commentary carry no number.
        if not 1 <= line_number <= len(self.numbered_lines):
            return None

        return self.numbered_lines[line_number - 1]

    def assign_line_number(self, proof_line: ProofLine) -> None:
        # Give the line the number a citation names it by. Called in source
        # order once the line's type is known.
        #
        # Commentary is skipped: it asserts nothing, so nothing can cite it, and
        # leaving it unnumbered is what makes prose free to insert. A line that
        # matched no line type is still numbered - the author meant it as a step,
        # and renumbering everything below a typo would be worse than the typo.
        line_type = proof_line.line_type
        if line_type is not None and line_type.behaviour == "comment":
            return

        self.numbered_lines.append(proof_line)
        proof_line.number = len(self.numbered_lines)

    def add_proof_line(self, text, context):
        proof_line = ProofLine(self, text, context=copy(context))
        self.proof_lines.append(proof_line)
        return proof_line

    def indicator(self):
        # Get the indicator level
        if not self.valid:
            return "error"

        if self.has_warnings:
            return "warning"

        return "ok"

    def data(self):
        # Get data for this proof
        return {
            "indicator": self.indicator(),
            "lines": [line.data() for line in self.proof_lines]
        }

    @property
    def holes(self) -> list[ProofLine]:
        """The lines stated as open goals rather than proved (`HOLE_KEY`).

        What a caller needs to tell an *unfinished* proof from a wrong one: both
        report `valid = False`, and only this says which. A proof with holes and no
        other failure is one whose shape checks and whose remaining work is
        enumerated here.
        """
        return [
            line
            for line in self.proof_lines
            if line.failure is not None and line.failure.code == "hole"
        ]

    @property
    def only_holes(self) -> bool:
        """Whether every failing line is an open goal.

        The predicate a top-down author (or an elaboration loop) works against:
        true means nothing is *wrong*, there is just work left. False with holes
        present means both, and the errors are the ones to fix first — filling a
        goal beneath a broken step proves nothing.
        """
        failing = [line for line in self.proof_lines if not line.valid]
        return bool(failing) and all(
            line.failure is not None and line.failure.code == "hole"
            for line in failing
        )

    def logical_lines(self):
        # Count the logical lines in the proof
        return len([
            line for line in self.proof_lines
            if (not line.empty) and (line.line_type is not None) and line.line_type.behaviour == "logical"
        ])

    def _resolve_antecedents(self, refs: list[str], context: Context) -> list[ProofLine]:
        # Resolve the cited-line refs following a rule/theorem label into the
        # antecedent lines. Shared by the inference-rule and promoted-theorem
        # branches of get_reference. A ref that does not resolve to a proof line
        # is an error.
        antecedents: list[ProofLine] = []
        for r in refs:
            try:
                item = self.get_reference(r, context)
            except Exception:
                raise Exception(f"{r} is not a proof line.") from None

            if not isinstance(item, ProofLine):
                raise Exception(f"{r} is not a proof line.")

            antecedents.append(item)

        return antecedents

    def get_reference(self, ref, context):
        # Get the referenced line from a ref string

        # Check if it's reference to another line
        if ref in self.reference_context:
            return self.reference_context[ref]

        rule = self.formal_system.rule_by_label(ref)
        if rule is not None:
            return InferenceReference(inference_rule=rule, key=ref)

        # A zero-premise proved/imported theorem cited by its label alone. The
        # ephemeral rule is built per citation (see promotion) rather than kept
        # among the system's primitive rules.
        promoted = self.formal_system.promoted_theorems.get(ref)
        if promoted is not None:
            return InferenceReference(inference_rule=promoted.as_rule(), key=ref)

        # An open goal. After the rule and theorem lookups, so a system that names
        # something `?` keeps its own meaning — the same precedence `Def` has.
        if ref == HOLE_KEY:
            return HoleReference(key=ref)

        if CITATION_SEPARATOR in ref:
            # Split the ref into parts
            ref_parts = ref.split(CITATION_SEPARATOR)
            key = ref_parts[0]

            rule = self.formal_system.rule_by_label(key)
            if rule is not None:
                antecedents = self._resolve_antecedents(ref_parts[1:], context)
                return InferenceReference(inference_rule=rule, key=key, antecedents=antecedents)

            # A proved/imported theorem applied to cited premises, `[<Thm>, i, ...]`.
            # Resolved exactly like a rule - its schematic statement is
            # re-instantiated against the premises and goal by unification, and its
            # `$d` provisos (now `disjoint` side-conditions) are enforced.
            promoted = self.formal_system.promoted_theorems.get(key)
            if promoted is not None:
                antecedents = self._resolve_antecedents(ref_parts[1:], context)
                return InferenceReference(
                    inference_rule=promoted.as_rule(), key=key, antecedents=antecedents
                )

            # A definitional step: `[<name>, <line>]` cites a named definition,
            # or `[Def, <line>]` leaves the applicable definition to be searched
            # for. Either way it cites exactly one source line.
            named = self._definition_by_label(key)
            if named is not None or key == DEFINITION_KEY:
                sources = [
                    item for r in ref_parts[1:]
                    if isinstance(item := self.get_reference(r, context), ProofLine)
                ]
                if len(sources) != 1:
                    raise Exception(f"{key} requires exactly one cited line.")
                return DefinitionReference(key=key, source=sources[0], definition=named)

            raise Exception(f"'{key}' is not a valid inference rule or definition.")

        if "." in ref:
            index = ref.index(".")
            proof_ref = ref[:index]
            remainder = ref[index + 1:]

            item = self.get_reference(proof_ref, context)

            if isinstance(item, str):
                # This is an error string
                raise Exception(item)

            if isinstance(item, Proof):
                return item.get_reference(remainder, context)

            elif hasattr(item, "get_reference"):
                # Item has a get reference method (probably a folder!)
                return item.get_reference(remainder, context)

        # Check if it's a line number
        try:
            return self.get_proof_line(int(ref))
        except ValueError:
            pass

        # Nothing works
        raise Exception(f"Invalid reference: {ref}")

    def check_logical_line(self, proof_line, context):
        # Check if the given proof line is valid.

        if proof_line.proof is not self:
            # Can't check a line outside the proof
            return False

        if proof_line.is_axiom:
            # Easy case
            return True

        if proof_line.formula_term is None:
            # No formula. Parsing may already have said something more specific -
            # that the formula was there but could not be projected into a term
            # (see FormalSystem.parse) - so don't flatten that to the generic
            # message.
            proof_line.valid = False
            if proof_line.invalid_message is None:
                proof_line.invalid_message = "No formula defined for logical line."
            proof_line.fail("no-formula")
            return False

        # Get the reference
        try:
            reference = self.get_reference(proof_line.reference_string, context)
        except Exception as e:
            proof_line.invalid_message = str(e)
            proof_line.valid = False
            proof_line.fail("bad-reference", reference=proof_line.reference_string)
            return False

        # A definitional step: this line is the cited line with one definition
        # unfolded/folded at a single position, checked over kernel terms.
        if isinstance(reference, DefinitionReference):
            return self.check_definitional_line(proof_line, reference, context)

        # An open goal: stated, not proved. Invalid, so `proof.valid` is False and
        # everything gated on validity (promotion above all) refuses it for free;
        # the code is what lets a *reader* tell an unfinished step from a wrong one.
        if isinstance(reference, HoleReference):
            proof_line.valid = False
            proof_line.invalid_message = "Open goal: this line is stated but not proved."
            proof_line.fail("hole")
            return False

        if not isinstance(reference, InferenceReference):
            proof_line.invalid_message = f"Invalid reference '{proof_line.reference_string}'."
            proof_line.valid = False
            proof_line.fail("bad-reference", reference=proof_line.reference_string)
            return False

        # Otherwise, it's an inference rule

        inference_rule = reference.inference_rule
        key = reference.key

        # Get the antecedent lines
        antecedents = reference.antecedents

        # A discharge rule consumes a whole subproof (cited by its opening
        # line) rather than individual antecedent lines.
        if inference_rule.is_discharge:
            return self.check_discharge_line(proof_line, reference, inference_rule, key, context)

        # An ordinary rule may only cite lines that are in scope: its own
        # subproof or an enclosing one, never inside a closed sibling. This is
        # the reiteration restriction that makes discharge sound.
        for ant in antecedents:
            if isinstance(ant, ProofLine) and not line_is_accessible(proof_line, ant):
                proof_line.valid = False
                proof_line.invalid_message = (
                    f"Line {ant.number} is out of scope "
                    "(it is inside a closed subproof)."
                )
                proof_line.fail("out-of-scope", rule=key, lines=numbers([ant]))
                return False

        if len(antecedents) == 0 and len(inference_rule.antecedents) == 0:
            # No antecedents for this inference rule
            if inference_rule.check(
                    antecedents=(),
                    extra_antecedents=(),
                    deduction=proof_line,
                    context=context
            ):
                # Record the rule as every other justifying branch does, so a
                # zero-premise step is not the one kind of line whose
                # justification is left unattributed.
                proof_line.inference_rule = inference_rule
                return True

        elif (
            len(antecedents) == 0
            and len(inference_rule.antecedents) <= MAX_CITED_ANTECEDENTS
        ):
            # Antecedents not provided. Try to justify from the lines above.
            #
            # Bounded by the same constant the explicit path uses, not by an arity
            # of its own: the old `< 5` was the permutation guard the assignment
            # search retired (see `MAX_CITED_ANTECEDENTS` below), left behind when
            # it was replaced. What it cost was a lie rather than only a
            # restriction — a five-premise rule cited with none was told it
            # "requires 5 antecedent(s)", which reads as too few given when in
            # fact the checker declined to look. `set.mm` reaches it: `cbv2`'s
            # step 6 cites the five lines immediately above it, which is exactly
            # what this branch infers.
            return self.justify(
                deduction=proof_line,
                context=context,
                inference_rule=inference_rule
            )

        # Otherwise, check the number of antecedents given
        if len(antecedents) < len(inference_rule.antecedents):
            # Not enough antecedents
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires {len(inference_rule.antecedents)!s} antecedent(s)."
            cited = _proof_lines(antecedents)
            proof_line.fail(
                "antecedent-count",
                rule=key,
                expected=len(inference_rule.antecedents),
                given=len(antecedents),
                # Which slots the lines they *did* cite could fill, so an author
                # short of a premise is told which one is missing rather than only
                # that a count is wrong.
                slots=inference_rule.slot_reports(
                    cited, inference_rule.admissibility(cited, context)
                ),
            )
            return False

        if len(antecedents) > len(inference_rule.antecedents) and not inference_rule.allow_extra_antecedents:
            # Too many antecedents
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires exactly {len(inference_rule.antecedents)!s} antecedent(s)."
            proof_line.fail(
                "antecedent-count",
                rule=key,
                expected=len(inference_rule.antecedents),
                given=len(antecedents),
            )
            return False

        if len(antecedents) > MAX_CITED_ANTECEDENTS:
            # The assignment search below is bipartite-fast-rejected and pruned,
            # not factorial, so this is no longer the tight "> 6" permutation
            # guard - just a generous sanity bound that keeps a pathological
            # citation (many mutually-admissible lines under an extra-antecedent
            # rule) from driving a large search. A real citation never approaches
            # it, and exceeding it is a graceful invalid line, not a server error.
            proof_line.valid = False
            proof_line.invalid_message = (
                f"{key} cites too many antecedents ({len(antecedents)}; max {MAX_CITED_ANTECEDENTS})."
            )
            proof_line.fail(
                "too-many-antecedents",
                rule=key,
                expected=MAX_CITED_ANTECEDENTS,
                given=len(antecedents),
            )
            return False

        # Assign the cited lines to the rule's antecedent slots (see
        # _first_valid_assignment): bipartite matching rejects a citation that
        # cannot fill every slot and prunes the search to admissible orderings,
        # replacing the old permutation-of-all-antecedents sweep. Any line left
        # over is an extra antecedent, allowed only when the rule permits them.
        assignment = self._first_valid_assignment(
            inference_rule, list(antecedents), proof_line, context
        )
        if assignment is not None:
            proof_line.antecedents, proof_line.extra_antecedents = assignment
            proof_line.inference_rule = inference_rule
            return True

        # No admissible, consistent assignment: not a valid line. What *kind* of
        # "does not apply" it was is worked out here, on the failure path only, so
        # a corpus whose proofs all check pays nothing for it.
        proof_line.valid = False
        proof_line.invalid_message = f"{key} does not apply."
        self._explain_assignment(proof_line, inference_rule, list(antecedents), key, context)
        return False

    def _explain_assignment(
        self,
        proof_line: ProofLine,
        inference_rule: InferenceRule,
        lines: list[ProofLine],
        key: str,
        context: Context,
    ) -> None:
        # Work out which kind of "does not apply" this was, and record it. Runs
        # only after the line has already failed, so the checking path is untouched
        # and this may ask every question rather than stopping at the first.
        #
        # The order is by how actionable the answer is, not by how the check runs.
        cited = numbers(lines)

        # 1. Ordering. Cheap, unambiguous, and it explains a citation that looks
        #    perfectly well shaped: a rule may not conclude from a later line.
        for line in lines:
            if proof_line.proof is line.proof and proof_line.index() <= line.index():
                proof_line.fail("ordering", rule=key, lines=numbers([line]))
                return

        # The slot/line graph, built once: every question below is asked of it,
        # and building it is a unification per edge.
        adjacency = inference_rule.admissibility(lines, context)

        # 2. A slot no cited line can fill *on its own*. The most useful answer
        #    there is — that slot's schema is a premise this proof does not have,
        #    which is exactly the next goal for anyone working backwards.
        unsatisfied = inference_rule.unsatisfied_slots(adjacency)
        if unsatisfied:
            proof_line.fail("slot-unsatisfied", rule=key, lines=cited, slots=unsatisfied)
            return

        # 3. Every slot has candidates, so the failure is about them holding
        #    *together* — unless a proviso is what blocked. That is asked first
        #    because it is the sharper answer, and it needs an assignment that
        #    binds to be checked against; where several bind, the first that trips
        #    a proviso is reported.
        for candidate in self._binding_assignments(
            inference_rule, lines, proof_line, context, adjacency
        ):
            proviso = inference_rule.failing_proviso(candidate, proof_line, context)
            if proviso is not None:
                proof_line.fail(
                    "side-condition",
                    rule=key,
                    lines=numbers(candidate),
                    proviso=proviso,
                )
                return

        # 4. Otherwise: either no assignment to distinct lines exists, or one does
        #    and the shared metavariables will not agree across it. Both are the
        #    same advice — the citation is individually plausible and jointly not —
        #    so they share a code and the slot graph is what distinguishes them.
        proof_line.fail(
            "inconsistent-binding",
            rule=key,
            lines=cited,
            slots=inference_rule.slot_reports(lines, adjacency),
        )

    def _binding_assignments(
        self,
        inference_rule: InferenceRule,
        lines: list[ProofLine],
        deduction: ProofLine,
        context: Context,
        adjacency: dict[int, list[int]],
    ) -> list[tuple[ProofLine, ...]]:
        # Assignments of cited lines to slots that unify, ignoring provisos — the
        # candidates a side-condition could be what rejected. Diagnosis only: the
        # search in `_first_valid_assignment` stops at the first assignment that
        # passes everything, and this one keeps going past the provisos precisely
        # to find out whether they are the reason it found none.
        #
        # Bounded exactly as that search is — the same admissibility graph, the
        # same fast reject when no system of distinct representatives exists, and
        # the same prefix pruning — so it explores what that search explored and no
        # more, up to `_EXPLAINED_ASSIGNMENTS`.
        required = len(inference_rule.antecedents)
        if saturating_matching(range(required), adjacency) is None:
            return []
        found: list[tuple[ProofLine, ...]] = []

        def walk(slot: int, chosen: list[int]) -> None:
            if len(found) >= _EXPLAINED_ASSIGNMENTS:
                return
            if slot == required:
                found.append(tuple(lines[j] for j in chosen))
                return
            for j in adjacency[slot]:
                if j in chosen:
                    continue
                candidate = [*chosen, j]
                if not inference_rule.prefix_binding_exists(
                    [lines[k] for k in candidate], deduction, context
                ):
                    continue
                walk(slot + 1, candidate)

        walk(0, [])
        return found

    def _first_valid_assignment(
        self,
        inference_rule: InferenceRule,
        lines: list[ProofLine],
        deduction: ProofLine,
        context: Context,
    ) -> tuple[tuple[ProofLine, ...], tuple[ProofLine, ...]] | None:
        # Find an assignment of cited `lines` to `inference_rule`'s antecedent
        # slots for which the rule holds, or None. Returns (antecedents, extras)
        # as tuples aligned to the rule's slots.
        #
        # A slot/line bipartite graph (edge = the line is individually admissible
        # for the slot, InferenceRule.slot_admits) drives two things: if no
        # matching saturates every slot the citation cannot apply at all, so we
        # reject up front; otherwise the backtracking search only ever tries
        # admissible (slot -> line) pairs, so it explores the handful of viable
        # assignments instead of every permutation. Each complete candidate is
        # confirmed by the authoritative, binding-consistent InferenceRule.check.
        required = len(inference_rule.antecedents)
        adjacency = inference_rule.admissibility(lines, context)

        if saturating_matching(range(required), adjacency) is None:
            # Some slot has no admissible line, or no system of distinct
            # representatives exists: the rule cannot apply to this citation.
            return None

        allow_extra = inference_rule.allow_extra_antecedents

        def search(
            slot: int, chosen: list[int]
        ) -> tuple[tuple[ProofLine, ...], tuple[ProofLine, ...]] | None:
            if slot == required:
                extras = tuple(line for k, line in enumerate(lines) if k not in chosen)
                if extras and not allow_extra:
                    return None
                antecedents = tuple(lines[j] for j in chosen)
                if inference_rule.check(
                    antecedents=antecedents,
                    extra_antecedents=extras,
                    deduction=deduction,
                    context=context,
                ):
                    return antecedents, extras
                return None

            for j in adjacency[slot]:
                if j in chosen:
                    continue
                candidate = [*chosen, j]
                # Prune early: the deduction and the slots chosen so far must
                # already unify. Slots are filled in order, so `candidate` is a
                # prefix aligned to the rule's first len(candidate) slots; if it
                # cannot bind, no completion can (unification is monotone), so
                # skip the whole subtree instead of descending to a leaf check().
                # This is what keeps an all-individually-admissible but globally
                # inconsistent citation (e.g. a shared metavariable over distinct
                # formulae) from costing an ordering-factorial number of checks.
                if not inference_rule.prefix_binding_exists(
                    [lines[k] for k in candidate], deduction, context
                ):
                    continue
                result = search(slot + 1, candidate)
                if result is not None:
                    return result
            return None

        return search(0, [])

    def check_discharge_line(
        self,
        proof_line: ProofLine,
        reference: InferenceReference,
        inference_rule: InferenceRule,
        key: str,
        context: Context,
    ) -> bool:
        # Check a discharge rule: it cites exactly one subproof by its opener.

        openers = [a for a in reference.antecedents if isinstance(a, ProofLine)]

        if len(openers) != 1:
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires exactly one subproof reference."
            proof_line.fail(
                "no-subproof", rule=key, expected=1, given=len(openers)
            )
            return False

        opener = openers[0]
        subproof = opener.opened_scope

        if subproof is None:
            proof_line.valid = False
            proof_line.invalid_message = f"Line {opener.number} does not open a subproof."
            proof_line.fail("no-subproof", rule=key, lines=numbers([opener]))
            return False

        # The subproof must be a *completed* one, in scope to discharge from
        # here: enclosed by an ancestor of this line, and not still open around
        # it. Cross-scope discharge is exactly the unsoundness we are closing.
        if subproof.parent is None or not subproof.parent.is_ancestor_of(proof_line.scope) \
                or subproof.is_ancestor_of(proof_line.scope):
            proof_line.valid = False
            proof_line.invalid_message = (
                f"Subproof at line {opener.number} is out of scope to discharge here."
            )
            proof_line.fail(
                "subproof-out-of-scope", rule=key, lines=numbers([opener])
            )
            return False

        if inference_rule.check_discharge(subproof, proof_line, context):
            proof_line.inference_rule = inference_rule
            proof_line.discharged_scope = subproof
            return True

        proof_line.valid = False
        proof_line.invalid_message = f"{key} does not apply."
        proof_line.fail("discharge-mismatch", rule=key, lines=numbers([opener]))
        return False

    def _definition_by_label(self, label: str) -> Definition | None:
        # The system's definition cited by this label, or None. Used to resolve a
        # `[<name>, <line>]` citation to the specific named definition.
        for definition in self.formal_system.definitions:
            if definition.label == label:
                return definition
        return None

    def check_definitional_line(
        self, proof_line: ProofLine, reference: DefinitionReference, context: Context
    ) -> bool:
        # Check a definitional step: `proof_line` must be the cited source line
        # with one definition (in scope) unfolded or folded at a single position.
        # A named citation pins the definition; the generic keyword searches those
        # in scope - the trusted core only ever checks a step it is handed (see
        # kernel.definitions). Each candidate is verified over kernel terms by
        # ProofLine.follows_from_definition.
        source = reference.source

        # The cited line must be in scope, exactly as an inference-rule antecedent
        # would be: never inside a closed sibling subproof.
        if not line_is_accessible(proof_line, source):
            proof_line.valid = False
            proof_line.invalid_message = (
                f"Line {source.number} is out of scope (it is inside a closed subproof)."
            )
            proof_line.fail(
                "out-of-scope", rule=reference.key, lines=numbers([source])
            )
            return False

        # A step in the same proof must come after the line it transforms.
        if source.proof is proof_line.proof and proof_line.index() <= source.index():
            proof_line.valid = False
            proof_line.invalid_message = f"{reference.key} must cite an earlier line."
            proof_line.fail("ordering", rule=reference.key, lines=numbers([source]))
            return False

        # The cited line must be a formula-bearing logical line: a definitional
        # step transforms one formula into another. Guard here so an unparsed or
        # non-logical citation is a clean invalid line, not an AttributeError
        # inside follows_from_definition (which dereferences line_type.behaviour).
        if source.line_type is None or source.line_type.behaviour != "logical" \
                or source.formula_term is None:
            proof_line.valid = False
            proof_line.invalid_message = f"Line {source.number} is not a formula line."
            proof_line.fail("no-formula", rule=reference.key, lines=numbers([source]))
            return False

        candidates = [reference.definition] if reference.definition is not None \
            else list(self.formal_system.definitions)

        for definition in candidates:
            if proof_line.follows_from_definition(source, definition, context):
                proof_line.valid = True
                proof_line.antecedents = (source,)
                proof_line.applied_definition = definition
                source.dependent_lines.add(proof_line)
                return True

        proof_line.valid = False
        if reference.definition is not None:
            proof_line.invalid_message = (
                f"{reference.key} does not apply between this line and line "
                f"{source.number}."
            )
        else:
            proof_line.invalid_message = (
                f"{reference.key} does not apply: no definition in scope relates this line "
                f"to line {source.number}."
            )
        proof_line.fail(
            "definition-mismatch",
            rule=reference.key,
            lines=numbers([source]),
            # `Definition.label` is declared and may be None (an unnamed
            # definition is legal); the ones with a name are the ones a caller
            # could cite explicitly, so they are what is worth reporting.
            definitions=tuple(
                d.label for d in candidates if d is not None and d.label is not None
            ),
        )
        return False

    def justify(self, deduction, context, inference_rule=None):
        # Artificially try to find a justification for the given reference. Optionally specify a inference rule.

        if inference_rule is not None:

            logical_lines = [
                line for line in self.proof_lines[:deduction.index()]
                if line.line_type is not None and line.line_type.behaviour == "logical"
                and line_is_accessible(deduction, line)
            ][-len(inference_rule.antecedents):]

            if not len(logical_lines) == len(inference_rule.antecedents):
                # Not enough previous logical lines
                deduction.valid = False
                deduction.invalid_message = "Antecedent lines couldn't be inferred."
                deduction.fail(
                    "antecedent-count",
                    rule=inference_rule.label,
                    expected=len(inference_rule.antecedents),
                    given=len(logical_lines),
                )
                return False

            # Same admissible-assignment search as an explicit citation: the
            # inferred lines exactly fill the slots (no extras), so this just
            # finds the ordering, if any, under which the rule holds.
            assignment = self._first_valid_assignment(
                inference_rule, logical_lines, deduction, context
            )
            if assignment is not None:
                deduction.antecedents, _ = assignment
                deduction.inference_rule = inference_rule
                return True

            # Otherwise, no justification found
            deduction.valid = False
            deduction.invalid_message = f"{inference_rule.label} does not apply."
            self._explain_assignment(
                deduction, inference_rule, logical_lines, inference_rule.label, context
            )
            return False

        # Otherwise, no inference rule specified.
        return False


class ProofLine:
    """A line in a proof."""

    def __init__(self, proof, text, context, reference_string=None, label=None):

        # The proof this line belongs to
        self.proof = proof

        # The text string on this line
        self.text = text

        # The text to display on this line. By default equal to the actual text, stripped.
        self.display = text.strip()

        # A frozen context - useful to later refer to from inference rules
        self.context = context

        # The reference string for this line (if any)
        self.reference_string = reference_string
        self.reference_string_display = reference_string

        # The label for this line (if any)
        self.label = label

        # The number a citation names this line by, assigned during parsing.
        # None for a line no citation can reach: a blank line or commentary.
        self.number = None

        # The line's formula as a kernel term, projected during parsing (see
        # FormalSystem.parse). This is what every check runs on: rule
        # unification, side-conditions, definitional steps. None for a line that
        # declares no formula field, or whose field is absent from the parse.
        self.formula_term: Term | None = None

        # The formula's surface string, read by the string-rewriting path (a
        # semi-Thue system like MIU matches flat text rather than structure -
        # see InferenceRule._string_pairs). Set by the parse; *derived* from the
        # term otherwise - see the `formula_string` property below.
        self._formula_string: str | None = None
        # Memo for that derivation, and the term it was derived from. Keyed by
        # the term rather than a bare flag so a re-projected formula cannot be
        # answered from a stale render.
        self._rendered_string: str | None = None
        self._rendered_from: Term | None = None

        # The LineType used for this line
        self.line_type = None

        # The indentation of this line
        self.indent = len(self.text) - len(self.text.lstrip())

        # The subproof this line belongs to (set during parsing). Defaults to
        # None, meaning "root scope" until the parser assigns one.
        self.scope = None

        # If this line opens a subproof, the Subproof it opens (else None).
        self.opened_scope = None

        # This line may be an axiom
        self.is_axiom = False

        # The axiom this line uses (if any)
        self.axiom = None

        # The inference instance with this line as the deduction
        self.inference = None

        # The inference rule that justified this line, once one has (None while
        # unchecked, for an unjustified line, and for a definitional step).
        self.inference_rule = None

        # The definition a definitional step unfolded or folded, once one has.
        # Recorded because a generic `[Def, n]` citation names none: the checker
        # searches the definitions in scope, so which one applied is knowable
        # only here, and a reader cannot recover it from the citation text.
        self.applied_definition: Definition | None = None

        # The cited lines this line was justified from: those filling the rule's
        # declared antecedent slots, and any surplus lines an
        # `allow_extra_antecedents` rule tolerated. Declared here (rather than
        # attached ad hoc by the checker) so every line carries them and a reader
        # -- the proof-line snapshot in `app/db/proofs_mapping.py` -- can walk the
        # justification graph without probing for the attribute.
        self.antecedents: tuple[ProofLine, ...] = ()
        self.extra_antecedents: tuple[ProofLine, ...] = ()

        # The subproof a discharge rule consumed to justify this line, or None.
        # A discharge cites a *block*, not lines, so it is recorded apart from
        # `antecedents` rather than flattened into them.
        self.discharged_scope: Subproof | None = None

        # Whether this step in the proof is valid
        self.valid = True

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = set()

        # Invalid message
        self.invalid_message = None

        # Why this line is not established, as data — the same verdict
        # `invalid_message` states in a sentence, plus what the checker knew and
        # used to discard. None while the line stands. See `.diagnostics`.
        self.failure: Failure | None = None

        # Warning message
        self.warning_message = None

        # Line may be empty
        self.empty = len(self.text) == 0

    @property
    def formula_string(self) -> str | None:
        """The formula's surface string — as parsed, or rendered from the term.

        A parse records the substring it matched, and that is authoritative. A
        line rebuilt from its stored row has no substring to record, so the
        string is *rendered* from the term instead (`Term.to_string`), which is
        exact: a term renders through its constructor's template pieces, a ground
        leaf renders its own literal, and the matcher accepts no source spelling
        that differs from those. See docs/verification-from-rows.md §4.

        Derived rather than asked for, because no caller is in a position to know
        whether it will be needed. The string is read only by the string-matching
        path, and what selects that path can be an inference rule *or* a promoted
        theorem — and the library is resolved after a proof's lines are populated,
        so a load-time "does this system need strings?" question is asked before
        its answer exists. It got the answer wrong, and a proof that verified when
        parsed failed when checked from its rows.
        """
        if self._formula_string is not None:
            return self._formula_string
        if self.formula_term is None:
            return None
        # Memoised because the string path reads this *many* times per check —
        # once per slot per candidate line while the bipartite assignment graph
        # is built (`slot_admits`), then again per prefix the search tries
        # (`_string_pairs`). Measured at 8.6 reads per line on a seven-line MIU
        # proof with four rules, against the one render per line the load path
        # used to do; a structured semi-Thue grammar would pay a DAG walk each
        # time.
        if self._rendered_from is not self.formula_term:
            self._rendered_string = self.formula_term.to_string()
            self._rendered_from = self.formula_term
        return self._rendered_string

    @formula_string.setter
    def formula_string(self, value: str | None) -> None:
        self._formula_string = value
    def execute(self, context):
        # Execute this proof line in the system.

        line_type = self.line_type

        if self.label is not None:
            # Add the proof line to the proof's reference context
            self.proof.reference_context[self.label] = self

        if line_type.behaviour == "logical":
            if line_type.scope in ("assumption", "variable"):
                # A scope opener is valid by fiat: a hypothesis is granted for
                # the duration of its subproof, a fresh variable is simply
                # introduced. Neither asserts anything until a discharge rule
                # consumes the subproof, so there is nothing to justify here.
                #
                # "Nothing to justify" is not "nothing can be wrong", though: if
                # parsing already rejected the line (its formula would not
                # project), granting it anyway would hide the fault here and
                # surface it as an unexplained discharge failure further down.
                if self.invalid_message is None:
                    self.valid = True
            else:
                # Logical lines for parsing
                self.proof.check_logical_line(self, context)

        elif line_type.behaviour == "axiom":
            # An axiom line asserts its own formula, so it needs no justification:
            # `check_logical_line` short-circuits on `is_axiom`. It used to also
            # generalise the formula into a reusable schema by round-tripping the
            # match back into a pattern, but nothing ever read the result - a
            # promoted theorem is the typed mechanism for that now (see
            # `promotion.PromotedTheorem`).
            self.is_axiom = True

        elif line_type.behaviour == "comment":
            # Don't need to do anything :)
            pass

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def fail(
        self,
        code: FailureCode,
        *,
        rule: str | None = None,
        reference: str | None = None,
        lines: tuple[int, ...] = (),
        expected: int | None = None,
        given: int | None = None,
        slots: tuple[SlotReport, ...] = (),
        proviso: str | None = None,
        definitions: tuple[str, ...] = (),
    ) -> None:
        """Record *why* this line is not established, beside the sentence.

        Called wherever `invalid_message` is set, and it takes the message *from*
        that field rather than restating it — two independently written texts for
        one verdict drift, and the sentence is already the one a reader sees.

        Never overwrites. The first thing to fail is the reason, and a later,
        vaguer diagnosis (`_explain_assignment` falling through to its default)
        must not bury a sharper one that already landed.
        """
        if self.failure is not None:
            return
        self.failure = Failure(
            code=code,
            message=self.invalid_message or "",
            rule=rule,
            reference=reference,
            lines=lines,
            expected=expected,
            given=given,
            slots=slots,
            proviso=proviso,
            definitions=definitions,
        )

    def follows_from_definition(self, other, definition, context):
        # Check if this proof line follows from the other by means of a definition:
        # one structural unfold over the shared-DAG term representation, checked in
        # either direction, with no re-parsing (see formal_system/definitions.py).

        if (not self.line_type.behaviour == "logical") or (not other.line_type.behaviour == "logical"):
            # Must be logical lines
            return False

        if self.formula_term is None or other.formula_term is None:
            return False

        return check_definitional_step(
            self.formula_term, other.formula_term, definition, context
        )

    def data(self):
        # Get data for this proof line
        return {
            "valid": self.valid,
            "number": self.number,
            "behaviour": self.line_type.behaviour if self.line_type is not None else None,
            "name": self.line_type.name if self.line_type is not None else None,
            "invalid_message": self.invalid_message,
            "failure": self.failure.as_dict() if self.failure is not None else None,
            "warning_message": self.warning_message,
            "reference": self.reference_string_display,
            "label": self.label,
            "display": self.display,
            "indent": self.indent
        }

    def __str__(self):
        return f"ProofLine: {self.text}"
