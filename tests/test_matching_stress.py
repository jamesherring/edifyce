"""Stress tests for the ``StringPattern`` split search.

``StringPattern.match`` reads a template with named slots — ``(a → b)`` — by
placing the template's literals in the string and parsing what falls between them
at the slots' declared sorts. Which splits it *tries* is the whole cost of a
parse, and the tests here pin down both halves of that:

* **What it reads.** A hand-written reference matcher (:func:`reference_reads`)
  enumerates every split with no pruning whatsoever, and the two are compared
  over a few hundred generated strings. Every prune in the real search is a claim
  that some split cannot match; this is what would catch one of those claims
  being wrong.
* **How much it reads.** Reading a nested formula must cost one parse per
  *subformula*, not one per candidate split of every subformula. That is asserted
  by counting parses rather than by timing, so it holds on a loaded machine and
  says exactly which property regressed.

``tests/test_matching.py`` covers the ordinary behaviour of the pattern classes;
this module is about the search under load and at its edges.
"""

from __future__ import annotations

import random
from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.matching import (
    AtomPattern,
    Context,
    StringPattern,
    UnionPattern,
    patterns as patterns_module,
)

BRACKETS = {"(": ")"}


# ---------------------------------------------------------------------------
# Grammars
# ---------------------------------------------------------------------------


def propositional(connectives=("→", "∧"), atoms="pq", brackets=BRACKETS):
    """A formula sort: binary connectives over an atom family."""
    formula = UnionPattern(name="formula", patterns=[], respect_brackets=brackets)

    opening = next(iter(brackets)) if brackets else "("
    closing = brackets[opening] if brackets else ")"

    compounds = [
        StringPattern(
            name=f"binary_{symbol}",
            pattern=f"{opening}a {symbol} b{closing}",
            respect_brackets=brackets,
        )
        for symbol in connectives
    ]

    for compound in compounds:
        formula.add_pattern(compound)

    for base in atoms:
        formula.add_pattern(AtomPattern(name=f"atom_{base}", base=base))

    for compound in compounds:
        compound.add_variables({"a": formula, "b": formula})

    return formula


def balanced(depth, connective="→", atom="p"):
    """A formula nesting equally on both sides: ``((p → p) → (p → p))``."""
    if depth == 0:
        return atom
    half = balanced(depth - 1, connective, atom)
    return f"({half} {connective} {half})"


def sequent_context() -> tuple[StringPattern, UnionPattern]:
    """``Γ ⊢ φ`` over a **left-nested** context list, as S1's system declares it.

    ``context ::= ∅ | wff | context , wff`` — recursive on the left, so the sort
    re-enters itself at every comma. Returns the line and the context sort.
    """
    formula = propositional()

    context = UnionPattern(name="context", patterns=[], respect_brackets=BRACKETS)
    cons = StringPattern(name="cons", pattern="g , a", respect_brackets=BRACKETS)
    cons.add_variables({"g": context, "a": formula})
    context.add_pattern(AtomPattern(name="empty", value="∅"))
    context.add_pattern(formula)
    context.add_pattern(cons)

    line = StringPattern(name="sequent", pattern="g ⊢ p", respect_brackets=BRACKETS)
    line.add_variables({"g": context, "p": formula})
    return line, context


def assumptions_text(count: int, atom: str = "p") -> str:
    """``∅ , p , p , …`` — a context of ``count`` assumptions."""
    text = "∅"
    for _ in range(count):
        text = f"{text} , {atom}"
    return text


@pytest.fixture
def context():
    return Context()


# ---------------------------------------------------------------------------
# A reference matcher: every split, no pruning
# ---------------------------------------------------------------------------


def reference_reads(sort, s):
    """Whether `s` is in the language `sort` generates, by exhaustive search.

    Deliberately naive and deliberately independent of the engine: a union tries
    every member, an atom is a token test, and a template is split every way there
    is. Nothing here knows about brackets, candidate positions, literal ordering
    or memos — which is the point, since those are what the real search prunes by.
    """
    if isinstance(sort, UnionPattern):
        return any(reference_reads(member, s) for member in sort.patterns)

    if isinstance(sort, AtomPattern):
        return sort.is_member(s)

    return _reference_template(sort, s, 0, 0, {})


def _reference_template(pattern, s, start, segment, bound):
    segments = pattern.segments

    if segment == len(segments):
        return start == len(s)

    kind, text, sort, size = segments[segment]

    if kind == patterns_module._LITERAL:
        if not s.startswith(text, start):
            return False
        return _reference_template(pattern, s, start + size, segment + 1, bound)

    # A slot: try every length of substring it could take, shortest first.
    for end in range(start, len(s) + 1):
        piece = s[start:end]

        if text in bound and bound[text] != piece:
            continue

        if not reference_reads(sort, piece):
            continue

        if _reference_template(pattern, s, end, segment + 1, {**bound, text: piece}):
            return True

    return False


def generated_strings(count, seed=20260725):
    """Formulas, and formulas with something done to them.

    Half the corpus is generated *from* the grammar, so the two matchers are
    compared on strings that genuinely parse; the other half is those same
    formulas with a character dropped, doubled or swapped. A near-miss is where a
    pruning bug hides — a split wrongly ruled out shows up as a formula that
    stops parsing, and a split wrongly allowed as a mangling that starts. Token
    soup would be rejected on the first literal and prove nothing either way.
    """
    rng = random.Random(seed)
    alphabet = "()pq_01 →∧"

    def formula(depth):
        if depth == 0 or rng.random() < 0.3:
            return rng.choice(["p", "q", f"p_{rng.randint(0, 9)}"])
        return f"({formula(depth - 1)} {rng.choice('→∧')} {formula(depth - 1)})"

    def mangle(text):
        if not text:
            return text

        at = rng.randrange(len(text))
        how = rng.randrange(3)

        if how == 0:
            return text[:at] + text[at + 1:]
        if how == 1:
            return text[:at] + text[at] + text[at:]
        return text[:at] + rng.choice(alphabet) + text[at + 1:]

    seen = []
    for _ in range(count // 2):
        # Capped in size because the reference is exponential in the slots it
        # splits across, and a corpus that takes a minute would be dropped.
        text = formula(rng.randint(0, 3))[:24]
        seen.append(text)

        mangled = text
        for _ in range(rng.randint(1, 2)):
            mangled = mangle(mangled)
        seen.append(mangled)

    return seen


def test_the_search_reads_exactly_what_an_exhaustive_split_reads(context):
    formula = propositional()

    disagreements = [
        text for text in generated_strings(400)
        if (formula.match(text, context) is not None) != reference_reads(formula, text)
    ]

    assert disagreements == []


# ---------------------------------------------------------------------------
# Cost: one parse per subformula, not per candidate split
# ---------------------------------------------------------------------------


def count_parses(monkeypatch):
    """Count the sort-level parses a match performs, keyed by nothing but volume.

    A union's ``_match`` is the unit of work worth counting: it is entered once
    per *distinct* substring the search decides to read (the memo collapses the
    repeats), so its total is exactly "how many different ways did this consider
    cutting the formula up".
    """
    counted = {"n": 0}
    original = UnionPattern._match

    def counting(self, *args, **kwargs):
        counted["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(UnionPattern, "_match", counting)
    return counted


@pytest.mark.parametrize("depth", [4, 5, 6, 7])
def test_a_nested_formula_costs_one_parse_per_subformula(depth, monkeypatch):
    # The property the split search exists to have: a formula nesting `depth` deep
    # is read at `depth` sorts, not at one sort per separator in it. A depth-7
    # formula is 763 characters with 127 occurrences of the connective, and every
    # one of them used to be a split worth parsing.
    formula = propositional()
    text = balanced(depth)

    context = Context()
    context.parse_memo = {}

    counted = count_parses(monkeypatch)

    assert formula.match(text, context) is not None

    # One per level, plus the whole string and a little slack. The number that
    # matters is that this does not scale with `len(text)`, which doubles with
    # every level.
    assert counted["n"] <= depth + 4


def test_a_deep_formula_reads_to_the_right_shape(context):
    # Depth is not only a cost question: the parse has to come back correct.
    depth = 8
    formula = propositional()

    context.parse_memo = {}
    match = formula.match(balanced(depth), context)

    assert match is not None

    # A union wraps its member's parse, keyed by the member's name, so each level
    # of the formula is two levels of the match.
    levels = 0
    while match.sub_matches:
        member = next(iter(match.sub_matches.values()))

        if "a" not in member.sub_matches:
            match = member
            break

        levels += 1
        match = member.sub_matches["a"]

    assert levels == depth
    assert match.string == "p"


# ---------------------------------------------------------------------------
# Edges of the search
# ---------------------------------------------------------------------------


def test_a_repeated_slot_must_take_the_same_text(context):
    formula = propositional()

    same = StringPattern(name="same", pattern="(a = a)", respect_brackets=BRACKETS)
    same.add_variables({"a": formula})

    assert same.match("(p = p)", context) is not None
    assert same.match("((p → q) = (p → q))", context) is not None
    assert same.match("(p = q)", context) is None
    assert same.match("((p → q) = (q → p))", context) is None


def test_a_repeated_slot_records_one_sub_match(context):
    formula = propositional()

    same = StringPattern(name="same", pattern="(a = a)", respect_brackets=BRACKETS)
    same.add_variables({"a": formula})

    match = same.match("(p = p)", context)

    assert list(match.sub_matches) == ["a"]
    assert match.sub_matches["a"].string == "p"


def test_slots_with_nothing_between_them(context):
    # Two slots side by side: no literal narrows the boundary, so every position
    # between them is a candidate and the search has to try them.
    term = UnionPattern(name="term", patterns=[], respect_brackets={"[": "]"})

    pair = StringPattern(name="pair", pattern="[ab]", respect_brackets={"[": "]"})
    term.add_pattern(pair)

    for base in "xy":
        term.add_pattern(AtomPattern(name=f"atom_{base}", base=base))

    pair.add_variables({"a": term, "b": term})

    assert term.match("[xy]", context) is not None
    assert term.match("[[xy]x]", context) is not None
    assert term.match("[x[yx]]", context) is not None
    assert term.match("[x]", context) is None
    assert term.match("[xyx]", context) is None


def test_a_separator_inside_an_operand_is_not_a_split(context):
    # The left operand contains the very connective the template splits on. The
    # first occurrence is inside it, so a search that split there would read
    # `(p` as a formula; it must go on to the one that separates the operands.
    formula = propositional()

    match = formula.match("((p → q) → p)", context)

    assert match is not None

    # `formula` is a union, so its parse wraps the production that read the string
    slots = next(iter(match.sub_matches.values())).sub_matches

    assert slots["a"].string == "(p → q)"
    assert slots["b"].string == "p"


def test_a_grammar_with_several_bracket_pairs(context):
    # More than one pair, so the search cannot reduce a delimiter to a depth
    # counter and has to match openings to closings.
    pairs = {"(": ")", "[": "]"}
    formula = propositional(brackets=pairs)

    listed = StringPattern(name="listed", pattern="[a, b]", respect_brackets=pairs)
    listed.add_variables({"a": formula, "b": formula})

    assert listed.match("[p, q]", context) is not None
    assert listed.match("[(p → q), q]", context) is not None
    assert listed.match("[(p → q], q)", context) is None
    assert listed.match("[p, q)", context) is None


def test_multi_character_delimiters_still_check(context):
    # Delimiters longer than a character get no bracket profile, so the search
    # falls back to the general scan and to trying every candidate split. It must
    # still read the same strings.
    pairs = {"begin ": " end"}
    formula = UnionPattern(name="formula", patterns=[], respect_brackets=pairs)

    grouped = StringPattern(name="grouped", pattern="begin a end", respect_brackets=pairs)
    formula.add_pattern(grouped)
    formula.add_pattern(AtomPattern(name="atom_p", base="p"))
    grouped.add_variables({"a": formula})

    assert formula.match("begin p end", context) is not None
    assert formula.match("begin begin p end end", context) is not None
    assert formula.match("begin p", context) is None


def test_a_slot_whose_sort_declares_no_brackets(context):
    # The template respects brackets but the slot's sort does not, so nothing
    # licenses skipping a split that leaves the slot unbalanced. The search has to
    # notice that and offer every candidate.
    word = UnionPattern(name="word", patterns=[])
    word.add_pattern(AtomPattern(name="open", value="("))
    word.add_pattern(AtomPattern(name="close", value=")"))

    quoted = StringPattern(name="quoted", pattern="(a b)", respect_brackets=BRACKETS)
    quoted.add_variables({"a": word, "b": word})

    # The string balances; neither slot's text does, and the sort takes them both.
    match = quoted.match("(( ))", context)

    assert match is not None
    assert match.sub_matches["a"].string == "("
    assert match.sub_matches["b"].string == ")"


def test_the_split_filter_stands_down_for_a_bracketed_metavariable(context):
    # A union answers a declared metavariable by *name*, before it looks at
    # brackets - so a metavariable spelled with one could be read where an
    # unbalanced split would otherwise be dismissed unparsed. Rare to the point of
    # perverse, and the search checks for it rather than assuming it away.
    formula = propositional()

    template = StringPattern(name="template", pattern="(a → b)", respect_brackets=BRACKETS)
    template.add_variables({"a": formula, "b": formula})

    plain = copy(context)
    plain.string_variables = {"φ": formula}
    assert template._sort_refuses_unbalanced(formula, plain) is True

    bracketed = copy(context)
    bracketed.string_variables = {")(": formula}
    assert template._sort_refuses_unbalanced(formula, bracketed) is False


def test_matching_resumes_from_a_template_offset(context):
    # `pattern_offset` reads a string against the template's tail. It survives the
    # move to segments: an offset that lands on a segment boundary resolves, and
    # one that lands inside a literal is an error rather than a silent mismatch.
    formula = propositional()

    template = StringPattern(name="template", pattern="(a → b)", respect_brackets=BRACKETS)
    template.add_variables({"a": formula, "b": formula})

    # The template from the slot `b` on, which is at offset 5 of `(a → b)`.
    assert template.match("q)", context, pattern_offset=5) is not None
    assert template.match("q", context, pattern_offset=5) is None

    with pytest.raises(ValueError):
        template.match("q)", context, pattern_offset=3)


def test_a_metavariable_fills_a_slot_whole(context):
    # A rule schema is read with its metavariables in scope, and one of them is
    # taken for the whole slot rather than parsed as a formula that happens to
    # start with its name.
    formula = propositional()

    template = StringPattern(name="template", pattern="(a → b)", respect_brackets=BRACKETS)
    template.add_variables({"a": formula, "b": formula})

    scoped = copy(context)
    scoped.string_variables = {"φ": formula, "ψ": formula}

    match = template.match("(φ → ψ)", scoped)

    assert match is not None
    assert match.sub_matches["a"].is_variable is True
    assert match.sub_matches["b"].string == "ψ"


def test_many_metavariables_do_not_change_what_parses(context):
    # The scan over what is in scope runs at every position the search considers a
    # slot, so how many are declared is a cost - never an answer.
    formula = propositional()

    template = StringPattern(name="template", pattern="(a → b)", respect_brackets=BRACKETS)
    template.add_variables({"a": formula, "b": formula})

    crowded = copy(context)
    crowded.string_variables = {f"m{i}": formula for i in range(200)}

    assert template.match("(m7 → m199)", crowded) is not None
    assert template.match("((p → q) → m0)", crowded) is not None
    assert template.match("(m200 → p)", crowded) is None


@pytest.mark.parametrize("assumptions", [4, 8, 12, 16])
def test_a_left_nested_context_costs_one_parse_per_assumption(
    assumptions: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S1's grammar, and the property that makes it usable at all. A sequent's
    # context is `∅ | wff | context , wff` — recursive on the *left*, so every
    # comma in the string is a candidate split and the sort re-enters itself at
    # each one. The roadmap made an AC matcher (S4) conditional on measuring
    # this, because a left-nested list is the shape this layer is slowest on.
    #
    # Measured: with the memo a context of *n* assumptions costs ~n parses; a
    # timing run without one goes 41 µs → 2.5 ms → 0.7 s → 4.8 min at 2, 8, 16
    # and 24 assumptions, which is ×4 per two assumptions. So the memo is not an
    # optimisation here, it is what makes the grammar viable — and
    # `LineType.parse_line` gives every proof line a fresh one, which is why a
    # real proof gets the linear column.
    #
    # Counted rather than timed, as the nesting case above is: a count says
    # which property regressed and holds on a loaded machine.
    line, _ = sequent_context()
    text = f"{assumptions_text(assumptions)} ⊢ p"

    context = Context()
    context.parse_memo = {}

    counted = count_parses(monkeypatch)

    assert line.match(text, context) is not None

    # Two sorts per assumption and a little slack — what matters is that it does
    # not scale with the *number of ways* the commas could be cut up.
    assert counted["n"] <= 2 * assumptions + 8
