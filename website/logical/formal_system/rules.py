"""Inference rules and their applications: :class:`InferenceRule`, :class:`Inference`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel import (
    And,
    DisjointLeaves,
    Equal,
    IsAtom,
    IsMember,
    Not,
    Occurs,
    Or,
    Var,
    from_match,
    from_pattern,
    match_all,
)
from ..matching import StringPattern
from .proof import ProofLine, Subproof

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..kernel import SideCondition, Term
    from ..matching.context import Context
    from ..matching.patterns import Pattern

    # A rule match's substitution: schematic variable name -> the Term it binds to.
    Binding = dict[str, Term]


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


def _normalise_side_condition(condition: SideCondition) -> tuple:
    """A structural normal form for comparing side-conditions across rules.

    Sorts compare by name (not object identity) so two systems that re-parse the
    same proviso agree, and boolean combinators fold to their parts. Used only
    by :meth:`InferenceRule.equivalent`.
    """
    if isinstance(condition, (And, Or)):
        return (
            type(condition).__name__,
            tuple(sorted(_normalise_side_condition(part) for part in condition.parts)),
        )
    if isinstance(condition, Not):
        return ("Not", _normalise_side_condition(condition.inner))
    if isinstance(condition, Occurs):
        return ("Occurs", condition.needle, condition.haystack)
    if isinstance(condition, Equal):
        return ("Equal", condition.left, condition.right)
    if isinstance(condition, DisjointLeaves):
        sort = None if condition.sort is None else condition.sort.name
        return ("DisjointLeaves", condition.left, condition.right, sort)
    if isinstance(condition, IsAtom):
        sort = None if condition.sort is None else condition.sort.name
        return ("IsAtom", condition.name, sort)
    if isinstance(condition, IsMember):
        return ("IsMember", condition.name, condition.sort.name)
    return (type(condition).__name__,)


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

        # Optionally allow extra antecedents
        self.allow_extra_antecedents: bool = allow_extra_antecedents

        # Keep a set of variables handy
        self.variables: dict[str, Pattern] | None = variables

        # The subproof this rule discharges (SubproofSchema), if it is a
        # discharge rule. None for an ordinary line-antecedent rule.
        self.subproof_schema: SubproofSchema | None = subproof_schema

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

        # Structural check over terms (the graph representation): the deduction
        # and every logical antecedent must match their schemas under one shared
        # binding, derived by unification. The formulae are already parsed, so we
        # project them straight to terms and never re-run the string matcher.
        binding = self._term_binding(antecedents, deduction, context)
        if binding is None:
            # No consistent match
            return False

        # Kernel side-conditions: soundness-critical provisos (freshness, $d,
        # atomicity, equality) checked structurally against that same binding.
        if not self._side_conditions_hold(binding, context):
            return False

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

        if schema is None or deduction.formula is None:
            return False

        # The subproof must be opened the way the schema expects (a hypothesis
        # for conditional-proof-style rules, a fresh variable for generalisation).
        if subproof.kind != schema.kind:
            return False

        conclusion = subproof.conclusion
        if conclusion is None or conclusion.formula is None:
            # An empty subproof discharges nothing.
            return False

        # Derive one consistent binding across the deduction and the subproof's
        # conclusion (and assumption, for hypothesis discharge) on the term
        # representation, the same way an ordinary rule binds its antecedents
        # (see _term_binding): schemas via _schema_term, proof-line formulae via
        # from_match, unified under one substitution. Shared metavariables - the
        # `p` in both a subproof's assumption and the deduction - are forced to
        # agree by that one binding; atoms unify by what they denote, so a
        # literal conclusion such as a falsum `⊥` matches its declared atom.
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
            if line is None or line.formula is None:
                return False
            term_pairs.append(
                (self._schema_term(pattern, occurrence, context), from_match(line.formula, context))
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

        Each ``(schema, subject)`` pair is projected into the term space -
        schemas via :func:`from_pattern` (variable slots become ``Var`` leaves),
        already-parsed formulae via :func:`from_match` - and unified together, so
        a metavariable shared across antecedents and the conclusion is forced to
        one value by a single binding rather than reconciled after the fact.
        """
        if deduction.formula is None:
            return None

        pairs = [
            (self._schema_term(self.deduction, 0, context), from_match(deduction.formula, context))
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

            if ant.formula is None:
                return None

            pairs.append(
                (self._schema_term(pattern, occurrence, context), from_match(ant.formula, context))
            )

        return match_all(pairs, context)

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

        if line.line_type.behaviour != "logical" and pattern.equivalent(
            line.line_type.pattern, context
        ):
            # An instance of a non-logical line: matched by type, binds nothing.
            return True

        if line.formula is None:
            return False

        pair = (self._schema_term(pattern, slot + 1, context), from_match(line.formula, context))
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
        precomputed *nested* term from the compiler (``schema_term``), because a
        flat ``from_pattern`` projection would be one production while the proof
        formula it must match is a nested tree of the system's productions. Its
        named metavariables are shared, so it needs no per-occurrence renaming.
        """
        if isinstance(pattern, StringPattern):
            # A compound template carries a precomputed *nested* term from the
            # compiler; a flat from_pattern projection would be one production
            # while the proof formula it must match is a nested tree. Either way
            # its named metavariables are shared, so no per-occurrence renaming.
            if pattern.schema_term is not None:
                return pattern.schema_term
            return from_pattern(pattern, context)

        term = from_pattern(pattern, context)
        renames = {
            name: Var(f"{name}\x00{occurrence}", sort)
            for name, sort in term.free_vars().items()
        }
        return term.substitute(renames, context) if renames else term

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

    def equivalent(
        self, other: object, context: Context, memo: dict[tuple, bool] | None = None
    ) -> bool:
        # Check equivalent. `memo` is shared with Pattern.equivalent during the
        # recursion, so its keys are heterogeneous (rule pairs and pattern pairs).

        if memo is None:
            memo = {}

        if (self, other) in memo:
            return memo[(self, other)]

        # Assume false
        memo[(self, other)] = False

        if type(other) is not InferenceRule:
            return False

        if not self.name == other.name:
            return False

        if not self.label == other.label:
            return False

        if not len(self.antecedents) == len(other.antecedents):
            return False

        if not self.allow_extra_antecedents == other.allow_extra_antecedents:
            return False

        # Assume true
        memo[(self, other)] = True

        for ant, other_ant in zip(self.antecedents, other.antecedents):
            if not ant.equivalent(other_ant, context, memo):
                memo[(self, other)] = False
                return False

        if not self.deduction.equivalent(other.deduction, context, memo):
            memo[(self, other)] = False
            return False

        if [_normalise_side_condition(c) for c in self.side_conditions] != [
            _normalise_side_condition(c) for c in other.side_conditions
        ]:
            memo[(self, other)] = False
            return False

        # Otherwise ok
        return True


@dataclass(eq=False)
class Inference:
    """A successful application of an inference rule, recorded on the deduction.

    Holds the rule and the proof lines it related. The structural match is now a
    term binding derived in :meth:`InferenceRule.check` (via unification) and is
    not retained here - the old Match-tree fields and variable-reconciliation
    walk went away with the string-based condition path.
    """

    inference_rule: InferenceRule

    # Antecedents and extra antecedents are proof lines; deduction is a proof line.
    antecedents: Sequence[ProofLine]
    extra_antecedents: Sequence[ProofLine]
    deduction: ProofLine
