# Metamath import: analysis and roadmap

**Status:** whole corpus imported and checked — 47,546 theorems, 97.8% verifying.
The remaining 2.2% is characterised in §1.1, and is import defects, not
unprovable mathematics.

Goal: import Metamath's `set.mm` while keeping **full verifiability** and **full
generality** (Edifyce stays a general proof assistant — any formal system, not a
hard-wired ZFC), *and* let humans read and write proofs at the altitude
mathematicians actually use.

This note is the single reference for that work: where the import stands, why
imported proofs look the way they do, the design decisions taken (recorded so they
are not relitigated), and what remains.

---

## 1. Where the import stands

`website/logical/metamath/` — `parser` → `compressed` → `importer`.

| Piece | State |
|---|---|
| `.mm` reader (`$c $v $f $e $a $p $d`, `${ $}`, `$( $)` comments) | done |
| Mandatory-hypothesis computation (declaration order) | done |
| Compressed-proof decoder (base-20/5 letters, `Z` saves, three bands) | done |
| Grammar built from syntax `$a` statements | done |
| Schematic theorem application (§5, A1) | done |
| Logical assertions promoted as citable theorems | done, but see §3.2 |
| Proof emission + kernel check | done |
| Proofs *under* `$e` hypotheses (`import_theorem`) | done |
| Whole-corpus ordered pass (§1.1) | done — 47,546 checked, 46,520 verify |
| Persisting the parse (§1.3) | done — one system, proofs, lines, terms |
| Scale (§5, A5) | **measured** — 23 min, 3.0 GB (§1.1) |
| Token-collision defects (§1.2) | **open** — 32 theorems, two causes, both ours |
| `$t` typesetting / notation (§4) | **next** |
| Axiom-vs-theorem split (§3.2) | **blocker** |
| Definition classification (§5, A4) | not a blocker; front-load |

`tests/test_metamath_import.py` imports `sqrt2re` from its verbatim `set.mm` proof
and has Edifyce's kernel check the result:

```
2 e. RR [2re]
0 < 2 [2pos]
( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]
```

A tampered conclusion is rejected, so a green import is evidence, not assumption.
Two properties make that claim hold, both enforced:

- **the proof must reach the declared statement.** A proof that terminates on some
  other well-formed result would otherwise import cleanly and check, while the
  theorem was still promoted under what it claimed;
- **a theorem is checked against only what precedes it.** `import_theorem` builds a
  per-theorem system promoting earlier assertions only, and registers that
  theorem's own `$e` hypotheses as givens — Metamath's `${ … $}` scoping. Without
  the first half a theorem justifies itself; without the second, a proof under
  hypotheses cannot be stated at all.

`import_database` (the whole library, everything promoted) remains the right view
for browsing, but `import_theorem` is the entry point for *checking* a proof.

### 1.1 The whole corpus

One ordered pass over `set.mm`: walk the file, add each syntax axiom to the
grammar as it is declared, check each theorem against only the notation and
theorems that precede it, then promote it. Every proof is emitted from its stored
compressed proof and checked by Edifyce's own kernel.

| | |
|---|---|
| theorems checked | 47,546 |
| verified | **46,520 (97.8%)** |
| rejected by the kernel | 1,026 |
| failed to promote | 32 |
| wall clock | 23 min 12 s |
| peak memory | 3.0 GB |

Cost is `check` 1,132 s, `promote` 218 s, `emit` 41 s. Per-theorem cost grows with
the grammar, which reaches 1,441 productions: 2.7 ms/theorem over the first 5,000,
28.8 ms/theorem by 45,000.

Two caveats on what that number means. The *variable-sort* leaves are seeded at
whole-database scope rather than grown with the walk — much weaker than the
notation ordering (a variable leaf admits more names; it adds no constructor that
could capture a parse), but not the strict discipline. And all 1,433 `df-`
statements are still imported as axioms (§3.2, A4), so this verifies `set.mm`
against a larger primitive basis than a faithful import would use.

### 1.2 Why the rejections happen

The 32 promotion failures have two root causes, both **defects on our side**, and
both the same shape: a `set.mm` constant token containing a character Edifyce
reads structurally. This is the third instance of that shape — the first was the
class variable `A` found inside the quantifier `A.`, fixed by renaming the
production's variable (`_uncollide`).

**A variable named `.,` breaks a `$d` proviso (17 theorems).** `set.mm` spells its
inner product `.,`, and `_distinct_provisos` emits `disjoint(.,, x, setvar)` — the
comma *in the name* is indistinguishable from the argument separator, so the
side-condition parser refuses it. Exactly one declared variable contains a comma,
so the blast radius is small, but the fix is a quoting or escaping convention in
the proviso syntax rather than anything Metamath-specific.

**Interval notation defeats the bracket check (15 theorems).** `set.mm` declares
14 constants that contain a parenthesis — `[,)`, `(,]`, `(,)`, `(x)`, `O(1)`, `((`
among them. A statement mentioning one, such as `( 0 [,) +oo ) C_ RR`, fails
`check_brackets` outright: the `)` inside the token `[,)` is counted as a
delimiter, so the string reads as unbalanced and never reaches a parse. Confirmed
directly — `check_brackets` returns False on each failing statement.

Bracket parity is an optimisation (it prunes candidate splits), not a grammatical
rule, so the fix is to profile brackets over *tokens* rather than characters and
let a declared constant be opaque to the scan.

One rejection cause has since been removed. set.mm opens with **two theorems
declared before any syntax axiom** — `idi` and `a1ii`, both `|- ph` — and the
grammar had no sort to state them in, because the logical sort was read off the
syntax axioms alone. A `$f`-declared typecode is a sort in its own right (`wph $f
wff ph` makes a bare `ph` a wff), which is already what makes `setvar` a sort, so
`_logical_sort` now reads every production. Two theorems, and the first two an
ordered walk meets.

The 1,026 kernel rejections are **not yet diagnosed**. They are not uniform —
they cluster (299 in the 25,000s, 389 in the 45,000s) and are absent below 10,000
— which suggests a small number of causes tied to particular notation rather than
a broad soundness gap. A promotion failure *does* cascade (a theorem that never
promoted cannot justify a later citation of it), so the 32 above may account for
some share of the 1,026; a failed *check* does not cascade, since the harness
promotes regardless of the verdict.

### 1.3 The parse is now kept

The pass above threw its work away. Each run re-read the `.mm` file, rebuilt the
grammar, re-parsed every proof and stored none of it — while `terms` and
`proof_lines` sat empty, describing exactly that structure. That is closed:

`website/logical/metamath/corpus.py` is the ordered pass, checked in rather than
run ad hoc. `walk(database, limit)` yields one `CheckedTheorem` per theorem, and
`corpus_spec(database, limit)` is the grammar it ends with.
`app/db/metamath_store.py` drives it and writes, per theorem, the same rows a
verify through the API writes (`store_proof_lines`): a `proof_lines` row per
line with the theorem that justified it, `proof_line_antecedents` edges for the
lines it was derived from, and the line's formula interned into the system's
shared `terms` DAG. `scripts/import_metamath.py` is the CLI.

**One system row for the whole walk.** The grammar grows as set.mm declares
notation, but a term row is keyed by *constructor name* and interned per system,
so terms built under an early grammar and a late one share rows correctly as long
as the stored system is the union — which `corpus_spec` is. That is the point:
the corpus lands in **one** term graph, so a subterm shared by two theorems is
one row and the theorem search indexes them together.

On the first 1,000 theorems of set.mm:

| | |
|---|---|
| theorems checked | 1,000 |
| verified | **1,000 (100%)** |
| wall clock | 26 s (of which 3 s reading the 51 MB file) |
| `proof_lines` rows | 3,521, every one carrying a term |
| `proof_line_antecedents` edges | 2,539 |
| `terms` / `term_children` rows | 1,951 / 3,828 |
| on disk | 6 MB |

The 3,521 formula-bearing lines intern to **1,337 distinct statements**, so the
sharing is real rather than nominal. And the rows stand alone: rebuilding the
system from `systems` rows and reloading each stored term renders back the exact
formula its line states, for all 3,521 — with no `.mm` file, no importer, and no
re-parse.

**What is stored is the parse, not yet the means to repeat it.** A system row
holds a grammar, definitions, axioms and rules. It has nowhere to hold a
*promoted theorem* — and the Metamath library is 49,000 of them — so the stored
system is grammar-only, and re-parsing an imported proof against it fails on its
first citation (`Invalid reference: ax-mp`). The rows record a check that
happened; they are not yet enough to re-run it. That is **§3.2's** storage
decision, and this is its sharpest consequence: until it lands, an imported
`proofs.valid` is a claim its own `formal_system_id` cannot reproduce.

So an import is deliberately **ownerless and unpublished**. `POST
/proofs/{id}/verify` writes a verdict back only for `user is not None and
proof.owner_id == user.id`, and reads at all only for a published proof or its
owner — so no request can reach an imported proof, re-check it against the
grammar-only system, and have `_record_verdict` drop the imported structure via
`store_proof_lines`'s clear. The same reason it is not re-checkable is the reason
it must not be *offered* for re-checking. `test_metamath_persistence` pins both
halves, so §3.2 closing the gap is a visible change rather than a silent one.

Both of those — storing the library, and reading stored terms back instead of
re-parsing — are the subject of
[docs/verification-from-rows.md](verification-from-rows.md), which takes the
same question from the engine side rather than the import's.

A related consequence of the same split: a theorem is checked under
`before=label` but stored under the union grammar, which is exactly the
forward-notation capture `before` exists to prevent. It costs nothing today —
the stored *terms* come from the correct parse, and nothing re-parses — but it is
another reason an imported proof must not be handed back to the checker.

What the walk trades for that speed is the exactness of the grammar limit
*between* rebuilds. The system is rebuilt when a syntax axiom is declared, not
per theorem, so a run of theorems declaring no notation shares one grammar —
identical, since notation is what changes it. The variable leaves are the
exception: they grow with every statement, so they are seeded once at the far end
of the walk. That is the §1.1 caveat, now explicit in the signature
(`build_spec(..., variable_scope=)`) rather than implied.

The rebuild itself is the remaining scale question. Re-promoting the library
after each notation change is fine over a slice (five rebuilds and ~3,500
promotions over the first 1,000 theorems) and is `O(theorems × notation)` over
the whole corpus. Extending a live system's grammar in place — teaching a sort
union and its projected constructor to accept a new branch — would make it
linear, and is the natural next step if the whole corpus is to be stored.

---

## 2. Why imported proofs look the way they do

Context for everything below: the shape of the import, the persistence of
deduction-form plumbing in imported proofs, and the entire Tier B programme all
follow from this diagnosis.

### 2.1 The specimen

A mathematician's proof that √2 is irrational is about six lines. `set.mm`'s
`sqrt2irr` (plus its core lemma `sqrt2irrlem`) is a few hundred primitive steps
citing roughly **ninety distinct prior theorems** — `syl`, `zcn`, `nncn`,
`ad2antrr`, `2cnd`, `oveq1d`, `eqtr4d`, `simpl`, `jca`, `ralrimdva`, …

That gap is not sloppiness. It is the direct consequence of a few deliberate
design decisions.

### 2.2 The cost centres

| # | Source | Machinery it produces |
|---|---|---|
| 1 | **Foundational depth** — everything reduces to ZFC+FOL | `df-2`: `2 = ( 1 + 1 )`; `df-div`, `df-sqrt` as `iota` descriptors; `df-q`. Mostly amortised into the library, but nothing is free |
| 2 | **Untyped → closure plumbing** *(biggest visible cost)* | "A ∈ ℤ", "B ≠ 0" are propositions to prove and carry: `nncn`, `zcn`, `2cnd`, `nnne0`, … A typed system discharges these invisibly |
| 3 | **Deduction form by hand** | Every line is `( ph → … )`, the antecedent threaded manually: `syl`, `adantr`, `ad2antrr`, `simpl`/`simpr`, `jca` — pure context bookkeeping |
| 4 | **Congruence spelled out** | Rewriting inside a term needs a position-specific lemma: `oveq1d`, `oveq2d`, `fveq2d`, `breq2`, `eleq1d`, plus `eqtr*` glue |
| 5 | **Substitution-only kernel** | Even modus ponens is a theorem (`ax-mp`) invoked as a step; no native natural deduction |
| 6 | **No automation in the stored object** | What `ring`/`simp`/`norm_num` hide elsewhere, Metamath spells out |
| 7 | **No structural abstraction** | No "similarly", "WLOG", "by symmetry"; infinite descent is re-encoded as strong induction |
| 8 | **Variable bookkeeping** | Dummy variables, `$d` constraints, binders via schematic metavariables |
| 9 | **Presentation** | Even the web renderer is one primitive step per row. Reading is scrolling |

### 2.3 The one root cause

Almost all of it collapses to a single decision:

> **Metamath has no elaboration gap.** The proof a human authors, the proof the
> kernel checks, and the proof a reader sees are *the same maximally-expanded
> object.* That buys a tiny trusted verifier and total generality — at the price
> of forcing every human to work at kernel altitude.

So the design question is not "how do we make the kernel cleverer" (that costs
verifiability) but **"how do we open an elaboration gap without giving up
generality"** — a high-level surface that elaborates down to primitive,
kernel-checkable steps, with abstractions defined *relative to the user's formal
system* rather than baked in.

### 2.4 What Edifyce already solves

Several of those costs are not structural in Edifyce the way they are in `set.mm`:

| Cost | Edifyce today | Verdict |
|---|---|---|
| 1 definitional depth | first-class layered, capture-avoiding definitions with provisos; `[Def, n]` steps checked over kernel terms | **covered** — `df-*` map to definitions |
| 2 typing/closure | the engine is **sorted**; `member`/`atom` provisos test sort membership structurally | structure present, **automation absent** (B2) |
| 3 deduction form | **native scoped subproofs with discharge**, reiteration restriction and eigenvariable freshness enforced | **covered for new proofs** — no `syl`/`adantr` needed |
| 5 substitution-only | rules are schematic; substitution is *derived by unification*, not written | **covered** |
| 7 lemma reuse | cross-proof citation with transitive cycle-checking | partly (see A1) |
| 8 `$d` / freshness | `disjoint(x, φ, …)` **is** `$d`; `fresh` atoms are eigenvariables | **covered** — direct mapping |

The headline: Edifyce is **natural-deduction-native and sorted**, so the two
largest Metamath cost centres are not forced on newly authored proofs. What is
missing is the automation and presentation layers (Tier B).

### 2.5 One thing that vanishes for free

Roughly half the labels in a `sqrt2irr`-scale proof are `c*`/`w*`/`cv` — Metamath
*proving that the formula is well-formed*, because it has no parser. Edifyce has a
grammar, so **every one of those steps disappears on import**: well-formedness
becomes parsing, not a proof line. This is why the decoder must classify each
cited label as syntax-vs-logic, and why an imported proof is already meaningfully
shorter than the stored one before any Tier B work.

---

## 3. What an import produces

### 3.1 Not a pre-built ZFC — and not Edifyce's ND ZFC

The importer **synthesises the system from the `.mm` file itself**: the grammar
comes from the syntax `$a` statements, nothing is pre-supplied. For the `sqrt2re`
fragment that is 8 productions and *zero* inference rules.

A full `set.mm` import yields ZFC+FOL **as set.mm axiomatises it — Hilbert-style**:
`ax-1`/`ax-2`/`ax-3` + `ax-mp`, then `ax-gen`/`ax-4`…`ax-13`, then `ax-ext`,
`ax-rep`, `ax-pow`, `ax-un`, `ax-reg`, `ax-inf`, `ax-ac`.

That is **a different system from `tests/zfc_systems.py`'s `SCOPED_ZFC`**, which is
natural deduction with real subproofs and discharge. The consequence matters:
imported proofs *keep* their deduction-form plumbing (§2.2 item 3), because in a
Hilbert system that plumbing is load-bearing. Moving them to ND form is a separate
translation — essentially B5, not something the importer gets for free.

### 3.2 The axiom-vs-theorem split (blocker)

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

It now also owns a **storage** decision, which §1.3 made concrete. `inference_rules`
have a table (`rules`); `promoted_theorems` have none, so a stored import carries
its grammar and none of its library, and an imported proof cannot be re-checked
from its own rows. Sequencing this item behind §1.3 is deliberate — the shape of
what to store is exactly the question this item answers, and storing 49,000
derived theorems as `rules` would answer it wrongly, declaring every proved
theorem a primitive of the system.

---

## 4. Notation and typesetting

### 4.1 Decision: separate source from display

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

### 4.2 Decision: Unicode as the imported source

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
readily. A collision/unmapped-token report is still wanted (§4.4).

### 4.3 Decision: render by folding kernel terms, not `Match` trees

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
- **Terms exist where matches do not** — decisive. A rule schema (`schema_term`),
  a promoted theorem's statement, a definition's higher/lower forms: all are terms
  with no `Match`. Match-based rendering would cover proof lines and nothing else,
  leaving no way to display a rule, an imported theorem's statement, or an
  instantiated schema. The frontend will want all of those.
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

### 4.4 Beyond per-token substitution

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

## 5. The plan

Tier A is what a faithful import requires; Tier B is the human-altitude layer —
the actual goal — which can land after, but should be designed for now so the
import does not foreclose it. A guardrail runs through both: **every abstraction is
parameterised by the user's declared system**, never hard-coded, and everything
either produces primitive steps the existing kernel checks (the de Bruijn
criterion) or only re-renders an already-checked proof.

### Tier A — prerequisites

**A1. Schematic theorem application — *done*.**
A `set.mm` proof is ~90 applications of previously proved theorems, each
re-instantiated at the call site; Metamath makes no distinction between citing a
`$a` and a `$p`. What shipped: `PromotedTheorem` records a theorem's schematic
statement (conclusion, premises, metavariables, `$d` provisos, matching regime)
and `as_rule()` builds the *ephemeral* `InferenceRule` a citation is checked
against. `FormalSystem.promoted_theorems` keeps derived theorems out of
`inference_rules`, and `Proof.get_reference` resolves `[Thm]` / `[Thm, i, …]` per
citation — nothing per-theorem is persisted as a rule.
`compiler.promote_from_source` is the import-facing builder (`$e`→premises,
`$f`→metavariables, `$d`→distinct). Closed theorems (`2re`) and string-matching
regimes are supported, and `$d` is demonstrably load-bearing: an `ax-5`-shaped
theorem rejects the capturing instance with the proviso and *accepts* it without.

Two findings worth keeping, both of which contradicted a reasonable guess:
promotion is a **graph** operation (`from_match` → re-variabilise → schema shell;
the string-layer `create_pattern` is not on the path), and a schema with no
composed term is **not** automatically broken — defined notation composes none yet
applies fine, while only a *ground* compound needs its term composed explicitly,
at the system's declared **logical sorts**.

*Still open:* promoting a **natively-authored** Edifyce proof needs a
generalisation policy the importer gets free from `$f`/`$d` — which leaves are
general, what sort to widen to, and (the part with real soundness surface)
deriving `$d` from the proof's ∀I freshness steps. Deferred; imports never hit it.

**A2. Compressed-proof decoder — *done as a vertical slice*.**
The whole proof of `sqrt2re`:

```
sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
  ( c2 2re 2pos sqrtpclii ) ABCD $.
```

Label table `[c2, 2re, 2pos, sqrtpclii]`; `ABCD` selects entries 1–4. Executed on a
stack: `c2` builds the class `2` (**syntax** — no line emitted), `2re` and `2pos`
push `|- 2 e. RR` and `|- 0 < 2`, then `sqrtpclii` pops **three** entries — its
mandatory hypotheses are the floating `$f class A` *then* the two essentials, in
declaration order. The floating slot supplies the substitution (`A := 2`); the
essential slots become the cited lines. Wrong order or count silently misaligns
every application, so it is computed at parse time (`Assertion.mandatory`).

Four stored steps → three proof lines (§1). Imported notation stays Metamath's own
(`e.`, `` ` ``) until §4 lands, since the grammar is built from set.mm's syntax
axioms and its tokens *are* the surface syntax.

**A3. Statement mapping — *partly done; blocker***.
`$c`→terminals, `$v`→metavariable names, `$f`→sort bindings, `$e`→antecedents,
`$a`→axiom or definition, `$p`→proof + promoted theorem, `$d`→`disjoint` provisos,
`${ $}`→scope. The reader handles all of these. Remaining: **the axiom-vs-theorem
split (§3.2)** — the real gap; the `$t` block (§4); typecodes beyond
`wff`/`class`/`setvar`; `$[ … $]` inclusion (low priority, set.mm is
self-contained). Import faithfully as Metamath's own sorts first; a richer type
discipline risks needing to re-prove things and is best deferred.

**A4. Definition classification — *not a blocker; front-load anyway*.**
Not every `$a` is fold/unfold-shaped, and Metamath relies on an *external*
definitional-soundness checker. Importing every logical `$a` as an axiom is still
**fully verifiable** — it is exactly what Metamath does. What is given up:
conservativity-by-construction, which Edifyce's `Define` supplies for free, and
definitional steps `[Def, n]` (without them a proof cites the biconditional and
reasons propositionally — sound, but longer). Clean cases map directly
(`df-nel`: `A e/ B ↔ ¬(A ∈ B)`; `df-2`: `2 = (1+1)`); `df-div`/`df-sqrt` define via
`iota`, so route them through the `fresh`-aware path and keep their existence
lemmas as cited premises. Default on "does not reduce to fold/unfold" must be
*axiom + flag*, never a silent `Define`. Do it early: reclassifying after a bulk
import means re-importing everything.

**A5. Scale — *measured; no longer a risk*.**
The whole corpus checks in 23 minutes at 3.0 GB (§1.1). Both risks this item
named were real and are now addressed. The backtracking string matcher was the
dominant cost and was *exponential in nesting depth* — `cbvral8vw` (16 binders)
did not finish at all — until substring parses were memoised per parse; reading a
template by its declared slots rather than character by character then halved
what remained. Candidate productions are picked by the string's leading character
instead of trying every leaf, which is what stops cost growing with the grammar's
1,441 productions. Resolution of 49,000 promoted theorems never became the
bottleneck the item predicted; the parse did.

What remains is memory — 3.0 GB, growing roughly linearly with theorems promoted
— and the fact that per-theorem cost still rises with grammar size (2.7 ms early,
28.8 ms late). Neither blocks a bulk import; both would matter for a corpus
several times larger.

### Tier B — the human-altitude layer

**B1. Tactic / elaboration framework.** A tactic takes a goal + context and **emits
primitive proof lines**, which the kernel re-checks exactly as if hand-written. A
buggy tactic can fail to find a proof but cannot certify a false one. This is the
layer Metamath omits (§2.2 item 6); everything below plugs into it. Record the
elaboration tree (which surface step produced which substeps) for B4.

**B2. Closure / typing solver** — removes the largest visible cost (§2.2 item 2).
Backward-chain a goal like `(B / 2) ∈ ℂ` against a *declared* set of closure rules,
emitting the primitive steps. General because it is driven by declarations, not by
ℂ. Before/after:

```
12.  B ∈ ℂ           [nncn, 4]          →   12.  (B / 2) ∈ ℂ     by closure
13.  2 ∈ ℂ           [2cnd, …]
14.  2 ≠ 0           [2ne0]
15.  (B / 2) ∈ ℂ     [divcl, 12, 13, 14]
```

Same four checked lines underneath; one line to write and read.

**B3. `calc` chains + congruence tactic** — removes §2.2 item 4. The author writes
an equality/`↔` chain with one justification per step; the elaborator synthesises
the congruence lemma from *which argument position changed* (data the grammar
already has), plus the transitivity glue. Parameterised on a user-declared
congruence, so it generalises past `=`.

**B4. Zoomable presentation** — removes §2.2 item 9 and makes imports readable.
Store the elaboration/subproof tree; let the frontend fold to a sketch and drill
down to primitives. `sqrt2irr` as six foldable rows, full rigour one click away.
The subproof tree already provides the scaffolding.

**B5. Idiom re-abstraction** (stretch; biggest presentation win). Imported proofs
have no authored structure, only Metamath idioms — so *recognise* them and fold to
human altitude: `syl` chains → transitivity/"hence"; `ad*ant*`/`simp*` clusters →
"in this context"; `oveqNd` runs ending in `eqtr*` → one `calc` step; closure
lemmas → hidden typing obligations; `nnind` → "by induction on n". Feeds B4's
tree, and applies to all 40 000 imported proofs rather than only new ones.

**B6. Structural macros** — WLOG / by-symmetry / case-split (§2.2 item 7). Expand
to *real* subproofs, discharging "similarly" by instantiating a proved symmetry
lemma, so the author writes the human phrase and the kernel still sees the full
argument. General because the justification is always a cited lemma.

---

## 6. Sequencing

1. **`$t` + Unicode source + term-fold renderer** (§4) — wanted now, and part of A3.
2. **Axiom-vs-theorem split** (§3.2) — the modelling blocker.
3. **A4 definition classification** — cheaper before bulk than after.
4. **Close out the 2.2%** (§1.2): the two token-collision defects first — they
   are ours, small, and one of them cascades — then diagnose the 1,026 kernel
   rejections, which are still unexplained.
5. ~~**Persist the parse.**~~ *Done* (§1.3) — the walk stores the system, its
   proofs, their line graphs and their terms. Two things are left: **storing the
   library**, which is item 2's to decide (§3.2) and is what would let an
   imported proof be re-checked from its rows; and scale — extend a live
   system's grammar in place so a whole-corpus store does not re-promote the
   library at each notation change.
6. **B1 + B2**, then **B4** and **B3**; then the stretch items **B5 / B6**. The
   tactic framework and closure solver come first because they shorten *new*
   Edifyce proofs as well as imported ones.

The throughline: keep the property that makes Metamath trustworthy — **a small
kernel checking a fully primitive object** — and add the **elaboration gap** it
deliberately omitted. Verifiability and generality are preserved by construction;
altitude is what we add.
