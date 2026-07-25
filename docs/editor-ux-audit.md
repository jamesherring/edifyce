# Audit & plan: the formal-system editor and theorem editor

**Status:** audit + proposal (findings verified against the running app) ·
**Branch:** `claude/editor-ui-audit-q73fqe`

> A UI/UX audit of the two authoring surfaces — the **formal-system editor**
> (`/systems/[id]/edit`) and the **theorem/proof editor** (`/proofs/[id]/edit`,
> plus the ad-hoc verifier at `/systems/[id]/verify`). Findings were gathered by
> driving the real dev servers with Playwright: registering a user, authoring a
> ZFC-shaped system through the API, writing a proof, and interacting with every
> control. Each finding notes how it was observed so it can be reproduced.

## How this was checked

Backend on `:8000` (FastAPI + Postgres), frontend on `:5173` (Vite dev), logged
in as a real user, with a seeded ZFC system (2 sorts, 4 productions, a line
type, an axiom, HYP + MP rules, one definition) and a valid 3-line proof. Every
screen below was opened and exercised, at desktop (1280px) and mobile (390px)
widths, with the browser console and network captured.

The design language is already strong — serif display type, a warm restrained
palette, a subtle patterned background, consistent cards, working dark mode, and
a genuinely good verification-result component (per-line tone, rule badges,
"by …" citations). The issues below are about **information architecture,
editing loops, and one correctness bug** — not the visual system, which should
be preserved.

---

## 0. Correctness bug (must fix first): the `/proofs` prefix collision

**The proofs JSON API and the proofs SPA routes share the same `/proofs`
URL prefix.** The systems half deliberately avoids this — the UI lives at
`/systems` while the API lives at `/formal-systems` — but proofs use `/proofs`
for *both* the REST resource and the client-side pages. They collide.

Verified in **production mode** (single FastAPI process serving the built SPA),
issuing browser-style navigations (`Accept: text/html`):

| Navigating to | Result | Should be |
|---|---|---|
| `/systems` | SPA shell ✅ | app |
| `/systems/{id}` | SPA shell ✅ | app |
| `/proofs` | **raw JSON list** ❌ | app |
| `/proofs/new` | **422 `uuid_parsing`** ❌ (`new` parsed as a proof id) | app |
| `/proofs/{id}` | **raw JSON detail** ❌ | app |
| `/proofs/{id}/edit` | SPA shell ✅ (only because no API route matches `…/edit`) | app |

So in production, any **hard navigation** to a proof page — refresh, bookmark,
open-in-new-tab, direct link, shared URL — shows raw JSON or a validation error
instead of the app. Only in-app client-side navigation works, because that never
does a document GET to `/proofs*`.

The **dev server is worse**: `frontend/vite.config.ts` proxies only
`/health`, `/formal-systems`, `/auth`, `/users` — `/proofs` is absent — so under
the documented `npm run dev` workflow the app's `fetch('/proofs…')` calls hit
Vite, receive the SPA HTML, and the whole proofs feature dies with *"The backend
returned an unexpected non-JSON response."* (Observed on `/proofs/{id}/edit`,
`/proofs`, `/proofs/{id}`.) The proofs half of the app is effectively unusable in
dev. Naively adding `/proofs` to the proxy list then breaks the SPA routes the
other way (navigations render JSON) — proving the root cause is the shared
prefix, not the proxy list.

**Recommended fix — namespace the whole JSON API under `/api`.** Move every REST
router to `/api/...` (`/api/formal-systems`, `/api/proofs`, `/api/auth`,
`/api/users`, `/api/health`) and let the SPA own every bare path. This removes
this collision *and every future one*, and collapses the dev proxy and the
`serve_spa` API-path guard (`app/main.py`) to a single prefix. Touch points:
router prefixes, `app/main.py` SPA fallback + `_api_paths`, `frontend/src/lib/api.ts`
base, `vite.config.ts` proxy. Add a regression test in the spirit of the existing
SPA-guard tests: every SPA route returns the shell for `Accept: text/html`.

A smaller alternative (rename the proof UI routes to a non-colliding prefix,
mirroring `/systems` ↔ `/formal-systems`) works too, but only defers the pattern;
the `/api` split is the durable fix.

---

## 1. The theorem (proof) editor — `/proofs/[id]/edit`

The editor is one long vertical stack: **Details** (name, description, proof
`<textarea>`, *Save changes*) → **Lemmas** (*Save references*) → a *Verify saved
proof* button → **Verification** results → **Visibility** → **Danger zone**.

**1a. The write→verify loop is slow and split across the page.** You type the
proof at the top, then must **Save**, then scroll past the Lemmas card to *Verify
saved proof*, then read results further down, then scroll back up to fix a line.
Verification runs against the **saved** source, never the live editor text — the
button literally says *"Verify saved proof"* and a guard warns *"Unsaved edits —
save before verifying"* (`+page.svelte:244`). Every iteration is
edit → save → scroll → verify → scroll. (Observed directly.)

**1b. The ephemeral verifier is a *better* editor than the real one.** The
ad-hoc workbench at `/systems/[id]/verify` is a clean **two-pane, side-by-side**
layout — proof on the left, live per-line verification on the right, a *Verify
proof* button, and a collapsible *Show system source* reference. It verifies
arbitrary text against the stored system with no save step. The persistent proof
editor — the one people actually iterate in — has the *worse* single-column,
save-gated layout. The two surfaces should converge on the better one.

**1c. No line numbers in the editor; results are numbered.** The `<textarea>`
(`code-editor.svelte`) has no gutter, but the Verification pane numbers each line
(1, 2, 3…). On a long proof, mapping *"invalid on line 7"* back to the textarea
means counting rows by hand. Results also don't link back to — or mark — the
offending editor line.

**1d. No symbol input.** The domain is Unicode-dense (`∈ → ∀ ⊆ ⊢ ≝`) yet there is
no palette, insert button, or shortcut anywhere — you must produce the glyphs via
the OS. (Confirmed: no symbol-insertion helper exists in `frontend/src`.) This is
the single biggest friction point for actually *typing* proofs and rules.

**1e. Fragmented saving.** Three separate persistence actions on one page —
*Save changes* (details + source), *Save references* (lemmas), *Publish* — with
no single source of truth for "is my work saved."

**1f. The editor is a bare textarea.** No syntax highlighting, no bracket
matching, no autocomplete of rule labels / line-type shapes / notation the system
already defines. (Tab-inserts-spaces is handled well; that's the one nicety.)

---

## 2. The formal-system editor — `/systems/[id]/edit`

A long single-column stack of ~10 cards: Details, a live compile-status banner,
then Sorts, Brackets, Grammar, Line type, Axioms, Inference rules, Definitions,
Visibility, Danger zone. Parts are edited in a right-side slide-over (`EditSheet`).

**2a. Long scroll, no map, narrow column.** Everything is one column ~600px wide,
centered in a 1280px+ viewport — roughly half the screen is empty background on
each side. There's no section navigation, outline, or anchors, so a real system
with many productions and rules becomes a long unstructured scroll. (Observed —
the seeded, deliberately small system already fills ~2400px of height.)

**2b. The live compile status is good — but scrolls away.** The *"Compiles
cleanly · 2 line type(s), 2 inference rule(s)"* banner (and its error-list
counterpart) is a real strength. But it sits once near the top, so while editing a
rule at the bottom of the page you can't see whether your change compiled.

**2c. Editing hides the context you need.** Authoring a rule means writing a
conclusion/antecedents like `q` or `(p → q)` that reference the system's grammar —
but the `EditSheet` slides over and **covers** the grammar, notation, and other
rules. There's no reference panel or notation cheat-sheet while editing, and no
symbol palette (see 1d) in the formula fields either. (Observed in the *Add rule*
sheet: raw text fields with placeholder examples only.)

**2d. Reorder is fiddly and unguarded.** Ordering is one-step up/down chevrons,
applied instantly with no undo — during the audit a mis-aimed click silently
swapped the MP and HYP rules. No drag-and-drop; end-cap chevrons (first-row up,
last-row down) appear enabled but are no-ops.

**2e. Split save model.** *Details* needs an explicit *Save changes*, but every
part (sorts, rules, …) saves immediately from its sheet. Two persistence models on
one page invite "did that save?" confusion.

**2f. No source preview while authoring.** The compiled `.edi` source is only on
the read-only detail page; authors can't see the lowered source as they build.

---

## 3. Cross-cutting

- **Lists default to the empty tab for logged-in users.** `/systems` and
  `/proofs` open on the **Published** view (`paged-list.svelte.ts:43`,
  `view = 'public'`) regardless of auth, so a user who just created a draft lands
  on *"No published systems yet."* and has to discover the *My systems* /
  *My proofs* toggle to see their own work. Default authenticated users to *mine*.
- **Empty states are dead ends.** Plain text with no call to action (e.g.
  *"No published systems yet."* offers no *Create a system* button).
- **No unsaved-changes guard.** Navigating away from either editor mid-edit
  loses work with no warning; no autosave, no local draft, no undo beyond the
  native textarea.
- **Icon-only controls need labels.** Reorder chevrons and edit pencils are
  icon-only; ensure `aria-label`s and visible focus for a keyboard/AT pass.
- **Minor:** inconsistent button casing (*Save changes* vs *Save Changes* in the
  sheet); overall a light a11y + copy pass is warranted.

---

## 4. Improvement plan

Ordered by leverage. Phase 0 is a bug fix; the rest is the "best-in-class"
push and can land incrementally.

Phases 0–2 have since landed; 3–5 are still open. The audit above describes the
state *before* those changes, so read it as the reasoning behind them rather
than as a description of the app today.

### Phase 0 — Resolve the `/proofs` collision *(correctness; small, self-contained)* — **done**
Namespace the JSON API under `/api` (§0). Fix dev proxy + `serve_spa` at the same
time; add the SPA-shell regression test. Unblocks the proofs feature in dev and
fixes hard-navigation in production.

### Phase 1 — One unified proof workbench *(highest UX leverage)* — **done**
Merge the ad-hoc verifier (`/systems/[id]/verify`) and the persistent editor
(`/proofs/[id]/edit`) into a single **two-pane, live-verify** component:
- Left: the code editor with a **line-number gutter**; right: verification that
  re-runs on the **live** editor text (debounced), against the stateless verify
  endpoint. Keep dirty tracking, but stop gating *verification* on *save*.
- Map results ↔ editor lines: click a result to focus that line; render
  invalid/warning markers in the gutter.
- Demote **Details / Lemmas / Visibility / Danger zone** into a collapsible
  sidebar or a secondary tab so editor + results own the screen.

### Phase 2 — Symbol input *(unblocks authoring everywhere)* — **done**
A symbol palette / insert-at-caret toolbar driven by the system's own brackets +
production notation (the app already knows every symbol the system defines).
Reused in the proof editor **and** the rule/axiom/definition formula fields.
(Complements — doesn't overlap — the `symbols-model-design.md` data-model work;
that's storage, this is input.)

The `\in → ∈` shortcut expansion sketched here was deliberately **not** built: a
production's Regex mode is full of literal backslashes (`\d`, `\s`), so
expanding them on the way in would corrupt exactly the field that needs them
most. If it's wanted later it has to be opt-in per field, not global.

### Phase 3 — Formal-system editor layout — **done**
- Two-column on wide screens: a sticky **section outline** (Sorts, Grammar,
  Rules, …) with the **compile status pinned** in view; content on the right.
- Show a **notation reference** inside the part-editing sheet so authors see the
  grammar they're referencing (the symbol palette itself landed in Phase 2).
- **Drag-and-drop reordering** (with a keyboard fallback); disable end-cap
  chevrons.

The optional live `.edi` **source preview** pane was not built — it needs a
backend endpoint that renders a stored system back to source, which the API
doesn't expose. Worth its own change if wanted.

### Phase 4 — Lists, entry points, safety
- Default authenticated users to **mine**; keep Published for discovery.
- Richer empty states with a primary CTA.
- **Unsaved-changes guard** (`beforeNavigate`) on both editors; consider autosave
  of drafts.

### Phase 5 — Polish & a11y
- `aria-label`s on icon buttons, focus management for sheets, consistent button
  casing, and a consolidated/clearer save model.

### Suggested sequencing
Phase 0 (bug) → Phase 1 + 2 together (they define the new proof experience) →
Phase 3 → Phases 4–5 as ongoing polish.
