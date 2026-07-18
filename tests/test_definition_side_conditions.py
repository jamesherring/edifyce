"""Definition guards expressed in the restricted `SideCondition` algebra.

A definition's optional `if <guard>` clause is now parsed through the same
closed vocabulary as a rule's `side_conditions:` block, stored on the
`matching.Definition` as a kernel `SideCondition`, and evaluated against a
kernel-term binding projected (via `from_match`) from the matched variables.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.compiler import compile as compile_formal_system
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import DisjointLeaves


# A base system that supplies the sorts/patterns; the definitions under test are
# added directly so the test does not depend on where compilation stores them.
SYSTEM = """FormalSystem Guarded:

    Regex setvar:
        ^[a-z]$

    Pattern membership:
        with x as setvar, y as setvar:
            x is an element of y

    UnionPattern formula:
        membership

    Pattern subset:
        with x as setvar, y as setvar:
            x is a subset of y

    formula:
        subset
"""


@pytest.fixture(scope="module")
def env():
    result = compile_formal_system(SYSTEM)
    assert "errors" not in result, result.get("errors")
    system = result["system"]
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    context.string_variables = {"x": system.build_context.variables["setvar"],
                                "y": system.build_context.variables["setvar"]}
    return system, context


def _make_definition(env, guard):
    system, context = env
    subset = system.build_context.variables["subset"]
    side_condition = parse_side_condition(guard, context) if guard is not None else None
    defn = subset.add_definition(
        "x is an element of y", "x is a subset of y", context,
        side_condition=side_condition, condition_string=guard,
        require_lower_match=False,
    )
    assert defn is not None
    return defn


def test_guard_is_stored_as_a_side_condition(env):
    defn = _make_definition(env, "disjoint(x, y, setvar)")
    assert isinstance(defn.side_condition, DisjointLeaves)
    assert defn.condition_string == "disjoint(x, y, setvar)"


def test_guard_admits_when_it_holds_and_rejects_when_violated(env):
    system, context = env
    setvar = system.build_context.variables["setvar"]
    defn = _make_definition(env, "disjoint(x, y, setvar)")
    sc = defn.side_condition

    holds = {sc.left: setvar.match("a", context), sc.right: setvar.match("b", context)}
    violates = {sc.left: setvar.match("a", context), sc.right: setvar.match("a", context)}

    assert defn._condition_holds(holds, context) is True
    assert defn._condition_holds(violates, context) is False


def test_negated_guard_inverts(env):
    system, context = env
    setvar = system.build_context.variables["setvar"]
    defn = _make_definition(env, "not disjoint(x, y, setvar)")
    sc = defn.side_condition
    same = {"x": setvar.match("a", context), "y": setvar.match("a", context)}
    distinct = {"x": setvar.match("a", context), "y": setvar.match("b", context)}
    assert defn._condition_holds(same, context) is True
    assert defn._condition_holds(distinct, context) is False


def test_missing_binding_fails_closed(env):
    defn = _make_definition(env, "disjoint(x, y, setvar)")
    # A binding that never bound the guard's variables must not admit the guard.
    assert defn._condition_holds({}, context=env[1]) is False


def test_guard_evaluates_against_a_real_match_binding(env):
    # The names in the parsed guard must line up with the keys of a real
    # higher-form match's sub_matches - the exact mapping check_application feeds
    # to _condition_holds. This is the end-to-end alignment the other tests
    # (which hand-build the binding) do not cover.
    system, context = env
    defn = _make_definition(env, "disjoint(x, y, setvar)")

    distinct = defn.higher.match("a is a subset of b", context)
    clash = defn.higher.match("a is a subset of a", context)
    assert distinct is not None and clash is not None

    assert defn._condition_holds(distinct.sub_matches, context) is True
    assert defn._condition_holds(clash.sub_matches, context) is False


def test_guard_ignores_unreferenced_bindings(env):
    # A binding entry the guard does not reference must not sink the check, even
    # if it could not be projected into a term.
    system, context = env
    setvar = system.build_context.variables["setvar"]
    defn = _make_definition(env, "disjoint(x, y, setvar)")
    mapping = {
        "x": setvar.match("a", context),
        "y": setvar.match("b", context),
        "junk": object(),  # unreferenced and unprojectable
    }
    assert defn._condition_holds(mapping, context) is True


def test_equivalent_with_multipart_and_guard_does_not_crash(env):
    # A conjunction whose parts' normal forms tie until the sort position (None
    # vs a sort name) must compare without raising - regression for the sorted()
    # TypeError in normal_form.
    from website.logical.kernel import And, DisjointLeaves

    system, context = env
    setvar = system.build_context.variables["setvar"]
    subset = system.build_context.variables["subset"]
    guard = And((DisjointLeaves("x", "y"), DisjointLeaves("x", "y", setvar)))

    def make():
        return subset.add_definition(
            "x is an element of y", "x is a subset of y", context,
            side_condition=guard, condition_string="disjoint(x, y)\ndisjoint(x, y, setvar)",
            require_lower_match=False,
        )

    assert make().equivalent(make(), context)


def test_equivalent_distinguishes_definitions_by_guard(env):
    _system, context = env
    guarded = _make_definition(env, "disjoint(x, y, setvar)")
    plain = _make_definition(env, None)
    assert not guarded.equivalent(plain, context)
    assert not plain.equivalent(guarded, context)

    same = _make_definition(env, "disjoint(x, y, setvar)")
    assert guarded.equivalent(same, context)


def test_malformed_guard_is_a_compile_error():
    guarded_source = SYSTEM.replace(
        "        x is a subset of y\n",
        "        x is a subset of y\n"
        "        Define x is a subset of y as x is an element of y if bogus(x, y)\n",
    )
    result = compile_formal_system(guarded_source)
    assert "errors" in result
    assert any("guard" in e.lower() or "bogus" in e.lower() for e in result["errors"])
