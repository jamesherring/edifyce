"""Three cheap measurements the prover's ranking rests on.

    uv run --with numpy --with scikit-learn \
        python -m experiments.lindenbaum.run_retrieval --out experiments/results

**Premise selection.** For each goal, rank the library and ask how much of what
its real proof cited lands in the top *k*. This is the metric a proof assistant
actually cares about, and unlike everything in `run.py` its ground truth is
already stored — `proof_lines.rule` is what the corpus itself reached for.

**Axiom-dependency signatures.** The free Boolean space of `run.py` gives every
generator an independent coordinate, which is why nothing about a formula
predicts its position. A theorem's *transitive axiom dependencies* are a
coordinate system with the opposite property: not free, computable from the
citation DAG, and different for theorems that are all equally provable. So the
question that came back at ρ = 0.0002 for the free space is asked again here.

**Proof length.** Whether syntax says anything about how hard a statement is,
which is what a search would order its frontier by.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

from experiments.lindenbaum import prover as P
from experiments.lindenbaum.corpus import Corpus, Theorem, read_corpus
from experiments.lindenbaum.run_search import declaration_order
from experiments.lindenbaum.transport import over_neon_https, over_psycopg
from experiments.lindenbaum.unification import Terms

CUTOFFS = (10, 50, 100, 200)


def axiom_signatures(corpus: Corpus, ordered: list[Theorem]) -> dict[str, int]:
    """Label → bitmask of the primitive axioms its proof transitively needs.

    One pass in declaration order is enough: a citation always points backwards,
    so a theorem's dependencies are settled before it is reached. Held as an int
    because 177 axioms fit in one, and the set operations the analysis wants are
    then single instructions.
    """
    axioms = [t.label for t in ordered if t.primitive]
    bit = {label: 1 << at for at, label in enumerate(axioms)}
    signature: dict[str, int] = {}
    for theorem in ordered:
        mask = bit.get(theorem.label, 0)
        for cited in corpus.cites.get(theorem.label, ()):
            mask |= signature.get(cited, 0)
        signature[theorem.label] = mask
    return signature


def _jaccard(left: int, right: int) -> float:
    union = bin(left | right).count("1")
    return 1.0 - (bin(left & right).count("1") / union) if union else 0.0


def premise_selection(
    corpus: Corpus, terms: Terms, ordered: list[Theorem], wanted: set[str], seed: int
) -> dict[str, object]:
    """Recall@k for each ranker, against the lemmas the real proof cited."""
    index = P.Index(terms)
    rng = random.Random(seed)
    totals: dict[str, dict[int, float]] = {}
    counted = 0

    for theorem in ordered:
        if theorem.label in wanted and theorem.term >= 0 and index.lemmas:
            truth = {
                label
                for label in corpus.cites.get(theorem.label, ())
                if label in index.by_label
            }
            if truth:
                counted += 1
                goal = terms.canonical(theorem.term)
                # Deep enough that the structural ranking is not truncated at the
                # widest cutoff — a saturating curve would read as a ceiling on
                # the method rather than on the list it was given.
                neighbours = index.neighbours(goal, max(CUTOFFS))
                votes: dict[str, float] = {}
                for at, weight in neighbours:
                    for label in index.cited[at]:
                        votes[label] = votes.get(label, 0.0) + weight
                ranked = {
                    "analogy": [
                        label
                        for label, _ in sorted(votes.items(), key=lambda p: -p[1])
                    ],
                    "structural": [index.lemmas[at].label for at, _ in neighbours],
                    "frequency": [
                        index.lemmas[at].label
                        for at in sorted(
                            range(len(index.lemmas)),
                            key=lambda at: -index.uses[at],
                        )[: max(CUTOFFS)]
                    ],
                    "random": [
                        index.lemmas[at].label
                        for at in rng.sample(
                            range(len(index.lemmas)),
                            min(len(index.lemmas), max(CUTOFFS)),
                        )
                    ],
                }
                # Analogy is a vote over *cited* labels, so its list can be
                # shorter than the deepest cutoff; padding it with the frequency
                # ranking is what a real selector would do and keeps the cutoffs
                # comparable.
                ranked["analogy"] = ranked["analogy"] + [
                    label
                    for label in ranked["frequency"]
                    if label not in set(ranked["analogy"])
                ]
                for name, order in ranked.items():
                    bucket = totals.setdefault(name, dict.fromkeys(CUTOFFS, 0.0))
                    for cutoff in CUTOFFS:
                        top = set(order[:cutoff])
                        bucket[cutoff] += len(truth & top) / len(truth)

        lemma = P.as_lemma(terms, theorem)
        if lemma is not None:
            at = index.add(lemma)
            index.cited[at] = corpus.cites.get(theorem.label, ())
        for label in corpus.cites.get(theorem.label, ()):
            index.cite(label)

    return {
        "goals": counted,
        "recall": {
            name: {str(cutoff): value / counted for cutoff, value in bucket.items()}
            for name, bucket in totals.items()
        },
    }


def signature_geometry(
    corpus: Corpus,
    terms: Terms,
    ordered: list[Theorem],
    signature: dict[str, int],
    seed: int,
) -> dict[str, object]:
    """Is the axiom-dependency signature visible in the statement's syntax?"""
    index = P.Index(terms)
    rows: list[dict[int, float]] = []
    masks: list[int] = []
    lengths: list[int] = []
    for theorem in ordered:
        if theorem.term < 0:
            continue
        rows.append(index.bag(terms.canonical(theorem.term)))
        masks.append(signature.get(theorem.label, 0))
        lengths.append(corpus.proof_length.get(theorem.label, 0))

    keys = sorted({key for row in rows for key in row})
    position = {key: at for at, key in enumerate(keys)}
    matrix = np.zeros((len(rows), len(keys)), dtype=np.float64)
    for at, row in enumerate(rows):
        for key, value in row.items():
            matrix[at, position[key]] = value
    matrix = np.log1p(matrix)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    matrix /= norms[:, None]

    rng = random.Random(seed)
    pairs = [
        (rng.randrange(len(rows)), rng.randrange(len(rows))) for _ in range(4000)
    ]
    pairs = [(a, b) for a, b in pairs if a != b]
    structural = [float(np.linalg.norm(matrix[a] - matrix[b])) for a, b in pairs]
    semantic = [_jaccard(masks[a], masks[b]) for a, b in pairs]
    rho, p_value = spearmanr(structural, semantic)

    # Predicting the signature bit by bit: the axioms that are neither universal
    # nor almost unused, since a bit that is always 1 is predicted by guessing.
    counts = [sum((mask >> bit) & 1 for mask in masks) for bit in range(177)]
    informative = [
        bit
        for bit, count in enumerate(counts)
        if 0.05 * len(masks) < count < 0.95 * len(masks)
    ][:32]
    cut = int(len(rows) * 0.75)
    accuracy = 0.0
    baseline = 0.0
    if informative:
        targets = np.array(
            [[(mask >> bit) & 1 for bit in informative] for mask in masks],
            dtype=np.float64,
        )
        model = Ridge(alpha=1.0)
        model.fit(matrix[:cut], targets[:cut])
        predicted = (model.predict(matrix[cut:]) > 0.5).astype(np.float64)
        accuracy = float((predicted == targets[cut:]).mean())
        majority = (targets[:cut].mean(axis=0) > 0.5).astype(np.float64)
        baseline = float((majority[None, :] == targets[cut:]).mean())

    length = np.log1p(np.array(lengths, dtype=np.float64))
    regression = Ridge(alpha=1.0)
    regression.fit(matrix[:cut], length[:cut])
    predicted_length = regression.predict(matrix[cut:])
    length_rho, _ = spearmanr(predicted_length, length[cut:])
    residual = float(((predicted_length - length[cut:]) ** 2).mean())
    variance = float(((length[cut:] - length[:cut].mean()) ** 2).mean())

    return {
        "theorems": len(rows),
        "distinct_signatures": len(set(masks)),
        "informative_axioms": len(informative),
        "spearman_structural_vs_signature": float(rho),
        "p_value": float(p_value),
        "signature_bit_accuracy": accuracy,
        "signature_bit_majority_baseline": baseline,
        "proof_length_spearman": float(length_rho),
        "proof_length_r2": 1.0 - residual / variance if variance else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default="postgresql://postgres@127.0.0.1:5439/edifyce"
    )
    parser.add_argument("--neon-https", action="store_true")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--goals", type=int, default=800)
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
    signature = axiom_signatures(corpus, ordered)
    rng = random.Random(arguments.seed)
    pool = [t for t in ordered if t.term >= 0 and corpus.cites.get(t.label)]
    sample = rng.sample(pool, min(arguments.goals, len(pool)))

    results = {
        "premise_selection": premise_selection(
            corpus, terms, ordered, {t.label for t in sample}, arguments.seed
        ),
        "signature_geometry": signature_geometry(
            corpus, terms, ordered, signature, arguments.seed
        ),
        "runtime_seconds": time.time() - started,
    }
    print(json.dumps(results, indent=2))
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "retrieval.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
