"""Schema entrypoint for the Atlas SQLAlchemy provider (see `atlas.hcl`).

Atlas loads the desired database schema by importing every module under the
directory it is pointed at and collecting SQLAlchemy metadata. Pointing it at
this single-file directory (rather than `app/db/`) avoids the provider importing
the package's modules twice — once standalone and once via the package's
`__init__` re-exports — which would double-register every table.

Importing `Base` pulls in all models via `app.db.__init__`, so `Base.metadata`
carries the full schema.
"""

from app.db import Base  # noqa: F401  (import registers all tables on Base.metadata)
