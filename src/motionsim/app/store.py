"""A small store on this machine: documents by kind and name, in one SQLite file.

The page keeps here what should outlast the browser: a run of the control lab, a scheme, an
exploration. A document is a JSON object, held as text under its kind and its name; nothing
is known here about what is inside one. The file is in MotionSim's folder.

Every call opens the file, does its work in one transaction and closes it, so requests
answered on several threads at once, or by two programs, never share a connection: SQLite
keeps them in turn, and one that has to wait does so for a few seconds before it gives up.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from motionsim.app.home import home, made
from motionsim.errors import Refusal

NAME = "motionsim.db"
# The layout of the file, kept in it as SQLite's user_version. 2 added the shared session and
# its activity (`motionsim.app.session`); a file of layout 1 is laid out again as 2 on opening.
SCHEMA = 2
# session-run: the last run of the lab, kept for the agent and the page to read its traces.
KINDS = ("control-run", "control-scheme", "exploration", "control-verdict", "session-run")
MAX_DOC = 1024 * 1024  # bytes of JSON in one document
MAX_DOCS = 500  # documents of one kind
LONGEST_NAME = 120  # characters of a document's own name shown in a list
WAIT = 10.0  # seconds one call waits for another to finish writing
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_LAYOUT = (
    """
CREATE TABLE IF NOT EXISTS documents (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    updated REAL NOT NULL,
    PRIMARY KEY (kind, id)
) WITHOUT ROWID
""",
    # Every version of the one shared session, the latest last: the page's design and the
    # control lab, as one JSON object. Old versions are what a write on a stale version is
    # rebased from; they are thinned to the latest few hundred.
    """
CREATE TABLE IF NOT EXISTS session_versions (
    version INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    source TEXT NOT NULL,
    at REAL NOT NULL
)
""",
    # What the agent changed, and what was undone: one row a change, with the figures before
    # and after it, for the page's notice and its activity log, and for Undo.
    """
CREATE TABLE IF NOT EXISTS activity (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    at REAL NOT NULL,
    source TEXT NOT NULL,
    body TEXT NOT NULL
)
""",
)


class NotKept(LookupError):
    """Nothing is kept under that kind and name."""


def checked_kind(kind: str) -> str:
    if kind not in KINDS:
        raise Refusal(
            "the store keeps no documents of that kind",
            f"the kinds kept are {', '.join(KINDS)}",
            "kind",
        )
    return kind


def checked_id(name: str) -> str:
    if not ID.fullmatch(name):
        raise Refusal(
            "a document's name is 1 to 64 letters, digits, dots, dashes and underscores, and starts with a letter or a digit",
            "give it such a name",
            "id",
        )
    return name


def _text(doc: object) -> str:
    """The document as the text that is kept, or the refusal of one that cannot be."""
    if not isinstance(doc, dict):
        raise Refusal("a document has to be a JSON object", "send an object, with the figures inside it", "doc")
    try:
        # Written as it was sent, letter for letter, so that what is kept is never longer
        # than what came.
        text = json.dumps(doc, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        size = len(text.encode())
    except (TypeError, ValueError, RecursionError):
        raise Refusal(
            "the document holds something JSON cannot: a figure that is not a number, half a character, "
            "or a value of no JSON kind",
            "leave such a value out, or send it as null",
            "doc",
        ) from None
    if size > MAX_DOC:
        raise Refusal(
            f"the document is {size} bytes, and {MAX_DOC} bytes is the most one may be",
            "keep the settings and the summary, and fewer points of the traces",
            "doc",
        )
    return text


class Store:
    """The documents kept in one file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else home() / NAME
        self._ready = False

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """The file, open for one transaction of a caller's own (the session's)."""
        with self._open() as link:
            yield link

    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        """The file, open for one transaction: committed if the work ends, undone if it
        raises, and closed either way."""
        made(self.path.parent)
        link = sqlite3.connect(self.path, timeout=WAIT, isolation_level=None)
        try:
            if not self._ready:
                self._lay_out(link)
            link.execute("BEGIN IMMEDIATE")
            try:
                yield link
            except BaseException:
                link.execute("ROLLBACK")
                raise
            link.execute("COMMIT")
        finally:
            link.close()

    def _lay_out(self, link: sqlite3.Connection) -> None:
        """The table, made where the file is new, and the file's layout checked where it is
        not: a file written by a later version is left alone and said to be one."""
        (version,) = link.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA:
            raise Refusal(
                f"the store at {self.path.name} was written by a later version of MotionSim",
                "run that version, or move the file away to start an empty store",
            )
        # What is kept is the user's own: the file is closed to everyone else on the machine.
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
        link.execute("BEGIN IMMEDIATE")
        for table in _LAYOUT:
            link.execute(table)
        link.execute(f"PRAGMA user_version = {SCHEMA}")
        link.execute("COMMIT")
        self._ready = True

    def put(self, kind: str, name: str, doc: object) -> dict:
        """Keep a document under its kind and name, in place of the one that was there."""
        checked_kind(kind), checked_id(name)
        text = _text(doc)
        assert isinstance(doc, dict)
        own = doc.get("name")
        title = own[:LONGEST_NAME] if isinstance(own, str) else ""
        now = time.time()
        with self._open() as link:
            there = link.execute("SELECT 1 FROM documents WHERE kind = ? AND id = ?", (kind, name)).fetchone()
            (count,) = link.execute("SELECT COUNT(*) FROM documents WHERE kind = ?", (kind,)).fetchone()
            if not there and count >= MAX_DOCS:
                raise Refusal(
                    f"{count} documents of the kind {kind} are kept, and {MAX_DOCS} is the most",
                    "delete one that is no longer needed, then save again",
                    "kind",
                )
            link.execute(
                "INSERT OR REPLACE INTO documents (kind, id, name, body, updated) VALUES (?, ?, ?, ?, ?)",
                (kind, name, title, text, now),
            )
        return {"kind": kind, "id": name, "name": title, "updated": now, "bytes": len(text.encode())}

    def get(self, kind: str, name: str) -> dict:
        """The document kept under a kind and name. Raises NotKept where there is none."""
        checked_kind(kind), checked_id(name)
        with self._open() as link:
            row = link.execute(
                "SELECT name, body, updated FROM documents WHERE kind = ? AND id = ?", (kind, name)
            ).fetchone()
        if row is None:
            raise NotKept(f"{kind}/{name}")
        return {"kind": kind, "id": name, "name": row[0], "updated": row[2], "doc": json.loads(row[1])}

    def list(self, kind: str) -> list[dict]:
        """What is kept of one kind, the latest first: each document's name, when it was
        kept and its size, and not the documents themselves."""
        checked_kind(kind)
        with self._open() as link:
            rows = link.execute(
                "SELECT id, name, updated, LENGTH(CAST(body AS BLOB)) FROM documents WHERE kind = ? "
                "ORDER BY updated DESC, id",
                (kind,),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "updated": r[2], "bytes": r[3]} for r in rows]

    def delete(self, kind: str, name: str) -> None:
        """Take a document away. Raises NotKept where there was none."""
        checked_kind(kind), checked_id(name)
        with self._open() as link:
            gone = link.execute("DELETE FROM documents WHERE kind = ? AND id = ?", (kind, name)).rowcount
        if not gone:
            raise NotKept(f"{kind}/{name}")
