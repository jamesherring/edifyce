# Alternative proofs, and what a result rests on

Two questions the store cannot currently be asked, and they are the same question
twice:

1. **Do these two library entries prove the same thing?** A corpus routinely
   carries several proofs of one result — `set.mm` spells them `…ALT`,
   `…OLD`, `…VD` — and nothing links them. A reader browsing 47,589 entries has
   no way to see that two of them are one theorem.
2. **Which axioms does a given result rest on?** And, once (1) is answered, the
   sharper form the first question makes available: *which axioms does each
   route rest on* — because two proofs of one result may bottom out in different
   primitives, and the honest answer is a disjunction (`{A1, A2}` **or**
   `{A2, A3}`) rather than a set.

This records what exists, what is missing, and what the missing half should look
like. Nothing here is implemented.

## 1. What exists today

### The result as an object

A **promoted theorem** (`app/db/promoted_theorems.py`) is the only first-class
"result" in the store. `uq_promoted_theorems_system_label` makes a label unique
per system, because a citation has to resolve to one entry. So two proofs of one
theorem are necessarily **two labels and two independent rows**, and the only
thing relating them is that they happen to state the same thing — which nothing
records, nothing computes, and no index can see.

The two proof↔entry edges are both single-valued and both mean something else:

| column | direction | means |
|---|---|---|
| `proofs.theorem_id` | proof → entry | whose `$e` hypotheses this proof may cite |
| `promoted_theorems.proved_by_id` | entry → proof | which proof's standing warrants the entry |

Neither is "the proofs of this result", and widening `proved_by_id` to many is
the wrong move — see §2.3.

`theorems` (`app/db/models.py`) is a third table, provisioned for search and
**written by nothing**. It is not the place for this either: it hangs off a
proof, and the relation wanted here is between *statements*.

### Deciding that two statements are the same

This is already solved, once, and by the right piece of code.

`terms_mapping.alpha_digest(term, is_free)` digests a term invariant under
consistent renaming of whatever `is_free` calls free. Two policies exist and the
difference is the whole subject:

* **the default** — renames every regex leaf. It is what
  `terms.alpha_digest` stores and what `ix_terms_system_alpha_digest` indexes,
  and it is a *search* key, not an identity: in a grammar whose numerals are a
  `matches` production it reads `2 = 5` and `7 = 9` as one statement.
  `tests/test_alpha_digest.py` pins exactly that, and
  `StatementOutcome.exact_is_approximate` reports when a system is one where it
  bites.
* **`metavariables_only`** — renameable in metavariables and nothing else, which
  is exactly the leaf a citation instantiates. **This is the identity.**

And it is already deployed as one: `proofs._discharge` compares a proof against
the assumption it claims to pay off by digesting both sides under
`metavariables_only` (`_rename_blind`), over the conclusion *and* the premises,
having read the assumption's side from rows via `assumptions.stated()` →
`Stated(conclusion, premises, provisos)`. That comparison — with its refusal to
match when a term is missing, and its separate proviso guard — is precisely
"do these two entries state the same theorem", written for a different purpose.

What is missing is that the answer is computed for one pair, at one moment,
and thrown away.

### Everything else deliberately refuses to answer

Worth stating, because it is not an oversight in any of them:

* `retrieval.conclusion_candidates` returns an `exact` flag from the *search*
  α-digest. Its docstring calls it a ranking hint; `Candidates` reports
  `unindexed` and `unfiltered` counts so a short list never reads as a complete
  one.
* `POST /formal-systems/{id}/statements` (`app/routers/statements.py`) will not
  say `proved`. It served such a field once and a review removed it: "the filter
  was fine and the word was not."
* `GET /formal-systems/{id}/library/{label}` returns one entry and one
  `proof_id`.

### What a result rests on

Three things exist, and each answers a slice.

**`app/db/provenance.py` already computes the axiom closure.** `_reach` walks
the citation graph below a proof — iteratively, memoised per proof,
cycle-guarded — and accumulates `axiom_labels`: the transitive set of *primitive*
library entries it reaches, partitioned from `assumed_labels` (a primitive that
is a debt) by whether an `AssumptionRow` exists. `Provenance.axioms` is the
answer this document's §3 wants.

Three things stop it being the answer:

* it is **corpus-wide** — `provenance(session)` reads every promoted row and
  every proof line in the database — and is reachable only from
  `scripts/check_provenance.py`. There is no per-result route.
* it counts as an axiom only a **primitive promoted theorem**. A system whose
  axioms are author-declared `AxiomRow`s reports **none**, and silently: an
  axiom is built into a line type with `behaviour="axiom"`, and such a line
  records `proof_lines.rule = NULL` ("a scope opener or axiom line (valid by
  fiat)" — `app/db/proof_lines.py`). `_cited` reads only `rule`. So the closure
  over a hand-authored system is empty by construction. Any route serving this
  must read `proof_lines.line_type WHERE behaviour = 'axiom'` too.
* inference rules are **explained away** on purpose (`explained_labels`): they
  are not library entries, so they resolve to no layer. For "which layer is this"
  that is right; for "what does this rest on" a declared rule *is* a primitive
  of the system, and the report needs it as a third kind beside axioms and
  assumptions. On an imported corpus this does not bite (`ax-mp` is a `$a`,
  hence a primitive entry); on an authored system it is most of the answer.

**`theorem_assumptions` is the storage pattern to copy.** `app/db/assumptions.py`
stores, per library entry, the transitive closure of the *assumptions* it rests
on — written at promotion as the union of its citations' closures (one hop of
work), read back in one query at any citation depth, re-pointed on discharge by
`inherit_closure`. It is the same shape the axiom closure needs, with `primitive`
in place of `assumed`, and it already ships the hard parts: the second door into
the library (`reference_closure`, following `[alias.line]` edges that name no
label), honest `unresolved`/`unread` reporting, and nearest-first label
resolution over the citing chain.

**`label_avoidances` is the corpus's own answer, unchecked.** `set.mm`'s
`$j usage 'X' avoids 'Y';` — 3,107 edges over 47 distinct avoided statements,
headed by `ax-12` (435) and `ax-10` (431) — asserts that `X` has a proof not
resting on `Y`. `app/db/avoidances.py` stores it as the file's claim and says
so: "Metamath's own verifier checks these against the proof's transitive
dependencies; Edifyce does not, yet." A computed axiom closure turns those 3,107
edges into a **test corpus**, which is the cheapest validation this feature
could ask for.

## 2. Alternative proofs

### 2.1 The identity key

Store on each entry a digest of what it *claims*, computed exactly as
`_discharge` computes it:

```
statement_identity = H(
    alpha_digest(conclusion, metavariables_only),
    [alpha_digest(premise_i, metavariables_only) for i in order],
)
```

Index it `(system_id, statement_identity)`. "The alternatives to this entry" is
then one indexed query, and the relation is derived rather than declared — no
author has to remember to link anything, and an import gets it for free.

Where it is computed: `promoted_theorems_mapping.store_theorem`, beside
`conclusion_fingerprint`, from the same `schemas` list — which already holds the
conclusion and every premise, interned together. That is the precedent to
follow in every respect: a derived index column, written at promotion, non-null
exactly when the cached terms are.

Five things to get right, all of them already decided elsewhere in the codebase:

* **Not the stored `terms.alpha_digest`.** That column carries the search
  policy, which over-reports (`2 = 5` ≡ `7 = 9`). Reusing it because it is
  already indexed would make "these are the same theorem" wrong in exactly the
  systems where numerals matter.
* **Premises ordered, not a set.** A citation fills antecedent slots by
  position, and `_discharge` compares ordered tuples. Two entries differing only
  in premise order will read as different results; that is conservative in the
  safe direction and matches the comparison already deployed.
* **Provisos are not part of the key.** `_discharge`'s proviso guard is
  asymmetric: a warrant carrying a proviso the assumption did not is a *narrower*
  theorem, one that refuses instances the dependents were written against. So
  provisos belong beside the key rather than in it — two entries with the same
  key and different `SideConditionRow` sets are alternatives with a
  strength difference, and the UI should say which is stronger. Folding them
  into the key would hide precisely the interesting case.
* **A NULL key is a miss, not an absence.** An entry with no cached conclusion
  term has no key, and the count must be reported — the `unindexed` contract
  from `app/db/retrieval.py`, for the same reason.
* **Scoped to the chain, not the database.** Digests are structural over
  constructor *names* and terms are interned per system, so the key is
  comparable down an inheritance spine and meaningless across a `Translation`
  that renames productions or a `StatementTemplate` that restates what it
  carries. Those are the two edges `retrieval` reports as `unfiltered`; the same
  answer applies here.

### 2.2 What it does and does not say

It says: *these entries state the same theorem, up to renaming metavariables.*

It does not say the two proofs are different in any interesting way, and it does
not say one is better. It also cannot say two entries are the same theorem when
one is a *schematic instance* of the other — `∀x. φ → φ` and `∀x. ψ → ψ` share
a key, but `φ → φ` and `p → p` where `p` is a declared atom do not, and should
not: the second pair really are different claims. Deciding "this entry
subsumes that one" is unification, not digesting, and belongs with
`retrieval` + `InferenceRule.concludes` if it is ever wanted. Keep the two apart:
**identity is a digest, subsumption is a unifier**, and conflating them is how
`exact` nearly became `proved`.

### 2.3 Why not "many proofs, one entry"

The tempting alternative is to keep one entry per result and let several proofs
warrant it — widen `proved_by_id`, or add a join table.

It is the wrong trade and the reason is retirement. `proved_by_id` is what says
an edit that stops a proof standing withdraws what it established
(`_retire_promotion`), and `promoted_theorems.proved_by_id` is `ON DELETE
CASCADE` because "an entry cannot outlive its only warrant". With many warrants,
every one of those becomes a question: does the entry survive one proof
breaking? Which proof's provisos does it carry? Which one does
`invalidate_warranted_edges` follow? And `proofs.theorem_id` — which grants
hypothesis scope — would have to fan out too.

Against which: the corpus convention is already two labels (`sqrt2irr` /
`sqrt2irrALT`), two labels cost nothing, and a derived identity key gives the
reader the same thing. **Model alternatives as a relation over entries, not as
an ownership edge.** One column, one index, no change to checking, promotion,
retirement, or invalidation.

### 2.4 Surface

* `GET /formal-systems/{id}/library/{label}` gains `alternatives: [{label,
  proof_id, primitive, provisos_delta}]` — the entries sharing this key down the
  chain, nearest-first, self excluded, with the count of same-key entries whose
  terms are unindexed.
* The proof page and the library card show an "Alternative proofs" section.
  An entry that is `primitive` and shares a key with a proved one is worth
  showing loudly: that is an axiom somebody has since derived.
* A system-level listing — "results with more than one proof" — is a
  `GROUP BY statement_identity HAVING count(*) > 1`, and is the view that makes
  a long theorem list navigable.

## 3. Axioms a result rests on

### 3.1 Storage

Generalise `theorem_assumptions` from *assumptions* to *primitives*. An
assumption is stored as a primitive already (`primitive` set, `proved_by_id`
NULL), `_reach` already partitions the two by whether an `AssumptionRow` exists,
and `inherit_closure` already handles a discharge moving an entry from one side
to the other. Making the table hold every primitive and letting the reader
partition it costs one write path and reuses every read.

Two things to settle before doing it:

* **Size.** Today the table holds debts, which are rare. Widened it holds
  (entry × axioms it rests on) for the whole corpus — order 47,589 × the mean
  closure size. `set.mm`'s `avoids` directives name 47 distinct statements,
  which suggests a mean in the tens and a total in the high hundreds of
  thousands. That is unremarkable for Postgres and should still be **measured on
  an import before the column is added**, not estimated here.
* **Declared axioms and rules.** Per §1, the closure must read
  `proof_lines.line_type` where `behaviour = 'axiom'` as well as
  `proof_lines.rule`, and should carry declared inference rules as a third kind.
  Without both, the report is empty for every hand-authored system and silently
  so — the exact failure shape this codebase keeps refusing elsewhere.

### 3.2 The disjunction

The point the feature turns on: **an axiom closure is a property of a proof, not
of a result.** Given the identity key of §2, a *result* is a set of entries, and
each has its own closure. So the report for a result is a family:

```
sqrt2irr     rests on  {ax-1, ax-2, ax-mp, ax-ext, ax-pow}
sqrt2irrALT  rests on  {ax-1, ax-2, ax-mp, ax-ext, ax-inf}
```

and three derived readings, all of which the UI should show and name:

* **each route**, separately — the primary answer, and the only one that is a
  fact about a proof;
* **the intersection** — what every known proof of this result uses;
* **the union** — what the development as a whole spends on this result.

The user-facing sentence is the disjunction: *this result is known from
`{ax-1, ax-2, ax-mp, ax-ext, ax-pow}` or from
`{ax-1, ax-2, ax-mp, ax-ext, ax-inf}`.*

### 3.3 What it must not say

**"Requires."** That no known proof avoids an axiom is not evidence that the
result needs it; independence is a metatheorem and nothing here establishes one.
The wording has to be "every known proof of this uses `ax-pow`", and the
distinction is the same one `propose_statement` draws when it refuses to say
`proved` and `retrieval` draws when it calls `exact` a hint.

`label_avoidances` is the shape of a real claim in this space, and note which
direction it goes: the corpus asserts that a proof *avoiding* `X` exists — a
positive, existential claim about a proof somebody has — and Edifyce stores it
as an assertion because it does not check it. A computed intersection is the
same kind of statement (a proof exists, here it is), and a computed
"requires" would be a universal claim over proofs that do not exist yet.

### 3.4 Validation

Compute the closure over an imported `set.mm` and check it against the 3,107
stored `avoids` edges: for each `X avoids Y`, `Y` must not be in `X`'s closure.
A violation is either a bug in the closure or a claim the file gets wrong, and
both are worth knowing. This is the cheapest high-coverage test available for
any of this, and it exists already as rows.

## 4. Order of work

1. `statement_identity` on `promoted_theorems`, computed in `store_theorem`;
   backfill; `alternatives` on the library-entry route; the UI section. Self
   contained, one column, no behaviour change.
2. Fix the axiom closure's blind spots — `behaviour = 'axiom'` line types, and
   declared rules as their own kind — with tests over a hand-authored system,
   *before* anything is stored. A stored closure computed by a walk with a known
   hole is worse than no closure.
3. Widen `theorem_assumptions` to all primitives, written at promotion; a
   per-proof and per-entry route serving one closure.
4. Join (1) and (3): the per-result report, its intersection and union, and the
   `avoids` cross-check as a test.
