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
`set.mm`'s LaTeX reading. As a display that is cosmetic; as a *source* it means
text no longer determines the term. The report also explicitly does not certify
absence, so an empty result would not settle it either.

They are **two problems, not one**, and only the first is the one this section
used to describe:

| | | what would settle it |
|---|---|---|
| **11** | a constant against a class *variable* of the same spelling — `+` is both `caddc` and a variable named `.+`; also `-`, `/`, `0`, `1`, `<`, `R_1`, `\cdot`, `\le`, `\perp`, `\uparrow` | a policy: spell class variables distinctly, once, for all of them |
| **8** | two distinct *constants* sharing a spelling — `citg1` and `citg2` both read `\int_2`; also `+\infty`, `-\infty`, `\Lambda`, `\mathrm{O}`, `\simeq_r`, `\times_s`, and `Se` (two `wff` productions of identical shape, `w-bnj13` being the Bernays section re-declaring it) | per-token editorial judgement — there is no rule to apply |

The second kind is upstream: `set.mm`'s own `latexdef` map is not injective, with
**39 spellings shared by two or more of its 1,794 tokens** (`S.1` and `S.2` both
declare `\int_2`). No amount of namespace work fixes those — one of each pair is
simply mis-spelled, and deciding which is a reading of the mathematics.

That split is why "decide the 19 pairs" is not one task. Ten minutes of policy
covers eleven of them; the other eight are eight separate judgements.

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
   mechanism aimed at input instead of display. `set.mm` itself distinguishes the
   *variable* half of them (§2's eleven) **by colour** in `htmldef`, which
   `as_text` drops by policy; colour is not typeable, so that does not rescue the
   source case, but it does mean that much of the ambiguity is ours rather than
   theirs. It does not extend to §2's other eight, where two constants share a
   spelling in `latexdef` itself and colour would not tell them apart either.

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
3. **Structured statement proposals** — §9c, done.
4. **Retrieval** — §9d, done. Which of the 47,589 to cite.

### What none of this solves

Which of 47,589 theorems to cite — *was* this section, and it was wrong to file it
as a nicety. The loop closed without being **driveable**: `slot-unsatisfied` says
"I need `(p → q)`" and nothing answered "here are the twelve theorems that could
conclude that", so on a corpus-sized library a caller had no move. That is §9d
below, and it turned out to be smaller than option D rather than adjacent to it.

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

## 9c. Structured statement proposals — *done*

`POST /proofs/{proof_id}/lines` adds a line stating a proposed term. This is the
expensive half: a citation is a label and some integers, but *stating* a formula
needs the grammar, so this is where a constructor vocabulary crosses the wire.

A `Proposal` is one of three things, and exactly one:

* **`ref`** — a term that already exists. The reason the whole thing is worth
  having: an interned term is shared, so a caller says "that subterm" instead of
  restating it. Where statements nest deeply that is the difference between a
  tractable emission and a long one that has to be exactly right.
* **`constructor`** — a production by name, with a proposal per slot. The
  vocabulary is the grammar's own, so it is closed and enumerable — which is what
  makes a constrained emission possible rather than aspirational.
A metavariable is deliberately **not** among them, though the engine's `Proposal`
has that arm. A proof line states a *ground* formula; a schematic variable belongs
to a rule schema or a promoted theorem's statement, and one proposed for a line
could not survive the round trip — `Q` parses back as the grammar's variable
*production*, a `Node`, not as a `Var`. Offering it and refusing it would be worse
than leaving it out.

### The round trip is checked, not trusted

Resolution is not a second parser. Nothing reads surface syntax; a proposal names
productions, and the text it becomes is `rendering.render` of the resolved term —
**the source spelling by construction**, because a production's render steps *are*
its source template.

That is what lets the round trip be verified per proposal: render the term, splice
it in, parse it back, and refuse the line unless the term that comes out is the
term that went in. A caller never has to be believed about what it meant, and no
ambiguity can pass unnoticed — which is precisely the guarantee §4 said a
notation-as-source path could not offer.

Three checks stack, each at its own level. `restate` and `recite` are
string-level and self-checking (the formula and the citation must read back as
written). The term comparison is the real one, and it compares **digests** rather
than terms: the proposal is resolved against the system built to compose the line
and the line is parsed against the one the verify builds, and a `Var`'s sort
compares by object identity, which does not survive two builds. A digest is
structural.

What the round trip cannot catch is a proposal that was *ignored* rather than
misread — a `ref` carrying slots, say, where the referenced term is exactly what
comes back. So the resolver refuses any field an arm does not use, rather than
quietly doing less than was asked.

### Inserting costs a renumbering

`before` names the citation number to insert ahead of, which is what a
goal-directed caller wants: a rule's antecedents must precede its conclusion, so
a premise for a hole goes *above* it. Appending displaces nothing and needs none
of this.

Citation numbers are positional, so a line added at `n` moves everything below it
— and every citation naming one of those lines now names the wrong one
**silently**, because the old number still resolves. `FormalSystem.renumber`
shifts them, and only bare integers: a rule's label, the definitional and hole
keywords, and a dotted lemma reference (`[MP, A.2]`, whose `2` is a line of
another proof) are left exactly as they are. It refuses wholesale rather than
rewriting in part, since a half-renumbered proof is worse than an untouched one.

The guard that matters is after the fact: **no line that was valid before may be
invalid after**. A mis-shifted citation still resolves, so nothing else would
catch it.

### Composed from a neighbour, not from a line type

A new line takes its text from an existing one — `restate` swaps the formula,
`recite` swaps the citation — so it inherits that line's type, shape and
indentation. The indent is put back explicitly, because `display` is stored
*stripped* with the indent in its own column; a line composed from it and written
as-is lands at the root, silently escaping the subproof it was meant to join. That avoids reconstructing a line type's syntax from its pattern,
which is the one piece of surface-syntax composition this would otherwise need,
and it makes the indentation right for the scope the line lands in.

The consequence is that a proof with no ordinary logical line has nothing to copy,
and says so. A scope opener is refused as a template for the same reason `/cite`
refuses one as a target: it states nothing checkable.

### Taking a line back out — *done*

`POST /proofs/{id}/lines/remove` is `/lines` inverted, and the same renumbering
run backwards: everything below the removed line closes up by one, and a citation
naming one of those lines has to follow it or it silently names another.
`FormalSystem.renumber` grew a `by` rather than a second copy of itself.

The guard is the same one and for the same reason — **no line that was valid
before may be invalid after** — with the removed line itself excepted, since it is
meant to be gone.

What is *not* symmetric is a line another line **cites**. An insertion can always
be undone by not making it; a removal that orphans its dependents has no answer to
give them, so it is refused with their numbers rather than applied. That is
decided from the stored edges, before anything is built.

### What is still not here

Moving a line. Unlike a removal it is not one shift: the lines between the old and
the new position move by one and everything else stays, so the rewrite is a
permutation rather than an offset — and a move that crosses a citation is a
reordering of the proof's dependencies, which is a different question from
renumbering it. Neither it nor removal is needed to *build* a proof, which is what
the loop does; removal is here because undoing a step the loop tried is.

## 9d. Retrieval — the loop, driveable — *done*

The loop §9 drew closes: a failure names a missing premise, a missing premise is a
goal, a goal is a hole, a hole is fillable. What it could not do is *move*. Every
step of it takes a justification as an input — `/cite` asks whether **this** rule
applies, and `propose` asks whether **this** statement checks — and nothing
produced one. On a library of 47,589 entries "try them all" is not an
implementation.

Two endpoints, split by what each can afford.

`GET /formal-systems/{id}/theorems/matching?term=…` is the **filter**. A
conclusion's root production is a column (`terms.constructor`, indexed per
system), so "theorems concluding an implication" is an index scan; α-identical
conclusions sort first, which is `alpha_digest` covering the exact case exactly as
§9 predicted. It builds nothing and confirms nothing, and says so.

`GET /proofs/{id}/lines/{n}/citations` is the **answer**. It returns
justifications that *check* — in `CitationProposal`'s own shape, so acting on one
is a copy into `/cite` rather than a translation.

### Why the confirm lives on the proof and the filter on the system

A library belongs to a system, so retrieval is the system's; but *confirming* a
candidate needs the system built, the theorems promoted, and the goal in a real
scope with real lines above it — which is a proof's context and nothing else's.
Checking a proof has already paid for all of that, so unifying twenty-five
candidates there is nearly free, while doing it behind a browse would put a system
build on a GET that invites being called repeatedly.

So the system route narrows and the proof route decides, and neither pretends to
be the other. A candidate is not an answer, and the schema says which it is.

### Two pools, bounded differently

A system's **rules** are few, so every one is tried — no retrieval needed or
wanted. Its **library** is unbounded, so it is narrowed first and only the
survivors are unified. That asymmetry is the whole design: the prefilter exists
because one of the two pools cannot be enumerated, not because unification is
slow.

Both are confirmed identically, because a promoted theorem *is* cited as a rule
(`PromotedTheorem.as_rule`). The `source` field records where a suggestion came
from and nothing about how it was checked.

### What had to change in the engine, and why

`InferenceRule.check` **recorded its verdict on the line** — `valid = True`, the
inference, a dependency edge on every antecedent. That is right for a checker,
which asks once, and wrong for a search, which asks a hundred times and keeps one
answer. Split into `applies` (the verdict, returned) and `check` (the verdict,
recorded); `check_discharge` split the same way into `discharges`. A search that
merely *asked* what could justify a hole would otherwise have filled it in, and
left every rejected candidate's bookkeeping behind on the way.

Added beside them: `concludes`, the conclusion-side twin of `slot_admits`, which
is the filter the search runs before any antecedent work — a rule that cannot
conclude the goal cannot justify it however its slots are filled.

### Two pools of *lines*, which is not obvious

An ordinary rule cites antecedents; a discharge rule cites a subproof's **opener**.
An opener lives *inside* the subproof it opens, so a line below cannot cite it as
an antecedent — and discharging it is exactly what it can do instead. Neither pool
contains the other (`accessible_lines`, `dischargeable_openers`), and conflating
them either offers citations the checker refuses or hides every discharge — which,
in a natural-deduction system, is every rule that closes a subproof.

### A rule that justifies everything

A hypothesis rule has no antecedents and a bare metavariable for a conclusion, so
it applies to every line in the system. `[HYP]` is a true answer to "what could
justify this?" and an uninformative one, and it would have headed every result on
needing no premises. Reported, flagged (`assumption`), ranked last —
`concludes_anything`. Not dropped: assuming the line is sometimes what an author
means to do, and a search that hid a legal move would be lying about the system.

Note the criterion is *both* halves. Modus ponens also concludes a bare
metavariable — everything it tells you is in its premises — so specificity of the
conclusion alone would have demoted the most useful rule in the system.

### What the filter cannot see, and says so

A theorem whose `statement_term_id` is NULL has no constructor to filter on. That
is a cache miss and not an absence — but retrieval is the one reader that cannot
pay a re-parse to recover from it, because it is choosing *which* theorems to look
at at all. So the count is reported (`unindexed`) rather than the rows being
quietly missing: a short list must not read as a complete one.

The same reasoning covers a **renamed** layer. A related system may spell the
goal's production differently, so the goal's constructor is inverted into each
layer's own names before its rows are asked (`Translation.stored_name`, whose
inverse is well-defined precisely because `translation_errors` refuses a map that
collapses two source names into one). Asking every layer about the citing system's
spelling would have returned nothing from exactly the edges a rename exists to
cross — a false negative, and the kind nobody would ever notice.

### Depth one, and honestly so

A suggestion justifies a line **from lines that already stand**. It does not prove
a gap: "here is my next step, find the four lemmas between it and what I have" is
a search over sequences of steps, which is elaboration (§3's option D) and remains
a different piece of work. What this supports is the step a caller has already
stated — which, in an imported corpus, is the overwhelming majority of what a
proof is made of.

### What this is not, and what would sharpen it

The prefilter is a **head-symbol** filter, which is the cheapest useful one and
deliberately not the best. A discrimination tree over the whole term
([search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md) Phase 1)
prunes far harder — `(A ∧ B) → C` against every stored implication is still a lot
of implications. The reason to do this one first is that it needs no new
representation and no new storage, only columns that already exist, and it sits
behind the same interface a term net would: candidates in, unification confirms.
Replacing `conclusion_candidates` is a local change when that index arrives.

## 9e. Driving the loop on a corpus — *done*

Everything in §7–§9c was exercised by three-line synthetic proofs. Nobody had run
the loop against `set.mm`, and that is where the remaining risk sat: corpus proofs
are a hundred lines long, cite theorems with a dozen premises, and are written in
a grammar with several thousand productions rather than four.

`scripts/restore_proofs.py` closes that. The trick that makes it tractable is that
the corpus is its own **answer key**: blank a step's citation and the right answer
is already known, so "did the loop get there" is an exact question and needs no
retrieval and no search. Five rounds — restore blanked citations, dry-run an
insertion, restate a formula from stored rows, offer deliberately wrong citations,
and really apply an insertion and read the structure back — over an imported slice
in a throwaway database. `scripts/README.md` has the operating instructions;
`tests/test_restore_proofs.py` runs the whole thing over a four-proof `.mm`
fragment so the harness itself does not rot.

### What it found

**`Proof.justify` had an arity cliff.** A citation naming *no* antecedents asks the
checker to infer them from the lines immediately above — a real and useful path,
and the one an author uses most. It was gated at `len(rule.antecedents) < 5`: the
permutation guard from before the assignment search became a bipartite matching,
left behind when the search was replaced (the `MAX_CITED_ANTECEDENTS` comment a few
lines below already records that the reasoning had lapsed). What it cost was not
only a restriction but a **lie**: a five-premise rule cited with none was told it
"requires 5 antecedent(s)", which reads as *too few given* when in fact nothing had
been looked at.

`set.mm` reaches it — 47 of the promoted theorems in its first 3,000 take five or
more premises, and `cbvald`'s step 6 cites exactly the five lines above it, which
is precisely what the branch would have inferred. The bound is now the same
`MAX_CITED_ANTECEDENTS` the explicit path uses. Where the lines above are *not* the
premises the rule wants, the verdict is now `slot-unsatisfied` or
`inconsistent-binding` — a reason rather than a miscount. The corpus re-imports
with the same 3,000 verified, 0 rejected.

### What it measured

The reference run: `set.mm`'s first 3,000 theorems, the 20 longest proofs among
them (693 steps), all five rounds — **100 round-results, all passed, 2,105 calls**.
The probes are where the interesting part is. Each of the four assertable
mutations landed on its code every single time:

| offered | told | n |
|---|---|---|
| a rule name nothing declares | `bad-reference` | 120/120 |
| one antecedent too many | `antecedent-count` | 120/120 |
| one antecedent too few | `antecedent-count` | 46/46 |
| the line itself among its antecedents | `ordering` | 64/64 |
| the antecedents reversed | *accepted* | 46/46 |
| no antecedents at all | accepted 35, refused 29 | 64 |

Three facts fall out, each of which changes what an emitting model should bother to
get right:

**Antecedent order carries no information.** Every swapped citation was accepted.
The assignment search is a bipartite matching over slots, so a citation is a *set*
of lines and the order is presentation. A model that treats getting the order right
as part of the task is spending effort on a degree of freedom that is not one.

**Omitting antecedents is not an error, it is a request.** A citation with none
means "the lines immediately above", and on real proofs that lands over half the
time — the corpus is written in dependency order, so the premises usually *are* the
preceding lines. It is a genuinely different citation from the one the model may
have meant, though, so the loop should always emit antecedents explicitly and treat
the inference as a convenience for humans. The 29 that did not land came back as
`inconsistent-binding` (26) or `slot-unsatisfied` (3) — a reason, not a shrug.

**Every refusal landed in §7's closed vocabulary.** No wrong citation came back
with a bare sentence and no code. That is the claim §7 makes and the one synthetic
fixtures could only illustrate.

### Deeper in

The same rounds against **14,000** theorems — into ZF proper, where statements
carry class abstractions and function application — pass too: the 20 longest proofs
there run to 454 lines and cite up to 10 antecedents in a single step, and 160
`state` restatements came back spelled exactly as `set.mm` spells them. That is the
strongest thing the `state` round says, because it is the one place a projection
could silently creep back into the write path: the round emits productions and
compares the *text* that comes out against the corpus's own.

The one restatement that blew the round's node budget was not from here. It was
`retbwax1` line 23, in the *propositional* slice — a nest of implications sharing
one subterm many ways, which as a tree is far larger than as the interned DAG it is
stored as. Nothing in the ZF slice came close. So the expansion hazard tracks
**sharing**, not the depth of the theory, and it is exactly the case `ref` exists
for (§9a) — which this round deliberately declines to use, so that the render and
the reparse are what is being tested.

### The cost — *closed, and not where this said it was*

Measured on the *same five proofs and the same 34 calls* against three imports, so
the only variable is the system:

| corpus | per call, before | after |
|---|---|---|
| 400 theorems | 65 ms | **45 ms** |
| 3,000 theorems | 80 ms | **56 ms** |
| 14,000 theorems | 136 ms | **93 ms** |

Sublinear in the corpus — a 35× corpus costs about twice as much per call —
because what grows is the *grammar* rather than the library, and a library is
resolved label by label rather than built (docs/verification-from-rows.md, P4).

**The diagnosis this section originally gave was wrong**, and the correction is
the useful part. It said the assembled `FormalSystem` was the thing to cache.
Profiling one `/cite` against the 14,000-theorem import says otherwise:

| | per build |
|---|---|
| `load_system` — the parts, as ORM rows | 36 ms |
| `load_effective` — the chain, into a spec | 5 ms |
| the cached schema and definition terms | 1 ms |
| `build_spec` | 12 ms |
| **one build, end to end** | **54 ms** |

`build_spec` is a fifth of it. Two-thirds is `load_system`, and that is not row
volume — the corpus system has 336 symbols and 241 bindings — but **thirteen
queries**, one per eagerly-loaded child collection, each crossing the async
greenlet bridge. It is latency, not work.

Which makes the fix simpler than a cache: **build once per request.** `/cite` and
`/lines` need the grammar before they can compose a line, and then handed the
verify nothing, so it loaded and built the whole system a second time — 2 builds,
26 queries, 2 `build_spec`s for one call. `_Built` is now one object carrying the
loaded system, its effective spec, the cached terms and the compiled system, and
`_verify_with_references` takes one instead of making one. `_require_publishable`
takes one too, which is what an applied `/cite` on a published proof re-gates
through — after its two cheap gates, so a publish refused for a draft system still
pays nothing for a compile it would throw away.

**Every build is now inside the system lock**, which the build used to rewrite a
line was not: `/cite` and `/lines` take it before they compose, and the publish
gate takes it on the one path that holds none of its own (`PATCH` with only
`published`). That matters beyond tidiness — the grammar a line is composed
against is now provably the grammar the check runs against.

Structural, so it is pinned structurally:
`test_a_citation_compiles_the_system_once` counts `build_spec` calls rather than
timing anything, and both new tests report `[2] == [1]` against the old code.

**What is deliberately not done.** A cache *across* requests would take the
remaining 54 ms to nearly nothing, and it is the wrong trade at this size. Its key
has to be readable without doing the work — which rules out any digest of the
spec, since computing one means loading the rows that cost the 36 ms — so it needs
a version stamp on `formal_systems` that every write to the system *or any of its
parts* bumps. That is precisely the invalidation cascade `app/db/schema_terms.py`
was written to avoid ("freshness is decided, not maintained"), and the failure
mode of a missed write path is a proof checked against a grammar that has moved.
Not worth it to save 54 ms on a request that no longer does it twice.

### What it still does not reach

The corpus is flat: a Metamath proof has no subproofs, so nothing here exercises
scope openers, discharge lines or indentation, which is exactly the ground the
synthetic fixtures do cover. The harness knows it — a proof whose citation numbers
do not run 1..N with a rule behind each is skipped rather than mis-asserted, since
the rounds predict a renumbering from a count.

And 14,000 theorems is not 47,546. Nothing stops the harness running against the
whole corpus — that import is a solved thing (metamath-import-roadmap §1.1) — but
these runs imported into SQLite, where 14,000 theorems already takes 27 minutes and
half a gigabyte, so the ceiling reached here is the throwaway database's rather
than the engine's. A whole-corpus run wants Postgres and a longer budget.

---

## 9f. The other half of a diagnosis: why a line *did* check — *done*

`diagnostics` (§9b, `Failure`) answers "why did this line not check", in a closed
vocabulary a caller branches on. Nothing answered the question a *valid* line
raises, and on an imported corpus that is the harder one: a line carries
`[imbi12d, 2, 3]` and a reader who does not already know `imbi12d` — which is
every reader, at 47,546 theorems — learns from it only that something applied.

**Everything needed was already computed and thrown away.** A rule is a schema
and a step is an instance of it, so "why does this follow" is answered by *what
the metavariables stood for here* — the binding `InferenceRule.applies` derives
and keeps for schematic promotion. Beside it sit the rule's own schemas, which
cited line filled which slot (the assignment search's own output, aligned to the
rule's slots), and the provisos checked over that binding.
`formal_system/justification.py` assembles those; it computes nothing, and like
`diagnostics` and `rendering` it is display, so a wrong record misleads a reader
and cannot make a false proof check.

**Served checked, not read** (`GET /proofs/{id}/lines/{n}/justification`), which
is the one real cost and the same trade `/lines/{n}/citations` already makes: the
substitution is derived by the match and no stored row carries it. Storing one per
citation was the alternative and is the wrong trade at this scale — set.mm's
proofs make roughly 4M citations, so a row per bound metavariable is tens of
millions of rows written on import for a record read one line at a time, on a
hover. The endpoint is asked once per card opened.

**Two steps carry less, and say so.** A discharge rule consumes a subproof rather
than cited lines and `check_discharge` keeps no binding, so its record names the
block and offers no assignments. A definitional step cites no rule at all — the
checker searches the definitions in scope — so its record is the definition that
applied, which is the one thing a generic `[Def, n]` citation cannot tell anyone.

**What is deliberately not composed** is the *instantiated* proviso. `restate`
would give one, but rendering it means inventing a phrasing for each of the
kernel's predicates, and a proviso in the author's own words (`x not free in phi`)
beside the assignments it names already says the same thing without a phrasing
layer of ours to keep in step with the kernel's.
