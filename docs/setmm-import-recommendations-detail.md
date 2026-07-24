# set.mm import — recommendations in depth

Companion to [`setmm-import-and-proof-altitude.md`](setmm-import-and-proof-altitude.md),
which diagnoses *why* Metamath's `sqrt2irr` is verbose and lists the enhancements
at a glance. This note expands each recommendation with the reasoning behind it
and worked examples in real Edifyce DSL syntax and real `set.mm` content.

Notation used below: Metamath statements are quoted verbatim from `set.mm`
(`|- …`); Edifyce fragments use the compiler DSL seen in `tests/zfc_systems.py`
(`InferenceRule`, `Define … as …`, `assume`/`derive` subproofs,
`side_conditions:`, citations like `[MP, 1, 2]` / `[Def, n]` / `[Alias.n]`).

---

## A preliminary worth stating: syntax steps vanish for free

Before the numbered items, one structural fact that reshapes several of them.
Look at the first ~50 tokens of `sqrt2irr`'s label table:

```
vx vy vz  c2 wcel cv cdiv co wceq cz wrex cn c1 clt wbr wne wral  ralbidv
wi wa vn  csqrt cfv cq caddc  peano2nn breq2 imbi1d nnnlt1 pm2.21d rgen …
```

Roughly half are `c*` (class constructors: `c2`, `cdiv`, `csqrt`, `cq`, …), `w*`
(wff constructors: `wcel` for `∈`, `wceq` for `=`, `wi` for `→`, `wral` for `∀…∈`,
…), or `v*`/`cv` (variable references). **These are not logic — they are
Metamath *proving that the formula is well-formed*.** Metamath has no parser; a
proof interleaves syntax-construction steps with inference steps because
well-formedness is itself a theorem to be proved.

Edifyce **has** a grammar (`Pattern`/`UnionPattern`/`Regex`), so well-formedness
is decided by parsing, not by proof steps. Every `c*`/`w*`/`cv` step in a Metamath
proof therefore **disappears** on import — it becomes part of how the line's
formula is parsed, not a line of its own. This is a large, essentially free
reduction in step count, and it's why the decoder (A2) must *classify* each cited
label as syntax vs. logic. It also means Edifyce's "primitive" proof is already
meaningfully shorter than Metamath's, before any Tier-B automation.

---

# Tier A — prerequisites for a faithful, verifiable import

## A1. Schematic theorem application ("theorems as rules")

**First, a distinction that decides when this is even needed.** "Theorems are
templates" is true, but it splits into two cases by *what kind of variable* is
re-instantiated:

- **Object / term variables** (Metamath `setvar`; a free term position). In a
  system with `∀` and universal instantiation, templating is an *object-level*
  rule: prove `⊢ φ(x)`, generalise to `⊢ ∀x φ(x)`, re-instantiate `⊢ φ(t)`. **No
  new machinery needed.** For example `nncn |- ( A e. NN -> A e. CC )` is, in ZFC,
  reducible to the single sentence `∀x (x ∈ ℕ → x ∈ ℂ)` plus UI: ℕ and ℂ are
  sets, so nothing schematic is required — Metamath only *states* it with a class
  variable for convenience (you can drop in `(A/B)` without first proving it a set
  and doing an explicit ∀-elim). Edifyce's ND ZFC already supports this path
  (∀-introduction via the eigenvariable subproof, ∀-elimination as a rule), so for
  set-level facts like `nncn` the object-level idiom is the *better* surface and
  A1 is unnecessary.

- **Formula variables** (Metamath `wff`), and rule/proof schemes. FOL **cannot
  quantify over these** — there is no `∀φ`. A theorem whose reuse substitutes a
  *formula* is irreducibly a scheme, a statement in the *metalanguage*, and **no
  object rule can instantiate it.** This is the case A1 exists for. Canonical
  irreducible examples: the propositional axiom `(φ → (ψ → φ))` (the language has
  no quantifier to internalise it); first-order PA induction; and ZFC's own
  **Separation** and **Replacement** — schemes over formulas that provably cannot
  be replaced by finitely many object sentences (ZFC is not finitely
  axiomatisable). In `set.mm` these are `ax-1`, `ax-rep`, `ax-sep`, stated with
  `wff` metavariables.

**Why the import needs A1 regardless.** Metamath's metalogic is *uniform direct
substitution*: applying **any** theorem — reducible `nncn` included — is
metavariable substitution in the verifier, never a routed-through-`∀` UI step. So
to replay an imported proof faithfully against the same kernel, Edifyce needs
schematic application as a general mechanism. And independently, Edifyce targets
*any* formal system — including quantifier-free ones (propositional Hilbert
systems, term-rewriting) where metasubstitution is the *only* reuse mechanism. So
A1 is required; it just shouldn't crowd out object-level UI where that's cleaner.

> **Status: implemented.** See `website/logical/formal_system/promotion.py`,
> `compiler.promote_from_source`, and `tests/test_theorem_promotion.py`. The
> diagnosis below is kept because it explains *why* the bridge has the shape it
> does; what shipped is summarised at the end of this section.

**The gap, as originally measured.** Tested against the Hilbert system in
`tests/test_engine_neutrality.py` (axiom schemes K, S + MP, no substitution rule):

- **Axiom *schemes* re-instantiated at arbitrary compound formulas** — they are
  `InferenceRule`s with metavariables, and the written instance is unified against
  the scheme. `((a→a) → (a→a))` is derivable from S/K/MP by instantiating the
  schemes at the compound formula `(a→a)`. So the schematic-application
  *mechanism already existed and was load-bearing.*
- **A proved *theorem* was a concrete line with no re-instantiation.** Having
  proved `(a → a)`, there was **no** way to cite it and obtain `((y→y) → (y→y))`:
  bare citation `[5]` is not even reiteration here, the `mapsto` explicit-
  substitution syntax is retired (`proof.py`), and there is no substitution rule.
  The only route was to *re-derive it from the schemes* at `(y→y)`. **Reusing a
  proved theorem as a template was impossible.**

**A1 is therefore a small, precise bridge, not a new subsystem: promote a proved
theorem into an `InferenceRule` so it joins the mechanism the axiom schemes
already use.** Demonstrated: adding the proved `(x→x)` as a zero-premise rule

```
InferenceRule self_imp:      # promoted from the theorem ⊢ (p → p)
    label: I
    deduction:
        (p → p)
```

makes `((y → y) → (y → y)) [I]` check as valid (and `(z→z) [I]` valid, `(a→b) [I]`
correctly invalid) — verified against the live engine. Promotion *is* A1: the
antecedents are the theorem's hypotheses, the deduction is its statement, and any
`$d` becomes `side_conditions:`.

**The promotion for a lemma with premises.** The closure lemma

```
nncn $p |- ( A e. NN -> A e. CC )
```

promotes to a one-antecedent rule (note: for `set.mm` fidelity we promote it, even
though ZFC *could* instead use the object-level `∀x(x∈ℕ→x∈ℂ)` + UI):

```
with A as class:
    InferenceRule nncn:          # promoted from the proved theorem `nncn`
        antecedents:
            A ∈ ℕ
        deduction:
            A ∈ ℂ
```

At a use site unification binds `A` to *your* term: if line 3 established
`(B / 2) ∈ ℕ`, then `[nncn, 3]` binds `A := (B / 2)` and yields `(B / 2) ∈ ℂ`.

A lemma **with** hypotheses and `$d` maps just as directly. From `sqrt2irrlem`:

```
sqrt2irrlem.1 $e |- ( ph -> A e. ZZ ) $.
sqrt2irrlem.2 $e |- ( ph -> B e. NN ) $.
sqrt2irrlem.3 $e |- ( ph -> ( sqrt ` 2 ) = ( A / B ) ) $.
sqrt2irrlem   $p |- ( ph -> ( ( A / 2 ) e. ZZ /\ ( B / 2 ) e. NN ) ) $=
```

→

```
with ph as formula, A as class, B as class:
    InferenceRule sqrt2irrlem:
        antecedents:
            (ph → A ∈ ℤ)
            (ph → B ∈ ℕ)
            (ph → (sqrt ` 2) = (A / B))
        deduction:
            (ph → ((A / 2) ∈ ℤ ∧ (B / 2) ∈ ℕ))
```

The three `$e` become the three antecedents; the `$p` statement becomes the
deduction; any `$d` becomes `side_conditions:` (see A3). The rule is now citable
as `[sqrt2irrlem, i, j, k]` with `ph, A, B` bound afresh each time.

### What shipped

- **`PromotedTheorem`** records a theorem's schematic statement — conclusion,
  premises, metavariables, `$d` provisos, and matching regime — and `as_rule()`
  builds the *ephemeral* `InferenceRule` a citation is checked against.
- **A separate namespace.** `FormalSystem.promoted_theorems` keeps derived
  theorems out of `inference_rules`, so a set.mm-scale library never pollutes the
  rules that *define* a system. `Proof.get_reference` resolves `[Thm]` and
  `[Thm, i, …]` to an ephemeral rule built on demand: nothing per-theorem is
  persisted as a rule. (That settles the "where do they live" question — and the
  answer to "eagerly or lazily" is *neither*: constructed per citation.)
- **`compiler.promote_from_source(system, label, statement, metavariables,
  premises, distinct, matching)`** — the import-facing builder. A Metamath `$p`
  maps straight in: `$e`→premises, `$f`→metavariables, `$d`→distinct.
- **`$d` is enforced**, and demonstrably load-bearing: an `ax-5`-shaped theorem
  `(φ → ∀x φ)` rejects the capturing instance `(x ∈ y → ∀x (x ∈ y))` with the
  proviso and *accepts* it without — so dropping `$d` is genuinely unsound, not
  merely untidy.
- **Closed theorems** (`2re`: `|- 2 e. RR`) promote too: with no metavariables the
  statement justifies exactly itself.
- **Matching regime is carried**, so a theorem promoted from a string-rewriting
  system stays string-checked.

Two findings from building it are worth keeping, because both contradicted a
reasonable guess:

1. **Promotion is a graph operation, not a string one.** The checker unifies
   kernel terms, so generalising a proved conclusion is `from_match` →
   re-variabilise the leaves → hang the term on a schema shell. `create_pattern`
   (which re-serialises a match to a string, with collision repair) is *not* on
   the path.
2. **A schema with no composed term is not automatically broken.** Defined
   notation composes none yet applies fine via the flat projection; only a
   *ground* compound is dead, and it needs its nested term composed explicitly —
   at the system's declared **logical sorts**, not the first sort in the grammar
   that happens to match.

### Still open

Promoting a **natively-authored** Edifyce proof (rather than an imported one)
needs a generalisation policy the importer gets for free from `$f`/`$d`: which
leaves are general, what sort to widen them to, and — the part with real
soundness surface — deriving `$d` constraints from the proof's ∀I freshness
steps. Deferred deliberately; imports never hit it.

---

## A2. Compressed-proof decoder → primitive Edifyce proof

> **Status: implemented as a vertical slice.** `website/logical/metamath/`
> (`parser` → `compressed` → `importer`) reads `.mm` source, builds the grammar
> from the syntax axioms, promotes the logical assertions, decodes the compressed
> proof, and emits Edifyce proof text. `tests/test_metamath_import.py` imports
> `sqrt2re` from its verbatim set.mm proof string and has the kernel check it.
> The worked example below is exactly what it produces. What is *not* yet done:
> scale (A5), definition classification (A4), and the full statement-level mapping
> for constructs this fragment doesn't reach (A3).

**The reasoning.** `set.mm` stores proofs in a compressed format: a parenthesised
**label table** followed by a run of capital letters encoding a **reverse-Polish
(stack) program**. To import, decode that program into a stack of partial results
and emit one Edifyce proof line per *logic* step (syntax steps fold into parsing,
per the preliminary).

**A fully worked minimal example.** The whole proof of `sqrt2re`:

```
sqrt2re $p |- ( sqrt ` 2 ) e. RR $=
  ( c2 2re 2pos sqrtpclii ) ABCD $.
```

The label table is `[c2, 2re, 2pos, sqrtpclii]`; the program `ABCD` means "apply
label 1, then 2, then 3, then 4" (`A`→1, `B`→2, …). Executing it on a stack:

| step | label | kind | stack after |
|---|---|---|---|
| A | `c2` | **syntax** — builds the class term `2` | `[ 2 ]` |
| B | `2re` | logic — `\|- 2 e. RR` | `[ 2, (2∈ℝ) ]` |
| C | `2pos` | logic — `\|- 0 < 2` | `[ 2, (2∈ℝ), (0<2) ]` |
| D | `sqrtpclii` | logic — `\|- ( sqrt ` A ) e. RR` from `A∈ℝ`, `0<A` | `[ ((sqrt`2)∈ℝ) ]` |

`sqrtpclii` pops **three** entries, not two — its *mandatory hypotheses* are the
floating `$f class A` followed by the two essentials `|- A e. RR` and `|- 0 < A`,
in declaration order. The floating slot is what supplies the substitution
(`A := 2`, read off the `c2` entry); the two essential slots become the cited
lines. Getting that order or count wrong silently misaligns every application, so
it is computed at parse time (`Assertion.mandatory`).

The syntax step `A` (`c2`) never becomes a line. So the four-token program imports
to a **three-line** Edifyce proof (with `sqrtpclii`, `2re`, `2pos` promoted per
A1) — verbatim output of the importer:

```
2 e. RR [2re]
0 < 2 [2pos]
( sqrt ` 2 ) e. RR [sqrtpclii, 1, 2]
```

(The notation stays Metamath's own — `e.`, `` ` `` — because the grammar is built
from set.mm's syntax axioms, so its tokens *are* the surface syntax. Rendering it
as `∈`/`√` is a display concern, and exactly the sort of thing B4/B5 address.)

which is already recognisably a proof a human could read. The decoder's job is to
run this stack machine over the (much larger) `sqrt2irr` program, tag each label
syntax-vs-logic, and thread the `Z`-marked backreferences Metamath uses to share
repeated subproofs (they become citations of an earlier line — Edifyce's proof
DAG already supports one line being cited many times).

**The contract:** the decoder emits *fully primitive* proofs the existing kernel
checks. That is the verifiability baseline, and running it over `set.mm` is a
merciless test of the kernel's rule-application and unification paths.

---

## A3. Symbol / statement mapping

**The reasoning.** Metamath's dialect is tiny — a handful of statement keywords —
and each has a natural Edifyce home. Getting the mapping right (especially the
easy-to-forget `$d` and `$f`) is what makes A1/A2 well-defined.

| Metamath | Meaning | Edifyce target |
|---|---|---|
| `$c` | constant symbol | a terminal in the grammar / an `Atom` |
| `$v` | variable | a metavariable name |
| `$f` | floating hyp: *typing* of a variable (`wff`, `class`, `setvar`) | a **sort binding** — `with A as class`, `with x as setvar` |
| `$e` | essential hyp | an `InferenceRule` **antecedent** (or a proof hypothesis) |
| `$a` | axiom / definition | an **axiom** rule, or a `Define` (see A4) |
| `$p` | theorem | a proof, **promoted to a rule** (A1) |
| `$d x y` | `x`, `y` may not share variables after substitution | a `disjoint(x, y)` **side condition** |
| `${ … $}` | scoping block for hyps | the `with … :` block enclosing a rule |

**Worked `$d` mapping.** `sqrt2irr` opens with

```
${
  $d n x y z $.
  …
  sqrt2irr $p |- ( sqrt ` 2 ) e/ QQ $=
```

`$d n x y z` says all pairs among `n, x, y, z` must stay distinct. That is exactly
Edifyce's `disjoint` proviso, which the side-condition algebra already supports
(`docs/side_condition_followups.md`):

```
with n as setvar, x as setvar, y as setvar, z as setvar:
    InferenceRule sqrt2irr:
        …
        side_conditions:
            disjoint(n, x)
            disjoint(n, y)
            disjoint(n, z)
            disjoint(x, y)
            disjoint(x, z)
            disjoint(y, z)
```

**Worked `$f` mapping.** Metamath's floating hyps

```
$f wff ph $.      $f class A $.      $f setvar x $.
```

are just declaring the sort each metavariable ranges over — precisely the
`with ph as formula, A as class, x as setvar:` bindings Edifyce already uses.
Metamath's two content sorts (`wff`, `class`) plus `setvar` map onto three Edifyce
sorts. **Recommendation: mirror Metamath's sorts faithfully at first** — a richer
type discipline is tempting for automation but risks having to re-prove things and
enlarges the soundness surface; enrich only once the faithful import checks green.

---

## A4. Definition classification

**The reasoning.** Not every `$a` is an axiom in the "new assumption" sense — many
are *definitions*. Metamath writes definitions as `$a` biconditionals/equalities
and relies on an **external** conservativity checker. Edifyce's `Define … as …`
is conservative **by construction** (it only folds/unfolds), which is strictly
better — *but only for `$a`s that are genuinely fold/unfold-shaped*. So the import
needs a classification pass: definition → `Define`; true axiom → axiom rule;
anything that doesn't fit → flag for a human.

**A clean definition.** Negated membership:

```
df-nel $a |- ( A e/ B <-> -. A e. B )
```

is a textbook fold/unfold and maps directly:

```
Define A e/ B as ¬ (A ∈ B)   label df-nel
```

Now a proof line can rewrite `A ∉ B` to `¬(A ∈ B)` (or back) with a definitional
step `[df-nel, n]` — checked over kernel terms, no trust required. Same for
`df-2`:

```
df-2 $a |- 2 = ( 1 + 1 )   ->   Define 2 as (1 + 1)   label df-2
```

**A definition that needs care.** `df-div` and `df-sqrt` define via an `iota`
(definite description):

```
df-div  $a |- / = ( x e. CC , y e. ( CC \ { 0 } ) |->
                    ( iota_ z e. CC ( y x. z ) = x ) )
```

This is still definitional, but its "unfolding" introduces a bound `iota` — so it
exercises Edifyce's `fresh`/capture-avoidance machinery, and its well-definedness
(that the `iota` exists uniquely) is itself a proof obligation Metamath discharges
elsewhere. Classify it as a definition, but route it through the `fresh`-aware
`Define` path and keep its existence lemma as a cited premise.

**A true axiom** (for contrast): `ax-mp`, `ax-1`, the ZFC axioms — these are not
eliminable and import as **axiom rules**, not `Define`s. The classifier's default
on "doesn't reduce to fold/unfold" must be *axiom + flag*, never a silent
`Define`, or conservativity is lost.

---

## A5. Scale & performance

**The reasoning.** `set.mm` is ~40 000 theorems in a 51 MB file, with proofs
hundreds of steps deep. Two parts of Edifyce meet this scale head-on and should be
benchmarked *before* committing to the import shape.

**Risk 1 — the notation parser.** Edifyce's grammar matcher is a hand-written
backtracking string matcher that disambiguates overlapping productions by a
`certainty` heuristic (count of non-variable characters). At `set.mm` grammar
size (hundreds of productions, deeply nested operator terms like
`( ( A / 2 ) e. ZZ /\ ( B / 2 ) e. NN )`), backtracking cost and heuristic
mis-ranking are real risks. **Mitigation:** drive bulk import through the
structured `declarative.py` path (build patterns directly, with precompiled
`schema_term`s) rather than the text DSL, and benchmark parse time on the widest
`set.mm` statements before scaling up.

**Risk 2 — rule resolution at 40 000 rules.** Every promoted theorem (A1) is a
schematic rule; checking a line searches for an antecedent-to-slot assignment and
unifies. Edifyce already replaced a factorial permutation sweep with a bipartite
matching + prefix-pruning, which is the right foundation — but it should be
exercised with a rule *library* of realistic size and with lines that cite
5–10 antecedents. **Mitigation:** index rules by conclusion head-symbol so a
citation resolves against a handful of candidate rules, not all 40 000; measure
worst-case lines (e.g. the `syl`/`jca`-heavy stretches).

Budget explicitly for this pass. Correctness at 12 theorems tells you nothing
about wall-clock at 40 000.

---

# Tier B — the human-altitude layer

These deliver the actual goal: writing and reading at mathematician altitude. All
obey one guardrail — **produce primitive steps the existing kernel checks (the de
Bruijn criterion) or only re-render an already-checked proof** — so verifiability
is never traded away, and all are **parameterised by the user's declared system**,
so generality is never traded away.

## B1. A tactic / elaboration framework (de Bruijn criterion)

**The reasoning.** This is the layer Metamath deliberately omits (§2.6 of the
companion). A *tactic* is a program that takes a goal + the current context and
**emits primitive proof lines**, which the kernel then checks exactly as if a
human had written them. Trust stays entirely in the kernel: a buggy tactic can
fail to find a proof, but it cannot certify a false one, because its output is
re-checked.

**Shape of the interface** (illustrative):

```python
# a tactic sees the goal and the in-scope lines; it returns lines to splice in,
# each of which the kernel re-verifies. It never gets to say "trust me".
Tactic = Callable[[Goal, Context], list[ProofLine]]
```

**Example — an `mp_chain` tactic** that, given a target and a set of in-scope
implications, finds a modus-ponens chain and emits the individual `[MP, i, j]`
lines. The author writes `by mp_chain`; the stored, checked proof still contains
the explicit MP steps. Every Tier-B item below is an instance of this pattern; B1
is the framework they plug into (a tactic registry, a goal representation, and the
splice-and-recheck loop).

## B2. A closure / typing solver (removes §2.2 plumbing)

**The reasoning.** The single largest visible slice of `sqrt2irr` is closure
plumbing — `nncn`, `zcn`, `2cnd`, `nnne0`, `nncnd`, `sqcld`, … A backward-search
tactic driven by a *declared* set of closure rules discharges these
automatically, and because it's driven by declarations it works in **any** system
that declares closure facts, not just ℂ.

**Example.** Declare the closure rule set (these are just promoted lemmas, A1):

```
closure_rules: nncn, zcn, 2cnd, nnre, nnne0, resqcl, zmulcl, …
```

Then a goal like `( B / 2 ) ∈ ℂ`, given `B ∈ ℕ` in scope, is solved by backward
chaining: `?( (B/2) ∈ ℂ )` ← `divcl` needs `B ∈ ℂ` and `2 ∈ ℂ` and `2 ≠ 0`;
`B ∈ ℂ` ← `nncn` from `B ∈ ℕ` ✓; `2 ∈ ℂ` ← `2cnd` ✓; `2 ≠ 0` ← `2ne0` ✓. The
tactic emits those four primitive lines. **Before / after:**

```
# before (imported, verbatim):
12.  B ∈ ℂ           [nncn, 4]
13.  2 ∈ ℂ           [2cnd, …]
14.  2 ≠ 0           [2ne0]
15.  (B / 2) ∈ ℂ     [divcl, 12, 13, 14]

# after (authored):
12.  (B / 2) ∈ ℂ     by closure
```

Same four checked lines underneath (B4 lets the reader expand them); one line to
write and read.

## B3. Equational reasoning — `calc` chains + a congruence tactic (removes §2.4)

**The reasoning.** Metamath rewrites inside a term with position-specific
congruence lemmas (`oveq1d`, `oveq2d`, `fveq2d`, …) plus `eqtr*` glue. A `calc`
surface lets the author write an equality/`↔` chain with one justification per
step; the elaborator **synthesises** the congruence lemma for each rewrite by
looking at *which argument position* changed (data it already has from the
notation grammar). Parameterise on a user-declared congruence relation, so it
generalises past `=` to `↔`, group equality, etc.

**Example** — the core algebra of the √2 proof (`a² = 2·b²` ⇒ manipulate):

```
# after (authored):
calc (sqrt ` 2) = (A / B)            [by hypothesis .3]
              …  ((A/2)/(B/2))       [by divcan7d]     # rewrite under `/`
              …  (A / B)             [by …]

# the elaborator emits, per step, the right congruence + transitivity:
#   … [oveq1d/oveq2d, …]   (Leibniz at the changed operand)
#   … [3eqtr4d, …]         (stitch the chain)
```

The author never names `oveq1d` vs `oveq2d`; the elaborator picks it from whether
operand 1 or operand 2 changed. Underneath, the checked proof is the same pile of
congruence steps Metamath stores.

## B4. Zoomable presentation (removes §2.9; makes imports readable)

**The reasoning.** An imported proof *is* fully expanded, so the payoff is in
rendering. Store the elaboration/subproof tree — which high-level step produced
which primitive substeps — and let the frontend fold to a sketch and drill down.
Edifyce's subproof tree already provides the scaffolding, and the frontend is a
thin client, so this is mostly a stored-tree + rendering task.

**Example — `sqrt2irr` as the reader first sees it:**

```
▸ 1.  assume (sqrt`2) ∈ ℚ, for contradiction        [expand ▾]
▸ 2.  then (sqrt`2) = A/B with A ∈ ℤ, B ∈ ℕ          [expand ▾]
▸ 3.  so (A/2) ∈ ℤ and (B/2) ∈ ℕ                     [sqrt2irrlem ▾]
▸ 4.  … infinite descent: no minimal B               [nnind ▾]
  5.  contradiction ∎
```

Each `▾` expands to the primitive steps (a `sqrt2irrlem` node expands to the
hundred-step lemma; a `by closure` node expands to its four lines). Six rows to
read, full rigour one click away.

## B5. Idiom re-abstraction for imported proofs (stretch; biggest presentation win)

**The reasoning.** B4 shows the *authored* structure — but imported proofs have no
authored structure, only Metamath idioms. A pass that **recognises** those idioms
and folds them to human altitude turns all 40 000 imported proofs readable, not
just newly authored ones. It's pattern-matching on the proof DAG, feeding B4's
tree.

**Recognition table:**

| Metamath idiom in the DAG | folds to |
|---|---|
| `syl`/`3syl` chain of implications | "hence" / a transitivity step |
| `ad2antrr`/`adantr`/`simpl`/`simpr` cluster | "in this context …" (context bookkeeping, hidden) |
| run of `oveqNd`/`fveqNd` ending in `eqtr*` | one `calc` step |
| application of a declared closure lemma | a hidden typing obligation (grey, expandable) |
| `nnind`/`fin` induction scaffold | "by induction on n" with the step case as a subproof |

**Example.** A raw imported stretch

```
40.  (ph ∧ ch) → ps          [ad2antrr, 39]
41.  ph → (ps → th)          [syl, 40, …]
42.  ph → th                 [mpd, 41, …]
```

folds, for display, to a single line `so th` — with the three primitive steps
preserved underneath and reachable via B4.

## B6. Structural macros — WLOG / by-symmetry / case-split (addresses §2.7)

**The reasoning.** Humans write "similarly for b" or "WLOG a ≤ b"; Metamath must
repeat the argument or hoist a lemma. A macro that expands to a *real* subproof —
discharging the "similarly" by instantiating a proved symmetry lemma — lets the
author write the human phrase while the kernel still sees the full argument.
General, because the symmetry/exhaustiveness justification is always a **cited
lemma**, never a built-in.

**Example — the a/b symmetry in √2-irrationality.** The argument "a is even, and b
is even by the same reasoning" is one symmetric claim used twice. With a symmetry
lemma `even_sym` in scope:

```
# after (authored):
7.  A is even                        by descent-argument on A
8.  B is even                        wlog from 7    [by even_sym]

# `wlog` expands to: instantiate even_sym with the A/B roles swapped, then
# discharge line 8's goal from line 7 — all primitive, all re-checked.
```

The author states the symmetry once; the checked proof contains both directions.

---

## Sequencing (mirrors the companion)

1. ~~**A1**, schematic theorem application~~ — **done**.
2. ~~**A2**, the compressed-proof decoder~~ — **done as a vertical slice**:
   `sqrt2re` imports from its verbatim set.mm proof and the kernel checks it.
3. **Widen the slice** — **A3** (statement-level mapping beyond what the `sqrt2re`
   fragment reaches) and **A4** (definition classification), then `sqrt2irr`'s
   dependency closure.
4. **A5** in parallel: benchmark parser and rule resolution at scale.
5. **B1 + B2**: tactic framework + closure solver — biggest readability jump for
   the least surface area, and they shorten *new* proofs too, not just imports.
6. **B4** (zoom) and **B3** (`calc`); then stretch items **B5 / B6**.
