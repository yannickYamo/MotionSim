"""Which build of the page this install serves: the id the built page names in its meta tag.

The app says it in a header of every answer and in the session socket's hello, so that a tab
opened on an older build (left open across an update) can tell, stop writing the shared
session, and offer a reload. A write to the session that names an older build is refused. The
id is read from the built page itself, again whenever the file changes: a page built anew while
the app runs is the one served, and the one named.
"""

from __future__ import annotations

import re
import threading

from motionsim import server as builtin

HEADER = "X-MotionSim-Build"
META = re.compile(rb'<meta\s+name="motionsim-build"\s+content="([A-Za-z0-9_-]{1,64})"')
MOST_READ = 64 * 1024  # the head of the page, where the tag is

_lock = threading.Lock()
_seen: tuple[tuple[int, int] | None, str] = (None, "")


def build_id() -> str:
    """The id of the page served, or empty where the page names none (or is not built)."""
    global _seen
    index = builtin.WEB_ROOT / "index.html"
    try:
        stat = index.stat()
    except OSError:
        return ""
    key = (stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _seen[0] == key:
            return _seen[1]
    try:
        with index.open("rb") as page:
            head = page.read(MOST_READ)
    except OSError:
        return ""
    found = META.search(head)
    named = found.group(1).decode("ascii") if found else ""
    with _lock:
        _seen = (key, named)
    return named


def older(sent: str | None) -> bool:
    """Whether a request names a build other than the one served: a page left open across an
    update. A request that names none (an agent, a script, the page in development) is not."""
    served = build_id()
    return bool(sent and served and sent.strip() != served)


OLDER = {
    "refused": "this tab is an older build of MotionSim than the one now running",
    "fix": "reload the page",
    "field": "build",
}
