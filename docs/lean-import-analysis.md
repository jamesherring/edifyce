# Importing Lean: analysis

**Status:** analysis only — nothing is built, and the recommendation is that the
largest of the three tiers below is deliberately **not** built. Tier 0 (statements
as a corpus) is small and worth doing; Tier 1 (Lean as a source for the ingestion
pipeline) is the interesting one and is already this project's stated direction
(`authoring-and-ingestion-roadmap.md` §4); Tier 2 (Edifyce's kernel re-verifying
mathlib) is refused, with the reason recorded here so it is not relitigated.

The question this answers: mathlib4 is a very large corpus of machine-checked
proofs under a permissive licence. Metamath's `set.mm` was imported and every one
of its 47,546 theorems re-verified by Edifyce's own kernel. Can the same be done
for Lean?

The short answer is that "import" means three different things, and only the
smallest two of them survive contact with the kernel. **The `set.mm` import
worked because Metamath's checking semantics *are* Edifyce's checking semantics.
Lean's are not, and the gap is not one of scale or effort — it is the difference
between substitution into a schema and deciding definitional equality in a
dependent type theory.**

All measurements below are from a shallow clone of
`leanprover-community/mathlib4` at `d77ef0741c6da1ff12df68fb4145ea0ae0850c54`
(2026-08-20). They are line-based counts over *source*, not over an elaborated
environment, so they undercount generated declarations (see §1.1) and should be
read as orders of magnitude rather than exact figures.

---

## 1. What is there

### 1.1 The library, measured

| | |
|---|---|
| `.lean` files under `Mathlib/` | 8,351 |
| lines | 2,299,205 |
| line-initial `theorem` | 125,930 |
| line-initial `lemma` | 53,339 |
| `def` / `instance` / `abbrev` | 32,112 / 27,144 / 3,589 |
| `structure` / `class` / `inductive` | 1,770 / 1,973 / 348 |
| `@[… to_additive …]` attributes | 16,067 |
| `sorry` | 138 |
| licence | Apache-2.0 |

Two caveats that matter for any pipeline.

**The source undercounts the library.** `to_additive` alone generates ~16,000
declarations that appear nowhere in the text, and `simp`/`ext`/`derive` machinery
generates more. The declaration count in a *built* environment is substantially
higher than 179,269. A pipeline that reads `.lean` files reads less than a
pipeline that reads an export.

**Mathlib declares essentially no axioms of its own.** The classical basis —
`propext`, `Classical.choice`, `Quot.sound` — is core Lean's, not Mathlib's. That
is a genuine point of similarity with `set.mm`, whose primitive basis the import
narrowed to 130 statements; the difference is that Lean's three sit on top of a
type theory rather than beside a first-order one.

### 1.2 The three altitudes it is available at

| altitude | tool | what you get | verification value |
|---|---|---|---|
| **kernel** | [`lean4export`](https://github.com/leanprover/lean4export) | NDJSON: an integer-indexed, hash-consed DAG of `Name`/`Level`/`Expr`, then declarations (`axiom`, `def`, `thm`, `opaque`, `quot`, `inductive` + constructors + recursors). A `thm` carries `value` — the **complete elaborated proof term**. | total, and unusable by us (§2) |
| **tactic** | [LeanDojo](https://github.com/lean-dojo/LeanDojo) Benchmark 4 | 122,517 theorems/proofs, 259,580 tactics, 167,779 premises, with proof states and name-resolved premises. Built for ML. | none — a tactic is a program, not a derivation |
| **statement** | doc-gen4 declaration data; HF mirrors | names, signatures, docstrings, dependency edges | none, but this is what Tier 0 and Tier 1 actually consume |

The kernel altitude is the only one that carries proof; the statement altitude is
the only one we can act on. That inversion is the whole finding.

---

## 2. Why this is not the Metamath import

### 2.1 What made `set.mm` fit

A Metamath `$p` proof is a sequence of applications of previously proved
assertions, each discharged by **substitution into a schema**, constrained by
`$d` distinct-variable provisos. That is, essentially one-to-one:

- schema application → `kernel/unify.py`'s first-order `match`
- `$d` → `kernel/side_conditions.py`'s `DisjointLeaves`
- a cited step → a `ProofLine` with a rule and antecedents

Nothing had to be invented. The importer (`website/logical/metamath/`, 5,132
lines) is a parser, a compressed-proof decoder and a great deal of bookkeeping —
it added **no trust**. Every one of the 47,546 proofs was emitted and then checked
by the same kernel that checks a hand-authored proof, in 24 min 17 s and 3.6 GB
(`metamath-import-roadmap.md` §1.1).

### 2.2 What Lean asks for instead

Checking a Lean proof term requires, at minimum:

- `Expr.app`, `lam`, `forallE`, `letE`, `proj`, `sort`, `lit` — hence beta, eta,
  eta-for-structures, zeta
- universe levels with `max`/`imax`, and their normalisation and unification
- delta with reducibility hints; iota on recursors; quotient reduction
  (`Quot.lift`, `Quot.ind`); proof irrelevance
- inductive families, mutual and nested inductives, derived recursors,
  well-founded recursion compiled through `WellFounded.fix`
- accelerated `Nat`/`String` literal arithmetic, or the corpus does not terminate
- and, above all, **definitional equality as a decision procedure**

Edifyce's kernel offers `Var`, `Bound` (de Bruijn) and
`Node(constructor, named_children)` (`kernel/terms.py`), plus first-order matching
— `unify.py`'s docstring is explicit that full two-sided unification is out of
scope — and there is no application or beta anywhere in the trusted core.

### 2.3 The representation maps; the checking does not

This is worth stating because the near-miss is genuinely close and will tempt
someone. `lean4export`'s output is an integer-indexed, hash-consed DAG of
expression nodes — structurally *the same idea* as `kernel/terms.py`'s `intern`,
down to maximal sharing and the DAG-not-tree framing. Reading an export into
Edifyce-shaped storage is not the hard part. It is not the part that matters
either: what an export needs is a checker, and the checker is the thing we do not
have and should not grow.

**The tempting shortcut, and why it fails.** "Model Lean's type theory *as* an
Edifyce formal system — the typing rules become inference rules, a proof term
becomes a derivation." The typing rules would go in fine; they are schematic.
Conversion would not. `Γ ⊢ a ≡ b` is not a schema that matches, it is a recursive
algorithm with heuristics for when to unfold. The only place in the kernel that
could host it is `side_conditions.py`, whose vocabulary — `Occurs`,
`DisjointLeaves`, `IsAtom`, `IsMember`, `Equal`, `Not`, `And`, `Or` — is closed on
purpose. Installing a conversion checker there is installing a Lean kernel inside
the trusted core, which is precisely what `terms.py`'s "the kernel hard-codes no
logic" invariant exists to prevent. It would also be the largest single addition
to the trusted base in the project's history, to check a corpus that is already
checked.

For scale: [Lean4Lean](https://arxiv.org/abs/2403.14064) is the first complete
Lean 4 typechecker besides the C++ reference implementation, is a multi-year
research effort, and runs 20–50% slower than the original. That is the size of
the object being proposed, and it is proposed as a *second* trusted core beside
ours, not an extension of it.

### 2.4 The half of mathlib that looks easy, and is not

A line-based classification of the 179,269 `theorem`/`lemma` bodies splits them
almost evenly: **88,612 tactic-mode, 90,203 term-mode** (454 undetermined). The
term-mode half is mostly one-liners — a single lemma application, an `Iff.rfl`, a
`to_additive`-style forward:

```lean
theorem trailingDegree_one : trailingDegree (1 : R[X]) = (0 : ℕ∞) :=
  trailingDegree_C one_ne_zero

theorem coe_inclusion (m : N) : (inclusion h m : M) = m :=
  rfl
```

The first looks exactly like a cited step with one antecedent. It is not one: the
implicit and instance arguments that make it typecheck are supplied by
elaboration, and reconstructing them is the elaborator's job, not a matcher's.

The second is worse. A `rfl` proof is *entirely* a definitional-equality check —
the one judgement Edifyce's kernel has no notion of at all — and there are
**11,179** declarations whose whole body is `:= rfl` or `:= Iff.rfl`, plus
**14,399** lone `rfl` continuation lines (a mix of term proofs written over two
lines and tactic blocks that a `rfl` closes, which is the same check either way).
So the population that most resembles a step-structured proof is the population
whose content is exactly the thing we cannot check.

**Conclusion of §2:** there is no version of this in which Edifyce's kernel
re-verifies mathlib. Any pipeline that ships must be honest that what it carries
is *Lean's* verification, attested, not ours.

---

## 3. What could be built

### Tier 0 — statements as a corpus

Ingest declaration names, statements, docstrings and the dependency graph; index
them for search and retrieval. No verification claimed, none implied.

Cheap, no engine reach, and it makes the search layer aware of the largest formal
library in existence — useful on its own terms and useful as retrieval context
for Tier 1.

### Tier 1 — Lean as an *ingestion source*

This is the one that is already on the roadmap.
`authoring-and-ingestion-roadmap.md` §4 names the destination as "proofs from
PDFs, arXiv and **Lean**, translated onto the imported ZFC base, with an LLM
assisting the translation". Lean is a much better source for that pipeline than a
paper is:

| the outer loop's problem | from a PDF | from Lean |
|---|---|---|
| segmentation | hard | free — declarations are the segments |
| ambiguous notation | severe (`informal-source-ingestion-roadmap.md` §1) | absent — everything is name-resolved |
| dependency order | must be reconstructed | free — the import graph is the order |
| "by Lemma 2.1 of [7]" | may not exist anywhere | always a resolvable name |
| **fidelity** | unchecked | **still unchecked** |
| **alignment** | unchecked | **still unchecked, and structurally harder** |

The last two rows are the point. Lean removes the mechanical problems and leaves
the two judgements that were never mechanical — and alignment is *harder* here
than for a paper, because the foundations genuinely differ. A mathlib theorem
about a typeclass-polymorphic `Group`, a `Finset`, or a quotient has no literal
ZFC statement; someone chooses the reading, and the choice is a reading of
mathematics.

**The honest representation already exists.** An imported mathlib statement is
exactly what `informal-source-ingestion-roadmap.md` §4.1 built: an assumption —
`primitive` set, `proved_by_id` NULL, with a debt row in `app/db/assumptions.py`
recording `reason` ("imported from mathlib4, verified by Lean, not by us") and
`source` (the declaration's fully-qualified name and commit). Provenance closure
then reports, from rows, exactly which imported statements any downstream proof
rests on — and §4.1's *discharge* path means proving one later retires the debt
and rewrites the closure without a new endpoint. The design already knows where
these belong.

### Tier 2 — kernel-level re-verification — **refused**

Recorded so it is not reopened. It requires a Lean typechecker (§2.2), which
would sit beside the Edifyce kernel as a second trusted core rather than inside
it; Python at mathlib scale is not credible when 47.5k first-order proofs cost
24 minutes; and the result would be a second, slower verification of a corpus
that CI already verifies on every commit. The value delivered over Tier 0 is a
green tick that a user has no reason to trust more than Lean's own.

If it is ever revisited, the shape is: an external checker in a compiled
language, consuming `lean4export` NDJSON, reporting a verdict that Edifyce
*records as an attestation* — which is Tier 0 plus a stronger `reason` string,
not a change to the kernel.

---

## 4. What Tier 0 + Tier 1 would take

| piece | shape | notes |
|---|---|---|
| **extraction** | `lake exe cache get` then `lean4export`, or take LeanDojo's prebuilt benchmark | building mathlib is hours of CPU and tens of GB; the prebuilt route avoids it and is sufficient for statements + premise graph |
| **statement reader** | read a `thm`'s `type`, ignore its `value` | the export DAG's integer indices map onto `kernel.terms.intern`'s sharing; only the type is needed |
| **target system** | either a new `SystemSpec` whose grammar spells Lean's surface syntax (statements parse and render; nothing is checked), or the imported ZFC base with translation on top | the first is mechanical; the second is the actual project |
| **storage** | `TheoremSpec` + `promote_from_source` (`website/logical/promotion.py`) + `app/db/assumptions.py` | mirrors `scripts/import_metamath.py` / `metamath/corpus.py`'s `walk` |
| **cross-foundation citation** | `website/logical/translation.py`, `wrapping.py` | already exists; a Lean-sourced statement need not live in the system its prerequisites do |
| **licence compliance** | attribution + NOTICE | see §7 |

---

## 5. What stays out

**A Lean elaborator.** Nothing in Tier 0 or Tier 1 reconstructs implicit or
instance arguments. Where a statement's meaning depends on them, the statement is
carried as *text plus a name*, and the translation is the consumer's judgement —
recorded, attributed, refutable. The moment a pipeline starts inferring instance
arguments to make a term compose, it has become an elaborator with none of the
guarantees.

**A tactic interpreter.** LeanDojo's 259,580 tactics are programs. Replaying them
requires Lean. They are useful as *evidence about what a proof does* for a model
reading them; they are not a proof format we can consume.

**A second kernel**, permanently (§2.3, Tier 2).

---

## 6. Sequencing

| | why here |
|---|---|
| 1. **Licence position settled** (§7) | it gates whether any derived corpus may land in the database at all; cheapest thing to get wrong late |
| 2. **Tier 0 — statement corpus + index** | small, no engine reach, and it is the retrieval context Tier 1 runs on |
| 3. **Tier 1 — imported statements as assumptions with provenance** | reuses §4.1's machinery unchanged; produces the first artifact that could misreport what it rests on, so it must land behind the honesty machinery, not beside it |
| 4. **Tier 1 — translation onto the ZFC base** | the real work, and the first thing that needs a consumer with judgement |
| ~~5.~~ **Tier 2** | refused (§3) |

### Foreclosure check

The test the previous three roadmaps applied. Does starting at Tier 0 foreclose
anything? No. Statements stored with their source name and commit are exactly the
input Tier 1 needs, and exactly the input a Tier 2 attestation would attach to.

The reverse is not safe, and it is the specific risk this document exists to name:
**an imported mathlib statement that lands as anything other than a recorded
assumption is a laundered verification.** It would read, from rows, as a theorem
this system holds — when what actually happened is that a different system, on a
different foundation, checked a statement someone translated by eye. That is the
failure the informal-ingestion roadmap's §1 calls the worst class precisely
because it is invisible. The insurance is the same one already taken out: **no new
path may create a citable entry whose warrant is not recorded.**

---

## 7. Licensing

`set.mm` is public-domain; mathlib4 is **Apache-2.0**. Redistributing derived
statement data therefore carries attribution and NOTICE obligations the Metamath
import did not, and Edifyce itself is MIT. This is not an obstacle — Apache-2.0 is
permissive and compatible downstream — but it is a decision to take deliberately
before a corpus lands, covering: where the NOTICE lives, whether per-declaration
attribution is stored on the row (it should be: the assumption's `source` field is
already the right place), and what a served API response says about provenance.

---

## References

- [`leanprover-community/mathlib4`](https://github.com/leanprover-community/mathlib4)
- [`leanprover/lean4export`](https://github.com/leanprover/lean4export) and its
  [NDJSON format spec](https://github.com/leanprover/lean4export/blob/master/format_ndjson.md)
- [LeanDojo](https://github.com/lean-dojo/LeanDojo) — Benchmark 4
- Carneiro, [*Lean4Lean: Verifying a Typechecker for Lean, in Lean*](https://arxiv.org/abs/2403.14064)
- [`metamath-import-roadmap.md`](metamath-import-roadmap.md) — the import this is measured against
- [`authoring-and-ingestion-roadmap.md`](authoring-and-ingestion-roadmap.md) §4 — where Lean is already named
- [`informal-source-ingestion-roadmap.md`](informal-source-ingestion-roadmap.md) — fidelity, alignment, assumptions, discharge
