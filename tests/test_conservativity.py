"""Conservativity: a definition must add notation, never assumptions.

A definition is conservative when adding it proves nothing new in the language
that preceded it. Two properties carry that, and the engine treats them very
differently:

* **non-circularity** — a definition may not (transitively) be stated in terms
  of itself. Mostly this holds *by construction*: a definition's defining form is
  matched against the grammar as extended by the definitions **before** it, so a
  definition stated in terms of its own **new notation** matches nothing and is
  dropped. That argument covers only a defined form the grammar does not already
  spell, which is why it needs a check as well
  (``declarative._require_a_non_circular_definition``) — see the section below.
* **freshness** — the defined symbol must be one the system does not already
  reason about. This is checked (``declarative._require_a_fresh_defined_form``),
  and "already" reaches further than it looks: a rule may be stated over a form no
  production spells, which parses against no sort and sits inert as flat text
  until a definition supplies the grammar for it.

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
    _build_rule,
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

# Two more relations, declared but not reasoned over, for the circularity cases:
# what makes them interesting is that they are grammatical before any definition
# runs, so a definition over them layers whatever it says.
SQSUBSET = template_prod("formula", "sqsubset", "(x ⊑ y)",
                         [("x", "setvar"), ("y", "setvar")])
SQSUBSET2 = template_prod("formula", "sqsubseteq", "(x ⊴ y)",
                          [("x", "setvar"), ("y", "setvar")])

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
# Non-circularity — by construction where the defined form is new notation
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
    # one can be earlier, so neither layers. Index ordering rules out every cycle
    # among definitions that introduce their own notation.
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
# Non-circularity — checked where the defined form is already grammatical
# ---------------------------------------------------------------------------


def test_a_definition_over_a_declared_production_cannot_be_self_referential() -> None:
    # The hole the layering argument leaves. `⊑` is a *declared production*, so
    # `(x ⊑ y)` is grammatical before any definition runs and the defining form
    # matches — the definition layers, and without a check it registers. It is
    # `P ↔ ¬P`: not an abbreviation but a contradiction.
    result = build_spec(spec(
        [defines("(x ⊑ y)", "((x ⊑ y) → ⊥)", name="circ")],
        productions=[SQSUBSET],
    ))

    assert "errors" in result
    (message,) = result["errors"]
    assert "in terms of itself" in message


def test_two_definitions_over_declared_productions_cannot_cycle() -> None:
    # Neither definition is self-referential; the cycle exists only between them,
    # and both forms are grammatical from the start so index ordering does not
    # break it. `⊑ ≝ ¬⊴` and `⊴ ≝ ¬⊑` unfold into each other forever.
    result = build_spec(spec(
        [defines("(x ⊑ y)", "((x ⊴ y) → ⊥)", name="d1"),
         defines("(x ⊴ y)", "((x ⊑ y) → ⊥)", name="d2")],
        productions=[SQSUBSET, SQSUBSET2],
    ))

    assert "errors" in result
    (message,) = result["errors"]
    assert "in terms of itself" in message


def test_a_cycle_closed_through_a_shared_defined_form_is_refused() -> None:
    # The other way past the layering argument: `S` is grammatical once its first
    # definition registers, so a *later* definition may name it again — this time
    # in terms of `T`, which is itself defined in terms of `S`.
    result = build_spec(spec([
        Definition_(sort="formula", name="a", higher="S", lower="⊥", bindings=[]),
        Definition_(sort="formula", name="b", higher="T", lower="(S → ⊥)", bindings=[]),
        Definition_(sort="formula", name="c", higher="S", lower="(T → ⊥)", bindings=[]),
    ]))

    assert "errors" in result
    (message,) = result["errors"]
    assert "in terms of itself" in message


def test_a_definition_over_a_declared_production_is_otherwise_fine() -> None:
    # The check is about the *cycle*, not about defining a production: `⊑` may be
    # given meaning in terms of `⊴` as long as `⊴` does not lead back to it.
    written = spec(
        [defines("(x ⊑ y)", "((x ⊴ y) → ⊥)", name="d1")],
        productions=[SQSUBSET, SQSUBSET2],
    )

    assert "errors" not in build_spec(written)
    assert registered_definition_layering(written) == [True]


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


# ---------------------------------------------------------------------------
# Freshness — a statement the grammar cannot yet read
# ---------------------------------------------------------------------------


def test_a_rule_over_a_form_no_production_spells_is_still_reasoned_over() -> None:
    # The sharpest freshness case, and the one an inventory of constructors
    # cannot see on its own: `⊑` has no production, so `SQ`'s conclusion parses
    # against no sort and is stored as a flat text pattern — a rule that looks,
    # at build time, to be about nothing. The definition then makes exactly that
    # form grammatical, and the rule becomes a rule about `⊥`.
    result = build_spec(spec(
        [defines("(x ⊑ y)", "⊥", name="bogus")],
        rules=[rule("SQ", "sqsubset rule", [], "(x ⊑ y)",
                    [("x", "setvar"), ("y", "setvar")])],
    ))

    assert "errors" in result
    (message,) = result["errors"]
    assert "already stated over that form" in message


def test_the_unreadable_statement_case_was_not_inert() -> None:
    # What that refusal is worth. Built here with `⊑` declared as a production and
    # no rule over it — the admissible version of the same definition — to show
    # the step it licences: `(a ⊑ b)` rewrites to `⊥`. In the refused system the
    # definition supplies that grammar itself, so the rule's own conclusion
    # becomes writable, and those two lines are a proof of ⊥.
    system = build_system(spec(
        [defines("(x ⊑ y)", "⊥", name="bogus")],
        productions=[SQSUBSET],
    ))
    context = copy(system.context)
    context.variables.update(system.build_context.variables)
    formula = system.build_context.variables["formula"]
    (definition,) = system.definitions

    def term(text: str):
        matched = formula.match(text, context)
        assert matched is not None, text
        return from_match(matched)

    assert check_definitional_step(term("(a ⊑ b)"), term("⊥"), definition, context)


def test_an_axiom_over_a_form_no_production_spells_is_refused() -> None:
    # The same hole through an axiom, whose schema is a line type rather than a
    # rule — so it is reached by re-reading the text, not by any term a pattern
    # carries.
    result = build_spec(spec(
        [Definition_(sort="formula", name="b", higher="S", lower="⊥", bindings=[])],
        axioms=[axiom("A", "a", "(S → S)")],
    ))

    assert "errors" in result
    (message,) = result["errors"]
    assert "already stated over that form" in message


def test_an_unreadable_statement_does_not_condemn_an_unrelated_definition() -> None:
    # The re-read is targeted: `SQ` mentions `⊑`, the definition introduces `S`,
    # and a statement the grammar cannot read is not by itself a reason to refuse
    # every definition that follows it.
    written = spec(
        [Definition_(sort="formula", name="b", higher="S", lower="⊥", bindings=[])],
        rules=[rule("SQ", "sqsubset rule", [], "(x ⊑ y)",
                    [("x", "setvar"), ("y", "setvar")])],
    )

    assert "errors" not in build_spec(written)


def test_a_rule_added_after_the_build_counts_as_reasoning_over_its_symbols() -> None:
    # `register_definition` is the one path on which the system can have gained a
    # primitive since the build, so it is the one path that has to look. The spec
    # this system was built from has no rule over `∈` at all.
    system = build_system(spec([]))
    system.add_inference_rule(_build_rule(
        rule("MEM", "membership rule", [], "(x ∈ y)",
             [("x", "setvar"), ("y", "setvar")]),
        system.build_context, 0, None,
    ))

    with pytest.raises(DeclarativeError, match="already stated over that form"):
        register_definition(defines("(x ∈ y)", "⊥", name="late"), system)
