"""Can the corpus prove itself? And does the geometry help?

    uv run --with numpy python -m experiments.lindenbaum.run_search \
        --out experiments/results --goals 600

Walks the corpus in declaration order. Each sampled theorem is handed to the
prover with **only what preceded it** — no citations, no proof length, no depth,
nothing from its own proof — and whatever comes back is re-checked by
`checking.py` before it counts. Then the same goals are run again under each
ranker, so the only thing that varies is which lemma the search tries first.

The comparison is the experiment. A prover with an oracle ranker solves
everything and one with a random ranker solves what is shallow; the interesting
number is what a *computable* ranking buys over frequency, which is the
baseline any premise selector has to beat.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

from experiments.lindenbaum import prover as P
from experiments.lindenbaum import quotient
from experiments.lindenbaum.checking import Checker
from experiments.lindenbaum.corpus import Corpus, Theorem, read_corpus
from experiments.lindenbaum.transport import over_neon_https, over_psycopg
from experiments.lindenbaum.unification import Terms, freeze

LAYER_ORDER = ("Propositional calculus", "First-order logic", "ZF set theory")


def declaration_order(corpus: Corpus) -> list[Theorem]:
    def rank(theorem: Theorem) -> tuple[int, int]:
        layer = (
            LAYER_ORDER.index(theorem.system)
            if theorem.system in LAYER_ORDER
            else len(LAYER_ORDER)
        )
        return (layer, theorem.position)

    return sorted(corpus.theorems, key=rank)


def rankers(index: P.Index, seed: int) -> dict[str, P.Scorer]:
    frequency = P.frequency_scorer(index)
    structural = P.structural_scorer(index)
    analogy = P.analogy_scorer(index)
    return {
        "random": P.random_scorer(index, seed),
        "frequency": frequency,
        "structural": structural,
        "analogy": analogy,
        "analogy+frequency": P.combine([(analogy, 2.0), (frequency, 1.0)]),
        "all": P.combine([(analogy, 2.0), (frequency, 1.0), (structural, 1.0)]),
    }


def _eligible(theorem: Theorem, corpus: Corpus, minimum: int) -> bool:
    return (
        theorem.term >= 0
        and all(p >= 0 for p in theorem.premise_terms)
        and corpus.proof_length.get(theorem.label, 0) >= minimum
    )


def run(
    corpus: Corpus,
    terms: Terms,
    ordered: list[Theorem],
    wanted: set[str],
    name: str,
    steps: int,
    width: int,
    depth: int,
    propositional: bool,
    use_quotient: bool,
) -> dict[str, object]:
    index = P.Index(terms)
    equivalences = quotient.Equivalences(terms) if use_quotient else None
    scorer = rankers(index, 7)[name]
    prover = P.Prover(
        terms, index, scorer, propositional=propositional, equivalences=equivalences
    )
    solved: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    attempted = 0
    started = time.time()

    for theorem in ordered:
        if theorem.label in wanted and _eligible(theorem, corpus, 1):
            attempted += 1
            hypotheses = tuple(
                terms.canonical(p) for p in theorem.premise_terms if p >= 0
            )
            attempt = P.Attempt(
                label=theorem.label,
                goal=terms.canonical(theorem.term),
                hypotheses=hypotheses,
                disjoint=frozenset(theorem.disjoint),
            )
            budget = P.Budget(steps=steps, depth=depth, width=width)
            # Everything the attempt interns is released once its report has
            # been taken, so the arena stays the size of the corpus rather than
            # growing with every lemma the search ever refreshed.
            mark = terms.mark()
            found = prover.attempt(attempt, budget)
            if found is not None:
                checker = Checker(
                    terms,
                    {lemma.label: lemma for lemma in index.lemmas},
                    frozenset(freeze(terms, h) for h in hypotheses),
                    frozenset(theorem.disjoint),
                    equivalences,
                )
                complaint = checker.check(
                    found, freeze(terms, terms.canonical(theorem.term))
                )
                if complaint is not None:
                    rejected.append(
                        {"theorem": theorem.label, "reason": complaint.reason}
                    )
                else:
                    cited = set(corpus.cites.get(theorem.label, ()))
                    labels = found.labels() - {"$e"}
                    solved.append(
                        {
                            "theorem": theorem.label,
                            "depth": found.depth(),
                            "steps": found.size(),
                            "corpus_proof_lines": corpus.proof_length.get(
                                theorem.label, 0
                            ),
                            "budget_used": budget.used,
                            "section": theorem.section.split("/")[-1],
                            "lemmas": sorted(labels),
                            "same_lemmas_as_corpus": labels == cited,
                            "novel_lemmas": sorted(labels - cited),
                        }
                    )
            terms.release(mark)
            if equivalences is not None:
                equivalences.forget()

        if equivalences is not None:
            equivalences.add(theorem)
        lemma = P.as_lemma(terms, theorem)
        if lemma is not None:
            at = index.add(lemma)
            index.cited[at] = corpus.cites.get(theorem.label, ())
        for label in corpus.cites.get(theorem.label, ()):
            index.cite(label)

    return {
        "ranker": name,
        "attempted": attempted,
        "solved": len(solved),
        "rate": len(solved) / attempted if attempted else 0.0,
        "rejected_by_checker": rejected,
        "seconds": time.time() - started,
        "proofs": solved,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default="postgresql://postgres@127.0.0.1:5439/edifyce"
    )
    parser.add_argument("--neon-https", action="store_true")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--goals", type=int, default=600)
    parser.add_argument(
        "--from-position",
        type=int,
        default=0,
        help=(
            "only sample theorems declared at or after this position — with a "
            "corpus imported past the library's end, this is the held-out set: "
            "goals whose statements were never part of the searched library"
        ),
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=4,
        help="only sample theorems whose stored proof is at least this long",
    )
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--width", type=int, default=14)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--rankers", default="random,frequency,analogy,all")
    parser.add_argument(
        "--propositional",
        action="store_true",
        help="close a subgoal when the hypotheses propositionally entail it",
    )
    parser.add_argument(
        "--quotient",
        action="store_true",
        help=(
            "let the closer rewrite an atom through a proved biconditional, so "
            "it computes modulo the equivalences the corpus has established "
            "rather than in the free algebra"
        ),
    )
    arguments = parser.parse_args()

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
    pool = [
        t
        for t in ordered
        if _eligible(t, corpus, arguments.min_lines)
        and t.position >= arguments.from_position
    ]
    rng = random.Random(arguments.seed)
    sample = rng.sample(pool, min(arguments.goals, len(pool)))
    wanted = {t.label for t in sample}
    print(
        f"{len(corpus.theorems)} theorems; {len(pool)} with >= {arguments.min_lines} "
        f"proof lines; sampling {len(wanted)}"
    )

    results = []
    for name in arguments.rankers.split(","):
        outcome = run(
            corpus,
            terms,
            ordered,
            wanted,
            name,
            arguments.steps,
            arguments.width,
            arguments.depth,
            arguments.propositional,
            arguments.quotient,
        )
        proofs = outcome["proofs"]
        deep = sum(1 for p in proofs if p["depth"] >= 3)
        novel = sum(1 for p in proofs if not p["same_lemmas_as_corpus"])
        print(
            f"{name:20s} solved {outcome['solved']:4d}/{outcome['attempted']} "
            f"({outcome['rate']:.1%}), depth>=3 {deep:4d}, "
            f"different lemmas from set.mm {novel:4d}, "
            f"rejected {len(outcome['rejected_by_checker'])}, "
            f"{outcome['seconds']:.0f}s"
        )
        results.append(outcome)

    summary = {
        "corpus": {
            "theorems": len(corpus.theorems),
            "systems": corpus.systems,
            "eligible": len(pool),
            "sampled": len(wanted),
            "min_proof_lines": arguments.min_lines,
        },
        "budget": {
            "steps": arguments.steps,
            "width": arguments.width,
            "depth": arguments.depth,
            "propositional_closer": arguments.propositional,
            "equivalence_quotient": arguments.quotient,
        },
        "rankers": [
            {
                key: value
                for key, value in outcome.items()
                if key != "proofs"
            }
            | {
                "depth_histogram": dict(
                    Counter(p["depth"] for p in outcome["proofs"])
                ),
                "solved_by_section": Counter(
                    p["section"] for p in outcome["proofs"]
                ).most_common(10),
                "different_lemmas_from_corpus": sum(
                    1 for p in outcome["proofs"] if not p["same_lemmas_as_corpus"]
                ),
                "mean_corpus_proof_lines_of_solved": (
                    sum(p["corpus_proof_lines"] for p in outcome["proofs"])
                    / len(outcome["proofs"])
                    if outcome["proofs"]
                    else 0.0
                ),
                "examples": sorted(
                    outcome["proofs"],
                    key=lambda p: (-p["corpus_proof_lines"], -p["depth"]),
                )[:20],
            }
            for outcome in results
        ],
    }
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "search.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {arguments.out / 'search.json'}")


if __name__ == "__main__":
    main()
