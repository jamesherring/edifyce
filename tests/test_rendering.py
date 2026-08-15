"""Rendering one term through more than one notation.

A term carries no notation: its constructor holds the *source* template it was
parsed from, and rendering folds that template over the children. A projection is
the same fold with substitute templates, so one checked term can be shown as
ASCII, Unicode or LaTeX without a second copy of it and without re-parsing.

The point of folding the *term* rather than substituting tokens is that the
structure is in the tree. Brackets, nesting and argument order come from the term;
only the notation comes from the projection, so a production may render quite
unlike its source.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import (
    Definition,
    LinePart,
    LineSpec,
    Production,
    SystemSpec,
    build_system,
)
from website.logical.formal_system import FormalSystem
from website.logical.kernel.terms import Term
from website.logical.metamath.display import notation_constructors
from website.logical.rendering import (
    Projection,
    Rule,
    longest_label,
    render,
    total_projection,
)


def system() -> FormalSystem:
    return build_system(
        SystemSpec(
            name="pc",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
                Production(
                    sort="formula",
                    name="negation",
                    template="-A",
                    bindings=[("A", "formula")],
                ),
                Production(sort="formula", name="falsum", atom_value="F"),
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                    logical_sort="formula",
                )
            ],
        )
    )


def term_for(text: str) -> Term:
    return system().parse(f"{text} [x]\n").proof_lines[0].formula_term


def test_with_no_projection_rendering_is_to_string() -> None:
    # The property everything else rests on: adding projections changes nothing
    # for a caller that asks for none.
    term = term_for("(p -> -q)")

    assert render(term) == term.to_string()
    assert render(term, Projection()) == term.to_string()


def test_a_projection_respells_the_productions_it_names() -> None:
    term = term_for("(p -> -q)")
    unicode = Projection(
        templates={
            "implication": (("lit", "("), ("slot", "A"), ("lit", " → "),
                            ("slot", "B"), ("lit", ")")),
            "negation": (("lit", "¬"), ("slot", "A")),
        },
        name="unicode",
    )

    assert render(term, unicode) == "(p → ¬q)"


def test_a_production_the_projection_does_not_name_keeps_its_own_template() -> None:
    # So a partial projection is useful: naming one production re-spells it and
    # leaves the rest alone.
    term = term_for("(p -> -q)")
    partial = Projection(templates={"negation": (("lit", "¬"), ("slot", "A"))})

    assert render(term, partial) == "(p -> ¬q)"


def test_a_projection_may_reorder_and_restructure_a_production() -> None:
    # What per-token substitution cannot do, and the reason to fold the tree: the
    # template is free to move its slots, drop the source's brackets, or wrap them
    # in something else entirely.
    term = term_for("(p -> -q)")
    prefix = Projection(
        templates={
            "implication": (("lit", "imp["), ("slot", "B"), ("lit", ", "),
                            ("slot", "A"), ("lit", "]")),
        }
    )

    assert render(term, prefix) == "imp[-q, p]"


def test_an_atom_is_respelled_by_its_own_name() -> None:
    # An atom carries its text rather than a template, so a projection has to reach
    # it through the same map — otherwise a grammar's constants stay in the source
    # notation while everything around them changes.
    term = term_for("(F -> p)")
    projected = Projection(templates={"falsum": (("lit", "⊥"),)})

    assert render(term, projected) == "(⊥ -> p)"


def test_rendering_is_recursive_through_nesting() -> None:
    term = term_for("((p -> q) -> -(r -> p))")
    unicode = Projection(
        templates={
            "implication": (("lit", "("), ("slot", "A"), ("lit", " → "),
                            ("slot", "B"), ("lit", ")")),
            "negation": (("lit", "¬"), ("slot", "A")),
        }
    )

    assert render(term, unicode) == "((p → q) → ¬(r → p))"


def definition_system() -> FormalSystem:
    """A system where a *definition* is the only thing making `S` grammatical.

    Nothing requires a production to declare a defined form first, and such a form
    joins no sort's union — so a projection built by walking the grammar alone
    cannot see it.
    """
    return build_system(
        SystemSpec(
            name="pc",
            productions=[
                Production(sort="formula", name="var", regex="[p-r]"),
                Production(
                    sort="formula",
                    name="implication",
                    template="(A -> B)",
                    bindings=[("A", "formula"), ("B", "formula")],
                ),
                Production(
                    sort="formula",
                    name="falsum",
                    atom_value="F",
                    denotes_constant=True,
                ),
            ],
            definitions=[
                Definition(
                    sort="formula", name="d", higher="S", lower="(F -> F)", bindings=[]
                )
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<formula> [<reference>]",
                    parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                    logical_sort="formula",
                )
            ],
        )
    )


def test_a_defined_form_is_a_production_a_projection_can_name() -> None:
    # Its constructor is named for the sort and the form (`formula:S`), and is
    # reached through the kernel definition rather than the grammar — a
    # `DefinedNotation` is not a `Pattern`, so `constructor_for` does not take one.
    system = definition_system()
    term = system.parse("(S -> p) [x]\n").proof_lines[0].formula_term
    projected = Projection(
        templates={
            "formula:S": (("lit", "⊤"),),
            "implication": (("lit", "("), ("slot", "A"), ("lit", " → "),
                            ("slot", "B"), ("lit", ")")),
        }
    )

    assert term.to_string() == "(S -> p)"
    assert render(term, projected) == "(⊤ → p)"


def application_system() -> FormalSystem:
    """A grammar that applies things *generically*, as `set.mm` does.

    `( F @ A )` is one production whatever `F` is, and `( A F B )` is one
    production whatever `F` is — so the symbol a reader thinks of as the operator
    is an operand, sitting in a slot, and no template for either production says
    anything about it. That is the shape a rule exists for.
    """
    return build_system(
        SystemSpec(
            name="app",
            productions=[
                Production(sort="term", name="var", regex="[a-c]"),
                Production(
                    sort="term", name="root", atom_value="sqrt", denotes_constant=True
                ),
                Production(
                    sort="term", name="over", atom_value="div", denotes_constant=True
                ),
                Production(
                    sort="term",
                    name="apply",
                    template="(F @ A)",
                    bindings=[("F", "term"), ("A", "term")],
                ),
                Production(
                    sort="term",
                    name="binop",
                    template="(A F B)",
                    bindings=[("A", "term"), ("F", "term"), ("B", "term")],
                ),
            ],
            lines=[
                LineSpec(
                    name="statement",
                    shape="<term> [<reference>]",
                    parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
                    logical_sort="term",
                )
            ],
        )
    )


def applied(text: str) -> Term:
    return application_system().parse(f"{text} [x]\n").proof_lines[0].formula_term


SQRT = Rule(
    name="sqrt",
    constructor="apply",
    pins={"F": "root"},
    pieces=(("lit", "√{"), ("slot", "A"), ("lit", "}")),
)
FRACTION = Rule(
    name="fraction",
    constructor="binop",
    pins={"F": "over"},
    pieces=(("lit", "frac{"), ("slot", "A"), ("lit", "}{"), ("slot", "B"), ("lit", "}")),
)


def test_a_rule_consumes_the_operand_it_pins() -> None:
    # The whole point, and what no per-production template can do: `sqrt` is an
    # *argument* of the application, and there is none of it left in the result.
    term = applied("(sqrt @ b)")

    assert term.to_string() == "(sqrt @ b)"
    assert render(term, Projection(rules=(SQRT,))) == "√{b}"


def test_a_rule_whose_pin_does_not_hold_leaves_the_term_alone() -> None:
    term = applied("(a @ b)")

    assert render(term, Projection(rules=(SQRT,))) == "(a @ b)"


def test_a_rule_reaches_an_operand_of_a_three_slot_production() -> None:
    term = applied("(a div b)")

    assert render(term, Projection(rules=(FRACTION,))) == "frac{a}{b}"


def test_a_rule_wins_over_the_template_for_its_root() -> None:
    # A rule is written *because* the root's own spelling reads badly here, so
    # consulting the template after matching would undo the point.
    term = applied("(sqrt @ b)")
    both = Projection(
        templates={"apply": (("slot", "F"), ("lit", "("), ("slot", "A"), ("lit", ")"))},
        rules=(SQRT,),
    )

    assert render(term, both) == "√{b}"
    # …and the template still governs an application the rule does not match.
    assert render(applied("(a @ b)"), both) == "a(b)"


def test_rendering_recurses_into_a_rule_s_captured_slots() -> None:
    term = applied("(sqrt @ (a div b))")

    assert render(term, Projection(rules=(SQRT, FRACTION))) == "√{frac{a}{b}}"


def test_the_most_specific_rule_matches_whatever_order_it_is_given_in() -> None:
    # Two rules with the same root: pins decide, not declaration order, so a table
    # cannot be broken by appending to it.
    catch_all = Rule(
        name="any",
        constructor="apply",
        pieces=(("slot", "F"), ("lit", "·"), ("slot", "A")),
    )
    term = applied("(sqrt @ b)")

    assert render(term, Projection(rules=(catch_all, SQRT))) == "√{b}"
    assert render(term, Projection(rules=(SQRT, catch_all))) == "√{b}"
    assert render(applied("(a @ b)"), Projection(rules=(catch_all,))) == "a·b"


def test_a_rule_may_name_a_grandchild_by_path() -> None:
    # A path is what lets a rule say something the root's own template cannot:
    # `A.A` is the argument of the *inner* application.
    unwrap = Rule(
        name="double-root",
        constructor="apply",
        pins={"F": "root", "A.F": "root"},
        pieces=(("lit", "√√{"), ("slot", "A.A"), ("lit", "}")),
    )
    term = applied("(sqrt @ (sqrt @ b))")

    assert render(term, Projection(rules=(unwrap, SQRT))) == "√√{b}"
    # One level of nesting only — the inner rule takes over below it.
    assert render(applied("(sqrt @ b)"), Projection(rules=(unwrap, SQRT))) == "√{b}"


def test_a_rule_alone_is_enough_for_a_projection_to_have_an_opinion() -> None:
    # `render` short-circuits to `to_string` for a projection that says nothing,
    # and a projection of rules alone says something.
    term = applied("(sqrt @ b)")

    assert render(term, Projection(rules=(SQRT,))) != term.to_string()


def test_total_projection_carries_the_rules_through() -> None:
    # Completion is about giving a *stored* notation a template for every
    # constructor; it has nothing to say about rules, and must not drop them.
    engine = application_system()
    completed = total_projection(
        notation_constructors(engine.build_context), Projection(rules=(SQRT,)), "latex"
    )

    assert completed.rules == (SQRT,)
    assert completed.name == "latex"
    assert "apply" in completed.templates


def test_a_path_resolves_a_dotted_label_at_any_depth() -> None:
    # A slot label may itself contain the separator (`set.mm` names class variables
    # `.+`, `.0.`), so a path is not simply split on every dot: the longest join
    # that names a child is the label, at each level rather than only at the root.
    steps = ["A", "", "+"]

    assert longest_label(steps, {"A"}.__contains__) == 1
    assert longest_label(["", "+"], {".+"}.__contains__) == 2
    assert longest_label(["F", "G"], {"F"}.__contains__) == 1
    assert longest_label(["X"], {"F"}.__contains__) == 0
    # Longest first, so a child genuinely called `A.B` beats descending into `A`.
    assert longest_label(["A", "B"], {"A", "A.B"}.__contains__) == 2


def test_a_rule_accounts_for_a_dotted_root_slot_it_descends_through() -> None:
    # `Rule.roots` resolves the same way, or a rule reaching into a dotted slot
    # would look as though it accounted for no slot at all and be refused.
    rule = Rule(
        constructor="c",
        pins={".+.F": "x"},
        pieces=(("slot", "A"),),
    )

    assert rule.roots({".+", "A"}) == {".+", "A"}


def test_a_self_nesting_rule_composes_at_every_depth() -> None:
    # The shape `setmm.DISPLAY_RULES` uses for factorial, where the general
    # spelling is ambiguous under its own nesting: a second rule with one more pin
    # is tried first, and fences the *whole* operand rather than reaching past it,
    # so applying it again brackets its own output.
    plain = Rule(
        name="post", constructor="apply", pins={"F": "root"},
        pieces=(("slot", "A"), ("lit", "!")),
    )
    nested = Rule(
        name="post-of-post", constructor="apply", pins={"F": "root", "A.F": "root"},
        pieces=(("lit", "("), ("slot", "A"), ("lit", ")!")),
    )
    projection = Projection(rules=(plain, nested))

    assert render(applied("(sqrt @ b)"), projection) == "b!"
    assert render(applied("(sqrt @ (sqrt @ b))"), projection) == "(b!)!"
    assert render(applied("(sqrt @ (sqrt @ (sqrt @ b)))"), projection) == "((b!)!)!"
