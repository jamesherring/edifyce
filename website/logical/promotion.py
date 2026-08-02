"""Building a :class:`PromotedTheorem` from a proved or imported theorem's source.

Promotion is how a proved lemma — or one imported from another corpus, notably a
Metamath ``$p`` — becomes citable in a system without joining its primitive
inference rules. The statement arrives as text in *the system's own grammar*, not
a source language of ours, so this is engine surface rather than anything to do
with the retired ``.edi`` compiler it used to share a module with.

See :class:`~website.logical.formal_system.promotion.PromotedTheorem` for what a
promoted theorem is, and :meth:`FormalSystem.promote` for registering one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from website.logical.build_context import (
    FormalSystemContext,
    build_schema_pattern,
    warm_grammar_index,
)
from website.logical.formal_system import FormalSystem, Proof, PromotedTheorem
from website.logical.formal_system.side_condition_syntax import (
    conjuncts,
    parse_side_condition,
    render_side_condition,
)
from website.logical.kernel import from_match
from website.logical.kernel.constructors import constructor_for
from website.logical.kernel.side_conditions import references, restate
from website.logical.kernel.terms import abstract
from website.logical.matching import Pattern, StringPattern

if TYPE_CHECKING:
    from website.logical.kernel.terms import FreeVars, Term
    from website.logical.matching.context import Context


@dataclass(frozen=True)
class TheoremSpec:
    """A promoted theorem in the form it is *written*: strings and names.

    Exactly :func:`promote_from_source`'s arguments, gathered into one record so
    the two things that need them can share it — an importer, which derives them
    from a corpus, and the persistence layer, which stores and replays them. It
    is to a ``PromotedTheorem`` what a ``SystemSpec`` is to a ``FormalSystem``:
    declarative, engine-object-free, and the thing a row round-trips to.

    Deliberately *not* carrying whether the theorem is a primitive of its system.
    Nothing about promotion reads that — a citation of an axiom and of a derived
    theorem are checked identically, which is the whole reason one construction
    serves both — so it belongs to whatever records the library, not here.
    """

    label: str
    statement: str
    metavariables: dict[str, str] = field(default_factory=dict)
    premises: tuple[str, ...] = ()
    distinct: tuple[str, ...] = ()
    matching: str = "structural"


def _logical_sorts(system: FormalSystem) -> list[Pattern]:
    # The sorts a proof line's formula is actually parsed at: each logical line
    # type's declared formula field (or the whole line pattern, for `formula:
    # self`). Composing a ground statement against *these* - rather than whichever
    # sort in the grammar happens to match first - keeps promotion in step with how
    # the system parses a line, so a theorem cannot be built against an unrelated
    # sort that no proof line would ever be read at.
    sorts: list[Pattern] = []
    for line_type in system.line_types:
        if line_type.behaviour != "logical" or line_type.formula_field is None:
            continue

        if line_type.formula_field == "self":
            sort = line_type.pattern
        elif isinstance(line_type.pattern, StringPattern):
            sort = line_type.pattern.variables.get(line_type.formula_field)
        else:
            continue

        if isinstance(sort, Pattern) and not any(sort is seen for seen in sorts):
            sorts.append(sort)
    return sorts


def _ground_schema_term(
    text: str,
    system: FormalSystem,
    context: FormalSystemContext,
    sorts: Sequence[Pattern],
) -> Term | None:
    # Compose the nested kernel term of a *ground* statement - one with literal
    # structure but no metavariables, like a closed theorem `2 ∈ ℝ`.
    #
    # compose_schema_term deliberately declines these (it keys on a metavariable),
    # so promotion composes them here instead. Two differences from that path: the
    # parse runs only at the system's logical `sorts` (see _logical_sorts), never
    # falling back to the rest of the grammar, and may use the system's *resolved*
    # definitions, which live on the built system's proof context - a
    # promoted theorem is built against an already-compiled system, unlike a rule
    # schema composed mid-compilation, where the build context still holds pending
    # records. There is nothing to re-variabilise: a ground statement binds no
    # metavariable. Returns None when no logical sort parses the text.
    parse_context = copy(context)
    parse_context.definitions = list(system.context.definitions)
    # Same reasoning as compose_schema_term: nothing this parse depends on moves
    # while it runs, so the substring parses can be memoised.
    parse_context.parse_memo = {}
    for sort in sorts:
        matched = sort.match(text, parse_context)
        if matched is not None:
            return from_match(matched)
    return None


def _theorem_schema(
    text: str,
    system: FormalSystem,
    context: FormalSystemContext,
    name: str,
    matching: str,
    cached: Term | None = None,
) -> Pattern:
    # Build one schema pattern for a promoted theorem's statement or premise.
    #
    # A *ground* compound - literal structure but no metavariables - composes no
    # schema term through the rule path, and its flat projection cannot match the
    # nested term a proof formula parses to, so it would be a theorem that never
    # applies. Compose the ground term explicitly instead: the schema is then that
    # exact term, and unification against a cited line is structural equality -
    # precisely the semantics of a closed theorem (`2 ∈ ℝ` justifies `2 ∈ ℝ` and
    # nothing else). A statement *with* metavariables is left alone: it projects
    # structurally even when nothing is composed, notably defined notation, whose
    # flat projection does apply (a `sub` alias matches an `a sub b` line).
    #
    # Only for structural matching: the string checker matches surface strings and
    # never reads `schema_term` (see InferenceRule.check), so composing a term for
    # it - let alone failing when none composes - would be meaningless.
    # A promoted theorem's statement is a proof line's formula, so it is read at
    # the sorts a line is read at - not at whichever sort of the grammar happens
    # to come first. Both composition paths take the same list.
    #
    # `cached` is the same term read back from storage instead of re-derived (P4).
    # It reaches the ground path too: whichever branch composed the term the first
    # time, what is stored is the term, and a stored one is simply attached. What
    # the branch below then decides is only whether the *pattern* needs replacing,
    # and with a term already in hand it does not.
    sorts = _logical_sorts(system)
    pattern = build_schema_pattern(text, context, name, prefer=sorts, cached=cached)
    if (
        matching != "string"
        and isinstance(pattern, StringPattern)
        and pattern.schema_term is None
        and pattern.non_variable_locations
        and not pattern.variable_locations
    ):
        ground = _ground_schema_term(text, system, context, sorts)
        if ground is None:
            raise ValueError(
                f"Statement {text!r} has no metavariables and does not parse at any "
                "of the system's logical sorts."
            )
        # A fresh shell, never the pattern build_schema_pattern returned: that can
        # be a system-owned pattern out of the grammar, which must not be given a
        # theorem's schema term.
        pattern = StringPattern(name=name, pattern=text)
        pattern.schema_term = ground
    return pattern


def promote_from_source(
    system: FormalSystem,
    label: str,
    statement: str,
    metavariables: Mapping[str, str],
    premises: Sequence[str] = (),
    distinct: Sequence[str] = (),
    matching: str = "structural",
    statement_term: Term | None = None,
    premise_terms: Sequence[Term | None] = (),
) -> PromotedTheorem:
    """Build a :class:`PromotedTheorem` from a proved/imported theorem's source.

    The import-facing promotion route. The theorem is given as source text in the
    system's own grammar: its conclusion ``statement``, its hypotheses
    ``premises``, its ``metavariables`` (name -> sort name), and its distinct-
    variable provisos ``distinct`` (each a ``disjoint(...)`` line). A Metamath
    ``$p`` maps here directly - ``$e`` -> ``premises``, ``$f`` -> ``metavariables``,
    ``$d`` -> ``distinct``. The metavariables are re-instantiated at each citation
    by unification and the provisos enforced against that binding (see
    :class:`~website.logical.formal_system.promotion.PromotedTheorem`).

    Unlike generalising a concrete proof line by renaming leaves, this parses the
    statement against the grammar with the metavariables held schematic, so a
    formula metavariable may stand for a *compound* (the usual case).

    ``matching`` sets how a citation is checked, mirroring ``InferenceRule``:
    ``"structural"`` (term unification, the default) or ``"string"`` for a theorem
    proved in a semi-Thue / string-rewriting system (e.g. MIU), which must stay
    string-checked to remain applicable.

    Register the result with :meth:`FormalSystem.promote` to make it citable. The
    theorem is not added to the system's primitive ``inference_rules``.

    A *closed* theorem - one whose statement is ground, such as Metamath's
    ``2 e. RR`` - is supported: with no metavariables to instantiate it justifies
    exactly its own statement and nothing else.

    ``statement_term`` and ``premise_terms`` supply already-composed kernel terms
    so the statement need not be parsed against the grammar again — what the
    persistence layer hands back when its stored terms are still current (see
    ``app/db/promoted_theorems_mapping.py``). Absent or ``None``, the text is
    composed exactly as before; a missing term costs a parse and never a
    difference in what the theorem says.

    Raises :class:`ValueError` if the system has no build context, if a sort name
    is not a declared pattern of the system, or if a structurally-matched ground
    conclusion/premise parses at none of the system's logical sorts. A statement
    *with* metavariables that names an undefined symbol is not rejected here - as
    with an authored rule schema it simply yields a theorem that never applies - so
    validate imports upstream.
    """
    if system.build_context is None:
        raise ValueError("Cannot promote a theorem against a system with no build context.")

    # Copy the context so the theorem's metavariables can be set in
    # string_variables without mutating the system's own build context. Warm the
    # grammar index on the original first, so the copy inherits it rather than
    # rebuilding it per theorem.
    warm_grammar_index(system.build_context)
    context = copy(system.build_context)
    string_variables: dict[str, Pattern] = {}
    for name, sort_name in metavariables.items():
        sort = system.build_context.variables.get(sort_name)
        if not isinstance(sort, Pattern):
            raise ValueError(
                f"Metavariable {name!r} names sort {sort_name!r}, which is not a "
                "declared pattern of the system."
            )
        string_variables[name] = sort
    context.string_variables = string_variables

    deduction = _theorem_schema(
        statement, system, context, label, matching, statement_term
    )
    antecedents = tuple(
        _theorem_schema(
            text, system, context, f"{label}.premise{index}", matching,
            premise_terms[index] if index < len(premise_terms) else None,
        )
        for index, text in enumerate(premises)
    )
    side_conditions = tuple(parse_side_condition(line, context) for line in distinct)

    return PromotedTheorem(
        label=label,
        deduction=deduction,
        antecedents=antecedents,
        side_conditions=side_conditions,
        variables=dict(string_variables),
        matching=matching,
    )


def proved_theorem(
    system: FormalSystem, proof: Proof, label: str
) -> tuple[TheoremSpec, PromotedTheorem]:
    """The library entry a completed proof establishes, as a *ground* theorem.

    The counterpart of :func:`~website.logical.metamath.importer.register` for a
    proof written here rather than imported: the same pair — the strings to store
    and the engine object whose composed terms are worth caching beside them.

    The statement is the conclusion's **term**, not its text. A proof's last
    root-level formula-bearing line is what it establishes, that line already
    carries the kernel term the checker unified against, and promoting from the
    term means the entry says exactly what was checked, with no parse between the
    two to disagree. The stored string is that term rendered
    (:meth:`~website.logical.kernel.terms.Term.to_string`), so it is a record of
    the term rather than a second source for it.

    Ground, because nothing here nominates metavariables: the entry justifies its
    own statement and no other instance of it, which is
    :func:`promote_from_source`'s closed-theorem case. Note this stays right for a
    *string-rewriting* system without being string-matched: with no metavariable
    to bind, unification of two ground terms is equality, which is what an
    associative matcher would have concluded too. Nominating metavariables — where
    the regime does start to matter — is a later phase.

    Raises :class:`ValueError` if the proof does not stand, carries a warning, or
    has no formula-bearing conclusion at its root scope. Defensive rather than
    the user-facing gate: a caller with an HTTP error to render should say so
    before reaching here.
    """
    if not proof.valid:
        raise ValueError("A proof that does not stand establishes no theorem.")
    if proof.has_warnings:
        raise ValueError(
            "A proof carrying a warning establishes no theorem: the warning is "
            "unresolved doubt about whether it stands."
        )

    # The *root* scope's conclusion: a line inside an assumption is proved under
    # that assumption, so it is not what the proof as a whole establishes.
    conclusion = None if proof.root_scope is None else proof.root_scope.conclusion
    if conclusion is None or conclusion.formula_term is None:
        raise ValueError(
            "The proof has no formula-bearing conclusion at its root scope, so "
            "there is nothing to promote."
        )

    term = conclusion.formula_term
    spec = TheoremSpec(label=label, statement=term.to_string())
    return spec, promote_spec(system, spec, statement_term=term)


def schematic_theorem(
    system: FormalSystem,
    proof: Proof,
    label: str,
    metavariables: Mapping[str, str],
    context: Context,
) -> tuple[TheoremSpec, PromotedTheorem]:
    """The library entry a proof establishes **schematically**, and its warrant.

    :func:`proved_theorem` promotes what a proof concluded, verbatim; this
    promotes what it concluded *for every instance of the leaves named in*
    ``metavariables`` — `⊢ (φ → φ)` proved once and cited at every instance
    rather than at the one the author happened to write.

    That claim needs discharging, not asserting. Nominating a leaf says the proof
    goes through whatever stands there, so the proof is **re-checked with the
    nominated leaves replaced by variables throughout** — every line, not just
    the conclusion — and the entry is written only if it still stands. What comes
    back is then a proof of the schematic statement, so the theorem is warranted
    directly rather than by an argument about uniformity.

    The abstraction is :func:`~website.logical.kernel.terms.abstract` over each
    line's already-checked term: no parse, and the leaves are replaced by *what
    they denote* rather than by rewriting the source. A leaf the grammar fixes as
    a constant, or a sort mismatch, then shows up as the abstracted proof failing
    to check — those guards are the checker's, not a list maintained here.

    **The provisos travel.** A step may have relied on a side condition
    (`ax-5`'s `not occurs(x, P)`), which held for the concrete leaves and says
    nothing about an arbitrary instance. Each such condition is restated over the
    step's own binding — which the abstracted check leaves on
    :attr:`~website.logical.formal_system.rules.Inference.binding` — and carried
    into the entry, where a citation re-checks it against its own instantiation.
    Without this, schematic promotion is exactly the hole an eigenvariable
    condition escapes through.

    Three shapes of proof are **refused** rather than generalised, each because
    the re-check above cannot discharge the claim for it (see
    :func:`_unsupported_for_abstraction`). They are refusals, not gaps: a
    nomination this cannot settle must not become a theorem.

    ``context`` is the one the proof was read in, needed to restate a proviso and
    to name a sort. Raises :class:`ValueError` if the proof does not stand, if a
    nominated sort is not a declared pattern, if the proof is of a shape this
    cannot settle, or if the abstracted proof fails.
    """
    if system.build_context is None:
        raise ValueError(
            "Cannot promote a theorem against a system with no build context."
        )
    _require_a_standing_proof(proof)

    sorts: FreeVars = {}
    for name, sort_name in metavariables.items():
        pattern = system.build_context.variables.get(sort_name)
        if not isinstance(pattern, Pattern):
            raise ValueError(
                f"Metavariable {name!r} names sort {sort_name!r}, which is not a "
                "declared pattern of the system."
            )
        sorts[name] = constructor_for(pattern)

    refusal = _unsupported_for_abstraction(proof, sorts)
    if refusal is not None:
        raise ValueError(refusal)

    abstracted = _abstracted_proof(system, proof, sorts, context)
    if not abstracted.valid:
        failed = next(
            (line for line in abstracted.proof_lines if not line.valid), None
        )
        raise ValueError(
            "The proof does not go through with "
            + ", ".join(sorted(metavariables))
            + " held schematic, so it does not prove the general statement"
            + (
                f": line {failed.number} — {failed.invalid_message}"
                if failed is not None and failed.invalid_message
                else "."
            )
        )

    conclusion = None if abstracted.root_scope is None else abstracted.root_scope.conclusion
    if conclusion is None or conclusion.formula_term is None:
        raise ValueError(
            "The abstracted proof has no formula-bearing conclusion at its root "
            "scope, so there is nothing to promote."
        )

    statement = conclusion.formula_term
    spec = TheoremSpec(
        label=label,
        statement=statement.to_string(),
        metavariables=dict(metavariables),
        distinct=_carried_provisos(
            abstracted, set(statement.free_vars()), set(metavariables), context, system
        ),
    )
    return spec, promote_spec(system, spec, statement_term=statement)


def _require_a_standing_proof(proof: Proof) -> None:
    # The same two guards `proved_theorem` opens with, shared rather than reached
    # by promoting the ground theorem first and discarding it: that path also
    # composes a schema pattern and parses the ground statement against the
    # grammar, which is work thrown away — and which can fail with "does not
    # parse at any logical sort" for a promotion that would otherwise succeed.
    if not proof.valid:
        raise ValueError("A proof that does not stand establishes no theorem.")
    if proof.has_warnings:
        raise ValueError(
            "A proof carrying a warning establishes no theorem: the warning is "
            "unresolved doubt about whether it stands."
        )


def _unsupported_for_abstraction(proof: Proof, sorts: FreeVars) -> str | None:
    # The shapes whose claim the re-check cannot settle, as the reason to refuse.
    #
    # Each is a case where re-checking the abstracted proof *passes* without
    # having tested anything, so accepting it would mint a theorem on no
    # evidence. Refused here rather than left to the check, precisely because the
    # check is what does not notice.
    #
    # Nothing to refuse when nothing is nominated: an empty abstraction is the
    # verbatim promotion, whose soundness is `proved_theorem`'s and does not
    # depend on any of this.
    if not sorts:
        return None
    for line in proof.proof_lines:
        rule = line.inference_rule
        if rule is not None and rule.matching == "string":
            # A string-rewriting step matches surface *strings*, and a variable
            # renders as its own name — so the abstracted proof is the same
            # strings and re-checking it discharges nothing. (The theorem would
            # also have to carry `matching="string"` to be checked the way it was
            # proved; both are why this is a refusal rather than a default.)
            return (
                f"Line {line.number} is justified by the string-rewriting rule "
                f"{rule.label!r}. A string step matches surface text, so holding "
                "a leaf schematic does not change what is checked and proves "
                "nothing about other instances."
            )

        if line.is_axiom and line.formula_term is not None:
            # An axiom-behaviour line is valid by fiat: `execute` grants it
            # without re-matching, so an abstracted term is never held to the
            # axiom's own schema and a leaf the axiom spells could be
            # generalised away unchecked.
            if abstract(line.formula_term, sorts) is not line.formula_term:
                return (
                    f"Line {line.number} is an axiom, granted by matching its own "
                    "shape rather than by a step that can be re-checked, and the "
                    "nomination changes it. Its leaves cannot be generalised."
                )

    scope = proof.root_scope
    stack = list(scope.children) if scope is not None else []
    while stack:
        subproof = stack.pop()
        stack.extend(subproof.children)
        if subproof.kind == "variable":
            # An eigenvariable's freshness is `Subproof.eigenvariable_is_fresh`,
            # not a `SideCondition`, and a discharge builds no `Inference` — so
            # there is no binding to restate and nothing to carry. The freshness
            # that held for the concrete variable says nothing about an instance.
            return (
                "This proof introduces an eigenvariable, whose freshness is "
                "checked against the concrete variable and cannot yet be carried "
                "into a schematic theorem. Promote it verbatim instead."
            )
    return None


def _abstracted_proof(
    system: FormalSystem,
    proof: Proof,
    sorts: FreeVars,
    context: Context,
) -> Proof:
    # The same proof with each nominated leaf replaced by a variable of its sort,
    # re-checked. Built as a fresh `Proof` over fresh lines rather than by
    # mutating the checked one: `check_proof` re-derives numbering, scope and
    # justification per line, and it must derive them for *this* proof rather
    # than find the original's answers already sitting there.
    #
    # The citation environment is carried over verbatim — a cited lemma or
    # promoted theorem is not what is being generalised, and re-resolving it here
    # would be a second library read for no answer.
    rebuilt = Proof(formal_system=system)
    rebuilt.reference_context = dict(proof.reference_context)
    parse_context = copy(context)
    for line in proof.proof_lines:
        fresh = rebuilt.add_proof_line(line.text, parse_context)
        if line.empty:
            continue
        fresh.line_type = line.line_type
        fresh.label = line.label
        fresh.reference_string = line.reference_string
        fresh.reference_string_display = line.reference_string_display
        if line.formula_term is not None:
            fresh.formula_term = abstract(line.formula_term, sorts)
    return system.check_proof(rebuilt, parse_context)


def _carried_provisos(
    abstracted: Proof,
    bindable: set[str],
    metavariables: set[str],
    context: Context,
    system: FormalSystem,
) -> tuple[str, ...]:
    # Every side condition the abstracted proof's steps relied on, restated over
    # the binding that step made and written as the lines a `TheoremSpec` carries.
    #
    # Deduplicated on the rendered line, because one proviso restated from two
    # applications of the same rule is one obligation, not two.
    names = {
        constructor_for(pattern): name
        for name, pattern in system.build_context.variables.items()
        if isinstance(pattern, Pattern)
    }
    lines: list[str] = []
    for line in abstracted.proof_lines:
        inference = line.inference
        if inference is None or inference.binding is None:
            continue
        for condition in inference.inference_rule.side_conditions:
            for part in conjuncts(restate(condition, inference.binding, context)):
                referenced = references(part)
                if not (referenced & metavariables):
                    # Closed under the theorem's metavariables: a fact about
                    # ground terms, settled by the check that just ran.
                    continue
                if not referenced <= bindable:
                    # A citation binds only what its statement mentions, so a
                    # proviso naming anything else could never be checked — it
                    # would raise inside the citation and read as "this theorem
                    # does not apply", for every instance. Refuse the nomination
                    # rather than store an entry nothing can cite.
                    raise ValueError(
                        "Holding "
                        + ", ".join(sorted(metavariables))
                        + " schematic leaves the proviso "
                        + repr(render_side_condition(part, names))
                        + " over "
                        + ", ".join(sorted(referenced - bindable))
                        + ", which the theorem's statement does not mention, so "
                        "no citation could discharge it."
                    )
                rendered = render_side_condition(part, names)
                if rendered not in lines:
                    lines.append(rendered)
    return tuple(lines)


def promote_spec(
    system: FormalSystem,
    spec: TheoremSpec,
    statement_term: Term | None = None,
    premise_terms: Sequence[Term | None] = (),
) -> PromotedTheorem:
    """Build a :class:`PromotedTheorem` from its declarative :class:`TheoremSpec`.

    ``statement_term`` / ``premise_terms`` skip the composing parse; see
    :func:`promote_from_source`.
    """
    return promote_from_source(
        system,
        label=spec.label,
        statement=spec.statement,
        metavariables=spec.metavariables,
        premises=spec.premises,
        distinct=spec.distinct,
        matching=spec.matching,
        statement_term=statement_term,
        premise_terms=premise_terms,
    )
