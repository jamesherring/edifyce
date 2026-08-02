"""A three-layer tower — propositional calculus ⊂ first-order logic ⊂ ZFC.

The shared fixture for everything about relationships between formal systems
(docs/system-relationships-roadmap.md). Each layer is an ordinary
:class:`~website.logical.declarative.SystemSpec` declaring only its **own**
parts; the tower is assembled by :func:`~website.logical.declarative.layered_spec`,
which is what ``formal_systems.inherits_from_id`` means.

Deliberately not a toy. Each layer has to be big enough that a wrong answer is
not the only answer available:

* **Propositional calculus** — implication, negation, the three Łukasiewicz
  axioms and modus ponens, plus ``∧`` declared as notation and *defined* over
  ``→``/``¬``, exactly as set.mm declares ``wa`` and then states ``df-an``. That
  last one is the load-bearing detail: ZFC's extensionality axiom is stated over
  ``∧``, so the tower only builds if a definition is held to the primitives of
  its own layer and its ancestors' rather than to a descendant's (see
  ``SystemSpec.definition_scope``).
* **First-order logic** — a ``term`` sort, ``=``/``∈``, the universal quantifier
  with its binding slot declared, generalisation and two quantifier axioms, one
  of which (``ax-5``) carries a real proviso. ``∃`` arrives as a definition, so
  the layer both consumes an ancestor's notation and adds its own.
* **ZFC** — extensionality, over the *ancestors'* ``∀``, ``∈``, ``=`` and the
  propositional layer's defined ``∧``; and ``⊆``, defined over all of them.

The notation is this suite's (``→``, ``∀x p``, ``∈``) rather than Metamath's, so
the tower composes with ``tests/spec_helpers.py`` and reads like the rest of the
suite. Every helper returns a fresh object graph, as those do.

**Formula metavariables are upper-case, term metavariables lower-case**, and that
is not decoration. A *definition*'s parameters are parsed in the system's own
context rather than under its bindings (``_register_notated_definition`` uses
``system.context`` deliberately), so they have to be spellable by the grammar:
``P`` is a ``formula`` leaf, ``x`` a ``term`` leaf. set.mm gets this from its
``$f`` declarations, which make every metavariable a variable production; here
the two leaf regexes do it.
"""

from __future__ import annotations

from website.logical.declarative import (
    LinePart,
    LineSpec,
    Production,
    Rule,
    SystemSpec,
)

from tests.spec_helpers import (
    atom_const_prod,
    axiom,
    brackets,
    conjunction_prod,
    defn,
    equality_prod,
    implication_prod,
    membership_prod,
    negation_prod,
    regex_prod,
    rule,
    template_prod,
    variable_prod,
)

# The three layer names, root first — the order `layered_spec` takes them in.
PC = "Propositional calculus"
FOL = "First-order logic"
ZFC = "ZFC"


def propositional_variable_prod() -> Production:
    """``formula ::= A | B | P1 | …`` — the propositional atoms.

    Upper-case so they never collide with the ``term`` variables the FOL layer
    adds (``[a-z][a-z0-9]*``), which is what lets both leaves live in one tower.
    """
    return regex_prod("formula", "prop_var", "[A-Z][A-Z0-9]*")


def statement_line(sort: str = "formula") -> LineSpec:
    """``<formula> [<reference>]`` — as ``spec_helpers``', but hyphens allowed.

    The labels here are Metamath's shape (``ax-1``, ``df-an``), and the shared
    helper's reference regex stops at alphanumerics, so a citation of one would
    not parse at all.

    ``sort`` names the logical sort, and appears in the shape as well — a line
    reads its formula *at* a sort, so a system that calls it something else says
    so twice. Only the renamed systems below pass anything but the default.
    """
    return LineSpec(
        name="statement",
        shape=f"<{sort}> [<reference>]",
        parts=[LinePart(name="reference", regex="[A-Za-z0-9 ,.-]+")],
        logical_sort=sort,
    )


def universal_prod() -> Production:
    """``formula ::= ∀x p``, with the binding slot **declared**.

    Two departures from ``spec_helpers.universal_prod``, both load-bearing. It
    declares ``scopes_over``, because half the point of the tower is that a
    binder introduced by a *child* is visible to the checks a parent's parts are
    held to. And it binds over the ``term`` *sort* rather than the ``variable``
    production, so "which sorts does a binder range over" has a union to answer
    with — which is what `_validate_constant_declarations` reads.
    """
    return template_prod(
        "formula",
        "universal",
        "∀x p",
        [("x", "term"), ("p", "formula")],
        scopes_over={"x": ["p"]},
    )


def existential_prod() -> Production:
    """``formula ::= ∃x p`` — ``universal_prod``'s counterpart, defined by `df-ex`."""
    return template_prod(
        "formula",
        "existential",
        "∃x p",
        [("x", "term"), ("p", "formula")],
        scopes_over={"x": ["p"]},
    )


# --- the layers ------------------------------------------------------------


def propositional_calculus_spec(name: str = PC) -> SystemSpec:
    """Implication, negation, the three axioms, modus ponens, and ``∧``."""
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            propositional_variable_prod(),
            negation_prod(),
            implication_prod(),
            # Declared *and* defined, exactly as set.mm declares `wa` and then
            # states `df-an` over it: the production supplies grammar and the
            # definition supplies meaning. Declaring it is deliberately not
            # disqualifying — what freshness refuses is defining a symbol the
            # axioms already reason about.
            conjunction_prod(),
        ],
        lines=[statement_line()],
        # Zero-antecedent *rules* rather than `spec.axioms`, because a Hilbert
        # proof cites its axioms by label (`[ax-1]`) and `spec.axioms` is the
        # other mechanism — a line type asserted by fiat when a line matches its
        # shape, which ZFC's extensionality below uses instead.
        rules=[
            rule(
                "ax-1",
                "simplification",
                [],
                "(P → (Q → P))",
                [("P", "formula"), ("Q", "formula")],
            ),
            rule(
                "ax-2",
                "distribution",
                [],
                "((P → (Q → R)) → ((P → Q) → (P → R)))",
                [("P", "formula"), ("Q", "formula"), ("R", "formula")],
            ),
            rule(
                "ax-3",
                "transposition",
                [],
                "((¬P → ¬Q) → (Q → P))",
                [("P", "formula"), ("Q", "formula")],
            ),
            rule(
                "MP",
                "modus ponens",
                ["P", "(P → Q)"],
                "Q",
                [("P", "formula"), ("Q", "formula")],
            ),
        ],
        definitions=[
            # The definition ZFC's extensionality axiom then reasons over, which
            # is what makes `definition_scope` load-bearing for this tower.
            defn(
                "formula",
                "conjunction",
                "(P ∧ Q)",
                "¬(P → ¬Q)",
                [("P", "formula"), ("Q", "formula")],
                label="df-an",
            )
        ],
    )


def first_order_logic_spec(name: str = FOL) -> SystemSpec:
    """Terms, ``=``, ``∈``, ``∀`` with its binder declared, and ``∃`` defined."""
    return SystemSpec(
        name=name,
        productions=[
            variable_prod(),
            equality_prod(),
            membership_prod(),
            universal_prod(),
            existential_prod(),
        ],
        rules=[
            rule(
                "ax-4",
                "quantified distribution",
                [],
                "(∀x (P → Q) → (∀x P → ∀x Q))",
                [("x", "term"), ("P", "formula"), ("Q", "formula")],
            ),
            rule(
                "GEN",
                "generalisation",
                ["P"],
                "∀x P",
                [("x", "term"), ("P", "formula")],
            ),
            # The proviso is the point: `P` may only be quantified vacuously over
            # an `x` it does not mention. A zero-antecedent rule rather than an
            # axiom because only a rule carries side conditions.
            rule(
                "ax-5",
                "vacuous quantification",
                [],
                "(P → ∀x P)",
                [("x", "term"), ("P", "formula")],
                side_conditions=["not occurs(x, P)"],
            ),
        ],
        definitions=[
            defn(
                "formula",
                "existential",
                "∃x P",
                "¬∀x ¬P",
                [("x", "term"), ("P", "formula")],
                label="df-ex",
            )
        ],
    )


def zfc_spec(name: str = ZFC) -> SystemSpec:
    """Extensionality, and ``⊆`` defined over the ancestors' notation."""
    return SystemSpec(
        name=name,
        axioms=[
            # Stated over the *propositional* layer's defined `∧` and the FOL
            # layer's `∀`/`∈`/`=`: a theory extension reasoning in the language
            # it inherited.
            axiom(
                "ax-ext",
                "extensionality",
                "(∀z ((z ∈ x → z ∈ y) ∧ (z ∈ y → z ∈ x)) → x = y)",
                [("x", "term"), ("y", "term"), ("z", "term")],
            )
        ],
        definitions=[
            defn(
                "formula",
                "subset",
                "x ⊆ y",
                "∀z (z ∈ x → z ∈ y)",
                [("x", "term"), ("y", "term")],
                fresh=[("z", "term")],
                label="df-ss",
            )
        ],
    )


def tower() -> list[SystemSpec]:
    """The three layers, root first — the argument :func:`layered_spec` takes."""
    return [propositional_calculus_spec(), first_order_logic_spec(), zfc_spec()]


# --- the same system under other names (R4b) -------------------------------


def _wff_rules() -> list[Rule]:
    # The propositional layer's four primitives, over the sort the renamed
    # systems call `wff`. The *labels* are unchanged: a rename is about the
    # grammar, and an edge's obligations are what pair a source primitive with a
    # target one.
    return [
        rule("ax-1", "simplification", [], "(P → (Q → P))",
             [("P", "wff"), ("Q", "wff")]),
        rule("ax-2", "distribution", [], "((P → (Q → R)) → ((P → Q) → (P → R)))",
             [("P", "wff"), ("Q", "wff"), ("R", "wff")]),
        rule("ax-3", "transposition", [], "((¬P → ¬Q) → (Q → P))",
             [("P", "wff"), ("Q", "wff")]),
        rule("MP", "modus ponens", ["P", "(P → Q)"], "Q",
             [("P", "wff"), ("Q", "wff")]),
    ]


def renamed_propositional_calculus_spec(name: str = "Renamed") -> SystemSpec:
    """:func:`propositional_calculus_spec` with every name changed and nothing else.

    The sort is ``wff`` rather than ``formula`` and the productions are ``imp``,
    ``neg``, ``conj``, ``wff_var``; the **notation is identical**, so the two
    systems write `(P → P)` the same way and disagree only about what to call the
    production that spells it. That is the point of the fixture: a transferred
    term is rebuilt over *this* system's constructors by name, so without a map
    the citation cannot resolve at all, and with one nothing else has to change.

    A rename is what an edge between two independently-built systems needs, and
    the pair PC/PC-under-other-names isolates it — the alternative, two systems
    that also differ in what they can say, would leave a refusal ambiguous
    between the rename and the difference.
    """
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            regex_prod("wff", "wff_var", "[A-Z][A-Z0-9]*"),
            template_prod("wff", "neg", "¬p", [("p", "wff")]),
            template_prod("wff", "imp", "(p → q)", [("p", "wff"), ("q", "wff")]),
            template_prod("wff", "conj", "(p ∧ q)", [("p", "wff"), ("q", "wff")]),
        ],
        lines=[statement_line("wff")],
        rules=_wff_rules(),
        definitions=[
            defn("wff", "conj", "(P ∧ Q)", "¬(P → ¬Q)",
                 [("P", "wff"), ("Q", "wff")], label="df-an")
        ],
    )


def respelled_propositional_calculus_spec(name: str = "Respelled") -> SystemSpec:
    """:func:`renamed_propositional_calculus_spec`, and the *notation* moves too.

    ``→`` is ``⊃`` here and ``¬`` is ``~``. A map renames productions, and a
    production carries its template, so a transferred statement is written in
    whatever the target spells it — which is the visible half of an
    interpretation edge and the reason a transferred entry's text is re-rendered
    from its term rather than carried over.
    """
    spec = renamed_propositional_calculus_spec(name)
    spec.productions = [
        template_prod("wff", "neg", "~p", [("p", "wff")])
        if prod.name == "neg"
        else template_prod("wff", "imp", "(p ⊃ q)", [("p", "wff"), ("q", "wff")])
        if prod.name == "imp"
        else prod
        for prod in spec.productions
    ]
    spec.rules = [
        rule("ax-1", "simplification", [], "(P ⊃ (Q ⊃ P))",
             [("P", "wff"), ("Q", "wff")]),
        rule("MP", "modus ponens", ["P", "(P ⊃ Q)"], "Q",
             [("P", "wff"), ("Q", "wff")]),
    ]
    spec.definitions = [
        defn("wff", "conj", "(P ∧ Q)", "~(P ⊃ ~Q)",
             [("P", "wff"), ("Q", "wff")], label="df-an")
    ]
    return spec


def narrowed_propositional_calculus_spec(name: str = "Narrowed") -> SystemSpec:
    """:func:`renamed_propositional_calculus_spec` with ``conj`` outside ``wff``.

    Everything the map names is *present*, so a check that asked "does the target
    declare something called ``conj``?" would pass this — and the transferred
    theorem would then be a claim about a sort that does not contain the
    conjunctions it quantifies over. What refuses it is
    :attr:`Constructor.admits`: the source's ``formula`` admits its conjunction
    and the target's ``wff`` does not admit the image, so the map narrows (§3.2).

    ``conj`` is parked in a sort of its own rather than deleted, because deleting
    it would be refused one step earlier — as an image the target's grammar does
    not declare — and that is a different check.
    """
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            regex_prod("wff", "wff_var", "[A-Z][A-Z0-9]*"),
            template_prod("wff", "neg", "¬p", [("p", "wff")]),
            template_prod("wff", "imp", "(p → q)", [("p", "wff"), ("q", "wff")]),
            # Grammatical, and *not* a `wff`.
            template_prod("aside", "conj", "(p ∧ q)", [("p", "wff"), ("q", "wff")]),
        ],
        lines=[statement_line("wff")],
        rules=_wff_rules(),
    )


def renamed_first_order_spec(name: str = "Renamed FOL") -> SystemSpec:
    """The whole PC ⊂ FOL tower's *grammar*, flat, under other names.

    The target of the binder case. It declares an image for every production the
    tower's ``formula`` and ``term`` admit — which the sort map's check demands,
    and which is why ``exists`` is here although nothing below cites it — with
    ``all`` carrying the same ``scopes_over`` its counterpart does. It declares no
    rules at all: what it is for is *citing* theorems proved elsewhere, and a
    system whose every step is a citation makes it unambiguous which mechanism a
    passing proof exercised.
    """
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            regex_prod("wff", "wff_var", "[A-Z][A-Z0-9]*"),
            template_prod("wff", "neg", "¬p", [("p", "wff")]),
            template_prod("wff", "imp", "(p → q)", [("p", "wff"), ("q", "wff")]),
            template_prod("wff", "conj", "(p ∧ q)", [("p", "wff"), ("q", "wff")]),
            regex_prod("ind", "ind_var", "[a-z][a-z0-9]*"),
            template_prod("wff", "eq", "s = t", [("s", "ind"), ("t", "ind")]),
            template_prod("wff", "mem", "s ∈ t", [("s", "ind"), ("t", "ind")]),
            template_prod("wff", "all", "∀x p", [("x", "ind"), ("p", "wff")],
                          scopes_over={"x": ["p"]}),
            template_prod("wff", "exists", "∃x p", [("x", "ind"), ("p", "wff")],
                          scopes_over={"x": ["p"]}),
        ],
        lines=[statement_line("wff")],
    )


# The map from the PC ⊂ FOL tower's names to `renamed_first_order_spec`'s.
FOL_RENAME = {
    "sorts": {"formula": "wff", "term": "ind"},
    "symbols": {
        "prop_var": "wff_var",
        "negation": "neg",
        "implication": "imp",
        "conjunction": "conj",
        "variable": "ind_var",
        "equality": "eq",
        "membership": "mem",
        "universal": "all",
        "existential": "exists",
    },
}


# The map from `propositional_calculus_spec`'s names to the renamed layer's.
# Partial on purpose where it can be: only names that actually differ are here.
PC_RENAME = {
    "sorts": {"formula": "wff"},
    "symbols": {
        "prop_var": "wff_var",
        "negation": "neg",
        "implication": "imp",
        "conjunction": "conj",
    },
}


# --- pieces the rejection tests need ---------------------------------------


def redeclared_implication_spec(name: str = "Redeclared") -> SystemSpec:
    """A child that redeclares ``implication`` with a *different* template.

    The collision `layered_spec` exists to refuse: it would take over
    ``ctx.variables["implication"]``, so every theorem inherited from the
    propositional layer would be about a different connective.
    """
    return SystemSpec(
        name=name,
        productions=[
            template_prod(
                "formula",
                "implication",
                "(P ⊃ Q)",
                [("P", "formula"), ("Q", "formula")],
            )
        ],
    )


def bound_constant_spec(name: str = "Bound constant") -> SystemSpec:
    """A layer declaring a ``term`` leaf as a constant of the object language.

    Harmless alone. Under the FOL layer, whose ``∀`` ranges over ``term``, it is
    a token a binder can bind declared as one that cannot be — refused by
    ``_validate_constant_declarations``, and only *because* of the layer above.
    """
    return SystemSpec(
        name=name,
        productions=[atom_const_prod("term", "zero", "∅", denotes_constant=True)],
    )


def propositional_grammar_spec(name: str = "Propositional grammar") -> SystemSpec:
    """The propositional layer's grammar with **no** rules — the control.

    Same productions and line type, nothing that reasons over ``→``. It is the
    accepted half of the freshness pair below: the refusal must come from the
    ancestors' *primitives*, not from their notation.
    """
    return SystemSpec(
        name=name,
        brackets=brackets(),
        productions=[
            propositional_variable_prod(),
            negation_prod(),
            implication_prod(),
            conjunction_prod(),
        ],
        lines=[statement_line()],
    )


def redefining_implication_spec(name: str = "Redefinition") -> SystemSpec:
    """A child defining ``→`` — a symbol its *ancestors'* axioms reason over.

    Refused by ``_require_a_fresh_defined_form``, which sees the ancestors'
    primitives because the layered spec carries them. Layered on
    :func:`propositional_grammar_spec` instead — same notation, no rules — it is
    accepted, which is what says the refusal is about the primitives.

    What it defines ``→`` *as* is beside the point and deliberately trivial: the
    defining form must avoid ``∧``, or non-circularity refuses it first (``∧`` is
    itself defined over ``→``) and the freshness check never runs.
    """
    return SystemSpec(
        name=name,
        definitions=[
            defn(
                "formula",
                "implies",
                "(P → Q)",
                "¬¬Q",
                [("P", "formula"), ("Q", "formula")],
                label="df-im",
            )
        ],
    )


def extra_line_spec(name: str = "Extra line") -> SystemSpec:
    """A child adding a second line type without restating the ancestor's."""
    return SystemSpec(
        name=name,
        lines=[
            LineSpec(
                name="claim",
                shape="claim <formula>",
                logical_sort="formula",
            )
        ],
    )


def stacked_definitions_spec(name: str = "Stacked") -> SystemSpec:
    """A child whose second definition is written in its first one's notation.

    Both defined forms are new — no production spells them — so each is
    grammatical only because the definition before it registered it. That is what
    makes their *order* load-bearing, and it is only visible with the ancestors
    in front: read alone, neither `∧` nor anything else here parses, so nothing
    layers and there is nothing an order could lose.
    """
    return SystemSpec(
        name=name,
        definitions=[
            defn(
                "formula",
                "nand",
                "(P ⊼ Q)",
                "¬(P ∧ Q)",
                [("P", "formula"), ("Q", "formula")],
                label="df-nand",
            ),
            defn(
                "formula",
                "nor",
                "(P ⊽ Q)",
                "¬(P ⊼ Q)",
                [("P", "formula"), ("Q", "formula")],
                label="df-nor",
            ),
        ],
    )
