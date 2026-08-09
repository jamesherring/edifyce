# Metamath import: analysis and roadmap

**Status:** whole corpus imported and checked — **all 47,546 theorems verify**,
each against only the notation and theorems preceding it, every proof emitted from
its stored compressed proof and checked by Edifyce's own kernel (§1.1). The
primitive basis is no longer "every logical `$a`": **1,429 of `set.mm`'s 1,559
import as definitions** rather than axioms, leaving 130 primitive, and every
theorem still verifies (§5, A4). What remains is a short, enumerated tail — 118
statements whose root is not a declared definitional equivalence, and 12 others —
and every one of them is a statement whose *shape* says it does not define, rather
than one the representation cannot carry. 126 of the 130 are named `ax-` by
`set.mm` itself.

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
| Axiom-vs-theorem split (§3.2) | done — engine, and the library stored by provenance |
| Definition classification (§5, A4) | done — wired into the walk; 1,429 definitions / 130 axioms, of which 126 are `set.mm`'s own `ax-` |

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
| definitions registered | 1,429 of 1,559 logical `$a` (§5, A4) |
| wall clock | 22 min 45 s axioms only, 24 min 17 s with definitions |
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

### 1.1a What the writes cost, and why it is round trips

The figures above are a *local* database, where a statement costs almost nothing
and the split is 65% engine to 35% database. Against a remote one that inverts,
because what a remote database charges for is **round trips**, and the import used
to make ~27 per theorem.

Three of them were avoidable, and one cause produced two:

- `store_term` interned **one** term per call, so a proof paid a `SELECT` per line
  for an answer whose size does not depend on how much is asked. `store_terms`
  asks once for the whole proof; `store_term` is now a wrapper on it.
- That `SELECT` **autoflushed**, and it ran between the `ProofLineRow`s being
  created — so each line flushed alone (an `INSERT` per line rather than one
  `executemany`) *and* became persistent, which made the later `.antecedents`
  assignment load the empty collection it was about to replace. Interning every
  formula first, then building the rows under `no_autoflush`, fixes both.
- `_link_proofs_to_theorems` issued one `UPDATE` per `$p`. The *deferral* is
  necessary — a proof cannot point at a theorem promoted after it — but the loop
  was not.

Measured on 800 theorems against local Postgres, and on 300 with a 2 ms
per-statement delay standing in for a remote one:

| | statements | wall (local) | wall (+2 ms/stmt) |
|---|---|---|---|
| before | 21,445 | 33.4 s | 34.7 s¹ |
| after | 11,585 | 19.5 s | 18.9 s¹ |

¹ the latency columns are the 300-theorem run (8,114 → 4,278 statements).

Statements roughly halve, and so does wall clock once latency is real. **The rows
are unchanged**: importing 400 theorems before and after gives byte-identical
content digests across proofs, lines, antecedent edges, terms, term children,
promoted theorems, premises and theorem links — which is the check a performance
change to a storage path actually needs.

What is left is inherent or cheap: `INSERT proofs` is one row per proof, and the
2 savepoints per theorem are what buy per-theorem error isolation. For a *remote*
target none of this beats `pg_dump`/`pg_restore` of a locally-built import, which
is one stream rather than thousands of round trips.

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

### 4.3a What the `$t` block turned out to be — *read; §4.2 needs revisiting*

`parser` now keeps comments (55,742 of them, and 60,661 attribution clauses on
assertions), which is what makes the `$t` block reachable at all: it *is* a
comment, so stripping comments was what blocked this whole section.
`metamath/typesetting.py` scans it. Three measurements change what §4.2 assumes.

**All three maps cover the same 1,794 tokens** — not the 1,818 / 1,867 / 1,882 a
keyword count suggests. The surplus is directives commented out inside the block's
own `/* … */`.

**`althtmldef` is not Unicode.** It is *HTML that renders as* Unicode, and the
difference is load-bearing: **719 of the 1,794 values carry `<SPAN>` markup**,
including every variable —

```
ph   ->   <SPAN CLASS=wff STYLE="color:blue">&#x1D711;</SPAN>
```

— where the colour encodes the typecode. Of the 1,075 that are entity-only, only
149 are non-ASCII once unescaped. `typesetting.as_text` does the derivation (682
tokens yield a non-ASCII character), but dropping the tags discards a distinction
the HTML makes, so it is a documented *policy* rather than a conversion.

**And the derived map is not injective, which §4.2 has to answer for.** Passed
through `as_text`, **50 renderings are shared by 107 of the 1,794 tokens**:

| | |
|---|---|
| `∪` | `u.`, `U.`, `U_` |
| `∩` | `i^i`, `\|^\|`, `\|^\|_` |
| `⊥` | `F.`, `._\|_`, `_\|_` |
| `,` | `.,`, `,`, `,.`, `,,` |

§4.1's own rule is that a *display* collision is cosmetic and a **source**
collision is a correctness bug. §4.2 proposes this map as the imported source, so
these 107 are exactly the case it forbids, and adopting it wholesale would make
three different unions unparseable from their own rendering.

It is not fatal, and the shape of the answer is already in §4.4: the colliding
tokens differ in *arity and position* (`u.` is binary, `U.` unary, `U_` indexed),
which a per-**production** template distinguishes even where a per-token map
cannot. So the collisions are an argument for production templates rather than
against Unicode source — but §4.2 needs restating in those terms, and the §4.4
collision report should start from this list of 50 rather than be discovered
later.

### 4.2a Unicode as source, measured — *§4.2 revised*

§4.2 proposed importing `set.mm` with Unicode as the **source** notation. Two
measurements say most of that should not be done, and the part worth having costs
nothing.

**The collision is real but a fifth the size feared.** §4.3a recorded that the `$t`
Unicode map shares 50 renderings across 107 tokens, and §4.1 classes a source
collision as a correctness bug. Measured at the level that decides a parse -
whether two *productions of one sort* end up spelled alike, slot names punched out
- it is **32 spellings over 64 productions**, still a fraction of the tokens,
because arity and position tell apart what a token map cannot: `∪` is `u.`, `U.`
and `U_`, but `( A ∪ B )`, `∪ A` and `∪ x ∈ A B` are three different shapes.

| notation | colliding spellings | productions |
|---|---|---|
| source (ASCII) | **0** | 0 |
| Unicode (`althtmldef`) | 32 | 64 |
| LaTeX (`latexdef`) | 19 | 38 |

(An earlier revision said 19 and 8. Both were wrong, in opposite directions, and
review caught the measurement rather than the conclusion: the walk stopped at a
sort's own productions and never reached the sub-sorts included into it — so
`class`'s operators were never compared with the class *variables* — while slots
were punched out without their sorts, so two templates differing only in what sort
a slot takes counted as colliding. Fixing both moved the figure up.)

**And the check finds collisions rather than certifying their absence.** Three
rounds of review each found another way it answered "none" for a grammar that had
them: a regex leaf a mapped atom now matches, two slots whose sorts differ by name
but overlap by inclusion, a defined form reachable from a sort that did not declare
it. All three are fixed and pinned, and none changes `set.mm`'s figures — but the
pattern is the lesson. Deciding whether a context-free grammar is ambiguous is not
something a comparison of surface templates can do, so the property is named
`collision_free` rather than `usable_as_source`, and adopting a notation as a
source wants a parser run over the corpus as well as a clean report.

`metamath/display.notation_report` is the check, and §4.4's asked-for report: it
gives the unmapped tokens and the colliding spellings for any candidate notation,
so re-syncing is driven by a list. Both `$t` maps cover every token the grammar
uses - `unmapped` is empty for each.

**What remains is genuine ambiguity in `set.mm`'s own rendering**, not an artefact.
`cpi` (the constant π) and `cppi` (the prime-counting function) are both `π` on its
HTML pages, as are `cpnf`/`cpinfty` (`+∞`), `cz`/`cza` (`ℤ`) and `cnr`/`cright`
(`R`). Sharper still, its *class variables* are spelled like its operators — the
variable `.+` renders `+`, exactly as `caddc` does, and likewise `./`, `.-` — so
`( A + B )` would not say which. A reader disambiguates by context; a parser
cannot. Adopting Unicode as the imported source therefore needs 32 editorial
decisions about what to call the second of each pair, which is a judgement about
`set.mm` rather than a piece of engineering.

**And a Unicode source needs no engine work at all**, which is the measurement that
changes the recommendation. A grammar *declared* in Unicode already parses and
round-trips:

```python
Production(sort="formula", name="implication", template="(A → B)", ...)
system.parse("(𝜑 → ¬⊥) [given]")     # parses, and to_string() gives it back
```

So there was never an engine gap. What §4.2 actually proposed was **re-spelling an
imported corpus**, and that couples four things - production templates, proof
emission (`import_proof` writes Metamath tokens), promotion, and proviso naming
(`𝜑` would have to be legal in a proviso, which is what `_proviso_safe_names`
exists to worry about) - and then wants all 47,546 proofs re-verified against a
changed grammar.

For what? Readability is already had: §4.3b renders any term in any notation
without touching the grammar. The only thing re-spelling adds is *authoring the
imported corpus in Unicode*, and nobody authors `set.mm` here - it is imported.

**So §4.2 is revised.** Unicode source is for **new** systems, where an author
declares the notation once and no re-spelling, collision list or re-verification
arises. The imported corpus keeps `set.mm`'s tokens as its source and gains
Unicode as a *projection*. If re-spelling the import is ever wanted, the report is
what makes it safe and the 32 pairs are what must be decided first.

### 4.3b The fold, parameterised — *done*

`website/logical/rendering.py` is `Node.to_string`'s fold with the templates
swappable. A `Projection` maps a constructor name to render steps — the same
`("lit", …)` / `("slot", …)` shape `Constructor.pieces` already holds, so a
projection is a *substitute template* rather than a new kind of thing. A
constructor it does not name renders from its own, so a partial projection is
useful and `render(term)` with none is `to_string()` exactly. That identity is
checked over all **49,105** of set.mm's parsed statements, which is what lets
projections be added without changing any existing caller.

It lives outside the kernel, as §4.3 requires: the kernel exposes `pieces` and
nothing here reaches back in.

`metamath/display.py` is the bridge from a token map to production templates, and
the bridge is the whole trick. A production's template is *made of* the tokens the
`$t` block renders, so mapping the tokens **inside the template** yields a
production template — and the tree then supplies the brackets, the nesting and the
argument order that per-token substitution loses:

```
wcel   ('slot','A'), ('lit',' e. '), ('slot','B')
   ->  ('slot','A'), ('lit',' ∈ '),  ('slot','B')
```

Over set.mm that seeds **776** templates automatically and re-spells **48,824** of
the 49,105 statements:

```
( sqrt ` 2 ) e. RR                          ( √ ‘ 2 ) ∈ ℝ
( sqrt ` 2 ) e/ QQ                          ( √ ‘ 2 ) ∉ ℚ
( A. z ( z e. x <-> z e. y ) -> x = y )     ( ∀ 𝑧 ( 𝑧 ∈ 𝑥 ↔ 𝑧 ∈ 𝑦 ) → 𝑥 = 𝑦 )
```

Two things it deliberately does not do. It does not invent notation the source
lacks — `( sqrt \` 2 )` becomes `( √ ‘ 2 )`, not `√2`, because the parentheses and
the application backtick are in the production and `set.mm` renders them. Turning
that into `\sqrt{2}` means *overriding* the production's template, which is §4.4
and is editorial rather than automatic; seeding from the file is the safe half.
And it takes spacing from the *template*, not the map: a `$t` value carries HTML
padding (`' &isin; '`) which would double every gap.

Atoms are included, which is easy to miss and cost a first attempt: a Metamath
constant is a nullary production (`RR`, `sqrt`, `0`) carrying its text rather than
a template, so a projection reaching only compound productions renders `( √ ‘ 2 )
∈ RR` — operators re-spelled, constants left in ASCII. Including them took the
projection from 120 templates to 776.

### 4.3c A notation, stored and served — *done*

§4.3b left the fold parameterised but with nothing to feed it on the read path: a
`Projection` was derived in memory from a built system, and a reader has a
database. So a notation is now **persisted with its system** and the whole path
runs from rows.

`notation_pieces` is one row per render step — `(system, notation, constructor,
position, kind, text)`. Steps rather than a template *string*, which was the first
attempt and is not available here: compiling `{A} ∈ {B}` back to steps needs a
delimiter no notation uses, and set.mm makes braces notation (`{ x | ph }`). The
rows are the shape `Constructor.pieces` already has, so nothing is compiled in
either direction.

Three pieces wire it up:

- **`rendering.total_projection`** completes a derived projection to name *every*
  constructor before it is stored. An in-memory projection names only what it
  changes, because the term carries its own constructor; a stored one cannot, so
  anything unnamed would render as a hole. On set.mm the `$t` block seeds **776**
  templates and completion takes that to **1,796** constructors — **2,605** rows.
- **`app/db/notations_mapping.py`** stores and loads them, and `render_stored`
  folds a stored notation over the *row* graph. It is the storage-side twin of
  `rendering.render`, and the two are pinned against each other on a real system
  (`tests/test_notations_store.py`) because they are one operation over two shapes
  and nothing else would catch them drifting. Reading from rows is the point: a
  display should not cost a system rebuild, which is what a *check* is for.
- **`import_corpus`** derives and stores the `unicode` notation as the last step
  of an import, which is the only place it can be derived — it needs the file's
  `$t` *and* the grammar that file built. A `.mm` storing none is not a failed
  import, and there are three ways to store none: no `$t`; a `$t` declaring only
  `latexdef`/`htmldef` (the three maps are independent, and a file may carry any
  of them); and a `$t` whose Unicode is about tokens this grammar's productions
  never use. The last two would otherwise complete to a `unicode` notation
  spelling every constructor exactly as the source does — advertising a reading
  that is the one a reader gets by asking for none.

Reading is **layered**, as the system is. A system inheriting from another is
built from its ancestors' parts in front of its own, so their constructors are its
constructors and their spellings are readings of it; `notation_layers` walks the
chain by id (not `load_chain`, which loads whole systems — seconds on a corpus,
far more than a reading should cost) and a child's own rows win per constructor.
Without that, building on an imported corpus would silently cost you the corpus's
notation — and since a `$t` block is where a notation comes from, that is every
notation there is. Storing stays unlayered: a notation is stored against the one
system it was derived for.

The API serves it: `GET /proofs/{id}/structure?notation=unicode` renders each
line's term through the stored notation into `ProofLineOut.rendered`, and
`FormalSystemDetail.notations` lists the names a system stores. `display` is left
alone — it is the source the proof was written in. Note what `rendered` is *not*:
it is the line's **term**, so it carries no citation and no indentation, both of
which the checker already stored separately; a client puts them back
(`frontend/src/lib/reading.ts`). A name the system does not store is a 404 rather
than a silent fall back to the source, which would look like the notation had no
opinion about any line.

The proof view offers Source alongside each stored notation, and re-reads on a
verify, since a check rewrites the structure the reading comes from.

What this does not add is *authoring* in a notation — that is §5's Tier B, and it
is the harder direction: rendering is a fold, and reading back is a parse against
a grammar the notation does not define.

### 4.4 Beyond per-token substitution — *done*

A per-token map yields token-soup LaTeX. Because Edifyce has the parse tree, a
production can instead carry its own display template, and an **override** is a
hand-written one that wins over whatever the map derived
(`display.with_overrides`).

**Where the report pointed.** `notation_report`'s token level says almost nothing
about a published corpus: `set.mm`'s `latexdef` covers all 1,794 of its tokens, so
`unmapped` is **empty**. What matters is the *production* level, and that is new —
`display.verbatim` lists the compound productions a notation leaves spelled as the
source spells them, because every token in them maps to itself. There were **11**,
of which most are right as they are (`A = B`, `A R B`, `( A F B )` need no help).
Three were not, and `setmm.DISPLAY_OVERRIDES` is that list curated:

| production | source | override | why |
|---|---|---|---|
| `cfv` | `( F ` A )` | `{F}\left({A}\right)` | TeX sets the backtick as an opening quote; **36%** of statements contain one |
| `cdc` | `; A B` | `{A}{B}` | a decimal numeral built digit by digit — `;` is the constructor, not a character to print |
| `cab` | `\{ x \| ph \}` | `\left\{{x} \mid {ph}\right\}` | `\mid` is the relation TeX provides for this; braces grow with the body |

Measured on `set.mm`:

```
sqrt2irr  ( \surd ` 2 ) \notin \mathbb{Q}
       →  \surd\left(2\right) \notin \mathbb{Q}
abscl     ( A \in \mathbb{C} → ( \operatorname{abs} ` A ) \in \mathbb{R} )
       →  ( A \in \mathbb{C} → \operatorname{abs}\left(A\right) \in \mathbb{R} )
```

**Both maps are now stored.** An import derives a notation per `$t` map the file
declares, so `set.mm` arrives with `unicode` *and* `latex`, and the proof view's
selector picks the second up with no frontend change — it lists whatever the
system stores. The `unicode` notation deliberately carries no overrides: `( 𝐹 ‘ 𝐴 )`
is how `set.mm` itself writes application, and a Unicode reading exists to be
faithful.

**What a per-production override cannot do**, and the roadmap's own third example
was the case: `( sqrt ` 2 )` is `cfv` applied to the constant `csqrt` — two
productions — so no template for either turns it into `\sqrt{2}`, and the best a
per-production override reaches is `\surd\left(2\right)`. Likewise `\frac{A}{B}`,
since `set.mm` builds division as the generic `co` applied to `cdiv`. Both want
matching a *shape* rather than a constructor, which is §4.4b.

### 4.4b Matching a shape — *done*

The cases §4.4 could not reach share one form, and it is `set.mm`'s central idiom
rather than a curiosity: application and binary operation are **generic**. `( F `
A )` is one production whatever `F` is (`cfv`), and `( A F B )` is one production
whatever `F` is (`co`), so the symbol a reader thinks of as the operator — `sqrt`,
`/`, `^`, `_C` — is an *operand*, a nullary class constant sitting in a slot.
Re-spelling either production says nothing about it.

`rendering.Rule` is that pair written down: the production at the root, what must
sit at given slot paths for it to apply (`{"F": "csqrt"}`), and the template to
use when it does. It is tried before the per-constructor template and wins
outright, and the pinned operand is **consumed** — there is no `\surd` left in
`\sqrt{2}` — which is precisely why it cannot be a template for either production
alone. A `Projection` now carries both halves: `templates` keyed by name, which is
what a `$t` map derives and is thousands of entries, and `rules` keyed by shape,
which is curated and single figures.

A slot is a **path** (`"F"`, `"A.F"`), so a rule can reach a grandchild the root's
own template cannot name. That is what buys generality without a tree: matching
walks paths rather than recursing over a pattern, and one flat table stores them.
Depth beyond one is unexercised by the corpus and costs nothing to allow.

Only a *rule*'s steps are paths, which is not a detail: a template's are slot
labels, and a Metamath slot label may contain a dot. `set.mm` names class
variables `.+`, `.x.` and `.0.`, and `seq M ( .+ , F )` is a production whose slot
is one of them, so splitting every step on a dot renders `seq M ( .+ , F )` — the
label where the operand belongs, across thousands of statements. Within a rule the
same labels stay addressable because a path resolves **longest label first at each
level** (`rendering.longest_label`): `A..+` is the `.+` of the child `A`, not three
steps. `Rule.roots` resolves against the root's own slots the same way, or a rule
descending into a dotted slot would look as though it accounted for none.

`setmm.DISPLAY_RULES` is `set.mm`'s, chosen where the mathematical notation is
genuinely two-dimensional or fenced and the linear form is a transcription of it:

| rule | source | before (§4.4) | after |
|---|---|---|---|
| `sqrt` | ``( sqrt ` A )`` | `\surd\left(A\right)` | `\sqrt{A}` |
| `absolute-value` | ``( abs ` A )`` | `\operatorname{abs}\left(A\right)` | `\left\lvert A\right\rvert` |
| `factorial` | ``( ! ` A )`` | `{!}\left(A\right)` | `A!` |
| `factorial-of-factorial` | ``( ! ` ( ! ` A ) )`` | — | `\left(A!\right)!` |
| `fraction` | `( A / B )` | `( A / B )` | `\frac{A}{B}` |
| `power` | `( A ^ B )` | `( A \uparrow B )` | `{A}^{B}` |
| `binomial` | `( N _C K )` | `( N \mathbin{\operatorname{C}} K )` | `\binom{N}{K}` |

`+`, `x.` and the rest read correctly as `( A + B )` and are left alone. Measured
over `set.mm`'s 50,421 parsed statements they change **3,297** of them:

```
sqrt2irr  \surd\left(2\right) \notin \mathbb{Q}
       →  \sqrt{2} \notin \mathbb{Q}
bcval     ( N \mathbin{\operatorname{C}} K ) = \mathrm{if} ( … , ( {!}\left(N\right)
            / ( {!}\left(( N - K )\right) \cdot {!}\left(K\right) ) ) , 0 )
       →  \binom{N}{K} = \mathrm{if} ( … , \frac{N!}{( ( N - K )! \cdot K! )} , 0 )
sqrtdiv   \surd\left(( A / B )\right) = ( \surd\left(A\right) / \surd\left(B\right) )
       →  \sqrt{\frac{A}{B}} = \frac{\sqrt{A}}{\sqrt{B}}
```

**Stored, so the read path has them.** Three tables — `notation_rules` (root,
name, order), `notation_rule_pins` (path, required production) and
`notation_rule_pieces` (the template steps) — rather than one with a
discriminator, because a pin and a step carry genuinely different columns and
encoding either into the other's is unpicked by hand later. `render_stored` walks
them over the row graph exactly as `rendering.render` walks kernel terms, and
`rendering.matches` is the one piece both folds share, so they cannot disagree
about what matching *means*; `tests/test_notations_store.py` pins the two answers
against each other on a real grammar as it already did for the templates. Checked
on `set.mm` itself as well — its 1,796-template `latex` notation stored, loaded
back, and folded over stored terms, agreeing with the engine's own fold on each of
`sqrt2irr`, `sqrtdiv`, `bcval`, `absval2`, `binom` and `facnn` (one per rule).

The last of them is what pin-count precedence is *for*. `A!!` conventionally means
the double factorial, a different operation, so a factorial of a factorial under
the plain rule would be shown as mathematics the term does not say. Parenthesising
every `N!` to prevent it would cost more than the rule wins; a second rule with one
more pin is tried first and fences the whole operand, so it composes with itself
and no depth produces a bare `!!`. `set.mm` contains no such statement today
(measured: 0), which is why this is a rule rather than a redesign.

Reading is layered like everything else, and by rule **name** — a child re-stating
`sqrt` replaces it and keeps the ancestor's other rules. Not by root constructor,
which would be wrong: several rules legitimately share a root, since fixing a
different operand in the same applicator is the whole idiom. Where two rules could
both match, the one with more pins wins whatever order they were written in, so a
table cannot be broken by appending to it.

`display.applicable_rules` refuses a rule this grammar cannot use, as
`display.applicable` does for an override and on a sharper version of the same
ground: a rule *consumes* what it pins, so a root slot neither pinned nor rendered
would vanish from the page with nothing to show it existed. It must therefore
account for **every** slot of its root, and its pins must name productions the
grammar has — a pin that can never hold is dead rather than dangerous, but
silently dead, which is what a table carried to another library would be.

The API and the frontend need no change: rules ride in on the stored projection
that `GET /proofs/{id}/structure?notation=…` already loads.

A **collision a rule introduces** is now checked too, and was not when rules were
added: `notation_report` compared surface templates per production, and a rule is
not one — two rules spelling a shape alike, or a rule spelling what a template
already does, went unreported. It takes `rules=` and reports either, naming the
rule as `rule:<name>` so a curator knows which of the two tables to edit. A rule is
compared by **shape alone**, without the slot-overlap test two productions get: a
rule's slots are paths into a pinned shape, so their sorts are not readable off one
constructor, and a curated table of seven is somewhere a false positive costs a
glance where the derived grammar's two thousand is not. Measured against the whole
of `set.mm`: the seven `latex` rules introduce **no** collision.

The 19 remaining collisions are **two problems, not one** — eleven a constant
against a class *variable* of the same spelling (`+` is both `caddc` and a variable
named `.+`), and eight two distinct *constants* that `set.mm`'s own `latexdef` maps
alike (`S.1` and `S.2` both declare `\int_2`; 39 of its 1,794 tokens share a
spelling with another). As a display both are cosmetic — `set.mm`'s HTML tells the
first eleven apart by colour, which `as_text` drops by policy — and as a *source*
both are correctness bugs, which is why §4.2a refused Unicode-as-source. Only the
first eleven would yield to a policy; see the authoring roadmap's §2 for the split.

`scripts/notation_report.py` prints all three lists for a file, so the table stays
driven by a list rather than by discovering breakage — and it reports collisions
against the notation **as adopted**, overrides and rules both, since each is a way
curating can create a collision the token map says nothing about.

`set.mm`'s own table is *passed to* the import rather than reached for by it
(`import_corpus(overrides=…)`, as `corpus_spec` already takes the binder table),
and the CLI opts in (`--setmm-overrides`) rather than out. An override is dropped
unless the grammar has that constructor with **exactly** its slots: a Metamath
label is local to its library, and a foreign `cfv` taking one slot more would
otherwise render with that slot silently omitted — a term shown as something it is
not. Matching name and arity is still not proof of matching meaning, which is why
the opt-in is explicit.

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

**A3. Statement mapping — *done, bar the notation layer***.
`$c`→terminals, `$v`→metavariable names, `$f`→sort bindings, `$e`→antecedents,
`$a`→axiom or definition, `$p`→proof + promoted theorem, `$d`→`disjoint` provisos,
`${ $}`→scope. The reader handles all of these. The axiom-vs-theorem split that
was this item's real gap is settled in both halves (§3.2). Remaining: the `$t`
block (§4); typecodes beyond `wff`/`class`/`setvar`; `$[ … $]` inclusion (low
priority, set.mm is self-contained). Import faithfully as Metamath's own sorts
first; a richer type discipline risks needing to re-prove things and is best
deferred.

**A4. Definition classification — *done; see "A4 wired in" below*.**
The classifier and its wiring are both in place — 1,429 of set.mm's 1,559 logical
`$a` register as definitions and 130 stay primitive. The rationale below is kept
as the record of why the split is worth having, and the figures inside it are
*staged*: each states the corpus result as of the step it describes, so 1,335 /
224 appears below as the state after binding slots and before the `$d` split, and
1,427 / 132 as the state after that split and before the `cmpo` scope fix, and
1,428 / 131 as the state before `df-bi` was declared. Only the figures here and
in the two tables above are the current result.

Metamath does not distinguish a definition from an axiom: both are `$a`, `df-` is
a convention its verifier never reads, and soundness of the definitional ones is
left to an *external* checker. Importing every logical `$a` as an axiom is
faithful and fully verifiable — it is what Metamath itself does — but it gives up
conservativity-by-construction, which Edifyce's `Define` supplies for free, and
definitional steps `[Def, n]` in a proof. It also overstates the basis: §3.2's
split counted 1,433 `df-` declared primitives of the imported system.

`metamath/definitions.classify` decides structurally, never by label. Three tests,
then the kernel:

1. the statement's root is a **declared definitional equivalence** (`wb`/`wceq`
   for `set.mm`) — declared rather than inferred, because arity and slot sorts do
   not tell `↔` from `→`, and nothing is a definition under the empty default;
2. its defined side is **not a bare metavariable**;
3. its defined side is **built from notation not yet in use**.

Two further refusals cover what a `Definition` cannot faithfully carry: a defining
form built from the form being defined, and a metavariable the proviso syntax
cannot name. A `$d` *is* carried, as the definition's provisos — 1,033 of the
definition-shaped statements have one, and dropping them would licence the
captures Metamath forbids. Carried **per pair**, though: a `$d` naming a variable
the definition has no name for keeps every pair it can state and drops the rest,
where dropping them is argued (below).

**The `$e` case has a known shape, and it is not a side condition — *done*.**
`df-sb` defines proper substitution using a bound `y` appearing on the right only,
which is sound just because the choice of `y` is immaterial; its `$e` (`sbjust.1`)
is the statement that it is. That is a *derivability* claim, and every predicate in
the kernel's closed algebra — `Occurs`, `DisjointLeaves`, `IsAtom`, `IsMember`,
`Equal` — is a total structural check on shape. A `Proven(φ)` proviso would have
to search for a proof at every citation: undecidable, and it would restore the
executable condition language the kernel deliberately retired.

So it is discharged **once, when the definition is registered, by citation**. A
`Definition` carries a `Justification` — a label and the obligation as a
statement — and `declarative._discharge_justification` settles it before any of
the definition is registered. `set.mm` shows this is the right model, because it
is already what Metamath does:

| | |
|---|---|
| `sbjust` | a **proved** `$p`, at position 2092 |
| `df-sb`'s `$e sbjust.1` | token-identical statement |
| order | `sbjust` precedes `df-sb` |

The same holds for `mojust`/`df-mo`. Both proofs are already in the corpus and
already ahead of the definition needing them, so the import cites what is there
rather than proving anything new. `metamath/definitions` finds the citation —
a proved statement token-identical to the hypothesis, ahead of it in the file —
and the engine decides whether it discharges anything:

- the obligation must be an **instance** of the cited statement, matched
  structurally with the obligation's own metavariables rigid, so the discharge
  holds for every substitution the definition is later used at. A theorem may be
  more general than the obligation needs, never less;
- the cited statement must carry **no premises of its own**, which would be the
  obligation again one step back;
- the definition **inherits the cited theorem's provisos**, restated in its own
  metavariables (`kernel.side_conditions.restate`). The citation licences only
  what the theorem licences, so `sbjust`'s `$d x y z` becomes a condition on
  `df-sb`. Stricter than Metamath, which re-proves the hypothesis per use — and
  over `set.mm` it costs nothing, since both definitions carry the same `$d` as
  the theorem they cite.

Verified against the corpus: both obligations discharge on the real terms, and
both inherit their theorem's `$d` restated over their own variables.

**The binding-slot wall — now down.** Before binding slots were declared, the
classifier returned **306 definitions, 1,253 axioms**, and the single dominant
refusal, **1,123 of them**, was *a defining form introducing a variable the
defined form does not supply*. `df-tru` is the shape:
`|- ( T. <-> ( A. x x = x -> A. x x = x ) )`, where `x` is quantified in the
defining form and `T.` has no room for it. With the slots declared it is
**1,335 definitions, 224 axioms**, and all 47,546 theorems still verify.

Every one of those is sound in Metamath and is sound here, because the defining
form *binds* the variable — which a `Definition` states with a `fresh` clause, and
which is what makes the unfold capture-avoiding. A `fresh` clause is inferred from
`Production.scopes_over`, and a `.mm` file carries no trace of binding slots:
nothing in `A. x ph` says the first slot binds in the second. So the wall was
never about soundness; it was that nothing had told the importer.

That refusal belongs to the classifier rather than the kernel for a reason worth
keeping: the kernel refuses by *raising*, which aborts a whole import over one
statement. The contract here is that doubt costs an axiom, not a build.

**And that contract is what a 25-definition sample was too small to check.** With
the slots declared, 242 of 1,335 candidates classified and were then refused on
registration — because `classify` declared every `$f` variable of the assertion a
definition `binding`, a binding becomes a *metavariable* in the context the forms
are re-parsed against, and `bind_scoped` skips `Var`s by design, they being
parameters the defined form supplies. The binder was never placed and
`unbound_parameters` reported it free. Every Metamath binder is a declared `$f`
variable — `A. x ph` needs `x` typed — so it hit exactly the definitions binding
slots exist to unlock and nothing else. A definition's parameters are its
*defined* form's slots, which is what `build_kernel_definition` always said, and
is what is declared now.

The lesson is about the evidence rather than the bug: a contract of the form
"what this returns, that accepts" is only tested by running both, over everything.

### Binding slots, and where they come from

The wall lifts by *declaring* which slots bind, and the size of that declaration
was worth measuring before writing it: **28 productions** account for all 1,123,
and ten of them for 94% of the binding occurrences —

| | | | |
|---|---|---|---|
| `cmpo` 904 | `cmpt` 791 | `wral` 582 | `crab` 419 |
| `wrex` 309 | `copab` 287 | `cab` 176 | `csb` 156 |
| `wsbc` 149 | `wex` 74 | | |

— then `coprab`, `crio`, `wal`, `ciun`, `csu`, `cixp`, `cio`, and a tail of
single-figure ones. `website/logical/metamath/setmm.py` holds the table, beside
the `equivalences` set, as *data about one library* rather than engine behaviour.

**An earlier revision of this section said `set.mm`'s `$j` annotations were the
obvious source. That was wrong**, and worth correcting rather than quietly
dropping, because the shape of the mistake recurs. Of the file's 1,204 `$j`
directives:

| | |
|---|---|
| `usage` (which axioms a proof avoids) | 1,137 |
| `restatement`, `primitive`, `congruence`, … | 62 |
| **`free_var` / `free_var_in`** | **5** |

Five, and their polarity is the opposite of what is needed: `$j free_var 'wsb'
with 'y'` marks the `y` of `[ y / x ] ph` **free**, although it sits exactly where
a binder would. So `$j` is an *exception list against an assumed default* — the
default being that a `setvar` slot binds — and reading it would still leave the
default to be supplied. Adopting that default is inference about binding
structure, which is the thing this project has twice declined for questions of
just this kind (`denotes_constant`, then `equivalences`), both times after the
inference turned out to be wrong in practice. So: a table.

Nor does position decide it, which is what any positional rule would assume:

```
citg    class S. A B _d x               the binder is the *last* token, binding B
cmpo    class ( x e. A , y e. B |-> C ) x reaches B as well as C
wral    wff A. x e. A ph                x binds ph and *not* the domain A
```

Declaring the slots is not on its own enough, and the second half is easy to
miss: the classifier's own refusals are stated over the surface variables, so they
had to become scope-aware too. `bind_scoped` — the same call `parse_definition`
makes to infer a `fresh` clause — decides which leaves are bound, and the
classifier now asks it rather than re-deriving the scopes, so what it admits is
what registration accepts. The `$d` check needed the same: a proviso naming a
binder is resolvable, because an unfold settles the leaf that binder takes and
exposes it under the binder's name.

Measured over the whole corpus, all 47,546 verifying throughout:

| | definitions | axioms | wall clock |
|---|---|---|---|
| axioms only | — | 1,559 | 1,364.7 s |
| definitions wired (§A4) | 306 | 1,253 | 1,389.7 s |
| **binding slots declared** | **1,335** | **224** | **1,456.8 s** |

So the faithful reading of `set.mm` costs **6.8%** over importing every logical
`$a` as an axiom, and the primitive basis falls from 1,559 to 224.

These three were taken back to back on one machine, which is what makes them
comparable to each other — and *only* to each other. A later container ran the
same 1,456.8 s walk in 1,861.3 s, so a figure from this table must never be
compared against one measured elsewhere; the next section shows what that mistake
looks like.

**What the 224 are**, since the tail is now short enough to enumerate:

| | |
|---|---|
| root is not a declared definitional equivalence | 119 |
| a `$d` constrains what the defined side does not supply | 92 |
| defined side is built from notation already in use | 9 |
| defining side introduces a variable nothing binds | 2 |
| defined side is a bare metavariable | 2 |

The 119 are `df-bi` and its kind — statements whose root is not `↔`/`=`, so
nothing about their shape says they define. The 9 are `df-clab`/`df-cleq`/`df-clel`
and neighbours, genuinely axioms connecting class notation to set theory.

### A `$d` names pairs, and a definition need not state all of them — *done*

**The 92 were the next item, and an earlier revision of this section said they
were `df-sb`'s shape: a `$d` over a variable in neither form.** Measured, that is
2 of them. The other **90** are a different shape entirely, and the arithmetic is
worth stating because it changed what the fix had to be:

| what the refused `$d` names | |
|---|---|
| **a spelling several binders share** (2–9 of them) | **90** |
| a variable living only in the `$e` (`df-sb`, `df-mo`) | 2 |

The unlock is the same in both cases, and it starts from noticing that a `$d` is
not one constraint. `$d x y z` is **three** — one per pair — and Edifyce's algebra
already takes one pair per proviso (`importer._distinct_provisos`). The refusal was
all-or-nothing over the whole assertion, so one unnameable variable cost every pair
the definition *could* state. It now drops the pair, and only where dropping it is
argued:

**A spelling several binders share.** `df-sup` quantifies `y` twice, and binders
are placed per *occurrence*, so `y` names two of them and no proviso can say which
(`kernel.definitions._condition_binding`). Pair it with a **parameter** and the
representation already enforces the constraint: `_bounds_are_fresh` requires every
binder's chosen leaf to be disjoint from every parameter's substitution, at every
unfold, written down or not — so the proviso was redundant. Pair it with another
**binder** and the kernel holds the *scope-aware* rule in place of Metamath's
blanket one: two binders may share a spelling where their scopes do not nest,
which alpha-conversion makes sound and which the kernel admits deliberately (its
docstring calls the blanket rule a regression). Either way the pair is redundant
or already decided, and stating it adds nothing.

**A variable living only in the `$e`.** `df-sb`'s `z` appears in `sbjust.1` and
nowhere else. Metamath makes it a mandatory variable because it re-proves the
hypothesis at every use; here the hypothesis is discharged **once**, by citation,
so no unfold ever chooses a `z` for the `$d` to constrain. What licences the
discharge is that `sbjust` holds under its own `$d` — and those provisos are
inherited (`declarative._discharge_justification`), so the constraint travels with
the obligation rather than being dropped.

Refusing is still the default for a pair neither argument covers. Nothing in
`set.mm` reaches that branch, and that is a claim rather than a coincidence: a
`$a`'s mandatory `$f` are exactly the variables of its statement and its `$e`, and
a statement variable is supplied, bound, or was already refused as free in the
defining form.

**Which is what finally reaches `df-sb` and `df-mo`** — the two definitions the
`Justification` mechanism was built for, refused until now first for their binders
and then for their `$d`. Both classify, both register, and both cite the theorem
`set.mm` proves for exactly that purpose.

One consequence is worth recording as *strictness*, not a defect. The obligation
is promoted with only the defined form's parameters as metavariables, so its
dummies (`y`, `z`) are ground leaves; the inherited provisos therefore name them
literally, and `df-sb` will not unfold under a `ph` mentioning the concrete
variables `y` or `z`. That is the once-and-for-all discharge showing its cost, as
§A4 said it would — Metamath re-proves the hypothesis per use and pays nothing.
Sound, since over-strictness refuses steps rather than admitting them, and free
for the import, which takes no definitional steps. Relaxing it means quantifying
the obligation over its own dummies, which is a separate change.

Measured over the whole corpus, all 47,546 still verifying: **1,427 definitions,
132 axioms**, at **+0.90%** wall clock — 1,878.0 s against a `develop` control of
1,861.3 s.

That control is the point, and it is worth saying why it was run. The first
measurement read 1,931 s against the 1,456.8 s in the table above and looked like
a 33% regression; the table's figures were taken on a *faster container*, and this
one reproduces the pre-change walk at 1,861.3 s. So an absolute number from that
table and one from this paragraph are not comparable, and the only honest
comparison is a same-machine A/B. (The 1,931 s run was also sharing four cores
with the test suite, which is the rest of the gap.)

### `cmpo` binds backwards, and `cmpt3` does not — *done*

Enumerating the tail found one entry of the binder table wrong rather than one
statement awkward. `df-linc` was refused for introducing a `v`, and its defining
form is `( s e. ( ( Base ` ( Scalar ` m ) ) ^m v ) , v e. ~P ( Base ` m ) |-> … )`
— the *second* binder used inside the *first* binder's domain. The table declared
`cmpo` as `{"x": ["B", "C"], "y": ["C"]}`, so that `v` read as free.

It is bound, and the definiens says so: `df-mpo` unfolds to
`{ <. <. x , y >. , z >. | ( ( x e. A /\ y e. B ) /\ z = C ) }`, an abstraction
binding `x`, `y`, `z` **simultaneously** across the whole body — `A` included. So
`y` reaches `A`, and the entry gains it.

**The instructive half is `cmpt3`, which was left alone.** Its notation is the
same shape one argument longer, `( x e. A , y e. B , z e. C |-> D )`, and widening
it by analogy is the obvious next move. It would have been wrong. `df-bj-mpt3`
unfolds to `{ <. s , t >. | E. x e. A E. y e. B E. z e. C ( … /\ t = D ) }` —
*nested restricted existentials*, not a simultaneous abstraction — so its scoping
really is strictly forward and `y` never reaches `A`. Two productions, identically
shaped, with different binding structure, and only the definiens distinguishes
them. That is the third time position or shape has been tried as a guide to
binding here and the third time it has failed; the table earns its keep again.

A binder's own domain is deliberately out of scope throughout. Each definiens does
bind it — `{ <. x , y >. | ( x e. A /\ … ) }` captures an `x` in `A` — but
`x e. A ( x )` is degenerate, `set.mm` forbids it by `$d` wherever it could arise,
and omitting it is the safe direction: an occurrence read as free costs a refused
definition, one wrongly read as bound would hide a capture.

**1,428 definitions, 131 axioms**, all 47,546 verifying.

### What is left primitive, and why almost none of it is ours

| | |
|---|---|
| root is not a declared definitional equivalence | 118 |
| defined side is built from notation already in use | 9 |
| defined side is a bare metavariable | 2 |
| defining side introduces a variable nothing binds | 1 |

The composition matters more than the count. **126 of the 130 are named `ax-` by
`set.mm` itself**, no assertion named `ax-` is classified as a definition, and no
remaining axiom is named anything but `ax-` or `df-`. The tail is `set.mm`'s own
primitive basis — `ax-1`, `ax-mp`, `ax-ext`, `ax-rep`, `ax-sep`, `ax-pow`,
`ax-inf`, `ax-ac`, `ax-groth`, the complex-number and Hilbert-space axioms, the
Frege and `ax-c*` alternate systems, and the unproved number-theory results used
as hypotheses (`ax-hgt749`, `ax-ros335`). Admitting any of them would be a defect.

That leaves four `df-` named, and three of those are axioms whatever they are
called: `df-clab`, `df-cleq` and `df-clel` connect class notation to set theory
and `set.mm`'s own literature treats them as axioms. The fourth is **`df-gmdl`**,
and it is not ours:

- `A. c e. ( mTC ` t ) …` and the two `( mUV ` c )` occurrences are *sibling*
  conjuncts of a `w3a` — checked by bracket depth, both at depth 2 — so `c`
  genuinely is free in the second, and nothing binds it.
- `mUV` is `Slot 7`, a **structure accessor**, while `c` ranges over `( mTC ` t )`,
  `Slot 4`, the type codes. So it applies a structure accessor to a type code: a
  category error independent of the scoping.
- Across the whole of `set.mm`, `mUV` is applied to `t` **fifteen** times and to
  `c` **twice** — those two. Both sibling conjuncts write `( mUV ` t )`.
- Nothing uses `mGMdl`. It appears in exactly two places in 51 MB: its syntax
  axiom `cgmdl` and this definition, both in Mario Carneiro's mathbox. No theorem
  is ever proved about it, so nothing would exercise the error.

It reads as a typo, and refusing it is right. Worth noting it is not merely
cosmetic: a definiens with a free variable the definiendum lacks asserts
`mGMdl = { t | φ(t,c) }` for *every* `c`, forcing `{ t | φ(t,c) } = { t | φ(t,c') }`
— a substantive claim rather than an abbreviation. Metamath's verifier does not
catch it because `( mUV ` c )` is perfectly grammatical (Metamath is untyped past
typecodes, and a setvar is a class); definitional soundness is left to an external
checker, and no `$j` directive exempts it. Upstream's to fix, not ours.

`df-bi` was the fifth, and is now a definition — treated next.

### `df-bi`, the one definition that cannot state itself — *done*

Every other definition in `set.mm` gives meaning to a symbol using symbols that
already have it. `df-bi` cannot, because the symbol it defines is the one the
classifier recognises a definition *by*:

```
df-an  |- ( ( ph /\ ps ) <-> -. ( ph -> -. ps ) )

df-bi  |- -. ( ( ( ph <-> ps ) -> -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) )
              -> -. ( -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) -> ( ph <-> ps ) ) )
```

`df-an`'s root is `wb`, a declared equivalence, with the defined form on one side
and the definiens on the other; test 1 passes and the rest follows. `df-bi`'s root
is `wn`. Structurally it is "not (not (L → R) and not (R → L))" — a biconditional
spelled longhand in `¬` and `→`, because `↔` has no meaning yet at the point it is
asserted. The syntax axiom `wb` is declared immediately above it; the *meaning* is
what this statement supplies, so this statement cannot use it.

That defeats all three tests, not only the first. Each presupposes that the root
*is* the equivalence and its two operands are the two forms. Here there is no such
root: the defined form `( ph <-> ps )` occurs twice, at depths 3 and 4 inside a
negation nest, and the definiens occurs twice as well. Nothing about `wn` says
which of its descendants is being defined, so tests 2 and 3 never get a defined
side to run on.

**It is the only one, and structurally must be.** A system bootstraps once.
`df-bi` is the first definition in the file and the only one asserted before an
equivalence connective means anything; all 1,428 that follow have `↔` or `=` and
use it. No second instance of the shape exists in the corpus, and none can.

Admitting it means deciding that `-. ( X -> -. Y )` *is* the conjunction of `X`
and `Y`, hence that the nest is an equivalence between the two forms — semantic
reasoning about what the connectives mean, inferred from shape. That is the fourth
time this project would have inferred a logical property rather than declaring it,
and the previous three were each tried and each failed:

| | inferred first | now declared |
|---|---|---|
| `denotes_constant` | read off the constructor's shape; had holes | per production |
| `equivalences` | "two slots of one sort" admits `→` as readily as `↔` | per database |
| binding slots | position tried; `citg`, `cmpo`, `wral` each break it | per production |

So the route taken is a **declaration**, and it turned out to be cheaper than
inventing one: **`set.mm` already carries it.** Among the file's 1,204 `$j`
directives is exactly one `definition` directive —

```
$j definition 'dfbi1' for 'wb';
```

— and `dfbi1` is `|- ( ( ph <-> ps ) <-> -. ( ( ph -> ps ) -> -. ( ps -> ph ) ) )`,
`df-bi`'s content the ordinary way round. `setmm.RESTATEMENTS` is written from
that rather than invented, and `classify` reads the two forms off the restatement
while naming the definition for the assertion — `df-bi` is what stops being an
axiom, and a definitional step cites `df-bi`. Naming it for `dfbi1` would shrink
the reported basis while leaving the axiom in it.

**Why this is a declaration and not a loophole.** A table saying "read this
assertion's shape from that theorem" could point anywhere, and a wrong entry would
register a bogus definition while all 47,546 proofs still verified — they take no
definitional steps, so nothing would notice. `_restatement` therefore checks five
things, and the last carries the weight:

- the restatement must exist in the database;
- it must be **logical**. A syntax `$p` asserts well-formedness, not truth;
- it must be **proved**, not asserted. An asserted one would be a second axiom
  about the same notation with nothing tying it to the first;
- it must carry every **`$d`** the assertion does. The two forms come from the
  restatement, so its provisos travel with them, and one on the assertion that the
  restatement lacks would simply be dropped — turning a conditionally-asserted
  statement into an unconditional rewrite. Compared pairwise, since `$d x y z`
  covers `$d x y` and a group-wise comparison would not see it;
- **its proof must cite the assertion it restates.** No structural test can
  confirm that `-. ( ( L -> R ) -> -. ( R -> L ) )` *is* the biconditional of `L`
  and `R` — deciding that is the semantic reading being avoided. What is checkable
  is that the restatement was *derived from* the assertion, which makes it a
  consequence of the axiom being reclassified rather than an unrelated equivalence
  pointed at it;
- and **its proof must actually derive it**. Citing is not enough: a `$p` that
  decodes and cites but concludes something else would otherwise be taken at its
  declared word, and the definition registered at the *assertion's* position while
  the walk rejects the restatement only later — or never, if `limit` stops first.
  Nothing retracts a definition, so this has to happen before it is used.

  That check is possible only because `import_proof` runs Metamath's own stack
  machine over the **database**: `dfbi1` cites `impbi`, `con3rr3` and `mt3`, every
  one proved *after* `df-bi`, so anything requiring them to be in the library would
  refuse the case this exists for. What it settles is that the derivation is
  well-formed and reaches the declared statement; that the theorems it cites are
  themselves proved is the walk's business, and the walk checks them.

That last check is read off the proof's **decoded steps**, and the distinction is
not pedantic. A compressed proof carries a label *table* listing what it may cite
and a letter stream saying what it does; the first version of this read the table,
and a proof listing `df-bi` beside a derivation from something else entirely — a
table entry never selected — passed it. The check that the whole mechanism rests
on was satisfiable without citing anything. Found by review, reproduced against
this section's own fixture, and pinned.

Reading a later theorem's statement is a deliberate forward reference, and worth
naming as one. It is the narrowest available: what it supplies is *which two forms
the assertion relates*, a fact about the file settled by parsing, of the same kind
as `equivalences` and `BINDERS`. What licences the definition is `df-bi` itself,
which sits at its own position. The restatement is evidence about a reading, not a
step in a proof.

**1,429 definitions, 130 axioms.** The basis now contains nothing `set.mm` itself
calls `df-` except the three class axioms its own literature also calls axioms,
and `df-gmdl`'s mathbox typo.

**Abstract binders make both of set.mm's justifications unnecessary — and set.mm
declines that on purpose.** Worth recording, because it decides what the binding-
slot work is *for*.

The kernel already stores a `fresh` binder abstractly, by index
(`kernel.terms.Bound`): `x ⊆ y ≝ ∀z(z ∈ x → z ∈ y)` is held as
`∀⟨0⟩(⟨0⟩ ∈ x → ⟨0⟩ ∈ y)`, and the *consumer* of an unfold picks the concrete
name. That is what turns capture from a rejection into a rename — `z ⊆ b` unfolds
to `∀w(w ∈ z → w ∈ b)` rather than failing. What survives is not a residual
occurs-check but the check that the *chosen* name is a good one, which cannot be
removed while terms round-trip to the user's surface syntax: a proof line is text
in the system's own grammar, and a grammar has no notion of an index, so the
boundary where names come back is where the check must live.

Now apply that to `df-sb`. Its `y` appears on the right only, so in Metamath the
definition genuinely commits to a name, and `sbjust` is the theorem that the
commitment does not matter. Declared `fresh`, the defining form is
`∀⟨0⟩(⟨0⟩ = t → ∀x(x = ⟨0⟩ → φ))` — **no choice is made, so there is nothing to
justify**. `A. y (…)` and `A. z (…)` are both unfolds of the same defined form, and
their equivalence follows from two definitional steps and transitivity.

`set.mm` states this argument itself, in `df-sb`'s own comment:

> The hypothesis asserts that the definition is independent of the particular
> choice of the dummy variable `y`. **Without this hypothesis, `sbjust` would be
> derivable from propositional axioms alone: one could apply the definiens for
> `[ t / x ] ph` twice, using different dummy variables `y` and `z`, and then
> invoke `bitr3i`** … This would jeopardize the independence of axioms.

"Apply the definiens twice and invoke `bitr3i`" is exactly two unfolds and
transitivity. So the mechanism works and its authors deliberately decline it: it
would make `sbjust` derivable and weaken an independence claim about their axiom
system. The two routes import the same theorems under different metatheoretic
discipline, and a faithful import wants Metamath's.

Which leaves `justification` earning its keep on the obligations no representation
removes — an existence lemma of the `df-div`/`df-sqrt` kind, which is a claim about
what exists rather than about how a binder is spelled. Both set.mm cases may cease
to need it once binding slots land; that is a success of the representation, not a
loss of the mechanism.

One consequence of the abstract representation is now usable directly: a
definition's own proviso may **constrain a binder** by the name its author
declared it under (`disjoint(z, x)` where `z` is the `fresh` name), resolved at
each unfold to whatever leaf the binder takes there. Before, the condition was
checked before the binders were resolved, so `z` in a proviso could only mean the
literal token `z`.

What is left primitive is enumerated once, under "What is left primitive, and why
almost none of it is ours" above — deliberately not repeated here, because a
second copy is a second thing to update and the first time these numbers moved
only one of the two copies did. The short of it: 126 of the 130 are `set.mm`'s
own `ax-`, and no assertion Metamath names `ax-` is classified as a definition.

None of the three tests is load-bearing alone, and the set is not trusted to be
complete. Test 1 admits an implication, since `( ph -> ps )` has a
biconditional's shape; test 3 then admits `ax-1`, because `ph` is notation not yet
in use the first time it appears — which is what test 2 is for, and which was
found by running the classifier over `set.mm` rather than by reasoning about it.
Any doubt defaults to axiom, which costs a longer proof rather than an unsound
one. What is *behind* that default is less than it sounds: the kernel refuses a
definition whose defining form introduces a leaf the defined form does not
supply — the capture half of admissibility — and nothing more. Non-circularity
and conservativity are untreated there, as in Metamath, so those refusals are
this module's and have nothing behind them.

### A4 wired in

`corpus.walk` takes `equivalences` and registers the definitional ones as it
reaches them. Naming none — the default — imports every logical `$a` as an axiom
exactly as before, so no stored system and no existing caller changes behaviour.

Two things had to be right, and neither was obvious from the classifier alone.

**Definitions land before their own rule.** A definition may only give meaning to
a symbol the system does not already reason with
(`declarative._require_a_fresh_defined_form`), and a definitional `$a`'s own
inference rule is stated over the very symbol it defines. Register the rule first
and every definition refuses itself. So the walk classifies and registers the
definition, *then* promotes the assertion — the same order the classifier's
"notation not yet in use" test already assumes.

**A definition whose defined form the grammar already spells registers no
notation.** This was the blocker that forced the earlier revert, and it was worth
more than it looked. A sort tries its own productions before its notations, so a
notation for an imported definition's defined form — grammatical from its own
syntax axiom — can never be *reached* by a parse. But it is scanned by every parse
that falls through to `try_definitions`, and, worse, any notation in scope
switches off the first-character leaf index that keeps a parse's cost proportional
to the formula rather than to the grammar (`UnionPattern.leaf_candidates`). On a
1,441-production grammar that is the difference between free and not:

| 5,000 theorems | wall clock |
|---|---|
| axioms only (before) | 15.3 s |
| definitions wired, notation registered | 37.4 s (**2.4×**) |
| definitions wired, notation skipped | **15.7 s** |

`UnionPattern.notation_for` is the split that allows it: build-or-find the
notation without registering it, so the builder can take its analysis of the
defined form — which slots, at which sorts — and extend the grammar only when
nothing else spells the form. The kernel definition is stated over the
production's constructor either way, which is what made the notation redundant
rather than merely unused.

Measured as matched pairs in one session, with every theorem verifying either way:

| | axioms only | definitions wired | cost |
|---|---|---|---|
| 5,000 theorems (30 definitions) | 15.3 s | 15.7 s | +2.6% |
| 20,000 theorems (134 definitions) | 280.2 s | 292.9 s | +4.5% |
| **47,546 theorems (306 definitions)** | **1,364.7 s** | **1,389.7 s** | **+1.8%** |

So the whole corpus still imports and verifies in 23 minutes, and the definitions
cost under two per cent of it. The residue tracks the number of definitions rather
than the corpus — a statement parse per logical `$a`, and the freshness scan over
the system's axioms and rules at each registration — which is why the proportion
*falls* as the walk lengthens: definitions are declared early and the theorems
that follow them are not.

The classification the walk produces is identical to the standalone classifier's,
breakdown included (306 definitions; 1,123 / 119 / 9 / 2 refused). Worth stating
because it is not a restatement: the walk derives `in_use` from the order it
actually registers in, and the classifier derived it from a separate pass.

*What remains*: `app/db/metamath_store.import_corpus` does not pass
`equivalences`, so a stored import is still all-axioms — the definitions would
have nowhere to go, since `corpus_spec` carries none. Storing them is the same
work as §3.2.

`df-div`/`df-sqrt` define via `iota` and will need the `fresh`-aware path with
their existence lemmas as cited premises — the first real test of whether the
kernel's refusal is the right arbiter or too strict.

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

### 4.5 Descriptions, authorship, and the title Metamath does not declare — *done*

`comments.py` read a `$( … $)` body into prose and attributions and had **zero
production callers**: parsed, then discarded on every run. It is now stored, and
that raised the question of where.

**Keyed by `(system, label)`, not by a foreign key into the thing described.** A
Metamath label lands in one of four places depending on what the importer made of
its statement — a **production** (a syntax `$a`), a **definition** (`df-un`), a
**primitive theorem** (`ax-ext`), or a **proof** and its theorem (a `$p`). Four
description columns would be four migrations and four join paths for one concept.
`label_descriptions` is one of each, and the label is what a reader cites anyway.
Attributions hang off it as rows — `set.mm` credits **131 people** across
**60,661** clauses, and the questions asked of an authorship record are aggregate.

Everything is stored **verbatim**, which is `comments.py`'s reasoning carried into
the schema: `set.mm` misspells four kinds (`Resised`, `Prove shortened`) and
malforms 22 dates (`25-Jan-20178`, `XX-May-2017`), so `dated` is a string rather
than a date and `kind` is not an enum. Normalising either would mean deciding what
an upstream typo meant.

**Titles.** Metamath declares none — no keyword, no field. What it has is the
convention that a comment opens with a one-line summary, and over `set.mm` that
holds well enough to use: a median of **53** characters and 108 at the 90th
percentile.

```
sqrt2irr   The square root of 2 is irrational.
ax-ext     Axiom of extensionality.
df-un      Define the union of two classes.
```

So `Description.title` is the first sentence, and the sentence boundary is the
whole of the work. It ends at the first `.`/`!`/`?` outside a **math span** and
outside a **parenthetical**, both measured: a `` ` … ` `` span is ASCII Metamath
and ASCII Metamath is full of stops (`-.`, `e.`, `A.`, `T.`), which cuts 613
titles to *"If ` ph ` is a wff, so is ` -."*; parentheticals carry the
abbreviations, costing a further 131 (*"Change the bound variable (i.e."*).
Balancing brackets beats a list of abbreviations and does not go stale.

`proofs.title` is a **column**, not a derivation: an imported proof fills it from
the same parse, and it is then editable, which a derived first sentence could
never be. `name` stays the label — that is what a citation spells and what the
slug is built from — so identity and sentence never have to displace each other.
The *prose* is not copied onto the proof: `description` rides on every
`ProofSummary`, and a corpus comment runs to paragraphs, so 47,000 of them would
land in a list view. It is read from `label_descriptions` on the single proof.

Two bounds worth recording, both from review. The descriptions stop at the same
**horizon** the grammar does — `corpus_spec` builds from what is declared before
the last walked theorem, so a `limit`ed import that described past it would attach
prose to labels its own rows do not contain. And the attribution recogniser bounds
each captured part to the width of the column it lands in (`KIND_MAX`, `WHO_MAX`,
`WHEN_MAX`), so an over-long capture is refused at the parse rather than
truncated: it is prose that fitted the shape, and recording it would credit
someone with something they did not do. `set.mm`'s longest are 48 / 53 / 11, so
all 60,661 still match.

Served on `ProofSummary`/`ProofDetail`, with the corpus's own record (prose plus
authorship) on the single proof read, and on
`GET /formal-systems/{id}/labels/{label}` for the three kinds of label that have
no proof at all — which is where the interesting prose lives.

What was deliberately not here — `set.mm`'s section outline — is §4.6 below.

---

### 4.6 The outline a file draws with comments — *done*

Metamath declares no sections either. The convention is a comment of the shape
rule / title / rule, and **which punctuation drew the rule is the depth**:

======  ==============  =====  ============================================
Rule    Level           Count  Example title
======  ==============  =====  ============================================
`####`    part             21  CLASSICAL FIRST-ORDER LOGIC WITH EQUALITY
`#*#*`    section         163  Pre-logic
`=-=-`    subsection    1,115  Inferences for assisting proof development
`-.-.`    subsubsection   604  Universal quantifier for use by df-tru
======  ==============  =====  ============================================

**No new table.** `proof_folders` is already a per-system tree with a parent, a
name and an ordering, which is what an outline is — so the schema cost is one
`description` column, for the prose 308 headers carry after their title (the
part-level ones run to hundreds of lines; one is 525). A header closes every open
section at its level or deeper, so the nesting is a stack, and each proof is filed
under the **deepest** section covering it. On set.mm: 1,903 folders, 21 roots, and
every one of the 50,550 assertions covered.

**Recognition is tight, because the alternative is reading prose as structure.** A
rule line must begin with the four-character motif *and* contain nothing but that
motif's characters. Charset alone will not do — a line of bare hyphens is a subset
of both `=-=-` and `-.-.`, and confusing them silently reshuffles the tree.

**Position came from the parser.** A comment previously reached a reader as a bare
string, and a header means nothing without knowing where it sits. `Commentary`
now carries `at`, an index into `Database.order`: how many assertions precede the
comment. It is computed by bisecting the label positions after the parse rather
than threaded through it, and `Database.comments` stays as a property, so every
existing reader is untouched. The parser still recognises nothing — a header is a
comment convention, and `sections.py` interprets it, exactly as `comments.py`
interprets a description.

Two things are worth stating because they are easy to get wrong. Placement takes
a position in `Database.order`, **not** a walk index: a section covers statements,
and the walk visits only the provable ones — a whole subsection may be nothing but
syntax axioms. And two headers may share an `at` (a part followed immediately by a
section, with no statement between), so a folder is keyed by its section's index
and not by that position; a dict keyed on it would keep only the deeper of the
pair.

Served whole at `GET /formal-systems/{id}/folders` — 1,903 nodes is one small
response, and paging a tree costs a request per expansion for no benefit at that
size — with a per-folder count of the proofs sitting *directly* in it, since a
part-level node holds nothing itself and a subtree total would make every ancestor
look equally full. The system page renders it as a collapsible tree.

### 4.7 An import nobody could read — *done*

The first real import to a deployed database landed 10,000 theorems and showed
none of them. Everything had stored correctly; every proof was `valid`; all of it
was invisible. Three causes, and they are worth recording because each looked
locally right.

**A corpus was ownerless *and* unpublished, and those are two different things.**
Ownerlessness is a statement about provenance, and it is the guard that stops
`POST /proofs/{id}/verify` writing `valid=False` over imported structure — it
reads `owner_id`. Publication is what makes a row *readable* by someone who does
not own it, and an import set neither. So `/proofs` (owner-scoped) could not see
them and `/proofs/public` (`published_at IS NOT NULL`) omitted them: 10,000
verified proofs reachable by nobody, `GET /proofs/{id}` 404 for everyone. The two
are now decided separately — published as written, still ownerless — and the
write-back guard is untouched.

**The deepest layer stayed a draft.** `layered_systems` published a layer "exactly
when something inherits from it", which reads as a tidy consequence of §5.1 and in
practice hides most of a corpus: the leaf holds the bulk of it (7,325 of the first
10,000 theorems), and being ownerless too, nobody could open it at all. The
argument that justified publishing the others — an imported layer's grammar is
fixed by the file the moment it is written, so there is no draft period to protect
— applies to the leaf identically. Every layer is now published, at one instant.

**And there was nowhere to browse to.** `/proofs` is owner-scoped, `/proofs/public`
is a flat global list; neither could answer "what is in this section". The outline
was a table of contents for a book with no pages. `/proofs/public` now takes
`formal_system_id` and `folder_id`, and a scoped page orders by **position** —
file order for an import — rather than by publication recency, which cannot order
rows that all published at the same instant and would otherwise fall through to
`created_at DESC` and hand back a section backwards. Both orderings end in `id`,
because an import is also the one writer whose rows tie on every other key:
`created_at` defaults to `now()`, which under Postgres is the *transaction's*
timestamp, so a whole batch shares it — and a tied block ordered at the planner's
discretion is a list that repeats and skips rows as it is paged.

Publishing an imported proof meets the same three conditions `_require_publishable`
asks of the interactive path, which is why it is safe rather than a special case:
the system is published, the proof verifies (a rejected one stays a draft), and it
has no reference links that might still be drafts — a corpus cites through
`promoted_theorems`, not proof-to-proof. The frontend makes a folder holding proofs
selectable and lists them beside the tree.

**When** publication happens is its own decision, and the obvious answer is wrong.
Setting it as each proof is written looks natural and breaks a batched run:
`_checkpoint` commits every `batch` theorems, so each batch becomes world-visible
as it lands, and an import that dies partway leaves a *partial* corpus published —
its proofs not yet pointed at the library entries they establish, since
`theorem_id` is written below the walk rather than in it. A committed batch cannot
be rolled back, so the only defence is not to publish until there is something
whole to publish. It is one statement over rows already written, issued after the
theorem links, so deferring it costs a round trip and buys atomicity: a run that
fails anywhere leaves everything a draft. The systems cannot be deferred the same
way — a child's terms intern against a chain that has to exist before the walk
reaches it — which is why the two are decided separately.

**What publishing an ownerless corpus opened, and what closed it.** `_is_readable`
grants a published proof to anyone, so publication also made `POST
/proofs/{id}/verify`, the dry-run `/cite`, `/lines` and `/lines/remove`, and the
citation search reachable without an account — on every imported proof. Each of
those rebuilds the proof's whole system and re-checks it, with no cache in front
of the build, which on `set.mm` is a 1,441-production grammar compiled per
request across 47,546 proofs. Nothing durable came of it (a non-owner's
transaction is never committed), and that is exactly what makes it worth
refusing: the work is real and the result is thrown away. All five now require a
signed-in caller. It costs a legitimate caller nothing — applying already
required ownership, and an owner is signed in by definition — and the *reads*
beside them (`GET /proofs/{id}`, `/structure`) are unchanged, which is the line:
reading a published proof is open, checking one is not.

**`--owner EMAIL` for the case where a corpus is somebody's.** Ownerlessness is
right for a shared library and wrong when a person wants the import in their own
lists, so `scripts/import_metamath.py --owner` hands every layer and every proof
to one registered user. It is opt-in because it gives up the guard ownerlessness
*is*: the owner-scoped routes can then reach the import, so a verify on one of
its proofs writes its verdict back — and a verdict of `False` calls
`store_proof_lines`, whose first act is to drop the imported structure.
(`scripts/restore_proofs.py` makes that trade deliberately, to reach the
owner-only apply path.) Folders stay ownerless either way: an outline is the
file's structure, and `get_system_folders` reads an owned folder as a user's
private one. The address is looked up rather than created, and the layer names
are checked against the owner's existing slugs first, because `formal_systems` is
uniquely indexed on (owner, slug) for owned rows.

---

### 4.7 What the reader is shown — *done*

Everything above is about what an import *stores*. This is the page it lands on,
and four things about it were wrong once a real corpus was on it.

**One view, not two.** The proof page showed a source pane beside a verification
pane. Authoring, those differ — one is editable text, the other is what the
checker made of it. *Browsing*, they are the same lines twice. The browse page now
shows a single verification-style list and the editor keeps the pair.

**The notation switch belongs to the checked lines.** It used to re-spell a
separate `<pre>`, so choosing `unicode` changed one pane and left the diagnostics
next to ASCII in the other. The rows now come from the **stored structure**
(`GET /proofs/{id}/structure`) rather than from `ProofDetail.result`, which is
what puts a re-spelled term and the verdict on it in the same row. `result` is
still what the overall badge and the cross-proof errors are read from — it is a
report about the *check*, not about a line.

**A `latex` reading is typeset.** Showing `\sqrt{2} \in \mathbb{R}` as text is
strictly worse than the `unicode` reading, which is the thing LaTeX-as-display was
for (§4.2a). The frontend sets it with KaTeX. What decides that a reading is TeX
is its **name**, which is the same judgement the importer makes when it turns
`latexdef` into the notation called `latex` (`display.py`) — there is no per-
notation format stored, and inventing one would mean a column on a table that is
thousands of rows of template pieces. A reading KaTeX will not parse falls back to
its source rather than to KaTeX's red error: a projection is derived per production
from a token map nobody checked against a TeX parser, so a miss is ordinary, and a
line set in red says "this proof is wrong", which is not what happened.

**The label is not the title.** §4.5 gave a `$p` a title and the page put it
*under* `name`, which reads as `setind` with a caption. A citation spells the
label and a human reads the sentence, so the sentence is the heading and the label
sits beside it as what the rest of the library refers to. The description and the
attributions move above the proof for the same reason: what a theorem says and who
proved it is what a reader wants first, and 30 lines of Hilbert-style plumbing is
a long way to scroll for it.

**And where the whole thing came from.** An imported proof has no author to
credit; the library it came from is the credit, and nothing on the page said so.
`formal_systems.provenance` is one sentence recorded by the import
(`metamath_store.metamath_provenance`), on **every layer of the spine** rather
than on the leaf — a theorem is filed in the layer its own section falls in, so a
propositional lemma sits on the root and came from the same file. On the system
rather than on its proofs because it is a fact about the corpus: one row instead
of 47,000 copies, and a reader of a proof already fetches its system.

### 4.8 The markup inside a comment — *partly done*

A survey of what `set.mm` carries and the import did not keep, counted rather than
guessed. Two of the findings are shipped; the rest is recorded here so the size of
each is known before it is picked up.

**Cross-references — shipped.** A comment writes `~ label` to point at another
statement, and the file does this **21,787 times across 12,389 comments**: 21,336
naming a statement, 242 a URL, 32 a page of the Metamath website, 177 resolving to
nothing. Kept verbatim in the prose it was punctuation — a reader saw `~ ax-13` and
could do nothing with it — and the *reverse* question, "what was built on this",
could not be asked at all. `label_references` makes it both a link and an index.

Three details are measured rather than assumed, and each would have been got wrong
by the obvious reading:

- **`~~` is an escape**, not two references. 84 of them, every one inside a URL,
  where the naive read turns `…/~~hirstjl/primer` into a reference to `hirstjl`.
- **Targets are whitespace-delimited and nothing else.** Stripping trailing
  punctuation resolves *zero* further labels, and four of set.mm's labels genuinely
  end in a `.` — so the tidying rule costs accuracy and buys nothing.
- **The span is stored, not just the target.** `start_offset`/`end_offset` index
  the stored prose, so rendering a reference as a link is a slice. The alternative
  is the markup rule implemented in the engine, again in the API, and again in the
  browser.

**The discouragement markers — shipped.** `(New usage is discouraged.)` (5,169)
and `(Proof modification is discouraged.)` (1,787) are decisions about the
statement wearing the costume of a sentence. As two booleans a reader gets a badge
and an authoring tool gets a filter. Two things here were also measured: 43 of the
modification markers are **hard-wrapped mid-clause**, so matching before the
unwrap undercounts (the survey's own first figure, 1,744, was wrong for exactly
this reason); and a recogniser loose enough to catch the corpus's one typo
(`New usaged`) must still be tight enough to refuse its one prose aside, a TODO
note whose sentence happens to contain "is discouraged".

**What is still dropped**, with the count that says how much it is worth:

| | count | note |
|---|---|---|
| `$j` markup directives | 1,222 in 1,203 blocks | **Read and stored** — see §4.9 and §4.11. |
| comments on non-assertion statements | 1,621 | 606 before a `$c` ("Absolute value function." — what a *symbol* means, and nothing else in the file says it), 432 before a `${`, 302 before an `$e`, 123 before a `$f`, 74 before a `$v`, 66 before a `$}`, 18 before a `$d`. `$e`/`$f` are labels and would key into `label_descriptions` unchanged; `$c`/`$v` declare tokens and need a token key. |
| `[Author]` bibliography refs | 5,271 across 135 works | **Read** — see §4.10. |
| `$t` non-definition directives | 12 kinds | `htmlvarcolor`, `htmltitle`, `htmlhome`, `exthtml*`, `htmldir`, `htmlcss`, `htmlfont`. Only `htmlvarcolor` has content value — the typecode-to-colour legend, which `althtmldef`'s `<SPAN>`s already encode per token. |
| front matter and dormant blocks | 56 + ~60 | Including commented-out mathematics, the largest 26 KB. |
| `proof_references` for an import | — | **Not a gap** — settled in #213. That table is the alias-lemma mechanism (`[alias.line]`, with a transitive re-parse behind every verify); a Metamath step cites a *theorem*, which resolves through `promoted_theorems`. The graph an import does build is served from `proof_lines.rule` at `GET /proofs/{id}/citations`. |

Total prose the import still drops: **374,876 characters**.

### 4.9 `$j`, and a claim of §4.8 that was wrong — *done*

`$j` is where a `.mm` file says the things Metamath's language has no keyword for.
`set.mm` writes **1,221 directives across 1,203 blocks**, and the distribution is
lopsided: `usage` 1,136, `restatement` 29, `primitive` 11, `congruence` 6,
`syntax` 4, `garden_path` 4, then a tail of ones and twos.

One shape covers all of them — `keyword arg* (preposition arg*)* ;` — so
`metamath/markup.py` reads rather than switching per keyword, and nothing there
interprets. It is the same little language as `$t`, so the scanner both use now
lives in `metamath/directives.py` instead of in two copies.

**Prepositions are a closed set** (`as`, `avoids`, `for`, `from`, `of`, `with`),
which is not a tidiness point: `garden_path` is written in *bare math tokens*
(`garden_path ( A => ( ph ;`), and an open reading takes its `A` and `ph` for
prepositions and invents clauses nobody wrote.

**The claim in §4.8 that `$j` states what `setmm.py` hardcodes was wrong**, and
worth correcting rather than quietly dropping. Three of the four tables *are*
declared, and are now checked against the file
(`tests/test_setmm_against_its_markup.py`):

| table | what the file says |
|---|---|
| `EQUIVALENCES` | `equality 'wb'`, `equality 'wceq'` — exactly the two |
| `RESTATEMENTS` | `definition 'dfbi1' for 'wb'`, and `justification 'bijust' for 'df-bi'` the other way round |
| `ASSERTION_TYPECODE` | `syntax '|-' as 'wff'` |

The fourth, `BINDERS`, is **not** derivable from `$j` and `setmm.py` already said
so. What the file carries is `bound 'setvar'` — which *sort* is bindable, one
directive — and `free_var`, an **exception list** of two naming slots that look
like binders and are not. Nothing in `$j` says that the `x` of `A. x ph` scopes
over `ph` while the `A` of `A. x e. A ph` does not; that is read off each syntax
axiom's statement, which is where the answer is. The two exceptions do not even
relate to the table the same way — `wsb` is in it (its `y` is the exception),
`wcdeq` is absent entirely (nothing about it binds) — which is the sharpest form
of the point.

Checked, not derived, and deliberately: Edifyce imports any `.mm` and most carry
no `$j`, so reading one where it exists would make an import's behaviour depend on
whether the file happened to annotate itself. Agreement is what the directives are
good for.

**`usage … avoids …` is stored**, being 93% of `$j` by volume and the only part
carrying content a reader wants: 3,107 edges over 47 avoided statements, headed by
`ax-12` (435), `ax-10` (431), `ax-11` (398), `ax-13` (373). It records a result
about the *proof* rather than the theorem — this one is derivable without that
axiom — and there is nowhere else to read it from, since the avoided statement is
usually nowhere in the citation graph, that being the point. `label_avoidances`
gets its own table rather than a column on the description, because a `usage`
directive is about a label whether or not the file also documents it.

Stored as the file's **claim**. Metamath's own verifier checks these against a
proof's transitive dependencies; Edifyce does not, and what would is a closure over
`proof_lines.rule` — which is indexed for exactly that shape of question. Left as
the next thing rather than implied.

**Upgrading a corpus already imported.** The migration adds an empty table and two
`false` columns; the prose behind them still has its markup in it, and nothing
re-reads it. `scripts/rebuild_markup.py` does, and needs no `.mm` file: references
were always extracted from the assembled prose and their offsets index exactly
that, so reading `label_descriptions.text` again yields what a fresh import would
have written. Idempotent by construction — a row it has already fixed has no
marker left to find, so the flags are OR-ed in and never assigned.

---

### 4.11 What the `$j` directives are stored as — *done*

§4.9 read them and stored one keyword. This stores the rest, and the shape is
what makes that one table rather than twenty-four.

Every name-carrying directive flattens to a **claim** — a subject, a kind, and at
most one object — and the two forms a directive takes are what produce it:

- with a preposition, the first argument is the subject and each value of each
  clause is an object (`usage 'a1i' avoids 'ax-11' 'ax-12'` → two claims);
- without one, every argument is a subject asserting the same thing about itself
  and there is no object (`primitive 'wn' 'wi'` → two claims).

Over `set.mm` that is **3,364 claims of 24 kinds over 1,329 labels**, from 1,222
directives. `usage_avoids` is 3,109 of them; the rest is the content §4.8 counted
as dropped — `restatement_of` 29, the `natded_*` family 175, `condcongruence` 9,
`primitive` 11, `equality_from` 6, `congruence` 6, and a tail.

**The kind keeps its preposition** (`equality_from`, `notfree_from`) because the
preposition is part of the relation's identity: those two share a keyword-adjacent
word and mean different things. And the kind is stored **as the file spells it**
rather than mapped to a vocabulary of ours, for the reason an attribution's `kind`
is kept verbatim — a closed set would have to be maintained against a file free to
add to it.

**Twelve directives are skipped**, by a deny-list rather than an allow-list so a
keyword some future file invents lands as data rather than being dropped in
silence. What it excludes is the four shapes whose arguments are not names:
`varcolorcode` and `altvarcolorcode` (colour tables for Metamath's own site — the
same reason `htmldef` is skipped), `garden_path` (bare math tokens), and
`unambiguous` (whose argument names a parsing algorithm). `type_conversions`
carries no argument at all.

`label_avoidances` **became** this table rather than sitting beside it. It was
already the claim shape with the kind implied by the table's name, and a second
table of identical columns for `restatement` would have been the drift
`tests/database.py` warns about in the small.

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

Items 2–4 are **done**; they are struck rather than deleted because each records
a decision worth not relitigating.

1. **`$t` + Unicode source + term-fold renderer** (§4) — wanted now, and part of A3.
2. ~~**Store the imported library.**~~ *Done* (§3.2) — but split by **provenance**
   rather than by kind, which is the opposite of what this item proposed. A
   measurement overturned it: building 1,559 axioms-as-rules eagerly would have
   put seconds on every verify. `promoted_theorems` holds both kinds and a
   `primitive` column records which is which.
3. ~~**A4 definition classification.**~~ *Done* — wired into the walk, and it did
   land before the bulk store as this item wanted.
4. ~~**Persist the parse.**~~ *Done* (§1.3) — the walk stores the system, its
   proofs, their line graphs and their terms. The scale half is done too: the
   walk extends one live system's grammar in place rather than rebuilding it, so
   a whole-corpus store no longer re-promotes the library at each notation change
   (§1.4, 16× on 20,000 theorems). With item 2 settled, an imported proof
   re-checks from its rows — measured over set.mm's first 1,000 theorems.
5. **B1 + B2**, then **B4** and **B3**; then the stretch items **B5 / B6**. The
   tactic framework and closure solver come first because they shorten *new*
   Edifyce proofs as well as imported ones.

The throughline: keep the property that makes Metamath trustworthy — **a small
kernel checking a fully primitive object** — and add the **elaboration gap** it
deliberately omitted. Verifiability and generality are preserved by construction;
altitude is what we add.
