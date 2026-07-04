# Deprecated assets

This directory holds code from the old Django implementation of Edifyce that is
**not currently wired into the FastAPI backend** but is kept as a reference for
future work. Nothing here is imported or served by the running application.

## `frontend/` — legacy UI (reference for the planned Svelte app)

The original app was a server-rendered Django site. The backend has since been
replaced by a stateless FastAPI API (`app/`) over the proof engine in
`website/logical/`. The frontend has not yet been reimplemented; the plan is a
standalone static **Svelte** app that talks to the FastAPI endpoints.

These files are preserved so the visual design, page structure, and client-side
proof-editor behaviour can be ported rather than rebuilt from scratch.

### Contents

- `frontend/templates/` — Django HTML templates (Django template syntax:
  `{% ... %}` / `{{ ... }}`). `base.html` is the app shell; `website/` holds the
  per-page templates.
- `frontend/static/` — the matching client assets: per-page CSS/JS, images, and
  the vendored [Ace](https://ace.c9.io/) code editor under `static/website/ace/`
  (used for the formal-system and proof editors).

### Page inventory

Mapping of the main UI templates to what they rendered (route names are from the
old `website/urls.py`, preserved in git history at commit `cf7d0de`):

| Template | Purpose |
|---|---|
| `website/index.html` | Landing / dashboard |
| `website/formal_system*.html` | View / create / edit a formal system; pattern views |
| `website/proof*.html` | View / create / edit / delete a proof |
| `website/folder*.html` | Proof-folder browsing, creation, deletion |
| `website/profile.html`, `settings.html` | User profile and settings |
| `website/pattern*.html`, `editable_text.html` | Shared partials / widgets |

### What was intentionally **not** kept here

- **django-allauth templates** (`templates/account/`, `openid/`,
  `socialaccount/`) — third-party auth-library boilerplate, not app UI. The
  FastAPI backend is stateless and has no auth, so a Svelte rebuild would not
  reuse these. They remain in git history at commit `cf7d0de` if needed.
- **Django view / model / URL code** (`website/views.py`, `models.py`,
  `urls.py`, etc.) — removed with the rest of the Django backend. The old
  routing table in `urls.py` is the best reference for how pages mapped to data
  and is recoverable from git history at `cf7d0de`.

## Porting notes

- The old templates called Django server-rendered views and several `ajax/*`
  endpoints (compile, save, validate, autocomplete). The new backend exposes a
  smaller, stateless surface — `POST /formal-systems/compile` and
  `POST /proofs/verify` (see `app/main.py`). The Svelte app should target those
  rather than reproducing the old AJAX contract.
- Persistence (folders, saved proofs, user accounts) has no backend yet; those
  UI flows are reference-only until corresponding API + storage exist.
