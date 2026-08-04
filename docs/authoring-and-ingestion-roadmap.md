# Authoring, and what an ingestion pipeline needs

A companion to [metamath-import-roadmap.md](metamath-import-roadmap.md). That
document is about getting a corpus *in*; this one is about what happens next —
how a proof gets **written**, by a person or by a machine.

The two questions turn out to have different answers, and the difference is the
point of writing this down.

---

## 1. How authoring works today

**The text is the truth.** `Proof.source` is a non-null `Text` column and
everything else is derived from it. The editor is a plain textarea bound to
`source`; 450 ms after typing stops it POSTs the whole buffer to
`/formal-systems/{id}/verify`, which runs `FormalSystem.parse(text)` and returns
per-line diagnostics. Saving writes `source`, then `/proofs/{id}/verify` re-checks
and stores the line and term rows.

**Only the grammar's own spelling parses.** `read_line` matches against the
`Pattern`s built from `SystemSpec`. A notation is `Constructor.pieces` — a
different projection of the same production — and the parse path never consults
one.

**Rendering is deliberately one-way.** `rendering.render` is a fold, and it is
*canonical, not verbatim*: redundant brackets the author typed are gone, sort
coercions collapse. There is no inverse and none was intended.

**The input help currently points the wrong way for imports.**
`symbols.ts::systemSymbols` leads the palette with the non-ASCII characters in the
system's *source* grammar. Metamath source is ASCII by construction — measured on
a 3,000-theorem `set.mm` slice: 119 productions, **zero** non-ASCII characters. So
for an imported corpus that row is empty and the palette falls back to a generic
Unicode catalogue, every character of which fails to parse. An author on `set.mm`
is offered `∈` and must type `e.`.

## 2. Why the notation direction is hard

Three obstacles, all measurable rather than aesthetic.

**A notation is not injective.** `notation_report` finds **19** collisions in
`set.mm`'s LaTeX reading, each a constant against a class *variable* of the same
spelling (`+` is both `caddc` and a variable named `.+`). As a display that is
cosmetic; as a *source* it means text no longer determines the term. The report
also explicitly does not certify absence, so an empty result would not settle it
either.

**A rule has no production form.** `Production` builds exactly one `Constructor`;
nothing constructs a two-node term. A `rendering.Rule` *consumes* what it pins —
there is no `sqrt` token in `\sqrt{2}` — so inverting one means re-inserting a
subterm the string never mentions. Possible (the rule says what to insert), but it
is a term rewrite, not a grammar entry.

**Metavariable spellings sit outside the projection.** `_render` returns a `Var`
as its own name by design. A Metamath import hides this because each `$v` is an
atom *production*; in a hand-authored system it is a real gap in what a notation
covers.

## 3. The options

| | What changes | Cost | Gated on |
|---|---|---|---|
| **A. Reverse input** — source stays the buffer, the editor helps | frontend + one endpoint | small | nothing |
| **B. Notation as a second grammar** — notation text parses | engine | moderate | injectivity |
| **C. Structured editing** — the term is the buffer | editor + API | large | — |
| **D. Elaboration** — Tier B's tactics and closure solver | engine | large | — |

**A — reverse input.** Drive the palette and completion from the *stored*
notation rather than a fixed catalogue, inserting **source** text: pick `√`, get
`( sqrt \` ▮ )` with the caret in the slot. Add a rendered pane so the author sees
`√2 ∉ ℚ` while typing ASCII. No soundness question arises, because what lands in
the buffer is source the existing parser reads. §4.4b is what makes this cheap —
the stored notation is already a total constructor→pieces map plus its rules, so a
reverse map is a query rather than a system rebuild.

**B — notation as a second grammar.** Re-spell `SystemSpec` through a notation and
build a second `FormalSystem`. Constructor names are unchanged, so the terms are
*identical* and the kernel is untouched. Missing: pieces→template conversion, a
post-parse rewrite inverting each rule, and the injectivity gate. Available for a
**new** system whose author declares the notation once — which is what §4.2a
already concluded — and gated for the imported corpus on those 19 pairs.

**C — structured editing.** The editor holds the term; notation is display-only in
both directions and ambiguity never arises, because the author picks the
production rather than a parser inferring it. The storage half already exists:
verification runs from rows ([verification-from-rows.md](verification-from-rows.md)).
What is missing is that `source` is still what an author edits.

**D — elaboration.** The metamath roadmap's B1/B2. Not an authoring feature at
all, and it competes for the same effort: §2.2's analysis is that proof *length*
dominates, not spelling. `sqrt2irr` is painful because it is ~90 lines of closure
obligations, not because one types `e.`.

## 4. What changes when the author is a machine

The intended destination is an ingestion pipeline: proofs from PDFs, arXiv and
Lean, translated onto the imported ZFC base, with an LLM assisting the translation
and the repair of steps that do not check. That reranks everything above, because
the pipeline's author has no keyboard.

**A drops to roughly no value.** It is a keyboard affordance. Worth doing for
people; it should not be justified on pipeline grounds.

**B becomes two-edged.** The upside is real — arXiv and PDF source *is* LaTeX, so
a LaTeX-shaped input notation shortens the translation distance, and emission in a
notation near a model's pretraining distribution is likely more reliable than
Metamath ASCII. (A judgement, not a measurement.) But the 19 collisions get far
worse under machine authorship: a person seeing `+` knows which they meant; a
model emits it confidently and the parser picks one. The resulting term may still
**check**, giving a green proof of something other than what the paper said. That
is a statement-fidelity failure, the worst class in autoformalisation precisely
because it is invisible. For a person an ambiguous notation is a papercut; for
ingestion it is a silent corruption channel. The fluency win is better taken at
the *translation* boundary — model emits LaTeX, a translator maps to source, and a
mis-mapping is a caught error rather than a different term.

**C is the API-shaped option** and pays off most of the four: structured emission
rather than free text, and errors anchored at a node rather than a character
offset.

**D is the biggest single lever.** The gap between a proof in a paper and a proof
in `set.mm` is almost entirely the elaboration gap — the closure and typing
obligations no paper states. Without that layer the model must emit all ~90 lines
itself, which is where autoformalisation efforts characteristically fall over.

## 5. But the binding constraint is the feedback signal

None of A–D is what will throttle a repair loop first. This is:

```python
# No admissible, consistent assignment: not a valid line.
proof_line.valid = False
proof_line.invalid_message = f"{key} does not apply."
```

The bipartite assignment search immediately above it *knows* which antecedent slot
could not be filled, which unification failed and which proviso blocked it. All of
it is discarded into a string that says "no". `VerifyProofResponse` is
`success: bool`, `errors: list[str]`, `proof: dict`; per line there is `valid`,
`invalid_message: str`, and — better than one might fear — `term`, `rule` and
`reference`.

No amount of nicer surface syntax compensates for a diagnostic that says only
that something failed.

**And a partial proof is not expressible.** A line stating a formula with no
justification is *representable* — the checker marks it invalid and the structure
survives — but it is classified as an error, not as an open obligation. An
incremental loop needs the difference between "this step is wrong" and "this step
is not done yet".

## 6. Sequencing

1. **Structured failure reasons** — *done* (§7). Stop discarding what the
   assignment search found: which slot, which proviso, expected against actual.
   Local to `formal_system/`, and the input to every repair loop there will ever be.
2. **Holes** — *done* (§8). Promote the unjustified line to a first-class open
   goal, so a partial proof is a legitimate object rather than a failed one.
   Together with (1) this is what makes an incremental loop possible at all.
3. **C**, as the structured-emission surface — but not before (1) and (2), because
   a structured editor whose error channel is `"syl does not apply."` is no better
   than a textarea.
4. **D** in parallel, on its own merits: the biggest lever for ingestion and for
   human authoring alike.
5. **A** whenever convenient. Cheap, and it fixes a live papercut.
6. **Not B for the imported corpus**, unless and until the 19 pairs are decided by
   a curated table of disambiguated input spellings — the `DISPLAY_OVERRIDES`
   mechanism aimed at input instead of display. `set.mm` itself distinguishes those
   pairs *by colour* in `htmldef`, which `as_text` drops by policy; colour is not
   typeable, so that does not rescue the source case, but it does mean the
   ambiguity is partly ours rather than theirs.

### Foreclosure check

The metamath roadmap's own test, applied here: does deciding now foreclose the
pipeline? A forecloses nothing. Deferring C costs mildly and cumulatively — every
feature that assumes `Proof.source` is the only input adds migration weight later.
The insurance costs nothing today: **do not add new text-only entry points**. The
verify path already runs from rows; keep new work on that side of the line.

---

## 7. Structured failure reasons — *done*

### What a failure is

`ProofLine.failure` is a `Failure`: a `code` from a closed vocabulary, the
human sentence `invalid_message` already carried, and whatever structured detail
that code implies — the rule, the antecedent slot, the terms that would not
unify, the proviso that blocked, the lines implicated.

The code is what a machine branches on and the message is what a person reads;
neither is derived from the other, because a sentence rewritten for clarity should
not change a consumer's behaviour.

### Computed on the failure path only

`InferenceRule.check` keeps its signature and its fast path exactly. Diagnosis is a
**second pass** (`Proof._explain_assignment`), run only once a line has already
failed, so a corpus that checks pays nothing for it. Measured over `set.mm`'s first
3,000 theorems, all of which verify: **7.4–8.1 s** with the diagnosis against
**7.1–8.0 s** without, four runs each — the run-to-run spread is larger than any
difference between them.

That is also what licenses the diagnosis to be thorough: it only ever runs on the
lines someone is looking at. `_binding_assignments` will enumerate up to
`_EXPLAINED_ASSIGNMENTS` (8) binding assignments looking for the proviso that
blocked, which the checking search would never do.

### Vocabulary

Closed, and each code carries what that kind of failure can say:

| code | what it adds |
|---|---|
| `unparsed-line` | — (the line matched no line type) |
| `no-formula` | the line cited, where a definitional step's source bears none |
| `bad-reference` | the citation as written |
| `out-of-scope` | the line cited from inside a closed subproof |
| `antecedent-count` | expected against given, and the slots the cited lines *could* fill |
| `too-many-antecedents` | the cap, against how many were cited |
| `slot-unsatisfied` | **which slot** and its schema — the premise that is missing |
| `inconsistent-binding` | every slot, with the lines individually admissible for it |
| `side-condition` | **which proviso**, in the words the author wrote it in |
| `ordering` | the antecedent that is not earlier |
| `no-subproof` / `subproof-out-of-scope` / `discharge-mismatch` | the opener |
| `definition-mismatch` | the source line, and the *named* definitions tried |
| `hole` | — (§8) |

`slot-unsatisfied` and `side-condition` are the two that matter most: the first is
exactly the "what do I still need to prove" signal a goal-directed loop runs on,
and the second is the freshness/`$d` class of failure that is otherwise almost
impossible to guess from a sentence. What they replace:

```
MP does not apply.
  → slot-unsatisfied  slot 1 wants `(p -> q)`; nothing cited fills it

GEN does not apply.
  → side-condition    proviso `not occurs(x, p)`, against line 1
```

A slot's schema is reported as the author would write it (`( p -> q )`), not as
`str(pattern)` — which is the class-prefixed repr and names the machinery rather
than the schema. A proviso is reported in the author's own words, which is why the
build now keeps each one's source line beside its parsed form
(`InferenceRule.side_condition_sources`).

**Stored, not recomputed.** `proof_lines.failure_code` and `failure_detail` carry
it, because the rows are the read path — a caller asking why a stored proof fails
should not have to re-verify it — and because `hole` rides in the same field, so
"which lines are still open" is a query rather than a scan.

## 8. Holes — *done*

A line cited `[?]` is an **open goal**: its formula is parsed and termed, it may be
cited by later lines, and the proof containing it is *incomplete* rather than
*wrong*.

`HOLE_KEY` follows `DEFINITION_KEY`'s precedent exactly — a keyword intercepted in
`get_reference`, with a same-named inference rule still winning, so a system may
repurpose it. The one constraint a hole inherits from the grammar is that the
system's **reference part must admit the keyword's characters**; the Metamath
importer's `_REFERENCE_REGEX` is widened for `?`, and a hand-authored system
declares its own.

### Why a hole is not valid

The tempting design is a hole that is `valid = True` so that citing it works
cleanly. That is the one thing it must not be: `proof.valid` is `all(line.valid)`,
so a hole reporting valid would make a proof with an unproved step report as
proved — and promotion, which is gated on validity, would then publish it.

So a hole is `valid = False` with `failure.code == "hole"`, and everything that
already refuses an invalid proof refuses it for free. What the code buys is that a
*client* can tell an open goal from a mistake, and style, count and prioritise it
accordingly. Later lines may still cite a hole and check against it — that is the
point of a goal-directed workflow, and it is sound because the proof as a whole is
reported invalid until the hole is filled.

`Proof.holes` lists them and `Proof.only_holes` is the predicate a top-down author
(or an elaboration loop) works against: true means nothing is *wrong*, there is
just work left. False with holes present means both, and the errors come first —
filling a goal beneath a broken step proves nothing. Both reach the API as
`VerifyProofResponse.holes` and `.only_holes`, beside a `success` that is False
either way.

---

## 9. Reasoning over the DAG rather than over a projection

The question §3's option C invites: does making the *term* the buffer let a model
reason about proofs structurally instead of about one rendering of them? Mostly
yes — but "the DAG" is two different graphs, and separating them shows that half
of this is already true and the other half is exactly what C is.

### Two graphs

**The justification DAG** — lines and the edges between them. Already served as
structure: `GET /proofs/{id}/structure` gives per line the `rule` that justified
it, `antecedents` as typed edges (`role`, `position`, and either `line_id` or
`proof_id`/`number` for a citation reaching into a lemma), the scope tree through
`scope_id`/`opens_scope`, and the `definition_id` a definitional step applied. No
prose is involved anywhere in it.

**The term DAG** — what a statement *is*. Interned, shared, digested. Until §9a
below, the API stopped at the root: `TermSummary` gave `constructor`, `digest` and
`alpha_digest`, and a reader wanting the formula's *parts* fell back to `display`
or `rendered`. A string cannot be pointed at — "the second argument of the
application on line 4" is computable from rows and not from a rendering.

### The asymmetry C removes

A model can already **read** structure and must still **reply in prose**, then
hope the parse round-trips to the structure it meant. That round-trip is where
§2's 19 ambiguities bite, and it fails silently.

C makes the write path structural. The useful way to put it: a projection becomes
a **view** — lossy, disposable, chosen per call — rather than the **carrier**.
Many projections, one truth.

### The loop, and what supplies each part

```
get_goals(proof)     → the holes                              §8, done
expand(term, depth, notation)
                     → nodes, each with its id AND its reading §9a, done
propose(line, justification)                                  §9b, done
   {rule: "MP", antecedents: [4, 6]}          ← cite: no formula emitted at all
   {statement: {constructor: "wcel",
                slots: {A: {ref: "node:a3f"}, ← reuse, do not re-emit
                        B: {constructor: "cr"}}}}
→ accepted, or Failure{code: "slot-unsatisfied", slots: [{schema: "(p -> q)"}]}
                     → which becomes the next goal              §7, done
```

The loop closes: a failure names a missing premise, a missing premise is a goal, a
goal is a hole, a hole is fillable. Two properties prose cannot supply:

- **The vocabulary is closed and enumerable.** Constructor names come from the
  system's own grammar, so valid emissions are a finite set — which is what makes
  constrained decoding or a tool schema possible rather than aspirational.
- **Structure sharing survives the wire.** `{ref: "node:a3f"}` says "the thing at
  line 4's second slot" without re-emitting it. Where statements nest deeply that
  is the difference between a tractable emission and a long one that has to be
  exactly right.

### What it is *not*

Reasoning over the DAG with no projection at all is neither achievable nor
desirable. A model's competence is in mathematical prose and LaTeX; node ids carry
no semantics for it. The realistic split is **perception stays a projection** —
but an annotated one, every rendered subterm tagged with its id, so the model can
point without restating — and **commitment is structural**, so a mis-translation
between the two is a caught error rather than a different term. That is the same
resolution §4 reached for B: take the fluency at the translation boundary, not by
making the carrier ambiguous.

### Staging

C is not all-or-nothing, and the cheap half is the bigger half.
`{rule: "MP", antecedents: [4, 6]}` is already fully structural — a label and two
integers, no term emission whatever — and in an imported Metamath corpus the
overwhelming majority of steps are exactly that shape. Only *new statements* need
the expensive half. So:

1. **Term subgraph, readable** — §9a, done.
2. **Structured citation proposals** — §9b, done.
3. **Structured statement proposals** — the term-building half, and the only part
   that needs a real constructor vocabulary over the wire.

### What none of this solves

Which of 47,589 theorems to cite. That is retrieval and it is separate — though
`alpha_digest` is a strong primitive for the exact case: "have I already got this,
up to renaming?" is an index lookup rather than a search.

## 9a. The term subgraph, served — *done*

`GET /formal-systems/{system_id}/terms/{term_id}` returns a stored term's nodes.

Against the **system**, not a proof, because that is what a term belongs to:
interning is per system, and one row is the statement of however many lines happen
to share it. Visibility is therefore the system's, and a term id the system does
not own is a 404 rather than an empty graph — a caller holding an id from
elsewhere has made a mistake worth hearing about.

**Flat, not nested.** A term is an interned DAG: a subterm two positions share is
one row with one id. Nesting would emit it twice, losing exactly the structure
sharing the storage exists for — and with it the ability to refer to a part rather
than repeat it. `(x = y → x = y)` comes back as **four** nodes — the implication,
the one equality both its slots name, and the two variable leaves — rather than
the six a tree would have.

**Every node carries its reading**, when a `notation` is asked for. That is the
annotated projection §9 wants: identity *and* rendering of every part at once. A
node at a `depth` horizon still reads in full — `depth` bounds what is listed, not
what is rendered, or a shallow request would be useless.

**`truncated` distinguishes a horizon from a leaf**, and a truncated node still
reports its `children`, so a second, deeper request can be aimed rather than
repeated. It is decided against what the walk *emitted* rather than against where
the bound fell: in a DAG a child beyond one node's depth is often reachable within
another's and already in the response, and calling that incomplete would cost a
caller a deeper request that returns nothing new.

Four implementation notes worth not rediscovering.

The digests are fetched by a **second query** rather than added to `StoredTerm`:
the sweep that builds a `TermGraph` runs on every proof view and every
check-from-rows, and neither needs them, so widening it would put two columns per
node on the hot path to serve a reader that asks rarely.

`depth` bounds the **output** rather than the read — the sweep already fetches the
closure in one query, so a shallow request costs the same and simply says less.

Visibility uses `readable_system_id_or_404`, a cheap twin of the usual check.
`_get_readable_or_404` hydrates the whole grammar — symbols, lines, definitions
and their provisos, axioms, rules — which is right for a route that renders a
system and badly wrong for one asked repeatedly for a single row of something
else.

Rendering is **one shared fold** (`notations_mapping.render_each`), not
`render_stored` per node. Per node re-walks that node's whole subtree, so
rendering all of them costs the sum of the subtree sizes; one memo across the
calls makes it linear. Sound because a stored term graph is acyclic by
construction — `store_term` interns bottom-up, so a node can never be its own
ancestor and its rendering cannot depend on the path taken to it.

## 9b. Structured citation proposals — *done*

`POST /proofs/{proof_id}/cite` justifies a line by naming a rule and the lines it
uses. `{line: 7, rule: "MP", antecedents: [4, 6]}` — a label and three integers,
already unambiguous, and needing none of the system's citation syntax. Making a
client format `[MP, 4, 6]` is exactly where a projection would creep back into a
structured path.

**A dry run by default.** A caller trying several justifications for one hole
should not have to undo the ones that did not work, so nothing is written unless
`apply` is set — and applying requires ownership, as any edit does. A published
proof can be *proposed against* by anyone and edited by no one but its owner.

**Checked in the proof's whole context**, because that is the only place a
citation means anything: scope, ordering and what stands above the line all bear
on it. `_verify_with_references` takes a `source` override for this — the stored
rows describe the stored source, so an override skips them rather than treating
them as stale, which they are not; they are about a different text.

**A rejection names the next goal.** The outcome carries the same `Failure` §7
gives a verify, so a citation that does not apply says *which premise is missing*
rather than only that it failed. That is the loop closing: goal → proposal →
failure → goal.

**A hole is a citation**, so retracting a step needs no second endpoint: propose
`rule: "?"` and the line is an open goal again.

**Applying is a source edit**, and carries every consequence of one. That is not
a formality: without them a proof laundering through a lemma broken here would
keep verifying against a cached verdict for a source that no longer says what it
did. So the apply branch mirrors `update_proof`'s post-edit block — discard the
stored check, invalidate dependents, retire the promotion, and re-gate a
*published* proof, which may not be edited into a non-verifying state and for
which `[?]` is exactly such an edit. Discarding first is load-bearing rather than
tidy: a verify prefers rows to text, so leaving the old structure would make the
publish gate re-check the previous source and wave the rewrite through.

### Composing and replacing, self-checked

`FormalSystem.cite(rule, antecedents)` composes the reference text — the label and
the numbers joined by `proof.CITATION_SEPARATOR`, which the reader and the writer
now share rather than each spelling `", "`.

`FormalSystem.recite(text, citation)` puts it into a line. A `Match` records no
positions, so the substitution is **textual** — and therefore self-checking: the
result is re-read, and returned only if its citation reads back as the one asked
for. A line whose formula happens to contain its own citation text, or a citation
the grammar's reference part cannot spell, is refused rather than mangled. That
turns a fragile splice into a safe one, and it is why `recite` returns
`str | None` rather than a string it hopes is right.

### The limits, deliberately

A line is addressed by its **citation number** — the handle an antecedent edge
already uses — which needs the proof's stored structure, so an unverified proof
gets a 409 saying to verify first rather than a guess.

A line whose citation the checker never **resolves** is refused rather than
reported on. A scope opener is granted by fiat — a hypothesis holds for its
subproof, a fresh variable is introduced — and an axiom line asserts itself; both
are valid whatever their reference says, and nothing stops a system declaring a
reference field on either. Reading a proposal's outcome off such a line's validity
would answer `accepted` for a citation nothing looked at, so the line type is
checked from the stored row before any work happens.

The system is built **twice** per request: once here, to read the line being
rewritten, and once inside the verify. Both builds now take the cached schema and
definition terms, so neither re-parses a rule schema — but a single build would
need `_verify_with_references` to accept a pre-compiled system, which is a wider
change than this warranted. Worth doing if a search loop ever proves hot.

And this only *re-justifies an existing line*. It cannot add one, because adding
a line means stating a formula, which is §9's step 3 and the half that needs a
constructor vocabulary over the wire. In an imported Metamath corpus the
overwhelming majority of steps are citations of previously proved theorems, so
the cheap half is also the common one.
