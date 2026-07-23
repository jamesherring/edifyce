import pytest

pytest.importorskip("regex")

from website.logical.matching import (
    Context,
    MatchSet,
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


def test_string_pattern_pre_format(context):
    pattern = StringPattern(name="arrow", pattern="x -> y", pre_format={"->": "→"})
    assert pattern.pre_format_apply("a -> b") == "a → b"

    match = pattern.match("x → y", context)
    assert match is not None
    assert match.string == "x → y"


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
# Match equivalence
# ---------------------------------------------------------------------------


def test_match_equivalent_same_string(word, context):
    assert word.match("same", context).equivalent(word.match("same", context), context)


def test_match_equivalent_different_string(word, context):
    assert not word.match("same", context).equivalent(
        word.match("diff", context), context
    )


def test_match_equivalent_different_pattern(word, context):
    other = RegexPattern(name="other", pattern="^[a-z]+$")
    assert not word.match("same", context).equivalent(
        other.match("same", context), context
    )


# ---------------------------------------------------------------------------
# MatchSet
# ---------------------------------------------------------------------------


def test_match_set_starts_empty_and_complete():
    match_set = MatchSet()
    assert len(match_set) == 0
    assert match_set.complete is True


def test_match_set_add_and_contains(word, context):
    match_set = MatchSet()
    match_set.add(word.match("aaa", context), context)
    match_set.add(word.match("bbb", context), context)

    assert len(match_set) == 2
    assert match_set.contains(word.match("aaa", context), context)
    assert not match_set.contains(word.match("zzz", context), context)


def test_match_set_remove(word, context):
    match_set = MatchSet()
    match_set.add(word.match("aaa", context), context)
    match_set.remove(word.match("aaa", context), context)

    assert len(match_set) == 0
    assert not match_set.contains(word.match("aaa", context), context)


def test_match_set_union(word, context):
    first = MatchSet()
    first.add(word.match("aaa", context), context)

    second = MatchSet()
    second.add(word.match("bbb", context), context)

    combined = first.union(second, context)
    assert len(combined) == 2
    assert combined.contains(word.match("aaa", context), context)
    assert combined.contains(word.match("bbb", context), context)
