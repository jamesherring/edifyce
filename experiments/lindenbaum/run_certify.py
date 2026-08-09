"""Certify later corpus theorems from earlier ones, and check that it is sound.

    uv run --with numpy --with scikit-learn \
        python -m experiments.lindenbaum.run_certify --neon-https --out results/

Walks the corpus in declaration order, so each theorem is a goal against exactly
what preceded it, and asks how much of the corpus can be established without
looking at a proof. Then four controls, because a certifier that says yes to
everything would score very well on the first question.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

from experiments.lindenbaum import certify, formulas
from experiments.lindenbaum.corpus import Corpus, Theorem, read_corpus
from experiments.lindenbaum.dag import Arena
from experiments.lindenbaum.transport import over_neon_https, over_psycopg

#: set.mm's own order, which a layered import splits into but does not record:
#: each layer's `position` restarts, so a global declaration order has to be
#: rebuilt from the layering. A single-system import has one layer and this is
#: the identity.
LAYER_ORDER = ("Propositional calculus", "First-order logic", "ZF set theory")


def _declaration_order(corpus: Corpus) -> list[Theorem]:
    def rank(theorem: Theorem) -> tuple[int, int]:
        layer = (
            LAYER_ORDER.index(theorem.system)
            if theorem.system in LAYER_ORDER
            else len(LAYER_ORDER)
        )
        return (layer, theorem.position)

    return sorted(corpus.theorems, key=rank)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default="postgresql://postgres@127.0.0.1:5439/edifyce"
    )
    parser.add_argument("--neon-https", action="store_true")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--controls", type=int, default=2000)
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

    arena = Arena.of(corpus)
    ordered = _declaration_order(corpus)
    atoms: dict[int, int] = {}

    # Walk the corpus as it was written: each theorem is a goal against exactly
    # what preceded it, and then joins the library. A single 80/20 split would
    # only ever ask about the last chapter, which for this prefix is all ZF —
    # and would report zero without saying that the propositional part, where
    # this fragment can work at all, was never a goal.
    library = certify.Library()
    goals: list[Theorem] = []
    certificates: list[certify.Certificate] = []
    unreached = 0
    without_lemmas = 0
    for theorem in ordered:
        if theorem.premises == 0 and theorem.term >= 0:
            goals.append(theorem)
            formula = certify.abstract(arena, theorem.term, atoms)
            certificate = certify.certify(formula, theorem.label, library)
            if certificate is None:
                unreached += 1
                if not library.usable(formula.atoms()):
                    without_lemmas += 1
            else:
                certificates.append(certificate)
        lemma = certify.as_lemma(arena, theorem, atoms)
        if lemma is not None:
            library.add(lemma)
    print(f"{len(corpus.theorems)} theorems; {library.size} became lemmas")

    tautologies = [c for c in certificates if c.tautology]
    from_library = [c for c in certificates if not c.tautology]
    print(
        f"certified {len(certificates)}/{len(goals)} "
        f"({len(tautologies)} by truth table, {len(from_library)} needing the library)"
    )
    print(f"  of the {unreached} not reached, {without_lemmas} had no usable lemma")

    rng = random.Random(arguments.seed)
    generators = corpus.closed_theorems()

    # Control 1: the negation of every goal certified above. Each is the negation
    # of a theorem, so certifying one would mean the library proves both a
    # statement and its negation.
    refuted = 0
    by_label = {t.label: t for t in goals}
    for certificate in certificates:
        theorem = by_label[certificate.label]
        negated = certify.Formula(
            op="wn", args=(certify.abstract(arena, theorem.term, atoms),)
        )
        if certify.certify(negated, theorem.label, library) is not None:
            refuted += 1

    # Controls 2 and 3: the experiment's own fragment, where provability is known
    # by construction — the refutable half must never certify, and the provable
    # half is a floor on recall for formulas built to be reachable.
    fragment = formulas.generate(
        arena, generators, count=arguments.controls, rng=rng
    )
    wrong = 0
    recovered = 0
    for compound in fragment:
        formula = certify.abstract(arena, compound.term, atoms)
        certificate = certify.certify(formula, "control", library)
        if compound.provable:
            recovered += certificate is not None
        else:
            wrong += certificate is not None

    # Control 4: the *negations* of the refutable half, which are theorems.
    negations = 0
    refutable = [c for c in fragment if not c.provable]
    for compound in refutable:
        formula = certify.Formula(
            op="wn", args=(certify.abstract(arena, compound.term, atoms),)
        )
        negations += certify.certify(formula, "control", library) is not None

    section_of = {t.label: t.section.split("/")[-1] for t in goals}
    attempted = Counter(section_of[t.label] for t in goals)
    succeeded = Counter(section_of[c.label] for c in certificates)
    by_section = [
        {
            "section": name,
            "goals": attempted[name],
            "certified": succeeded[name],
            "rate": succeeded[name] / attempted[name],
        }
        for name in sorted(attempted, key=lambda n: -succeeded[n])
        if succeeded[name]
    ]
    examples = [
        {"theorem": c.label, "lemmas": list(c.lemmas), "atoms": c.atoms}
        for c in sorted(from_library, key=lambda c: (len(c.lemmas), -c.connectives))[:15]
    ]

    results = {
        "corpus": {"theorems": len(corpus.theorems), "systems": corpus.systems},
        "walk": {
            "lemmas": library.size,
            "goals_without_hypotheses": len(goals),
        },
        "certified": {
            "total": len(certificates),
            "rate": len(certificates) / len(goals) if goals else 0.0,
            "by_truth_table": len(tautologies),
            "needing_the_library": len(from_library),
            "not_reached": unreached,
            "not_reached_with_no_usable_lemma": without_lemmas,
            "mean_lemmas_when_needed": (
                sum(len(c.lemmas) for c in from_library) / len(from_library)
                if from_library
                else 0.0
            ),
        },
        "controls": {
            "negations_of_certified_goals": refuted,
            "refutable_compounds_certified": wrong,
            "refutable_compounds_tested": len(refutable),
            "provable_compounds_certified": recovered,
            "provable_compounds_tested": len(fragment) - len(refutable),
            "negations_of_refutable_certified": negations,
        },
        "certified_by_section": by_section[:15],
        "examples_needing_the_library": examples,
        "runtime_seconds": time.time() - started,
    }
    print(json.dumps(results["controls"], indent=1))
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "certification.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {arguments.out / 'certification.json'}")


if __name__ == "__main__":
    main()
