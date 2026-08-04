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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import scripts.restore_proofs as restore
from app.db.metamath_store import import_corpus
from tests.test_metamath_persistence import PROPOSITIONAL
from website.logical.metamath import parse


@pytest.fixture
def corpus(tmp_path) -> str:
    """A throwaway database holding the fragment, with the proofs owned."""
    url = f"sqlite:///{tmp_path / 'corpus.db'}"
    restore._provision(url, recreate=False)
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


def _drive(
    url: str, rounds: list[str], keys: list[restore.Key]
) -> tuple[dict[str, restore.Tally], dict[str, int]]:
    owner = restore._owner_of(url)
    rows, children = restore._term_rows(url, keys)
    codes: dict[str, int] = {}
    tallies = asyncio.run(
        restore.drive(url, owner, keys, rounds, _settings(), rows, children, codes)
    )
    return tallies, codes


def _run(url: str, rounds: list[str]) -> tuple[dict[str, restore.Tally], dict[str, int]]:
    return _drive(url, rounds, restore._keys(url, None, 10, longest=False))


def _one(url: str, label: str) -> restore.Key:
    keys = restore._keys(url, [label], 1, longest=False)
    assert len(keys) == 1, keys
    return keys[0]


async def _rewrite(url: str, owner, proof_id, source: str) -> bool:
    engine = create_async_engine(restore._async_url(url))
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        return (await restore._rewrite(sessions, owner, proof_id, source)).ok
    finally:
        await engine.dispose()


async def _probe(url: str, owner, key: restore.Key, codes: dict[str, int]):
    engine = create_async_engine(restore._async_url(url))
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        return await restore.round_probe(sessions, owner, key, [0], 1, codes)
    finally:
        await engine.dispose()


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


def test_the_answer_key_records_the_order_the_citation_names(corpus):
    """A step cited out of slot order must be restored as it was written.

    An edge's `position` is the rule's **slot**, and the assignment search fills
    slots by matching — so `[ax-mp, 3, 2]` and `[ax-mp, 2, 3]` store exactly the
    same edges. An answer key taken from the edges therefore restores whichever
    order the *rule* happens to want, and reports a byte difference against a
    source that is perfectly fine.

    Metamath hides this: the importer emits its citations in slot order, so the
    two coincide for every proof in the corpus. This rewrites one by hand.
    """
    owner = restore._owner_of(corpus)
    key = _one(corpus, "mp2")
    swapped = key.steps[-1]
    assert len(swapped.antecedents) == 2, swapped

    reversed_source = key.source.replace(
        restore.citation_text(swapped.rule, swapped.antecedents),
        restore.citation_text(swapped.rule, tuple(reversed(swapped.antecedents))),
    )
    assert reversed_source != key.source
    assert asyncio.run(_rewrite(corpus, owner, key.proof_id, reversed_source))

    rewritten = _one(corpus, "mp2")
    assert rewritten.steps[-1].antecedents == tuple(reversed(swapped.antecedents))

    # And the round restores exactly that, rather than the order the rule wants.
    tallies, _ = _drive(corpus, ["cite"], [rewritten])
    assert [r.detail for r in tallies["cite"].results if not r.ok] == []


def test_a_driven_proof_is_left_as_the_corpus_wrote_it(corpus):
    # `apply` really inserts a line, so without putting the proof back a second
    # run would find it invalid — and the selection only takes proofs that verify,
    # so it would silently drive fewer and fewer proofs each time.
    before = {key.label: key.source for key in restore._keys(corpus, None, 10, longest=False)}
    _run(corpus, list(restore.ROUNDS))
    after = {key.label: key.source for key in restore._keys(corpus, None, 10, longest=False)}
    assert after == before

    # The whole point: the same run again finds the same proofs.
    tallies, _ = _run(corpus, list(restore.ROUNDS))
    for tally in tallies.values():
        assert not [r for r in tally.results if not r.ok]
        assert tally.passed + tally.skipped == 4


def test_a_target_that_already_holds_systems_is_not_silently_dropped(corpus):
    # The natural thing to hand `--database-url` is whatever `DATABASE_URL` is
    # already set to, and this run drops every table and reassigns every proof's
    # owner. Costing a retry is the right price.
    with pytest.raises(SystemExit, match="already holds formal systems"):
        restore._provision(corpus, recreate=False)
    restore._provision(corpus, recreate=True)
    assert restore._keys(corpus, None, 10, longest=False) == []


def test_a_wrong_citation_that_is_accepted_fails_the_probe_round(corpus, monkeypatch):
    # The round counts what a refusal said, and used to count an *acceptance* the
    # same way — so an engine that took an unknown rule name would have been
    # recorded rather than reported. That is the worst thing this round can find.
    owner = restore._owner_of(corpus)
    key = _one(corpus, "mp2")

    async def _accept(sessions, owner_id, proof_id, line, rule, antecedents=(), apply=True):
        return restore.Call(
            outcome=restore.CitationOutcome(
                line=line,
                citation=restore.citation_text(rule, antecedents),
                accepted=True,
            )
        )

    monkeypatch.setattr(restore, "_cite", _accept)
    codes: dict[str, int] = {}
    result = asyncio.run(
        _probe(corpus, owner, key, codes)
    )
    assert result.ok is False
    assert "should have been refused with 'bad-reference'" in result.detail


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


def test_rounds_run_in_the_harness_order_not_the_operator_s():
    # `apply` edits the proof the others read, so it runs last however it is asked
    # for. Otherwise `--rounds apply,cite` drives `cite` against an answer key one
    # line out of date and blames the engine for the flag.
    assert restore._ordered_rounds("apply,cite") == ["cite", "apply"]
    assert restore._ordered_rounds("state, probe ") == ["state", "probe"]
    with pytest.raises(ValueError, match="nonesuch"):
        restore._ordered_rounds("cite,nonesuch")


def test_the_async_url_understands_a_url_that_names_its_driver():
    # Reached only after the import on the default path, so a scheme this did not
    # recognise used to blow up minutes of work later.
    assert restore._async_url("sqlite:////tmp/x.db") == "sqlite+aiosqlite:////tmp/x.db"
    for named in ("postgresql+psycopg://u@h/db", "postgres://u@h/db"):
        assert restore._async_url(named) == "postgresql+asyncpg://u@h/db"


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
