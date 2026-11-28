"""The page served by an ASGI app, with what a program that stays running can keep.

`motionsim serve` runs this where FastAPI and uvicorn are installed (the `app` extra), and
the standard library's server otherwise. Both answer every address of the service through
the same one dispatch, so a figure is the same whichever serves it. What is added here is
what the page cannot keep by itself: a small local store for runs and schemes, and the key
of the datasheet reader, set from the page and kept in a file only its owner can read.

Importing this package loads neither FastAPI nor uvicorn: `available` says whether they are
there, and `motionsim.app.server` is the module that needs them.
"""

from __future__ import annotations

from importlib.util import find_spec

__all__ = ["NEEDS", "available"]

# The libraries of the `app` extra, by the names they are imported under.
NEEDS = ("fastapi", "uvicorn", "wsproto")


def available() -> bool:
    """Whether the ASGI app can run here: its libraries are installed."""
    return all(find_spec(name) is not None for name in NEEDS)
