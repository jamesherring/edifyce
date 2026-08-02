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

from website.logical.declarative import Production, SystemSpec, build_system
from website.logical.declarative import LinePart, LineSpec
from website.logical.rendering import Projection, render


def system():
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


def term_for(text: str):
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
