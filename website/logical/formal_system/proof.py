"""The :class:`Proof` and its :class:`ProofLine` members."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..graphs import saturating_matching
from ..kernel.side_conditions import Not, Occurs
from ..kernel.terms import from_match
from ..matching import Match
from .definitions import follows_by_definition

if TYPE_CHECKING:
    from ..matching.context import Context
    from ..matching.definitions import Definition
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

# The justification keyword for a definitional step: a line cited as
# `[Def, <line>]` claims to be the cited line with one definition unfolded (or
# folded) at a single position. The checker searches the definitions in scope
# for one that relates the two lines (the elaboration-layer role the kernel
# leaves open - see kernel.definitions). An inference rule of the same label
# still wins, since rules are resolved first, so a system is free to repurpose
# the keyword.
DEFINITION_KEY = "Def"


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
                    and line.formula is not None:
                return line
        return None

    @property
    def eigenvariable(self) -> Match | None:
        # The fresh variable a "variable" subproof introduces (its opener's
        # formula match), or None for other kinds.
        if self.kind != "variable" or self.assumption is None:
            return None
        return self.assumption.formula

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
        eigenvariable = self.eigenvariable
        if eigenvariable is None:
            return False

        eigenvariable_term = from_match(eigenvariable, context)
        fresh = Not(Occurs("eigenvariable", "hypothesis"))

        for assumption in self.enclosing_assumptions():
            if assumption.formula is None:
                continue

            binding = {
                "eigenvariable": eigenvariable_term,
                "hypothesis": from_match(assumption.formula, context),
            }
            if not fresh.check(binding, context):
                return False

        return True


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
    inference rule (optionally with antecedent lines and a variable mapping).
    """

    inference_rule: object
    key: str
    antecedents: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)


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

        # The proof model id
        self.model_id = None

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

    def logical_lines(self):
        # Count the logical lines in the proof
        return len([
            line for line in self.proof_lines
            if (not line.empty) and (line.line_type is not None) and line.line_type.behaviour == "logical"
        ])

    def _resolve_antecedents(
        self, refs: list[str], context: Context
    ) -> tuple[list[ProofLine], dict]:
        # Resolve the cited-line refs following a rule/theorem label into the
        # antecedent lines (and any reference mapping). Shared by the inference-
        # rule and promoted-theorem branches of get_reference. A ref that does not
        # resolve to a proof line (nor a mapping on the previous one) is an error.
        antecedents: list[ProofLine] = []
        mapping: dict = {}
        last_proof_line: ProofLine | None = None
        for r in refs:
            try:
                item = self.get_reference(r, context)

                if isinstance(item, ProofLine):
                    antecedents.append(item)
                    last_proof_line = item
                    continue

            except Exception:
                # Not a line reference; it may be a mapping on the previous line.
                try:
                    if last_proof_line is not None:
                        mapping.update(self.get_reference_mapping(r, last_proof_line, context))
                        continue

                except Exception:
                    pass

            # Otherwise this is not a proof line
            raise Exception(f"{r} is not a proof line.")

        return antecedents, mapping

    def get_reference(self, ref, context):
        # Get the referenced line from a ref string

        # Check if it's reference to another line
        if ref in self.reference_context:
            return self.reference_context[ref]

        for ir in self.formal_system.inference_rules:
            # Compare against the ir label and formatted label
            if ref == ir.label:
                return InferenceReference(inference_rule=ir, key=ref)

        # A zero-premise proved/imported theorem cited by its label alone. The
        # ephemeral rule is built per citation (see promotion) rather than kept
        # among the system's primitive rules.
        promoted = self.formal_system.promoted_theorems.get(ref)
        if promoted is not None:
            return InferenceReference(inference_rule=promoted.as_rule(), key=ref)

        if ", " in ref:
            # Split the ref into parts
            ref_parts = ref.split(", ")
            key = ref_parts[0]

            for ir in self.formal_system.inference_rules:
                if key == ir.label:
                    # It's an inference rule
                    antecedents, mapping = self._resolve_antecedents(ref_parts[1:], context)
                    return InferenceReference(
                        inference_rule=ir, key=key, antecedents=antecedents, mapping=mapping
                    )

            # A proved/imported theorem applied to cited premises, `[<Thm>, i, ...]`.
            # Resolved exactly like a rule - its schematic statement is
            # re-instantiated against the premises and goal by unification, and its
            # `$d` provisos (now `disjoint` side-conditions) are enforced.
            promoted = self.formal_system.promoted_theorems.get(key)
            if promoted is not None:
                antecedents, mapping = self._resolve_antecedents(ref_parts[1:], context)
                return InferenceReference(
                    inference_rule=promoted.as_rule(), key=key, antecedents=antecedents, mapping=mapping
                )

            # A definitional step: `[<name>, <line>]` cites a named definition,
            # or `[Def, <line>]` leaves the applicable definition to be searched
            # for. Either way it cites exactly one source line.
            named = self._definition_by_label(key, context)
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

    @staticmethod
    def get_reference_mapping(ref, source_proof_line, context):
        # Get the mapping on a proof line with reference to the source proof line.

        if " mapsto " not in ref:
            return {}

        # The `<source> mapsto <target>` reference-mapping syntax resolved
        # `source` to a pattern through the get_by_path interpreter, now retired.
        # It was unused (no proof in the corpus contains `mapsto`). Raising here
        # is caught by the reference-resolution fallback in the caller, so the
        # net effect is that a `mapsto` reference no longer resolves - the citing
        # line's reference stays unresolved and the line fails to justify. That
        # is the right outcome for an unsupported syntax; a typed reference
        # mechanism would reintroduce it deliberately.
        raise Exception("Reference mapping ('<source> mapsto <target>') is no longer supported.")

    def check_logical_line(self, proof_line, context):
        # Check if the given proof line is valid.

        if proof_line.proof is not self:
            # Can't check a line outside the proof
            return False

        if proof_line.is_axiom:
            # Easy case
            return True

        if proof_line.formula is None:
            # No formula
            proof_line.valid = False
            proof_line.invalid_message = "No formula defined for logical line."
            return False

        # Get the reference
        try:
            reference = self.get_reference(proof_line.reference_string, context)
        except Exception as e:
            proof_line.invalid_message = str(e)
            proof_line.valid = False
            return False

        # A definitional step: this line is the cited line with one definition
        # unfolded/folded at a single position, checked over kernel terms.
        if isinstance(reference, DefinitionReference):
            return self.check_definitional_line(proof_line, reference, context)

        if not isinstance(reference, InferenceReference):
            proof_line.invalid_message = f"Invalid reference '{proof_line.reference_string}'."
            proof_line.valid = False
            return False

        # Otherwise, it's an inference rule

        inference_rule = reference.inference_rule
        key = reference.key
        proof_line.reference_mapping = reference.mapping

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
                return False

        if len(antecedents) == 0 and len(inference_rule.antecedents) == 0:
            # No antecedents for this inference rule
            if inference_rule.check(
                    antecedents=(),
                    extra_antecedents=(),
                    deduction=proof_line,
                    context=context
            ):
                # It's a valid line
                return True

        elif len(antecedents) == 0 and len(inference_rule.antecedents) < 5:
            # Antecedents not provided. Try to justify:
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
            return False

        if len(antecedents) > len(inference_rule.antecedents) and not inference_rule.allow_extra_antecedents:
            # Too many antecedents
            proof_line.valid = False
            proof_line.invalid_message = f"{key} requires exactly {len(inference_rule.antecedents)!s} antecedent(s)."
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

        # No admissible, consistent assignment: not a valid line.
        proof_line.valid = False
        proof_line.invalid_message = f"{key} does not apply."
        return False

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
        adjacency = {
            slot: [j for j, line in enumerate(lines) if inference_rule.slot_admits(slot, line, context)]
            for slot in range(required)
        }

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
            return False

        opener = openers[0]
        subproof = opener.opened_scope

        if subproof is None:
            proof_line.valid = False
            proof_line.invalid_message = f"Line {opener.number} does not open a subproof."
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
            return False

        if inference_rule.check_discharge(subproof, proof_line, context):
            proof_line.inference_rule = inference_rule
            return True

        proof_line.valid = False
        proof_line.invalid_message = f"{key} does not apply."
        return False

    @staticmethod
    def _definition_by_label(label: str, context: Context) -> "Definition | None":
        # The definition in scope cited by this label, or None. Used to resolve a
        # `[<name>, <line>]` citation to the specific named definition.
        for definition in context.definitions:
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
            return False

        # A step in the same proof must come after the line it transforms.
        if source.proof is proof_line.proof and proof_line.index() <= source.index():
            proof_line.valid = False
            proof_line.invalid_message = f"{reference.key} must cite an earlier line."
            return False

        # The cited line must be a formula-bearing logical line: a definitional
        # step transforms one formula into another. Guard here so an unparsed or
        # non-logical citation is a clean invalid line, not an AttributeError
        # inside follows_from_definition (which dereferences line_type.behaviour).
        if source.line_type is None or source.line_type.behaviour != "logical" \
                or source.formula is None:
            proof_line.valid = False
            proof_line.invalid_message = f"Line {source.number} is not a formula line."
            return False

        candidates = [reference.definition] if reference.definition is not None \
            else list(context.definitions)

        for definition in candidates:
            if proof_line.follows_from_definition(source, definition, context):
                proof_line.valid = True
                proof_line.antecedents = (source,)
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

        # A reference mapping given on the line
        self.reference_mapping = {}

        # The label for this line (if any)
        self.label = label

        # The number a citation names this line by, assigned during parsing.
        # None for a line no citation can reach: a blank line or commentary.
        self.number = None

        # The formula match (if any) on this line
        self.formula = None

        # The LineType used for this line
        self.line_type = None

        # The match with the line type pattern
        self.match = None

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

        # Whether this step in the proof is valid
        self.valid = True

        # Later proof lines that depend (directly) on this one
        self.dependent_lines = set()

        # Invalid message
        self.invalid_message = None

        # Warning message
        self.warning_message = None

        # Line may be empty
        self.empty = len(self.text) == 0

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
                self.valid = True
            else:
                # Logical lines for parsing
                self.proof.check_logical_line(self, context)

        elif line_type.behaviour == "axiom":
            # An axiom line asserts its own formula, so it needs no justification:
            # `check_logical_line` short-circuits on `is_axiom`. It used to also
            # generalise the formula into a reusable schema
            # (`Match.create_pattern`), but nothing ever read the result - a
            # promoted theorem is the typed mechanism for that now (see
            # `promotion.PromotedTheorem`).
            self.is_axiom = True

        elif line_type.behaviour == "comment":
            # Don't need to do anything :)
            pass

    def index(self):
        # Get the index of this line in the proof
        return self.proof.proof_lines.index(self)

    def follows_from_definition(self, other, definition, context):
        # Check if this proof line follows from the other by means of a definition:
        # one structural unfold over the shared-DAG term representation, checked in
        # either direction, with no re-parsing (see formal_system/definitions.py).

        if (not self.line_type.behaviour == "logical") or (not other.line_type.behaviour == "logical"):
            # Must be logical lines
            return False

        if self.formula is None or other.formula is None:
            return False

        return follows_by_definition(self.formula, other.formula, definition, context)

    def data(self):
        # Get data for this proof line
        return {
            "valid": self.valid,
            "number": self.number,
            "behaviour": self.line_type.behaviour if self.line_type is not None else None,
            "name": self.line_type.name if self.line_type is not None else None,
            "invalid_message": self.invalid_message,
            "warning_message": self.warning_message,
            "reference": self.reference_string_display,
            "label": self.label,
            "display": self.display,
            "indent": self.indent
        }

    def __str__(self):
        return f"ProofLine: {self.text}"
