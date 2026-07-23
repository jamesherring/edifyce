"""A declarative model of a formal system that lowers to the Edifyce compiler.

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

:func:`lower` still renders a ``SystemSpec`` to equivalent ``.edi`` source for
the read-only ``/source`` export (and as the oracle the direct builder is
differentially tested against); it is no longer on the build path.

Crucially, **definitions remain first-class**: a definition becomes the engine's
``Define <higher> as <lower> [where <proviso>]``, so a complex base system (ZFC)
can be layered up with familiar notation (``⊆``, ``∅``, ``P(x)`` ...) exactly as
the engine already supports.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, field

from .compiler import (
    FormalSystemContext,
    _combine_side_conditions,
    build_schema_pattern,
)
from .formal_system import FormalSystem, InferenceRule, LineType
from .formal_system.side_condition_syntax import parse_side_condition
from .matching import MatchSet, RegexPattern, StringPattern, UnionPattern


class DeclarativeError(Exception):
    """Raised for problems detectable in a :class:`SystemSpec` before lowering."""


# ---------------------------------------------------------------------------
# Structured records: the declarative model of a system
# ---------------------------------------------------------------------------


@dataclass
class Production:
    sort: str
    name: str
    template: str | None = None        # composite: the notation template
    regex: str | None = None           # atomic: a raw regex
    bindings: list[tuple[str, str]] = field(default_factory=list)  # (var, sort)


@dataclass
class Definition:
    sort: str
    name: str
    higher: str
    lower: str
    bindings: list[tuple[str, str]]
    condition: str | None = None


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


@dataclass
class SystemSpec:
    name: str = ""
    brackets: list[tuple[str, str]] = field(default_factory=list)
    productions: list[Production] = field(default_factory=list)
    line: LineSpec | None = None
    definitions: list[Definition] = field(default_factory=list)
    axioms: list[Rule] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)

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


def _with_clause(bindings: list[tuple[str, str]]) -> str:
    return ", ".join(f"{var} as {sort}" for var, sort in bindings)


def lower(spec: SystemSpec) -> str:
    """Lower a :class:`SystemSpec` to ``.edi`` source text.

    The ordering here is what removes the engine's forward-declaration trap:
    every sort's ``UnionPattern`` is declared empty up front, so productions in
    any order can reference any sort, and the unions are filled afterwards.
    """

    out: list[str] = []
    pad = "    "

    def emit(level: int = 0, text: str = "") -> None:
        out.append((pad * level + text) if text else "")

    emit(0, f"FormalSystem {_identifier(spec.name) or 'System'}:")
    emit()

    # 1. Atomic (regex) sort members and inline line parts.
    for prod in spec.productions:
        if prod.regex is not None:
            emit(1, f"Regex {prod.name}:")
            emit(2, _anchor(prod.regex))
            emit()

    if spec.line:
        for part in spec.line.parts:
            emit(1, f"Regex {part.name}:")
            emit(2, _anchor(part.regex))
            emit()

    # 2. Forward-declare every sort as an empty union (order independence).
    for sort in spec.sort_names():
        emit(1, f"UnionPattern {sort}:")
        emit()

    # 3. Composite productions.
    for prod in spec.productions:
        if prod.template is None:
            continue
        emit(1, f"Pattern {prod.name}:")
        if prod.bindings:
            emit(2, f"with {_with_clause(prod.bindings)}:")
            emit(3, prod.template)
        else:
            emit(2, prod.template)
        emit()

    # 4. Fill each sort union with its members, in declared order.
    for sort in spec.sort_names():
        members = [p.name for p in spec.productions if p.sort == sort]
        if not members:
            continue
        emit(1, f"{sort}:")
        for member in members:
            emit(2, member)
        emit()

    # 5. Proof context + line type (statement pattern and accessors).
    if spec.line:
        _emit_line(spec, emit)

    # 6. Definitions -- layered abbreviations, first-class.
    for defn in spec.definitions:
        emit(1, f"{defn.sort}:")
        tail = f" where {defn.condition}" if defn.condition else ""
        if defn.bindings:
            emit(2, f"with {_with_clause(defn.bindings)}:")
            emit(3, f"Define {defn.higher} as {defn.lower}{tail}")
        else:
            emit(2, f"Define {defn.higher} as {defn.lower}{tail}")
        emit()

    # 7a. Axioms -> axiom line types. An axiom is *asserted*, not derived by a
    # rule: the engine's `behaviour: axiom` marks a line matching the axiom
    # formula valid on its own. (This also sidesteps the kernel's schema->term
    # projection, which cannot represent a whole concrete formula in rule
    # deduction position.)
    for axiom in spec.axioms:
        _emit_axiom(axiom, emit)

    # 7b. Rules -> inference rules.
    for rule in spec.rules:
        _emit_rule(rule, emit)

    return "\n".join(out) + "\n"


def _anchor(regex: str) -> str:
    if not regex.startswith("^"):
        regex = "^" + regex
    if not regex.endswith("$"):
        regex = regex + "$"
    return regex


def _line_layout(
    spec: SystemSpec,
) -> tuple[str, list[tuple[str, str]], tuple[str, str], tuple[str, str] | None]:
    """Resolve a line's template and its formula/reference placeholders.

    Returns ``(template, placeholders, logical_ph, reference_ph)`` where each
    ``_ph`` is a ``(placeholder_name, variable)`` pair (``reference_ph`` may be
    ``None``). Shared by :func:`_emit_line` (text path) and :func:`build_system`
    (direct path) so both agree on which matched field is the formula/citation.
    """
    line = spec.line
    sorts = set(spec.sort_names())
    part_names = {p.name for p in line.parts}

    # Tokenise the shape into (placeholder | literal) fragments.
    template, placeholders = _shape_to_template(line.shape)

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


def _emit_line(spec: SystemSpec, emit) -> None:
    line = spec.line
    template, placeholders, logical_ph, reference_ph = _line_layout(spec)

    emit(1, "ProofContext:")
    emit(2, "given: MatchSet()")
    emit()

    bindings = [(var, ph) for ph, var in placeholders]
    emit(1, "Pattern statement_pattern:")
    emit(2, f"with {_with_clause(bindings)}:")
    emit(3, template)
    emit()

    # Declare which matched sub-field is the formula (and the citation) directly
    # on the line type, rather than as interpreted `formula()`/`reference()`
    # accessor functions — the engine projects these structurally.
    emit(1, f"LineType {line.name}:")
    emit(2, "pattern: statement_pattern")
    emit(2, "behaviour: logical")
    emit(2, f"formula: {logical_ph[1]}")
    if reference_ph is not None:
        emit(2, f"reference: {reference_ph[1]}")
    emit()


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


def _emit_axiom(axiom: Rule, emit) -> None:
    # An axiom lowers to a Pattern for its formula plus an axiom-behaviour line
    # type; a line matching the formula is self-justifying.
    pattern_name = f"{_identifier(axiom.name)}_axiom"

    emit(1, f"Pattern {pattern_name}:")
    if axiom.bindings:
        emit(2, f"with {_with_clause(axiom.bindings)}:")
        emit(3, axiom.deduction)
    else:
        emit(2, axiom.deduction)
    emit()

    # For a bare axiom assertion the whole match is the formula: `formula: self`
    # declares that structurally (replacing a `formula(): return self` accessor).
    emit(1, f"LineType {_identifier(axiom.name)}:")
    emit(2, f"pattern: {pattern_name}")
    emit(2, "behaviour: axiom")
    emit(2, "formula: self")
    emit()


def _emit_rule(rule: Rule, emit) -> None:
    has_bindings = bool(rule.bindings)
    base_level = 1
    if has_bindings:
        emit(1, f"with {_with_clause(rule.bindings)}:")
        base_level = 2

    emit(base_level, f"InferenceRule {_identifier(rule.name)}:")
    emit(base_level + 1, "label:")
    emit(base_level + 2, rule.label)
    if rule.antecedents:
        emit(base_level + 1, "antecedents:")
        for ant in rule.antecedents:
            emit(base_level + 2, ant)
    emit(base_level + 1, "deduction:")
    emit(base_level + 2, rule.deduction)
    if rule.side_conditions:
        emit(base_level + 1, "side_conditions:")
        for proviso in rule.side_conditions:
            emit(base_level + 2, proviso)
    emit()


# ---------------------------------------------------------------------------
# Direct builder: SystemSpec -> FormalSystem, without the .edi round-trip.
#
# This constructs the engine objects straight from the SystemSpec by calling the
# same low-level primitives compile() uses (build_schema_pattern, add_variables,
# add_definition, parse_side_condition, the Pattern constructors), driven from
# spec fields in lower()'s order. Because there is no text pass, respect_brackets
# is set on each pattern at construction rather than patched on afterwards.
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
    name = _identifier(spec.name) or "System"
    ctx = FormalSystemContext()
    system = FormalSystem(name=name)
    ctx.variables[name] = system

    brackets = _bracket_map(spec)

    def register(pattern):
        # Every named pattern respects the system's brackets (parity with the
        # old post-compile `_patch_brackets`, which walked the same set).
        pattern.respect_brackets = brackets
        return pattern

    # 1. Atomic (regex) productions and inline line parts.
    for prod in spec.productions:
        if prod.regex is not None:
            ctx.variables[prod.name] = register(
                RegexPattern(name=prod.name, pattern=_anchor(prod.regex), pre_format=ctx.pre_format)
            )
    if spec.line:
        for part in spec.line.parts:
            ctx.variables[part.name] = register(
                RegexPattern(name=part.name, pattern=_anchor(part.regex), pre_format=ctx.pre_format)
            )

    # 2. Forward-declare every sort as an empty union (order independence).
    for sort in spec.sort_names():
        ctx.variables[sort] = register(
            UnionPattern(name=sort, patterns=[], pre_format=ctx.pre_format)
        )

    # 3. Composite productions.
    for prod in spec.productions:
        if prod.template is None:
            continue
        pattern = StringPattern(name=prod.name, pattern=prod.template, pre_format=ctx.pre_format)
        pattern.add_variables(_binding_patterns(prod.bindings, ctx))
        ctx.variables[prod.name] = register(pattern)

    # 4. Fill each sort union with its members, in declared order.
    for sort in spec.sort_names():
        union = ctx.variables[sort]
        for prod in spec.productions:
            if prod.sort == sort:
                union.patterns.append(ctx.variables[prod.name])

    # 5. Line: proof context + statement pattern + logical line type.
    if spec.line:
        _build_line(spec, ctx, system, register)

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
    for defn in spec.definitions:
        _finalise_definition(defn, ctx, system)

    # 9. Wire the build context and index the patterns.
    system.build_context = ctx
    system.build_pattern_dictionary()
    return system


def _build_line(spec: SystemSpec, ctx: FormalSystemContext, system: FormalSystem,
                register: Callable[[Pattern], Pattern]) -> None:
    template, placeholders, logical_ph, reference_ph = _line_layout(spec)

    system.context.logical["given"] = MatchSet()

    pattern = StringPattern(name="statement_pattern", pattern=template, pre_format=ctx.pre_format)
    pattern.add_variables({var: ctx.variables[ph] for ph, var in placeholders})
    ctx.variables["statement_pattern"] = register(pattern)

    line_type = LineType(
        name=spec.line.name,
        pattern=pattern,
        behaviour="logical",
        formula_field=logical_ph[1],
        reference_field=reference_ph[1] if reference_ph is not None else None,
    )
    ctx.variables[spec.line.name] = line_type
    system.add_line_type(line_type)


def _build_axiom(axiom: Rule, ctx: FormalSystemContext, system: FormalSystem,
                 register: Callable[[Pattern], Pattern]) -> None:
    pattern_name = f"{_identifier(axiom.name)}_axiom"
    pattern = StringPattern(name=pattern_name, pattern=axiom.deduction, pre_format=ctx.pre_format)
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
        name=_identifier(rule.name), label=rule.label, variables=dict(string_variables)
    )
    for antecedent in rule.antecedents:
        inference_rule.antecedents.append(build_schema_pattern(antecedent, rule_ctx, "antecedent"))
    inference_rule.deduction = build_schema_pattern(rule.deduction, rule_ctx, "deduction")
    for proviso in rule.side_conditions:
        inference_rule.side_conditions.append(parse_side_condition(proviso, rule_ctx))
    return inference_rule


def _finalise_definition(defn: Definition, ctx: FormalSystemContext, system: FormalSystem) -> None:
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

    result = union.add_definition(
        defn.lower, defn.higher, context_copy, kernel_condition=kernel_condition, label=None
    )
    if result is not None:
        system.context.definitions.add(result)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_spec(spec: SystemSpec, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from a :class:`SystemSpec`.

    The entry point for callers that hold a ``SystemSpec`` -- e.g. a persistence
    layer that reconstructs one from database rows, or a test that assembles one
    directly. Returns ``{"system": FormalSystem}`` on success or
    ``{"errors": [...]}`` when the spec is invalid.
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


def _uses_parens(spec: SystemSpec) -> bool:
    texts = [p.template or "" for p in spec.productions]
    texts += [d.lower for d in spec.definitions]
    texts += [r.deduction for r in spec.axioms + spec.rules]
    return any("(" in t for t in texts)
