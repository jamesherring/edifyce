"""A declarative model of a formal system that lowers to the Edifyce compiler.

The proof engine is powerful but its source language forces three unrelated
jobs -- describing the *grammar*, the *inference rules*, and *side conditions*
-- through one imperative, whitespace-sensitive mechanism (``Pattern`` /
``UnionPattern`` / ``with ... as ...`` / ``.each(...)`` / ``return self.f``).
Recursive grammars only work if the author performs a non-obvious ordering
dance (forward-declare an empty ``UnionPattern`` *then* fill it), and a wrong
guess compiles cleanly yet silently matches nothing.

This module offers a structured, order-independent description of a system --
the :class:`SystemSpec` dataclasses (grammar productions, a logical line,
definitions, axioms, rules) -- and *lowers it to ordinary ``.edi`` source*,
which the real :func:`website.logical.compiler.compile` then turns into a
``FormalSystem``. It is deliberately a thin front-end: nothing here
re-implements matching or proof checking -- it only rearranges the declarative
model into the engine's own language and hands off. The one thing the ``.edi``
language cannot express, ``respect_brackets``, is patched onto the compiled
patterns afterwards.

A :class:`SystemSpec` is built directly -- by the persistence layer
(``app.db.system_to_spec`` reconstructs one from stored rows) or, in tests, by
scripted assembly -- and handed to :func:`build_spec`. There is no text-syntax
front-end; the relational storage, not a source blob, is the source of truth.

Crucially, **definitions remain first-class**: a definition lowers to the
engine's ``Define <higher> as <lower> [where <proviso>]``, so a complex base
system (ZFC) can be layered up with familiar notation (``⊆``, ``∅``, ``P(x)``
...) exactly as the engine already supports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .compiler import compile as compile_edi


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
    # How steps are checked against this rule: "structural" (term unification,
    # the default) or "string" (associative matching, for a string-rewriting
    # rule such as MIU's — see website.logical.matching.rewriting).
    matching: str = "structural"


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

    # Side-conditions are the kernel's structural term algebra, checked against a
    # rule's *term* binding. A string-rewriting rule is justified by associative
    # matching over surface strings (no term binding), so it cannot evaluate
    # them. Rather than silently ignore a proviso an author wrote — which would
    # make the rule quietly more permissive than intended — reject the pairing.
    for rule in spec.rules:
        if rule.matching == "string" and rule.side_conditions:
            raise DeclarativeError(
                f"Rule {rule.label!r} uses string matching, which cannot enforce "
                f"side-conditions; drop them or switch it to structural matching."
            )

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


def _emit_line(spec: SystemSpec, emit) -> None:
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
    if rule.matching != "structural":
        emit(base_level + 1, "matching:")
        emit(base_level + 2, rule.matching)
    if rule.side_conditions:
        emit(base_level + 1, "side_conditions:")
        for proviso in rule.side_conditions:
            emit(base_level + 2, proviso)
    emit()


# ---------------------------------------------------------------------------
# respect_brackets -- the one thing ``.edi`` can't express, patched on after.
# ---------------------------------------------------------------------------


def _patch_brackets(system, bracket_pairs: list[tuple[str, str]]) -> None:
    if not bracket_pairs:
        return
    mapping = {o: c for o, c in bracket_pairs}

    seen: set[int] = set()

    def walk(pattern) -> None:
        if pattern is None or id(pattern) in seen:
            return
        seen.add(id(pattern))
        if hasattr(pattern, "respect_brackets"):
            pattern.respect_brackets = mapping
        for sub in getattr(pattern, "patterns", []) or []:
            walk(sub)
        for sub in (getattr(pattern, "variables", {}) or {}).values():
            walk(sub)

    for value in system.context.variables.values():
        if hasattr(value, "respect_brackets"):
            walk(value)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_spec(spec: SystemSpec, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from a :class:`SystemSpec`.

    The entry point for callers that hold a ``SystemSpec`` -- e.g. a persistence
    layer that reconstructs one from database rows, or a test that assembles one
    directly. Returns ``{"system": FormalSystem}`` on success or
    ``{"errors": [...]}`` when lowering or compilation fails.
    """

    # Lowering can still reject a parsed-but-invalid spec (e.g. a line shape
    # with no grammar-sort placeholder); surface that as errors, not an
    # exception, to keep the build contract.
    try:
        edi = lower(spec)
    except DeclarativeError as exc:
        return {"errors": [str(exc)]}

    result = compile_edi(edi, system_dict=system_dict)

    if "system" in result:
        # Determine bracket pairs: those declared, else default '()' if any
        # template/definition actually uses a parenthesis.
        brackets = list(spec.brackets)
        if not brackets and _uses_parens(spec):
            brackets = [("(", ")")]
        _patch_brackets(result["system"], brackets)

    return result


def _uses_parens(spec: SystemSpec) -> bool:
    texts = [p.template or "" for p in spec.productions]
    texts += [d.lower for d in spec.definitions]
    texts += [r.deduction for r in spec.axioms + spec.rules]
    return any("(" in t for t in texts)
