import pytest

pytest.importorskip("regex")

from website.logical.matching import (
    Context,
    RegexPattern,
    StringPattern,
    UnionPattern,
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
