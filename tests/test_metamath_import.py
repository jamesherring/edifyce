"""Importing Metamath into Edifyce: the ``sqrt2re`` vertical slice.

Covers ``website.logical.metamath`` end to end — read ``.mm`` source, build the
grammar from its syntax axioms, promote its logical assertions to citable
theorems, decode a compressed proof, and have Edifyce's own kernel check the
result.

The specimen is set.mm's ``sqrt2re`` ("the square root of 2 is a real number"),
whose stored proof is short enough to reason about in full::

    sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
      ( c2 2re 2pos sqrtpclii ) ABCD $.

Executing ``ABCD`` against that label table: ``c2`` builds the class ``2``
(*syntax* — no logical content), ``2re`` and ``2pos`` supply ``|- 2 e. RR`` and
``|- 0 < 2``, and ``sqrtpclii`` consumes all three to conclude. So four stored
steps import as **three** proof lines: Edifyce parses well-formedness instead of
proving it, and the syntax step simply disappears.

``2re``/``2pos``/``sqrtpclii`` appear here as ``$a``, standing in for the part of
the library an import would already have processed; ``sqrt2re``'s proof is the
verbatim set.mm string, which is what the decoder is actually tested against.
"""

from __future__ import annotations

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_system
from website.logical.metamath import (
    MetamathError,
    build_spec,
    decode,
    import_database,
    import_proof,
    import_theorem,
    parse,
    promote_assertions,
    split_proof,
)
from website.logical.metamath.corpus import walk
from website.logical.metamath.importer import (
    _distinct_provisos,
    _givens,
    _proviso_safe_names,
    grammar_schedule,
)
from website.logical.metamath.parser import Hypothesis


def notation_names(spec) -> list[str]:
    """The productions a syntax axiom declared, in order.

    Everything else in a spec's grammar is machinery the import adds: the atom
    leaf per `$v` variable, and the shapeless production including each
    `<typecode>_var` sub-sort into its typecode.
    """
    return [
        p.name
        for p in spec.productions
        if not p.sort.endswith("_var") and not p.name.endswith("_var")
    ]


def variables_of(spec, typecode: str) -> set[str]:
    """The variable tokens the grammar admits as leaves of `typecode`."""
    return {
        p.atom_value for p in spec.productions if p.sort == f"{typecode}_var"
    }


# A self-contained fragment of set.mm: every statement below is quoted from it.
SQRT2RE_FRAGMENT = r"""
$c |- wff class ( ) ` e. RR sqrt 2 0 < $.
$v A B F R $.
cA $f class A $.
cB $f class B $.
cF $f class F $.
cR $f class R $.

$( Syntax axioms — in Metamath these *are* the grammar. $)
wcel $a wff A e. B $.
wbr $a wff A R B $.
cfv $a class ( F ` A ) $.
c2 $a class 2 $.
cr $a class RR $.
csqrt $a class sqrt $.
cc0 $a class 0 $.
clt $a class < $.

$( The library this slice builds on. $)
2re $a |- 2 e. RR $.
2pos $a |- 0 < 2 $.
${
  sqrtthi.1 $e |- A e. RR $.
  ${
    sqrpclii.2 $e |- 0 < A $.
    sqrtpclii $a |- ( sqrt ` A ) e. RR $.
  $}
$}

$( The theorem, with its proof exactly as set.mm stores it. $)
sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
  ( c2 2re 2pos sqrtpclii ) ABCD $.
"""


# A theorem proved *under* an essential hypothesis. `dup`'s mandatory hypotheses
# are `[wph, dup.1]`, so `AABBC` pushes `ph`, `ph`, `|- ph`, `|- ph` and applies
# `jca` — the premise is selected twice, by letter rather than by a `Z` save.
HYPOTHESIS_FRAGMENT = r"""
$c |- wff ( ) -> /\ $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wa $a wff ( ph /\ ps ) $.
${
  jca.1 $e |- ph $.
  jca.2 $e |- ps $.
  jca $a |- ( ph /\ ps ) $.
$}
${
  dup.1 $e |- ph $.
  dup $p |- ( ph /\ ph ) $= ( jca ) AABBC $.
$}
"""


# Two proved theorems, the second under a `$f` declared inside its own scope, so
# `ch` is out of scope at `dup` and in scope at `tri`. A `$v`/`$f` at top level
# would not do: an *active* floating hypothesis is citable as a dummy variable
# from the first assertion onward, so only a scoped one comes into scope late.
LATE_VARIABLE_FRAGMENT = r"""
$c |- wff ( ) -> /\ $.
$v ph ps ch $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wa $a wff ( ph /\ ps ) $.
${
  jca.1 $e |- ph $.
  jca.2 $e |- ps $.
  jca $a |- ( ph /\ ps ) $.
$}
${
  dup.1 $e |- ph $.
  dup $p |- ( ph /\ ph ) $= ( jca ) AABBC $.
$}
${
  wch $f wff ch $.
  tri.1 $e |- ch $.
  tri $p |- ( ch /\ ch ) $= ( jca ) AABBC $.
$}
"""


# As above, but `ch`'s first `$f` sits in a block with no assertion in it, so the
# earliest-*declared* `wff` variable is the latest-*mentioned* one. That is what
# tells apart scheduling the `wff_var` sub-sort at its first member's position and
# scheduling it at the earliest of them.
DECLARED_BEFORE_MENTIONED_FRAGMENT = r"""
$c |- wff ( ) -> /\ $.
$v ph ps ch $.
${
  wch $f wff ch $.
$}
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
wa $a wff ( ph /\ ps ) $.
${
  jca.1 $e |- ph $.
  jca.2 $e |- ps $.
  jca $a |- ( ph /\ ps ) $.
$}
${
  dup.1 $e |- ph $.
  dup $p |- ( ph /\ ph ) $= ( jca ) AABBC $.
$}
${
  wch2 $f wff ch $.
  tri.1 $e |- ch $.
  tri $p |- ( ch /\ ch ) $= ( jca ) AABBC $.
$}
"""


# A fragment with a binder sort (`setvar`, which no syntax axiom builds) and a
# `$d`, for the sort-restriction and variable-membership tests.
BINDER_FRAGMENT = r"""
$c |- wff class setvar = RR A. e. $.
$v x ph A B $.
vx $f setvar x $.
wph $f wff ph $.
cA $f class A $.
cB $f class B $.
wceq $a wff A = B $.
wcel $a wff A e. B $.
wal $a wff A. x ph $.
cr $a class RR $.
${
  $d A B $.
  ax $a |- A = B $.
$}
"""


EXPECTED_PROOF = (
    "2 e. RR [2re]\n"
    "0 < 2 [2pos]\n"
    "( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]"
)


@pytest.fixture(scope="module")
def database():
    return parse(SQRT2RE_FRAGMENT)


# ---------------------------------------------------------------------------
# Reading .mm source
# ---------------------------------------------------------------------------
def test_syntax_and_logic_are_separated(database):
    # The `|-` typecode marks an assertion of truth; every other typecode
    # declares notation. Keeping them apart is what lets syntax steps vanish.
    assert [a.label for a in database.syntax_assertions()] == [
        "wcel", "wbr", "cfv", "c2", "cr", "csqrt", "cc0", "clt",
    ]
    assert [a.label for a in database.logical_assertions()] == [
        "2re", "2pos", "sqrtpclii", "sqrt2re",
    ]


def test_mandatory_hypotheses_are_scoped_and_ordered(database):
    # `sqrtpclii` sits inside two nested scopes, so it takes both essentials —
    # plus the floating hypothesis for the `A` they mention, which is declared
    # far earlier. Order is declaration order, and it is what the proof's stack
    # machine pops by, so getting it wrong silently misaligns every application.
    assert [h.label for h in database.assertions["sqrtpclii"].mandatory] == [
        "cA", "sqrtthi.1", "sqrpclii.2",
    ]

    # `sqrt2re` mentions no variables and sits in no scope: nothing is mandatory,
    # which is why its proof indexes the label table directly.
    assert database.assertions["sqrt2re"].mandatory == ()


def test_floating_hypotheses_of_unmentioned_variables_are_not_mandatory(database):
    # `cB`/`cF`/`cR` are active everywhere but mentioned by neither `sqrtpclii`'s
    # statement nor its essentials, so they are not popped when it is applied.
    mandatory = {h.label for h in database.assertions["sqrtpclii"].mandatory}
    assert {"cB", "cF", "cR"}.isdisjoint(mandatory)


def test_comments_and_scope_errors(database):
    assert parse("$c a $. $( a comment $) $v x $.").constants == {"a"}

    with pytest.raises(MetamathError, match="Unterminated comment"):
        parse("$c a $. $( never closed")

    with pytest.raises(MetamathError, match="Unbalanced"):
        parse("${ $c a $.")


# ---------------------------------------------------------------------------
# The compressed proof format
# ---------------------------------------------------------------------------
def test_split_proof_separates_the_label_table(database):
    labels, letters = split_proof(database.assertions["sqrt2re"].proof)
    assert labels == ["c2", "2re", "2pos", "sqrtpclii"]
    assert letters == "ABCD"


def test_uncompressed_proofs_are_refused():
    with pytest.raises(MetamathError, match="Only compressed proofs"):
        split_proof(("2re", "ax-mp"))


def test_letters_number_steps_in_base_twenty():
    # A-T are 1-20; each leading U-Y adds a further 20 in base five, so the
    # sequence runs A..T, UA..UT, VA.., .., YA..YT, then UUA.
    labels = [f"L{n}" for n in range(1, 130)]

    def selected(letters):
        return [step.label for step in decode(letters, labels, ())]

    assert selected("A") == ["L1"]
    assert selected("T") == ["L20"]
    assert selected("UA") == ["L21"]
    assert selected("UT") == ["L40"]
    assert selected("VA") == ["L41"]
    assert selected("YA") == ["L101"]
    assert selected("UUA") == ["L121"]
    assert selected("ABC") == ["L1", "L2", "L3"]


def test_step_numbers_select_across_the_three_bands():
    # Band 1 is the theorem's own mandatory hypotheses, band 2 the label table,
    # band 3 the steps saved by `Z`.
    hypothesis = Hypothesis(
        label="h1", typecode="|-", tokens=("A",), floating=False, position=0
    )
    steps = decode("ABZC", ["only"], (hypothesis,))

    assert steps[0].hypothesis is hypothesis         # 1 -> the mandatory hyp
    assert steps[1].label == "only"                  # 2 -> the one table entry
    assert steps[1].saved is True                    # ...tagged by the Z
    assert steps[2].backreference == 0               # 3 -> the first saved step


def test_malformed_letter_streams_are_rejected():
    with pytest.raises(MetamathError, match="'Z' does not follow"):
        decode("Z", ["a"], ())

    with pytest.raises(MetamathError, match="ends mid-number"):
        decode("AU", ["a"], ())

    with pytest.raises(MetamathError, match="unexpected character"):
        decode("A?", ["a"], ())


# ---------------------------------------------------------------------------
# The import itself
# ---------------------------------------------------------------------------
def test_syntax_axioms_become_the_grammar(database):
    spec = build_spec(database)
    productions = {p.name: p for p in spec.productions}

    # A syntax axiom with variables is a template over its floating hypotheses,
    # which are listed in *declaration* order (`cA` precedes `cF` in the file),
    # not in order of appearance in the template.
    assert productions["cfv"].sort == "class"
    assert productions["cfv"].template == "( F ` A )"
    assert productions["cfv"].bindings == [("A", "class"), ("F", "class")]

    # ...and one without is a constant of its sort.
    assert productions["c2"].atom_value == "2"
    assert productions["c2"].template is None


def test_logical_assertions_are_promoted_not_made_rules(database):
    system = import_database(database)

    assert set(system.promoted_theorems) == {"2re", "2pos", "sqrtpclii", "sqrt2re"}
    # They are derived results, so they stay out of the system's primitive rules.
    assert system.inference_rules == []

    # `sqrtpclii` keeps its premises and its metavariable, so it re-instantiates.
    promoted = system.promoted_theorems["sqrtpclii"]
    assert len(promoted.antecedents) == 2
    assert set(promoted.variables) == {"A"}

    # `2re` is closed: nothing to instantiate.
    assert system.promoted_theorems["2re"].antecedents == ()
    assert system.promoted_theorems["2re"].variables == {}


def test_sqrt2re_imports_to_the_expected_proof(database):
    assert import_proof(database, "sqrt2re") == EXPECTED_PROOF


def test_syntax_steps_emit_no_proof_line(database):
    # Four stored steps (`ABCD`), three imported lines: `c2` built the class `2`,
    # which Edifyce gets by parsing rather than by proof.
    _labels, letters = split_proof(database.assertions["sqrt2re"].proof)
    assert len(letters) == 4
    assert len(import_proof(database, "sqrt2re").splitlines()) == 3


def test_the_imported_proof_is_checked_by_the_kernel(database):
    # The payoff: a real Metamath proof, translated, and verified by Edifyce's
    # own checker. Nothing in the importer re-verifies anything.
    system, text = import_theorem(database, "sqrt2re")
    proof = system.parse(text)

    assert proof.valid is True
    assert all(line.valid for line in proof.proof_lines)


def test_a_tampered_import_is_rejected(database):
    # The check is real: swap the conclusion for one that does not follow and the
    # kernel refuses it, so a green import is evidence rather than assumption.
    system, text = import_theorem(database, "sqrt2re")
    tampered = text.replace(
        "( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]", "0 < 2 [sqrtpclii, 1, 2]"
    )

    assert system.parse(tampered).proof_lines[-1].valid is False


# ---------------------------------------------------------------------------
# Faithfulness: an import that checks must mean what it claims
# ---------------------------------------------------------------------------
def test_a_proof_that_reaches_the_wrong_statement_is_rejected():
    # A proof terminating on *some* well-formed result would otherwise import
    # cleanly and its lines would check - while establishing something other than
    # the theorem, which is still promoted under its declared statement. A green
    # import has to mean the declared statement was derived.
    bogus = SQRT2RE_FRAGMENT.replace("( c2 2re 2pos sqrtpclii ) ABCD", "( 2pos ) A")

    with pytest.raises(MetamathError, match="proof concludes"):
        import_proof(parse(bogus), "sqrt2re")


def test_a_theorem_cannot_justify_itself(database):
    # Only assertions *preceding* the theorem are promoted, so its own statement
    # is not citable while its proof is being checked.
    system, _text = import_theorem(database, "sqrt2re")

    assert "sqrt2re" not in system.promoted_theorems
    assert system.parse("( sqrt ` 2 ) e. RR [sqrt2re]").proof_lines[0].valid is False


def test_essential_hypotheses_are_given_and_stated_once():
    # A theorem with `$e` hypotheses proves *under* them: they are registered as
    # givens so the premise lines resolve. Compressed proofs re-select band-1
    # hypotheses by letter rather than Z-saving them, so `dup` pushes its premise
    # twice - it must still be stated once and cited twice.
    database = parse(HYPOTHESIS_FRAGMENT)
    system, text = import_theorem(database, "dup")

    assert text == "ph [dup.1]\n( ph /\\ ph ) [jca, 1, 1]"

    proof = system.parse(text)
    assert proof.valid is True
    assert all(line.valid for line in proof.proof_lines)


def test_variables_are_members_of_their_sort():
    # `wph $f wff ph` makes a bare `ph` a wff in its own right, and `vx $f setvar
    # x` makes `setvar` a sort with no syntax axiom behind it at all. Without both,
    # statements mentioning a variable do not parse - and a `$f`-only typecode
    # used in a binding fails deep in the builder with a bare KeyError.
    system = import_database(parse(HYPOTHESIS_FRAGMENT))
    assert system.parse("ph [dup.1]").proof_lines[0].formula_term is not None

    setvar_system = import_database(parse(BINDER_FRAGMENT))
    assert "setvar" in setvar_system.build_context.variables


def test_distinct_variable_provisos_are_sort_restricted():
    # `$d` forbids the substitutions sharing a *variable*, not any leaf: sortless
    # `disjoint(A, B)` also separates constants, so it would reject `RR = RR`,
    # which Metamath permits under `$d A B`.
    system = import_database(parse(BINDER_FRAGMENT))

    assert system.promoted_theorems["ax"].side_conditions[0].sort is not None
    assert system.parse("RR = RR [ax]").proof_lines[0].valid is True


def test_a_statement_written_in_a_variable_alone_still_has_a_logical_sort():
    # set.mm opens with two theorems - `idi` and `a1ii`, both `|- ph` - stated
    # before any syntax axiom is declared. A `$f`-declared typecode is a sort in
    # its own right (`wph $f wff ph` makes a bare `ph` a wff), so the logical
    # sort is readable from the variable leaves; reading only the syntax axioms
    # left the first two theorems of the file with no grammar to be stated in.
    database = parse(
        r"""
$c |- wff $.
$v ph $.
wph $f wff ph $.
${
  idi.1 $e |- ph $.
  idi $p |- ph $= ( ) B $.
$}
"""
    )
    system, text = import_theorem(database, "idi")

    assert text == "ph [idi.1]"
    assert system.parse(text).valid is True


def test_a_database_with_no_readable_logical_sort_is_refused():
    # With neither a syntax axiom nor a conventionally-named sort there is
    # nothing to go on, and guessing among variable-only sorts would as happily
    # pick a binder sort as the logical one.
    with pytest.raises(MetamathError, match="cannot be told"):
        build_spec(parse("$c |- setvar $. $v x $. vx $f setvar x $."))


def test_a_proof_cannot_cite_notation_declared_later():
    # Promoting only the *preceding* logical assertions does not cover syntax: a
    # syntax step never reaches the kernel (`_apply` folds it into the expression
    # it builds), so a proof using notation introduced after the theorem would
    # translate to a line that checks against a grammar built from the whole
    # database. The ordering is enforced on the proof table itself.
    forward = r"""
$c |- wff LATE EARLY $.
early $a wff EARLY $.
ax $a |- EARLY $.
thm $p |- EARLY $= ( late ax ) AB $.
late $a wff LATE $.
"""
    with pytest.raises(MetamathError, match="declared later"):
        import_proof(parse(forward), "thm")


def test_a_proof_cannot_cite_a_hypothesis_out_of_scope():
    # The same rule for hypotheses: one from a sibling `${ … $}` block is not
    # active for this theorem, even though it is declared earlier.
    out_of_scope = r"""
$c |- wff EARLY $.
$v ph $.
wph $f wff ph $.
early $a wff EARLY $.
${
  other.1 $e |- ph $.
  other $a |- EARLY $.
$}
thm $p |- EARLY $= ( other.1 ) A $.
"""
    with pytest.raises(MetamathError, match="not in scope"):
        import_proof(parse(out_of_scope), "thm")


def test_a_proved_syntax_theorem_is_not_a_production():
    # set.mm's `bj-0` is `$p wff ( ( ph -> ps ) -> ch )` - a *proved* syntactic
    # theorem, derivable from `wi`, introducing no notation. Read as a production
    # it invents a constructor overlapping the real nesting, and (having more
    # literal structure) it wins the parse: formulas then build `bj-0` nodes that
    # no schema matches. Only `$a` statements declare notation.
    database = parse(
        r"""
$c |- wff ( ) -> $.
$v ph ps ch $.
wph $f wff ph $.
wps $f wff ps $.
wch $f wff ch $.
wi $a wff ( ph -> ps ) $.
bj-0 $p wff ( ( ph -> ps ) -> ch ) $= ( wi ) ABCDD $.
"""
    )
    assert [a.label for a in database.syntax_assertions()] == ["wi"]
    assert database.assertions["bj-0"].declares_notation is False


def test_the_grammar_respects_declaration_order():
    # Rejecting forward *citations* is not enough: notation declared later must
    # not be available to *parse* an earlier theorem's lines either, or what the
    # kernel checks depends on notation that did not exist yet.
    database = parse(
        r"""
$c |- wff ( ) -> LATE $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
early $a |- ( ph -> ps ) $.
late $a wff LATE $.
"""
    )
    assert notation_names(build_spec(database)) == ["wi", "late"]
    assert notation_names(build_spec(database, before="early")) == ["wi"]


def test_variable_sorts_carry_the_variables_a_proof_may_cite():
    # A sort's leaf pattern enumerates its variables, so taking *every* declared
    # variable makes the pattern grow with the database rather than with what is
    # reachable. What a proof may cite is the test: a statement's own tokens, and
    # the variables of the hypotheses *active* where it sits - including an
    # optional floating one it never mentions, which Metamath permits a proof to
    # use as a dummy. A `$v` with no `$f` at all can be cited by nothing.
    database = parse(
        r"""
$c |- wff $.
$v ph ps dummy typeless $.
wph $f wff ph $.
wps $f wff ps $.
wdummy $f wff dummy $.
wff_a $a wff ph $.
ax $a |- ph $.
"""
    )
    # Active `$f`, mentioned by no statement: a proof may still use it as a dummy
    # variable, so the grammar must be able to read one (set.mm's `ax7` does).
    # `typeless` is declared by `$v` but typed by no `$f`, so nothing can cite it.
    assert variables_of(build_spec(database), "wff") == {"ph", "ps", "dummy"}


def test_comment_stripping_is_linear():
    # Comments were removed by re-slicing the remaining text each time, which is
    # quadratic: set.mm holds ~56k comments in 51MB and took minutes. This parses
    # in milliseconds when linear, and pathologically slowly if that regresses.
    source = "$c a $.\n" + "$( filler comment $)\n" * 5000 + "$v x $.\n"
    database = parse(source)

    assert database.constants == {"a"}
    assert database.variables == {"x"}


def test_duplicate_labels_are_rejected():
    # Labels are one flat namespace. Overwriting silently would lose the first
    # statement while leaving its label in `order`, yielding the second twice.
    with pytest.raises(MetamathError, match="Duplicate label"):
        parse("$c a $. $v x $. h1 $f a x $. h1 $f a x $.")


def test_import_errors_are_reported(database):
    with pytest.raises(MetamathError, match="No assertion labelled"):
        import_proof(database, "nosuchlabel")

    with pytest.raises(MetamathError, match="has no proof"):
        import_proof(database, "2re")


# The `A.` / `A` collision, reduced to its parts. set.mm's `wral` is
# `A. x e. A ph`, where `A.` is the universal quantifier and `A` a class
# variable; nothing else about restricted quantification matters here.
QUANTIFIER_FRAGMENT = r"""
$c |- wff class setvar A. e. $.
$v ph x A B y $.
wph $f wff ph $.
vx $f setvar x $.
vy $f setvar y $.
cA $f class A $.
cB $f class B $.
wral $a wff A. x e. A ph $.
${
  rgenw.1 $e |- ph $.
  rgenw $a |- A. x e. A ph $.
$}
$( Mentions `y` and `B`, so the variable sorts carry them - see
   test_variable_sorts_carry_only_reachable_variables. $)
other $a |- A. y e. B ph $.
"""


def test_a_variable_hidden_inside_a_constant_is_renamed():
    # A production's variables are located by scanning the template for their
    # names, so the class variable `A` is also found at offset 0, inside the
    # quantifier `A.`. The production then demands the same class in both places.
    database = parse(QUANTIFIER_FRAGMENT)
    production = next(p for p in build_spec(database).productions if p.name == "wral")

    assert production.template == "A. x e. A_0 ph"
    assert dict(production.bindings) == {"x": "setvar", "A_0": "class", "ph": "wff"}

    # The setvar `x` does not collide with anything, so it keeps its name.
    assert "x" in dict(production.bindings)


def test_a_quantification_parses_over_any_class():
    # The symptom the rename fixes: with `A` claimed at offset 0, only a
    # quantification over a class *literally named* `A` parsed, which silently
    # invalidated every restricted quantification in set.mm.
    database = parse(QUANTIFIER_FRAGMENT)
    system = build_system(build_spec(database))
    context = copy(system.context)
    wff = system.build_context.variables["wff"]

    assert wff.match("A. x e. A ph", context) is not None
    assert wff.match("A. y e. B ph", context) is not None


def test_a_variable_not_hidden_in_a_constant_keeps_its_name():
    # The rename is driven by a real collision (more substring occurrences than
    # token occurrences), so an ordinary production is left exactly as written.
    database = parse(
        r"""
$c |- wff ( ) -> $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
"""
    )
    production = next(p for p in build_spec(database).productions if p.name == "wi")

    assert production.template == "( ph -> ps )"
    assert dict(production.bindings) == {"ph": "wff", "ps": "wff"}


# A `$d` over two *class* variables, in a database shaped like set.mm: `class`
# has a syntax axiom (so it is not a binder sort) and `setvar` has none (so it
# is). `C` is mentioned so the class leaf carries it.
CLASS_DISTINCT_FRAGMENT = r"""
$c |- wff class setvar = RR A. e. $.
$v x ph A B C $.
vx $f setvar x $.
wph $f wff ph $.
cA $f class A $.
cB $f class B $.
cC $f class C $.
wceq $a wff A = B $.
wal $a wff A. x ph $.
cr $a class RR $.
mentionC $a |- C = RR $.
${
  $d A B $.
  ax $a |- A = B $.
$}
"""


def test_a_distinct_variable_proviso_covers_every_variable_sort():
    # `$d` forbids the substitutions sharing a *variable* of any typecode. Keying
    # the proviso to the single binder sort dropped every `$d` over class or wff
    # variables, since none of their leaves are `setvar` - so a $d over two class
    # variables constrained nothing at all.
    system = import_database(parse(CLASS_DISTINCT_FRAGMENT))

    # Both substituted with the same *class variable*: Metamath rejects.
    assert system.parse("C = C [ax]").valid is False

    # Distinct variables, and a shared *constant*, are both fine: `$d` separates
    # variables, not every leaf.
    assert system.parse("A = B [ax]").valid is True
    assert system.parse("RR = RR [ax]").valid is True


def test_the_proviso_is_emitted_for_each_variable_sort():
    database = parse(CLASS_DISTINCT_FRAGMENT)
    system = import_database(database)
    provisos = _distinct_provisos(database.assertions["ax"], database, system)

    assert set(provisos) == {
        "disjoint(A, B, wff_var)",
        "disjoint(A, B, setvar_var)",
        "disjoint(A, B, class_var)",
    }


# A proof using a *dummy* variable: `t` is typed by a floating hypothesis active
# where `ax7` sits, but mentioned by neither its statement nor its mandatory
# hypotheses. This is the shape of set.mm's own `ax7`.
DUMMY_VARIABLE_FRAGMENT = r"""
$c |- wff setvar = -> $.
$v x y t $.
vx $f setvar x $.
vy $f setvar y $.
vt $f setvar t $.
wceq $a wff x = y $.
wi $a wff ( x = y -> x = y ) $.
${
  step.1 $e |- ( x = t -> x = y ) $.
  step $a |- ( x = y -> x = y ) $.
$}
"""


def test_a_dummy_variable_is_in_the_grammar_of_a_theorem_that_may_cite_it():
    # `t` is mentioned only by `step`'s own essential hypothesis, so it is
    # reachable; the point of the test is that a variable typed by an active
    # floating hypothesis reaches the grammar at all.
    database = parse(DUMMY_VARIABLE_FRAGMENT)
    assert "t" in variables_of(build_spec(database), "setvar")


# set.mm names its half-open intervals `[,)` and `(,]` — constants that *contain*
# a bracket without being one. `( 0 [,) +oo )` has two openings and three
# closings by character, so counting them all reads it as unbalanced.
INTERVAL_FRAGMENT = r"""
$c |- wff class ( ) [,) (,] +oo C_ RR 0 $.
$v A B F $.
cA $f class A $.
cB $f class B $.
cF $f class F $.
wss $a wff A C_ B $.
$( `[,)` is a class *constant* used as the operator of `( A F B )` - which is
   exactly how set.mm spells a half-open interval. $)
cico $a class [,) $.
cioc $a class (,] $.
co $a class ( A F B ) $.
cpnf $a class +oo $.
cr $a class RR $.
cc0 $a class 0 $.
ax $a |- ( 0 [,) +oo ) C_ RR $.
"""


def test_a_constant_that_spells_a_bracket_is_not_one():
    # The interval token's `)` is part of its name. Counting it as a delimiter
    # made every statement mentioning one fail bracket parity before it reached a
    # parse, which is most of what an import of set.mm rejected.
    system = import_database(parse(INTERVAL_FRAGMENT))
    formula = system.build_context.variables["wff"]

    assert formula.check_brackets("( 0 [,) +oo ) C_ RR") is True
    assert formula.check_brackets("( 0 (,] +oo ) C_ RR") is True

    # The builder found them from the grammar, not from a hard-coded list.
    assert set(formula.bracket_opaque) == {"[,)", "(,]"}


def test_genuinely_unbalanced_brackets_are_still_refused():
    # The opaque tokens must not turn the check off: a real imbalance still fails.
    system = import_database(parse(INTERVAL_FRAGMENT))
    formula = system.build_context.variables["wff"]

    assert formula.check_brackets("( 0 [,) +oo C_ RR") is False
    assert formula.check_brackets("0 [,) +oo ) C_ RR") is False


def test_a_grammar_without_such_constants_declares_none():
    # Nothing is opaque unless a declared constant actually spells a delimiter,
    # so an ordinary system pays only a truthiness check.
    system = import_database(parse(HYPOTHESIS_FRAGMENT))
    assert system.build_context.variables["wff"].bracket_opaque == ()


# set.mm spells its inner product `.,` — a metavariable whose *name* contains the
# character a proviso uses to separate arguments.
COMMA_VARIABLE_FRAGMENT = r"""
$c |- wff class setvar = A. e. $.
$v x ., A $.
vx $f setvar x $.
cip $f class ., $.
cA $f class A $.
wceq $a wff A = A $.
wal $a wff A. x A = A $.
${
  $d ., x $.
  $( `.,` must be *mentioned* to be a metavariable of `ax` - a `$d` over
     something the statement does not bind constrains nothing. $)
  ax.1 $e |- ., = A $.
  ax $a |- A. x A = A $.
$}
"""


def test_a_metavariable_spelt_with_a_comma_can_still_carry_a_proviso():
    # `disjoint(left, right, sort)` is read by splitting on top-level commas, so
    # `$d ., x` came out as `disjoint(.,, x, setvar)` - four arguments where three
    # were meant. The proviso parser refused it, the theorem never promoted, and
    # every theorem citing it failed too.
    database = parse(COMMA_VARIABLE_FRAGMENT)
    system = build_system(build_spec(database))

    rename = _proviso_safe_names(database.assertions["ax"])
    assert rename == {".,": "._0"}

    provisos = _distinct_provisos(database.assertions["ax"], database, system, rename)
    assert all("._0" in p for p in provisos)
    assert not any(".,," in p for p in provisos)

    # And the theorem promotes, which it could not before.
    system = import_database(database)
    assert "ax" in system.promoted_theorems


def test_a_metavariable_without_a_comma_is_left_alone():
    # The rename is driven by a real collision, so ordinary names are untouched.
    database = parse(BINDER_FRAGMENT)
    assert _proviso_safe_names(database.assertions["ax"]) == {}


def test_one_opaque_token_may_contain_another():
    # set.mm declares both `O(1)` and `<_O(1)`. The spans are unioned rather than
    # matched greedily, so neither ordering nor nesting can leave a delimiter
    # inside the longer token counted.
    database = parse(
        r"""
$c |- wff class ( ) O(1) <_O(1) e. $.
$v A B $.
cA $f class A $.
cB $f class B $.
wcel $a wff A e. B $.
cbig $a class O(1) $.
cbigle $a class <_O(1) $.
cop $a class ( A B ) $.
ax $a |- O(1) e. <_O(1) $.
"""
    )
    formula = build_system(build_spec(database)).build_context.variables["wff"]

    assert set(formula.bracket_opaque) == {"O(1)", "<_O(1)"}
    assert formula.check_brackets("O(1) e. <_O(1)") is True
    assert formula.check_brackets("( O(1) e. <_O(1) )") is True
    # A real imbalance around them is still caught.
    assert formula.check_brackets("( O(1) e. <_O(1)") is False


def test_a_replacement_name_avoids_tokens_the_premises_use():
    # `._0` is a declared *constant* the premise spells. Renaming `.,` onto it
    # would leave that constant's spelling alone while registering it as the
    # metavariable, so the premise would parse as depending on the metavariable
    # and the theorem would accept premises Metamath does not.
    database = parse(
        r"""
$c |- wff class setvar = ._0 A. e. $.
$v x ., A $.
vx $f setvar x $.
cip $f class ., $.
cA $f class A $.
wceq $a wff A = A $.
wal $a wff A. x A = A $.
cconst $a class ._0 $.
${
  $d ., x $.
  ax.1 $e |- ., = ._0 $.
  ax $a |- A. x A = A $.
$}
"""
    )
    rename = _proviso_safe_names(database.assertions["ax"])

    assert rename[".,"] != "._0"
    premise_tokens = {
        token for h in database.assertions["ax"].mandatory for token in h.tokens
    }
    assert rename[".,"] not in premise_tokens


def test_opaque_tokens_apply_to_multi_character_delimiters():
    # A system whose delimiters are longer than a character takes the general
    # bracket scan rather than the single-character fast path. Both must step
    # over a constant that merely spells a delimiter.
    from website.logical.matching import StringPattern

    pattern = StringPattern(name="p", pattern="a")
    pattern.respect_brackets = {"<<": ">>"}
    pattern.bracket_opaque = ("x>>",)

    assert pattern.check_brackets("<< x>> >>") is True
    assert pattern.check_brackets("<< a >>") is True
    # Still catches a real imbalance around the opaque token.
    assert pattern.check_brackets("<< x>>") is False


def test_a_variable_is_a_leaf_of_its_own_sub_sort_inside_its_typecode():
    # A `$v` variable is declared as its own atom leaf of a `<typecode>_var`
    # sub-sort, and that sub-sort is included into the typecode. The sub-sort is
    # what a `$d` proviso restricts to (see _distinct_provisos): without it there
    # would be no name for "the leaves that are variables" as distinct from the
    # typecode's constants.
    database = parse(SQRT2RE_FRAGMENT)
    spec = build_spec(database)

    assert variables_of(spec, "class") == {"A", "B", "F", "R"}
    # One shapeless production, naming the sub-sort: that is what includes it.
    inclusion = [p for p in spec.productions if p.name == "class_var"]
    assert len(inclusion) == 1
    assert inclusion[0].sort == "class"
    assert inclusion[0].template is inclusion[0].atom_value is inclusion[0].regex is None

    # A variable reads as its typecode, and the sub-sort admits it while excluding
    # a constant of the same typecode.
    system = build_system(spec)
    context = system.build_context
    assert context.variables["class_var"].match("A", context) is not None
    assert context.variables["class_var"].match("2", context) is None
    assert context.variables["class"].match("A", context) is not None


def test_the_variable_schedule_matches_a_per_theorem_build():
    # The walk declares every variable leaf to the horizon and admits each as it
    # is reached, rather than rebuilding the grammar per theorem. That is only
    # worth anything if the leaves live at a theorem are the leaves
    # `build_spec(before=...)` would have declared for it. They used to be seeded
    # at whole-database scope, which let a theorem parse against a name `set.mm`
    # declares tens of thousands of statements later.
    database = parse(LATE_VARIABLE_FRAGMENT)
    schedule = grammar_schedule(database)

    live: set[str] = set()
    checked = []
    for index, label in enumerate(database.order):
        live.update(
            name for sort, name in schedule.entries.get(index, ())
            if sort.endswith("_var")
        )
        assertion = database.assertions[label]
        if not (assertion.is_logical and assertion.proof):
            continue

        scoped = build_spec(database, before=label)
        expected = {p.name for p in scoped.productions if p.sort.endswith("_var")}
        assert live == expected
        checked.append(label)

    assert checked == ["dup", "tri"]
    # The property with teeth: `ch` is declared in `tri`'s own scope, so it is out
    # of scope at `dup` and only the ordering can tell the two apart.
    assert variables_of(build_spec(database, before="dup"), "wff") == {"ph", "ps"}
    assert variables_of(build_spec(database, before="tri"), "wff") == {"ph", "ps", "ch"}


def test_the_walk_scopes_a_late_variable_out_of_an_earlier_theorem():
    # End to end through `corpus.walk`: a variable in scope only for the last
    # theorem must not be readable at the first, and both proofs must still check.
    database = parse(LATE_VARIABLE_FRAGMENT)
    checked = list(walk(database))

    assert [c.label for c in checked] == ["dup", "tri"]
    assert all(c.verified for c in checked), [c.error for c in checked]


def test_the_walk_agrees_with_building_each_theorem_on_its_own():
    # The cheap path and the strict path must reach the same verdict.
    database = parse(SQRT2RE_FRAGMENT)
    for checked in walk(database):
        alone, alone_text = import_theorem(database, checked.label)
        assert checked.source == alone_text
        assert checked.verified is alone.parse(alone_text).valid is True


def test_an_imported_grammar_survives_the_database_round_trip():
    # A variable leaf is an atom, and the `<typecode>_var` sub-sort is included
    # into its typecode by a production carrying no shape at all - neither
    # template, regex, nor atom. Persistence had never seen either, and an import
    # that cannot be stored has to be redone from source on every run.
    #
    # Through a real session, because the failure this pins is an INSERT: symbols
    # share one namespace under `uq_symbols_system_name`, and the inclusion names
    # the sub-sort it includes. In memory a second row of that name merely rebinds
    # the first in `spec_to_system`'s dict and nothing looks wrong.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import Base, spec_to_system, system_to_spec
    from app.db.models import FormalSystem as FormalSystemRow

    database = parse(SQRT2RE_FRAGMENT)
    spec = build_spec(database, name="mm")

    def shape(candidate):
        return sorted(
            (p.sort, p.name, p.template, p.regex, p.atom_value, p.atom_base,
             p.denotes_constant)
            for p in candidate.productions
        )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(spec_to_system(spec))
        session.commit()
        rebuilt = system_to_spec(session.query(FormalSystemRow).one())

    assert shape(rebuilt) == shape(spec)

    # And the grammar read back out of the database still reads a proof.
    system = build_system(rebuilt)
    promote_assertions(database, system, before="sqrt2re")
    _givens(database.assertions["sqrt2re"], system)
    assert system.parse(import_proof(database, "sqrt2re")).valid is True


def test_a_metavariable_outranks_a_production_spelt_the_same_way():
    # Metamath keeps labels and variable names in separate namespaces, so a syntax
    # axiom may be labelled `ph` while `ph` is also a `$v`. Edifyce resolves
    # productions out of one namespace, so a premise stated as the bare
    # metavariable `ph` resolved to that production and matched only what it
    # matches - rejecting a proof that instantiates `ph` at anything else.
    database = parse(
        r"""
$c |- wff ( ) -> TOP $.
$v ph ps $.
wph $f wff ph $.
wps $f wff ps $.
ph $a wff TOP $.
wi $a wff ( ph -> ps ) $.
${
  jca.1 $e |- ph $.
  jca $a |- ( ph -> ph ) $.
$}
${
  dup.1 $e |- ( TOP -> TOP ) $.
  dup $p |- ( ( TOP -> TOP ) -> ( TOP -> TOP ) ) $= ( ph wi jca ) BBCAD $.
$}
"""
    )
    system, text = import_theorem(database, "dup")
    assert system.parse(text).valid is True


def test_a_sub_sort_joins_its_typecode_at_its_earliest_member():
    # `_declared_variables` yields `$f` declaration order, which stops matching
    # first-mention order the moment a `$f` is scoped. Scheduling the `wff_var`
    # sub-sort at its first *declared* member's position leaves `ph`'s leaf live
    # while the sub-sort is not yet a branch of `wff`, so `dup` cannot read its own
    # statement - a proof `import_theorem` accepts, failed by the walk alone.
    database = parse(DECLARED_BEFORE_MENTIONED_FRAGMENT)

    for checked in walk(database):
        alone, alone_text = import_theorem(database, checked.label)
        assert checked.verified is alone.parse(alone_text).valid is True


# `x` is typed `class` inside one block and `wff` inside a later one — legal
# Metamath, since a `$f` is scoped. Both typings must not be live at once.
RETYPED_VARIABLE_FRAGMENT = r"""
$c |- wff class ( ) -> e. $.
$v ph x $.
wph $f wff ph $.
${
  vx1 $f class x $.
  cls.1 $e |- ( x e. x ) $.
  cls $a |- ( x e. x ) $.
$}
wi $a wff ( ph -> ph ) $.
we $a wff ( x e. x ) $.
${
  vx2 $f wff x $.
  wf.1 $e |- x $.
  wf $a |- x $.
$}
"""


def test_a_variable_is_typed_only_where_its_floating_hypothesis_is_active():
    # A `$f` is scoped, so availability is a property of the (typecode, variable)
    # *pair*, not of the token. Reading every `$f` in the database and filtering by
    # mention alone gave `x` both typings from its earliest use — admitting the
    # later one before its `$f` exists, and leaving both live afterwards, which can
    # make an unambiguous grammar ambiguous.
    database = parse(RETYPED_VARIABLE_FRAGMENT)

    assert {k: database.order[v] for k, v in database.typed_from().items()} == {
        ("wff", "ph"): "cls",
        ("class", "x"): "cls",
        ("wff", "x"): "wf",
    }

    # At `cls` only the `class` typing is in scope; the `wff` one arrives with its
    # own block.
    assert variables_of(build_spec(database, before="cls"), "class") == {"x"}
    assert variables_of(build_spec(database, before="cls"), "wff") == {"ph"}
    assert variables_of(build_spec(database, before="wf"), "wff") == {"ph", "x"}

    # And the walk's schedule agrees with the per-theorem build, as ever.
    schedule = grammar_schedule(database)
    live: set[str] = set()
    for index, label in enumerate(database.order):
        live.update(
            name for sort, name in schedule.entries.get(index, ())
            if sort.endswith("_var")
        )
        if database.assertions[label].is_logical:
            scoped = build_spec(database, before=label)
            expected = {p.name for p in scoped.productions if p.sort.endswith("_var")}
            assert live == expected, label


# A sort declared *after* a theorem: `class` arrives with `cset`, which follows
# `id`. A walk stopping at `id` builds no `class` sort, so a schedule covering the
# whole database would name one the system never built.
SORT_AFTER_THEOREM_FRAGMENT = r"""
$c |- wff class ( ) -> SET $.
$v ph ps A $.
wph $f wff ph $.
wps $f wff ps $.
wi $a wff ( ph -> ps ) $.
${
  id.1 $e |- ph $.
  id $p |- ph $= ( ) B $.
$}
cA $f class A $.
cset $a class SET $.
${
  late.1 $e |- ph $.
  late $p |- ph $= ( ) B $.
$}
"""


def test_the_schedule_is_bounded_by_the_walk_horizon():
    # `grammar_schedule` has to be bounded the same way `build_spec` is, and by the
    # *same* label. Unbounded, it scheduled a sort declared past the horizon —
    # which `_reset_sorts` then looked up in a system that never built it, so a
    # `limit` short of the end aborted the whole walk on a KeyError instead of
    # checking the prefix it was asked for.
    database = parse(SORT_AFTER_THEOREM_FRAGMENT)

    assert [(c.label, c.verified) for c in walk(database, limit=1)] == [("id", True)]
    assert [(c.label, c.verified) for c in walk(database)] == [
        ("id", True), ("late", True),
    ]

    # Bounded at `id`, the schedule names only sorts that system has.
    assert "class" not in grammar_schedule(database, before="id").sorts
    assert "class" in grammar_schedule(database).sorts
