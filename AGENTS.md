# AGENTS.md

Guidance for AI coding agents (and humans skimming for orientation) working in
this repository. For end-user setup and API usage, see [README.md](README.md).

## What Edifyce is

Edifyce is a **formal proof assistant**. Users define a *formal system* — its
grammar, notation, and inference rules — as structured, individually-editable
parts, then write *proofs* in that system and have them mechanically verified,
line by line.

The project began as a server-rendered Django site and has been rebuilt as:

- a stateless **FastAPI** backend (`app/`) that wraps the existing proof engine, and
- a standalone **SvelteKit** single-page frontend (`frontend/`) that talks to it.

The proof engine itself (`website/logical/`) predates the migration and is the
heart of the project. Treat it as the source of truth; the API layer is a thin
adapter over it, and the frontend is a thin client over the API.

## Layout

| Path | What lives here |
|---|---|
| `app/` | FastAPI application. `main.py` = routes (and static-SPA serving); `schemas.py` = Pydantic request/response models. Thin — it delegates to the engine. |
| `app/auth/` | Authentication (fastapi-users): httponly-cookie + JWT backend, user manager, register/login/logout/`users` routers, and GitHub/Google social login (`oauth.py`, enabled per provider by env). Mounted in `main.py`; needs `DATABASE_URL`. |
| `app/db/` | Persistence layer: SQLAlchemy 2.0 (async) models + session wiring. Beside the engine, not inside it. A system is normalised rows (`systems.py`), and a verified proof's lines are rows too — each formula interned into the shared term graph (`proof_lines.py` + `terms.py`). Only `theorems` is unused by routes. See `app/db/README.md`. |
| `migrations/` | Atlas versioned SQL migrations (`atlas.sum`). Config in `atlas.hcl`; models loaded via `tools/atlas/schema.py`. |
| `website/logical/` | The proof engine. This is where the real logic is. |
| `website/logical/declarative.py` | The `SystemSpec` dataclasses (grammar productions, lines, definitions, axioms, rules) and `build_spec`/`build_system`, which construct a `FormalSystem` straight from one. **This is how systems are built in production.** |
| `website/logical/kernel/` | The trusted checking core: `constructors` (a production projected to kernel data), `terms` (interned, shared-DAG formula trees), `unify` (first-order matching), `side_conditions` (the closed proviso vocabulary), `definitions` (a definitional unfold as a cited step, and the capture half of a definition's admissibility). Hard-codes no logic. |
| `website/logical/formal_system/` | `FormalSystem`, `Proof`, `ProofLine`, line types, inference rules — the built system and proof-checking. |
| `website/logical/matching/` | Pattern-matching engine (patterns, contexts, matches). Now **only** the parser: it turns proof-line text into a `Match`, which `kernel.from_match` projects into a term for checking. A `Definition` here makes defined notation grammatical; *applying* one is the kernel's job. Also `rewriting`, the associative matcher for string-rewriting (semi-Thue) rules. |
| `website/logical/build_context.py` | The build context (`FormalSystemContext`) and the constructions needing it — `build_schema_pattern`, `combine_side_conditions`. Driven from `SystemSpec` fields by `declarative`; the sole way a system is assembled. |
| `website/logical/promotion.py` | `promote_from_source`: builds a citable `PromotedTheorem` from a proved or imported theorem's statement, written in *the system's own* grammar (a Metamath `$p` maps here directly). |
| `website/logical/graphs.py` | Leaf graph utilities: bipartite matching for antecedent-slot assignment, topological order for proof dependencies. |
| `frontend/` | SvelteKit (Svelte 5) SPA styled with Tailwind CSS v4 + shadcn-svelte. Static build talks to the API. `src/routes/` = pages, `src/lib/api.ts` = the API client. See `frontend/README.md`. |
| `tests/` | pytest suite covering the API, engine, kernel, and matching. |
| `benchmarks/` | What a parse costs. Proof checking *is* parsing, so the matching layer is where a slow system is slow; take a baseline with `uv run python -m benchmarks.bench_matching --save base.json` before touching it and `--compare base.json` after. See `benchmarks/README.md`. |

The two public entry points into the engine are `declarative.build_spec(spec)` —
which the API reaches via `app.db.system_to_spec`, so the relational rows are the
source of truth, not any source blob — and `FormalSystem.parse(text)` for a
proof. Start there when tracing behaviour.

### Constants vs variables of the object language

A production declares `denotes_constant`: whether its tokens name one fixed thing
(`⊥`, `∅`) or stand for variables a binder can bind. This is Metamath's `$c` vs
`$v`, and like Metamath's it is **declared, not inferred** — nothing about a
production's shape settles it, since a one-token atom is a constant in
`formula ::= ⊥` and a variable in `setvar ::= a | b | c`. The engine once guessed
from the constructor's shape and had holes.

It gates exactly one thing: whether a definition's defining form may mention a
leaf the defined form does not supply (`formal_system/definitions.py`). It reaches
nothing else — not unification, equality, side-conditions, or rule checking. The
default is `False`, variable-like, so a forgotten declaration costs a refused
definition rather than a capturing one; the unsafe direction takes a positive act.

Two declarations the engine refuses outright. An **indexed atom family** (`p_#`)
is a supply of interchangeable tokens — `AtomPattern.fresh` mints new ones — so no
grammar makes it a constant and no author could mean it. And a production in a
sort some **binder ranges over** is bindable, so it names a variable of the object
language whatever the author ticked (`declarative._validate_constant_declarations`);
that needs binding slots to see, so it is silent for a grammar that declares none.
What is still trusted is a sort no binder mentions — a genuine judgement about the
grammar, now the only one left.

Two follow-ups this leaves open:

- **Binding slots on productions.** A production may now declare which of its slots
  *binds* and over what — `Production.scopes_over`, `{"x": ["phi"]}` for `∀x.phi`.
  It is optional and empty by default, so a grammar that declares nothing behaves
  exactly as it did before it existed. Two things read it: a definition's `fresh`
  clause is **inferred** from the parsed defining form rather than written by
  hand (`formal_system/definitions.py`), which is what a Metamath `$a`/`$p` carries
  no trace of; and a `denotes_constant` declaration the grammar contradicts is
  refused, as above. They also drive **scope-aware binding**: a defining form's
  binders are placed per *occurrence* rather than per name, so an occurrence
  outside a binder's scope stays free and two binders sharing a spelling stay two
  ([docs/scope-aware-binding.md](docs/scope-aware-binding.md), which carries the
  soundness argument). One use remains — scope-aware definitional *steps*, which
  is what admitting an open abbreviation like `S ≝ (a ∈ b)` would need, and the
  only one that widens what a *proof* may do. Analysed and **blocked**: deciding
  capture at the redex turns out to be the easy half, and the hard half is that a
  defined form is a leaf, so `Occurs` answers differently either side of a
  definitional equality — which wants separate semantic-leaf metadata rather than
  anything to do with `free_vars`
  ([docs/scope-aware-definitional-steps.md](docs/scope-aware-definitional-steps.md)).
- **Conservativity.** A definition must add notation, not assumptions, and both
  halves are now settled. **Non-circularity** holds by construction: a defining
  form is matched against the grammar as extended by the definitions *before* it,
  so a definition stated in terms of itself matches nothing and is dropped, and
  the "defined using" relation is a DAG by index — there is no check because none
  is reachable. **Freshness** is checked
  (`declarative._require_a_fresh_defined_form`): a definition may not give meaning
  to a symbol an axiom or rule is already stated over, since equating such a
  symbol to something else is an axiom rather than a definition. Declaring the
  defined form as a *production* is deliberately not disqualifying — that is how
  `⊆` becomes grammatical before `df-subset` gives it meaning; what is refused is
  defining a symbol the theory already reasons about. Pinned in
  `tests/test_conservativity.py`.

The bespoke `.edi` source language and its compiler are **gone**. A system is a
`SystemSpec` and nothing else; there is no text form to round-trip through, and
`LineType` behaviours the compiler alone could author (`indent`, a logical line
with no formula field) are refused at construction.

## Working in this repo

The **backend** requires **Python 3.13+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                      # install deps (incl. dev group)
uv run pytest                                # run the test suite
uv run uvicorn app.main:app --reload         # run the dev server (docs at /docs)
```

The **frontend** requires **Node 20+** and lives in `frontend/`.

```bash
cd frontend
npm install
npm run dev            # dev server on :5173, proxies API paths to the backend on :8000
npm run build          # static bundle written to frontend/build
npm run check          # svelte-check type checking
```

Run both dev servers together: the Vite dev server proxies the API paths
(`/health`, `/formal-systems`, `/proofs`) to `uvicorn` on :8000, so no CORS or
extra config is needed. Alternatively, after `npm run build` the FastAPI app
serves the static bundle from `/`, so a single `uvicorn` process serves both the
API and the UI (see the static-frontend block at the bottom of `app/main.py`).

### Database migrations

The database schema is **model-driven**: the SQLAlchemy models in `app/db/` are
the source of truth, and Atlas diffs them against `migrations/` to plan new SQL.
After changing a model, generate and commit the migration — don't hand-write it:

```bash
atlas migrate diff <name> --env local    # plan a migration from the models
atlas migrate validate --env local       # read-only: verify atlas.sum integrity
```

`atlas migrate diff` writes a new `migrations/*.sql` **only when the models have
drifted** from the recorded migrations; on a clean tree it prints "synced" and
writes nothing. It is *not* a read-only probe — don't run it with a throwaway
name to "check" for drift, because a real drift leaves a stray migration (and a
bumped `atlas.sum`) behind. That file-writing behavior is exactly how CI detects
drift: it runs `atlas migrate diff drift_check` and fails if `migrations/` is
then dirty (`.github/workflows/migrations.yml`). For a genuinely read-only check
use `atlas migrate validate`. When you do generate a migration, commit **both**
the new `migrations/*.sql` file and the updated `migrations/atlas.sum`.

Atlas needs a throwaway **dev database** (with pgvector) to diff against; how you
supply it depends on where you're working — see `atlas.hcl` for the `ATLAS_DEV_URL`
override (its default spins up `docker://pgvector/pg16/dev`). Two gotchas
wherever you run it:

- **`psql` rejects a `search_path` query param** in `ATLAS_DEV_URL` — it's
  Atlas-specific. Strip it (`sed -E 's/[?&]search_path=[^&]*//'`) for raw `psql`;
  Atlas itself consumes the full URL fine.
- **Never hand-merge `atlas.sum`.** It's a hash chain Atlas maintains; a manual
  edit produces a checksum Atlas rejects. If a migration conflicts with `develop`
  (usually only `atlas.sum` collides, since migration files have distinct
  timestamps), roll back your migration commit, merge `develop`, then re-run
  `atlas migrate diff` to regenerate the file and sum on the new base.

- **Run the tests before and after any change to the engine.** The engine is
  large, largely untyped in its internals, and interconnected — tests are the
  safety net. CI runs `uv run pytest -v` on every PR.
- **Keep the API layer thin.** New behaviour belongs in `website/logical/`;
  `app/` should stay a translation layer between HTTP/Pydantic and the engine.
- **Keep the frontend a thin client.** It renders and calls the API; proof and
  compile logic stays in the engine, not the browser. The API contract lives in
  `app/schemas.py` (backend) and `frontend/src/lib/api.ts` (client) — change both
  together.
- **Preserve public engine signatures** unless you intend to update every caller
  and test. `matching/__init__.py` deliberately re-exports the old flat API after
  a package split — respect that contract.
- **Prefer dataclasses and explicit `raise`s** over dict-records and bare
  `assert`s. Recent history has been steadily moving the codebase that way; match
  the direction it's already going.
- **Type new code fully.** The engine's older internals are largely untyped, but
  all new code — and any function you meaningfully rewrite — must carry parameter
  and return-type annotations (including `-> None`). Use `from __future__ import
  annotations` and a `TYPE_CHECKING` block for engine types to keep annotations
  runtime-free and avoid import cycles. See `website/logical/kernel/terms.py` for
  the pattern to follow.
- **Lean on types; fail loudly.** When an object's type is known, access its
  attributes directly (`obj.attr`) rather than `getattr(obj, "attr", default)`.
  A defaulting `getattr` hides both the type and a genuine bug — a missing
  attribute should raise, not silently fall back. If some instances of a type may
  or may not carry a field, that field belongs in the class as a declared
  attribute with a default (so every instance has it and callers stay typed), not
  as something attached ad hoc and probed with `getattr`. Reserve `getattr`/
  `setattr` for genuinely dynamic keys not known until runtime — a lookup keyed
  by user-authored strings, say — never for a field your own code declares.
- **Import at module top.** Put imports at the top of the module, not inside
  functions. A function-local import is only justified to break a real import
  cycle or to defer a heavy/optional dependency — and when you use one, say why in
  a comment. The kernel depends on `matching`, and `formal_system`/`compiler`
  depend on the kernel, so those directions import freely at the top; `matching`
  must never import the kernel or `formal_system`.
- **Keep the kernel's dependency on `matching` inside `kernel/constructors.py`.**
  It is the only module there that reads a `Pattern`, and nothing it returns
  contains one: a production is projected once to a `Constructor`, and a term,
  its constructor, that constructor's slot sorts and a sort union's branches are
  all kernel data. That is what lets `terms`, `unify`, `side_conditions` and
  `definitions` be written against the kernel alone — so resolve a production at
  the projection rather than importing `matching` into another kernel module.
  The kernel also reads no *strings*: turning surface syntax into terms is
  `formal_system`'s job (`parse_definition`), so nothing in the trusted core
  re-parses at check time.

## On comments

Keep comments **brief and forward-looking**. Explain **why**, not **how** — the
code already says how. Good comments capture the reasoning, constraint, or
gotcha that the code can't: why a path is disabled, why an exception is caught
and reshaped, why an edge case is handled the way it is. See `app/main.py`'s note
on the proof-checker raising for the tone to aim for. If a comment merely
restates the line below it, delete it.

## For Claude Code on the web

**Do not set up scheduled check-ins, cron triggers, or self-scheduled wake-ups**
in Claude Code web sessions for this repo. Web sessions run in ephemeral
containers and recurring triggers are not wanted here — do the work in the
session and finish. If a task seems to call for polling or a delayed follow-up,
surface it to the user instead of scheduling it.

**The Atlas dev database is pre-provisioned in web sessions only.** The session
setup script installs Atlas, logs it in via `ATLAS_TOKEN`, and starts a Postgres
+ pgvector cluster on `127.0.0.1:5433` that `ATLAS_DEV_URL` already points at — so
`atlas migrate diff --env local` works out of the box (this is not present in
local checkouts, which supply their own dev DB per `atlas.hcl`). The setup runs
**once at container init**, so after a worker/container restart the server is gone
while its data dir at `/var/lib/postgresql/pgdev` persists. If `atlas` reports
`connect: connection refused` on `:5433`, restart it:

```bash
runuser -u postgres -- /usr/lib/postgresql/16/bin/pg_ctl \
  -D /var/lib/postgresql/pgdev -o "-p 5433 -k /tmp" \
  -l /var/lib/postgresql/pgdev/server.log -w start
```

(`pg_ctl -D /var/lib/postgresql/pgdev status` tells you if it's already up.)
