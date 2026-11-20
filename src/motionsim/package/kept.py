"""Package figures kept on disk between runs.

Working out what a generic package does means solving the plate equation on a grid: a
good part of a second the first time, for figures that are the same every time for the
same package, rating and variant. They are kept in a file in the user's cache folder, so
that a second run of the same command reads them back instead.

The file is figures only, written as JSON and read as JSON: nothing in it is run. Its name
carries a fingerprint of the code that works the figures out and of the version, so that
a change to either starts a new file, and an entry is used only if it has the shape the
figure has. A file that cannot be read, or a folder that cannot be written, is passed by:
the figures are then worked out as they would be without it. MOTIONSIM_CACHE names
another folder, or `off` to keep nothing.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

# What the figures are worked out by: a change to any of these is a change to the figures.
_SOURCES = ("templates.py", "plate.py", "column.py", "materials.py", "../fit/foster.py")
_HERE = Path(__file__).parent


def folder() -> Path | None:
    """Where the figures are kept, or None to keep none."""
    given = os.environ.get("MOTIONSIM_CACHE", "")
    if given.lower() == "off":
        return None
    if given:
        return Path(given)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "motionsim"


@functools.cache
def _fingerprint() -> str:
    from motionsim import __version__

    digest = hashlib.sha256(__version__.encode())
    for name in _SOURCES:
        try:
            digest.update((_HERE / name).read_bytes())
        except OSError:
            digest.update(name.encode())
    return digest.hexdigest()[:16]


class _Store:
    """One function's kept figures: read once, written back whole when one is added."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.entries: dict[str, Any] | None = None

    def path(self) -> Path | None:
        where = folder()
        return None if where is None else where / f"{self.name}-{_fingerprint()}.json"

    def load(self) -> dict[str, Any]:
        if self.entries is None:
            self.entries = {}
            path = self.path()
            if path is not None:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self.entries = data
                except (OSError, ValueError, RecursionError):
                    pass
        return self.entries

    def add(self, key: str, value: Any) -> None:
        entries = self.load()
        entries[key] = value
        path = self.path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside it and moved into place, so that a reader never meets half a file.
            with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as out:
                json.dump(entries, out)
            os.replace(out.name, path)
        except OSError:
            pass


def _figures(value: Any) -> bool:
    """Whether a value read back is figures, nested in lists, as a kept value is."""
    if isinstance(value, list):
        return all(_figures(v) for v in value)
    return value is None or (isinstance(value, float | int) and not isinstance(value, bool) and math.isfinite(value))


def kept(
    name: str, to_plain: Callable[[Any], Any], from_plain: Callable[[Any], Any]
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A function's results kept on disk, keyed by its arguments' repr. to_plain makes a
    result figures in lists; from_plain makes it back, and is given only what passes as
    figures."""
    store = _Store(name)

    def wrap(work: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(work)
        def keeping(*args, **kwargs):
            key = repr((args, sorted(kwargs.items())))
            found = store.load().get(key)
            if found is not None and _figures(found):
                try:
                    return from_plain(found)
                except (TypeError, ValueError):
                    pass
            value = work(*args, **kwargs)
            store.add(key, to_plain(value))
            return value

        return keeping

    return wrap
