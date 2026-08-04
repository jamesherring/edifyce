"""What `scripts/check_layering.py` will and will not call a confirmation.

The script itself runs against a real `.mm` and is not part of the suite — that
is the point of it (D4, docs/system-relationships-roadmap.md §8). But its
*comparison* is a pure function over two summaries, and what it refuses to accept
is worth pinning, because the failure mode of a checking harness is passing
vacuously and nothing about a green run says which kind of green it was.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from scripts.check_layering import Run, compare


def run(
    *,
    spine: list[tuple[str, int]],
    proofs: dict[str, tuple[str, bool]] | None = None,
    library: dict[str, bool] | None = None,
    **overrides: object,
) -> Run:
    """A summary with everything agreeing, so a test names only what it changes."""
    stored = {"pc-thm": ("$= ( ax-1 ) ABC", True)} if proofs is None else proofs
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
    }
    return Run(**{**fields, **overrides})  # type: ignore[arg-type]


TWO_LAYERS = [("Propositional calculus", 1), ("First-order logic", 1)]
BOTH = {"pc-thm": ("$= ( ax-1 ) ABC", True), "fol-thm": ("$= ( ax-4 ) ABC", True)}


def test_two_agreeing_runs_over_a_real_spine_are_a_confirmation() -> None:
    flat = run(spine=[("Metamath", 2)], proofs=BOTH)
    spined = run(spine=TWO_LAYERS, proofs=BOTH)

    assert compare(flat, spined).differences == []


def test_a_spine_that_collapsed_to_one_layer_is_refused() -> None:
    # **From review.** A plan whose section titles the file does not open, or a
    # `--limit` short of the second boundary, gives one system — and then every
    # equality the script checks holds because the two runs *are* the same run.
    # Reproduced against the repo's own fixture: at `--limit 1` the script
    # printed "Layering changed nothing" and exited 0 while comparing nothing.
    #
    # The same guard catches a regression that filed every proof into the root,
    # which is a spine in name only.
    flat = run(spine=[("Metamath", 1)])
    spined = run(spine=[("Propositional calculus", 1)])

    reasons = [difference.what for difference in compare(flat, spined).differences]
    assert reasons == ["the spined run is not a spine"]


def test_layers_that_do_not_add_up_are_refused() -> None:
    # Non-empty is not enough: the shares have to partition what was stored, or
    # the breakdown is describing a different run from the one being compared.
    flat = run(spine=[("Metamath", 2)], proofs=BOTH)
    spined = run(spine=[("Propositional calculus", 1), ("First-order logic", 5)],
                 proofs=BOTH)

    reasons = [difference.what for difference in compare(flat, spined).differences]
    assert reasons == ["per-layer proof counts"]


def test_a_rewritten_proof_source_is_caught() -> None:
    # The headline: a citation is stored as a bare label and resolves through the
    # spine, so splitting a corpus must not rewrite one. Same labels, same
    # verdicts, same counts — and a different body.
    flat = run(spine=[("Metamath", 2)], proofs=BOTH)
    spined = run(
        spine=TWO_LAYERS,
        proofs={**BOTH, "fol-thm": ("$= ( ax-4 ) ABD", True)},
    )

    differences = compare(flat, spined).differences
    assert [d.what for d in differences] == ["proof sources or verdicts"]
    assert "fol-thm" in differences[0].detail


def test_a_promotion_refused_under_a_spine_is_caught_twice() -> None:
    # The actual D4 finding, in the shape the script sees it: 354 labels promoted
    # flat and not spined, with the checked/verified/rejected counters identical
    # because `theorems_failed` is counted apart from `failed`. The label set is
    # what caught it; the counter comparison was added afterwards so that the
    # next one trips both, and this asserts that it does.
    flat = run(spine=[("Metamath", 2)], proofs=BOTH, library={"ax-1": True, "ax-5": True})
    spined = run(
        spine=TWO_LAYERS,
        proofs=BOTH,
        library={"ax-1": True},
        theorems=1,
        theorems_failed=1,
    )

    reasons = {difference.what for difference in compare(flat, spined).differences}
    assert reasons == {"theorems", "theorems failed", "library labels"}
