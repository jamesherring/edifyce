"""Run both experiments against an imported corpus and write the results.

    DATABASE_URL=... uv run --with numpy --with scikit-learn \
        python -m experiments.lindenbaum.run --out results/

Reproduces, at corpus scale, the prototype described in
``experiments/README.md``: a structural embedding that is asked whether syntax
predicts truth, and a Boolean semantic embedding that is asked whether the
connectives survive as exact algebra.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter, deque
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC

from experiments.lindenbaum import formulas, semantic, structural
from experiments.lindenbaum.corpus import Corpus, Theorem, read_corpus
from experiments.lindenbaum.dag import Arena
from experiments.lindenbaum.transport import over_neon_https, over_psycopg

#: How deep into the `.mm` outline a "family" is taken. A chapter is too coarse
#: (three of them cover the corpus) and a leaf section too fine (a handful of
#: theorems each); two levels is the granularity at which a held-out family is
#: recognisably a different subject.
FAMILY_DEPTH = 2
#: The families held out of training, chosen to mirror the prototype's
#: {Foundation, Infinity, Separation, Replacement} rather than sampled: the
#: question is whether an embedding trained on one part of mathematics transfers
#: to a *subject* it has not seen, and a random draw over section names answers a
#: weaker question. set.mm's outline has no Separation section of its own in this
#: prefix — `ax-sep` is developed inside the Extensionality run — so the Power
#: Sets family stands in for it as the fourth distinct axiom family.
HELD_OUT_FAMILIES = ("Infinity", "Replacement", "Regularity", "Power Sets")
#: Matching the prototype's 2¹⁰ = 1024 coordinates, so the two runs compare.
COORDINATES = 1024
PROJECTIONS = (8, 32, 64, 128, 256)
#: Kernel SVM is O(n²) to fit; the linear and neighbour models see everything.
SVM_CAP = 6000
NEIGHBOUR_CAP = 8000


def _family(theorem: Theorem) -> str:
    return "/".join(theorem.section.split("/")[:FAMILY_DEPTH])


def _accuracy(predicted: np.ndarray, actual: np.ndarray) -> float:
    return float((predicted == actual).mean())


def _classify(
    train_x: np.ndarray,
    train_y: np.ndarray,
    test_x: np.ndarray,
    test_y: np.ndarray,
    seed: int,
) -> dict[str, float]:
    train_x, test_x = structural.standardise(train_x, test_x)
    results: dict[str, float] = {}

    linear = LogisticRegression(max_iter=2000, C=1.0)
    linear.fit(train_x, train_y)
    results["linear"] = _accuracy(linear.predict(test_x), test_y)

    rng = np.random.default_rng(seed)
    take = rng.permutation(len(train_x))[:SVM_CAP]
    svm = SVC(kernel="rbf", C=1.0, gamma="scale")
    svm.fit(train_x[take], train_y[take])
    results["rbf_svm"] = _accuracy(svm.predict(test_x), test_y)

    take = rng.permutation(len(train_x))[:NEIGHBOUR_CAP]
    neighbour = KNeighborsClassifier(n_neighbors=1, n_jobs=-1)
    neighbour.fit(train_x[take], train_y[take])
    results["nearest_neighbour"] = _accuracy(neighbour.predict(test_x), test_y)
    return results


def _skeleton_features(compounds: list[formulas.Compound]) -> np.ndarray:
    """A bag of operator-tree shapes — the label's actual cause, as features.

    The control the structural experiment is measured against: the label is a
    function of the skeleton, so a classifier given the skeleton and nothing else
    is an upper bound on what any embedding of these formulas could achieve.
    """
    shapes = [compound.skeleton.shape() for compound in compounds]
    vocabulary = {shape: at for at, shape in enumerate(sorted(set(shapes)))}
    operators = sorted(formulas.CONNECTIVES)
    extra = len(operators) + 3
    matrix = np.zeros((len(compounds), len(vocabulary) + extra), dtype=np.float64)
    for row, (compound, shape) in enumerate(zip(compounds, shapes, strict=True)):
        matrix[row, vocabulary[shape]] = 1.0
        for at, operator in enumerate(operators):
            matrix[row, len(vocabulary) + at] = shape.count(f"{operator}(")
        matrix[row, -3] = compound.skeleton.size()
        matrix[row, -2] = len(compound.generators)
        matrix[row, -1] = shape.count("(")
    return matrix


def _citation_distances(
    corpus: Corpus, labels: list[str], pairs: int, seed: int
) -> tuple[list[int], list[tuple[int, int]]]:
    """Shortest-path distances in the citation graph, for a sample of pairs.

    The graph is taken undirected: "how far apart in the library" is the question,
    and a citation is evidence of proximity whichever way it points.
    """
    position = {label: at for at, label in enumerate(labels)}
    adjacency: list[set[int]] = [set() for _ in labels]
    for source, targets in corpus.cites.items():
        if source not in position:
            continue
        for target in targets:
            if target in position:
                adjacency[position[source]].add(position[target])
                adjacency[position[target]].add(position[source])

    rng = random.Random(seed)
    sources = rng.sample(range(len(labels)), min(len(labels), 256))
    distances: list[int] = []
    sampled: list[tuple[int, int]] = []
    for source in sources:
        seen = {source: 0}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen[neighbour] = seen[node] + 1
                    queue.append(neighbour)
        reachable = [node for node in seen if node != source]
        if not reachable:
            continue
        for target in rng.sample(reachable, min(len(reachable), pairs // len(sources) + 1)):
            distances.append(seen[target])
            sampled.append((source, target))
    return distances, sampled


def _check_alpha_keys(corpus: Corpus, arena: Arena) -> dict[str, object]:
    """Check the experiment's alpha key against the engine's `alpha_digest`.

    Experiment 1's whole feature space is a bag of alpha classes, so a key that
    was subtly wrong — collapsing `φ → φ` into `φ → ψ`, say — would produce a
    negative result that said nothing about embeddings. The engine already
    computes an alpha-invariant hash for every stored term for its own "same
    statement up to variable names" index, so the two partitions can be compared:
    agreement is the check.

    Compared over **statement roots**, not over every row. The engine numbers a
    term's free variables from the root of whatever statement it was stored
    under and writes that digest onto each subterm row — so a shared subterm's
    stored digest depends on which statement interned it first, and is not a
    per-subterm alpha class at all. A root's is. The key here is numbered within
    each subterm and so is compositional, which is what a bag-of-subtrees feature
    needs; the two agree exactly where the engine's is anchored.
    """
    roots = sorted({theorem.term for theorem in corpus.theorems if theorem.term >= 0})
    by_key: dict[int, str] = {}
    by_digest: dict[str, int] = {}
    conflicts = 0
    compared = 0
    for term in roots:
        digest = corpus.alpha_digest[term]
        if digest is None:
            continue
        compared += 1
        key = arena.key[term]
        if by_key.setdefault(key, digest) != digest:
            conflicts += 1
        elif by_digest.setdefault(digest, key) != key:
            conflicts += 1
    return {
        "statement_roots_compared": compared,
        "alpha_classes": len(by_digest),
        "disagreements_with_engine": conflicts,
    }


def _report_families(generators: list[Theorem]) -> list[tuple[str, int]]:
    counts = Counter(_family(theorem) for theorem in generators)
    return counts.most_common()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres@127.0.0.1:5439/edifyce",
        help="the corpus to read, over psycopg",
    )
    parser.add_argument(
        "--neon-https",
        action="store_true",
        help=(
            "read the corpus over Neon's SQL-over-HTTP endpoint using "
            "$POSTGRES_URL, for a database whose Postgres port is not reachable"
        ),
    )
    parser.add_argument(
        "--system",
        action="append",
        default=None,
        help=(
            "a system to read, repeatable; the default reads every system that "
            "holds theorems, which is what a layered import wants"
        ),
    )
    parser.add_argument("--cache", type=Path, default=None, help="corpus pickle")
    parser.add_argument("--out", type=Path, required=True, help="results directory")
    parser.add_argument("--compounds", type=int, default=24000)
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
        corpus = read_corpus(query, arguments.system)
        if arguments.cache is not None:
            arguments.cache.parent.mkdir(parents=True, exist_ok=True)
            corpus.save(arguments.cache)
    print(f"corpus {', '.join(corpus.systems)}: {len(corpus.theorems)} theorems, "
          f"{len(corpus.kind)} terms, read in {time.time() - started:.1f}s")

    arena = Arena.of(corpus)
    generators = corpus.closed_theorems()
    rng = random.Random(arguments.seed)
    results: dict[str, object] = {
        "corpus": {
            "systems": corpus.systems,
            "theorems": len(corpus.theorems),
            "primitive": sum(1 for t in corpus.theorems if t.primitive),
            "with_hypotheses": sum(1 for t in corpus.theorems if t.premises),
            "without_stored_term": sum(1 for t in corpus.theorems if t.term < 0),
            "generators": len(generators),
            "terms": len(corpus.kind),
            "citation_edges": sum(len(v) for v in corpus.cites.values()),
            "sections": len({t.section for t in corpus.theorems}),
        }
    }
    print(f"generators (closed, with a stored term): {len(generators)}")

    results["alpha_key_check"] = _check_alpha_keys(corpus, arena)
    print(f"alpha key vs engine: {results['alpha_key_check']}")

    families = _report_families(generators)
    named = [name for name, _ in families if name]
    unseen = {
        name
        for name in named
        if any(keyword in name for keyword in HELD_OUT_FAMILIES)
    }
    seen = [name for name in named if name not in unseen]
    seen_pool = [t for t in generators if _family(t) in set(seen)]
    unseen_pool = [t for t in generators if _family(t) in unseen]
    # Each keyword must land somewhere. A layered import re-roots the outline per
    # layer, so one axiom family can arrive as several sections and matching on
    # count would be wrong; matching on coverage is the invariant that matters.
    unmatched = [
        keyword
        for keyword in HELD_OUT_FAMILIES
        if not any(keyword in name for name in unseen)
    ]
    if unmatched:
        raise RuntimeError(f"held-out families matched no section: {unmatched}")
    results["families"] = {
        "all": [{"name": n, "generators": c} for n, c in families],
        "train": seen,
        "held_out": sorted(unseen),
        "train_generators": len(seen_pool),
        "held_out_generators": len(unseen_pool),
    }
    print(f"families: {len(families)}; holding out {sorted(unseen)}")

    print("building the fragment…")
    fragment = formulas.generate(
        arena, generators, count=arguments.compounds, rng=rng
    )
    train_fragment = formulas.generate(
        arena, seen_pool, count=int(arguments.compounds * 2 / 3), rng=rng
    )
    test_fragment = formulas.generate(
        arena, unseen_pool, count=int(arguments.compounds / 3), rng=rng
    )
    results["fragment"] = {
        "compounds": len(fragment),
        "provable": sum(1 for c in fragment if c.provable),
        "seen_family_compounds": len(train_fragment),
        "unseen_family_compounds": len(test_fragment),
        "skeleton_shapes": len({c.skeleton.shape() for c in fragment}),
        "mean_formula_nodes": None,
    }

    print("embedding structurally…")
    stamp = time.time()
    x_all = structural.embed(arena, [c.term for c in fragment])
    x_train = structural.embed(arena, [c.term for c in train_fragment])
    x_test = structural.embed(arena, [c.term for c in test_fragment])
    results["fragment"]["mean_formula_nodes"] = float(
        np.expm1(x_all[:, structural.BUCKETS]).mean()
    )
    print(f"  {len(fragment) + len(train_fragment) + len(test_fragment)} formulas "
          f"in {time.time() - stamp:.1f}s")

    y_all = np.array([c.provable for c in fragment], dtype=int)
    y_train = np.array([c.provable for c in train_fragment], dtype=int)
    y_test = np.array([c.provable for c in test_fragment], dtype=int)

    cut = int(len(fragment) * 0.75)
    experiment_one: dict[str, object] = {
        "unseen_family": _classify(
            x_train, y_train, x_test, y_test, arguments.seed
        ),
        "random_split": _classify(
            x_all[:cut], y_all[:cut], x_all[cut:], y_all[cut:], arguments.seed
        ),
    }

    skeleton_all = _skeleton_features(fragment)
    control = LogisticRegression(max_iter=2000)
    control.fit(skeleton_all[:cut], y_all[:cut])
    experiment_one["skeleton_only_control"] = _accuracy(
        control.predict(skeleton_all[cut:]), y_all[cut:]
    )
    results["experiment_1"] = experiment_one
    print(f"experiment 1: {experiment_one}")

    print("citation graph vs structural distance…")
    labels = [t.label for t in generators]
    graph_distance, pairs = _citation_distances(corpus, labels, 4000, arguments.seed)
    statements = structural.embed(arena, [t.term for t in generators])
    embedded = np.linalg.norm(
        statements[[a for a, _ in pairs]] - statements[[b for _, b in pairs]], axis=1
    )
    rho, p_value = spearmanr(graph_distance, embedded)
    results["citation_graph"] = {
        "pairs": len(pairs),
        "spearman_rho": float(rho),
        "p_value": float(p_value),
        "mean_path_length": float(np.mean(graph_distance)),
    }
    print(f"  rho = {rho:.4f} over {len(pairs)} pairs")

    print("embedding semantically…")
    slot_of = {theorem.label: at for at, theorem in enumerate(generators)}
    omega = semantic.assignments(len(generators), COORDINATES, arguments.seed)
    e_all = semantic.embed(fragment, omega, slot_of)

    distinguished = e_all[:, semantic.DISTINGUISHED]
    provability_accuracy = float(((distinguished > 0) == (y_all == 1)).mean())

    algebra: dict[str, float] = {}
    wanted = min(2000, len(fragment) - len(fragment) % 2)
    sample = rng.sample(range(len(fragment)), wanted)
    left = [fragment[i] for i in sample[: wanted // 2]]
    right = [fragment[i] for i in sample[wanted // 2 :]]
    e_left = semantic.embed(left, omega, slot_of)
    e_right = semantic.embed(right, omega, slot_of)

    negated = np.stack([
        semantic.embed_one(
            formulas.Skeleton(op="not", args=(c.skeleton,)), c.generators, omega, slot_of
        )
        for c in left
    ])
    algebra["negation"] = float(np.abs(negated + e_left).max())
    for operator, predicted in (
        ("and", np.minimum(e_left, e_right)),
        ("or", np.maximum(e_left, e_right)),
        ("imp", np.maximum(-e_left, e_right)),
        ("iff", e_left.astype(np.int16) * e_right.astype(np.int16)),
    ):
        joined = np.stack([
            semantic.embed_one(*semantic.combine(operator, a, b), omega, slot_of)
            for a, b in zip(left, right, strict=True)
        ])
        algebra[operator] = float(np.abs(joined - predicted).max())

    squared = ((e_left.astype(np.int32) - e_right.astype(np.int32)) ** 2).sum(axis=1)
    hamming = semantic.hamming(e_left, e_right)
    algebra["hamming_identity"] = float(np.abs(squared - 4 * hamming).max())

    projections = []
    subset = e_all[: min(len(e_all), 4000)]
    drawn = min(1500, len(subset) - len(subset) % 2)
    index = rng.sample(range(len(subset)), drawn)
    a, b = index[: drawn // 2], index[drawn // 2 :]
    exact = np.linalg.norm(
        subset[a].astype(np.float64) - subset[b].astype(np.float64), axis=1
    )
    # A zero-distance pair is two formulas of the fragment that agree under every
    # sampled assignment — logically equivalent, as far as these coordinates can
    # see. A relative error is undefined there, so they are excluded and counted:
    # how many there are is itself a fact about the fragment.
    separated = exact > 0
    kept_a = [index for index, keep in zip(a, separated, strict=True) if keep]
    kept_b = [index for index, keep in zip(b, separated, strict=True) if keep]
    exact = exact[separated]
    for dimension in PROJECTIONS:
        compressed = semantic.project(subset, dimension, arguments.seed)
        approximate = np.linalg.norm(compressed[kept_a] - compressed[kept_b], axis=1)
        error = np.abs(approximate - exact) / exact
        projections.append(
            {
                "dimension": dimension,
                "median_relative_error": float(np.median(error)),
                "p90_relative_error": float(np.quantile(error, 0.9)),
            }
        )

    results["experiment_2"] = {
        "coordinates": COORDINATES,
        "generators": len(generators),
        "exhaustive": False,
        "distinguished_coordinate_accuracy": provability_accuracy,
        "algebraic_identity_max_error": algebra,
        "random_projection": projections,
        "projection_pairs": len(exact),
        "equivalent_pairs_excluded": int((~separated).sum()),
    }
    print(f"experiment 2: E* accuracy {provability_accuracy:.4f}, algebra {algebra}")

    print("can structure predict semantics?")
    structural_distance = np.linalg.norm(
        x_all[a].astype(np.float64) - x_all[b].astype(np.float64), axis=1
    )
    semantic_hamming = semantic.hamming(subset[a], subset[b])
    rho_sem, p_sem = spearmanr(structural_distance, semantic_hamming)

    targets = list(range(1, 33))
    ridge = Ridge(alpha=1.0)
    train_x, test_x = structural.standardise(x_all[:cut], x_all[cut:])
    e_train = e_all[:cut][:, targets].astype(np.float64)
    e_test = e_all[cut:][:, targets]
    ridge.fit(train_x, e_train)
    predicted = np.sign(ridge.predict(test_x))
    predicted[predicted == 0] = 1
    results["structure_to_semantics"] = {
        "spearman_rho_structural_vs_hamming": float(rho_sem),
        "p_value": float(p_sem),
        "coordinates_predicted": len(targets),
        "mean_coordinate_accuracy": float((predicted == e_test).mean()),
        "best_coordinate_accuracy": float((predicted == e_test).mean(axis=0).max()),
    }
    print(f"  rho = {rho_sem:.4f}, coordinate accuracy "
          f"{results['structure_to_semantics']['mean_coordinate_accuracy']:.4f}")

    results["runtime_seconds"] = time.time() - started
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {arguments.out / 'results.json'} in {results['runtime_seconds']:.0f}s")


if __name__ == "__main__":
    main()
