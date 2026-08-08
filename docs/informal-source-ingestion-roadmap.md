# Ingesting an informal proof

A companion to [authoring-and-ingestion-roadmap.md](authoring-and-ingestion-roadmap.md).
That document ends with the **inner loop** built and measured: a goal is a hole, a
hole is fillable, a failure names the next goal, and retrieval says what to cite
(§7–§9e). Everything it exercises assumes a proof object that already exists, in a
system that already spells the mathematics, aimed at a statement someone has
already decided is the right one.

This document is about the **outer loop** — what happens between an arXiv paper
and that starting point — and about the one thing the outer loop must not be
allowed to do, which is to launder an unverified judgement into a green tick.

---

## 1. What the checker can and cannot certify

The kernel certifies exactly one sentence:

> this sequence of steps establishes **this term** in **this system**.

An informal source adds three claims that sit entirely outside it:

1. **Fidelity.** That the term *is* the paper's theorem. Nothing mechanical
   decides this. A mis-formalised statement that checks is a green proof of
   something else — the worst failure class in autoformalisation precisely
   because it is invisible (§4 of the authoring roadmap made the same point about
   ambiguous notation, one level down).
2. **Alignment.** That the paper's `∫`, `⊆`, "measurable" are the system's
   `citg1`, `wss`, and whichever of the corpus's several notions the author meant.
   Partly mechanical (a term either parses or it does not), mostly not (which
   production the author *meant* is a reading).
3. **Standing prerequisites.** That the results the paper cites — "by Lemma 2.1
   of [7]", "by compactness" — are in the library, are the same results, and are
   proved rather than assumed.

None of the three is checkable, and all three are unavoidable. So the design
principle for everything below:

> **Do not try to verify the unverifiable. Make it explicit, attributed,
> queryable, and impossible to lose.**

That is the same instinct the codebase already has in two places. `Provenance`
answers "which axioms does this theorem rest on" from rows rather than trusting
where a proof was filed. Retrieval reports `unindexed` rather than silently
returning a short list, "because a short list must not read as a complete one". An
ingestion pipeline needs the same discipline applied to fidelity and to
assumptions.

## 2. The split of responsibility

| | owns | why it is there and not elsewhere |
|---|---|---|
| **Engine** | what a proof *is* — terms, rules, scopes, checking, the closed failure vocabulary, unification-confirmed retrieval | it is the only thing trusted; every new concept below is asked whether the kernel must learn it, and the answer is almost always no |
| **API** | small, deterministic, authenticated, idempotent moves over stored rows: CRUD, search, propose-and-check, the honesty ledger | it is the only thing that can be *called a thousand times by a retrying agent*, so everything it does must be cheap, replayable, and safe to abandon halfway |
| **Consumer (LLM)** | reading, segmenting, deciding what a symbol means, judging whether a retrieved theorem is the lemma the paper cited, choosing to stub or to prove, and the prose→structure translation | every one of these is a *reading of mathematics*, which is the one thing a model is better at than a query |

The line to hold: **the API never guesses and never accepts prose as evidence.**
A model's judgement enters as a recorded attestation with an author, not as a
fact. The consumer never emits surface syntax — it emits constructor proposals
and rule/antecedent citations, both from closed enumerable vocabularies, which is
already the shape `/proofs/{id}/lines` and `/proofs/{id}/cite` take.

## 3. What is already built and needs nothing

Worth stating, because it is most of the mechanism and it changes what remains
to be done into a much smaller list.

- **A partial proof is a first-class object.** `[?]` is an open goal; `holes` and
  `only_holes` distinguish "unfinished" from "wrong"; a hole is `valid = False`
  so nothing downstream can publish or promote through it (§8).
- **Failures are structured**, from a closed vocabulary, stored on the row
  (§7). `slot-unsatisfied` *is* the next goal.
- **Writes are structural.** `/cite` for a justification, `/lines` for a stated
  formula, `/lines/remove` to undo one — all dry-run by default, all round-trip
  checked by digest rather than trusted (§9b, §9c).
- **The vocabulary is enumerable.** `GET /formal-systems/{id}` returns the
  productions, so a constrained emission is a query, not an aspiration.
- **Retrieval works and is honest about being a filter** (§9d).
- **The term DAG is readable**, every node with its id *and* its rendering, which
  is what lets a model point at a subterm instead of restating it (§9a).
- **Cross-system citation exists** — relations, `Translation`, `StatementTemplate`
  — so a paper's theorem need not be formalised in the same system its
  prerequisites live in.

## 4. What is missing

Six gaps, in dependency order. The first two are the honesty machinery and
everything else produces artifacts that would otherwise quietly lie.

### 4.1 Assumptions, as first-class citable entries — *done*

A translation cannot proceed top-down without citing results it has not proved.
Today the only two ways to do that are both wrong: promote something unproved
(refused, correctly — promotion requires a published, verifying proof), or leave
a hole (which blocks every dependent step, so nothing downstream can be
translated until everything upstream is finished).

What is needed is a third move: an entry with a statement, no proof, and an
explicit reason. This section first proposed it as a third value beside
`promoted_theorems.primitive`; it is not, and why not is under "what it turned
out to be" below.

*Engine:* almost nothing. An assumed entry is cited exactly as any other
(`PromotedTheorem.as_rule`), and the kernel must not learn the distinction — a
proof citing one is a perfectly good proof *of a conditional*. The difference is
entirely bookkeeping.

*API:* `POST /formal-systems/{id}/assumptions`, with the statement written as
source text in the system's own grammar — the form
`promotion.promote_from_source` already reads, so an imported theorem and an
assumed one arrive the same way. A structured (constructor-vocabulary)
alternative waits on §4.4 rather than being guessed at now. `reason` is required;
`source` is free text, because structuring a citation is §4.3's job.

*Consumer:* decides what to assume, and what the assumption's informal source is.

**What it turned out to be.** Almost nothing, which is the sign the modelling was
right. The entry is a promoted theorem with `primitive` set and `proved_by_id`
NULL — exactly what it is to a citation — and the debt is a side table beside it
(`app/db/assumptions.py`). `primitive` answers "does this system assert this
without proving it", a question about *checking*; "foundation or debt" is a
question about the *development*, and only the second is ever paid down. The
kernel, unification and `promoted_theorems_mapping` learn nothing.

Adding one changes what a label resolves to, which is the same event as promoting
a theorem — so it takes the system lock and runs the same `invalidate_citations`.
Withdrawing one is the mirror. What withdrawal deliberately does **not** do is
retire the promotions of the proofs that cited it: those proofs are unchecked
rather than disproved, and that is the shape retiring any entry already has
rather than a new cascade invented here.

One limit worth recording: a *ground* statement the grammar cannot read is
refused, and a *schematic* one is not. That is the engine's settled position — a
schema that parses nothing yields a theorem that never applies, exactly as an
authored rule's does — and this route does not overrule it.

### 4.2 Provenance extended to assumptions, and exposed — *done*

`app/db/provenance.py` already walks the citation graph transitively and reports
the deepest layer and the axioms reached. It is not on any route — it is a
script. Two changes:

- **`assumes: tuple[str, ...]`** beside `axioms`, computed by the same closure.
  "What does this rest on that nobody has proved" is exactly the question the
  existing walk answers, one predicate away.
- **`GET /proofs/{id}/provenance`**, and the same summary inline on `ProofDetail`
  and `PromotedTheoremOut`.

Then the gate. A proof resting on an assumption may be **published** — a
conditional result is a legitimate object and hiding it helps nobody — but it is
marked, its promoted entry is marked, and the mark is transitive. Promotion of a
proof with a non-empty `assumes` is allowed and the entry inherits it; what is
refused is a *silent* one. The rule to enforce: **an entry's `assumes` closure is
never smaller than the union of its citations'.**

This is the single highest-value item here, and it is worth having even if no
ingestion pipeline is ever built.

**The closure is stored per library entry, not walked.** `theorem_assumptions`
holds what each entry transitively rests on, written when the entry is promoted
as the union of its citations' closures — so each promotion does *one hop*, and
reading a proof's debts is one hop as well, at any citation depth, in either
direction. An assumption carries a self-edge, so unioning the closures of the
entries a proof cites needs no special case for citing one directly. Ids and not
labels throughout, since a relation edge may rename a label across systems.

Two properties this buys that a walk would not. The **reverse** direction is a
single indexed count, which is what makes the public register below rank
anything. And an entry promoted before the table existed reads as an empty
closure, which is the *right* answer rather than a missing one — nothing can rest
on an assumption that did not exist when it was promoted.

**A proof reaches the library through two doors**, and the second has no label on
it. The first is a rule label its lines resolve (`proof_lines.rule`); the second
is a *lemma proof* whose lines it cites as `[alias.line]`, where the rule
recorded is whatever justified the step and the lemma's own citations are rows on
the lemma. Reading only the first calls a proof unconditional when every debt it
has came through a lemma — caught in review, with a test that reproduced exactly
that: `assumes: []`, `complete: true`, and an empty closure stored at promotion,
which would have made the loss permanent for everything built on top.

So `reference_closure` follows the **antecedent edges** first — what the checker
cited, not what `proof_references` declares, the same choice `provenance.py`
makes one level down — and the labels are read across the whole closure. That is
the one walk left, and it is over *proofs*: per-development and acyclic by
construction, not the corpus-scale library graph the stored closure exists to
avoid walking.

`GET /proofs/{id}/provenance` reads it, and reports what it could not account for
— one field per door. `unresolved`: a cited label that names no library entry, no
rule of the chain and no hypothesis of a theorem being proved. `unread_lemmas`: a
cited lemma proof holding no stored structure, whose own debts could therefore
not be read. A report that dropped either would say "rests on nothing" when the
truth is "rests on something I could not follow" — the same reasoning
`retrieval.py`'s `unindexed` already applies. A proof that has never been
verified has no resolved citations to read and is told to verify, rather than
told it assumes nothing.

The batch `app/db/provenance.py` report gained `assumes` beside `axioms`, and the
two **partition** the primitives reached: a corpus that adopts no assumptions
reports `axioms` exactly as it did before.

**The register is public.** `GET /assumptions/public` lists every assumption in a
published system, ordered by how many library entries rest on it — **transitively**,
which is the whole reason the closure is stored rather than the direct edges: an
entry three hops away that names the assumption nowhere still counts, and a count
of direct citers would rank a debt by how visible it is rather than by how much
has been built on it. That ordering
is the point rather than a nicety: a theorem everyone knows is true and Edifyce
cannot yet justify is the most useful thing this database can say about its own
gaps, and the count says which gap closing pays for most. Ordered in the database
rather than per page, since a ranking that only held within twenty arbitrary rows
would mean nothing.

### 4.3 The formalization record: source, claim, glossary

The object that does not exist at all. An ingestion run produces a proof, and a
proof has `title`, `description` and a system — nowhere to put *which paper*,
*which theorem in it*, *what the informal statement said*, or *what the model
decided `μ` meant*.

Three tables, all beside the engine and invisible to it:

| | holds | keyed by |
|---|---|---|
| `source_documents` | arXiv id / DOI / URL, version, retrieval date, content hash, licence | id |
| `formalizations` | one claim: the informal statement verbatim, the target `terms.id`, the proof attempting it, status, and the **attestation** (who or what asserted the correspondence, when, with what reasoning) | (document, claim) |
| `glossary_entries` | the paper's notion → the system's label or production, with the reasoning and the attestor | (formalization, notion) |

The content hash matters: a v2 of a paper may restate the theorem, and a
formalization pinned to v1 must not silently claim to be about v2.

The attestation is the part to get right. It is **not** a boolean "reviewed". It
is an author (a user id, or a model identifier and its prompt/version), a
timestamp, the informal text as it stood, and the prose reasoning. Fidelity is
reviewed by people; the API's job is to make sure the review has something
stable to point at and that its absence is visible.

*Engine:* nothing. This layer never reaches `website/logical/`.

### 4.4 Goal-first: state a theorem before proving it

Every structured write today is *inside* a proof — `POST /proofs/{id}/lines`
needs a proof, and a template line within it to inherit shape from. An ingestion
run needs the opposite order: state the target first, ask whether it is already
proved, and only then open a proof aimed at it.

- `POST /formal-systems/{id}/statements` — resolve a `Proposal` against the
  system's grammar, intern the term, return its id, its rendering, and *whether
  the library already concludes it* (α-digest exact hit, then the existing
  head-symbol candidates). This is "is this already proven?", which is the first
  question of any translation and currently has no answer that does not involve
  writing a proof first.
- The same call is what the glossary and the assumption endpoints take their
  statements through, so there is one path from a constructor vocabulary to a
  stored term and it is round-trip checked exactly once.

*Engine:* small. `proposals.resolve` already composes a term against a built
system; what it lacks is a caller that is not a proof line. The round-trip check
(§9c) is currently entangled with `restate`/`recite` line composition and needs
lifting out so a bare statement can be checked the same way.

### 4.5 Alignment tools: prose search, and the notation direction

Two lookups an aligning model needs and cannot make.

**Prose search.** `label_descriptions` holds `set.mm`'s 50,550 documented
assertions and is readable **one label at a time**. A model that has just read
"by the Cantor–Schröder–Bernstein theorem" has a name and needs a label. The
`theorems.embedding` column (pgvector, 1536, HNSW-indexed) has been provisioned
and unused since it was added. Wiring description text into it is Phase 4 of
[search-and-embeddings-roadmap.md](search-and-embeddings-roadmap.md) arriving
early and cheaply, because the alignment problem needs "aboutness" and structural
search cannot supply it.

Two endpoints: `GET /formal-systems/{id}/labels?q=` (lexical, immediately, over
the prose already stored) and the same with `?similar=` once embeddings land. The
lexical one is worth shipping first and alone — on a corpus that names things
`cbvald` the *title* is what a model can recognise.

**The notation direction.** §3's option B — notation as a second input grammar —
stays refused, for the reason §4 gives: a LaTeX-shaped input would shorten the
translation distance and would also make `+` ambiguous between a constant and a
variable in eleven measured cases, and the resulting term may still check. Take
the fluency at the translation boundary. What *is* worth having is the read
direction — rendering a system's terms in a LaTeX-ish notation so a model
recognises what it is looking at, which is already what `notation` does on the
term-graph route.

### 4.6 Scopes, which the corpus never exercised

A paper's proof is full of case splits, inductions and "assume for contradiction"
— all of which are **subproofs**. The structured write path cannot make one:
`/lines` refuses a scope opener as a template and composes every new line from an
existing logical line's shape (§9c), and §9e records plainly that a Metamath
corpus is flat, so nothing in the measured run touched scope openers, discharge
lines or indentation.

This is the gap most likely to bite first on a real paper, and the synthetic
fixtures already cover the ground the corpus does not — so the work is to extend
the structured path, not to discover the semantics:

- a line proposal that **opens a scope** (a hypothesis, a fresh variable),
- a line proposal that **discharges** one, and
- the renumbering guard extended over scope boundaries, with the same
  after-the-fact invariant that already governs insertion: *no line that was
  valid before may be invalid after*.

`dischargeable_openers` and the discharge half of the citation search already
exist on the read side, which is the half that is usually harder.

## 5. What stays out

**Elaboration (option D) is not on this critical path**, and saying so is the
point. It is the biggest single lever — the gap between a paper's step and a
formal one is mostly the closure and typing obligations no paper states — but it
is a search over *sequences* of steps, and everything above is needed whether or
not it exists. Depth-one retrieval plus a model willing to state intermediate
lines gets a long way, and it gets there without a search budget.

When it does arrive, it arrives behind the interface that is already there:
candidates in, unification confirms, and `formal_system/retrieval.py` grows a
depth parameter. Nothing above needs to change to accommodate it.

**A second parser** stays out, permanently. Nothing in this pipeline reads
surface syntax; the model emits productions, the API renders them, and the round
trip is checked by digest. That is the guarantee that makes machine authorship
safe at all (§9c), and it is the first thing a shortcut would spend.

## 6. Ergonomics of being called by a machine

The consumer is an agent that retries, runs concurrently, and abandons work
halfway. Three properties the current surface does not have and will need:

- **Idempotency.** `POST /proofs/{id}/lines` applied twice inserts twice. An
  `Idempotency-Key` header, stored per (user, key) with the response, makes a
  retry safe. Without it a network timeout is indistinguishable from a failure
  and the recovery is a diff.
- **Optimistic concurrency.** A proof edited between a caller's read and its
  write silently wins. `If-Match` on the proof's `updated_at`/version turns that
  into a 412 the caller can re-plan against.
- **Batching.** §9e measured 45–93 ms per call, dominated by *loading* the system
  (13 queries per build, latency not work) — and `_Built` already fixed the
  duplicate build within a request. A translation run makes thousands of calls
  against one system, so a batch endpoint that takes a list of proposals and
  builds once amortises the whole cost. The deliberate non-goal remains a
  cross-request system cache, for the reason §9e gives: its invalidation is
  exactly the cascade `schema_terms.py` was written to avoid.

## 7. Sequencing

| | why here |
|---|---|
| 1. **Assumptions + provenance closure + `GET /proofs/{id}/provenance`** (§4.1, §4.2) — *done* | the honesty machinery; everything after it produces artifacts that would otherwise misreport what they rest on |
| 2. **Goal-first statements** (§4.4) | the first call any translation makes, and the single path from vocabulary to stored term |
| 3. **Formalization record** (§4.3) | pure storage, no engine reach; makes fidelity reviewable rather than assumed |
| 4. **Lexical prose search** (§4.5) | cheap, and it is what alignment actually runs on |
| 5. **Scopes in the structured path** (§4.6) | the first thing a real paper needs that a Metamath corpus never asked for |
| 6. **Idempotency / batching** (§6) | when call volume proves it, not before |
| 7. **Embeddings, then elaboration** | the two large ones, both behind interfaces that already exist |

### Foreclosure check

The test the previous two roadmaps both applied. Does starting at (1) foreclose
anything? No — and the reverse is not true. Every artifact produced before the
provenance closure exists is an artifact whose dependence on unproved assumptions
has to be reconstructed later, from rows that were never asked to record it. The
insurance is the same one §6 of the authoring roadmap took out and costs as
little: **no new path may create a citable entry whose warrant is not recorded.**
