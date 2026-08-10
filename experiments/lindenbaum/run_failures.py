"""Why the unsolved goals are unsolved.

    uv run --with numpy --with scikit-learn \
        python -m experiments.lindenbaum.run_failures --out experiments/results

A solve rate on its own says how far the prover gets, not what is stopping it,
and those want different fixes. So the same goals are run three times:

1. **as it ships** — the combined ranker at the standard budget;
2. **with an oracle ranker** — the lemmas the real proof cited, ranked first, at
   the *same* budget. Whatever this solves and (1) does not is lost to
   **retrieval**: the search could have done it, and was never handed the lemma.
3. **oracle, deeper and richer** — the same cheat with a larger depth and step
   allowance. What this adds is lost to **budget**; what even this cannot reach
   is lost to something structural, and no ranking will fix it.

The oracle is a measuring instrument, not a method: it reads the goal's own proof,
which is precisely what the honest runs are forbidden.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

from experiments.lindenbaum import prover as P
from experiments.lindenbaum.checking import Checker
from experiments.lindenbaum.corpus import Corpus, Theorem, read_corpus
from experiments.lindenbaum.run_search import _eligible, declaration_order
from experiments.lindenbaum.transport import over_neon_https, over_psycopg
from experiments.lindenbaum.unification import Terms, freeze


def _attempt(
    prover: P.Prover,
    index: P.Index,
    terms: Terms,
    theorem: Theorem,
    budget: P.Budget,
) -> P.Step | None:
    hypotheses = tuple(terms.canonical(p) for p in theorem.premise_terms if p >= 0)
    attempt = P.Attempt(
        label=theorem.label,
        goal=terms.canonical(theorem.term),
        hypotheses=hypotheses,
        disjoint=frozenset(theorem.disjoint),
    )
    mark = terms.mark()
    found = prover.attempt(attempt, budget)
    if found is not None:
        checker = Checker(
            terms,
            {lemma.label: lemma for lemma in index.lemmas},
            frozenset(freeze(terms, h) for h in hypotheses),
            frozenset(theorem.disjoint),
        )
        if checker.check(found, freeze(terms, terms.canonical(theorem.term))) is not None:
            found = None
    depth = found.depth() if found is not None else 0
    terms.release(mark)
    return found if depth else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default="postgresql://postgres@127.0.0.1:5439/edifyce"
    )
    parser.add_argument("--neon-https", action="store_true")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--goals", type=int, default=150)
    parser.add_argument("--min-lines", type=int, default=2)
    parser.add_argument("--steps", type=int, default=1200)
    parser.add_argument("--width", type=int, default=14)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--deep-steps", type=int, default=4000)
    parser.add_argument("--deep-depth", type=int, default=9)
    parser.add_argument("--deep-width", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260809)
    arguments = parser.parse_args()

    started = time.time()
    if arguments.cache is not None and arguments.cache.exists():
        corpus = Corpus.load(arguments.cache)
    else:
        query = (
            over_neon_https()
            if arguments.neon_https
            else over_psycopg(arguments.database_url)
        )
        corpus = read_corpus(query)
        if arguments.cache is not None:
            arguments.cache.parent.mkdir(parents=True, exist_ok=True)
            corpus.save(arguments.cache)

    terms = Terms(corpus)
    ordered = declaration_order(corpus)
    pool = [t for t in ordered if _eligible(t, corpus, arguments.min_lines)]
    rng = random.Random(arguments.seed)
    wanted = {t.label for t in rng.sample(pool, min(arguments.goals, len(pool)))}

    index = P.Index(terms)
    oracle = P.OracleScorer(index)
    honest = P.combine(
        [
            (P.analogy_scorer(index), 2.0),
            (P.frequency_scorer(index), 1.0),
            (P.structural_scorer(index), 1.0),
        ]
    )
    plain = P.Prover(terms, index, honest)
    cheating = P.Prover(terms, index, oracle)

    records: list[dict[str, object]] = []
    for theorem in ordered:
        if theorem.label in wanted:
            cited = frozenset(corpus.cites.get(theorem.label, ()))
            oracle.aim(cited)
            found = _attempt(
                plain,
                index,
                terms,
                theorem,
                P.Budget(
                    steps=arguments.steps,
                    depth=arguments.depth,
                    width=arguments.width,
                ),
            )
            with_oracle = (
                None
                if found is not None
                else _attempt(
                    cheating,
                    index,
                    terms,
                    theorem,
                    P.Budget(
                        steps=arguments.steps,
                        depth=arguments.depth,
                        width=arguments.width,
                    ),
                )
            )
            deeper = (
                None
                if (found is not None or with_oracle is not None)
                else _attempt(
                    cheating,
                    index,
                    terms,
                    theorem,
                    P.Budget(
                        steps=arguments.deep_steps,
                        depth=arguments.deep_depth,
                        width=arguments.deep_width,
                    ),
                )
            )
            missing = sorted(label for label in cited if label not in index.by_label)
            records.append(
                {
                    "theorem": theorem.label,
                    "section": theorem.section.split("/")[-1],
                    "corpus_lines": corpus.proof_length.get(theorem.label, 0),
                    "corpus_depth": corpus.proof_depth.get(theorem.label, 0),
                    "distinct_lemmas_cited": len(cited),
                    "cited_not_in_library": missing,
                    "hypotheses": theorem.premises,
                    "root": terms.constructor[terms.canonical(theorem.term)],
                    "outcome": (
                        "solved"
                        if found is not None
                        else "retrieval"
                        if with_oracle is not None
                        else "budget"
                        if deeper is not None
                        else "structural"
                    ),
                    "found_depth": found.depth() if found is not None else 0,
                }
            )

        lemma = P.as_lemma(terms, theorem)
        if lemma is not None:
            at = index.add(lemma)
            index.cited[at] = corpus.cites.get(theorem.label, ())
        for label in corpus.cites.get(theorem.label, ()):
            index.cite(label)

    outcomes = Counter(record["outcome"] for record in records)
    print(f"{len(records)} goals: {dict(outcomes)}")

    def profile(name: str) -> dict[str, object]:
        rows = [r for r in records if r["outcome"] == name]
        if not rows:
            return {"goals": 0}
        return {
            "goals": len(rows),
            "share": len(rows) / len(records),
            "median_corpus_lines": sorted(r["corpus_lines"] for r in rows)[
                len(rows) // 2
            ],
            "median_corpus_depth": sorted(r["corpus_depth"] for r in rows)[
                len(rows) // 2
            ],
            "median_distinct_lemmas": sorted(r["distinct_lemmas_cited"] for r in rows)[
                len(rows) // 2
            ],
            "with_hypotheses": sum(1 for r in rows if r["hypotheses"]),
            "deeper_than_search_cap": sum(
                1 for r in rows if r["corpus_depth"] > arguments.depth
            ),
            "cites_something_outside_the_library": sum(
                1 for r in rows if r["cited_not_in_library"]
            ),
            "top_sections": Counter(r["section"] for r in rows).most_common(6),
            "top_roots": Counter(r["root"] for r in rows).most_common(6),
        }

    results = {
        "corpus": {"theorems": len(corpus.theorems), "systems": corpus.systems},
        "budget": {
            "steps": arguments.steps,
            "depth": arguments.depth,
            "width": arguments.width,
            "deep_steps": arguments.deep_steps,
            "deep_depth": arguments.deep_depth,
            "deep_width": arguments.deep_width,
        },
        "goals": len(records),
        "outcomes": dict(outcomes),
        "profiles": {name: profile(name) for name in outcomes},
        "records": records,
        "runtime_seconds": time.time() - started,
    }
    print(json.dumps(results["profiles"], indent=2))
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "failures.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {arguments.out / 'failures.json'}")


if __name__ == "__main__":
    main()
