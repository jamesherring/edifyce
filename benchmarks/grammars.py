"""Grammars for the matching benchmarks, built straight from the pattern classes.

Deliberately not built through ``declarative.build_system``: these exist to put a
known shape in front of :class:`~website.logical.matching.StringPattern` — a deep
nest, a wide grammar, an ambiguous split — not to exercise system assembly. A
system builder in the loop would make the numbers a measurement of two things.

Each factory returns the union that is the sort to parse at, so a benchmark can
call ``union.match(text, context)`` and time exactly the parse.
"""

from __future__ import annotations

from website.logical.matching import (
    AtomPattern,
    Context,
    StringPattern,
    UnionPattern,
)

# One table per shape, shared by every pattern that declares it. Sharing is not
# cosmetic: the search only skips a split it would have to parse when the slot's
# sort respects *this same* table, and it compares the tables by identity (see
# `StringPattern._sort_refuses_unbalanced`). Two equal-but-distinct dicts leave
# the prune switched off, and the benchmark then times a path no built system
# takes.
BRACKETS = {"(": ")"}
SQUARE = {"[": "]"}


def propositional(connectives: int = 4, atoms: int = 3) -> UnionPattern:
    """A propositional grammar: a few binary connectives over an atom family.

    The shape almost every hand-written system has, and the one deep nesting
    stresses: every connective's template opens with ``(``, so the leading-
    character index cannot separate them and each candidate parse of a subformula
    is tried against all of them.
    """
    symbols = ["→", "∧", "∨", "↔"][:connectives]

    formula = UnionPattern(name="formula", patterns=[], respect_brackets=BRACKETS)

    compounds = [
        StringPattern(name=f"binary_{i}", pattern=f"(a {symbol} b)", respect_brackets=BRACKETS)
        for i, symbol in enumerate(symbols)
    ]
    negation = StringPattern(name="negation", pattern="¬a", respect_brackets=BRACKETS)

    for compound in [*compounds, negation]:
        formula.add_pattern(compound)

    for base in "pqrstuvwxyz"[:atoms]:
        formula.add_pattern(AtomPattern(name=f"atom_{base}", base=base))

    for compound in compounds:
        compound.add_variables({"a": formula, "b": formula})
    negation.add_variables({"a": formula})

    return formula


def wide(constants: int = 1200) -> UnionPattern:
    """A grammar with a large flat vocabulary: two compounds, many nullary atoms.

    The shape a Metamath import produces — set.mm declares ~1,200 nullary class
    constants (``RR``, ``sin``, ``2``) beside a hundred or so compounds. The cost
    a naive union pays here grows with the size of the *grammar* rather than the
    size of the formula, which is the thing worth watching.
    """
    expression = UnionPattern(name="expression", patterns=[], respect_brackets=BRACKETS)

    plus = StringPattern(name="plus", pattern="(a + b)", respect_brackets=BRACKETS)
    times = StringPattern(name="times", pattern="(a x b)", respect_brackets=BRACKETS)

    for compound in (plus, times):
        expression.add_pattern(compound)

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    for i in range(constants):
        # Spread the leading characters so the index has something to key on, as a
        # real vocabulary does.
        token = f"{alphabet[i % len(alphabet)]}{i}"
        expression.add_pattern(AtomPattern(name=f"const_{i}", value=token))

    for compound in (plus, times):
        compound.add_variables({"a": expression, "b": expression})

    return expression


def juxtaposition() -> UnionPattern:
    """Prefix application, ``(a b)`` — the shape a term algebra is written in.

    Two slots separated by a single space, which is also the separator inside
    every operand, so the split search has an occurrence to try per subterm.
    """
    term = UnionPattern(name="term", patterns=[], respect_brackets=BRACKETS)

    application = StringPattern(name="application", pattern="(a b)", respect_brackets=BRACKETS)
    term.add_pattern(application)

    for base in "fgxyz":
        term.add_pattern(AtomPattern(name=f"atom_{base}", base=base))

    application.add_variables({"a": term, "b": term})
    return term


def adjacent() -> UnionPattern:
    """A grammar whose compound puts two slots side by side: ``[ab]``.

    The worst case for the split search: nothing at all separates the operands,
    so every position between them is a candidate boundary and no literal can
    narrow it. Rare in a real grammar, which is why it is worth having here —
    it is the case the search must not fall over on.
    """
    term = UnionPattern(name="term", patterns=[], respect_brackets=SQUARE)

    pair = StringPattern(name="pair", pattern="[ab]", respect_brackets=SQUARE)
    term.add_pattern(pair)

    for base in "xyz":
        term.add_pattern(AtomPattern(name=f"atom_{base}", base=base))

    pair.add_variables({"a": term, "b": term})
    return term


def bracket_spelling_constants(count: int = 15) -> UnionPattern:
    """A grammar naming constants that are *spelled* with a parenthesis.

    The shape a Metamath import produces — set.mm declares fourteen such tokens
    (`[,)`, `((`, `O(1)`) — and the only one where `Pattern._opaque_positions`
    does any work. Every other scenario here leaves `bracket_opaque` empty, so
    without this the opaque path is unmeasured and a regression in it would not
    show up in a `--compare`.
    """
    expression = UnionPattern(name="expression", patterns=[], respect_brackets=BRACKETS)

    binary = StringPattern(name="binary", pattern="( a b c )", respect_brackets=BRACKETS)
    expression.add_pattern(binary)

    spelt = ["[,)", "(,]", "(,)", "[,]", "((", "))", "O(1)", "(x)", "(+)", "(/)",
             "(,)", "[.)", "(.]", "<_O(1)", "(cn)"][:count]

    for i, token in enumerate(spelt):
        expression.add_pattern(AtomPattern(name=f"spelt_{i}", value=token))
    for token in ("A", "B", "0", "RR"):
        expression.add_pattern(AtomPattern(name=f"const_{token}", value=token))

    binary.add_variables({"a": expression, "b": expression, "c": expression})

    for pattern in (expression, binary):
        pattern.bracket_opaque = tuple(sorted(set(spelt)))

    return expression


def sequent(separators: int = 1) -> tuple[StringPattern, UnionPattern]:
    """A turnstile line ``Γ ⊢ φ`` over a propositional formula sort.

    Returns the line pattern and the formula sort it is built over. The line's one
    literal (``⊢``) can occur many times in the string being read, so every
    occurrence is a candidate split — the case the candidate-position search
    exists for.
    """
    formula = propositional()

    line = StringPattern(name="sequent", pattern="a ⊢ b", respect_brackets=BRACKETS)
    line.add_variables({"a": formula, "b": formula})

    return line, formula


def nest(depth: int, connective: str = "→", atom: str = "p") -> str:
    """A right-nested formula of the given depth: ``(p → (p → (p → p)))``."""
    text = atom
    for _ in range(depth):
        text = f"({atom} {connective} {text})"
    return text


def balanced(depth: int, connective: str = "→", atom: str = "p") -> str:
    """A balanced formula of the given depth: both operands nest equally.

    Twice the size of a right-nest at the same depth, and the shape that punishes
    a parser which re-reads a subformula once per candidate split of its parent.
    """
    if depth == 0:
        return atom
    half = balanced(depth - 1, connective, atom)
    return f"({half} {connective} {half})"


def propositional_system():
    """A built ``FormalSystem``, for timing a whole proof rather than one parse.

    Assembled from ``tests.spec_helpers`` rather than from a copy of it here: that
    module is the repository's way of writing a ``SystemSpec``, and a second copy
    would drift. Everything a proof line costs runs through this — line-type
    parsing, rule matching, side conditions — so it is the check on whether the
    matching numbers above show up where a user would feel them.
    """
    # Imported here, not at the top: this pulls in the whole declarative builder
    # and the test helpers, which the pattern-level benchmarks have no use for.
    from website.logical.declarative import SystemSpec, build_system

    from tests.spec_helpers import (
        atom_family_prod,
        brackets,
        hyp_rule,
        mp_rule,
        statement_line,
        template_prod,
    )

    spec = SystemSpec(
        name="Propositional",
        brackets=brackets(),
        productions=[
            atom_family_prod("formula", "atom", "p"),
            template_prod("formula", "implication", "(a → b)", [("a", "formula"), ("b", "formula")]),
            template_prod("formula", "conjunction", "(a ∧ b)", [("a", "formula"), ("b", "formula")]),
            template_prod("formula", "negation", "¬a", [("a", "formula")]),
        ],
        lines=[statement_line()],
        rules=[hyp_rule(), mp_rule()],
    )

    return build_system(spec)


def modus_ponens_proof(depth: int) -> str:
    """A three-line proof whose formulas nest to `depth`.

    The premise, the implication and the conclusion are all read as formulas, and
    the rule's own schema is matched against each — so one proof exercises the
    parse several times over at whatever size `depth` sets.
    """
    antecedent = balanced(depth, connective="∧")
    consequent = balanced(depth, connective="∧", atom="p_1")

    return "\n".join([
        f"{antecedent} [HYP]",
        f"({antecedent} → {consequent}) [HYP]",
        f"{consequent} [MP, 1, 2]",
    ])


def metavariable_context(sort: UnionPattern, count: int) -> Context:
    """A context declaring `count` metavariables of `sort`.

    A rule schema is parsed with its metavariables in scope, and the search
    consults every one of them at every position it considers a variable — so how
    many are declared is itself a parameter of the cost.
    """
    context = Context()
    context.string_variables = {f"m{i}": sort for i in range(count)}
    return context
