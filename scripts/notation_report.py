#!/usr/bin/env python
"""What a `.mm` file's own notation would leave unsaid or say twice.

    uv run python scripts/notation_report.py set.mm --notation latex

The roadmap's §4.4 report, so re-syncing a notation against a grammar is driven
by a list rather than by discovering breakage. Reads the file and prints three
things, in the order they are worth acting on:

**verbatim** — compound productions the notation leaves spelled as the source
spells them. The list that matters, and the one a per-production override answers
(`setmm.DISPLAY_OVERRIDES`). A token map covering every token can still leave a
*production* in ASCII, because each of its tokens maps to itself: `set.mm`'s
``( F ` A )`` is exactly that, and TeX sets its backtick as an opening quote.

**unmapped** — tokens the map does not spell. Cosmetic: the token renders as
itself and the result is mixed but readable.

**collisions** — productions the notation spells alike. As a display that is a
presentation flaw; as a *source* it would be a correctness bug, since text would
no longer determine the term. Finding none is not proof of none — see
:class:`~website.logical.metamath.display.NotationReport`.

Touches no database: this is a question about a file and a grammar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# The script lives under `scripts/`, so the repo root is not on the path when it
# is run directly (`python scripts/notation_report.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from website.logical.declarative import build_system  # noqa: E402
from website.logical.metamath import build_spec, parse  # noqa: E402
from website.logical.metamath.display import (  # noqa: E402
    notation_report,
    projection_for,
    verbatim,
    with_overrides,
)
from website.logical.metamath.setmm import DISPLAY_OVERRIDES  # noqa: E402
from website.logical.metamath.typesetting import as_text, typesetting_of  # noqa: E402

if TYPE_CHECKING:
    from website.logical.kernel.constructors import Constructor

# Which `$t` directive each notation is derived from, and whether its values are
# markup. Both HTML directives are — `htmldef` is entities and `<SPAN>` wrappers
# just as `althtmldef` is, and reading either verbatim would report `A &isin; B`
# as the spelling — so both go through `as_text`. `latexdef` is already text.
_MAPS = {"unicode": ("unicode", True), "latex": ("latex", False), "html": ("html", True)}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the .mm file to read")
    parser.add_argument(
        "--notation",
        default="latex",
        choices=sorted(_MAPS),
        help="which of the file's $t maps to report on (default: latex)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="report the map as declared, before this repo's curated overrides",
    )
    parser.add_argument(
        "--limit", type=int, default=40, help="how many entries to list per section"
    )
    return parser.parse_args()


def _template(constructor: Constructor) -> str:
    """A production's source spelling, slots braced, for reading in a terminal."""
    return "".join(
        text if kind == "lit" else "{" + text + "}" for kind, text in constructor.pieces
    )


def main() -> int:
    arguments = _arguments()
    # `.mm` is UTF-8 (set.mm's comments and `$t` block are not ASCII); reading it
    # under the platform locale fails outright wherever that is not UTF-8.
    database = parse(arguments.source.read_text(encoding="utf-8"))
    typesetting = typesetting_of(database.comments)
    if typesetting is None:
        print(f"{arguments.source}: no $t block, so no notation to report on.")
        return 0

    attribute, is_markup = _MAPS[arguments.notation]
    declared = getattr(typesetting, attribute)
    if not declared:
        print(f"{arguments.source}: the $t block declares no {arguments.notation} map.")
        return 0
    tokens = (
        {token: as_text(value) for token, value in declared.items()}
        if is_markup
        else dict(declared)
    )

    system = build_system(build_spec(database, name=arguments.source.stem))
    projection = projection_for(
        system.build_context,
        tokens,
        name=arguments.notation,
        definitions=system.definitions,
    )
    overrides = {} if arguments.raw else DISPLAY_OVERRIDES.get(arguments.notation, {})
    projection = with_overrides(projection, overrides)
    # Against the projection actually being adopted, not the raw map: an override
    # replaces a template wholesale, so a collision one introduces is invisible to
    # a token-level check — and that is the only kind curating this table can
    # create.
    report = notation_report(
        system.build_context,
        tokens,
        system.context.definitions,
        templates=projection.templates,
    )

    print(f"{arguments.source} — {arguments.notation}")
    print(f"  tokens declared   {len(tokens)}")
    print(f"  productions spelt {len(projection.templates)}")
    if overrides:
        print(f"  overrides applied {len(overrides)} ({', '.join(sorted(overrides))})")

    left = verbatim(system.build_context, projection, system.definitions)
    print(f"\n  verbatim — {len(left)} compound productions left as the source spells them")
    for constructor in left[: arguments.limit]:
        print(f"    {constructor.name:14s} {_template(constructor)}")
    _elided(len(left), arguments.limit)

    print(f"\n  unmapped — {len(report.unmapped)} tokens the map does not spell")
    for token in sorted(report.unmapped)[: arguments.limit]:
        print(f"    {token}")
    _elided(len(report.unmapped), arguments.limit)

    print(f"\n  collisions — {len(report.collisions)} spellings shared by two productions")
    for collision in report.collisions[: arguments.limit]:
        shared = ", ".join(collision.productions)
        print(f"    {collision.sort}: {collision.spelling!r} — {shared}")
    _elided(len(report.collisions), arguments.limit)
    return 0


def _elided(total: int, limit: int) -> None:
    if total > limit:
        print(f"    … and {total - limit} more (raise --limit to see them)")


if __name__ == "__main__":
    raise SystemExit(main())
