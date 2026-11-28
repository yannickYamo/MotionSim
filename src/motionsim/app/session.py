"""The one shared session of this install: the page's design and the control lab, as one
versioned JSON object in the store, written by the page and by a coding agent.

The session is `{"design": <the page's state>, "lab": <the lab's part>}`. A write is compared
with the version it was made on figure by figure (a path of names to a value that is not an
object). All that is known here of what is inside a part is which of the design's figures only
make sense together (pagestate.UNITS): such a set moves as one.

Versions. Every write that changes something makes a new version. A write says the version it
was made on (`base`):

- made on the latest, it is taken as it is;
- made on an older one, what it changed (against that older version) is laid over the latest:
  where no figure it changed was changed since, nothing is lost (rebased); where one was, the
  write wins, as the latest word, and the writer whose figure was replaced is told: the answer
  and the change pushed to everyone carry `overwrote`, with the figures and who had set them.

Activity. A change made by the agent (and an undo) is kept as an entry: what it changed, each
figure before and after, and when. The page shows the latest as a notice with Undo, and all of
them in its activity log; Undo puts back each figure the change set, where it still holds what
the change left there. A figure changed again since is not put back over that later change:
the undo is refused, and says which figure and what to do.

The page's own writes are not entries: it has its own undo, and writes at every keystroke.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

from motionsim.app.pagestate import UNITS
from motionsim.app.store import MAX_DOC, Store
from motionsim.errors import Refusal

PARTS = ("design", "lab")
SOURCES = ("page", "agent", "chat", "undo")
KEEP_VERSIONS = 300  # versions kept to rebase a stale write on
KEEP_ACTIVITY = 500  # entries of the activity log
MOST_SHOWN = 40  # figures of one change said in full; more are counted
LONGEST_VALUE = 400  # characters of a value kept in an entry; a longer one is kept whole as well

Path = tuple[str, ...]
Listener = Callable[[dict], None]


def _leaves(doc: Any, at: Path = ()) -> dict[Path, Any]:
    """Every figure of a document by its path: a value that is not an object is a figure, and
    so is an empty object (a list is a figure whole: its items are not told apart)."""
    if isinstance(doc, dict) and doc:
        out: dict[Path, Any] = {}
        for key, value in doc.items():
            out.update(_leaves(value, (*at, str(key))))
        return out
    return {at: doc}


def diff(before: Any, after: Any, by_figure: bool = False) -> dict[Path, tuple[Any, Any]]:
    """The figures that differ between two documents: each path with its value before and
    after (`MISSING` where it is not there)."""
    a, b = _leaves(before), _leaves(after)
    out: dict[Path, tuple[Any, Any]] = {}
    for path in a.keys() | b.keys():
        old, new = a.get(path, MISSING), b.get(path, MISSING)
        # An empty object filled, or emptied, is said by the figures that came or went.
        if by_figure and {type(old), type(new)} == {dict, _Missing} and (old == {} or new == {}):
            continue
        if not _same(old, new):
            out[path] = (old, new)
    # A figure that became an object, or an object a figure: the shorter path stands for it,
    # with the whole of what is there on either side.
    short = [p for p in out if any(q != p and q[: len(p)] == p for q in out)]
    for p in short:
        out[p] = (get_at(before, p), get_at(after, p))
    return {p: v for p, v in out.items() if not any(q != p and p[: len(q)] == q for q in short)}


def _overwritten(mine: dict, theirs: dict, given: dict, now_doc: dict) -> list[dict]:
    """The figures a stale write sets that were set to something else since it was made on:
    each said as it was set since, where the write leaves it otherwise."""
    return [
        {"path": dotted(path), "was": _plain(theirs[path][1])}
        for path in _overlap(theirs, mine)
        if not _same(get_at(given, path), get_at(now_doc, path))
    ]


def _within(path: Path, outer: Path) -> bool:
    return path[: len(outer)] == outer


# Each set of the design's figures that moves as one (pagestate.UNITS), as paths in the session.
_UNITS: tuple[tuple[Path, ...], ...] = tuple(tuple(("design", *figure.split(".")) for figure in unit) for unit in UNITS)


def _whole(mine: dict, on: dict, given: dict) -> dict:
    """What a write changed, with every set of figures that moves as one taken whole where it
    changed any of them: a stale write lays all of the set over the latest, or none of it, so
    that a merge never leaves the parts on the page of one version beside the parts ticked of
    another."""
    out = dict(mine)
    for unit in _UNITS:
        if unit[0][0] not in given or not any(_within(p, m) or _within(m, p) for p in mine for m in unit):
            continue
        for m in unit:
            for p in [p for p in out if _within(p, m)]:
                del out[p]
            if not any(_within(m, p) for p in out):  # held whole already by a path round it
                out[m] = (get_at(on, m), get_at(given, m))
    return out


def _merged(now_doc: dict, mine: dict, given: dict) -> dict:
    """The latest version with what the write changed laid over it."""
    merged = json.loads(json.dumps(now_doc))
    for path, (_, new) in mine.items():
        if len(path) == 1:
            merged[path[0]] = None if new is MISSING else new
            continue
        set_at(merged, path, new)
        if new is MISSING:  # an object the write no longer has goes when nothing is left in it
            for k in range(len(path) - 1, 1, -1):
                if get_at(given, path[:k]) is MISSING and get_at(merged, path[:k]) == {}:
                    set_at(merged, path[:k], MISSING)
    return merged


def _mark_made(entry: dict, before: dict, after: dict) -> None:
    """What an entry's undo takes away whole: the objects it made, the parts it began."""
    for f in entry["figures"]:
        if not f["had"]:
            f["made"] = _first_absent(before, tuple(f["path"].split(".")))
    entry["began"] = [k for k in PARTS if before.get(k) is None and isinstance(after.get(k), dict)]


def _hollow(value: Any) -> bool:
    """An object with nothing in it but empty objects."""
    return isinstance(value, dict) and all(_hollow(v) for v in value.values())


def _first_absent(doc: Any, path: Path) -> list[str]:
    """The shortest part of a path that the document did not have."""
    for k in range(1, len(path) + 1):
        if get_at(doc, path[:k]) is MISSING:
            return list(path[:k])
    return list(path)


def _opened(before: dict, after: dict) -> dict:
    """The document before, with a part that was null and is now an object read as an empty
    object: what such a write changed is then its figures, each undone alone."""
    return {**before, **{k: {} for k in PARTS if before.get(k) is None and isinstance(after.get(k), dict)}}


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def label_of(path: Path, labels: dict[str, dict]) -> dict:
    """A figure's label and unit: its own, else that of the nearest object round it whose label
    stands for everything within it (the page's bookkeeping, by kind of motor and so on)."""
    own = labels.get(dotted(path))
    if own is not None:
        return own
    for k in range(len(path) - 1, 0, -1):
        found = labels.get(dotted(path[:k]))
        if found is not None and found.get("within"):
            return found
    return {}


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


def get_at(doc: Any, path: Path) -> Any:
    for key in path:
        if not isinstance(doc, dict) or key not in doc:
            return MISSING
        doc = doc[key]
    return doc


def set_at(doc: dict, path: Path, value: Any) -> None:
    """Put a value at a path, making the objects on the way; MISSING takes it away."""
    for key in path[:-1]:
        nxt = doc.get(key)
        if not isinstance(nxt, dict):
            nxt = doc[key] = {}
        doc = nxt
    if value is MISSING:
        doc.pop(path[-1], None)
    else:
        doc[path[-1]] = value


def _overlap(a: Iterable[Path], b: Iterable[Path]) -> list[Path]:
    """The paths of one set that are, contain, or lie inside a path of the other."""
    bs = list(b)
    return sorted({p for p in a for q in bs if p[: len(q)] == q or q[: len(p)] == p})


def dotted(path: Path) -> str:
    return ".".join(path)


def _plain(value: Any) -> Any:
    return None if value is MISSING else value


def checked_doc(doc: object) -> dict:
    """A whole session, or the refusal of one that is not."""
    if not isinstance(doc, dict):
        raise Refusal("a session is a JSON object", 'send {"design": ..., "lab": ...}', "doc")
    stray = [k for k in doc if k not in PARTS]
    if stray:
        raise Refusal(
            f"a session holds {' and '.join(PARTS)}, and not {', '.join(map(str, stray))}",
            "leave the other names out",
            stray[0],
        )
    for part in PARTS:
        if doc.get(part) is not None and not isinstance(doc[part], dict):
            raise Refusal(f"the session's {part} is a JSON object, or null", f"send {part} as an object", part)
    text = json.dumps(doc, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode()) > MAX_DOC:
        raise Refusal(
            f"the session is {len(text.encode())} bytes, and {MAX_DOC} bytes is the most it may be",
            "leave out the mission's points, or keep fewer parts compared",
            "doc",
        )
    return doc


class Stale(Refusal):
    """An undo that would put a figure back over a later change of it."""


class Session:
    """The shared session, kept in the store's file."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._lock = threading.RLock()  # one write at a time within this program; SQLite between programs
        self.listeners: list[Listener] = []

    # -- reading ----------------------------------------------------------------------------

    def current(self) -> dict:
        """The latest version: {"version", "doc", "at", "source"}. Version 0 is the empty one."""
        with self.store.transaction() as link:
            row = link.execute(
                "SELECT version, body, at, source FROM session_versions ORDER BY version DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"version": 0, "doc": {"design": None, "lab": None}, "at": None, "source": None}
        return {"version": row[0], "doc": json.loads(row[1]), "at": row[2], "source": row[3]}

    def _version(self, link, version: int) -> dict | None:
        if version == 0:
            return {"design": None, "lab": None}
        row = link.execute("SELECT body FROM session_versions WHERE version = ?", (version,)).fetchone()
        return None if row is None else json.loads(row[0])

    def activity(self, limit: int = 100, source: str | None = None) -> list[dict]:
        """The latest entries first."""
        with self.store.transaction() as link:
            rows = link.execute(
                "SELECT body FROM activity" + (" WHERE source = ?" if source else "") + " ORDER BY seq DESC LIMIT ?",
                ((source, limit) if source else (limit,)),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def entry(self, change_id: str) -> dict:
        with self.store.transaction() as link:
            row = link.execute("SELECT body FROM activity WHERE id = ?", (change_id,)).fetchone()
        if row is None:
            raise Refusal(
                f"no change has the id {change_id}",
                "take the id from the change's answer, or from get_session's recent activity",
                "change_id",
            )
        return json.loads(row[0])

    # -- writing ----------------------------------------------------------------------------

    def write(
        self,
        doc: dict,
        base: int | None,
        source: str,
        what: str = "",
        labels: dict[str, dict] | None = None,
        client: str = "",
        kind: str = "change",
        undoes: str = "",
    ) -> dict:
        """Write the parts of a session given (a part left out is left as it is), as made on
        version `base` (None: on the latest). Returns what came of it: the new version, the
        figures changed, whether it was rebased, what it overwrote and the entry it made."""
        if source not in SOURCES:
            raise Refusal(f"a write comes from one of {', '.join(SOURCES)}", "say where it comes from", "source")
        checked_doc(doc)
        with self._lock, self.store.transaction() as link:
            latest = link.execute("SELECT version, body FROM session_versions ORDER BY version DESC LIMIT 1").fetchone()
            version, now_doc = (latest[0], json.loads(latest[1])) if latest else (0, {"design": None, "lab": None})
            base = version if base is None else base
            if base > version or base < 0:
                raise Refusal(
                    f"version {base} of the session was never written: the latest is {version}",
                    "read the session again and write on what it says",
                    "base",
                )
            given = {k: doc[k] for k in PARTS if k in doc}
            # A version thinned away: what the write changed is everything it differs in now.
            on = (self._version(link, base) if base != version else now_doc) or now_doc
            mine = _whole(diff({k: on.get(k) for k in given}, given), on, given)
            rebased = base != version
            overwrote = _overwritten(mine, diff(on, now_doc), given, now_doc) if rebased else []
            merged = _merged(now_doc, mine, given)
            changes = diff(_opened(now_doc, merged), merged, by_figure=True) or diff(now_doc, merged)
            if not changes:
                return {"version": version, "changed": [], "rebased": rebased, "overwrote": [], "change": None}
            checked_doc(merged)
            version += 1
            at = time.time()
            link.execute(
                "INSERT INTO session_versions (version, body, source, at) VALUES (?, ?, ?, ?)",
                (version, json.dumps(merged, ensure_ascii=False, separators=(",", ":")), source, at),
            )
            link.execute("DELETE FROM session_versions WHERE version <= ?", (version - KEEP_VERSIONS,))
            owners = self._owners(link, [o["path"] for o in overwrote]) if overwrote else {}
            for o in overwrote:
                o["by"] = owners.get(o["path"], "page")
            entry = None
            if source != "page":
                entry = self._entry(changes, source, what, labels or {}, at, version, kind, undoes)
                _mark_made(entry, now_doc, merged)
                self._keep_entry(link, entry)
            elif overwrote:
                self._mark_overwritten(link, [o["path"] for o in overwrote], at)
        out = {
            "version": version,
            "changed": sorted(dotted(p) for p in changes),
            "rebased": rebased,
            "overwrote": overwrote,
            "change": entry,
        }
        self._tell({"type": "session", "version": version, "source": source, "client": client, **out})
        return out

    def _entry(
        self,
        changes: dict[Path, tuple[Any, Any]],
        source: str,
        what: str,
        labels: dict[str, dict],
        at: float,
        version: int,
        kind: str,
        undoes: str,
    ) -> dict:
        figures = []
        for path in sorted(changes):
            old, new = changes[path]
            key = dotted(path)
            label = label_of(path, labels)
            figures.append(
                {
                    "path": key,
                    "label": label.get("label", key),
                    "unit": label.get("unit", ""),
                    "old": _plain(old),
                    "new": _plain(new),
                    "had": old is not MISSING,
                    **({"kept": True} if label.get("kept") else {}),
                }
            )
        return {
            "id": secrets.token_hex(6),
            "at": at,
            "source": source,
            "kind": kind,
            "what": what or _what(figures),
            "figures": figures,
            "version": version,
            "undone": None,
            "undoes": undoes or None,
            "overwritten": None,
            "undoable": kind != "undo",
        }

    def _keep_entry(self, link, entry: dict) -> None:
        link.execute(
            "INSERT INTO activity (id, at, source, body) VALUES (?, ?, ?, ?)",
            (entry["id"], entry["at"], entry["source"], json.dumps(entry, ensure_ascii=False, default=str)),
        )
        link.execute(
            "DELETE FROM activity WHERE seq <= (SELECT MAX(seq) FROM activity) - ?",
            (KEEP_ACTIVITY,),
        )

    def _owners(self, link, paths: list[str]) -> dict[str, str]:
        """Who last set each of these figures, as far as the activity says: the agent, or the page."""
        out: dict[str, str] = {}
        for (body,) in link.execute("SELECT body FROM activity ORDER BY seq DESC LIMIT 50"):
            entry = json.loads(body)
            for f in entry.get("figures", []):
                if f["path"] in paths and f["path"] not in out:
                    out[f["path"]] = entry["source"]
        return out

    def _mark_overwritten(self, link, paths: list[str], at: float) -> None:
        """An agent's change whose figure the page's stale write replaced: said on its entry."""
        for seq, body in link.execute("SELECT seq, body FROM activity ORDER BY seq DESC LIMIT 50").fetchall():
            entry = json.loads(body)
            hit = [f["path"] for f in entry.get("figures", []) if f["path"] in paths]
            if hit and not entry.get("overwritten"):
                entry["overwritten"] = {"at": at, "by": "page", "figures": hit}
                link.execute("UPDATE activity SET body = ? WHERE seq = ?", (json.dumps(entry, default=str), seq))

    def note(
        self,
        what: str,
        source: str = "agent",
        kind: str = "action",
        details: dict | None = None,
        undoable: bool = False,
    ) -> dict:
        """An entry for something done that changes no figure of the session (an export, a
        sweep): logged, and pushed, with nothing to undo."""
        entry: dict[str, Any] = {
            "id": secrets.token_hex(6),
            "at": time.time(),
            "source": source,
            "kind": kind,
            "what": what,
            "figures": [],
            "version": None,
            "undone": None,
            "undoes": None,
            "overwritten": None,
            "undoable": undoable,
            **({"details": details} if details else {}),
        }
        with self._lock, self.store.transaction() as link:
            self._keep_entry(link, entry)
        self._tell({"type": "activity", "change": entry})
        return entry

    def mark_undone(self, change_id: str, by: str | None = None) -> dict:
        """Mark an entry undone (an action put back by whoever did it, an export taken away)."""
        with self._lock:
            entry = self.entry(change_id)
            entry["undone"] = {"at": time.time(), "by": by}
            with self.store.transaction() as link:
                link.execute("UPDATE activity SET body = ? WHERE id = ?", (json.dumps(entry, default=str), change_id))
        self._tell({"type": "activity", "change": entry})
        return entry

    def undo(self, change_id: str, client: str = "") -> dict:
        """Put back each figure a change set, where it still holds what the change left there."""
        with self._lock:
            entry = self.entry(change_id)
            if entry.get("undone"):
                raise Refusal("that change was undone already", "nothing more to do", "change_id")
            if not entry.get("figures"):
                raise Refusal(
                    "that entry changed nothing of the design or the lab, so there is nothing to put back",
                    "undo a change that set a figure",
                    "change_id",
                )
            now = self.current()
            doc = json.loads(json.dumps(now["doc"]))
            for f in entry["figures"]:
                path = tuple(f["path"].split("."))
                there = get_at(doc, path)
                if not _same(_plain(there), f["new"]):
                    raise Stale(
                        f"{f['label']} was changed again after this change (it is now {_said(there)}), "
                        "so it is not put back over that",
                        "set it by hand, or undo the later change first",
                        f["path"],
                    )
            for f in entry["figures"]:
                set_at(doc, tuple(f["path"].split(".")), f["old"] if f["had"] else MISSING)
            for f in entry["figures"]:  # an object the change made for a figure goes with it
                made = tuple(f.get("made") or ())
                if made and len(made) > 1 and get_at(doc, made) == {}:
                    set_at(doc, made, MISSING)
            for part in entry.get("began", []):  # a part the change began, taken back whole
                if _hollow(doc.get(part)):
                    doc[part] = None
            labels = {
                f["path"]: {"label": f["label"], "unit": f["unit"], **({"kept": True} if f.get("kept") else {})}
                for f in entry["figures"]
            }
            out = self.write(
                {k: doc.get(k) for k in PARTS},
                now["version"],
                "undo",
                what=f"Undid: {entry['what']}",
                labels=labels,
                client=client,
                kind="undo",
                undoes=change_id,
            )
            with self.store.transaction() as link:
                entry["undone"] = {"at": time.time(), "by": (out["change"] or {}).get("id")}
                link.execute("UPDATE activity SET body = ? WHERE id = ?", (json.dumps(entry, default=str), change_id))
            self._tell({"type": "activity", "change": entry})
        return out

    # -- telling ----------------------------------------------------------------------------

    def _tell(self, event: dict) -> None:
        for listener in list(self.listeners):
            try:
                listener(event)
            except Exception:  # a listener that fails takes nobody else down with it
                continue


def shown(entry: dict) -> dict:
    """An entry as it is sent: a value too long to show (a whole scheme, a list of stretches)
    is said by its size; the figures are kept whole in the store for Undo."""

    def short(value: Any) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        return value if len(text) <= LONGEST_VALUE else {"elided": f"{len(text)} characters"}

    # The page's bookkeeping is kept for Undo, and never said as a figure changed.
    figures = [f for f in entry.get("figures", []) if not f.get("kept")]
    out = [{**f, "old": short(f["old"]), "new": short(f["new"])} for f in figures[:MOST_SHOWN]]
    return {**entry, "figures": out, "more": max(0, len(figures) - MOST_SHOWN)}


def _said(value: Any) -> str:
    if value is MISSING or value is None or value == "":
        return "empty"
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= 60 else text[:57] + "..."


def figure_text(value: Any, unit: str = "") -> str:
    """A value as the notice says it: a number with its unit, a word as it is."""
    if value is None or value == "" or value is MISSING:
        return "empty"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        text = f"{value:.4g}"
        return f"{text} {unit}".strip()
    if isinstance(value, str):
        return f"{value} {unit}".strip() if unit else value
    if isinstance(value, list):
        return f"{len(value)} items"
    return "changed"


def _what(figures: list[dict]) -> str:
    """The change in a line: the first figures with their old and new values. A figure with no
    label of its own (the page's bookkeeping of whose a figure is) is left out of the line
    where any labelled one changed."""
    said = [f for f in figures if not f.get("kept")] or figures
    labelled = [f for f in said if f["label"] != f["path"]]
    figures = labelled or said
    shown = [
        f"{f['label']} {figure_text(f['old'], f['unit'])} → {figure_text(f['new'], f['unit'])}" for f in figures[:3]
    ]
    more = len(figures) - 3
    return "; ".join(shown) + (f"; and {more} more" if more > 0 else "")
