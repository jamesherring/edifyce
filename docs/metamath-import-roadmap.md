# Metamath import: analysis and roadmap

**Status:** whole corpus imported and checked — **all 47,546 theorems verify**,
each against only the notation and theorems preceding it, every proof emitted from
its stored compressed proof and checked by Edifyce's own kernel (§1.1). One
qualification on what that establishes: `df-` statements still import as axioms
rather than definitions (§3.2, A4), so this verifies `set.mm` against a larger
primitive basis than a faithful import would use.

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
| Whole-corpus ordered pass (§1.1) | done — 47,546 checked, **all 47,546 verify** |
| Persisting the parse (§1.3) | done — one system, proofs, lines, terms |
| Whole-corpus walk, strictly scoped (§1.4) | done — `corpus.walk` |
| Scale (§5, A5) | **measured** — 24 min, 3.6 GB (§1.1) |
| Token-collision defects (§1.2) | fixed — four instances of one shape |
| `$t` typesetting / notation (§4) | **next** |
| Axiom-vs-theorem split (§3.2) | engine done; storing the library open |
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

One ordered pass over `set.mm` (`corpus.walk`, §1.4): walk the file, add each
syntax axiom and each variable to the grammar as it becomes available, check each
theorem against only the notation and theorems that precede it, then promote it.
Every proof is emitted from its stored compressed proof and checked by Edifyce's
own kernel.

| | |
|---|---|
| theorems checked | 47,546 |
| verified | **47,546 (100%)** |
| rejected by the kernel | 0 |
| failed to promote | 0 |
| wall clock | 23 min 57 s |
| peak memory | 3.6 GB |

Cost is dominated by `check`; `promote` and `emit` are each under a fifth of it.
Per-theorem cost grows with the grammar, which reaches 1,441 productions, and with
the library promoted into the system:

| theorems | ms each |
|---|---|
| 0 – 5,000 | 3.2 |
| 5,000 – 10,000 | 13.5 |
| 20,000 – 25,000 | 36.9 |
| 40,000 – 45,000 | 49.0 |

Roughly a fifteen-fold spread end to end, which is the number to beat if the corpus
is ever walked at several times this size.

The parse is no longer thrown away: the walk stores the system, each proof, its
line graph and its interned terms (§1.3).

### 1.2 The token collisions, and the shape they shared

Getting from the first whole-corpus pass (97.8%) to 100% took four fixes. All four
were **defects on our side**, and all four were the same shape: *a Metamath name
containing a character Edifyce reads structurally*. Worth recording, because it is
the failure mode any corpus with a rich constant vocabulary will provoke.

| collision | cost | fix |
|---|---|---|
| class variable `A` found inside the quantifier `A.` | 1,096 theorems | `_uncollide` renames the production's variable |
| a `$d` over a `class`/`wff` variable constrained nothing | soundness | sort-restricted `disjoint` per variable sort |
| interval constants `[,)`, `(,]` defeat the bracket check | ~1,000 theorems | `bracket_opaque`: a declared constant is opaque to the parity scan |
| a variable named `.,` cannot be named in a proviso | 69 theorems | `_proviso_safe_names` renames it, avoiding statement *and* premise tokens |

Two of these were found only by triaging the rejections directly, and both were
badly under-estimated first time round — the bracket collision was booked at 15
theorems when it accounted for around a thousand, because only the theorems that
failed to *promote* had been counted, not those whose *proofs* then failed to
check. A promotion failure cascades; a check failure does not.

Two engine limits surfaced alongside them: parsing was exponential in nesting
depth (a 16-binder statement took over 30 minutes; a parse memo per line brought it
to under a second), and `MAX_CITED_ANTECEDENTS` was 16 when 437 `set.mm`
assertions cite more than that.

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

### 1.4 The walk, and the scope it enforces

The pass is `corpus.walk`: **one** system, built covering the whole walk and then
*grown*. Every production is declared up front and admitted to its sort at the
position it becomes available — notation at the syntax axiom that declares it, a
variable where its `$f` first types it (`importer.grammar_schedule`). That is what
`import_theorem` establishes per theorem, made affordable over 47,546 of them.

Notation is the half that *has* to be scoped: a syntax axiom declares a
**constructor**, and one declared later can capture the parse of an earlier
theorem's formulas — set.mm's mathbox theorem `bj-0` overlaps the nesting of `wi`
and, unscoped, reaches back 600k lines. Variables were the half that was not,
seeded once at whole-database scope. A variable leaf adds no constructor, so it
never captured anything the way `bj-0` does — but the loose scope hid a real bug (a
proof using an optional floating hypothesis as a dummy parsed fine under it and
failed the moment it was tightened), and closing it costs about 2%.

**A variable is its own atom leaf** of a `<typecode>_var` sub-sort included into
its typecode, where it used to be one alternation regex per sort. A sort's
variables have to be able to grow, and an alternation cannot be extended in place:
a regex leaf's kernel constructor is identified by its regex *text*, so rewriting
it would split one variable into two non-interchangeable terms either side of the
rewrite. An atom is identified by its own token and joins a sort through
`add_pattern`, the mechanism notation already grows through. The sub-sort is what
keeps `$d` expressible — a proviso restricts to the leaves that *are* variables,
and spread over the typecode's own sort there would be no name for just those.

**A `$f` is itself scoped**, so availability is a property of the `(typecode,
variable)` **pair**: the same `x` may be a class in one block and a wff in a later
one. Reading every `$f` in the database and filtering by mention gave it both
typings from its earliest use — admitting the later one before its `$f` existed and
leaving both live, which can make an unambiguous grammar ambiguous.
`Database.typed_from` reads each assertion's *active* floating hypotheses instead.

**Growing beats rebuilding, by a factor of sixteen.** The walk used to rebuild
whenever notation was declared — correct, and the obvious way to scope notation
exactly. It costs the library: a `PromotedTheorem` holds patterns of the system it
was built against, so none survive a rebuild and every one is re-promoted. Over
set.mm's first 20,000 theorems that is 255 rebuilds and 3,224,504 re-promotions
against 20,544 promotions when built once — quadratic in the corpus, and by
measurement the whole cost of the pass:

| 20,000 theorems | |
|---|---|
| rebuild per notation change | 5,234 s |
| build once, admit as reached | **330 s** |

Two things a single build must get right. Productions are admitted at **every**
logical assertion, not only the checked ones: an axiom is promoted as the walk
passes it, and building a `PromotedTheorem` parses its statement. And the *logical
sort* is the one thing a single build cannot scope, since the line type is fixed at
build time — so a theorem stated before any prefix could name that sort is reported
rather than checked, the same refusal `_logical_sort` makes when built from that
prefix.

What is still whole-database is **sort admission**: a union's kernel constructor
fixes its branches when the system is built. It costs nothing, because admission is
only ever asked about a term that already parsed, and parsing is scoped.

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

### 3.2 The axiom-vs-theorem split

**The engine half is done.** `promote_assertions` used to register *every* logical
assertion as a promoted theorem, erasing the distinction that namespace exists to
preserve — a system's primitive rules against its derived results. `ax-mp` is the
clearest case; it is literally an inference rule:

```
${  min $e |- ph $.   maj $e |- ( ph -> ps ) $.   ax-mp $a |- ps $.  $}
```

A logical `$a` now joins `inference_rules`, a `$p` joins `promoted_theorems`
(`importer.register`). One construction serves both — they are the same shape to
the checker, and `PromotedTheorem.as_rule` was already the bridge — so the split
decides which namespace answers a citation, not how one is checked. An imported
system can now answer "what are your axioms?": on `set.mm`, **1,559 logical `$a`**
(126 `ax-`, 1,433 `df-`) against **47,546 `$p`**.

That count is also the argument for A4. All 1,433 `df-` are currently primitives
of the imported system, which is a much larger basis than `set.mm` actually
assumes — the definitional ones should be `Define`, not axioms, and the split is
what makes the overstatement visible rather than hidden among 49,000 theorems.

Resolving a citation needed an index first. `Proof.get_reference` scanned
`inference_rules` linearly, twice per citation — free at a handful of rules, not
at 1,559 against roughly 4M citations. `FormalSystem.rule_by_label` keys them.

**The storage half is now done too** — but not the way this section proposed, and
the difference is worth recording because a measurement overturned it.

The plan was to split the library by *kind*: **axioms** into the existing `rules`
table (a declarative `Rule` is all strings, and `promoted_theorem` already
computes exactly those), **derived theorems** into a table of their own. That
would have made an imported system's axioms real `inference_rules`, which is
tidy. It does not scale. `build_system` builds every rule **eagerly**, and a build
is what a verify performs: at 309 productions, 269 axioms-as-rules already cost
0.29 s per build, so set.mm's 1,559 at 1,441 productions would put seconds on
every verify and grow with the corpus. A fully imported set.mm would have been
effectively unverifiable.

So the split that got built is by **provenance**, not by kind. `rules` keeps its
meaning — the handful of primitives an author declared, built with the system —
and a new `promoted_theorems` table holds a library that arrived whole, *both*
kinds, resolved by label on demand: a verify reads the citations off a proof's own
lines and promotes exactly those. A `primitive` column records which kind an entry
is, so "what does this system assume?" is still one query
(`WHERE primitive`); nothing in *checking* reads it, because a citation of an
axiom and of a derived theorem are checked identically — which is the same fact
this section already rests on, pointed at storage instead of at namespaces.

The string-computation helper this section asked for was still the right first
step, and exists: `promotion.TheoremSpec` plus `importer.theorem_spec`, shared by
promotion and by the persistence layer.

Measured: over set.mm's first 1,000 theorems, all 1,000 re-check from their rows
alone and agree with the verdict the import recorded — no `.mm` file, no statement
parsed. See [docs/verification-from-rows.md](verification-from-rows.md) P4 for the
laziness, the term cache, and how a theorem's own `$e` hypotheses stay scoped to
its own proof.

---

## 4. Notation and typesetting

### 4.1 Decision: separate source from display

**Source and display are separate layers**, as in Metamath — *not* LaTeX stored as
the logical source.

The deciding argument is where failures land. A **display** collision (two tokens
render alike) is cosmetic: the proof still checks. A **grammar** collision (two
tokens *parse* alike) is a correctness bug. Storing LaTeX as source converts every
cosmetic problem into a correctness one, and imports a normalisation problem
besides (`\left(` vs `(`, optional braces, competing macros for one symbol).

Two further reasons: `set.mm` ships *three* display maps, and separation gives
LaTeX, Unicode, MathML and screen-reader text from one checked source; and Edifyce
targets *any* formal system, where MIU and semi-Thue systems have no use for LaTeX.
`StringPattern` already carries `display_pattern` / `display_variables` beside its
matching pattern.

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

The renderer walks the **kernel `Term` graph**. `Node.to_string()` already walks a
production's template emitting literals and recursing into `children`; a display
render is that same fold with `display_pattern` in place of `pattern`.

The decisive reason is that **terms exist where matches do not**. A rule schema, a
promoted theorem's statement, a definition's higher/lower form: all are terms with
no `Match`, so match-based rendering would cover proof lines and nothing else.
Terms are also canonical (`from_match` collapses union-coercion wrappers) and
interned, so rendering memoises for free.

Constraints when building it:

- **The renderer lives outside the kernel**, which hard-codes no logic and stays
  small. `Node.pattern` is already a `matching.Pattern`, so this adds no coupling.
- **Canonical ≠ verbatim.** Rendering from the term normalises redundant brackets
  and drops coercions; a verbatim echo must come from the stored source string.
- **Definition-backed nodes** use `defn.higher` as their constructor, so display
  templates key on patterns generally, not productions only.
- `to_string` probes with `getattr(pattern, "pattern", None)`. AGENTS.md
  discourages that idiom; dispatch on pattern type instead of copying it.

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
`$a` and a `$p`. `PromotedTheorem` records the schematic statement (conclusion,
premises, metavariables, `$d` provisos, matching regime) and `as_rule()` builds the
*ephemeral* `InferenceRule` a citation is checked against, so nothing per-theorem
is persisted as a rule. `$d` is demonstrably load-bearing: an `ax-5`-shaped theorem
rejects the capturing instance with the proviso and accepts it without.

Promotion turned out to be a **graph** operation (`from_match` → re-variabilise →
schema shell), not a string one, and a schema with no composed term is not broken —
only a *ground* compound needs its term composed, at the system's logical sorts.

*Still open:* promoting a **natively-authored** Edifyce proof needs a
generalisation policy the importer gets free from `$f`/`$d` — which leaves are
general, what sort to widen to, and deriving `$d` from the proof's ∀I freshness
steps. Deferred; imports never hit it.

**A2. Compressed-proof decoder — *done*.**
`sqrt2re $p |- ( sqrt \` 2 ) e. RR $= ( c2 2re 2pos sqrtpclii ) ABCD $.` — the
label table is indexed by `ABCD` and executed on a stack: `c2` builds the class `2`
(**syntax**, no line emitted), `2re`/`2pos` push their statements, then
`sqrtpclii` pops **three** — its floating `$f class A` *then* its two essentials,
in declaration order. The floating slot supplies the substitution (`A := 2`); the
essentials become the cited lines. Wrong order or count silently misaligns every
application, so it is computed at parse time (`Assertion.mandatory`).

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
The whole corpus checks in 24 minutes at 3.6 GB (§1.1). Both risks this item named
were real and are addressed. The backtracking string matcher was the dominant cost
and *exponential in nesting depth* — `cbvral8vw` (16 binders) did not finish at all
— until substring parses were memoised per parse; reading a template by its
declared slots then halved what remained, and picking candidate productions by the
string's leading character is what stops cost growing with the grammar's 1,441.
Resolution of 49,000 promoted theorems never became the bottleneck this item
predicted; the parse did, and then the library re-promotion did (§1.4).

What remains is memory — 3.6 GB, growing roughly linearly with theorems promoted —
and per-theorem cost still rising with grammar size (5 ms early, 60 ms late).
Neither blocks a bulk import; both would matter for a corpus several times larger.

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
2. **Store the imported library** (§3.2) — the axioms first, which need no
   schema work now the split names them; then the 47,546 derived theorems,
   which is the question still open.
3. **A4 definition classification** — cheaper before bulk than after.
4. ~~**Persist the parse.**~~ *Done* (§1.3) — the walk stores the system, its
   proofs, their line graphs and their terms. The scale half of this item is
   done too: the walk extends one live system's grammar in place rather than
   rebuilding it, so a whole-corpus store no longer re-promotes the library at
   each notation change (§1.4, 16× on 20,000 theorems). What is left is
   **storing the library**, which is item 2's to decide (§3.2) and is what would
   let an imported proof be re-checked from its rows.
5. **B1 + B2**, then **B4** and **B3**; then the stretch items **B5 / B6**. The
   tactic framework and closure solver come first because they shorten *new*
   Edifyce proofs as well as imported ones.

The throughline: keep the property that makes Metamath trustworthy — **a small
kernel checking a fully primitive object** — and add the **elaboration gap** it
deliberately omitted. Verifiability and generality are preserved by construction;
altitude is what we add.
