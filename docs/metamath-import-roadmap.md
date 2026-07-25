# Metamath import: roadmap

**Status:** the import exists as a working vertical slice; this note records where
it stands, the design decisions taken (so they are not relitigated), and what
remains before a bulk `set.mm` import.

Companions: [`setmm-import-and-proof-altitude.md`](setmm-import-and-proof-altitude.md)
(why Metamath proofs are verbose, and the A1–A5 / B1–B6 recommendations) and
[`setmm-import-recommendations-detail.md`](setmm-import-recommendations-detail.md)
(each recommendation with worked examples). This file is the forward-looking plan;
those two are the analysis behind it.

---

## 1. Where the import stands

`website/logical/metamath/` — `parser` → `compressed` → `importer`.

| Piece | State |
|---|---|
| `.mm` reader (`$c $v $f $e $a $p $d`, `${ $}`, `$( $)` comments) | done |
| Mandatory-hypothesis computation (declaration order) | done |
| Compressed-proof decoder (base-20/5 letters, `Z` saves, three bands) | done |
| Grammar built from syntax `$a` statements | done |
| Logical assertions promoted as citable theorems | done, but see §2.2 |
| Proof emission + kernel check | done |
| `$t` typesetting / notation | **§3 — next** |
| Axiom-vs-theorem split | **§2.2 — blocker** |
| Definition classification (`df-*`) | **§4.2 — not a blocker, but front-load** |
| Scale | **§4.3 — unmeasured** |

`tests/test_metamath_import.py` imports `sqrt2re` from its verbatim `set.mm` proof
string and has Edifyce's kernel check the result:

```
2 e. RR [2re]
0 < 2 [2pos]
( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]
```

Four stored steps become three lines — `c2` is a *syntax* step, and Edifyce parses
well-formedness rather than proving it. A tampered conclusion is rejected, so a
green import is evidence rather than assumption.

---

## 2. What formal system an import produces

### 2.1 Not a pre-built ZFC — and not Edifyce's ND ZFC

The importer **synthesises the system from the `.mm` file itself**: the grammar
comes from the syntax `$a` statements, nothing is pre-supplied. For the `sqrt2re`
fragment that is 8 productions and *zero* inference rules.

A full `set.mm` import yields ZFC+FOL **as set.mm axiomatises it — Hilbert-style**:
`ax-1`/`ax-2`/`ax-3` + `ax-mp`, then `ax-gen`/`ax-4`…`ax-13`, then `ax-ext`,
`ax-rep`, `ax-pow`, `ax-un`, `ax-reg`, `ax-inf`, `ax-ac`.

That is **a different system from `tests/zfc_systems.py`'s `SCOPED_ZFC`**, which is
natural deduction with real subproofs and discharge. The consequence matters and
should not be forgotten: imported proofs *keep* their deduction-form plumbing
(`syl`, `adantr`, `simp*`), because in a Hilbert system that plumbing is load
bearing. Moving them to ND form is a separate translation — essentially the B5
idiom re-abstraction work, not something the importer does for free.

### 2.2 The axiom-vs-theorem split (blocker)

`promote_assertions` currently promotes **every** logical assertion, including the
`$a` axioms. That erases exactly the distinction `promoted_theorems` was built to
preserve: a system's *primitive* rules versus its *derived* results.

`ax-mp` is the clearest case — it is literally an inference rule:

```
${  min $e |- ph $.   maj $e |- ( ph -> ps ) $.   ax-mp $a |- ps $.  $}
```

**The split to make:** logical `$a` → the system's `inference_rules` (they define
it); `$p` → `promoted_theorems` (they are derived). Until then an imported system
cannot answer "what are your axioms?", and the namespace separation does no work.

---

## 3. Notation and typesetting

### 3.1 Decision: separate source from display

**Source and display are separate layers**, as in Metamath — *not* LaTeX stored as
the logical source.

The deciding argument is where failures land. A **display** collision (two tokens
render alike) is cosmetic: the proof still checks. A **grammar** collision (two
tokens *parse* alike) is a correctness bug: the checker cannot tell them apart.
Storing LaTeX as source converts every cosmetic problem into a correctness one.
LaTeX is also a poor canonical form — `\left(` vs `(`, optional braces,
discretionary spacing, competing macros for one symbol — so it would import a
normalisation problem that otherwise does not exist.

Two further reasons:

- **One source, many renderings.** `set.mm` ships *three* maps (`latexdef`,
  `htmldef`, `althtmldef`). Separation gives LaTeX (papers), Unicode (terminal,
  plaintext, diffs), MathML/HTML (web) and screen-reader text from one checked
  source; LaTeX-as-source forecloses the alternates.
- **Generality.** Edifyce targets *any* formal system. MIU, semi-Thue systems and
  propositional Hilbert systems have no use for LaTeX; presentation does not
  belong in the logical layer.

Edifyce already models this: `StringPattern` carries `display_pattern` /
`display_variables` beside its matching pattern.

### 3.2 Decision: Unicode as the imported source

Metamath's ASCII (`e.`, `A.`, `->`) is a 1990s constraint and is *less* readable
than Edifyce's existing idiom, which already writes `(p → q)`, `x ∈ y`, `∀x p` as
source. So an import uses:

- **source** = Unicode, from `set.mm`'s `althtmldef` (`∈`, `ℝ`, `√`, `∀`, `→`)
- **display** = LaTeX, from `latexdef` (`\in`, `\mathbb{R}`, `\surd`)

Both maps are authored by the `set.mm` maintainers in its `$t` block (1818
`latexdef` entries), so neither is hand-invented — the "best-effort, re-sync as we
learn" workflow starts from the authoritative source rather than from scratch.

Unicode-as-source also *shrinks* the collision surface, since Unicode symbols are
near-1:1 with Metamath tokens whereas LaTeX's `\mathrm{…}` wrappers collide
readily. A collision/unmapped-token report is still wanted (§3.4).

### 3.3 Decision: render by folding kernel terms, not `Match` trees

The renderer walks the **kernel `Term` graph**, not the matching layer's `Match`
tree. The mechanism already exists: `Node.to_string()` walks a production's
template emitting literal chunks and recursing into `children`. A display render
is that same fold with `display_pattern` in place of `pattern`.

Why the term graph:

- **`Node` retains what rendering needs** — `pattern` (the constructor, so the
  display template is reachable), `children` as `{slot_label: Term}` keyed by the
  production's own variable slots (so placeholders resolve directly), `literal`
  for ground leaves.
- **Terms are canonical.** `from_match` collapses union-coercion wrappers, so a
  formula has one term however many union layers parsed it. Folding a `Match`
  means walking scaffolding with no mathematical content.
- **Terms exist where matches do not** — and this is decisive. A rule schema
  (`schema_term`), a promoted theorem's statement, a definition's higher/lower
  forms: all are terms with no `Match`. Match-based rendering would cover proof
  lines and nothing else, leaving no way to display a rule, an imported theorem's
  statement, or an instantiated schema. The frontend will want all of those.
- Interning means shared subterms are physically shared, so rendering memoises.

**Constraints to respect when building it:**

- **The renderer lives outside the kernel.** The kernel's virtue is that it
  hard-codes no logic and stays small; LaTeX is presentation. `to_string` is
  defensible *in* the kernel (source round-tripping is a term-layer concern), but
  a display renderer belongs in a presentation module that *reads* terms. No new
  coupling either way: `Node.pattern` is already a `matching.Pattern`.
- **Canonical ≠ verbatim.** Rendering from the term gives the canonical form,
  which may differ from what an author typed (redundant brackets normalised,
  coercions gone). Usually desirable; but a verbatim echo must come from the
  stored source string, not the term.
- **Definition-backed nodes** use `defn.higher` as their constructor, so display
  templates key on *patterns generally*, not productions only.
- `to_string` reaches for `getattr(pattern, "pattern", None)` probes. The repo's
  guidance discourages that idiom; the new renderer should dispatch on pattern
  type rather than copy it.

### 3.4 Beyond per-token substitution

A per-token map yields token-soup LaTeX (`( \surd \` 2 ) \in \mathbb{R}`). Because
Edifyce has the parse tree, each production can instead carry its own display
template:

| production | source template | display template |
|---|---|---|
| `wcel` | `A ∈ B` | `{A} \in {B}` |
| `cfv` | `( F \` A )` | `{F}\left({A}\right)` |
| `csqrt` + `cfv` | `( √ \` A )` | `\sqrt{A}` |

giving `\sqrt{2} \in \mathbb{R}` rather than soup. The `$t` map seeds most of it
automatically; overrides are applied per production where the naive rendering is
poor. Ship a report of unmapped tokens and colliding renderings so re-syncing is
driven by a list rather than by discovering breakage.

---

## 4. Remaining work before bulk import

### 4.1 A3 — statement mapping (blocker)

Mostly done in the parser. What remains:

- **the axiom-vs-theorem split** (§2.2) — the real gap;
- the `$t` block (§3);
- typecodes beyond `wff`/`class`/`setvar`;
- `$[ … $]` file inclusion — low priority, `set.mm` is self-contained.

### 4.2 A4 — definition classification (not a blocker; front-load anyway)

Importing every logical `$a` as an axiom still yields **fully verifiable** results
— that is exactly what Metamath does, relying on an *external* definitional
soundness checker. What is given up:

- conservativity-by-construction, which Edifyce's `Define` supplies for free;
- definitional steps `[Def, n]`. Without them a proof cites the biconditional as
  an axiom and reasons propositionally — sound, but longer.

So it does not block a bulk import. **But do it early**: reclassifying afterwards
means re-importing everything, so it is far cheaper before than after. Default on
"does not reduce to fold/unfold" must be *axiom + flag*, never a silent `Define`,
or conservativity is lost quietly.

### 4.3 A5 — scale (unmeasured)

~40 000 theorems, 51 MB, proofs hundreds of steps deep. Two risks, neither yet
measured:

- the notation matcher is a hand-written backtracking string matcher with a
  `certainty` heuristic — validate at `set.mm` grammar size, and prefer the
  declarative/precompiled build path for bulk import;
- 40 000 promoted theorems must resolve fast — index by conclusion head symbol so
  a citation resolves against a handful of candidates, and exercise the
  antecedent-assignment and unification paths at library scale.

Correctness on a dozen theorems says nothing about wall-clock on forty thousand.

---

## 5. Sequencing

1. **`$t` + Unicode source + term-fold renderer** (§3) — wanted now, and it is
   also part of A3.
2. **Axiom-vs-theorem split** (§2.2) — the modelling blocker.
3. **A4 definition classification** — cheaper before bulk than after.
4. **A5 benchmarks**, in parallel from step 2 onward.
5. **Widen the slice**: `sqrt2irr` and its dependency closure — the first target
   large enough to hurt.
6. Then the altitude work (B1–B6) from the companion notes: the tactic framework
   and closure solver first, since they shorten *new* proofs as well as imported
   ones.

The throughline is unchanged from the analysis: keep the property that makes
Metamath trustworthy — a small kernel checking a fully primitive object — and add
the elaboration and presentation layers Metamath deliberately omitted.
