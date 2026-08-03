"""A sequent calculus as a **layer of a tower**, rather than a system beside one.

S1 declared a sequent calculus standing alone and S2 carried a Hilbert library
into it across an `interpretation` edge. This is the third arrangement, and it is
the one an imported corpus forces:

    Hilbert PC  ──▶  Hilbert FOL  ──▶  *sequent layer*
                       (the spine)

The layer **inherits** the grammar it reasons about rather than restating it, and
that is the whole point. `set.mm` declares 1,441 productions; a sequent system
beside it would have to redeclare every one of them, or carry a rename with an
entry for every one of them, and `translation_errors` holds a rename to
*totality* — every name of the source's grammar must have an image. Neither is
something an author writes. A child declares four productions and inherits the
rest.

What the two arrangements each buy
----------------------------------
An **edge** (S2) relates two systems built independently: neither contains the
other, so a transferred statement is wrapped and every source primitive owes an
obligation. It is the only thing that works when the sequent system is not a
descendant, and it is what an author reaches for when the two grammars are
genuinely separate.

The **spine** works when the sequent calculus is being built *over* a system that
already exists. Then there is nothing to translate (the child's `formula` is the
parent's rows), nothing to wrap (the child can state a `formula` line itself),
and no obligation to discharge (the parent's rules *are* the child's). What
replaces the wrap is one declared rule:

    lift    antecedent:  P            (read at the parent's logical sort)
            deduction:   ∅ ⊢ P

which is the interpretation stated as a primitive of the combined system instead
of as a claim about two of them. It is sound for the same reason S2's closed
template is (§9.24), and it is the author's claim in exactly the same way any
declared rule is.

What is parent-agnostic, and what is not
----------------------------------------
The split below is the finding, and it is sharper than expected: **the part of a
sequent calculus that does not mention a connective is the part that transfers to
any parent.** :func:`sequent_core` — the context sort, the turnstile, the four
structural rules, cut, and `lift` — names only its parent's *logical sort*, so it
sits on this repository's `formula` tower and on an imported `wff` one without
changing a character. Only the logical rules (→R, →L, ∀R) spell connectives, and
those are written per parent: `(A → B)` here, `( ph -> ps )` over `set.mm`.

Two names a layer must not reuse, both learned the hard way and both recorded in
docs/system-relationships-roadmap.md §9.25: a **line part** (`reference` is the
importer's, so this layer's is `citation`) and a **production name**, since
`layered_spec` claims both once across a chain.
"""

from __future__ import annotations

from website.logical.declarative import (
    LinePart,
    LineSpec,
    Production,
    Rule,
    SystemSpec,
)

from tests.layered_systems import (
    first_order_logic_spec,
    propositional_calculus_spec,
)
from tests.spec_helpers import atom_const_prod, rule, template_prod

# What a sequent layer calls its citation field. Not `reference`, which the
# Hilbert layers and the Metamath importer both use: `layered_spec` claims a line
# part's name once across a chain, so a child adding a line type has to pick a
# fresh one. See §9.25 — within a *single* spec two line types may share a part
# name freely, which is what makes this a wart rather than a rule.
CITATION = "citation"


def sequent_core(
    name: str = "Sequent core",
    *,
    formula: str = "formula",
    empty: str = "∅",
    turnstile: str = "⊢",
) -> SystemSpec:
    """The parent-agnostic half: contexts, the turnstile, and structure.

    Everything here names ``formula`` — the parent's logical sort — and nothing
    else of the parent's grammar. So this is the layer that sits unchanged on any
    Hilbert tower, this repository's or an imported one's, and `formula="wff"` is
    the whole of what an import needs to change.

    ``lift`` is what replaces S2's statement template. A theorem of the parent is
    already citable here, on a *parent* line, because the child's library is its
    ancestors' (§5.2) — so the only thing missing is a step from `φ` to `∅ ⊢ φ`,
    and that is an ordinary rule with an antecedent at one sort and a conclusion
    at another. Sound because the parent's theorems hold outright and the empty
    context assumes nothing; unsound if `∅` were replaced by a context
    metavariable, for the same reason §9.24 gives — a rule schema is read for all
    instances of its metavariables, and `Γ ⊢ φ` for arbitrary Γ is a claim
    weakening has to earn rather than one lifting may assume.
    """
    return SystemSpec(
        name=name,
        productions=[
            # The empty context, a constant of the object language.
            atom_const_prod("context", "sequent-empty", empty, denotes_constant=True),
            # The sort inclusion: a formula alone is a context. Named for the
            # *sort* rather than for the production it admits, because a chain
            # claims production names once and `formula` is taken.
            Production(sort="context", name=formula),
            template_prod(
                "context", "sequent-cons", "g , a",
                [("g", "context"), ("a", formula)],
            ),
            template_prod(
                "sequent", "sequent-turnstile", f"g {turnstile} p",
                [("g", "context"), ("p", formula)],
            ),
        ],
        lines=[
            LineSpec(
                name="sequent-statement",
                shape=f"<sequent> [<{CITATION}>]",
                parts=[LinePart(name=CITATION, regex="[^\\[\\]]+")],
                logical_sort="sequent",
            )
        ],
        rules=[
            rule("id", "identity", [], "G , A ⊢ A",
                 [("G", "context"), ("A", formula)]),
            rule("WL", "weakening", ["G ⊢ C"], "G , A ⊢ C",
                 [("G", "context"), ("A", formula), ("C", formula)]),
            rule("XL", "exchange", ["G , A , B ⊢ C"], "G , B , A ⊢ C",
                 [("G", "context"), ("A", formula), ("B", formula), ("C", formula)]),
            rule("CL", "contraction", ["G , A , A ⊢ C"], "G , A ⊢ C",
                 [("G", "context"), ("A", formula), ("C", formula)]),
            rule("cut", "cut", ["G ⊢ A", "G , A ⊢ C"], "G ⊢ C",
                 [("G", "context"), ("A", formula), ("C", formula)]),
            # The bridge, and the whole of what an edge's template and
            # obligations were doing — see this function's note.
            rule("lift", "lifting", ["P"], f"{empty} {turnstile} P",
                 [("P", formula)]),
        ],
    )


def propositional_sequent_rules(formula: str = "formula") -> list[Rule]:
    """→R and →L, which spell a connective and are therefore parent-specific.

    Written against *this* repository's `(A → B)`. Over an imported corpus the
    same two rules are written against `( ph -> ps )`, and nothing else about the
    layer changes — which is the split :func:`sequent_core` exists to make.
    """
    return [
        rule("→R", "implication right", ["G , A ⊢ B"], "G ⊢ (A → B)",
             [("G", "context"), ("A", formula), ("B", formula)]),
        rule("→L", "implication left", ["G ⊢ A", "G , B ⊢ C"], "G , (A → B) ⊢ C",
             [("G", "context"), ("A", formula), ("B", formula), ("C", formula)]),
    ]


def first_order_sequent_rules(
    formula: str = "formula", variable: str = "term"
) -> list[Rule]:
    """∀R with its eigenvariable condition, and ∀L.

    The proviso is the reason a sequent layer is worth having over a Hilbert one
    at all, and it reads exactly as it does in S1: `occurs` descends the context
    because a context is a term of an ordinary sort (§3.4). What is new is that
    the sort it descends *into* is the parent's — `formula` and `term` are the
    tower's rows, not this layer's — so the proviso is asked about notation this
    layer never declared.
    """
    return [
        rule("∀R", "universal right", ["G ⊢ P"], "G ⊢ ∀x P",
             [("G", "context"), ("P", formula), ("x", variable)],
             side_conditions=["not occurs(x, G)"]),
        rule("∀L", "universal left", ["G , P ⊢ C"], "G , ∀x P ⊢ C",
             [("G", "context"), ("P", formula), ("C", formula), ("x", variable)]),
    ]


def sequent_layer_spec(name: str = "Sequent FOL") -> SystemSpec:
    """The layer this repository's tower carries: core + both rule sets."""
    spec = sequent_core(name=name)
    spec.rules.extend(propositional_sequent_rules())
    spec.rules.extend(first_order_sequent_rules())
    return spec


def sequent_tower_specs() -> list[SystemSpec]:
    """The whole chain, ancestors first — what `layered_spec` is given.

    PC and FOL are `tests/layered_systems.py`'s, unmodified and unaware of this:
    a tower does not know it is being built on, which is the property that makes
    adding a sequent layer to an *imported* corpus the same operation as adding
    one here.
    """
    return [
        propositional_calculus_spec(),
        first_order_logic_spec(),
        sequent_layer_spec(),
    ]
