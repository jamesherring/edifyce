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
from website.logical.declarative import SystemSpec, build_spec
from website.logical.kernel.constructors import constructor_for
from website.logical.matching.patterns import StringPattern, UnionPattern


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


def test_admission_is_read_after_the_unions_are_filled(system):
    # `admits` is computed on demand, not at constructor-build time, so a sort's
    # branches cannot be sampled before `build_system` has finished adding them.
    union = UnionPattern(name="late", patterns=[])
    constructor = constructor_for(union)
    union.patterns.append(system.context.variables["implication"])

    assert constructor_for(system.context.variables["implication"]) in constructor.admits
