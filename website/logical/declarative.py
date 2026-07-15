"""A declarative front-end that lowers to the existing Edifyce compiler.

The proof engine is powerful but its source language forces three unrelated
jobs -- describing the *grammar*, the *inference rules*, and *side conditions*
-- through one imperative, whitespace-sensitive mechanism (``Pattern`` /
``UnionPattern`` / ``with ... as ...`` / ``.each(...)`` / ``return self.f``).
Recursive grammars only work if the author performs a non-obvious ordering
dance (forward-declare an empty ``UnionPattern`` *then* fill it), and a wrong
guess compiles cleanly yet silently matches nothing.

This module offers a small, sectioned, non-code configuration format and
*lowers it to ordinary ``.edi`` source*, which the real
:func:`website.logical.compiler.compile` then turns into a ``FormalSystem``.
It is deliberately a thin front-end: nothing here re-implements matching or
proof checking -- it only rearranges declarative input into the engine's own
language and then hands off. The one thing the ``.edi`` language cannot
express, ``respect_brackets``, is patched onto the compiled patterns
afterwards.

Crucially, **definitions remain first-class**: a ``definitions`` section
lowers to the engine's ``Define <higher> as <lower> [if <condition>]``, so a
complex base system (ZFC) can be layered up with familiar notation (``⊆``,
``∅``, ``P(x)`` ...) exactly as the engine already supports.

The input format (see ``examples/zfc.system`` for a full worked example)::

    system <Name>

    notation
      brackets ( )                       # optional grouping bracket pair

    grammar
      <sort> | <name> | matches <regex>              # atomic (leaf) member
      <sort> | <name> | <template> | <bindings>      # composite production

    line <name>
      shape <text with <placeholders>>
      <part> | matches <regex>           # inline parts (e.g. a reference)
      logical <sort>                     # which placeholder is the formula

    definitions
      <sort> | <name> | <higher> | means <lower> | <bindings> [ | if <cond> ]

    axioms
      <label> | <name> | <formula> [ | <bindings> ]

    rules
      <label> | <name> | from <a> ; <b> | infer <c> | <bindings>

``<bindings>`` is a ``;``-separated list of groups ``n1, n2 : sort``.

``|`` separates columns; a literal pipe inside a field (a regex alternation or
pipe notation such as set-builder ``{ x \\| y }``) is written ``\\|``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .compiler import compile as compile_edi


class DeclarativeError(Exception):
    """Raised for problems the front-end can detect before lowering."""


# ---------------------------------------------------------------------------
# Parsing the sectioned input into structured records
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


_SECTIONS = {"system", "notation", "grammar", "line", "definitions", "axioms", "rules"}


def _split_columns(row: str) -> list[str]:
    # Split a row on its ``|`` column separators. A literal pipe inside a field
    # -- a regex alternation ``[a-z]+\|[A-Z]+`` or pipe notation like
    # set-builder ``{ x \| φ }`` -- is written ``\|`` and does not split.
    # Only ``\|`` is special; other backslashes (``\d``, ``\.``) pass through.
    columns: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row) and row[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "|":
            columns.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    columns.append("".join(current).strip())
    return columns


def _parse_bindings(text: str) -> list[tuple[str, str]]:
    # Parse "x, y : variable, p : formula" (or ';'-separated) into
    # [(x, variable), (y, variable), (p, formula)]. Names sharing a sort are
    # comma-listed before the ':'; a ':' atom closes the current group.
    bindings: list[tuple[str, str]] = []
    text = text.replace(";", ",").strip()
    if not text:
        return bindings

    pending: list[str] = []
    for atom in text.split(","):
        atom = atom.strip()
        if not atom:
            continue
        if ":" in atom:
            name, sort = atom.split(":", 1)
            name, sort = name.strip(), sort.strip()
            if name:
                pending.append(name)
            for pending_name in pending:
                bindings.append((pending_name, sort))
            pending = []
        else:
            pending.append(atom)

    if pending:
        raise DeclarativeError(f"Binding names {pending} have no ': sort'.")

    return bindings


def _blocks(source: str) -> list[tuple[str, str, list[str]]]:
    # Yield (section_keyword, header_remainder, body_lines) for each top-level
    # section. A section header sits at column 0; its body is every following
    # indented (or blank) line until the next column-0 line.
    lines = source.splitlines()
    blocks: list[tuple[str, str, list[str]]] = []

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if raw[0].isspace():
            raise DeclarativeError(f"Unexpected indented line outside any section: {raw!r}")

        keyword = stripped.split()[0]
        if keyword not in _SECTIONS:
            raise DeclarativeError(f"Unknown section '{keyword}'.")

        header_remainder = stripped[len(keyword):].strip()

        body: list[str] = []
        i += 1
        while i < len(lines) and (not lines[i].strip() or lines[i][0].isspace()):
            body_line = lines[i].strip()
            if body_line and not body_line.startswith("#"):
                body.append(body_line)
            i += 1

        blocks.append((keyword, header_remainder, body))

    return blocks


def parse(source: str) -> SystemSpec:
    """Parse declarative source into a :class:`SystemSpec`."""

    spec = SystemSpec()

    for keyword, header, body in _blocks(source):

        if keyword == "system":
            spec.name = header

        elif keyword == "notation":
            for row in body:
                if row.startswith("brackets"):
                    toks = row.split()[1:]
                    if len(toks) != 2:
                        raise DeclarativeError("'brackets' needs an opening and closing symbol.")
                    spec.brackets.append((toks[0], toks[1]))

        elif keyword == "grammar":
            for row in body:
                cols = _split_columns(row)
                if len(cols) < 3:
                    raise DeclarativeError(f"Grammar row needs at least 'sort | name | body': {row!r}")
                sort, name, third = cols[0], cols[1], cols[2]
                if third.startswith("matches "):
                    spec.productions.append(Production(sort=sort, name=name, regex=third[len("matches "):].strip()))
                else:
                    bindings = _parse_bindings(cols[3]) if len(cols) > 3 else []
                    spec.productions.append(Production(sort=sort, name=name, template=third, bindings=bindings))

        elif keyword == "line":
            line = LineSpec(name=header, shape="")
            for row in body:
                if row.startswith("shape "):
                    line.shape = row[len("shape "):].strip()
                elif row.startswith("logical "):
                    line.logical_sort = row[len("logical "):].strip()
                else:
                    cols = _split_columns(row)
                    if len(cols) == 2 and cols[1].startswith("matches "):
                        line.parts.append(LinePart(name=cols[0], regex=cols[1][len("matches "):].strip()))
                    else:
                        raise DeclarativeError(f"Unrecognised line row: {row!r}")
            spec.line = line

        elif keyword == "definitions":
            for row in body:
                cols = _split_columns(row)
                # sort | name | higher | means <lower> | bindings [ | if <cond> ]
                if len(cols) < 4 or not cols[3].startswith("means "):
                    raise DeclarativeError(f"Definition row must be 'sort | name | higher | means <lower> | bindings': {row!r}")
                lower = cols[3][len("means "):].strip()
                bindings = _parse_bindings(cols[4]) if len(cols) > 4 else []
                condition = None
                if len(cols) > 5 and cols[5].startswith("if "):
                    condition = cols[5][len("if "):].strip()
                spec.definitions.append(Definition(
                    sort=cols[0], name=cols[1], higher=cols[2], lower=lower,
                    bindings=bindings, condition=condition,
                ))

        elif keyword == "axioms":
            for row in body:
                cols = _split_columns(row)
                if len(cols) < 3:
                    raise DeclarativeError(f"Axiom row must be 'label | name | formula': {row!r}")
                bindings = _parse_bindings(cols[3]) if len(cols) > 3 else []
                spec.axioms.append(Rule(label=cols[0], name=cols[1], antecedents=[],
                                        deduction=cols[2], bindings=bindings))

        elif keyword == "rules":
            for row in body:
                cols = _split_columns(row)
                # label | name | from a ; b | infer c | bindings
                if len(cols) < 4:
                    raise DeclarativeError(f"Rule row must be 'label | name | from ... | infer ... | bindings': {row!r}")
                from_col = cols[2]
                infer_col = cols[3]
                if from_col != "from" and not from_col.startswith("from "):
                    raise DeclarativeError(f"Rule row needs a 'from ...' column: {row!r}")
                if not infer_col.startswith("infer "):
                    raise DeclarativeError(f"Rule row needs an 'infer ...' column: {row!r}")
                antecedents = [a.strip() for a in from_col[len("from"):].split(";") if a.strip()]
                deduction = infer_col[len("infer "):].strip()
                bindings = _parse_bindings(cols[4]) if len(cols) > 4 else []
                spec.rules.append(Rule(label=cols[0], name=cols[1], antecedents=antecedents,
                                       deduction=deduction, bindings=bindings))

    return spec


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
        if defn.bindings:
            emit(2, f"with {_with_clause(defn.bindings)}:")
            tail = f" if {defn.condition}" if defn.condition else ""
            emit(3, f"Define {defn.higher} as {defn.lower}{tail}")
        else:
            tail = f" if {defn.condition}" if defn.condition else ""
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

    # The engine fetches logical content via formula() and the citation via
    # reference(); those accessor names are part of its contract.
    emit(1, "statement_pattern.formula():")
    emit(2, f"return self.{logical_ph[1]}")
    emit()
    if reference_ph is not None:
        emit(1, "statement_pattern.reference():")
        emit(2, f"return self.{reference_ph[1]}")
        emit()

    emit(1, f"LineType {line.name}:")
    emit(2, "pattern: statement_pattern")
    emit(2, "behaviour: logical")
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

    # The engine reads a logical line's content via formula(); for a bare axiom
    # assertion the whole match is the formula.
    emit(1, f"{pattern_name}.formula():")
    emit(2, "return self")
    emit()

    emit(1, f"LineType {_identifier(axiom.name)}:")
    emit(2, f"pattern: {pattern_name}")
    emit(2, "behaviour: axiom")
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


def build(source: str, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from declarative source.

    Mirrors :func:`website.logical.compiler.compile`: returns
    ``{"system": FormalSystem}`` on success or ``{"errors": [...]}`` on failure.
    """

    try:
        spec = parse(source)
    except DeclarativeError as exc:
        return {"errors": [str(exc)]}

    return build_spec(spec, system_dict=system_dict)


def build_spec(spec: SystemSpec, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from an already-parsed :class:`SystemSpec`.

    The entry point for callers that hold a ``SystemSpec`` directly rather than
    source text -- e.g. a persistence layer that reconstructs one from database
    rows. Same return shape as :func:`build`.
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


def _demo(path: str) -> None:
    # `python -m website.logical.declarative <file.system>`: show the lowered
    # .edi and confirm the system compiles.
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    print("=" * 70)
    print("LOWERED .edi")
    print("=" * 70)
    print(lower(parse(source)))

    result = build(source)
    print("=" * 70)
    if "errors" in result:
        print("COMPILE ERRORS")
        for err in result["errors"]:
            print("  ", err)
        return

    system = result["system"]
    print(f"COMPILED: {system.name}")
    print("  line types:", [lt.name for lt in system.line_types])
    print("  rules:", [ir.label for ir in system.inference_rules])


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m website.logical.declarative <file.system>")
        raise SystemExit(2)
    _demo(sys.argv[1])
