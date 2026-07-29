"""Conservativity: a definition must add notation, never assumptions.

A definition is conservative when adding it proves nothing new in the language
that preceded it. Two properties carry that, and the engine treats them very
differently:

* **non-circularity** — a definition may not (transitively) be stated in terms
  of itself. This holds *by construction* and always has: a definition's defining
  form is matched against the grammar as extended by the definitions **before**
  it, so the "is defined using" relation is a DAG by index. The tests here pin
  that rather than a check, because there is no check to pin.
* **freshness** — the defined symbol must be one the system does not already
  reason about. This is checked (``declarative._require_a_fresh_defined_form``).

The distinction that makes freshness subtle: *declaring the defined form as a
production is not what disqualifies it*. Declaring ``subset`` and then defining
``(x ⊆ y)`` is the ordinary way to introduce notation here — the production
supplies grammar, the definition supplies meaning. What is refused is defining a
symbol an axiom or rule is already stated over.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import Definition as Definition_
from website.logical.declarative import (
    DeclarativeError,
    SystemSpec,
    build_spec,
    build_system,
    register_definition,
    registered_definition_layering,
)
from website.logical.kernel import check_definitional_step, from_match
from tests.spec_helpers import (
    atom_const_prod,
    axiom,
    brackets,
    regex_prod,
    rule,
    statement_line,
    template_prod,
)

GRAMMAR = [
    atom_const_prod("formula", "falsum", "⊥", denotes_constant=True),
    regex_prod("setvar", "letter", "[a-z]"),
    template_prod("formula", "membership", "(x ∈ y)", [("x", "setvar"), ("y", "setvar")]),
    template_prod("formula", "implication", "(p → q)", [("p", "formula"), ("q", "formula")]),
]

# A rule stated over `∈`: with this present the system *reasons about* membership.
MEMBERSHIP_RULE = rule(
    "MEMR", "membership rule", ["(x ∈ y)"], "⊥", [("x", "setvar"), ("y", "setvar")]
)


def spec(definitions, productions=(), rules=(), axioms=()) -> SystemSpec:
    return SystemSpec(
        name="C",
        brackets=brackets(),
        productions=[*GRAMMAR, *productions],
        lines=[statement_line()],
        rules=list(rules),
        axioms=list(axioms),
        definitions=list(definitions),
    )


def defines(higher: str, lower: str, name: str = "d") -> Definition_:
    return Definition_(
        sort="formula", name=name, higher=higher, lower=lower,
        bindings=[("x", "setvar"), ("y", "setvar")],
    )


# ---------------------------------------------------------------------------
# Non-circularity — holds by construction, via layering
# ---------------------------------------------------------------------------


def test_a_definition_cannot_be_stated_in_terms_of_itself() -> None:
    # `S ≝ (S → ⊥)`. The defining form is matched before this definition's own
    # notation is registered, so `S` is not yet grammatical and the form matches
    # nothing — the definition does not layer and is dropped. Self-reference is
    # not refused by a check; it is unreachable.
    written = spec([Definition_(sort="formula", name="d", higher="S",
                                lower="(S → ⊥)", bindings=[])])

    assert registered_definition_layering(written) == [False]
    assert build_spec(written)["system"].definitions == []


def test_two_definitions_cannot_be_stated_in_terms_of_each_other() -> None:
    # `A ≝ (B → ⊥)` needs `B` to precede it and `B ≝ (A → ⊥)` needs `A` to; only
    # one can be earlier, so neither layers. The same index ordering that makes
    # self-reference unreachable rules out every cycle.
    written = spec([
        Definition_(sort="formula", name="d1", higher="A", lower="(B → ⊥)", bindings=[]),
        Definition_(sort="formula", name="d2", higher="B", lower="(A → ⊥)", bindings=[]),
    ])

    assert registered_definition_layering(written) == [False, False]


def test_layering_on_an_earlier_definition_is_not_circular() -> None:
    # The property is a DAG, not an absence of edges: `T` may be defined using
    # `S` when `S` came first, and both layer.
    written = spec([
        Definition_(sort="formula", name="d1", higher="S", lower="⊥", bindings=[]),
        Definition_(sort="formula", name="d2", higher="T", lower="(S → ⊥)", bindings=[]),
    ])

    assert registered_definition_layering(written) == [True, True]
    assert len(build_spec(written)["system"].definitions) == 2


# ---------------------------------------------------------------------------
# Freshness — checked
# ---------------------------------------------------------------------------


def test_defining_a_symbol_a_rule_reasons_over_is_refused() -> None:
    result = build_spec(spec([defines("(x ∈ y)", "(⊥ → ⊥)")], rules=[MEMBERSHIP_RULE]))

    assert "errors" in result
    (message,) = result["errors"]
    assert "already stated over that form" in message


def test_defining_a_symbol_an_axiom_constrains_is_refused() -> None:
    # An axiom is a line type rather than an `InferenceRule`, and its schema is
    # stored as literal text — so this is the case a structural read of the
    # pattern cannot see, and only re-parsing catches.
    written = spec(
        [defines("(x ∈ y)", "(⊥ → ⊥)")],
        axioms=[axiom("EXT", "ext", "((a ∈ b) → (a ∈ b))")],
    )
    result = build_spec(written)

    assert "errors" in result
    assert "already stated over that form" in result["errors"][0]


def test_declaring_the_defined_form_as_a_production_is_not_disqualifying() -> None:
    # The ordinary way to introduce notation: `⊑` is declared so the form is
    # grammatical, and nothing else in the system mentions it, so defining it
    # adds no assumption. This is `df-subset`'s shape and must keep working.
    written = spec(
        [defines("(x ⊑ y)", "(⊥ → ⊥)")],
        productions=[template_prod("formula", "sqsubset", "(x ⊑ y)",
                                   [("x", "setvar"), ("y", "setvar")])],
        rules=[MEMBERSHIP_RULE],
    )

    assert "errors" not in build_spec(written)


def test_two_definitions_may_still_share_a_defined_form() -> None:
    # Each is its own citable axiom, as in Metamath. The freshness check asks
    # about the *system's* symbols, not about notation a definition introduced.
    written = spec([
        Definition_(sort="formula", name="d1", higher="S", lower="⊥", bindings=[]),
        Definition_(sort="formula", name="d2", higher="S", lower="(⊥ → ⊥)", bindings=[]),
    ])
    result = build_spec(written)

    assert "errors" not in result
    assert len(result["system"].definitions) == 2


def test_the_refused_definition_was_not_inert() -> None:
    # Why this is a refusal and not a note: without the check the kernel
    # definition is stated over the *production's* constructor, so a proof gets
    # to rewrite a membership into a tautology. Built here without a rule over
    # `∈` — which is what makes it admissible — to show the step it would enable.
    system = build_system(spec([defines("(x ∈ y)", "(⊥ → ⊥)", name="bogus")]))
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    formula = system.build_context.variables["formula"]
    (definition,) = system.definitions

    def term(text: str):
        matched = formula.match(text, context)
        assert matched is not None, text
        return from_match(matched)

    assert check_definitional_step(
        term("(a ∈ b)"), term("(⊥ → ⊥)"), definition, context
    )


def test_a_definition_registered_after_the_build_is_held_to_the_same_rule() -> None:
    # `register_definition` is the corpus-import path — the one place a definition
    # arrives after the system exists, and so the one most likely to carry a
    # defined form the system already reasons about. It reads the same primitive
    # signatures the build computed, so the refusal does not depend on *when* the
    # definition shows up.
    system = build_system(spec([], rules=[MEMBERSHIP_RULE]))

    with pytest.raises(DeclarativeError, match="already stated over that form"):
        register_definition(defines("(x ∈ y)", "(⊥ → ⊥)", name="late"), system)

    # And a fresh notation still registers by that path.
    assert register_definition(
        Definition_(sort="formula", name="late-ok", higher="S", lower="⊥", bindings=[]),
        system,
    )
