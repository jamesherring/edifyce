"""The little language Metamath's ``$t`` and ``$j`` comments are written in.

Both are "additional information" comments and both use the same syntax, which is
*not* Metamath's token stream and cannot be read with ``split()``:

- a directive ends at ``;``, not at whitespace;
- values are strings concatenated with ``+``, across line breaks;
- strings are double- *or* single-quoted, since a token containing ``"`` must be
  written ``'"'``;
- and a block may carry ``/* … */`` comments of its own, anywhere a space may go.

:mod:`~.typesetting` reads the ``$t`` block and :mod:`~.markup` the ``$j`` ones.
They want different things out of a directive — one a pair of strings, the other a
keyword with prepositional clauses — but they scan identically, so the scanning is
here and the shape each expects is theirs.

``where`` names the block in an error, since a reader with a malformed file wants
to know which of the two it was.
"""

from __future__ import annotations

from .parser import MetamathError


def skip_space(text: str, index: int, where: str) -> int:
    """Past whitespace and the block's own ``/* … */`` comments."""
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                raise MetamathError(f"{where}: unterminated /* comment.")
            index = end + 2
        else:
            return index
    return index


def read_value(text: str, index: int, where: str) -> tuple[str, int]:
    """One value: a run of quoted strings joined by ``+``.

    A quote is escaped by doubling it within a string of the same kind.
    """
    parts: list[str] = []
    while True:
        index = skip_space(text, index, where)
        if index >= len(text) or text[index] not in "\"'":
            raise MetamathError(f"{where}: expected a quoted string at offset {index}.")
        quote = text[index]
        index += 1
        chunk: list[str] = []
        while True:
            end = text.find(quote, index)
            if end == -1:
                raise MetamathError(f"{where}: unterminated string.")
            chunk.append(text[index:end])
            if text.startswith(quote * 2, end):
                chunk.append(quote)
                index = end + 2
                continue
            index = end + 1
            break
        parts.append("".join(chunk))

        after = skip_space(text, index, where)
        if after < len(text) and text[after] == "+":
            index = after + 1
            continue
        return "".join(parts), after


def read_word(text: str, index: int) -> tuple[str, int]:
    """One bare word — a directive's keyword, or a preposition inside it."""
    start = index
    while index < len(text) and (text[index].isalnum() or text[index] == "_"):
        index += 1
    return text[start:index], index
