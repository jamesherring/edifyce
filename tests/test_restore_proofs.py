"""The corpus-driven authoring loop, on a corpus small enough for CI.

`scripts/restore_proofs.py` drives the structured write path — holes, `/cite`,
`/lines` — against imported Metamath proofs, using the original as an answer key.
Running it over `set.mm` is what found the arity cliff in `Proof.justify`
(docs/authoring-and-ingestion-roadmap.md §9d), and that is not something a suite
can do: the corpus is a 50 MB download and a slice big enough to be interesting
takes minutes to import.

What *can* be pinned here is the harness itself, over the same propositional
fragment `tests/test_metamath_persistence.py` quotes. Four real proofs with real
compressed proofs and a genuinely used library is enough to run every round, so a
change that breaks the loop — or breaks the harness that would have caught it —
fails here rather than the next time someone downloads `set.mm`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import scripts.restore_proofs as restore
from app.db.metamath_store import import_corpus
from tests.test_metamath_persistence import PROPOSITIONAL
from website.logical.metamath import parse


@pytest.fixture
def corpus(tmp_path) -> str:
    """A throwaway database holding the fragment, with the proofs owned."""
    url = f"sqlite:///{tmp_path / 'corpus.db'}"
    restore._provision(url)
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(PROPOSITIONAL), name="fragment")
            session.commit()
        assert report.verified == 4, report
    finally:
        engine.dispose()
    restore._own(url, "harness@example.invalid")
    return url


def _settings(**overrides) -> SimpleNamespace:
    return SimpleNamespace(
        insert_positions=3,
        max_nodes=400,
        state_lines=3,
        probe_lines=3,
        quiet=True,
        **overrides,
    )


def _run(url: str, rounds: list[str]) -> tuple[dict[str, restore.Tally], dict[str, int]]:
    owner = restore._owner_of(url)
    keys = restore._keys(url, None, 10, longest=False)
    rows, children = restore._term_rows(url, keys)
    codes: dict[str, int] = {}
    tallies = asyncio.run(
        restore.drive(url, owner, keys, rounds, _settings(), rows, children, codes)
    )
    return tallies, codes


def test_every_round_passes_on_a_real_fragment(corpus):
    tallies, _ = _run(corpus, list(restore.ROUNDS))
    for name, tally in tallies.items():
        failures = [f"{r.label}: {r.detail}" for r in tally.results if not r.ok]
        assert not failures, f"{name} — {failures}"
        assert tally.passed + tally.skipped == 4


def test_a_blanked_proof_comes_back_byte_identical(corpus):
    # The `cite` round's own assertion, restated here so the reason this suite
    # exists is legible: an equivalent-but-different source would mean the loop
    # silently rewrote a step, which is exactly what an answer key is for.
    tallies, _ = _run(corpus, ["cite"])
    assert [r.ok for r in tallies["cite"].results] == [True] * 4


def test_antecedent_order_carries_no_information(corpus):
    # A citation with its antecedents reversed is accepted, every time: the
    # assignment search is a bipartite matching over slots, so the *set* is the
    # citation and the order is presentation. Recorded because an emitting model
    # that thinks otherwise will spend effort on a degree of freedom that is not
    # one (roadmap §9d).
    _, codes = _run(corpus, ["probe"])
    swapped = {key: n for key, n in codes.items() if key.startswith("swapped:")}
    assert swapped and set(swapped) == {"swapped:accepted"}


def test_omitting_antecedents_asks_the_checker_to_infer_them(corpus):
    # And is not an error: `Proof.justify` takes the lines immediately above. The
    # fragment's proofs are written in dependency order, so some of these land.
    _, codes = _run(corpus, ["probe"])
    assert codes.get("none-cited:accepted", 0) > 0


def test_an_unknown_rule_and_a_miscount_land_in_the_vocabulary(corpus):
    # `drive` fails the round when they do not, so this is really an assertion
    # that the probes ran at all — a mutation that produced nothing would pass
    # the round silently.
    _, codes = _run(corpus, ["probe"])
    assert codes.get("unknown-rule:bad-reference", 0) > 0
    assert codes.get("one-long:antecedent-count", 0) > 0


# ---------------------------------------------------------------------------
# The harness's own arithmetic
# ---------------------------------------------------------------------------


def test_spread_keeps_both_ends():
    assert restore._spread(range(1, 11), 3) == [1, 5, 10]
    assert restore._spread(range(1, 4), 9) == [1, 2, 3]
    # One means the last, not the first: a proof's conclusion is the interesting
    # line, and its first step is usually a hypothesis.
    assert restore._spread(range(1, 11), 1) == [10]


def test_a_line_is_holed_by_replacing_its_citation():
    assert restore._holed("( ph -> ps ) [ax-mp, 1, 2]") == "( ph -> ps ) [?]"
    # Nothing bracketed to replace: left alone rather than guessed at.
    assert restore._holed("ph") == "ph"


def test_a_short_citation_needs_two_antecedents_to_be_short():
    step = restore.Step(1, 0, "MP", (2,), None, "")
    # Dropping the only antecedent is not a short citation — it is a request to
    # infer them, which is a different operation with a different verdict.
    assert restore._mutate("one-short", step) is None
    assert restore._mutate("none-cited", step) == ("MP", ())
    assert restore._mutate("one-short", restore.Step(1, 0, "MP", (2, 3), None, "")) == (
        "MP",
        (2,),
    )


def test_a_self_citation_replaces_rather_than_appends():
    # So the count stays right and ordering is the only thing left wrong.
    step = restore.Step(4, 0, "MP", (1, 2), None, "")
    assert restore._mutate("self-citing", step) == ("MP", (1, 4))
