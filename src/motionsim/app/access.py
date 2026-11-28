"""The access code a coding agent connects with: one per install, made at the first start.

The code is kept in a file of its own in MotionSim's folder, readable and writable by its owner
and nobody else, as the reader's key is. The agent sends it as a bearer token on every request
to /mcp; the page shows it in Settings, where it can be made anew (the old one then stops
working at once). It is never written to a log, and no tool of the agent's ever says it.
"""

from __future__ import annotations

import contextlib
import hmac
import os
import secrets
import tempfile
import threading
from pathlib import Path

from motionsim.app.home import home, made

NAME = "agent.code"
LENGTH = 32  # bytes of randomness: 43 characters of URL-safe text
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_PUTTING = threading.Lock()


def path() -> Path:
    return home() / NAME


def _read() -> str:
    try:
        handle = os.open(path(), os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(handle, "rb") as kept:
            text = kept.read(256).decode("ascii").strip()
    except (OSError, ValueError):
        return ""
    return text if len(text) >= 32 and text.isascii() and text.replace("-", "").replace("_", "").isalnum() else ""


def _write(code: str) -> None:
    folder = made(home())
    handle, beside = tempfile.mkstemp(prefix=f".{NAME}.", suffix=".new", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as out:
            out.write(code)
        with _PUTTING:
            os.replace(beside, folder / NAME)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(beside)


def code() -> str:
    """The code, made and kept where there is none yet."""
    kept = _read()
    if kept:
        return kept
    with _PUTTING:
        kept = _read()
    if kept:
        return kept
    made_now = secrets.token_urlsafe(LENGTH)
    _write(made_now)
    return _read() or made_now


def regenerate() -> str:
    """A new code in place of the old: an agent connected with the old one is refused from now on."""
    fresh = secrets.token_urlsafe(LENGTH)
    _write(fresh)
    return fresh


def admitted(authorization: str | None) -> bool:
    """Whether a request's Authorization header carries the code, compared in constant time."""
    if not authorization:
        return False
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return False
    return hmac.compare_digest(token.strip().encode(), code().encode())
