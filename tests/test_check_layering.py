"""What `scripts/check_layering.py` will and will not call a confirmation.

The script itself runs against a real `.mm` and is not part of the suite — that
is the point of it (D4, docs/system-relationships-roadmap.md §8). But its
*comparison* is a pure function over two summaries and an expected partition, and
what it refuses to accept is worth pinning, because the failure mode of a
checking harness is passing vacuously and nothing about a green run says which
kind of green it was.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from scripts.check_layering import Run, Unreachable, compare

PC = "Propositional calculus"
FOL = "First-order logic"
TWO_LAYERS = [(PC, 1), (FOL, 1)]
BOTH = {"pc-thm": ("$= ( ax-1 ) ABC", True), "fol-thm": ("$= ( ax-4 ) ABC", True)}
# Where the file says each of them belongs, which is what `expected_owners`
# derives from the boundaries rather than reading back from the run.
EXPECTED = {"pc-thm": PC, "fol-thm": FOL}


def run(
    *,
    spine: list[tuple[str, int]],
    proofs: dict[str, tuple[str, bool]] | None = None,
    library: dict[str, bool] | None = None,
    owners: dict[str, str] | None = None,
    **overrides: object,
) -> Run:
    """A summary with everything agreeing, so a test names only what it changes."""
    stored = BOTH if proofs is None else proofs
    fields: dict[str, object] = {
        "checked": len(stored),
        "verified": len(stored),
        "rejected": 0,
        "failed": 0,
        "lines": 3,
        "formulas": 3,
        "described": 2,
        "sections": 4,
        "notation": 0,
        "theorems": 2,
        "primitives": 1,
        "theorems_failed": 0,
        "proofs": stored,
        "library": {"ax-1": True} if library is None else library,
        "folders": ["Pre-logic"],
        "described_labels": {"ax-1", "pc-thm"},
        "spine": spine,
        # Default to filing everything where the file says it goes, so a test
        # that is not about the partition does not have to restate it.
        "owners": {label: EXPECTED[label] for label in stored} if owners is None
        else owners,
    }
    return Run(**{**fields, **overrides})  # type: ignore[arg-type]


def flat_run(**overrides: object) -> Run:
    """The unlayered side: one system, so everything is filed under its name."""
    stored = overrides.pop("proofs", BOTH)
    return run(
        spine=[("Metamath", len(stored))],
        proofs=stored,  # type: ignore[arg-type]
        owners=dict.fromkeys(stored, "Metamath"),
        **overrides,
    )


def reasons(*args: object) -> list[str]:
    return [difference.what for difference in compare(*args).differences]  # type: ignore[arg-type]


def test_two_agreeing_runs_over_a_real_spine_are_a_confirmation() -> None:
    assert reasons(flat_run(), run(spine=TWO_LAYERS), EXPECTED) == []


def test_a_plan_covering_these_theorems_with_one_layer_is_refused() -> None:
    # **From review.** A plan whose section titles the file does not open, or a
    # `--limit` short of the second boundary, gives one layer — and then every
    # equality the script checks holds because the two runs *are* the same run.
    # Reproduced against the repo's own fixture: at `--limit 1` the script
    # printed "Layering changed nothing" and exited 0 while comparing nothing.
    #
    # Asked of the *expected* partition rather than the realised one, so a run
    # that wrongly collapsed is caught by the next test instead of excused here.
    one = {"pc-thm": ("$= ( ax-1 ) ABC", True)}

    assert reasons(
        flat_run(proofs=one),
        run(spine=[(PC, 1)], proofs=one, owners={"pc-thm": PC}),
        {"pc-thm": PC},
    ) == ["nothing here is a comparison"]


def test_a_layer_whose_proofs_went_somewhere_else_is_caught() -> None:
    # **From review, and the gap the first cut left.** Requiring only that *some*
    # two layers carry proofs passes a run that filed every ZF theorem under
    # first-order logic: two non-empty shares summing correctly is all such a
    # check ever asks. Every other comparison is blind to which system a row
    # landed in, so the partition has to be compared element by element.
    spined = run(
        spine=[(PC, 2), (FOL, 0)],
        owners={"pc-thm": PC, "fol-thm": PC},
    )

    differences = compare(flat_run(), spined, EXPECTED).differences
    assert [d.what for d in differences] == ["proofs filed in the wrong layer"]
    assert "fol-thm" in differences[0].detail


def test_layers_that_do_not_add_up_are_refused() -> None:
    # The report's own breakdown has to describe the run it came from, even when
    # every proof is filed correctly.
    spined = run(spine=[(PC, 1), (FOL, 5)])

    assert reasons(flat_run(), spined, EXPECTED) == ["per-layer proof counts"]


def test_a_flat_run_that_is_not_flat_is_refused() -> None:
    # If it ever spread across systems, every "same either way" result would be
    # comparing the wrong thing.
    flat = run(spine=[("Metamath", 2)], owners={"pc-thm": "Metamath", "fol-thm": FOL})

    assert "the flat run is not flat" in reasons(flat, run(spine=TWO_LAYERS), EXPECTED)


def test_a_rewritten_proof_source_is_caught() -> None:
    # The headline: a citation is stored as a bare label and resolves through the
    # spine, so splitting a corpus must not rewrite one. Same labels, same
    # verdicts, same counts — and a different body.
    spined = run(
        spine=TWO_LAYERS,
        proofs={**BOTH, "fol-thm": ("$= ( ax-4 ) ABD", True)},
    )

    differences = compare(flat_run(), spined, EXPECTED).differences
    assert [d.what for d in differences] == ["proof sources or verdicts"]
    assert "fol-thm" in differences[0].detail


STRANDED = Unreachable(
    proof="zf-thm", filed_in=FOL, label="ax-ext", declared_in=("ZF set theory",)
)


def test_a_stranded_citation_is_reported_with_where_it_lives() -> None:
    # The point of the guard is that the reader can act on it, so the detail has
    # to name the proof, the layer it was filed in, and where the label actually
    # is — a count alone says a plan is wrong without saying which part of it.
    spined = run(spine=TWO_LAYERS, unreachable=(STRANDED,))

    differences = compare(flat_run(), spined, EXPECTED).differences
    assert [d.what for d in differences] == [
        "a citation the citing proof's chain cannot reach"
    ]
    assert differences[0].detail == (
        "zf-thm (in 'First-order logic') cites 'ax-ext', "
        "declared in 'ZF set theory'"
    )


def test_the_flat_run_is_reported_as_itself_and_not_as_a_disagreement() -> None:
    # **From review.** This was `require("…", (), flat.unreachable)`, whose
    # detail reads "flat=() spined=(…)" — so a defect in the *flat* run printed
    # under the spined run's heading and sent the reader to the wrong import.
    flat = flat_run(unreachable=(STRANDED,))

    differences = compare(flat, run(spine=TWO_LAYERS), EXPECTED).differences
    assert [d.what for d in differences] == [
        "a citation out of reach in the *flat* run"
    ]
    assert "spined=" not in differences[0].detail


def test_a_promotion_refused_under_a_spine_is_caught_twice() -> None:
    # The actual D4 finding, in the shape the script sees it: 354 labels promoted
    # flat and not spined, with the checked/verified/rejected counters identical
    # because `theorems_failed` is counted apart from `failed`. The label set is
    # what caught it; the counter comparison was added afterwards so that the
    # next one trips both, and this asserts that it does.
    flat = flat_run(library={"ax-1": True, "ax-5": True})
    spined = run(
        spine=TWO_LAYERS,
        library={"ax-1": True},
        theorems=1,
        theorems_failed=1,
    )

    assert set(reasons(flat, spined, EXPECTED)) == {
        "theorems", "theorems failed", "library labels"
    }
