"""What a checked line says about *why* it checked.

`diagnostics` is tested for the failure side; this is the other half. A citation
names a step (`[MP, 1, 2]`) without explaining it, and what the checker actually
established — the rule's own schemas, which line filled which premise, and above
all the substitution the match derived — is already on the line and was going
nowhere.
"""

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_system
from website.logical.formal_system.justification import justification
from website.logical.rendering import Projection

from tests.miu_system import miu_spec
from tests.spec_helpers import (
    assumption_line,
    brackets,
    cp_rule,
    defn,
    hyp_rule,
    implication_prod,
    mp_rule,
    membership_prod,
    regex_prod,
    reiteration_rule,
    rule,
    statement_line,
    subset_def,
    template_prod,
    universal_prod,
    variable_prod,
)


def pq() -> list[tuple[str, str]]:
    return [("p", "formula"), ("q", "formula")]


@pytest.fixture(scope="module")
def system():
    return build_system(
        SystemSpec(
            name="PropLogic",
            brackets=brackets(),
            productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
            lines=[statement_line(), assumption_line()],
            rules=[
                hyp_rule(),
                mp_rule(),
                reiteration_rule(),
                rule("RImp", "reflexive", (), "(p → q)", pq(), ["equal(p, q)"]),
                cp_rule(),
            ],
        )
    )


def line_of(proof, number):
    return next(line for line in proof.proof_lines if line.number == number)


def test_a_step_reports_the_rule_it_resolved_to(system):
    proof = system.parse("a [HYP]\n(a → b) [HYP]\nb [MP, 1, 2]")
    assert proof.valid is True

    told = justification(line_of(proof, 3))

    assert told is not None
    assert (told.kind, told.label, told.name) == ("rule", "MP", "modus ponens")
    # The rule's own conclusion, not this line's — the schema is what the step is
    # an instance *of*, and it is what a reader who does not know `MP` needs.
    assert told.conclusion == "q"


def test_the_premises_pair_the_rules_slots_with_the_cited_lines(system):
    proof = system.parse("a [HYP]\n(a → b) [HYP]\nb [MP, 1, 2]")

    told = justification(line_of(proof, 3))

    assert [(p.position, p.schema, p.number, p.statement) for p in told.premises] == [
        (0, "p", 1, "a"),
        (1, "(p → q)", 2, "(a → b)"),
    ]


def test_the_assignments_are_what_the_metavariables_stood_for(system):
    # The whole point: `[MP, 1, 2]` says a rule applied, and this says the rule
    # applied *with p as a and q as b*, which is what makes the step checkable by
    # a reader rather than only by the kernel.
    proof = system.parse("a [HYP]\n(a → b) [HYP]\nb [MP, 1, 2]")

    told = justification(line_of(proof, 3))

    assert [(a.variable, a.stands_for) for a in told.assignments] == [
        ("p", "a"),
        ("q", "b"),
    ]


def test_the_assignments_are_read_through_a_notation(system):
    # A reader looking at a proof in one spelling must not be shown the
    # substitution in another.
    proof = system.parse("a [HYP]\n(a → b) [HYP]\nb [MP, 1, 2]")
    # A spelling the grammar does not use, so a reading that ignored the
    # projection would come back with the source's `→` and be caught.
    horseshoe = Projection(
        name="horseshoe",
        templates={
            "implication": (("lit", "("), ("slot", "p"), ("lit", " ⊃ "), ("slot", "q"), ("lit", ")"))
        },
    )

    # HYP binds its one metavariable to the whole formula, so line 2's assignment
    # is the implication itself — the case where a notation shows.
    assert [a.stands_for for a in justification(line_of(proof, 2), horseshoe).assignments] == [
        "(a ⊃ b)"
    ]
    # And the premises a step quotes are read the same way, so one record is not
    # half in one spelling and half in another.
    assert [p.statement for p in justification(line_of(proof, 3), horseshoe).premises] == [
        "a",
        "(a ⊃ b)",
    ]


def test_a_proviso_is_reported_in_the_authors_own_words(system):
    # `x not free in phi` is what a reader can check; the repr of a frozen
    # dataclass is not. The variables it names are how they find it in the
    # assignments.
    proof = system.parse("(a → a) [RImp]")
    assert proof.valid is True

    told = justification(line_of(proof, 1))

    assert [(p.source, p.variables) for p in told.provisos] == [
        ("equal(p, q)", ("p", "q"))
    ]


def test_a_discharge_names_the_block_it_consumed_and_binds_nothing(system):
    # `check_discharge` records the rule and the verdict but keeps no binding, so
    # this must say what it can and not invent the rest.
    proof = system.parse("    assume a\n    a [R, 1]\n(a → a) [CP, 1]")

    told = justification(line_of(proof, 3))

    assert told is not None
    assert told.label == "CP"
    assert told.discharges == "[assume p ⊢ q]"
    assert told.assignments == ()


def test_an_unjustified_line_is_explained_by_nothing(system):
    # A hole, a scope opener, a comment and a failed line all report *no*
    # justification — each is a different thing to say, and `diagnostics` is
    # where they are said.
    proof = system.parse("a")

    assert justification(line_of(proof, 1)) is None


def test_a_definitional_step_names_the_definition_that_applied(system):
    # A `[Def, n]` citation names none — the checker searches the definitions in
    # scope — so which one applied is knowable only from the line.
    built = build_system(
        SystemSpec(
            name="Defined",
            brackets=brackets(),
            productions=[
                regex_prod("formula", "atom", "[a-z]"),
                implication_prod(),
                template_prod("formula", "self_implies", "refl p", [("p", "formula")]),
            ],
            lines=[statement_line()],
            definitions=[
                defn(
                    "formula",
                    "refl",
                    "refl p",
                    "(p → p)",
                    [("p", "formula")],
                    label="df-refl",
                )
            ],
            rules=[hyp_rule()],
        )
    )
    proof = built.parse("refl a [HYP]\n(a → a) [Def, 1]")
    assert proof.valid is True

    told = justification(line_of(proof, 2))

    assert told is not None
    assert told.kind == "definition"
    assert told.label == "df-refl"
    assert told.conclusion == "refl p ≝ (p → p)"


def test_a_slot_the_rule_never_named_is_not_reported_as_an_assignment(system):
    # A bare-sort slot (`formula` meaning "any formula") has no name to share by,
    # so the schema projection renames each occurrence apart — `formula\x000`.
    # That name appears in no schema and no proviso beside it, so reporting it
    # would be reporting the machinery. The premise row already names the line.
    built = build_system(
        SystemSpec(
            name="Pairs",
            brackets=brackets(),
            productions=[regex_prod("formula", "atom", "[a-z]"), implication_prod()],
            lines=[statement_line()],
            rules=[hyp_rule(), rule("PAIR", "pair", ["formula", "formula"], "p", pq())],
        )
    )
    proof = built.parse("a [HYP]\nb [HYP]\nc [PAIR, 1, 2]")
    assert proof.valid is True

    told = justification(line_of(proof, 3))

    assert [a.variable for a in told.assignments] == ["p"]
    assert [(p.schema, p.number) for p in told.premises] == [
        ("formula", 1),
        ("formula", 2),
    ]


def test_a_definitions_binders_are_shown_by_the_name_they_were_declared_with():
    # A defining form stores its binders abstractly, by index, because an unfold's
    # consumer chooses each one's name. A reader is not that consumer: without the
    # declared name put back, `x ⊆ y` reads as `∀⟨0⟩ (⟨0⟩ ∈ x → …)`.
    built = build_system(
        SystemSpec(
            name="Sets",
            brackets=brackets(),
            productions=[
                variable_prod(),
                membership_prod(),
                implication_prod(),
                universal_prod(),
                template_prod(
                    "formula", "subset", "x ⊆ y", [("x", "variable"), ("y", "variable")]
                ),
            ],
            lines=[statement_line()],
            definitions=[subset_def()],
            rules=[hyp_rule()],
        )
    )
    proof = built.parse("a ⊆ b [HYP]\n∀z (z ∈ a → z ∈ b) [Def, 1]")
    assert proof.valid is True, [
        (line.display, line.invalid_message) for line in proof.proof_lines
    ]

    told = justification(line_of(proof, 2))

    assert told.conclusion == "x ⊆ y ≝ ∀z (z ∈ x → z ∈ y)"


def test_an_unlabelled_definition_reports_no_label_rather_than_a_stand_in():
    # `Def` is how a *citation* reaches a definition, not a name one has. Putting
    # it here would hand a caller a label to look prose or a proof up by that
    # names no definition at all.
    built = build_system(
        SystemSpec(
            name="Unlabelled",
            brackets=brackets(),
            productions=[
                regex_prod("formula", "atom", "[a-z]"),
                implication_prod(),
                template_prod("formula", "self_implies", "refl p", [("p", "formula")]),
            ],
            lines=[statement_line()],
            definitions=[
                defn("formula", "refl", "refl p", "(p → p)", [("p", "formula")])
            ],
            rules=[hyp_rule()],
        )
    )
    proof = built.parse("refl a [HYP]\n(a → a) [Def, 1]")
    assert proof.valid is True

    told = justification(line_of(proof, 2))

    assert told.label == ""
    assert told.conclusion == "refl p ≝ (p → p)"


def test_a_rewriting_step_says_what_its_variables_matched():
    # A semi-Thue rule binds surface *strings* by associative matching, and the
    # checker keeps that substitution apart from the term one so nothing meaning
    # terms can read it. To a reader it is the same question — and it is the one
    # thing a rewriting rule's citation cannot say.
    built = build_system(miu_spec())
    proof = built.parse("MI\nMII [R2, 1]")
    assert proof.valid is True, [
        (line.display, line.invalid_message) for line in proof.proof_lines
    ]

    told = justification(line_of(proof, 2))

    assert told is not None
    assert [(a.variable, a.stands_for) for a in told.assignments] == [("x", "I")]
