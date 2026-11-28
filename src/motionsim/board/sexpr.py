"""KiCad's files are brackets inside brackets: (name value (name value ...) ...). This reads
them into lists of text, and nothing else: no number is turned, no name is known here.

It is written to be handed anything: a bracket never closed, a string never ended, brackets
a million deep. Each is refused in a line. Nothing here calls itself, so depth costs no stack.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from motionsim.board.model import MOST_BYTES, MOST_DEPTH, MOST_VALUES
from motionsim.errors import Refusal
from motionsim.text import whole

Node = list  # of str and Node

# A stretch of the file taken apart in one call: a bracket, a quoted text whole, a bare word,
# or, where a quoted text does not end inside the stretch, all from its opening quote on, each
# with the white space before it taken in the same match and not kept (a run of it is passed
# in one step, and leaves nothing behind but at a stretch's end). Nothing in these patterns can be
# matched two ways: a quoted text is runs of plain characters and escaped ones, each run taken
# whole and never given back (the ++ and *+), so a text of any length is walked once and
# nothing is remembered of the way through it.
_QUOTED = r'"(?:[^"\\]++|\\.)*+"'
_TOKENS = re.compile(rf'\s*+(?:([()]|{_QUOTED}|[^\s()"]++|"[\s\S]*+))?', re.DOTALL)
_WHOLE = re.compile(_QUOTED, re.DOTALL)
_WORD = re.compile(r'[^\s()"]++')
STRETCH = 1 << 18  # characters taken apart at a time


def _refuse(name: str, why: str) -> Refusal:
    return Refusal(
        f"the board file {name} is not a KiCad board that can be read: {why}",
        "save the board again from KiCad's PCB editor and give that file",
        "board",
    )


def _stretches(text: str, name: str) -> Iterator[list[str]]:
    """The file's brackets, quoted texts (in their quotes) and bare words, in order, a stretch
    at a time. A word or a quoted text that a stretch's end cuts through is taken whole with
    one match from where it starts: read again a doubled stretch at a time, a word of 29 MB
    was walked some sixty times over."""
    at, size = 0, len(text)
    while at < size:
        end = min(at + STRETCH, size)
        tokens = [*filter(None, _TOKENS.findall(text, at, end))]
        last = tokens[-1] if tokens else ""
        if last[:1] == '"' and not _WHOLE.fullmatch(last):
            # A quoted text that does not end in this stretch: read to its end, wherever that is.
            whole = _WHOLE.match(text, end - len(last))
            if whole is None:
                raise _refuse(name, "a quoted text is never closed")
            tokens[-1], end = whole.group(), whole.end()
        elif end < size and last and last[0] not in '()"' and not text[end - 1].isspace():
            # A bare word the stretch's end may cut: it goes on to the next space or bracket.
            word = _WORD.match(text, end - len(last))
            if word:  # always: it starts at the word's own first character
                tokens[-1], end = word.group(), word.end()
        yield tokens
        at = end


def _within(text: str, name: str) -> Iterator[list[str]]:
    left = MOST_VALUES
    for tokens in _stretches(text, name):
        left -= len(tokens)
        if left < 0:
            raise Refusal(
                f"the board file {name} holds more than {whole(MOST_VALUES)} brackets and values, more than a board "
                f"file of {MOST_BYTES // (1024 * 1024)} MB does",
                "give the board of the power stage alone",
                "board",
            )
        yield tokens


def _counted(text: str, name: str) -> Iterator[list[str]]:
    """The stretches, with a file of more brackets and values than any board file holds
    refused as soon as a stretch takes it past them. A file that may hold that many is first
    counted for the price of the walk alone, so that one that does is refused before millions
    of its values are kept; any other is counted in the same walk, and read once."""
    if _most_values(text) > MOST_VALUES:
        for _ in _within(text, name):
            pass
    yield from _within(text, name)


def _most_values(text: str) -> int:
    """The most brackets and values a text can hold, counted without taking it apart: words
    and quoted texts are kept apart by spaces, brackets and quotes, so there are no more of
    them than of those, and a bracket is one itself; nor more than the characters that are
    not spaces."""
    brackets, spaces = text.count("(") + text.count(")"), sum(map(text.count, " \t\n\r"))
    # And each is at least a character that is not a space.
    return min(2 * brackets + text.count('"') + spaces + 1, len(text) - spaces)


def _unquoted(token: str) -> str:
    return token[1:-1].replace('\\"', '"') if "\\" in token else token[1:-1]


def parse(text: str, name: str = "board.kicad_pcb") -> Node:
    """The one bracket a file holds, as a list: its name first, then its values and the
    brackets inside it."""
    stack: list[Node] = []
    done: Node | None = None
    # The innermost open bracket's own append, kept at hand: a file of millions of values
    # spends most of its read here, and a lookup saved on each is a second saved on a file.
    take: Callable[[object], None] | None = None
    for tokens in _counted(text, name):
        for token in tokens:
            if token == "(":
                if done is not None:
                    raise _refuse(name, "it holds more after its last bracket")
                if len(stack) >= MOST_DEPTH:
                    raise _refuse(name, f"its brackets are more than {MOST_DEPTH} deep")
                opened: Node = []
                stack.append(opened)
                take = opened.append
            elif token == ")":
                if not stack:
                    raise _refuse(name, "a bracket closes that was never opened")
                node = stack.pop()
                if stack:
                    stack[-1].append(node)
                    take = stack[-1].append
                else:
                    done, take = node, None
            elif take is None:
                raise _refuse(name, "it does not start with a bracket")
            else:
                take(_unquoted(token) if token[0] == '"' else token)
    if stack or done is None:
        raise _refuse(name, "a bracket is never closed: the file is cut short")
    return done


def head(node) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def children(node: Node, name: str) -> list[Node]:
    return [child for child in node if isinstance(child, list) and head(child) == name]


def child(node: Node, name: str) -> Node | None:
    return next((c for c in node if isinstance(c, list) and head(c) == name), None)


def words(node: Node | None) -> list[str]:
    """A bracket's own values, without its name and without the brackets inside it."""
    return [v for v in node[1:] if isinstance(v, str)] if node else []


def numbers(node: Node | None, name: str, what: str) -> list[float]:
    """A bracket's values as numbers; one that is not is refused with what it was for."""
    out = []
    for word in words(node):
        try:
            out.append(float(word))
        except ValueError:
            raise _refuse(name, f"{what} holds {word[:40]!r} where a number belongs") from None
        if out[-1] != out[-1] or abs(out[-1]) > 1e6:
            raise _refuse(name, f"{what} holds {word[:40]!r}, which is no length on a board")
    return out
