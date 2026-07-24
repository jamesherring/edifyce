import pytest

pytest.importorskip("regex")

from website.logical.compiler import (
    AbstractSyntaxTree,
    compile as compile_formal_system,
    get_inherited_system,
)
from website.logical.formal_system import FormalSystem


# ---------------------------------------------------------------------------
# get_inherited_system
# ---------------------------------------------------------------------------


def test_get_inherited_system_finds_slug():
    code = "FormalSystem X:\n    inherit base-system\n"
    assert get_inherited_system(code) == "base-system"


def test_get_inherited_system_returns_none_without_inherit():
    assert get_inherited_system("FormalSystem X:\n    Regex w:\n        ^.$") is None


def test_get_inherited_system_last_inherit_wins():
    assert get_inherited_system("inherit first\ninherit second") == "second"


# ---------------------------------------------------------------------------
# AbstractSyntaxTree.valid_variable_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["good_name", "x1", "alpha", "_private"])
def test_valid_variable_names(name):
    assert AbstractSyntaxTree.valid_variable_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["123bad", "has space", "", "FormalSystem", "Abstract", "Pattern"],
)
def test_invalid_variable_names(name):
    assert AbstractSyntaxTree.valid_variable_name(name) is False


# ---------------------------------------------------------------------------
# AbstractSyntaxTree.add_lines — indentation tree building
# ---------------------------------------------------------------------------


def test_add_lines_builds_tree_by_indentation():
    root = AbstractSyntaxTree()
    root.add_lines(["parent:", "    child1", "    child2", "second_parent"])

    assert root.is_root()
    assert [t.line for t in root.sub_trees] == ["parent:", "second_parent"]

    parent = root.sub_trees[0]
    assert [t.line.strip() for t in parent.sub_trees] == ["child1", "child2"]
    assert all(t.parent is parent for t in parent.sub_trees)


def test_add_lines_tracks_line_numbers():
    root = AbstractSyntaxTree()
    root.add_lines(["parent:", "    child"])
    assert root.sub_trees[0].line_number == 1
    assert root.sub_trees[0].sub_trees[0].line_number == 2


def test_add_lines_leaf_and_root_flags():
    root = AbstractSyntaxTree()
    root.add_lines(["parent:", "    child"])
    assert root.is_root() and not root.is_leaf()
    assert root.sub_trees[0].sub_trees[0].is_leaf()


def test_add_lines_over_indented_first_line_is_an_error():
    root = AbstractSyntaxTree()
    root.add_lines(["        overindented"])
    assert root.error == "Invalid indent"


def test_add_lines_ignores_blank_lines():
    root = AbstractSyntaxTree()
    root.add_lines(["", "a", "", "b", ""])
    assert [t.line for t in root.sub_trees] == ["a", "b"]


def test_tree_str():
    root = AbstractSyntaxTree()
    root.add_lines(["parent:"])
    assert str(root) == "Tree root"
    assert str(root.sub_trees[0]) == "1: parent:"


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


VALID_SYSTEM = """FormalSystem Demo:

    Regex word:
        ^[a-z]+$

    ProofContext:
        given: MatchSet()

    Pattern if_pattern:
        with s as word:
            if s:

    LineType statement:
        pattern: word
        behaviour: none

    LineType if:
        pattern: if_pattern
        behaviour: indent
"""


def test_compile_valid_system():
    result = compile_formal_system(VALID_SYSTEM)
    assert "errors" not in result

    system = result["system"]
    assert isinstance(system, FormalSystem)
    assert system.name == "Demo"
    assert [lt.name for lt in system.line_types] == ["statement", "if"]
    assert system.inference_rules == []


def test_compile_line_type_attributes():
    system = compile_formal_system(VALID_SYSTEM)["system"]

    statement, if_line = system.line_types
    assert statement.behaviour == "none"
    assert statement.pattern.name == "word"
    assert if_line.behaviour == "indent"
    assert if_line.pattern.name == "if_pattern"


def test_context_block_on_line_type_is_rejected():
    # The `context:` line-type block (which fed a `given` MatchSet through the
    # removed `ProofLine.edit_context`) is no longer supported: it is now an
    # unrecognised line-type parameter. Part of retiring the `get_by_path`
    # string interpreter - see docs/side_condition_followups.md.
    source = """FormalSystem Demo:

    Regex word:
        ^[a-z]+$

    ProofContext:
        given: MatchSet()

    Pattern if_pattern:
        with s as word:
            if s:

    LineType if:
        pattern: if_pattern
        behaviour: indent
        context.given:
            add: s
"""
    result = compile_formal_system(source)
    assert "errors" in result
    assert any("context.given" in e for e in result["errors"])


def test_compile_inference_rule():
    system = compile_formal_system(
        """FormalSystem WithRule:

    Regex formula:
        ^[a-z]+$

    with s as formula:
        InferenceRule repetition:
            label:
                REP
            antecedents:
                s
            deduction:
                s
"""
    )["system"]

    assert len(system.inference_rules) == 1
    rule = system.inference_rules[0]
    assert rule.name == "repetition"
    assert rule.label == "REP"
    assert len(rule.antecedents) == 1
    assert rule.deduction is not None


def test_compile_comment_only_code_gives_empty_system():
    result = compile_formal_system("# only a comment\n\n")
    assert "errors" not in result
    system = result["system"]
    assert system.name == ""
    assert system.line_types == []


def test_compile_collects_errors_with_line_numbers():
    code = (
        "FormalSystem Ok:\n"
        "\n"
        "    Regex 1bad:\n"
        "        ^.+$\n"
        "\n"
        "    Pattern 2bad:\n"
        "        x"
    )
    result = compile_formal_system(code)
    assert result == {
        "errors": [
            "3: Invalid variable name: '1bad'.",
            "6: Invalid variable name: '2bad'.",
        ]
    }


def test_compile_invalid_top_level_name_is_dropped():
    # Known limitation: errors are collected by parent nodes from their
    # sub-trees, so an error on a top-level line (like an invalid
    # FormalSystem name) is never added to the error log. The declaration
    # is skipped and compilation falls back to an empty unnamed system.
    result = compile_formal_system("FormalSystem 9lives:\n    Regex w:\n        ^.$")
    assert "errors" not in result
    assert result["system"].name == ""


def test_compile_inherit_unknown_slug_is_an_error():
    result = compile_formal_system("FormalSystem A:\n\n    inherit missing-slug")
    assert result == {
        "errors": ["3: Could not find formal system with slug: missing-slug."]
    }


def test_compile_abstract_patterns():
    result = compile_formal_system(
        "FormalSystem B:\n\n    Abstract alpha, beta\n\n    Regex w:\n        ^.$"
    )
    assert "errors" not in result
    assert result["system"].name == "B"


def test_compile_unknown_top_level_line_is_lenient():
    # Content the compiler does not recognise at the top level is skipped
    # rather than reported, and yields an empty unnamed system.
    result = compile_formal_system("NotAKeyword ???:\n  broken")
    assert "errors" not in result
    assert result["system"].name == ""


# ---------------------------------------------------------------------------
# Discharge-rule guard: `.edi` rejects what the declarative model rejects
# ---------------------------------------------------------------------------

_DISCHARGE_SYSTEM = """FormalSystem Discharge:

    Regex atom:
        ^[a-z]$

    Regex reference:
        ^[A-Za-z 0-9,]+$

    UnionPattern formula:
        atom

    Pattern implication:
        with p as formula, q as formula:
            (p -> q)

    formula:
        implication

    Pattern statement_pattern:
        with f as formula, r as reference:
            f [r]

    Pattern assumption_pattern:
        with phi as formula:
            assume phi

    LineType claim:
        pattern: statement_pattern
        behaviour: logical
        formula: f
        reference: r

    LineType assume:
        pattern: assumption_pattern
        behaviour: logical
        scope: assumption
        formula: phi

    with p as formula, q as formula:
        InferenceRule conditional_proof:
            label:
                CP
            subproof:
                assume:
                    p
                derive:
                    q
            deduction:
                (p -> q)%(EXTRA)s
"""


@pytest.mark.parametrize(
    "extra",
    [
        "\n            antecedents:\n                p",
        "\n            side_conditions:\n                equal(p, q)",
    ],
    ids=["antecedents", "side_conditions"],
)
def test_discharge_rule_cannot_carry_antecedents_or_side_conditions(extra):
    # The discharge check consumes the subproof and never evaluates line
    # antecedents or side-conditions, so keeping either would leave a soundness
    # constraint the author wrote but the checker never applies. `.edi` rejects
    # the pairing exactly as declarative.build_system and the API do.
    result = compile_formal_system(_DISCHARGE_SYSTEM % {"EXTRA": extra})
    assert "errors" in result
    assert any("discharges a subproof" in e for e in result["errors"]), result["errors"]


@pytest.mark.parametrize(
    "extra",
    ["", "\n            allow_extra_antecedents:\n                True"],
    ids=["plain", "allow_extra_antecedents"],
)
def test_discharge_rule_without_a_dropped_constraint_compiles(extra):
    # The guard is scoped to constraints whose loss would be unsound. A plain
    # discharge rule compiles, and so does one carrying `allow_extra_antecedents`:
    # the discharge check ignores that flag too, but an ignored *allowance* is
    # only ever stricter, so it is inert rather than rejected.
    result = compile_formal_system(_DISCHARGE_SYSTEM % {"EXTRA": extra})
    assert "errors" not in result, result.get("errors")
