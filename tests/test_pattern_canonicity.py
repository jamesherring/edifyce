"""A built system's productions are canonical: one object per production.

Sort admission (``unify.sort_admits``) is a set lookup keyed on constructor
identity, and a constructor is built once per production. That is only correct
if two structurally equivalent productions are always the *same object* — if a
system could hold two distinct-but-equal ``formula`` unions, a term built
through one would be refused where the other was expected.

Nothing in the engine copies a production any more. It used to:
``FormalSystemContext.inherit`` handed every union a ``deepcopy`` of itself, and
``Pattern.can_map_to`` existed to walk the resulting chain. Nothing called
``inherit``, so the copies were never made and the machinery was deleted — these
tests are what stops it coming back by accident.

The second half covers the other side of the same boundary: that the projection
is *total*. ``kernel.constructors`` reads a ``Pattern``; nothing it hands back
holds one, so a term and everything reachable from it is kernel data. Which is
also why the build must project each sort only once its branches are known — a
constructor resolves them when it is made, not on demand.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from tests.spec_helpers import (
    brackets,
    conjunction_prod,
    hyp_rule,
    implication_prod,
    membership_prod,
    mp_rule,
    statement_line,
    subset_def,
    universal_prod,
    variable_prod,
)
from website.logical.declarative import LinePart, LineSpec, SystemSpec, build_spec
from website.logical.kernel import from_match
from website.logical.kernel.constructors import Constructor, constructor_for
from website.logical.kernel.terms import Node, Term
from website.logical.matching.patterns import Pattern, StringPattern, UnionPattern


def zfc_spec() -> SystemSpec:
    return SystemSpec(
        name="ZFC",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod(),
                     universal_prod(), conjunction_prod()],
        lines=[statement_line()],
        rules=[hyp_rule(), mp_rule()],
        definitions=[subset_def()],
    )


def reachable_patterns(system) -> list:
    """Every pattern reachable from the system's namespaces."""
    found: dict[int, object] = {}

    def walk(pattern) -> None:
        if id(pattern) in found:
            return
        found[id(pattern)] = pattern
        if isinstance(pattern, UnionPattern):
            for member in pattern.patterns:
                walk(member)
        if isinstance(pattern, StringPattern):
            for info in pattern.variable_locations.values():
                walk(info["pattern"])
            for sub in pattern.variables.values():
                walk(sub)

    for context in (system.context, system.build_context):
        for value in context.variables.values():
            if hasattr(value, "pattern_type"):
                walk(value)
        for notation in context.definitions:
            walk(notation.template)
            walk(notation.sort)

    return list(found.values())


@pytest.fixture(scope="module")
def system():
    result = build_spec(zfc_spec())
    assert "errors" not in result, result.get("errors")
    return result["system"]


def test_no_two_distinct_productions_are_equivalent(system):
    # The invariant sort admission rests on: structural equivalence coincides
    # with object identity, so a set keyed on identity decides it exactly.
    patterns = reachable_patterns(system)
    assert len(patterns) > 1

    equivalent_pairs = [
        (a.name, b.name)
        for i, a in enumerate(patterns)
        for b in patterns[i + 1:]
        if a.equivalent(b, system.context)
    ]
    assert equivalent_pairs == []


def test_each_production_name_binds_one_object(system):
    by_name: dict[str, list] = {}
    for pattern in reachable_patterns(system):
        by_name.setdefault(pattern.name, []).append(pattern)

    duplicated = {name: len(group) for name, group in by_name.items() if len(group) > 1}
    assert duplicated == {}


def test_two_lines_declaring_the_identical_part_share_one_production():
    # Line parts are registered per line, so a second line *rebinds* the name —
    # deliberately, since two lines may spell the same part differently. Declaring
    # the identical part twice is not that case, and must not mint a second
    # object: two equivalent-but-distinct productions break the identity that
    # sort admission decides on.
    shared = LinePart(name="reference", regex="[A-Za-z0-9, ]+")
    spec = SystemSpec(
        name="Parts",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod()],
        lines=[
            LineSpec(name="claim", shape="<formula> [<reference>]",
                     parts=[shared], logical_sort="formula"),
            LineSpec(name="restate", shape="also <formula> [<reference>]",
                     parts=[LinePart(name=shared.name, regex=shared.regex)],
                     logical_sort="formula"),
        ],
        rules=[hyp_rule()],
    )
    result = build_spec(spec)
    assert "errors" not in result, result.get("errors")
    built = result["system"]

    parts = {
        id(info["pattern"]): info["pattern"]
        for line_type in built.line_types
        for info in line_type.pattern.variable_locations.values()
        if info["pattern"].name == "reference"
    }
    assert len(parts) == 1

    # Both lines still parse — sharing the production changed nothing observable.
    assert built.parse("x ∈ y [HYP]").valid is True
    assert built.parse("also x ∈ y [HYP]").valid is True


def test_two_lines_may_still_spell_the_same_part_differently():
    # The rebind this shares an object with must not become a blanket dedup: two
    # lines naming one part with *different* regexes keep their own.
    spec = SystemSpec(
        name="PartsDiffer",
        brackets=brackets(),
        productions=[variable_prod(), membership_prod(), implication_prod()],
        lines=[
            LineSpec(name="claim", shape="<formula> [<reference>]",
                     parts=[LinePart(name="reference", regex="[A-Za-z0-9, ]+")],
                     logical_sort="formula"),
            LineSpec(name="restate", shape="also <formula> [<reference>]",
                     parts=[LinePart(name="reference", regex="[0-9]+")],
                     logical_sort="formula"),
        ],
        rules=[hyp_rule()],
    )
    result = build_spec(spec)
    assert "errors" not in result, result.get("errors")
    built = result["system"]

    parts = {
        id(info["pattern"])
        for line_type in built.line_types
        for info in line_type.pattern.variable_locations.values()
        if info["pattern"].name == "reference"
    }
    assert len(parts) == 2

    # And `claim` kept its own, wider regex — the alphabetic citation still parses.
    assert built.parse("x ∈ y [HYP]").valid is True


def test_copying_a_context_shares_its_productions(system):
    # Contexts are copied all over the engine (per proof line, per rule, per
    # side condition). Every one of those copies must keep the *same* production
    # objects, or admission sets built against one would not recognise the other.
    duplicate = copy(system.context)
    for name, pattern in system.context.variables.items():
        assert duplicate.variables[name] is pattern


# ---------------------------------------------------------------------------
# What the invariant buys: admission is exactly membership
# ---------------------------------------------------------------------------


def test_admission_set_is_the_sort_and_its_branches(system):
    formula = system.context.variables["formula"]
    admits = constructor_for(formula).admits

    # A union admits itself and each of its branches...
    assert constructor_for(formula) in admits
    for member in formula.patterns:
        assert constructor_for(member) in admits

    # ...and nothing outside the grammar.
    stranger = UnionPattern(name="formula", patterns=list(formula.patterns))
    assert constructor_for(stranger) not in admits


def test_a_leaf_sort_admits_only_itself(system):
    variable = system.context.variables["variable"]
    assert constructor_for(variable).admits == frozenset({constructor_for(variable)})


def test_the_build_projects_each_sort_with_its_branches(system):
    # A sort's branches are resolved when it is projected, so a union projected
    # while still empty would admit nothing but itself for the rest of the
    # system's life. `build_system` projects the grammar explicitly, after the
    # step that fills the unions, so every declared sort arrives complete.
    for name, pattern in system.context.variables.items():
        if not isinstance(pattern, UnionPattern):
            continue
        constructor = constructor_for(pattern)
        assert len(constructor.members) == len(pattern.patterns), name
        for member in pattern.patterns:
            assert constructor_for(member) in constructor.admits


def test_projecting_an_unfilled_sort_raises_rather_than_sealing_it_empty(system):
    # Branches are resolved once, at projection, so projecting an unfilled union
    # would seal it admitting nothing but itself — a system that builds and then
    # refuses valid proofs. A sort with no productions cannot be declared, so this
    # can only mean the ordering went wrong, and it fails loudly.
    with pytest.raises(ValueError, match="before its productions"):
        constructor_for(UnionPattern(name="late", patterns=[]))


def test_nothing_reachable_from_a_term_is_a_production(system):
    # The projection is a boundary: `constructors` reads a `Pattern`, and nothing
    # it hands back contains one. A term, its constructor, that constructor's slot
    # sorts and a sort union's branches are all kernel data, which is what lets
    # `terms`, `unify`, `definitions` and `side_conditions` be written without
    # reference to the matching layer.
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    formula = context.variables["formula"]

    seen: set[int] = set()
    found: list[str] = []

    def walk(obj, path: str) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, Pattern):
            found.append(f"{path}: {type(obj).__name__} {obj.name!r}")
            return
        # Only the kernel's own objects have fields worth following; a str or an
        # int is a leaf, and `vars` would raise on it.
        if not isinstance(obj, (Constructor, Term)):
            return
        for name, value in vars(obj).items():
            walk(value, f"{path}.{name}")
        if isinstance(obj, Constructor):
            for label, slot in obj.slot_sorts.items():
                walk(slot, f"{path}.slot_sorts[{label}]")
            for index, member in enumerate(obj.members):
                walk(member, f"{path}.members[{index}]")
        if isinstance(obj, Node):
            for label, child in obj.children.items():
                walk(child, f"{path}.children[{label}]")

    statements = ["x ∈ y", "(x ∈ y → x ∈ z)", "∀z (z ∈ x → z ∈ y)", "x ⊆ y"]
    for statement in statements:
        matched = formula.match(statement, context)
        assert matched is not None, statement
        walk(from_match(matched), f"term({statement!r})")

    # A definition's schemas carry Var leaves, so this covers a variable's sort.
    for definition in system.definitions:
        walk(definition.higher, "definition.higher")
        walk(definition.lower, "definition.lower")

    assert found == []
    assert len(seen) > len(statements)  # the walk actually went somewhere


def test_a_recursive_grammar_projects_without_recursing_forever(system):
    # `implication`'s slot sort is the `formula` union, which contains
    # `implication`. Projection registers a constructor before resolving its slot
    # sorts, so the cycle closes on the registered object instead of rebuilding.
    implication = constructor_for(system.context.variables["implication"])
    formula = constructor_for(system.context.variables["formula"])

    assert set(implication.slot_sorts.values()) == {formula}
    assert implication in formula.members
