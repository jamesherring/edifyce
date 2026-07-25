from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.matching import (
    AtomPattern,
    Context,
    RegexPattern,
    StringPattern,
    UnionPattern,
    patterns as patterns_module,
)


@pytest.fixture
def context():
    return Context()


@pytest.fixture
def word():
    return RegexPattern(name="word", pattern="^[a-z]+$")


# ---------------------------------------------------------------------------
# RegexPattern
# ---------------------------------------------------------------------------


def test_regex_pattern_match(word, context):
    match = word.match("hello", context)
    assert match is not None
    assert match.string == "hello"
    assert match.pattern is word


def test_regex_pattern_no_match(word, context):
    assert word.match("HELLO", context) is None


# ---------------------------------------------------------------------------
# StringPattern
# ---------------------------------------------------------------------------


def test_string_pattern_match_extracts_variables(word, context):
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": word})

    match = pattern.match("if hello:", context)
    assert match is not None
    assert match.string == "if hello:"
    assert set(match.sub_matches) == {"s"}
    assert match.sub_matches["s"].string == "hello"


def test_string_pattern_no_match(word, context):
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": word})
    assert pattern.match("while hello:", context) is None


def test_long_strings_match_without_a_length_limit(context):
    # The retired `pre_format` hook ran every candidate string through a rewriter
    # that raised above 1000 characters. Since the engine always passed it an
    # empty (but non-None) dictionary, that limit applied to *every* match, so a
    # long-but-legitimate formula was rejected with an incomprehensible error.
    # Matching must have no length ceiling.
    long_word = "a" * 5000
    word = RegexPattern(name="word", pattern="^[a-z]+$")
    assert word.match(long_word, context) is not None

    pattern = StringPattern(name="wrap", pattern="(s)", variables={"s": word})
    assert pattern.match(f"({long_word})", context) is not None

    union = UnionPattern(name="either", patterns=[word])
    assert union.match(long_word, context) is not None


# ---------------------------------------------------------------------------
# The `field` accessor (the sole surviving use of the retired interpreter)
# ---------------------------------------------------------------------------


def test_field_projects_declared_sub_match(word, context):
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": word})
    match = pattern.match("if hello:", context)
    assert match.field("s").string == "hello"


def test_field_raises_for_unknown_field(word, context):
    match = word.match("hello", context)
    with pytest.raises(KeyError):
        match.field("nope")


# ---------------------------------------------------------------------------
# UnionPattern
# ---------------------------------------------------------------------------


def test_union_pattern_matches_any_member(word, context):
    if_pattern = StringPattern(
        name="if_pattern", pattern="if s:", variables={"s": word}
    )
    union = UnionPattern(name="either", patterns=[word, if_pattern])

    match = union.match("if abc:", context)
    assert match is not None
    assert list(match.sub_matches) == ["if_pattern"]

    match = union.match("abc", context)
    assert match is not None
    assert list(match.sub_matches) == ["word"]


def test_union_pattern_no_match(word, context):
    union = UnionPattern(name="either", patterns=[word])
    assert union.match("123", context) is None


# ---------------------------------------------------------------------------
# The variable-leaf walk (what a definition reads its parameters off)
# ---------------------------------------------------------------------------


def test_variable_leaves_finds_declared_slots(word, context):
    # The slot's sort must be one that consults `string_variables` when it
    # matches - a union does, a bare regex does not (see `revariabilise`).
    sort = UnionPattern(name="term", patterns=[word])
    context.string_variables = {"phi": sort}
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": sort})

    match = pattern.match("if phi:", context)
    assert [leaf.string for leaf in match.variable_leaves()] == ["phi"]


def test_variable_leaves_is_empty_for_a_ground_parse(word, context):
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": word})

    match = pattern.match("if hello:", context)
    assert match.variable_leaves() == []


# ---------------------------------------------------------------------------
# Leading-character index over a union's leaves
# ---------------------------------------------------------------------------


def _arith_union():
    # A grammar in the shape a large import produces: a handful of compound
    # productions, and many nullary constants (set.mm has ~1,200 of them).
    plus = StringPattern(name="plus", pattern="( a + b )")
    times = StringPattern(name="times", pattern="( a * b )")
    constants = [AtomPattern(name=f"c{n}", value=str(n)) for n in range(50)]
    union = UnionPattern(name="expr", patterns=[plus, times, *constants])
    for compound in (plus, times):
        compound.add_variables({"a": union, "b": union})
    return union, plus, constants


def test_the_leaf_index_excludes_by_opening_character(context):
    union, plus, constants = _arith_union()
    _, leaves, _ = union.match_options(context)

    # A string opening `(` cannot be any of the 50 constants.
    opening_bracket = union.leaf_candidates("( 1 + 2 )", context, leaves)
    assert plus in opening_bracket
    assert not any(constant in opening_bracket for constant in constants)

    # A string opening `4` can only be the constants starting with that digit,
    # and never a compound whose template opens with `(`.
    digit = union.leaf_candidates("4", context, leaves)
    assert plus not in digit
    assert all(leaf.value.startswith("4") for leaf in digit)


def test_the_leaf_index_does_not_change_what_parses(context):
    union, _, _ = _arith_union()

    for text in ("( 1 + 2 )", "( ( 1 + 2 ) * 3 )", "7", "( 4 * ( 5 + 6 ) )"):
        assert union.match(text, context) is not None, text

    for text in ("( 1 + )", "99", "1 + 2", "( 1 ? 2 )"):
        assert union.match(text, context) is None, text


def test_a_leaf_opening_with_a_variable_is_always_a_candidate(context):
    # `a = b` can begin with anything its left operand can, so no opening
    # character may rule it out.
    union, _, constants = _arith_union()
    equals = StringPattern(name="equals", pattern="a = b")
    union.add_pattern(equals)
    equals.add_variables({"a": union, "b": union})

    _, leaves, _ = union.match_options(context)
    for character in "(4x":
        assert equals in union.leaf_candidates(character + "...", context, leaves)

    assert union.match("1 = 2", context) is not None


def test_the_leaf_index_stands_down_when_it_cannot_reason(context):
    # Two cases where a leaf can match a string its template does not predict, so
    # the index must offer every leaf rather than filter on the first character.
    union, _, _ = _arith_union()
    _, leaves, _ = union.match_options(context)

    # A bare string variable is matched by any leaf, whatever it opens with.
    variable_context = copy(context)
    variable_context.string_variables = {"n": union}
    assert union.leaf_candidates("n", variable_context, leaves) is leaves

    # With definitions in scope a leaf can match through an unfold.
    definition_context = copy(context)
    definition_context.definitions = {object()}
    assert union.leaf_candidates("( 1 + 2 )", definition_context, leaves) is leaves


def test_a_member_reshaped_after_it_joined_is_still_offered(context):
    # The index reads a member's *leading literal*, and giving a template its
    # slots rewrites that: `a = b` opens with the literal `a = b` until `a` is a
    # variable, after which it opens with anything. A union parsed against in
    # between must not keep the earlier reading, or the production silently stops
    # being tried for every string it now reads.
    union, _, _ = _arith_union()

    equals = StringPattern(name="equals", pattern="a = b")
    union.add_pattern(equals)

    # A parse here is what fills the flattening and the leading-character index.
    assert union.match("7", context) is not None

    equals.add_variables({"a": union, "b": union})

    assert union.match("1 = 2", context) is not None


def test_reshaping_a_template_outside_any_union_costs_no_invalidation(context):
    # The other half of the contract: a rule schema builds a template and parses
    # with it straight away, so invalidating on every `add_variables` would
    # re-flatten the whole grammar once per schema.
    union, _, _ = _arith_union()
    assert union.match("7", context) is not None

    before = patterns_module._union_revision

    schema = StringPattern(name="schema", pattern="( a + b )")
    schema.add_variables({"a": union, "b": union})

    assert patterns_module._union_revision == before
