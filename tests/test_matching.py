import pytest

pytest.importorskip("regex")

from website.logical.matching import (
    Condition,
    Context,
    MatchSet,
    RegexPattern,
    StringPattern,
    UnionPattern,
    constant,
    parse_path,
)


@pytest.fixture
def context():
    return Context()


@pytest.fixture
def word():
    return RegexPattern(name="word", pattern="^[a-z]+$")


# ---------------------------------------------------------------------------
# parse_path
# ---------------------------------------------------------------------------


def test_parse_path_without_dots():
    assert parse_path("simple") == ("simple", None)


def test_parse_path_splits_on_first_dot():
    assert parse_path("a.b.c") == ("a", "b.c")


def test_parse_path_ignores_dots_inside_brackets():
    assert parse_path("fn(a.b).c") == ("fn(a.b)", "c")
    assert parse_path("fn(a.b)") == ("fn(a.b)", None)


# ---------------------------------------------------------------------------
# constant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s,expected",
    [
        ("True", True),
        ("False", False),
        ("set()", set()),
        ("tuple()", tuple()),
        ("list()", []),
        ("[]", []),
        ("dict()", {}),
        ("{}", {}),
        ("42", 42),
        ("3.5", 3.5),
        ("'hi'", "hi"),
        ('"hi"', "hi"),
    ],
)
def test_constant_values(s, expected):
    assert constant(s) == expected


def test_constant_match_set():
    result = constant("MatchSet()")
    assert isinstance(result, MatchSet)
    assert len(result) == 0


def test_constant_returns_none_for_non_constants():
    assert constant("unquoted") is None
    assert constant("None") is None


# ---------------------------------------------------------------------------
# Condition parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "string,expected_type",
    [
        ("a and b", "and"),
        ("a or b", "or"),
        ("not a", "not"),
        ("x in y", "in"),
        ("x not in y", "not in"),
        ("a is b", "is"),
        ("a is not b", "is not"),
        ("x == y", "equals"),
        ("(a and b)", "brackets"),
        ("plain", "atomic"),
    ],
)
def test_condition_types(string, expected_type):
    assert Condition(string=string).type == expected_type


def test_condition_sub_items_for_in():
    condition = Condition(string="x in y")
    assert condition.sub_items == ["x", "y"]


def test_condition_sub_items_for_equals():
    condition = Condition(string="x == y")
    assert condition.sub_items == ("x", "y")


def test_condition_atomic_flags():
    assert Condition(string="x in y").is_atomic() is True
    assert Condition(string="plain").is_atomic() is True
    assert Condition(string="a and b").is_atomic() is False


def test_condition_mismatched_parentheses_raise():
    with pytest.raises(Exception, match="mismatched parentheses"):
        Condition(string="(a and b")

    with pytest.raises(Exception, match="mismatched parentheses"):
        Condition(string="a) and b")


def test_condition_conjunctive_parts():
    condition = Condition(string="a and b and c")
    assert sorted(part.string for part in condition.conjunctive_parts()) == [
        "a",
        "b",
        "c",
    ]


def test_condition_single_conjunctive_part():
    condition = Condition(string="a or b")
    assert condition.conjunctive_parts() == {condition}


def test_condition_equivalent_compares_strings():
    context = Context()
    assert Condition(string="a in b").equivalent(Condition(string="a in b"), context)
    assert not Condition(string="a in b").equivalent(
        Condition(string="a in c"), context
    )


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


def test_match_contains_submatch(word, context):
    pattern = StringPattern(name="if_pattern", pattern="if s:", variables={"s": word})
    match = pattern.match("if hello:", context)

    assert match.contains(word.match("hello", context), context)
    assert not match.contains(word.match("zzz", context), context)


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
