"""The shared session over HTTP and a WebSocket, and the agent's settings, for the page.

    GET    /api/session                 the latest version: {"version", "doc", "at", "source"}
    PUT    /api/session                 {"base": version, "doc": {"design"?, "lab"?}, "client": id}
                                        -> {"version", "changed", "rebased", "overwrote", "change"}
    GET    /api/session/activity        {"items": [entry, ...]}, the latest first
    POST   /api/session/undo            {"change": id, "client": id} -> as PUT; 422 where it cannot be
    GET    /api/settings/agent          {"code", "url", "command", "write"}: how to connect an agent
    POST   /api/settings/agent/code     a new access code, the old one refused from then on
    GET    /api/exports/<name>          a file an agent exported (a report, a scheme)
    WS     /ws/session                  {"type": "hello", "version", "build"}, then every change as it is made:
                                        {"type": "session", "version", "source", "client", "changed",
                                         "rebased", "overwrote", "change"} and
                                        {"type": "activity", "change"} (an undo marked, an export noted)

Each is for this machine's own page alone, as the store and the settings are.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from starlette.datastructures import Headers

from motionsim.app import access
from motionsim.app.build import build_id
from motionsim.app.home import home
from motionsim.app.session import Session, shown

SESSION = "/api/session"
ACTIVITY = "/api/session/activity"
UNDO = "/api/session/undo"
AGENT = "/api/settings/agent"
NEW_CODE = "/api/settings/agent/code"
CHAT = "/api/session/chat"
EXPORTS = "/api/exports/"
SOCKET = "/ws/session"
PATHS = (SESSION, ACTIVITY, UNDO, AGENT, NEW_CODE, CHAT)
MOST_LISTENERS = 32  # pages open at once on one install
EXPORT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
EXPORT_TYPES = {
    ".pdf": "application/pdf",
    ".svg": "image/svg+xml",
    ".md": "text/markdown; charset=utf-8",
    ".c": "text/x-c; charset=utf-8",
    ".h": "text/x-c; charset=utf-8",
    ".zip": "application/zip",
    ".json": "application/json",
}


def exports() -> Path:
    return home() / "exports"


def handles(path: str) -> bool:
    return path in PATHS or path.startswith(EXPORTS)


def mcp_url(headers: Headers) -> str:
    host = headers.get("host") or "localhost:4310"
    return f"http://{host}/mcp"


def agent_settings(headers: Headers) -> dict:
    """How an agent connects, with the code: for this machine's own page alone."""
    code = access.code()
    url = mcp_url(headers)
    return {
        "code": code,
        "url": url,
        "command": f'claude mcp add --transport http motionsim {url} --header "Authorization: Bearer {code}"',
        "write": True,
    }


class Hub:
    """The pages listening for changes: each a queue, filled from whichever thread wrote."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        session.listeners.append(self._heard)

    def _heard(self, event: dict) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        for queue in list(self.queues):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_offer, queue, event)

    async def serve(self, socket: WebSocket) -> None:
        """One page, told of every change from now on until it goes."""
        self.loop = asyncio.get_running_loop()
        if len(self.queues) >= MOST_LISTENERS:
            return await socket.close(1013, "too many pages are listening")
        await socket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.queues.add(queue)
        gone = asyncio.ensure_future(_gone(socket))
        try:
            version = (await asyncio.to_thread(self.session.current))["version"]
            await socket.send_json({"type": "hello", "version": version, "build": build_id()})
            while not gone.done():
                taken = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({taken, gone}, return_when=asyncio.FIRST_COMPLETED)
                if taken not in done:
                    taken.cancel()
                    break
                event = taken.result()
                if event.get("change"):
                    event = {**event, "change": shown(event["change"])}
                await socket.send_json(event)
        except (OSError, RuntimeError, WebSocketDisconnect):
            pass
        finally:
            self.queues.discard(queue)
            gone.cancel()
            with contextlib.suppress(OSError, RuntimeError, WebSocketDisconnect):
                await socket.close()


def _offer(queue: asyncio.Queue, event: dict) -> None:
    """A page that has not read its last 256 changes is told to read the session again."""
    if queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            while True:
                queue.get_nowait()
        queue.put_nowait({"type": "behind"})
        return
    queue.put_nowait(event)


async def _gone(socket: WebSocket) -> None:
    """Returns once the page has gone. What it says is not listened to."""
    while True:
        message = await socket.receive()
        if message["type"] == "websocket.disconnect":
            return


def exported(name: str) -> tuple[bytes, str] | None:
    """An exported file by its name, and its type; None for no such file."""
    if not EXPORT_NAME.fullmatch(name):
        return None
    target = exports() / name
    kind = EXPORT_TYPES.get(target.suffix)
    if kind is None or not target.is_file() or target.is_symlink():
        return None
    return target.read_bytes(), kind
