"""Vercel serverless entrypoint for the Edifyce FastAPI backend.

Vercel's Python runtime discovers the module-level ``app`` (an ASGI
application) and serves it. Requests are routed here by the ``rewrites`` in
``vercel.json``; a rewrite is invisible to the app, so FastAPI still sees the
original request path (e.g. ``/api/health``) and its routes — all namespaced
under ``/api`` — match with no changes.

The static SvelteKit bundle is served directly by Vercel from
``frontend/build`` — not by this function — so the SPA-serving branch in
``app.main`` stays dormant here (no ``frontend/build`` is bundled), and this
function only answers the JSON API.
"""

import sys
from pathlib import Path

# The `app` and `website` packages live at the repo root. Make that importable
# regardless of the function's working directory on Vercel.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
