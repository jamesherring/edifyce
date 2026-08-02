"""A sequent calculus as an ordinary Edifyce system.

S1 of docs/system-relationships-roadmap.md, and (c) of its brief: sequents and
the deduction theorem, expressed without the checker learning what a sequent is.

The whole of §6.2's claim is in the grammar:

    sort context ::= ∅ | wff | context , wff
    sort sequent ::= context ⊢ wff
    line statement : sequent

A **context is a term**, which is the difference between this and the natural
deduction Edifyce already has. There, an assumption context is a property of the
*proof* — a subproof's scope — so there is nothing to weaken, cite, or quantify
over. Here `Γ` is an ordinary metavariable of an ordinary sort, so the deduction
theorem is an ordinary rule and its eigenvariable condition is an ordinary
proviso over a term the kernel's `occurs` can see into (§3.4).

The cost is stated in §6.2 and is visible throughout `tests/test_sequent_calculus.py`:
**a syntactic list is not a set.** `Γ, A, B` and `Γ, B, A` are different terms,
so exchange, weakening and contraction are declared rules and cited by hand.
That is honest sequent calculus, and it is what shows S3 where an
associative-commutative matcher would pay.
"""

from __future__ import annotations

from website.logical.declarative import LinePart, LineSpec, Production, SystemSpec

from tests.spec_helpers import (
    atom_const_prod,
    brackets,
    regex_prod,
    rule,
    template_prod,
)


def sequent_line() -> LineSpec:
    """``<sequent> [<reference>]`` — a proof line *is* a sequent.

    The one thing the line type says that matters: a logical line's formula is
    read at the ``sequent`` sort, so every line of a proof is a whole sequent
    rather than a formula standing in some ambient context.
    """
    return LineSpec(
        name="statement",
        shape="<sequent> [<reference>]",
        parts=[LinePart(name="reference", regex="[^\\[\\]]+")],
        logical_sort="sequent",
    )


def sequent_spec(name: str = "Sequent calculus") -> SystemSpec:
    """LK for a first-order fragment: →, ¬, ∀ over a two-sorted grammar."""
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            # --- the formula language ---------------------------------------
            regex_prod("wff", "wff_var", "[A-Z][A-Z0-9]*"),
            regex_prod("ind", "ind_var", "[a-z][a-z0-9]*"),
            template_prod("wff", "equality", "s = t", [("s", "ind"), ("t", "ind")]),
            template_prod("wff", "negation", "¬p", [("p", "wff")]),
            template_prod(
                "wff", "implication", "(p → q)", [("p", "wff"), ("q", "wff")]
            ),
            template_prod(
                "wff", "universal", "∀x p", [("x", "ind"), ("p", "wff")],
                scopes_over={"x": ["p"]},
            ),
            # --- the context ------------------------------------------------
            # `∅` is the empty context, and it is a *constant* of the object
            # language: it names one fixed thing rather than standing for a
            # context a binder could bind.
            atom_const_prod("context", "empty", "∅", denotes_constant=True),
            # A formula alone is a context — the sort inclusion that lets
            # `A ⊢ B` be written without spelling the empty context first.
            Production(sort="context", name="wff"),
            # And the cons cell. Left-nested by construction: the right of a
            # comma is a formula, so `A , B , C` can only read as `(A , B) , C`
            # and `G , A` splits off the *rightmost* assumption — which is
            # exactly what the deduction theorem does.
            template_prod(
                "context", "cons", "g , a", [("g", "context"), ("a", "wff")]
            ),
            # --- the sequent ------------------------------------------------
            template_prod(
                "sequent", "turnstile", "g ⊢ p", [("g", "context"), ("p", "wff")]
            ),
        ],
        lines=[sequent_line()],
        rules=[
            # --- the axiom --------------------------------------------------
            rule("id", "identity", [], "G , A ⊢ A",
                 [("G", "context"), ("A", "wff")]),
            # One axiom of the object theory, so that something is provable
            # *about* a variable without that variable being an assumption —
            # which is what a non-vacuous ∀R needs, and what a calculus with no
            # axioms cannot supply (`id` puts its formula in the context by
            # construction).
            rule("refl", "reflexivity", [], "G ⊢ a = a",
                 [("G", "context"), ("a", "ind")]),

            # --- the structural rules, which a list rather than a set is what
            # --- makes necessary (§6.2)
            rule("WL", "weakening", ["G ⊢ C"], "G , A ⊢ C",
                 [("G", "context"), ("A", "wff"), ("C", "wff")]),
            rule("XL", "exchange", ["G , A , B ⊢ C"], "G , B , A ⊢ C",
                 [("G", "context"), ("A", "wff"), ("B", "wff"), ("C", "wff")]),
            rule("CL", "contraction", ["G , A , A ⊢ C"], "G , A ⊢ C",
                 [("G", "context"), ("A", "wff"), ("C", "wff")]),
            rule("cut", "cut", ["G ⊢ A", "G , A ⊢ C"], "G ⊢ C",
                 [("G", "context"), ("A", "wff"), ("C", "wff")]),

            # --- the logical rules ------------------------------------------
            # →R *is* the deduction theorem, and it is a primitive of a sequent
            # calculus rather than an admissible rule of a Hilbert one (§6.1),
            # so nothing is smuggled in by having it.
            rule("→R", "implication right", ["G , A ⊢ B"], "G ⊢ (A → B)",
                 [("G", "context"), ("A", "wff"), ("B", "wff")]),
            rule("→L", "implication left", ["G ⊢ A", "G , B ⊢ C"],
                 "G , (A → B) ⊢ C",
                 [("G", "context"), ("A", "wff"), ("B", "wff"), ("C", "wff")]),
            rule("¬R", "negation right", ["G , A ⊢ B"], "G ⊢ ¬A",
                 [("G", "context"), ("A", "wff"), ("B", "wff")]),

            # ∀R, and its eigenvariable condition — the phase's central case.
            # `x` may be generalised only where the context does not depend on
            # it, and that is a question about a *term*: `occurs` descends the
            # context the same way it descends a formula, because a context is
            # a term of an ordinary sort (§3.4).
            rule("∀R", "universal right", ["G ⊢ P"], "G ⊢ ∀x P",
                 [("G", "context"), ("P", "wff"), ("x", "ind")],
                 side_conditions=["not occurs(x, G)"]),
            # ∀L instantiates the bound variable with itself, which is the
            # instantiation a schema can express without a substitution
            # operator; see the module's note in tests/test_sequent_calculus.py.
            rule("∀L", "universal left", ["G , P ⊢ C"], "G , ∀x P ⊢ C",
                 [("G", "context"), ("P", "wff"), ("C", "wff"), ("x", "ind")]),
        ],
    )
