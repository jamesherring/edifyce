"""A declarative model of a formal system, built directly into the engine.

The proof engine is powerful but its source language forces three unrelated
jobs -- describing the *grammar*, the *inference rules*, and *side conditions*
-- through one whitespace-sensitive mechanism (``Pattern`` / ``UnionPattern`` /
``with ... as ...``). Recursive grammars only work if the author performs a
non-obvious ordering dance (forward-declare an empty ``UnionPattern`` *then*
fill it), and a wrong guess compiles cleanly yet silently matches nothing.

This module offers a structured, order-independent description of a system --
the :class:`SystemSpec` dataclasses (grammar productions, a logical line,
definitions, axioms, rules). :func:`build_spec` / :func:`build_system` turn one
into a ``FormalSystem`` **directly**, by calling the engine's own construction
primitives (``build_schema_pattern``, ``add_variables``, ``add_definition``,
``parse_side_condition``, the ``Pattern`` constructors) -- no text pass. Nothing
here re-implements matching or proof checking; it only wires the declarative
model into engine objects. Because there is no text pass, ``respect_brackets``
is set on each pattern at construction.

A :class:`SystemSpec` is built by the persistence layer
(``app.db.system_to_spec`` reconstructs one from stored rows) or, in tests, by
scripted assembly. The relational storage, not a source blob, is the source of
truth.

Crucially, **definitions remain first-class**: a definition becomes the engine's
``Define <higher> as <lower> [where <proviso>]``, so a complex base system (ZFC)
can be layered up with familiar notation (``⊆``, ``∅``, ``P(x)`` ...) exactly as
the engine already supports.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import copy
from dataclasses import InitVar, dataclass, field

from .compiler import (
    FormalSystemContext,
    _combine_side_conditions,
    build_schema_pattern,
)
from .formal_system import FormalSystem, InferenceRule, LineType, SubproofSchema
from .formal_system.side_condition_syntax import parse_side_condition
from .matching import AtomPattern, Pattern, RegexPattern, StringPattern, UnionPattern


class DeclarativeError(Exception):
    """Raised for problems detectable in a :class:`SystemSpec` before lowering."""


# The scopes a line type may open (mirrors LineType.scope's accepted values).
_LINE_SCOPES = (None, "assumption", "variable")

# The line behaviours a declarative system may author. `LineType` accepts more,
# but the rest are not offered here: `axiom` is emitted from `spec.axioms` rather
# than declared; `definition`/`import` fail closed in the checker (their payload
# came from an accessor mechanism that was removed); and `indent` is the block
# nesting that `LineSpec.scope` replaced. A value the engine ignores or refuses
# is worse than no value at all, so building one is an error, not a silent no-op.
_LINE_BEHAVIOURS = ("logical", "comment")


# ---------------------------------------------------------------------------
# Structured records: the declarative model of a system
# ---------------------------------------------------------------------------


@dataclass
class Production:
    sort: str
    name: str
    template: str | None = None        # composite: the notation template
    regex: str | None = None           # atomic (leaf): a raw regex
    atom_value: str | None = None      # atom constant: the single literal token it matches
    atom_base: str | None = None       # atom family: base of the `p_#` indexed family
    bindings: list[tuple[str, str]] = field(default_factory=list)  # (var, sort)


@dataclass
class Definition:
    sort: str
    name: str
    higher: str
    lower: str
    bindings: list[tuple[str, str]]
    condition: str | None = None
    # The defining form's bound variables, `[(var, sort)]` (the `fresh` clause).
    # Declaring a binder lets the term checker unfold the definition
    # capture-avoidingly, so a quantified definition (and any proviso on it) takes
    # the kernel path instead of being refused. Empty for a binder-free alias.
    fresh: list[tuple[str, str]] = field(default_factory=list)
    # Optional name a proof cites this definition by (`[<label>, <line>]`); the
    # generic `[Def, <line>]` keyword searches all in-scope definitions instead.
    # Must be unique within a system so a named citation resolves unambiguously.
    label: str | None = None


@dataclass
class Subproof:
    """The subproof a discharge rule consumes as a unit (→I, RAA, ∀I).

    A discharge rule cites no lines: it consumes a whole subproof. ``derive`` is
    the pattern its final line must match; the subproof is opened by exactly one
    of ``assume`` (a hypothesis pattern, an *assumption* subproof) or ``fresh``
    (an eigenvariable pattern, a *variable* subproof). All three are rule-schema
    source lines, parsed against the rule's metavariables like its deduction.
    """
    derive: str
    assume: str | None = None
    fresh: str | None = None


@dataclass
class Rule:
    label: str
    name: str
    antecedents: list[str]
    deduction: str
    bindings: list[tuple[str, str]]
    # Soundness provisos from the `side_conditions` section, one kernel-vocabulary
    # line each (implicit conjunction). Attached to the rule by its label; empty
    # for axioms and unconditioned rules.
    side_conditions: list[str] = field(default_factory=list)
    # How steps are checked against this rule: "structural" (term unification,
    # the default) or "string" (associative matching, for a string-rewriting
    # rule such as MIU's — see website.logical.matching.rewriting).
    matching: str = "structural"
    # The subproof this rule discharges, or None for an ordinary line-antecedent
    # rule. A discharge rule typically has no `antecedents`.
    subproof: Subproof | None = None
    # Whether a citation may name *more* lines than the rule has antecedent slots.
    # The surplus lines are recorded as `extra_antecedents` and left unconstrained
    # (they justify nothing), so this weakens what the citation must prove; off by
    # default, so a citation must name exactly the rule's antecedents.
    #
    # Inert on a discharge rule: that path cites exactly one subproof opener and
    # never consults this flag. Unlike antecedents/side-conditions (which the
    # discharge check also ignores, but whose loss would drop a *soundness*
    # constraint, hence the guard in build_system), an ignored allowance can only
    # ever be stricter, so the pairing is permitted rather than rejected.
    allow_extra_antecedents: bool = False


@dataclass
class LinePart:
    name: str
    regex: str


@dataclass
class LineSpec:
    name: str
    shape: str
    parts: list[LinePart] = field(default_factory=list)
    logical_sort: str | None = None
    # The scope this line opens, orthogonal to its logical behaviour: None (a
    # plain line), "assumption" (opens a subproof under a hypothesis, for e.g.
    # →I) or "variable" (opens one under a fresh variable, for e.g. ∀I). A scope
    # opener may still bear a formula, so this is separate from the line's shape.
    scope: str | None = None
    # What the checker does with lines of this type: "logical" (the default — the
    # line asserts a formula and must be justified) or "comment" (prose, never
    # checked and never numbered, so no citation can name it). A comment line
    # carries no formula, so it needs no `logical_sort` and its shape need not
    # name a grammar sort — the one line kind that may be pure text.
    behaviour: str = "logical"


@dataclass
class SystemSpec:
    name: str = ""
    brackets: list[tuple[str, str]] = field(default_factory=list)
    productions: list[Production] = field(default_factory=list)
    # Logical line types, in order. A system typically has one (`statement`), but
    # may declare several (e.g. a `claim` line and a scoped `assume` line); the
    # engine tries each when parsing a proof line.
    lines: list[LineSpec] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    axioms: list[Rule] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    # Back-compat for the former single-line API (`SystemSpec(line=...)`). An
    # `InitVar` so it is accepted at construction but never a stored field —
    # otherwise it would perturb the dataclass `==` the storage round-trip relies
    # on. Prefer `lines`.
    line: InitVar[LineSpec | None] = None

    def __post_init__(self, line: LineSpec | None) -> None:
        if line is not None:
            self.lines = [line, *self.lines]

    def sort_names(self) -> list[str]:
        seen = []
        for p in self.productions:
            if p.sort not in seen:
                seen.append(p.sort)
        return seen


# ---------------------------------------------------------------------------
# Lowering a SystemSpec to ``.edi`` source
# ---------------------------------------------------------------------------


def _identifier(name: str) -> str:
    ident = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if ident and ident[0].isdigit():
        ident = "_" + ident
    return ident


def _anchor(regex: str) -> str:
    if not regex.startswith("^"):
        regex = "^" + regex
    if not regex.endswith("$"):
        regex = regex + "$"
    return regex


def _line_layout(
    line: LineSpec, sorts: set[str],
) -> tuple[str, list[tuple[str, str]], tuple[str, str] | None, tuple[str, str] | None]:
    """Resolve a line's template and its formula/reference placeholders.

    Returns ``(template, placeholders, logical_ph, reference_ph)`` where each
    ``_ph`` is a ``(placeholder_name, variable)`` pair (either may be ``None``),
    given the system's grammar ``sorts`` so the logical placeholder can be
    resolved. ``logical_ph`` is ``None`` only for a comment line, which carries
    no formula.
    """
    part_names = {p.name for p in line.parts}

    # Tokenise the shape into (placeholder | literal) fragments.
    template, placeholders = _shape_to_template(line.shape)

    # Every placeholder has to resolve to something later (`ctx.variables[ph]`),
    # so name the undeclared one here rather than letting it surface as a bare
    # KeyError whose message is just the token.
    undeclared = [ph for ph, _ in placeholders if ph not in part_names and ph not in sorts]
    if undeclared:
        raise DeclarativeError(
            f"Line {line.name!r} has placeholder(s) "
            f"{', '.join(repr(ph) for ph in undeclared)} in its shape naming no "
            f"grammar sort or part; declare each as a part of the line."
        )

    # A comment line asserts nothing, so it has no formula to project — and its
    # shape is free to be prose, naming no grammar sort at all.
    if line.behaviour == "comment":
        if line.logical_sort is not None:
            raise DeclarativeError(
                f"Line {line.name!r} is commentary, so it carries no formula; "
                f"remove its logical sort {line.logical_sort!r}."
            )
        # Nor a citation. Projecting the prose as the line's `reference` would
        # surface it in the UI as the rule that justified the line.
        return template, placeholders, None, None

    # Choose the logical placeholder: explicit 'logical <sort>' or first sort.
    logical_ph = None
    if line.logical_sort:
        for ph, var in placeholders:
            if ph == line.logical_sort:
                logical_ph = (ph, var)
                break
    if logical_ph is None:
        for ph, var in placeholders:
            if ph in sorts:
                logical_ph = (ph, var)
                break
    if logical_ph is None:
        raise DeclarativeError("Line shape must contain a placeholder naming a grammar sort.")

    # The reference placeholder (if any inline part is used).
    reference_ph = None
    for ph, var in placeholders:
        if ph in part_names:
            reference_ph = (ph, var)
            break

    return template, placeholders, logical_ph, reference_ph


def _shape_to_template(shape: str) -> tuple[str, list[tuple[str, str]]]:
    # Replace each <name> placeholder with a fresh single-letter variable,
    # preserving all literal text (spaces, brackets) verbatim.
    template = []
    placeholders: list[tuple[str, str]] = []
    used = set()
    i = 0
    while i < len(shape):
        if shape[i] == "<":
            j = shape.find(">", i)
            if j == -1:
                raise DeclarativeError(f"Unclosed placeholder in shape: {shape!r}")
            ph = shape[i + 1:j]
            var = _fresh_var(ph, used)
            used.add(var)
            placeholders.append((ph, var))
            template.append(var)
            i = j + 1
        else:
            template.append(shape[i])
            i += 1
    return "".join(template), placeholders


def _fresh_var(placeholder: str, used: set[str]) -> str:
    base = placeholder[0] if placeholder else "v"
    if base not in used:
        return base
    n = 1
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


# ---------------------------------------------------------------------------
# Direct builder: SystemSpec -> FormalSystem.
#
# This constructs the engine objects straight from the SystemSpec by calling the
# same low-level primitives compile() uses (build_schema_pattern, add_variables,
# add_definition, parse_side_condition, the Pattern constructors), driven from
# the spec fields directly. There is no text pass, so respect_brackets is set on
# each pattern at construction rather than patched on afterwards.
# ---------------------------------------------------------------------------


def _bracket_map(spec: SystemSpec) -> dict[str, str] | None:
    # The opening->closing map every pattern respects: declared pairs, else the
    # default `()` when any template/definition/deduction actually uses a paren.
    brackets = list(spec.brackets)
    if not brackets and _uses_parens(spec):
        brackets = [("(", ")")]
    return {o: c for o, c in brackets} or None


def _binding_patterns(bindings: list[tuple[str, str]], ctx: FormalSystemContext) -> dict[str, Pattern]:
    # Map a `with`-style binding list `[(var, sort)]` to `{var: sort_pattern}`,
    # the string-variable dict the engine's pattern/rule builders consume.
    return {var: ctx.variables[sort] for var, sort in bindings}


def build_system(spec: SystemSpec) -> FormalSystem:
    """Build a :class:`FormalSystem` directly from a :class:`SystemSpec`.

    Raises :class:`DeclarativeError` for a structurally-invalid spec (e.g. a line
    shape with no grammar-sort placeholder); :func:`build_spec` wraps that into
    the ``{"errors": [...]}`` contract.
    """
    # A string-rewriting rule is justified by associative matching over surface
    # strings, with no term binding to evaluate side-conditions against; refuse
    # the pairing rather than silently ignoring a proviso the author wrote (same
    # guard `lower` applies before emitting `.edi`).
    for rule in spec.rules:
        if rule.matching == "string" and rule.side_conditions:
            raise DeclarativeError(
                f"Rule {rule.label!r} uses string matching, which cannot enforce "
                f"side-conditions; drop them or switch it to structural matching."
            )
        # A discharge rule is checked by consuming its subproof (check_discharge);
        # that path never evaluates line antecedents or side-conditions, so
        # configuring them would silently drop a soundness constraint. Refuse the
        # pairing rather than accept a rule whose provisos are ignored.
        if rule.subproof is not None and (rule.antecedents or rule.side_conditions):
            raise DeclarativeError(
                f"Rule {rule.label!r} discharges a subproof, so it cannot also carry "
                f"antecedents or side-conditions (the discharge check ignores them); "
                f"remove them."
            )

    name = _identifier(spec.name) or "System"
    ctx = FormalSystemContext()
    system = FormalSystem(name=name)
    ctx.variables[name] = system

    brackets = _bracket_map(spec)

    def register(pattern: Pattern) -> Pattern:
        # Every named pattern respects the system's brackets (parity with the
        # old post-compile `_patch_brackets`, which walked the same set).
        pattern.respect_brackets = brackets
        return pattern

    def unregistered(pattern: Pattern) -> Pattern:
        # Bracket parity deliberately not applied — see its uses.
        return pattern

    # 1. Atomic productions: regex leaves, atom constants, and atom families.
    for prod in spec.productions:
        if prod.regex is not None:
            ctx.variables[prod.name] = register(
                RegexPattern(name=prod.name, pattern=_anchor(prod.regex))
            )
        elif prod.atom_value is not None or prod.atom_base is not None:
            # An atom constant (`value`, one literal token) or indexed family
            # (`base`, the infinite `p_#` -> p_0, p_1, ...). A single token needs
            # no bracket parity, so it is not `register`ed — its `respect_brackets`
            # stays None, matching what the compiler produces.
            ctx.variables[prod.name] = AtomPattern(
                name=prod.name,
                value=prod.atom_value,
                base=prod.atom_base,
            )
    # (Inline line parts are registered per-line in step 5, immediately before
    # the line that uses them, so two lines may reuse a part name with different
    # regexes without the shared namespace binding both to the last one.)

    # 2. Forward-declare every sort as an empty union (order independence).
    for sort in spec.sort_names():
        ctx.variables[sort] = register(
            UnionPattern(name=sort, patterns=[])
        )

    # 3. Composite productions.
    for prod in spec.productions:
        if prod.template is None:
            continue
        pattern = StringPattern(name=prod.name, pattern=prod.template)
        pattern.add_variables(_binding_patterns(prod.bindings, ctx))
        ctx.variables[prod.name] = register(pattern)

    # 4. Fill each sort union with its members, in declared order.
    for sort in spec.sort_names():
        union = ctx.variables[sort]
        for prod in spec.productions:
            if prod.sort == sort:
                union.patterns.append(ctx.variables[prod.name])

    # 5. Lines: a statement pattern + logical line type per declared line. Each
    # line's inline parts are registered just before it is built (see step 1).
    if spec.lines:
        sorts = set(spec.sort_names())
        for line in spec.lines:
            # Commentary is prose, not a term: bracket parity must not apply to
            # it, or an unbalanced bracket in a note ("-- discharge ( here")
            # stops the line matching at all and fails the proof. Same reason an
            # atom constant is left unregistered in step 1.
            line_register = unregistered if line.behaviour == "comment" else register
            for part in line.parts:
                ctx.variables[part.name] = line_register(
                    RegexPattern(name=part.name, pattern=_anchor(part.regex))
                )
            _build_line(line, sorts, ctx, system, line_register)

    # 6. Axioms -> axiom-behaviour line types.
    for ax in spec.axioms:
        _build_axiom(ax, ctx, system, register)

    # 7. Rules -> inference rules.
    for rule in spec.rules:
        system.add_inference_rule(_build_rule(rule, ctx))

    # 8. Publish the build variables into the proof context, then finalise
    # definitions against that (now complete) context -- the order compile()
    # uses so `add_definition` can match the lower form against the productions.
    system.context.variables.update(ctx.variables)
    # Per position, whether the definition layered — kept in spec order so a
    # caller can map it back to a specific definition even when two share a
    # defined form (see registered_definition_layering). A cited definition name
    # must be unambiguous, so a duplicate label is rejected here (mirroring
    # compile()) rather than silently letting `[<name>, <line>]` pick one.
    seen_labels: set[str] = set()
    layering: list[bool] = []
    for defn in spec.definitions:
        if defn.label is not None:
            if defn.label in seen_labels:
                raise DeclarativeError(f"Duplicate definition label '{defn.label}'.")
            seen_labels.add(defn.label)
        layering.append(_finalise_definition(defn, ctx, system))
    system.definition_layering = layering

    # 9. Parse each rule's provisos now that definitions have resolved, so a
    # proviso's term argument may use defined notation (e.g. `equal(t, ∅)`). Each
    # rule brings its own metavariables. Mirrors compile()'s finalisation pass.
    for inference_rule in system.inference_rules:
        if not inference_rule.pending_side_conditions:
            continue
        rule_context = copy(system.context)
        rule_context.string_variables = {
            **rule_context.string_variables, **(inference_rule.variables or {})
        }
        inference_rule.side_conditions.extend(
            parse_side_condition(line, rule_context)
            for line in inference_rule.pending_side_conditions
        )
        inference_rule.pending_side_conditions = []

    # 10. Wire the build context and index the patterns.
    system.build_context = ctx
    system.build_pattern_dictionary()
    return system


def _build_line(line: LineSpec, sorts: set[str], ctx: FormalSystemContext,
                system: FormalSystem, register: Callable[[Pattern], Pattern]) -> None:
    if line.scope not in _LINE_SCOPES:
        raise DeclarativeError(
            f"Line {line.name!r} has invalid scope {line.scope!r}; "
            f"expected one of {', '.join(repr(s) for s in _LINE_SCOPES)}."
        )
    if line.behaviour not in _LINE_BEHAVIOURS:
        raise DeclarativeError(
            f"Line {line.name!r} has invalid behaviour {line.behaviour!r}; "
            f"expected one of {', '.join(repr(b) for b in _LINE_BEHAVIOURS)}."
        )
    if line.behaviour == "comment" and line.scope is not None:
        # A subproof has to be opened by a line the discharge rule can cite, and
        # commentary is unnumbered — so the subproof could never be discharged.
        raise DeclarativeError(
            f"Line {line.name!r} is commentary, so it cannot open a "
            f"{line.scope} scope; no rule could discharge it."
        )
    template, placeholders, logical_ph, reference_ph = _line_layout(line, sorts)

    # Each line gets a distinctly-named pattern (a single line named "statement"
    # keeps the historical "statement_pattern" name).
    pattern_name = f"{_identifier(line.name)}_pattern"
    pattern = StringPattern(name=pattern_name, pattern=template)
    pattern.add_variables(_binding_patterns([(var, ph) for ph, var in placeholders], ctx))
    ctx.variables[pattern_name] = register(pattern)

    line_type = LineType(
        name=line.name,
        pattern=pattern,
        behaviour=line.behaviour,
        scope=line.scope,
        # Declared, not merely absent: a comment line has no formula to project,
        # so leaving the field unset keeps prose out of anything that harvests
        # line formulae (the term graph, definitional steps).
        formula_field=logical_ph[1] if logical_ph is not None else None,
        reference_field=reference_ph[1] if reference_ph is not None else None,
    )
    ctx.variables[line.name] = line_type
    system.add_line_type(line_type)


def _build_axiom(axiom: Rule, ctx: FormalSystemContext, system: FormalSystem,
                 register: Callable[[Pattern], Pattern]) -> None:
    pattern_name = f"{_identifier(axiom.name)}_axiom"
    pattern = StringPattern(name=pattern_name, pattern=axiom.deduction)
    pattern.add_variables(_binding_patterns(axiom.bindings, ctx))
    ctx.variables[pattern_name] = register(pattern)

    # A bare axiom asserts its whole match, hence `formula_field="self"`.
    line_type = LineType(
        name=_identifier(axiom.name), pattern=pattern, behaviour="axiom", formula_field="self"
    )
    ctx.variables[_identifier(axiom.name)] = line_type
    system.add_line_type(line_type)


def _build_rule(rule: Rule, ctx: FormalSystemContext) -> InferenceRule:
    # The rule's bindings are its metavariables; put them in a scoped copy of the
    # build context so `build_schema_pattern` treats them as variables (exactly
    # the string-variable scope compile() gets from a `with ... as ...` block).
    string_variables = _binding_patterns(rule.bindings, ctx)
    rule_ctx = copy(ctx)
    rule_ctx.string_variables = dict(string_variables)

    inference_rule = InferenceRule(
        name=_identifier(rule.name),
        label=rule.label,
        variables=dict(string_variables),
        matching=rule.matching,
        subproof_schema=_build_subproof(rule, rule_ctx),
        allow_extra_antecedents=rule.allow_extra_antecedents,
    )
    for antecedent in rule.antecedents:
        inference_rule.antecedents.append(build_schema_pattern(antecedent, rule_ctx, "antecedent"))
    inference_rule.deduction = build_schema_pattern(rule.deduction, rule_ctx, "deduction")
    # Provisos are parsed later (see build_system), once definitions resolve, so a
    # proviso's term argument may use defined notation. Here we only collect them.
    inference_rule.pending_side_conditions = list(rule.side_conditions)
    return inference_rule


def _build_subproof(rule: Rule, rule_ctx: FormalSystemContext) -> SubproofSchema | None:
    # A discharge rule consumes a subproof opened by exactly one of a hypothesis
    # (`assume`) or a fresh variable (`fresh`); its final line must match
    # `derive`. Each is a rule-schema line parsed against the rule's variables,
    # exactly like the deduction.
    subproof = rule.subproof
    if subproof is None:
        return None
    if (subproof.assume is None) == (subproof.fresh is None):
        raise DeclarativeError(
            f"Rule {rule.label!r} subproof must be opened by exactly one of "
            f"'assume' or 'fresh'."
        )
    return SubproofSchema(
        conclusion=build_schema_pattern(subproof.derive, rule_ctx, "subproof"),
        assumption=(build_schema_pattern(subproof.assume, rule_ctx, "subproof")
                    if subproof.assume is not None else None),
        fresh=(build_schema_pattern(subproof.fresh, rule_ctx, "subproof")
               if subproof.fresh is not None else None),
    )


def _finalise_definition(defn: Definition, ctx: FormalSystemContext, system: FormalSystem) -> bool:
    """Register ``defn`` against the now-complete grammar, returning whether it
    layered — ``True`` when its defining (lower) form was recognised (given the
    definitions already in context), ``False`` when it matched nothing and so was
    dropped. A recognised form is added to the proof context."""
    union = ctx.variables[defn.sort]
    context_copy = copy(system.context)
    context_copy.string_variables.update(_binding_patterns(defn.bindings, ctx))

    # A `;` inside a `where` proviso conjoins several kernel conditions, matching
    # how the compiler splits the lowered `where` clause.
    where_strings = (
        [part.strip() for part in defn.condition.split(";") if part.strip()]
        if defn.condition
        else []
    )
    kernel_condition = _combine_side_conditions(where_strings, context_copy)

    # The defining form's bound variables, resolved to their sort patterns, so the
    # term checker treats them as binders (capture-avoiding unfold) rather than as
    # stray ground leaves that would force the string path.
    fresh_patterns = _binding_patterns(defn.fresh, ctx)

    result = union.add_definition(
        defn.lower,
        defn.higher,
        context_copy,
        fresh=fresh_patterns or None,
        kernel_condition=kernel_condition,
        label=defn.label,
    )
    if result is not None:
        system.context.definitions.add(result)
    # Non-None covers both a freshly added definition and one that de-duplicated
    # into an existing equivalent — either way its form was recognised, so the
    # definition layers. None means the lower form matched nothing.
    return result is not None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_spec(spec: SystemSpec, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from a :class:`SystemSpec`.

    The entry point for callers that hold a ``SystemSpec`` -- e.g. a persistence
    layer that reconstructs one from database rows, or a test that assembles one
    directly. Returns ``{"system": FormalSystem}`` on success or
    ``{"errors": [...]}`` when the spec is invalid.

    ``system_dict`` is reserved for cross-system references (a parent system a
    child inherits from). The declarative path does not resolve inheritance yet,
    so it is currently unused; it is kept on the signature so callers of the
    engine's public build entry point don't break when that lands.
    """
    try:
        return {"system": build_system(spec)}
    except DeclarativeError as exc:
        return {"errors": [str(exc)]}
    except Exception as exc:  # noqa: BLE001
        # A spec that reaches here passed storage validation but the engine still
        # rejected it (e.g. a malformed proviso). Preserve the build contract --
        # return errors rather than raising into the caller (a 500 at the API).
        return {"errors": [str(exc)]}


def registered_definition_layering(spec: SystemSpec) -> list[bool]:
    """Per definition, in ``spec.definitions`` order, whether it *layers*.

    Definitions layer positionally: a definition may build on the ones before it,
    so its defining (lower) form is parsed against the grammar those earlier
    definitions have already extended. A definition placed **ahead** of one whose
    notation its lower form uses does not raise -- its lower form simply matches
    nothing, and it is dropped silently. The returned flag is ``True`` for a
    definition that was recognised, ``False`` for one that was dropped.

    Keyed by **position**, not by defined form, so a caller can tell whether a
    *specific* definition would be dropped even when two definitions share a
    higher form (a set of forms would collapse them) or are structurally
    equivalent up to renaming (which ``add_definition`` de-duplicates).

    Layering depends only on the grammar (productions, in their sort unions) and
    the definitions themselves; axioms, rules and lines contribute nothing to it.
    So the build is done against a spec **reduced** to grammar plus definitions:
    an unrelated draft error the draft-tolerant CRUD persisted (a half-written
    rule, a malformed proviso) then can't fail the build and blind the check into
    reporting every definition dropped. Only a broken *grammar* still errors —
    and there no definition can layer at all, so all-``False`` is the honest
    answer (nothing is live for a reorder to drop).
    """
    reduced = copy(spec)
    reduced.axioms = []
    reduced.rules = []
    reduced.lines = []
    result = build_spec(reduced)
    if "errors" in result:
        return [False] * len(spec.definitions)
    return result["system"].definition_layering


def _uses_parens(spec: SystemSpec) -> bool:
    texts = [p.template or "" for p in spec.productions]
    texts += [d.lower for d in spec.definitions]
    texts += [r.deduction for r in spec.axioms + spec.rules]
    return any("(" in t for t in texts)
