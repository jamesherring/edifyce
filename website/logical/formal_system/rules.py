"""Inference rules and their applications: :class:`InferenceRule`, :class:`Inference`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel import Var, from_pattern, match_all
from ..matching import StringPattern
from ..matching.rewriting import joint_binding_exists
from .diagnostics import SlotReport, numbers
from .proof import ProofLine, Subproof

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel import SideCondition, Term
    from ..matching.context import Context
    from ..matching.patterns import Pattern

    # A rule match's substitution: schematic variable name -> the Term it binds to.
    Binding = dict[str, Term]


def statement_term(pattern: Pattern) -> Term:
    """The kernel term a schema pattern is unified as, metavariables shared.

    A compound template (a Hilbert axiom, an imported ``$p``) carries a
    precomputed *nested* term from the build; anything else projects flat, which
    is one production. Either way its named metavariables keep their names, so a
    repeated one binds consistently.

    This is the projection for a schema read *as a statement* - one occurrence,
    so nothing is renamed apart. :meth:`InferenceRule._schema_term` adds that
    renaming for a bare-sort slot appearing in several antecedents.
    """
    if isinstance(pattern, StringPattern) and pattern.schema_term is not None:
        return pattern.schema_term
    return from_pattern(pattern)


@dataclass(eq=False)
class SubproofSchema:
    """The subproof an inference rule discharges.

    A discharge rule (conditional proof, RAA, universal generalisation) does
    not cite individual lines - it consumes a whole subproof as a unit. This
    records what that subproof must look like:

    ``assumption`` - pattern the subproof's opening hypothesis must match, or
                     ``None`` when the subproof is opened by a fresh variable
                     rather than a hypothesis.
    ``conclusion`` - pattern the subproof's final line must match.
    ``fresh``      - the eigenvariable pattern for a variable-opened subproof
                     (universal generalisation), or ``None``. Its presence is
                     what makes the rule require a ``variable`` subproof rather
                     than an ``assumption`` one; the freshness side-condition is
                     enforced in :meth:`InferenceRule.check_discharge`.
    """

    conclusion: Pattern
    assumption: Pattern | None = None
    fresh: Pattern | None = None

    @property
    def kind(self) -> str:
        # Which kind of scope opener this schema discharges.
        return "variable" if self.fresh is not None else "assumption"


class InferenceRule:
    """Inference rules for deduction."""

    def __init__(
        self,
        name: str,
        label: str | None = None,
        antecedents: list[Pattern] | None = None,
        deduction: Pattern | None = None,
        side_conditions: list[SideCondition] | None = None,
        allow_extra_antecedents: bool = False,
        variables: dict[str, Pattern] | None = None,
        subproof_schema: SubproofSchema | None = None,
        matching: str = "structural",
    ) -> None:

        # The inference rule name
        self.name: str = name.replace("_", " ")

        # The inference rule label
        self.label: str = label if label is not None else ""

        # List of antecedent patterns
        self.antecedents: list[Pattern] = antecedents if antecedents is not None else []

        # Deduction pattern (set during compilation; None until then)
        self.deduction: Pattern | None = deduction

        # Kernel side-conditions (provisos) that must hold for the rule to apply,
        # checked structurally against the term binding. See side_condition_syntax.
        self.side_conditions: list[SideCondition] = (
            side_conditions if side_conditions is not None else []
        )

        # Raw proviso lines awaiting a parse. The build defers parsing to its
        # finalisation pass — once the system's definitions have resolved, so a
        # proviso argument may use defined notation — then fills `side_conditions`
        # and clears this. Empty except transiently mid-build.
        self.pending_side_conditions: list[str] = []

        # Each parsed proviso's own source line, index-aligned to
        # `side_conditions`. Kept only so a *failure* can quote the author's own
        # words: a reader wants `x not free in phi`, not the repr of a frozen
        # dataclass. Nothing checks against it, and a rule built without it (a
        # caller passing `side_conditions=` directly) simply reports the parsed
        # form instead — see `failing_proviso`.
        self.side_condition_sources: list[str] = []

        # Optionally allow extra antecedents
        self.allow_extra_antecedents: bool = allow_extra_antecedents

        # Keep a set of variables handy
        self.variables: dict[str, Pattern] | None = variables

        # The subproof this rule discharges (SubproofSchema), if it is a
        # discharge rule. None for an ordinary line-antecedent rule.
        self.subproof_schema: SubproofSchema | None = subproof_schema

        # How a step is justified against this rule's schemas:
        #   "structural" - first-order term unification (the default; logical
        #                  systems, where a variable binds a whole subterm), or
        #   "string"     - associative matching on the surface strings, for a
        #                  string-rewriting (semi-Thue) system like MIU, whose
        #                  rules split and concatenate flat strings in ways the
        #                  term unifier structurally cannot. See
        #                  ``website.logical.matching.rewriting``.
        self.matching: str = matching

    @property
    def is_discharge(self) -> bool:
        # Whether this rule discharges a subproof rather than citing lines.
        return self.subproof_schema is not None

    def check(
        self,
        antecedents: Sequence[ProofLine],
        extra_antecedents: Sequence[ProofLine],
        deduction: ProofLine,
        context: Context,
    ) -> bool:
        # Check to see if the proposed proof lines are valid under this inference rule

        # Check the number of antecedents matches
        if not len(antecedents) == len(self.antecedents):
            return False

        if type(deduction) is not ProofLine:
            # Deduction doesn't point to a valid proof line
            return False

        # Deduction must be after the antecedents
        for ant in (*antecedents, *extra_antecedents):
            if type(ant) is not ProofLine:
                # antecedent isn't a proof line
                return False

            # Deduction in the same proof must come after the antecedents
            if deduction.proof is ant.proof and deduction.index() <= ant.index():
                return False

        # Create an inference instance
        inference = Inference(self, antecedents, extra_antecedents, deduction)

        if self.matching == "string":
            # String-rewriting step: the deduction and every antecedent must
            # match their schemas as *strings* under one shared substitution,
            # found by associative matching (splitting/concatenation the term
            # unifier cannot do). No kernel side-conditions on this path.
            if not self._string_binding_exists(antecedents, deduction, context):
                return False
        else:
            # Structural check over terms (the graph representation): the
            # deduction and every logical antecedent must match their schemas
            # under one shared binding, derived by unification. The formulae are
            # already parsed, so we project them straight to terms and never
            # re-run the string matcher.
            binding = self._term_binding(antecedents, deduction, context)
            if binding is None:
                # No consistent match
                return False

            # Kernel side-conditions: soundness-critical provisos (freshness,
            # $d, atomicity, equality) checked structurally against that binding.
            if not self._side_conditions_hold(binding, context):
                return False

            # Kept for schematic promotion, which restates these very conditions
            # over it; see `Inference.binding`.
            inference.binding = binding

        # Otherwise ok
        deduction.inference_rule = self
        deduction.inference = inference
        deduction.valid = True

        # Add the deduction line as dependent to each of the antecedents
        for ant in antecedents:
            ant.dependent_lines.add(deduction)

        return True

    def check_discharge(self, subproof: Subproof, deduction: ProofLine, context: Context) -> bool:
        # Check that `deduction` follows by discharging `subproof` under this
        # rule. Discharge rules consume a whole subproof as a unit (conditional
        # proof, reductio, universal generalisation) rather than citing lines.

        schema = self.subproof_schema

        if schema is None or deduction.formula_term is None:
            return False

        # The subproof must be opened the way the schema expects (a hypothesis
        # for conditional-proof-style rules, a fresh variable for generalisation).
        if subproof.kind != schema.kind:
            return False

        conclusion = subproof.conclusion
        if conclusion is None or conclusion.formula_term is None:
            # An empty subproof discharges nothing.
            return False

        # Derive one consistent binding across the deduction and the subproof's
        # conclusion (and assumption, for hypothesis discharge) on the term
        # representation, the same way an ordinary rule binds its antecedents
        # (see _term_binding): schemas via _schema_term, proof-line formulae
        # already projected at parse time, unified under one substitution. Shared
        # metavariables - the `p` in both a subproof's assumption and the
        # deduction - are forced to agree by that one binding; atoms unify by what
        # they denote, so a literal conclusion such as a falsum `⊥` matches its
        # declared atom.
        schema_pairs: list[tuple[Pattern, ProofLine]] = [
            (self.deduction, deduction),
            (schema.conclusion, conclusion),
        ]
        if schema.assumption is not None:
            schema_pairs.append((schema.assumption, subproof.assumption))

        if schema.fresh is not None:
            # Tie the eigenvariable to the quantified variable. The fresh schema
            # variable (e.g. the `x` in `fresh: x`) is the same metavariable as
            # the bound `x` in the deduction `∀x p`, so matching it against the
            # subproof's opener forces the *introduced* variable to be the one
            # actually generalised. Without this, opening `let y` and concluding
            # `∀x …` would generalise x while only y was checked for freshness.
            schema_pairs.append((schema.fresh, subproof.assumption))

        term_pairs: list[tuple[Term, Term]] = []
        for occurrence, (pattern, line) in enumerate(schema_pairs):
            if line is None or line.formula_term is None:
                return False
            term_pairs.append(
                (self._schema_term(pattern, occurrence, context), line.formula_term)
            )

        if match_all(term_pairs, context) is None:
            return False

        # Freshness side-condition for universal generalisation: the
        # eigenvariable must be genuinely arbitrary - it may not occur in any
        # hypothesis still in force around the subproof (checked structurally on
        # kernel terms by Subproof.eigenvariable_is_fresh).
        if schema.fresh is not None and not subproof.eigenvariable_is_fresh(context):
            return False

        deduction.inference_rule = self
        deduction.valid = True
        return True

    def _term_binding(
        self, antecedents: Sequence[ProofLine], deduction: ProofLine, context: Context
    ) -> Binding | None:
        """Derive the substitution under which the deduction and every logical
        antecedent match their schemas, or ``None`` if none is consistent.

        Both sides are already terms: a schema via :func:`from_pattern` (variable
        slots become ``Var`` leaves), a proof line via the projection done when it
        was parsed. They are unified together, so a metavariable shared across
        antecedents and the conclusion is forced to one value by a single binding
        rather than reconciled after the fact.
        """
        if deduction.formula_term is None:
            return None

        pairs = [
            (self._schema_term(self.deduction, 0, context), deduction.formula_term)
        ]

        for occurrence, (pattern, ant) in enumerate(zip(self.antecedents, antecedents), start=1):
            if ant.line_type is None:
                return None

            if ant.line_type.behaviour != "logical" and pattern.equivalent(
                ant.line_type.pattern, context
            ):
                # An instance of a non-logical line: matched structurally by its
                # type, it carries no formula variables, so it binds nothing.
                continue

            if ant.formula_term is None:
                return None

            pairs.append(
                (self._schema_term(pattern, occurrence, context), ant.formula_term)
            )

        return match_all(pairs, context)

    def _string_pairs(
        self, antecedents: Sequence[ProofLine], deduction: ProofLine
    ) -> list[tuple[StringPattern, str]] | None:
        """The ``(schema, subject-string)`` pairs for a string-rewriting step.

        One pair for the deduction and one per aligned antecedent, read off the
        parsed formulae' surface strings. ``antecedents`` may be a *prefix* of
        the rule's slots (the assignment search prunes on prefixes); ``zip``
        aligns to whatever is supplied. Returns ``None`` — the step cannot hold —
        if a needed formula is absent or a schema is not a string template.
        """
        if deduction.formula_string is None or not isinstance(self.deduction, StringPattern):
            return None

        pairs: list[tuple[StringPattern, str]] = [(self.deduction, deduction.formula_string)]
        for pattern, ant in zip(self.antecedents, antecedents):
            if ant.formula_string is None or not isinstance(pattern, StringPattern):
                return None
            pairs.append((pattern, ant.formula_string))
        return pairs

    def _string_binding_exists(
        self, antecedents: Sequence[ProofLine], deduction: ProofLine, context: Context
    ) -> bool:
        """Whether one substitution makes every schema instantiate to its line,
        as strings — the string-rewriting analogue of :meth:`_term_binding`."""
        pairs = self._string_pairs(antecedents, deduction)
        return pairs is not None and joint_binding_exists(pairs, context)

    def slot_admits(self, slot: int, line: ProofLine, context: Context) -> bool:
        """Whether ``line`` could fill antecedent ``slot`` on its own.

        This is the *individual* admissibility of one line for one schema slot -
        the necessary condition a globally-consistent assignment must satisfy for
        this pair. It mirrors the per-antecedent handling in :meth:`_term_binding`
        (a non-logical line matches by its type and binds nothing; a logical one
        must unify with the slot's schema) but ignores cross-slot sharing, so the
        caller can use it to build a bipartite slot/line graph and skip citations
        (and orderings) that cannot possibly apply. The authoritative,
        binding-consistent check stays :meth:`check`.
        """
        if line.line_type is None:
            return False

        pattern = self.antecedents[slot]

        if self.matching == "string":
            # String rules bind by associative matching, not term unification;
            # a line is admissible for the slot if its surface string can match
            # the slot schema on its own (cross-slot sharing is settled later).
            if line.formula_string is None or not isinstance(pattern, StringPattern):
                return False
            return joint_binding_exists([(pattern, line.formula_string)], context)

        if line.line_type.behaviour != "logical" and pattern.equivalent(
            line.line_type.pattern, context
        ):
            # An instance of a non-logical line: matched by type, binds nothing.
            return True

        if line.formula_term is None:
            return False

        pair = (self._schema_term(pattern, slot + 1, context), line.formula_term)
        return match_all([pair], context) is not None

    def prefix_binding_exists(
        self, antecedents: Sequence[ProofLine], deduction: ProofLine, context: Context
    ) -> bool:
        """Whether the deduction and the first ``len(antecedents)`` antecedent
        slots can unify under one binding.

        ``antecedents`` is a *prefix* of an assignment (aligned to the rule's
        slots in order). The assignment search calls this to prune a partial
        assignment as soon as it is inconsistent - unification is monotone, so a
        prefix that cannot bind can never be completed - instead of exploring
        every ordering down to a full :meth:`check`. Reuses :meth:`_term_binding`,
        which already includes the deduction pair (so a shared metavariable is
        forced to agree from the first slot on).
        """
        if self.matching == "string":
            # The string-rewriting analogue: a prefix that admits no joint
            # substring binding across the deduction and the chosen slots cannot
            # be completed, so the search can prune it here too.
            return self._string_binding_exists(antecedents, deduction, context)
        return self._term_binding(antecedents, deduction, context) is not None

    def _schema_term(self, pattern: Pattern, occurrence: int, context: Context) -> Term:
        """Project a schema pattern into a term, keeping named metavariables
        shared but making each bare-sort position independent.

        A named metavariable (``p``, ``q``, ... - a ``StringPattern`` slot) is
        meant to denote the same formula everywhere it appears, so its name is
        left intact and the shared binding pins it. A bare sort used directly
        (``formula`` meaning "any formula") has no name to share by; two such
        positions are independent premises, so each occurrence's anonymous
        variable is renamed apart rather than collapsed into one binding.

        A compound template (e.g. a Hilbert axiom ``(p -> (q -> p))``) carries a
        precomputed *nested* term from the build (``schema_term``), because a
        flat ``from_pattern`` projection would be one production while the proof
        formula it must match is a nested tree of the system's productions. Its
        named metavariables are shared, so it needs no per-occurrence renaming.
        """
        if isinstance(pattern, StringPattern):
            # A compound template carries a precomputed *nested* term from the
            # build; a flat from_pattern projection would be one production
            # while the proof formula it must match is a nested tree. Either way
            # its named metavariables are shared, so no per-occurrence renaming.
            return statement_term(pattern)

        term = from_pattern(pattern)
        renames = {
            name: Var(f"{name}\x00{occurrence}", sort)
            for name, sort in term.free_vars().items()
        }
        return term.substitute(renames, context) if renames else term

    @staticmethod
    def _schema_text(pattern: Pattern) -> str:
        """A slot's schema as a reader would write it.

        `str(pattern)` is the class-prefixed repr (`StringPattern: antecedent`),
        which names the machinery and not the schema. A compound rule schema keeps
        its own surface form in `display_pattern` — `( p -> q )`, which is the
        thing a caller has to go and prove — and anything else is named by the
        sort it draws from.
        """
        if isinstance(pattern, StringPattern):
            return pattern.display_pattern
        return pattern.name

    def unsatisfied_slots(
        self, lines: Sequence[ProofLine], context: Context
    ) -> tuple[SlotReport, ...]:
        """Antecedent slots that **no** cited line could fill on its own.

        The diagnosis half of :meth:`slot_admits`, and the most useful thing a
        failed citation can say: a slot with no candidate is a premise the proof
        does not yet have, which is exactly the next goal a goal-directed caller
        wants. Runs only after a line has already failed (see
        :mod:`~.diagnostics`), so it may ask the question per slot rather than
        stopping at the first.

        Empty when every slot has *some* candidate — which does not mean the rule
        applies, only that the failure is about the slots holding together rather
        than about one being unreachable.
        """
        return tuple(
            SlotReport(index=slot, schema=self._schema_text(self.antecedents[slot]))
            for slot in range(len(self.antecedents))
            if not any(self.slot_admits(slot, line, context) for line in lines)
        )

    def slot_reports(
        self, lines: Sequence[ProofLine], context: Context
    ) -> tuple[SlotReport, ...]:
        """Every slot, with the cited lines individually admissible for it.

        What :meth:`unsatisfied_slots` cannot say: when each slot has candidates
        but they cannot be assigned to distinct lines, or cannot bind together,
        the useful record is the whole bipartite graph rather than one slot.
        """
        return tuple(
            SlotReport(
                index=slot,
                schema=self._schema_text(self.antecedents[slot]),
                candidates=numbers(
                    [line for line in lines if self.slot_admits(slot, line, context)]
                ),
            )
            for slot in range(len(self.antecedents))
        )

    def failing_proviso(
        self,
        antecedents: Sequence[ProofLine],
        deduction: ProofLine,
        context: Context,
    ) -> str | None:
        """The first proviso that does not hold for this assignment, or None.

        Reported in the author's own words where the build kept them
        (`side_condition_sources`), because `x not free in phi` is what a reader
        — and a caller trying to repair the step — can act on, where the repr of a
        frozen dataclass is not.

        None means the provisos are not what stopped this assignment: either they
        all hold, or no binding exists for them to be checked against, which is a
        different failure and is reported as one.
        """
        if self.matching == "string":
            # A string-rewriting step binds surface strings and carries no kernel
            # proviso, so there is never one to blame.
            return None
        binding = self._term_binding(antecedents, deduction, context)
        if binding is None:
            return None
        for index, condition in enumerate(self.side_conditions):
            try:
                if condition.check(binding, context):
                    continue
            except Exception:
                # A *malformed* proviso fails closed in `_side_conditions_hold`,
                # so it is genuinely why the rule did not apply and naming it is
                # the whole point of being here.
                pass
            if index < len(self.side_condition_sources):
                return self.side_condition_sources[index]
            return str(condition)
        return None

    def _side_conditions_hold(self, binding: Binding, context: Context) -> bool:
        """Whether every side-condition holds against the rule's term binding.

        Each proviso is a closed, structural predicate over the matched terms
        (see :mod:`~website.logical.kernel.side_conditions`). A *malformed*
        proviso - one naming a metavariable the rule never binds - raises inside
        the kernel; we fail closed (the rule does not apply) rather than let it
        escape and abort the whole proof parse. Rejecting is sound: a bad
        proviso can only make a rule too strict, never accept an invalid step.
        """
        try:
            return all(
                side_condition.check(binding, context)
                for side_condition in self.side_conditions
            )
        except Exception:
            return False


@dataclass(eq=False)
class Inference:
    """A successful application of an inference rule, recorded on the deduction.

    Holds the rule and the proof lines it related, plus the term ``binding`` the
    match derived - what each of the rule's metavariables stood for on this step.

    The binding is kept because a *schematic promotion* needs it: nominating a
    leaf of the proof as a metavariable claims the proof goes through for every
    instance, and that is only true if the provisos the steps relied on travel
    with the theorem. Restating one out of the step's binding is exactly
    :func:`~website.logical.kernel.side_conditions.restate`, and this is where
    the binding to restate over comes from. ``None`` for a string-rewriting step,
    which binds surface strings rather than terms and carries no kernel proviso.
    """

    inference_rule: InferenceRule

    # Antecedents and extra antecedents are proof lines; deduction is a proof line.
    antecedents: Sequence[ProofLine]
    extra_antecedents: Sequence[ProofLine]
    deduction: ProofLine
    binding: Binding | None = None
