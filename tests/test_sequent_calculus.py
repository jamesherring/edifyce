"""Proving in a sequent calculus, with nothing added to the engine.

S1 of docs/system-relationships-roadmap.md, which delivers (c): sequents and the
deduction theorem, expressible because a **context is a term**. §6.2 predicted
that no engine change would be needed and said that needing one would itself be
the finding. None was: `tests/sequent_system.py` is an ordinary `SystemSpec`, and
everything below is an ordinary proof checked by the ordinary checker.

Two things it *did* find, both recorded against the tests that pin them:

* the eigenvariable condition is **stricter than the textbook one**, because
  `Occurs` is syntactic by design and cannot tell a bound occurrence from a free
  one (`test_a_bound_occurrence_blocks_generalisation_too`); and
* ∀L can only instantiate the bound variable with **itself**, since a rule
  schema has no substitution operator
  (`test_universal_left_instantiates_the_binder_with_itself`).

Both are sound — each refuses more than a textbook calculus would — and both are
about what an author can *say*, not about what the checker will believe.

A third thing it found is about *these tests* rather than about the engine, and
it is why `test_negation_refutes_only_what_yields_falsity` exists. ¬R was first
written as →R with the conclusion changed — `Γ, A ⊢ B ⟹ Γ ⊢ ¬A`, with `B`
unconstrained — which refutes every formula and makes the calculus below
inconsistent. Nothing failed, because no proof here cited ¬R and the fixture
guard only checked the label existed. Edifyce checks proofs against whatever
system it is handed and has no opinion about whether a declared rule is sound;
the whole burden is the author's, and **a rule no proof cites has discharged
none of it.** All twelve of the fixture's rules are cited by an accepted proof
below, which is the discipline that would have caught this one.
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_spec
from website.logical.kernel import from_match
from website.logical.kernel.terms import Node
from website.logical.matching import UnionPattern

from tests.sequent_system import sequent_spec

if TYPE_CHECKING:
    from website.logical.formal_system import FormalSystem
    from website.logical.kernel.terms import Term


@pytest.fixture(scope="module")
def system() -> FormalSystem:
    built = build_spec(sequent_spec())
    assert "errors" not in built, built["errors"]
    return built["system"]


def stands(system: FormalSystem, source: str) -> bool:
    """Whether ``source`` checks, as a whole proof."""
    return bool(system.parse(source).valid)


def why(system: FormalSystem, source: str) -> str:
    """Every reason a line of ``source`` did not check, for a refusal's message."""
    proof = system.parse(source)
    return " | ".join(
        f"{line.number}: {line.invalid_message}"
        for line in proof.proof_lines
        if not line.empty and not line.valid and line.invalid_message
    )


def test_the_system_is_the_one_these_tests_assume(system: FormalSystem) -> None:
    # A guard on the fixture rather than on the code: every refusal below would
    # pass just as well against a system that declared none of these rules, or
    # whose grammar could not state a sequent at all.
    assert {rule.label for rule in system.inference_rules} == {
        "id", "refl", "WL", "XL", "CL", "cut", "→R", "→L", "¬L", "¬R", "∀R", "∀L",
    }
    assert stands(system, "∅ , A ⊢ A [id]")
    assert not stands(system, "∅ , A ⊢ B [id]")


# ---------------------------------------------------------------------------
# The deduction theorem, which is the whole point
# ---------------------------------------------------------------------------


def test_the_identity_yields_an_implication(system: FormalSystem) -> None:
    # `⊢ (A → A)` from identity and →R — the smallest thing a sequent calculus
    # has to be able to do, and the one Edifyce could not state before, because
    # a natural-deduction assumption context is a property of the *proof* and
    # cannot appear in what a line says (§6.1).
    assert stands(system, "∅ , A ⊢ A [id]\n∅ ⊢ (A → A) [→R, 1]")


def test_the_deduction_theorem_on_a_three_assumption_context(system: FormalSystem) -> None:
    # →R with a context under it: `Γ, A ⊢ B` gives `Γ ⊢ (A → B)` for a Γ that is
    # itself two assumptions. Nothing about the rule mentions how long Γ is —
    # it is one metavariable, and unification splits the rightmost assumption off
    # a left-nested list.
    assert stands(system, "P , Q , R ⊢ R [id]\nP , Q ⊢ (R → R) [→R, 1]")


def test_the_converse_direction(system: FormalSystem) -> None:
    # The other way: from `Γ ⊢ (A → B)` to `Γ, A ⊢ B`, which is modus ponens
    # written as a sequent. Derived rather than declared — →L and exchange are
    # what it takes, and that it *is* derivable is why the calculus needs no rule
    # for it.
    assert stands(
        system,
        "∅ , A ⊢ A [id]\n"
        "∅ , A , B ⊢ B [id]\n"
        "∅ , A , (A → B) ⊢ B [→L, 1, 2]\n"
        "∅ , (A → B) , A ⊢ B [XL, 3]",
    )


# ---------------------------------------------------------------------------
# The structural rules — the cost §6.2 names, in use
# ---------------------------------------------------------------------------


def test_weakening_and_exchange(system: FormalSystem) -> None:
    # A list is not a set, so an assumption arrives at the right-hand end and
    # has to be walked to where a rule wants it. Both cited by hand, which is
    # honest sequent calculus and is what S3 measures the cost of.
    assert stands(
        system,
        "∅ , A ⊢ A [id]\n"
        "∅ , A , B ⊢ A [WL, 1]\n"
        "∅ , B , A ⊢ A [XL, 2]",
    )


def test_contraction(system: FormalSystem) -> None:
    assert stands(
        system,
        "∅ , A ⊢ A [id]\n"
        "∅ , A , A ⊢ A [WL, 1]\n"
        "∅ , A ⊢ A [CL, 2]",
    )


def test_cut(system: FormalSystem) -> None:
    # `⊢ (B → a = a)` through a cut on `a = a`. The same sequent has a cut-free
    # derivation — weaken `refl` and apply →R — which is Gentzen's theorem
    # rather than a defect of the fixture; both are written here because the
    # rule is only exercised by a proof that uses it.
    assert stands(
        system,
        "∅ ⊢ a = a [refl]\n"
        "∅ , a = a ⊢ a = a [id]\n"
        "∅ , a = a , B ⊢ a = a [WL, 2]\n"
        "∅ , a = a ⊢ (B → a = a) [→R, 3]\n"
        "∅ ⊢ (B → a = a) [cut, 1, 4]",
    )
    assert stands(
        system,
        "∅ ⊢ a = a [refl]\n"
        "∅ , B ⊢ a = a [WL, 1]\n"
        "∅ ⊢ (B → a = a) [→R, 2]",
    )


def test_negation_refutes_only_what_yields_falsity(system: FormalSystem) -> None:
    # ¬R is single-succedent, so it needs `⊥`: with one formula on the right,
    # "assuming A proves *something*" is not a refutation of A. Written with an
    # unconstrained metavariable where `⊥` stands — `G , A ⊢ B` ⟹ `G ⊢ ¬A`, the
    # shape →R has and the shape this rule first had — every formula is
    # refutable and the calculus proves both `⊢ a = a` and `⊢ ¬a = a`.
    #
    # The pair is the test: `∅ , A ⊢ ¬¬A` goes through, and the derivation that
    # the unsound reading would license does not.
    assert stands(
        system,
        "∅ , A ⊢ A [id]\n"
        "∅ , A , ¬A ⊢ ⊥ [¬L, 1]\n"
        "∅ , A ⊢ ¬¬A [¬R, 2]",
    )

    inconsistent = "∅ , a = a ⊢ a = a [id]\n∅ ⊢ ¬a = a [¬R, 1]"
    assert not stands(system, inconsistent)
    assert "¬R does not apply" in why(system, inconsistent)


# ---------------------------------------------------------------------------
# The eigenvariable condition — the phase's central case
# ---------------------------------------------------------------------------


def test_generalisation_over_a_context_that_does_not_mention_the_variable(system: FormalSystem) -> None:
    # ∀R's proviso is `not occurs(x, G)`, and `G` is a **term** — so this is the
    # kernel's ordinary `Occurs` descending an ordinary sort. Nothing about
    # sequents reaches the checker.
    #
    # Both accepted cases: an empty context, and a non-empty one about some
    # other variable.
    assert stands(system, "∅ ⊢ a = a [refl]\n∅ ⊢ ∀a a = a [∀R, 1]")
    assert stands(system, "c = c ⊢ a = a [refl]\nc = c ⊢ ∀a a = a [∀R, 1]")


def test_generalisation_over_a_context_that_does_mention_it(system: FormalSystem) -> None:
    # And the refusal, which is the phase's central test: one line differs from
    # the accepted pair above — the context is about `a` rather than `c` — and
    # the derivation stops. `a = a ⊢ ∀a a = a` is exactly the false step a
    # missing eigenvariable condition licenses.
    #
    # It is expressible *only* because the context is a term the kernel can
    # descend (§3.4). A context carried as text with a separator would have put
    # this decision back in the parser.
    source = "a = a ⊢ a = a [refl]\na = a ⊢ ∀a a = a [∀R, 1]"
    assert not stands(system, source)
    assert "∀R does not apply" in why(system, source)


def test_a_bound_occurrence_blocks_generalisation_too(system: FormalSystem) -> None:
    # **A finding, pinned as behaviour rather than asserted as right.**
    #
    # `∅ , ∀a a = a ⊢ ∀a a = a` is derivable in a textbook calculus: the
    # eigenvariable condition is that `a` is not *free* in the context, and here
    # every occurrence of it is bound by the very quantifier in the assumption.
    # It is refused, because `Occurs` is syntactic — the kernel says so in as
    # many words, and deliberately: a condition that needs binder scoping
    # "depends on the object logic or on proof state and is intentionally not
    # expressible here" (`kernel/side_conditions.py`).
    #
    # So the proviso available is a sound over-approximation of the one the
    # calculus wants, in the same way Metamath's `$d` is. What it costs an
    # author is generalising over a variable the context mentions anywhere at
    # all, however bound; what it never costs is a wrong verdict.
    assert stands(
        system,
        "∅ , a = a ⊢ a = a [id]\n∅ , ∀a a = a ⊢ a = a [∀L, 1]",
    )
    assert not stands(
        system,
        "∅ , a = a ⊢ a = a [id]\n"
        "∅ , ∀a a = a ⊢ a = a [∀L, 1]\n"
        "∅ , ∀a a = a ⊢ ∀a a = a [∀R, 2]",
    )


def test_universal_left_instantiates_the_binder_with_itself(system: FormalSystem) -> None:
    # **The other finding.** §8's S1 asks for "∀L instantiated with a term that
    # would capture → rejected", which supposes a ∀L that instantiates. A rule
    # schema has no substitution operator — it is matched by unification, and
    # `P[t/x]` is not something a pattern can say — so the ∀L that *is*
    # expressible instantiates the bound variable with itself: from `Γ, P ⊢ C`
    # infer `Γ, ∀x P ⊢ C`, which is sound for every P, x, and t-free.
    #
    # There is therefore no capture to reject, which is why no test asserts one.
    # Instantiating with an arbitrary term needs either substitution in the
    # schema language or ∀L stated as a *definition*, and neither is S1's.
    assert stands(system, "∅ , A ⊢ A [id]\n∅ , ∀a A ⊢ A [∀L, 1]")


# ---------------------------------------------------------------------------
# What a context is, asserted on the term
# ---------------------------------------------------------------------------


def test_a_context_is_a_left_nested_list(system: FormalSystem) -> None:
    # §8.0's rule that a claim about terms is asserted about terms. `A , B , C`
    # is `((A , B) , C)` and can be nothing else: the right of a comma is a
    # formula, so no other nesting is even grammatical — which is what makes
    # "the rightmost assumption" a thing →R can name.
    context = _term(system, "A , B , C")
    assert isinstance(context, Node) and context.constructor.name == "cons"
    assert context.children["a"].literal == "C"
    assert context.children["g"].constructor.name == "cons"


def test_the_empty_context_extended_is_not_a_bare_formula(system: FormalSystem) -> None:
    # The encoding's honest cost, and the reason a proof cannot drift between
    # the two spellings: `∅ , A` and `A` mean the same context and are different
    # terms, so a rule matched against one does not apply to the other.
    assert _term(system, "∅ , A") != _term(system, "A")
    assert stands(system, "∅ , A ⊢ A [id]\n∅ ⊢ (A → A) [→R, 1]")
    assert not stands(system, "∅ , A ⊢ A [id]\nA ⊢ (A → A) [→R, 1]")


def test_implication_right_reaches_only_the_rightmost_assumption(system: FormalSystem) -> None:
    # From `P, Q, R ⊢ R`, →R discharges `R` and not `Q`. The accepted half is
    # `test_the_deduction_theorem_on_a_three_assumption_context`; this is its
    # pair, and the second proof is the price — the *same* target sequent, and
    # what it takes to reach it is exchange, cited by hand.
    #
    # The two halves must end on the same line for that to be the claim: a
    # second proof reaching some *other* conclusion would show only that some
    # longer derivation exists, not that exchange is what the rejected step was
    # missing.
    assert not stands(system, "P , Q , R ⊢ R [id]\nP , R ⊢ (Q → R) [→R, 1]")
    assert stands(
        system,
        "P , Q , R ⊢ R [id]\n"
        "P , R , Q ⊢ R [XL, 1]\n"
        "P , R ⊢ (Q → R) [→R, 2]",
    )


def test_contraction_needs_two_of_the_same(system: FormalSystem) -> None:
    # CL is `G , A , A ⊢ C`, so two *different* assumptions do not contract —
    # asserted against the accepted case above, which differs only in that.
    assert not stands(system, "P , A , B ⊢ B [id]\nP , A ⊢ B [CL, 1]")


# ---------------------------------------------------------------------------
# What makes the grammar viable at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assumptions", [4, 8, 12])
def test_a_proof_line_reads_its_context_once_per_assumption(
    system: FormalSystem, assumptions: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S3's answer, asserted where the claim actually lives.
    #
    # A context is `∅ | wff | context , wff` — recursive on the *left*, so every
    # comma is a candidate split and the sort re-enters itself at each one.
    # Read without memoisation that is exponential: `benchmarks/bench_matching
    # --only sequent-context` times a bare pattern match at 0.2 ms, 2.4 ms,
    # 40 ms and 18 s for 4, 8, 12 and 20 assumptions. What makes it linear
    # instead is that `LineType.parse_line` gives every line a fresh
    # `parse_memo`, and *that* is the load-bearing fact — the roadmap closes S3
    # on it.
    #
    # `tests/test_matching_stress.py` pins the same bound on a bare pattern, but
    # it installs the memo itself, so it holds whatever `parse_line` does. This
    # goes through the real path: a whole proof, checked by the system, with
    # nothing but `parse_line` to supply the memo. Counted rather than timed, so
    # it says which property regressed and holds on a loaded machine.
    counted = {"n": 0}
    original = UnionPattern._match

    def counting(self, *args, **kwargs):
        counted["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(UnionPattern, "_match", counting)

    context = " , ".join(["∅", *["A"] * assumptions])
    assert stands(system, f"{context} ⊢ A [id]")

    # Two sorts per assumption and change — linear, with room for the fixed cost
    # of the line type and the rule's own schemas. What it rules out is scaling
    # with the number of *ways* the commas could be cut up: at twelve
    # assumptions the memoless read is already four orders of magnitude over
    # this.
    assert counted["n"] <= 4 * assumptions + 20


def _term(system: FormalSystem, text: str) -> Term:
    """The kernel term ``text`` parses to at the ``context`` sort."""
    matched = system.build_context.variables["context"].match(text, copy(system.context))
    assert matched is not None, f"{text!r} does not parse as a context"
    return from_match(matched)
