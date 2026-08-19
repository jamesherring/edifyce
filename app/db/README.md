# Persistence layer

SQLAlchemy 2.0 (async / asyncpg) models plus the schema-as-code migration setup.
This layer lives *beside* the engine: `website/logical/` stays a pure function of
its input, and these models are how the application tier remembers systems,
proofs, and (in future) searchable theorems. The `users`, system-decomposition,
proof, term and proof-line tables are all wired into routes (`app/auth/`,
`app/routers/`); `theorems` is not yet — it is the schema and the tooling to
evolve it.

## Layout

| Path | What |
|---|---|
| `app/db/base.py` | Declarative `Base`, naming convention, id/timestamp mixins |
| `app/db/models.py` | Account + proof-surface ORM models |
| `app/db/systems.py` | Normalised formal-system decomposition (grammar/rules/definitions as flat rows) |
| `app/db/systems_mapping.py` | `spec_to_system` / `system_to_spec` round trip between the declarative `SystemSpec` and the rows, and `effective_spec`, which layers an inheritance chain into one |
| `app/db/descriptions.py` | What a system says about the labels it names: prose, titles, and authorship |
| `app/db/descriptions_mapping.py` | Store/load a label's description and its `(Contributed by …)` clauses |
| `app/db/outline_mapping.py` | A `.mm` file's section outline, stored as the folder tree it already is |
| `app/db/slugs.py` | `slugify` / `unique_slug` — here rather than in a router, since an import needs them too |
| `app/db/notations_mapping.py` | Store/load a system's named notations, and render a stored term through one from rows alone |
| `app/db/side_conditions.py` | Definition provisos as the kernel side-condition algebra, stored as rows |
| `app/db/side_conditions_mapping.py` | Parse/render a `where` proviso ↔ side-condition rows |
| `app/db/terms.py` | Term graph: kernel-term DAGs as shared `terms` / `term_children` rows |
| `app/db/terms_mapping.py` | `store_term` / `prefetch_terms` round trip between kernel `Term`s and the rows. A stored constructor resolves through the **sort unions**, not `context.variables`: that namespace is shared with lines, axioms and line parts, and a name declared twice resolves to the later one. A `Translation` renames each stored name before that lookup, which is how a theorem crosses a renaming edge |
| `app/db/promoted_theorems.py` | The citable library: proved and imported theorems as rows, resolved by label |
| `app/db/promoted_theorems_mapping.py` | `store_theorem` / `load_theorems`: the library round trip |
| `app/db/system_relations.py` | The general edge between two systems: where theorems transfer, the sort/symbol maps that rename them on the way, the statement template that restates them when the two disagree about what a judgement is, and one obligation per source primitive |
| `app/db/system_relations_mapping.py` | `related_layers`: which systems an edge adds to a citation's reach, and — for an edge that renames — whether its map reads the source's language into the target's (`website/logical/translation.py`). An edge that *wraps* carries its template declaratively instead: composing it is the citing system's job, since a term is only ever built against the system it will be checked in |
| `app/db/schema_terms.py` | `store_schema_terms` / `load_schema_terms`: a rule's schema templates as composed kernel terms, so a build need not re-parse them |
| `app/db/definition_terms.py` | `store_definition_terms` / `load_definition_terms`: the same for a definition's two surface forms |
| `app/db/proof_lines.py` | Proof structure: a checked proof's lines + the justification edges between them |
| `app/db/provenance.py` | Which layer a proof's dependencies actually reach, against the one it was filed in — the citation graph followed transitively, over rows alone |
| `app/db/proofs_mapping.py` | `store_proof_lines`: project a checked engine `Proof` into those rows |
| `app/db/metamath_store.py` | `import_corpus`: walk a Metamath `.mm` database and store the system, its proofs, and their line graphs |
| `app/db/session.py` | Lazy async engine + `get_session` FastAPI dependency |
| `alembic.ini` | Alembic config (no URL in it — see `migrations/env.py`) |
| `migrations/` | Alembic environment (`env.py`) + versioned revisions |

## The schema

Modernised from the original Django app (`website/models.py` on `main`):

- **`users`** — collapses Django's `auth.User` + `Profile`, built on
  fastapi-users' `SQLAlchemyBaseUserTableUUID` (contributes `email`,
  `hashed_password`, `is_active`, `is_superuser`, `is_verified`). Wired into the
  auth routes in `app/auth/` (register / login / logout / `users/me`).
- **`oauth_accounts`** — linked social logins (fastapi-users'
  `SQLAlchemyBaseOAuthAccountTableUUID`); one user, many providers. The library
  hardcodes the FK to a `user` table, so we repoint it at our `users` table.
  Populated by the GitHub/Google social-login routers in `app/auth/oauth.py`
  (enabled per provider when its client id/secret are set).
- **`formal_systems`** — a system's identity + surrounding concerns: `name`,
  `slug`, optional `owner`, self-referential `inherits_from_id` (system
  inheritance), and `published_at`. Its grammar/rules/definitions are **not** a
  blob here — they live in the decomposition tables below.

  **`inherits_from_id` is resolved.** A system's rows are its *own* parts; what
  it is *built from* is its ancestors' parts followed by them
  (`effective_spec` → `declarative.layered_spec`), so a child adding `∀x φ` to
  `formula` says `sort="formula"` and lands in the union its ancestor declared.
  A name may be declared once down a chain — a child redeclaring an ancestor's
  `→` would change what every theorem inherited from it means — and a parent
  must be **published** before a child may build on it, since publishing is what
  freezes the grammar the descendants' proofs are checked against. A layer also
  gets a symbol row for every sort it merely *mentions* (`⊆` is a `formula` over
  `term`, neither of which ZFC declares), so no row ever references another
  system's namespace. See
  [`docs/system-relationships-roadmap.md`](../../docs/system-relationships-roadmap.md).
- **`sorts`, `productions`, `production_bindings`, `production_binding_scopes`,
  `line_types`, `line_parts`,
  `definitions`, `definition_bindings`, `axioms`, `axiom_bindings`, `rules`,
  `rule_antecedents`, `rule_bindings`, `notation_brackets`** — the **normalised
  system decomposition** (`systems.py`): one row per declaration, with real FKs
  and explicit `position` ordering. This makes every part of a system a
  first-class, indexable, searchable entity — "which systems define `⊆`", "which
  rules take two premises" — answerable in plain SQL with no recompile. The
  bridge to the engine is `systems_mapping`: rows → `SystemSpec` →
  `FormalSystem` (`declarative.build_system`). `production_binding_scopes` is
  the odd one out in referencing `production_bindings` at both ends: it records
  which sibling slot a binder scopes over (the `phi` of `∀x.phi`), which is what
  lets a definition's `fresh` clause be inferred rather than declared.

  `rules` and `rule_antecedents` also carry **schema terms**
  (`schema_terms.py`): a rule's deduction, antecedents and subproof lines are
  templates, and the build parses each against the whole grammar to get the
  nested term the checker unifies with. That parse is roughly half of building a
  system and gives the same answer every time, so a verify stores what it
  composed (`rules.deduction_term_id` and friends → `terms`) and the next one
  reads it. Unlike `proof_lines`, these rows are a **cache and not a record**:
  `rules.schema_digest` fingerprints the grammar and the rule's own templates and
  bindings, and a row whose digest no longer matches is simply not read — so a
  part edit needs no invalidation sweep, and a stale row is inert rather than
  believed. The digest also covers which grammar names a line, part or axiom
  *shadows* in the build namespace, because a rename onto a production's name
  changes nothing a template composes to and so would otherwise leave the rows
  looking current. (It is not what makes such a system *correct* — a collision
  present from the outset matches the digest at both ends. `TermGraph` resolves a
  stored constructor through the sort unions rather than that namespace, which is
  what settles it either way.) The FKs into `terms` are `ON DELETE SET NULL`:
  losing a term must cost a re-compose, never a rule. And a NULL term id is a
  *miss* even under a matching digest — never "this template composes to
  nothing" — because the same NULL is what a deleted term, and a slot that
  resolved to a declared pattern instead of a composed one, both leave behind.

  `definitions` carries the same kind of cache for its two surface forms
  (`definition_terms.py`): `higher_term_id` / `lower_term_id` hold the terms the
  build parsed them into, under `definitions.term_digest`. Two differences from a
  rule's, both forced by what a definition is. The digest is **per system**, not
  per row — a definition's forms are parsed against the grammar as extended by the
  definitions before it, and the slot key is a spec position that an insertion
  moves — so every row of a system carries one value. And the stored term stops
  **before binder placement**: `bind_scoped` binds ground leaves sitting in binder
  slots, so storing the finished `Definition.lower` would rebuild with no binders
  at all and quietly drop the definition's capture-avoidance proviso.
  `definition_fresh.term_id` rides the same digest, holding the leaf a declared
  binder's name denotes — the fallback an unfold uses when it names no binder. A
  row exists only for a *declared* binder and a declared binder always has a
  default, so a NULL there **is** a hole and the currentness check says so; what
  is not a hole is a definition with no `fresh` rows at all, which is what a
  binder the grammar places leaves behind.
- **`promoted_theorems`, `promoted_theorem_premises`,
  `promoted_theorem_bindings`** — a system's **citable library**
  (`promoted_theorems.py`): results it has proved, or imported from a corpus, and
  registered for schematic reuse. Separate from `rules` because the two differ in
  *scale* and therefore in how they are read: a system's primitives are a handful
  and are built with it, while an imported library is 49,000 entries and is
  resolved **by label, on demand** — a verify reads the citations off a proof's
  own lines and promotes only those. Both kinds of an imported library live here
  (a Metamath logical `$a` as much as a `$p`); `primitive` records which, so
  "what does this system assume?" is one query while checking stays indifferent.
  Statement and premise terms are cached beside their text under `schema_digest`,
  on the same contract as the rule schema terms above. A premise's `label` is how
  the theorem's **own** proof cites it, and the only way to reach it — a bare
  hypothesis citable by anyone would prove anything — with `proofs.theorem_id`
  saying which proof that is. `proved_by_id` points the other way and means
  something else: which proof's *standing* warrants the entry, set by
  `POST /proofs/{id}/promote` and left NULL by an import, whose warrant is the
  corpus. That is what lets an edit retire a locally-proved entry without a
  grammar change taking a 49,000-theorem import down with it.
- **`notation_pieces`** — how a system's terms may be *read*, as against the
  grammar they are written in. One row per render step of one constructor in one
  named notation (`unicode`, `latex`), the same `("lit", …)` / `("slot", …)` shape
  `Constructor.pieces` holds — steps rather than a template string, because no
  delimiter is safe (set.mm makes braces notation). A stored notation names
  *every* constructor: a reader has rows and no grammar, so anything unnamed has
  no source template to fall back to. `render_stored` folds it over the term rows,
  which is why showing a proof in a notation costs a query and not a system
  rebuild. Derived where the source is — a Metamath import reads the file's `$t`
  block, one notation per map it declares, so `set.mm` arrives with both a
  `unicode` and a `latex` reading — never re-derived on the read path. A derived
  notation is *faithful*: it re-spells a production's tokens and leaves its shape
  alone. Where that reads badly a curated override replaces the whole template
  (`setmm.DISPLAY_OVERRIDES`, driven by `scripts/notation_report.py`). **Read** through the inheritance
  chain (a child inherits its ancestors' notations and overrides them per
  constructor, as its grammar layers on theirs); **stored** against the one system
  it was derived for.
- **`notation_rules`** / **`notation_rule_pins`** / **`notation_rule_pieces`** —
  the other half of a notation: a spelling matched by *shape* rather than by
  constructor name. `set.mm` applies things generically — ``( F ` A )`` is one
  production whatever `F` is — so the symbol a reader thinks of as the operator is
  an *operand*, and no per-constructor template turns ``( sqrt ` 2 )`` into
  `\sqrt{2}`. A rule is the root production, what must sit at given slot paths
  (`notation_rule_pins`, `F` → `csqrt`) and the template to use when it does
  (`notation_rule_pieces`). Tried before the template and winning outright, with
  the pinned operand consumed. Three tables rather than one with a discriminator,
  because a pin and a render step carry different columns. **Read** through the
  inheritance chain and replaced per rule *name* — several rules legitimately
  share a root, so replacing per constructor would be wrong. Curated
  (`setmm.DISPLAY_RULES`), never derived from a token map, which has no way to say
  any of this.
- **`label_descriptions`** / **`label_attributions`** — what a system records
  about the labels it names. Keyed by `(system, label)` rather than by an FK into
  the thing described, because one label lands in one of four row types depending
  on what the importer made of its statement — a production (a syntax `$a`), a
  definition (`df-un`), a primitive theorem (`ax-ext`), or a proof and its theorem
  (a `$p`). Four description columns would be four migrations for one concept.
  `title` is the prose's first sentence, which is a title in all but name:
  Metamath declares none. Attributions are rows, not a string, because an
  authorship record is asked aggregate questions — set.mm credits 131 people
  across 60,661 clauses — and every field is verbatim (the corpus misspells four
  kinds and malforms 22 dates, so `dated` is a string and `kind` is not an enum).
  Distinct from `proofs.title`/`proofs.description`, which are the proof's own
  and editable. An import copies the *title* across — short, and a listing wants
  it — and leaves `proofs.description` alone, because `description` rides on every
  `ProofSummary` and a corpus comment runs to paragraphs. The prose is read from
  here, on the single proof.
- **`side_conditions`** — a definition's proviso (`where` clause) stored as the
  kernel's closed side-condition algebra (`side_conditions.py`) rather than an
  opaque string: one row per algebra node (`occurs`/`equal`/`disjoint`/`atom`/
  `member` leaves referencing the definition's metavariables + an optional sort
  FK; `not`/`and`/`or` combinators), a tree via `parent_id`. So "which definitions
  have a disjoint-variable proviso" or "which constrain the `setvar` sort" are
  plain SQL. `side_conditions_mapping` parses the `where` surface syntax to rows
  and renders it back (the grammar mirrors the engine's `side_condition_syntax`,
  cross-checked by a test so the two can't drift).
- **`proof_folders`** / **`proofs`** — the folder/proof tree, scoped to a system.
  Ordering is a plain `position`; publishing is a `published_at` timestamp. A
  Metamath import fills the folders from the **section outline** its file draws
  with comments (`app/db/outline_mapping.py`): `####` part, `#*#*` section,
  `=-=-` subsection, `-.-.` subsubsection, 1,903 of them on set.mm, nested by a
  stack and each proof filed under the deepest section covering it. The tree
  needed no new table — a per-system tree with a parent, a name and an ordering
  is exactly what an outline is — only a `description`, for the prose 308 of
  set.mm's headers carry after their title. A folder's `ON DELETE CASCADE` takes
  its children; a proof's `folder_id` is `ON DELETE SET NULL`, so losing an
  outline never costs a proof. (The
  old app modelled both through a separate `FolderEntry`/`OrderedModel`; this
  flattens that indirection.)
- **`proof_references`** — the directed proof-to-proof dependency graph (an
  association object, `ProofReference`): each edge carries the citation `alias`
  the citing proof uses to name the lemma in its source (`[alias.line]`) and a
  display `position`. The graph is kept acyclic; the API rejects an edge that
  would close a cycle. This is the only place the dependency graph lives — the
  engine tracks no proof-to-proof edges of its own.
- **`proof_lines`** / **`proof_line_antecedents`** — the **proof decomposition**
  (`proof_lines.py`): what `proofs.source` says, as structure. One row per source
  line carrying what the checker determined about it (line type, behaviour,
  citation `number`, verdict, the scope it opens or sits in) and, for a
  formula-bearing line, a `term_id` into the `terms` graph below — so a proof's
  statements are the *same* interned kernel-term DAG the theorem search indexes,
  and "which proofs state a membership formula" is one query rather than a
  recompile. `proof_line_antecedents` is the justification graph: the lines a line
  was actually derived from, as edges rather than as a reference string to
  re-parse (a bare `[MP]` records the two lines the checker *inferred*). Finer
  than `proof_references`, which is the proof-to-proof edge; a citation reaching
  into a cited lemma is recorded by that proof's id and citation number, since the
  lemma owns its own line rows. Written by `proofs_mapping.store_proof_lines` when
  a proof is verified or published, and **dropped whenever `proofs.valid` is** —
  the snapshot is derived from a check, so it never outlives one. That includes
  editing the *system*: a part edit changes the grammar a proof was checked
  against, so it invalidates every proof in the system
  (`proofs_mapping.discard_system_checks`, called from every part route; a
  published system is frozen, so this only ever runs for a draft). Read back at
  `GET /api/proofs/{id}/structure` — and by **verify**, which reads both the
  proof's *own* lines and those of every lemma it cites from here rather than
  parsing anything (`proofs_mapping.load_proof_for_check` and
  `load_proof_lines`). A proof checked once never has its text parsed again;
  `proofs.source` is parsed only when there are no rows, which is exactly when
  there is nothing to trust. That is what makes these rows load-bearing rather
  than a render, and why the invalidation above is now soundness-critical rather
  than merely tidy. What the rows never supply is a *verdict*: numbering, scope
  and justification are re-derived on every check, so a row says what a line
  states and never whether it stands. See
  [`docs/verification-from-rows.md`](../../docs/verification-from-rows.md).
- **`terms`** / **`term_children`** — the **term graph** (`terms.py`): kernel
  term DAGs stored as shared rows, interned per system by a structural
  `digest` so equal subterms are stored once. This is the structural-search
  substrate for theorems (PR #23's follow-up replacing the old JSONB
  `pattern` blob): "top constructor is `implication`", "mentions `∈`
  anywhere" (a recursive CTE over `term_children`), "uses defined notation
  `x ⊆ y`" (the `defined` kind joins against `definitions.higher`) — all in
  plain SQL. The bridge to live kernel terms is `terms_mapping`
  (`store_term` / `prefetch_terms`). Each row also carries an **`alpha_digest`**
  (`terms_mapping.alpha_digest`): a second structural hash that numbers free
  variables by first occurrence, so it is invariant under consistent renaming
  while `digest` is not. It is the "same statement up to variable names" search
  key — `a in b` and `y in z` share an `alpha_digest` but not a `digest`, while
  `a in a` (a shared variable) keeps its own — non-unique (many exact rows per
  alpha class), indexed by `(formal_system_id, alpha_digest)`. It does not cover
  partial-pattern / goal-directed search (that is a matching problem for a
  discrimination-tree index plus a kernel unification confirm, not a whole-term
  hash).
- **`theorems`** — *forward-looking, currently unpopulated.* Points at the
  statement's root in the term graph (`statement_term_id`) for structural,
  **pattern-based** search, and carries a pgvector `embedding` (semantic /
  **AI** search via an HNSW index). Both live in the same store and join back
  to the proof that establishes them.

Deliberate departure from the Django schema (and from #13's first draft): a
formal system is stored as **normalised rows**, not an opaque `source` text +
`compiled` JSONB blob — so it is queryable without recompiling. The engine, which
still treats a system as source it recompiles, is fed by rebuilding the source
from the rows on demand (`systems_mapping`). Proofs keep their `source` — a proof
*is* the text its author wrote — and their `result`, a cached JSON snapshot of the
checker output for the editor to render; the structure behind that check lives in
`proof_lines` (above), where it is queryable.

The embedding dimension is `EMBEDDING_DIMENSIONS` in `models.py` (default 1536).
Match it to the embedding model you deploy (e.g. Voyage voyage-3 = 1024, OpenAI
text-embedding-3-small = 1536). Changing it is a migration.

## Migrations (Alembic)

The models are the source of truth. Alembic compares them against a database and
writes the revision that closes the gap.

```bash
# Plan a new migration after changing the models:
alembic revision --autogenerate -m "what changed"

# Apply migrations to a database:
alembic upgrade head

# Read-only: are the models fully applied to this database?
alembic check
```

All three need a database URL. `migrations/env.py` takes it from `-x url=...`,
then `MIGRATE_URL`, then `DATABASE_URL`, and normalises what it finds — an async
driver is rewritten to `postgresql+psycopg` (a migration runs on a plain
`Connection`), and a stray `search_path` parameter is dropped. So the app's own
`DATABASE_URL` works here unchanged. There is deliberately no URL in
`alembic.ini`: it would be the one place a production database could be committed
by accident.

`--autogenerate` needs a database at the current head to diff against, not an
empty one — `scripts/edifyce-dev db up && scripts/edifyce-dev migrate` gives you
one. Always read the generated revision before committing it; three things it
gets wrong here, all in `migrations/versions/*_initial_schema.py` as worked
examples:

- **Extensions are never emitted.** The models attach `vector` and `pg_trgm` as
  `before_create` DDL events, which fire for `metadata.create_all` and not for
  Alembic. A migration that needs a new extension hand-adds `op.execute("CREATE
  EXTENSION IF NOT EXISTS ...")`.
- **A `use_alter` foreign key is silently dropped by `op.create_table`.**
  `promoted_theorems.proved_by_id` and `proofs.theorem_id` point at each other, so
  one is declared `use_alter` to let the table sort resolve; that constraint then
  has to be added by an explicit `op.create_foreign_key` once both tables exist.
  `alembic check` catches it if you forget.
- **Column order drifts from the deployed database.** Postgres appends columns in
  the order migrations added them, so a database built from the baseline orders
  them differently from one built by the migrations that preceded it. It is
  `attnum` ordering only — nothing here selects with `*`.

`Vector(1536)`, the HNSW index and the `gin_trgm_ops` trigram indexes all render
correctly with no help (`env.py`'s `render_item` hook supplies the pgvector
import autogenerate omits), and `compare_type` / `compare_server_default` are
both on, so a widened column or a changed server default is caught rather than
ignored.

**Applying to Neon (verified against a real Vercel-provisioned DB).** Use the
direct (non-pooled) endpoint — the `DATABASE_URL_UNPOOLED` /
`POSTGRES_URL_NON_POOLING` var, *not* the `-pooler` host: a migration runs its
DDL in a transaction, which PgBouncer's transaction pooling breaks. Vercel's Neon
integration also provisions a `neon_auth` schema, which is simply out of view —
Alembic reflects only the default schema.

## CI/CD

Migrations are not applied by hand in normal operation — two workflows own it,
split by event so the apply never surfaces as a skipped check on PRs:

- **`.github/workflows/migrations.yml` — on a pull request** (touching the models,
  `migrations/`, `alembic.ini`, or `uv.lock`): against a throwaway
  `pgvector/pgvector` service container, it asserts the history has exactly one
  head, runs `alembic upgrade head` (which is what proves every revision actually
  executes), then `alembic check` as the **drift gate** — a model change without a
  matching revision fails there. It also round-trips `downgrade base` → `upgrade
  head`, and refuses an undeclared destructive operation
  (`scripts/check_destructive_migrations.py`). No Neon branch is touched, and no
  secret is needed.
- **`.github/workflows/apply-migrations.yml` — on push to `develop`** → `alembic
  upgrade head` against the Neon **develop** branch (Vercel Preview). **On push to
  `main`** → the Neon **main** branch (Vercel Production). The target URLs live in
  the `NEON_DEVELOP_MIGRATE_URL` / `NEON_MAIN_MIGRATE_URL` GitHub secrets, each
  the unpooled endpoint.

So the day-to-day loop is: change the models → `alembic revision --autogenerate`
→ read and commit the revision → open a PR. CI proves it's in sync and runnable;
merging applies it. A manual `alembic upgrade head` is only for local databases
and one-off recovery.

**Deploy ordering (know this before wiring the DB into routes).** GitHub Actions
applies the migration while Vercel independently builds the new code off the same
push — they race. That's harmless today because nothing at runtime touches the
DB and every migration so far is purely additive. Once routes depend on the
schema, keep migrations **backward-compatible with the currently-deployed code**
(expand/contract: add columns/tables before the code needs them; drop only after
the code that used them is gone) so either order is safe.

## Runtime

`session.py` is lazy: importing it never opens a connection, and the app boots
fine with no `DATABASE_URL`. Set `DATABASE_URL` to the Neon **pooled** connection
string (`-pooler` host) — the engine uses `NullPool` so Neon's PgBouncer owns
pooling, which is what keeps Vercel serverless functions from exhausting
connections.
