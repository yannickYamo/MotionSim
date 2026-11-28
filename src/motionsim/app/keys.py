"""The datasheet reader's key, set from the page and kept in a file of its own.

The key is written to one file in MotionSim's folder, readable and writable by its owner
and nobody else. It is never put in the store, in a log, in an answer or in the words of a
refusal. A reader set up in the environment wins over it: `state` says which is in use.

Only the key's shape is checked. Whether a service takes it is found out when a datasheet
is read, which is the first time it leaves the machine.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from importlib.util import find_spec
from pathlib import Path

from motionsim.app.home import home, made
from motionsim.errors import Refusal
from motionsim.observe import provider

NAME = "reader.key"
LONGEST = 512  # characters; a key of any maker is a hundred or so
# The request that brings a key: the key and a few bytes of JSON around it.
MAX_REQUEST = 4096
# What reading a datasheet with the saved key needs installed: the `reader` extra.
READER_NEEDS = ("anthropic", "pdfplumber", "pypdfium2", "PIL")


def path() -> Path:
    return home() / NAME


def checked(key: object) -> str:
    """The key, if it has the shape of one. The refusal says what is wrong with the shape
    and never repeats what was sent."""
    if not isinstance(key, str) or not key:
        raise Refusal("no key was given", "paste the key into the box", "key")
    if len(key) > LONGEST:
        raise Refusal(
            f"that is longer than a key is: {len(key)} characters, and {LONGEST} is the most taken",
            "paste the key alone",
            "key",
        )
    # A key goes into a request header as it is: printable ASCII, and no space in it.
    if any(not "!" <= c <= "~" for c in key):
        raise Refusal(
            "a key has no spaces, line ends or other characters outside plain letters, digits and signs",
            "paste the key alone, with nothing before or after it",
            "key",
        )
    return key


# One save at a time puts its file in place: two at once would each be whole, and the one
# kept would still be the last one asked for.
_PUTTING = threading.Lock()
# Opened without following a link: one planted where the key is would have it read from, or
# written into, a file of whoever planted it.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def save(key: object) -> None:
    """Keep the key. It is written beside its place under a name of its own, made new for this
    save and closed to everyone else from the start, and then put in its place whole: a
    reader never finds half a key, and no two saves write into one file."""
    text = checked(key)
    folder = made(home())
    handle, beside = tempfile.mkstemp(prefix=f".{NAME}.", suffix=".new", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as out:
            out.write(text)
        with _PUTTING:
            os.replace(beside, folder / NAME)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(beside)


def saved() -> str:
    """The key kept, or nothing where none is: a file that is missing, cannot be read, is a
    link or does not hold a key is no key."""
    try:
        handle = os.open(path(), os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(handle, "rb") as kept:
            text = kept.read(LONGEST + 2).decode("ascii").strip()
    except (OSError, ValueError):
        return ""
    try:
        return checked(text)
    except Refusal:
        return ""


def forget() -> bool:
    """Take the key away. Whether there was one."""
    try:
        path().unlink()
    except FileNotFoundError:
        return False
    return True


def state() -> dict:
    """What the page shows of the reader: whether its libraries are installed, whether a
    key is set, and where the one in use comes from. Never the key."""
    environment, kept = provider.in_environment(), bool(saved())
    return {
        "reader": {
            "available": all(find_spec(name) is not None for name in READER_NEEDS),
            "key": "set" if environment or kept else "unset",
            "source": "environment" if environment else "saved" if kept else None,
            # A key may be kept while the environment's is the one used: it can still be forgotten.
            "saved": kept,
        }
    }


def use_saved() -> None:
    """Have the reader look the saved key up, each time it chooses what to read with."""
    provider.saved_key = saved
