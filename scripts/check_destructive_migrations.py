"""Refuse a migration that destroys data without saying so.

What this replaces is `atlas migrate lint`, which flagged destructive changes
across every migration a pull request added. Alembic has no equivalent — the
ecosystem's linters read SQL files, and an Alembic revision is Python — so this
reads the revisions directly.

Deliberately narrow. It reports `drop_table` and `drop_column` in a revision's
``upgrade()``, which are the two operations that lose rows outright and cannot be
undone by re-running anything. It says nothing about `alter_column`, which is
destructive only for some type changes and would cost more false positives than
it is worth.

A drop is not forbidden — retiring a table is a real thing to do. It has to be
*declared*: put ``allow-destructive`` in the revision's docstring, which is where
the reason belongs anyway, and this passes it.

    uv run python scripts/check_destructive_migrations.py --base origin/develop
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

VERSIONS = Path("migrations/versions")
DESTRUCTIVE = frozenset({"drop_table", "drop_column"})
ACKNOWLEDGEMENT = "allow-destructive"


def changed_revisions(base: str) -> list[Path]:
    """Revision files this branch adds or edits, relative to `base`."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base}...HEAD", "--", str(VERSIONS)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line) for line in diff.stdout.split() if line.endswith(".py")]


def destructive_operations(source: str) -> list[str]:
    """The destructive `op.*` calls in this revision's ``upgrade()``.

    Only `upgrade()`: a `downgrade()` undoing a `create_table` is a drop by
    construction, and flagging those would flag every migration ever written.
    """
    tree = ast.parse(source)
    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ),
        None,
    )
    if upgrade is None:
        return []

    found = []
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr in DESTRUCTIVE
            and isinstance(function.value, ast.Name)
            and function.value.id == "op"
        ):
            targets = ", ".join(
                repr(argument.value) if isinstance(argument, ast.Constant) else "?"
                for argument in node.args
            )
            found.append(f"op.{function.attr}({targets})")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="git ref to compare against")
    arguments = parser.parse_args()

    failed = False
    for path in changed_revisions(arguments.base):
        source = path.read_text()
        operations = destructive_operations(source)
        if not operations:
            continue
        if ACKNOWLEDGEMENT in source:
            print(f"{path}: destructive, acknowledged — {', '.join(operations)}")
            continue
        print(
            f"{path}: destructive operations in upgrade() — {', '.join(operations)}.\n"
            f"  These drop data irrecoverably. If that is intended, say so in the\n"
            f"  revision's docstring with the word {ACKNOWLEDGEMENT!r} and why.",
            file=sys.stderr,
        )
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
