"""The fingerprint index, and the one property it must never break: recall.

A fingerprint is a filter for goal-directed retrieval (Phase 1 of
docs/search-and-embeddings-roadmap.md). The engine half — turning a term into its
feature vector and comparing two of them — is here; the storage and the wiring
into `conclusion_candidates` are the database's.

What is pinned:

* the compatibility table, feature by feature;
* what `feature_at` reads at a position — a symbol, or a marker for why none is
  there;
* **the contract**: whenever the kernel can match a stored schema to a goal, the
  fingerprints are compatible. The unifier is the oracle, run over a cross-product
  of real schema and ground terms, so a fingerprint that ever pruned a genuine
  match would fail here. Precision — how much it prunes — is reported alongside,
  because a filter that keeps everything is sound and useless.
"""

from copy import copy

import pytest

pytest.importorskip("regex")

from website.logical.declarative import SystemSpec, build_system
from website.logical.fingerprint import (
    ABSENT,
    BELOW_VAR,
    VARIABLE,
    compatible,
    feature_at,
    features_compatible,
    fingerprint,
)
from website.logical.formal_system.rules import statement_term
from website.logical.kernel import from_match, match
from tests.spec_helpers import brackets, regex_prod, rule, statement_line, template_prod


def _pqr():
    return [("p", "formula"), ("q", "formula"), ("r", "formula")]


# Implication and conjunction over atoms, with rules whose schemas reach two and
# three levels deep — enough that a position below the root distinguishes terms a
# head-symbol filter cannot.
SYSTEM = SystemSpec(
    name="Prop",
    brackets=brackets(),
    productions=[
        regex_prod("formula", "atom", "[a-z][a-z0-9]*"),
        template_prod("formula", "implication", "(p -> q)", _pqr()[:2]),
        template_prod("formula", "conjunction", "(p ∧ q)", _pqr()[:2]),
    ],
    lines=[statement_line()],
    rules=[
        rule("MP", "modus_ponens", ["p", "(p -> q)"], "q", _pqr()[:2]),
        rule("CONJ", "conjunction_intro", ["p", "q"], "(p ∧ q)", _pqr()[:2]),
        rule("AX1", "add", [], "(p -> (q -> p))", _pqr()[:2]),
        rule("AX2", "distribute", [],
             "((p -> (q -> r)) -> ((p -> q) -> (p -> r)))", _pqr()),
        rule("NEST", "nest", [], "((p -> q) -> r)", _pqr()),
    ],
)


@pytest.fixture(scope="module")
def context():
    system = build_system(SYSTEM)
    ctx = copy(system.context)
    ctx.variables.update(system.build_context.variables)
    return system, ctx


def _rule(system, label):
    (found,) = [r for r in system.inference_rules if r.label == label]
    return found


def ground(context, text):
    _system, ctx = context
    return from_match(ctx.variables["formula"].match(text, ctx))


# ---------------------------------------------------------------------------
# The compatibility table
# ---------------------------------------------------------------------------


def test_a_symbol_is_compatible_only_with_itself_among_symbols():
    assert features_compatible("S\x1eimplication", "S\x1eimplication")
    assert not features_compatible("S\x1eimplication", "S\x1econjunction")


def test_a_variable_binds_to_anything_present_but_not_to_absence():
    for other in ("S\x1eimplication", "L\x1eatom\x1ea", VARIABLE, BELOW_VAR):
        assert features_compatible(VARIABLE, other)
        assert features_compatible(other, VARIABLE)
    # …except ABSENT: there is no subterm for the variable to bind.
    assert not features_compatible(VARIABLE, ABSENT)
    assert not features_compatible(ABSENT, VARIABLE)


def test_below_a_variable_is_compatible_with_everything():
    for other in ("S\x1eimplication", VARIABLE, ABSENT, BELOW_VAR):
        assert features_compatible(BELOW_VAR, other)
        assert features_compatible(other, BELOW_VAR)


def test_absent_clashes_with_any_present_subterm():
    assert features_compatible(ABSENT, ABSENT)
    assert features_compatible(ABSENT, BELOW_VAR)
    assert not features_compatible(ABSENT, "S\x1eimplication")
    assert not features_compatible(ABSENT, VARIABLE)


def test_the_markers_are_schulz_letters():
    # A stored fingerprint is read against the paper, so the letters must be his:
    # A variable-here, B below-variable, N nonexistent.
    assert (VARIABLE, BELOW_VAR, ABSENT) == ("A", "B", "N")


def test_comparing_fingerprints_over_different_positions_is_refused(context):
    # Width equality is not enough: two position sets of the same width describe
    # different paths, so comparing their vectors slot by slot is meaningless.
    # `((), (0,))` and `((), (0, 0))` are both width two — the fingerprint carries
    # the position-set identity so the mismatch is refused, not misread. (Codex,
    # on #198.)
    term = ground(context, "(a -> b)")
    here = fingerprint(term, positions=[(), (0,)])
    deeper = fingerprint(term, positions=[(), (0, 0)])
    assert len(here.features) == len(deeper.features)  # same width…
    assert here.key != deeper.key                      # …different positions
    with pytest.raises(ValueError, match="position-set mismatch"):
        compatible(here, deeper)


# ---------------------------------------------------------------------------
# What feature_at reads
# ---------------------------------------------------------------------------


def test_the_root_position_is_the_head_symbol(context):
    # Position () is exactly the head-symbol filter the fingerprint generalises.
    imp = ground(context, "(a -> b)")
    con = ground(context, "(a ∧ b)")
    assert feature_at(imp, ()) != feature_at(con, ())
    assert feature_at(imp, (0,)) == feature_at(ground(context, "(a -> c)"), (0,))


def test_a_ground_leaf_makes_the_positions_below_it_absent(context):
    atom = ground(context, "a")
    assert feature_at(atom, ()) != ABSENT  # the leaf itself is a symbol
    assert feature_at(atom, (0,)) == ABSENT
    assert feature_at(atom, (0, 0)) == ABSENT


def test_two_atoms_of_one_production_differ_by_their_token(context):
    # `a` and `b` share a constructor but not a literal, so they are distinct
    # symbols — the fingerprint must tell them apart or it would never prune a
    # wrong constant.
    assert feature_at(ground(context, "a"), ()) != feature_at(ground(context, "b"), ())


def test_a_schema_variable_reads_as_VARIABLE_and_shrouds_below(context):
    system, _ctx = context
    # `q` alone is a bare metavariable; `(p -> q)` has variables at its two slots.
    assert feature_at(statement_term(_rule(system, "MP").deduction), ()) == VARIABLE
    schema = statement_term(_rule(system, "MP").antecedents[1])  # (p -> q)
    assert feature_at(schema, ()) != VARIABLE       # the implication node
    assert feature_at(schema, (0,)) == VARIABLE     # the variable p
    assert feature_at(schema, (0, 0)) == BELOW_VAR  # below that variable


# ---------------------------------------------------------------------------
# The recall contract — the whole point
# ---------------------------------------------------------------------------


def _schemas(system):
    return {
        "p": statement_term(_rule(system, "MP").antecedents[0]),
        "(p -> q)": statement_term(_rule(system, "MP").antecedents[1]),
        "(p ∧ q)": statement_term(_rule(system, "CONJ").deduction),
        "(p -> (q -> p))": statement_term(_rule(system, "AX1").deduction),
        "ax2": statement_term(_rule(system, "AX2").deduction),
        "((p -> q) -> r)": statement_term(_rule(system, "NEST").deduction),
    }


_SUBJECTS = [
    "a",
    "(a -> b)",
    "(a ∧ b)",
    "(a -> a)",
    "(a -> (b -> a))",
    "(a -> (b -> c))",
    "((a -> b) -> c)",
    "((a ∧ b) -> c)",
    "((a -> (b -> c)) -> ((a -> b) -> (a -> c)))",
]


def test_a_matchable_pair_is_never_pruned(context):
    # The contract: if the kernel can match the schema to the goal, the
    # fingerprints agree. A violation here is a citation retrieval would silently
    # never offer — the one failure mode a filter must not have.
    system, ctx = context
    schemas = _schemas(system)
    subjects = {text: ground(context, text) for text in _SUBJECTS}

    matched = kept = 0
    total = len(schemas) * len(subjects)
    for schema in schemas.values():
        sfp = fingerprint(schema)
        for subject in subjects.values():
            is_match = match(schema, subject, ctx) is not None
            is_compatible = compatible(fingerprint(subject), sfp)
            if is_match:
                matched += 1
                assert is_compatible, "a real match was pruned — recall is broken"
            if is_compatible:
                kept += 1

    # The filter has to actually filter, or it is sound and pointless: most of the
    # cross-product neither matches nor survives.
    assert matched >= 6          # there are real matches to protect
    assert kept < total          # and real prunes happening
    assert kept < total * 0.6    # the majority is rejected before the unifier


def _random_formula(rng, depth):
    # A ground formula string in the grammar: an atom, or a binary connective of
    # two smaller ones. Depth-bounded so generation terminates.
    if depth <= 0 or rng.random() < 0.35:
        return rng.choice(["a", "b", "c", "d", "x0", "y1"])
    op = rng.choice(["->", "∧"])
    return f"({_random_formula(rng, depth - 1)} {op} {_random_formula(rng, depth - 1)})"


def test_recall_holds_over_random_goals(context):
    # The contract again, this time against many goals rather than a curated few:
    # the fixed schemas are a stand-in for a library, the random ground formulas
    # for the goals a caller throws at it. Seeded, so a failure reproduces.
    import random  # noqa: PLC0415 — test-local, and only to drive the fuzz

    system, ctx = context
    schemas = [(term, fingerprint(term)) for term in _schemas(system).values()]
    rng = random.Random(1729)

    checked = pruned = 0
    for _ in range(300):
        subject = ground(context, _random_formula(rng, 3))
        sfp = fingerprint(subject)
        for schema, schema_fp in schemas:
            # `compatible` is symmetric; the schema is what carries the variables.
            if match(schema, subject, ctx) is not None:
                assert compatible(sfp, schema_fp), "a real match was pruned"
                checked += 1
            elif not compatible(sfp, schema_fp):
                pruned += 1

    assert checked > 0   # real matches happened and were protected
    assert pruned > 0    # and the filter earned its keep


def test_the_fingerprint_prunes_where_the_head_symbol_cannot(context):
    # Both are implications, so a head-symbol filter (position () alone) keeps the
    # pair; a position below the root rejects it, and the kernel agrees there is no
    # match. This is the sequent-calculus case from the retrieval PR — the head is
    # uninformative, the structure below it is not.
    system, ctx = context
    schema = _schemas(system)["((p -> q) -> r)"]
    subject = ground(context, "((a ∧ b) -> c)")

    assert feature_at(schema, ()) == feature_at(subject, ())        # heads agree
    assert not compatible(fingerprint(subject), fingerprint(schema))  # but the whole prints do not
    assert match(schema, subject, ctx) is None                     # and there is no match
