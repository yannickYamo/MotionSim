"""The service as an ASGI app: FastAPI over the same dispatch the standard library's server uses.

Nothing is worked out here and nothing about an address of the service is known here: a
request is checked as `motionsim.server` checks it (where it comes from, where it is going,
how large it is), handed to the service's one `dispatch` on a worker thread, and its answer
sent with the same status, body and headers. An address added to the service's tables is
answered here from then on, with no change to this module.

What this app adds to the standard library's server:

- `/ws/stream`, a WebSocket over the same step-by-step searches as `<address>/stream`;
- `/api/store/...`, the local store (`motionsim.app.store`);
- `/api/settings`, the datasheet reader's key (`motionsim.app.keys`);
- `/api/control/phrase`, a run's verdict phrased by the language model set up for the reader
  (`motionsim.control.verdict_phrase`), kept in the store by the verdict's key;
- `/api/control/export_port`, the C export ported to a microcontroller by the same model
  (`motionsim.service.control.export_port`);
- `/api/session/...` and `/ws/session`, the session the page shares with a coding agent, and
  `/api/settings/agent`, how the agent connects (`motionsim.app.shared`);
- the build of the page it serves, named in a header of every answer (`motionsim.app.build`),
  so a tab left open across an update can tell, and a session write from it is refused;
- `/mcp`, the coding agent's own way in, by the Model Context Protocol (`motionsim.app.agent`),
  for a request that carries the install's access code.

Every request, of any method and to any address, the WebSocket too, is answered only for
this machine's own page: see `local`.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import logging
import threading
from collections.abc import Callable, Generator, Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from motionsim import server as builtin
from motionsim.app import access, keys, shared
from motionsim.app.build import HEADER as BUILD_HEADER
from motionsim.app.build import OLDER, build_id, older
from motionsim.app.home import devices, home, made
from motionsim.app.session import Session, shown

if TYPE_CHECKING:
    from motionsim.app.agent import Bench
from motionsim.app.store import MAX_DOC, NotKept, Store
from motionsim.errors import Refusal
from motionsim.service import routes
from motionsim.service.answers import answer, fault_of
from motionsim.service.workspace import Workspace

log = logging.getLogger("motionsim")

JSON = builtin.MIME[".json"]
METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH")
ALLOW = "GET, HEAD, POST, PUT, DELETE, OPTIONS"
# The names this machine is asked for by, from a browser on it.
LOCAL = ("127.0.0.1", "localhost", "[::1]")
SOCKET = "/ws/stream"
STORE = "/api/store/"
SETTINGS = "/api/settings"
KEY = "/api/settings/key"
PHRASE = "/api/control/phrase"
PORT = "/api/control/export_port"
NOT_KEPT = {"error": "nothing is kept under that name"}
# Kinds of the store that the app writes itself and a request may only read.
WRITTEN_HERE = {
    "control-verdict": {
        "error": "phrased verdicts are kept by the app from its own checked phrasings, and are not written "
        "or taken away from outside",
        "fix": "POST /api/control/phrase with the run's quality: the app phrases and keeps it",
    }
}
STOPPED = {"error": "the request stopped before its end"}
NO_DOC = {"error": "the request holds no document: a document to keep is sent as a JSON object"}
TOO_LARGE_KEY = {
    "refused": "the request is too large to be a key",
    "fix": "paste the key alone",
    "field": "key",
}
TOO_LARGE_DOC = {
    "refused": f"the document is too large to be kept: {MAX_DOC} bytes is the most one may be",
    "fix": "keep the settings and the summary, and fewer points of the traces",
    "field": "doc",
}

# Searches over sockets at once: each holds a worker for as long as it runs, and the workers
# are what every other request is answered on too.
MOST_STREAMS = 8


def busy() -> dict:
    return {
        "refused": f"{MOST_STREAMS} searches are already running, which is as many as run at once",
        "fix": "wait for one to finish, or stop one in another tab, and ask again",
        "field": "",
    }


Answer = tuple[int, dict]


def local(headers: Headers) -> bool:
    """Only this machine's own page may talk to the engine, the store and the settings.

    Another site open in the same browser could otherwise post to this address, and that
    would spend the user's key, change it, or read what is kept. The Host header must name
    this machine, which a page of another name pointed at this address cannot do; and a
    request that says where it came from must have come from the page at that very host,
    over plain HTTP, which is how this page is served. The port is whatever the browser was
    given: in a container the port inside is not the port outside.
    """
    hosts = headers.getlist("host")
    origins = headers.getlist("origin")
    if len(hosts) != 1 or len(origins) > 1:
        return False
    name, colon, port = hosts[0].rpartition(":")
    if not colon:
        name, port = hosts[0], "80"
    if name not in LOCAL or not (port.isascii() and port.isdigit()):
        return False
    return not origins or origins[0] == f"http://{hosts[0]}"


def same_origin(headers: Headers) -> bool:
    """Whether a request to the store or the settings was made by this page itself, as a
    browser says of every request it sends. A program that is not a browser says nothing,
    and is answered: it could read the files themselves."""
    return headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")


def _packed(body: bytes, kind: str, accepted: str) -> tuple[bytes, dict[str, str]]:
    """The body as it goes: text of more than a kilobyte gzipped for a browser that takes it."""
    textual = kind.startswith(("text/", "application/json", "image/svg"))
    if not (textual and len(body) > 1024):
        return body, {}
    if not builtin.takes_gzip(accepted):
        return body, {"Vary": "Accept-Encoding"}
    return gzip.compress(body, compresslevel=6, mtime=0), {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"}


def reply(headers: Headers, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None) -> Response:
    """An answer with the headers every answer of the page carries."""
    body, packing = _packed(body, kind, headers.get("accept-encoding") or "")
    build = build_id()
    return Response(
        content=body,
        status_code=status,
        headers={
            "Server": "motionsim",
            "Content-Type": kind,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": builtin.POLICY,
            **packing,
            **({BUILD_HEADER: build} if build else {}),
            **(extra or {}),
        },
    )


def said(headers: Headers, payload: object, status: int = 200, extra: dict[str, str] | None = None) -> Response:
    return reply(headers, status, builtin.written(payload), JSON, extra)


# The headers every answer carries, added where an answer was made below this app's own code
# (a framework's own answer to a method or an address it takes no route for) without them.
STRICT = (
    (b"server", b"motionsim"),
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"content-security-policy", builtin.POLICY.encode()),
)


def _strict(send: Send) -> Send:
    async def sent(message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            have = {name.lower() for name, _ in headers}
            headers += [(name, value) for name, value in STRICT if name not in have]
            message = {**message, "headers": headers}
        await send(message)

    return sent


class OnlyLocal:
    """Everything the app answers, held to this machine's own page before anything else
    sees the request, and answered with the page's headers whatever answers it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            send = _strict(send)
        if scope["type"] not in ("http", "websocket") or local(Headers(scope=scope)):
            if scope["type"] == "http" and scope["method"] not in METHODS:
                headers = Headers(scope=scope)
                answer = {"error": f"{scope['method']} is not answered at this address"}
                return await said(headers, answer, 405, {"Allow": ALLOW})(scope, receive, send)
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            # Closed before it is taken: the browser is told 403, and no message is read.
            return await send({"type": "websocket.close", "code": 1008})
        await said(Headers(scope=scope), builtin.ONLY_LOCAL, 403)(scope, receive, send)


class Lines(Response):
    """A search answered a line at a time, each line a JSON object: a step as it finishes,
    then the answer. Each step is worked out on a worker thread; a page that stops waiting
    stops the search before its next step."""

    def __init__(self, lines: Generator[dict, None, None], done: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.lines, self.done = lines, done
        self.raw_headers = [
            (name.encode(), value.encode())
            for name, value in (
                ("server", "motionsim"),
                ("content-type", "application/x-ndjson"),
                ("cache-control", "no-store"),
                ("x-content-type-options", "nosniff"),
                ("content-security-policy", builtin.POLICY),
                ("connection", "close"),
            )
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The request is read whole, so all the page has left to say is that it has gone;
        # the server says nothing of that when a line is sent, and has to be asked.
        gone = asyncio.ensure_future(_gone(receive))
        try:
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            stopped = threading.Event()
            gone.add_done_callback(lambda _: stopped.set())
            while not gone.done():
                line = await run_in_threadpool(_step, self.lines, stopped)
                if line is None:
                    await send({"type": "http.response.body", "body": b""})
                    break
                if gone.done():
                    break
                body = builtin.written(line) + b"\n"
                await send({"type": "http.response.body", "body": body, "more_body": True})
        except OSError:
            pass  # the page went away mid-line: nothing is left to say to it
        finally:
            self.lines.close()
            gone.cancel()
            self.done()


async def _gone(receive: Receive) -> None:
    """Returns once the page has stopped waiting for its answer."""
    while (await receive())["type"] != "http.disconnect":
        pass


async def _body(request: Request, most: int, too_large: dict) -> bytes | Response:
    """What was sent, or the answer that says why it cannot be taken. A body longer than
    its kind of request has is refused before a byte of it is read, and one that does not
    say its length is refused at the byte that makes it too long."""
    closing = {"Connection": "close"}  # the body is not read, so the connection cannot be kept
    declared = request.headers.get("content-length")
    if declared is None and "transfer-encoding" not in request.headers:
        return b""
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            length = -1
        if length < 0:
            return said(request.headers, {"error": "the request does not say how long it is"}, 400, closing)
        if length > most:
            return said(request.headers, too_large, 422, closing)
    parts, size = [], 0
    pieces = request.stream()
    while True:
        # Each piece waited on for as long as a connection may say nothing, as the standard
        # library's server waits: a request that stops halfway holds nothing for ever.
        try:
            part = await asyncio.wait_for(anext(pieces), builtin.IDLE)
        except StopAsyncIteration:
            break
        except TimeoutError:
            return said(request.headers, STOPPED, 408, closing)
        except ClientDisconnect:
            # The page went away halfway: no fault, and the answer goes nowhere.
            return said(request.headers, STOPPED, 400, closing)
        size += len(part)
        if size > most:
            return said(request.headers, too_large, 422, closing)
        parts.append(part)
    return b"".join(parts)


async def _object(request: Request, most: int, too_large: dict, needed: bool = False) -> dict | Response:
    """The JSON object a request carries, or the answer that says why there is none. needed:
    a request with no body at all is refused, where one would otherwise stand for {}."""
    body = await _body(request, most, too_large)
    if isinstance(body, Response):
        return body
    if needed and not body:
        return said(request.headers, NO_DOC, 400)
    try:
        data = json.loads(body or b"{}")
    except (ValueError, RecursionError):
        return said(request.headers, {"error": "the request was not JSON"}, 400)
    if not isinstance(data, dict):
        return said(request.headers, {"error": "the request has to be a JSON object"}, 400)
    return data


def _file(path: str) -> tuple[int, bytes, str, str]:
    """A file of the built page; any other address is the page itself, which then shows the
    step the address names. An address that points out of the page's folder is one of those."""
    if path == "/robots.txt":
        return 200, builtin.ROBOTS, builtin.MIME[".txt"], "no-store"
    root = builtin.WEB_ROOT
    index = root / "index.html"
    try:
        target = (root / path.lstrip("/")).resolve()
        if path in ("/", "") or not target.is_file() or root.resolve() not in target.parents:
            target = index
    except (OSError, ValueError):  # a name no file can have
        target = index
    if not target.is_file():
        return 404, b"the page has not been built", builtin.MIME[".txt"], "no-store"
    kind = builtin.MIME.get(target.suffix, "application/octet-stream")
    return 200, target.read_bytes(), kind, builtin.cache_of(target)


class Service:
    """The requests of one workspace and one store, answered."""

    def __init__(self, workspace: Workspace, store: Store) -> None:
        self.workspace = workspace
        self.store = store
        self.streams = 0  # searches over sockets under way: counted on the one event loop
        self.session = Session(store)
        self.hub = shared.Hub(self.session)
        self.bench: Bench | None = None  # the agent's tools, set where the app is made
        self.chat: Any = None  # the page's chat, made at its first message

    async def __call__(self, request: Request) -> Response:
        """Any request but the WebSocket. A fault in here is the tool's, said as one."""
        try:
            return await self._answer(request)
        except Exception as fault:
            return said(request.headers, fault_of(fault, "a request"), 500)

    async def _answer(self, request: Request) -> Response:
        # The address as it was sent, before any reading of its escapes: it is compared
        # with the addresses of the service letter for letter, as the other server does.
        raw = request.scope.get("raw_path")
        path = raw.decode("latin-1") if raw else request.url.path
        method = request.method
        if method == "OPTIONS":
            return reply(request.headers, 204, b"", builtin.MIME[".txt"], {"Allow": ALLOW})
        if shared.handles(path):
            return await self._shared(request, method, path)
        if path in (SETTINGS, KEY) or path.startswith(STORE):
            return await self._kept(request, method, path)
        if method in ("GET", "HEAD"):
            return await self._get(request, path)
        if method == "POST":
            return await self._post(request, path)
        return said(request.headers, {"error": f"{method} is not answered at this address"}, 405, {"Allow": ALLOW})

    async def _get(self, request: Request, path: str) -> Response:
        if path == "/engine/mode.json":  # the page asks where its engine is: here
            return said(request.headers, {"server": True})
        if path == "/api/setup" or path.startswith("/api/device/"):
            status, body = await run_in_threadpool(routes.dispatch, path, {}, self.workspace)
            return said(request.headers, body, status)
        if path.startswith("/api/"):
            return said(request.headers, {"error": "no such address, or one that is posted to"}, 404)
        status, content, kind, cache = await run_in_threadpool(_file, path)
        return await run_in_threadpool(reply, request.headers, status, content, kind, {"Cache-Control": cache})

    async def _post(self, request: Request, path: str) -> Response:
        if path == "/api/read":
            return await self._read(request)
        if path == PHRASE:
            return await self._phrase(request)
        if path == PORT:
            return await self._port(request)
        streamed = path.endswith(builtin.STREAMED) and path.removesuffix(builtin.STREAMED) in routes.STREAMS
        if streamed:
            path = path.removesuffix(builtin.STREAMED)
        # Where the request is going is known before its body is read: one to nowhere is
        # answered at once, and never waited on.
        if not routes.known(path):
            return said(request.headers, {"error": "no such address"}, 404, {"Connection": "close"})
        data = await _object(request, *builtin.most(path))
        if isinstance(data, Response):
            return data
        if streamed:
            if self.streams >= MOST_STREAMS:
                return said(request.headers, busy(), 429)
            self.streams += 1
            return Lines(routes.stream(path, data, self.workspace), self._stream_done)
        status, body = await run_in_threadpool(routes.dispatch, path, data, self.workspace)
        return said(request.headers, body, status)

    async def _read(self, request: Request) -> Response:
        """A datasheet read: the one request that is a file, and a paid call."""
        pdf = await _body(request, builtin.MAX_BODY, builtin.TOO_LARGE)
        if isinstance(pdf, Response):
            return pdf
        query = request.scope.get("query_string", b"").decode("latin-1")
        name = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("name", "datasheet.pdf")
        work = lambda: builtin.read_datasheet(unquote(name), pdf, self.workspace, builtin.NO_KEY_SETTINGS)  # noqa: E731
        status, body = await run_in_threadpool(answer, work, "/api/read")
        return said(request.headers, body, status)

    async def _phrase(self, request: Request) -> Response:
        """A run's verdict phrased by the model set up for the reader: a paid call, so for
        this page alone, as the settings are. The verdict is judged here again from the
        figures sent, so what the model is given is only ever the engine's own findings."""
        own = {"Cross-Origin-Resource-Policy": "same-origin"}
        if not same_origin(request.headers):
            return said(request.headers, builtin.ONLY_LOCAL, 403, own)
        data = await _object(request, *builtin.most("/api/control/verdict"))
        if isinstance(data, Response):
            return data
        status, body = await run_in_threadpool(answer, lambda: self._phrased(data), PHRASE)
        return said(request.headers, body, status, own)

    async def _port(self, request: Request) -> Response:
        """The C export ported to a microcontroller by the model set up for the reader: a paid
        call, so for this page alone, as the settings are."""
        from motionsim.service.control import export_port
        from motionsim.service.validate import asked

        own = {"Cross-Origin-Resource-Policy": "same-origin"}
        if not same_origin(request.headers):
            return said(request.headers, builtin.ONLY_LOCAL, 403, own)
        data = await _object(request, *builtin.most("/api/control/export_c"))
        if isinstance(data, Response):
            return data

        def work() -> dict:
            asked("/api/control/export_c", data)
            return export_port.route(data, self.workspace)

        status, body = await run_in_threadpool(answer, work, PORT)
        return said(request.headers, body, status, own)

    def _phrased(self, data: dict) -> dict:
        from motionsim.control import verdict_phrase
        from motionsim.service.control.judging import verdict_of

        judged = verdict_of(data)

        def get(key: str) -> dict | None:
            try:
                return self.store.get(verdict_phrase.KIND, key)["doc"]
            except NotKept:
                return None

        def put(key: str, doc: dict) -> None:
            try:
                self.store.put(verdict_phrase.KIND, key, doc)
            except Refusal:
                # The store is full of phrasings: the oldest makes room, and one that still
                # cannot be kept is phrased again next time.
                kept = self.store.list(verdict_phrase.KIND)
                if kept:
                    self.store.delete(verdict_phrase.KIND, kept[-1]["id"])
                with contextlib.suppress(Refusal):
                    self.store.put(verdict_phrase.KIND, key, doc)

        return verdict_phrase.phrased(judged, get, put)

    async def _kept(self, request: Request, method: str, path: str) -> Response:
        """The settings and the store: what this machine keeps, for this page alone."""
        # Not to be loaded by a page of another origin, even unread.
        own = {"Cross-Origin-Resource-Policy": "same-origin"}
        if not same_origin(request.headers):
            return said(request.headers, builtin.ONLY_LOCAL, 403, own)
        work = await (
            self._settings(request, method, path) if path.startswith(SETTINGS) else self._stored(request, method, path)
        )
        if work is None:
            return said(request.headers, {"error": f"{method} is not answered at this address"}, 405, own)
        if isinstance(work, Response):
            return work
        try:
            status, body = await run_in_threadpool(answer, work, path, NotKept)
        except NotKept:
            status, body = 404, NOT_KEPT
        return said(request.headers, body, status, own)

    async def _settings(self, request: Request, method: str, path: str) -> Callable[[], object] | Response | None:
        """The work a request to the settings asks for, or its answer where that is already
        known, or None for a method the address does not take."""
        if path == SETTINGS:
            return keys.state if method in ("GET", "HEAD") else None
        if method == "DELETE":
            return _forgotten
        if method != "PUT":
            return None
        data = await _object(request, keys.MAX_REQUEST, TOO_LARGE_KEY)
        if isinstance(data, Response):
            return data
        return lambda: _saved(data.get("key"))

    async def _stored(self, request: Request, method: str, path: str) -> Callable[[], object] | Response | None:
        """The same, for the store: a kind lists what is kept of it, a kind and a name are
        one document, read, kept or taken away."""
        kind, *rest = path.removeprefix(STORE).split("/")
        if len(rest) > 1:
            return said(request.headers, {"error": "no such address"}, 404)
        if not rest:
            return (lambda: {"kind": kind, "items": self.store.list(kind)}) if method in ("GET", "HEAD") else None
        (name,) = rest
        if method in ("GET", "HEAD"):
            return lambda: self.store.get(kind, name)
        if kind in WRITTEN_HERE and method in ("PUT", "DELETE"):
            # What is kept of this kind is written by the app alone, from its own checks:
            # a document put here would be shown as if it had passed them.
            return said(request.headers, WRITTEN_HERE[kind], 403, {"Cross-Origin-Resource-Policy": "same-origin"})
        if method == "DELETE":
            return lambda: self._deleted(kind, name)
        if method != "PUT":
            return None
        doc = await _object(request, MAX_DOC, TOO_LARGE_DOC, needed=True)
        if isinstance(doc, Response):
            return doc
        return lambda: self.store.put(kind, name, doc)

    async def _shared(self, request: Request, method: str, path: str) -> Response:
        """The shared session, the agent's settings and what the agent exported: for this page alone."""
        own = {"Cross-Origin-Resource-Policy": "same-origin"}
        if not same_origin(request.headers):
            return said(request.headers, builtin.ONLY_LOCAL, 403, own)
        if path.startswith(shared.EXPORTS):
            if method not in ("GET", "HEAD"):
                return said(request.headers, {"error": f"{method} is not answered at this address"}, 405, own)
            name = unquote(path.removeprefix(shared.EXPORTS))
            found = await run_in_threadpool(shared.exported, name)
            if found is None:
                return said(request.headers, NOT_KEPT, 404, own)
            body, kind = found
            disposition = {"Content-Disposition": f'attachment; filename="{name}"'}
            return reply(request.headers, 200, body, kind, {**own, **disposition})
        writes = (path, method) in ((shared.SESSION, "PUT"), (shared.UNDO, "POST"))
        if writes and older(request.headers.get(BUILD_HEADER)):
            # A tab left open across an update: it would write the old page's idea of the design.
            return said(request.headers, OLDER, 409, own)
        work = await self._shared_work(request, method, path)
        if work is None:
            return said(request.headers, {"error": f"{method} is not answered at this address"}, 405, own)
        if isinstance(work, Response):
            return work
        status, answered = await run_in_threadpool(answer, work, path)
        return said(request.headers, answered, status, own)

    async def _shared_work(self, request: Request, method: str, path: str) -> Callable[[], object] | Response | None:
        if method in ("GET", "HEAD"):
            return self._shared_read(request, path)
        action = await self._shared_action(request, method, path)
        if action is not None:
            return action
        if (path, method) not in ((shared.SESSION, "PUT"), (shared.UNDO, "POST")):
            return None
        data = await _object(request, MAX_DOC + 4096, TOO_LARGE_DOC, needed=True)
        if isinstance(data, Response):
            return data
        named = data.get("client")
        client = named[:64] if isinstance(named, str) else ""
        field = "change" if path == shared.UNDO else "base"
        given = data.get(field)
        if path == shared.UNDO and (not isinstance(given, str) or not given):
            refused = {"refused": "no change was named", "fix": "send its id as change", "field": field}
            return said(request.headers, refused, 422)
        if path == shared.SESSION and given is not None and (isinstance(given, bool) or not isinstance(given, int)):
            refused = {"refused": "base is the version written on", "fix": "send it as a whole number", "field": field}
            return said(request.headers, refused, 422)
        if path == shared.UNDO:
            # Through the agent's own undo: a run kept or a file exported is taken back too.
            change = str(given)
            return lambda: self._undo(change, client)
        doc = data.get("doc")
        return lambda: _undone(self.session.write(doc, given, "page", client=client))  # type: ignore[arg-type]

    async def _shared_action(self, request: Request, method: str, path: str) -> Callable[[], object] | Response | None:
        """The agent's code made anew, or a message to the page's chat."""
        if (path, method) == (shared.NEW_CODE, "POST"):
            return lambda: (access.regenerate(), shared.agent_settings(request.headers))[1]
        if path == shared.CHAT and method in ("POST", "DELETE"):
            return await self._chat_work(request, method)
        return None

    async def _chat_work(self, request: Request, method: str) -> Callable[[], object] | Response:
        """A message to the page's chat, or the conversation forgotten."""
        if method == "DELETE":
            return lambda: (self._chatting().forget(), {"forgotten": True})[1]
        data = await _object(request, 4 * 4096, TOO_LARGE_DOC, needed=True)
        if isinstance(data, Response):
            return data
        message = data.get("message")
        if not isinstance(message, str):
            refused = {"refused": "no message was sent", "fix": "send it as message", "field": "message"}
            return said(request.headers, refused, 422)
        return lambda: self._chatting().ask(message)

    def _chatting(self) -> Any:
        """The chat, on a bench of its own over the shared session, its runs one at a time with the agent's."""
        if self.chat is None:
            from motionsim.app.agent import Bench
            from motionsim.app.chat import Chat

            bench = Bench(self.workspace, self.store, self.session)
            bench.source = "chat"
            if self.bench is not None:
                bench.running = self.bench.running
            self.chat = Chat(bench)
        return self.chat

    def _shared_read(self, request: Request, path: str) -> Callable[[], object] | None:
        if path == shared.AGENT:
            return lambda: shared.agent_settings(request.headers)
        if path == shared.ACTIVITY:
            return lambda: {"items": [shown(e) for e in self.session.activity(100)]}
        if path == shared.SESSION:
            return self.session.current
        if path == shared.CHAT:
            return lambda: self._chatting().ready()
        return None

    def _undo(self, change: str, client: str) -> dict:
        entry = self.session.entry(change)
        if entry.get("kind") == "action" and self.bench is not None:
            return {"undone": self.bench.undo(change), "change": None}
        return _undone(self.session.undo(change, client=client))

    def _stream_done(self) -> None:
        self.streams -= 1

    def _deleted(self, kind: str, name: str) -> dict:
        self.store.delete(kind, name)
        return {"deleted": True, "kind": kind, "id": name}

    async def socket(self, socket: WebSocket) -> None:
        """A search over a WebSocket. The page says once what it asks, {"route": an address
        of a search, "data": its request}; each step comes back as a message, and the answer
        last, as `stream` gives them. Closing the socket, or saying anything more, stops the
        search before its next step, and a step not yet begun is never begun."""
        await socket.accept()
        lines: Generator[dict, None, None] | None = None
        gone: asyncio.Future | None = None
        taken = False
        try:
            try:
                first = await asyncio.wait_for(socket.receive(), builtin.IDLE)
            except TimeoutError:
                return await socket.close(1008, "nothing was asked")
            asked = _asked(first)
            if isinstance(asked, tuple) and self.streams >= MOST_STREAMS:
                asked = {"status": 429, "body": busy()}
            if not isinstance(asked, tuple):
                if asked is not None:
                    await socket.send_text(builtin.written(asked).decode())
                return
            self.streams, taken = self.streams + 1, True
            lines = routes.stream(asked[0], asked[1], self.workspace)
            # The request is read whole: the next thing the page says is that it has gone.
            gone = asyncio.ensure_future(socket.receive())
            stopped = threading.Event()
            gone.add_done_callback(lambda _: stopped.set())
            while not gone.done():
                # A worker may be free only after the page has gone: the step is looked at
                # again there, before it begins.
                line = await run_in_threadpool(_step, lines, stopped)
                if line is None or gone.done():
                    break
                await socket.send_text(builtin.written(line).decode())
        except (OSError, RuntimeError, WebSocketDisconnect):
            pass  # the page went away mid-message: no fault, and nothing is left to say to it
        finally:
            if taken:
                self.streams -= 1
            if lines is not None:
                lines.close()
            if gone is not None:
                gone.cancel()
            with contextlib.suppress(OSError, RuntimeError, WebSocketDisconnect):
                await socket.close()


def _undone(result: dict) -> dict:
    """A write's answer as the page is sent it: its entry with long values said by their size."""
    return {**result, "change": shown(result["change"]) if result.get("change") else None}


def _step(lines: Generator[dict, None, None], stopped: threading.Event) -> dict | None:
    """The search's next step, or None where the page has gone or the search is done."""
    return None if stopped.is_set() else next(lines, None)


def _saved(key: object) -> dict:
    """Keep the key, and say how the settings now stand: never the key."""
    keys.save(key)
    return keys.state()


def _forgotten() -> dict:
    keys.forget()
    return keys.state()


def _asked(message: Mapping) -> tuple[str, dict] | dict | None:
    """What a WebSocket's first message asks: an address and its request; or the answer to
    one that asks nothing that can be read, as the page reads every answer; or None where
    the page has already gone."""
    if message.get("type") != "websocket.receive":
        return None
    text = message.get("text")
    if text is None:
        return {"status": 400, "body": {"error": "the request was not JSON"}}
    if len(text.encode()) > builtin.MAX_JSON:
        return {"status": 422, "body": builtin.TOO_LARGE_JSON}
    try:
        sent = json.loads(text)
    except (ValueError, RecursionError):
        return {"status": 400, "body": {"error": "the request was not JSON"}}
    data = sent.get("data", {}) if isinstance(sent, dict) else None
    if not isinstance(data, dict) or not isinstance(sent.get("route"), str):
        return {"status": 400, "body": {"error": 'the request has to be a JSON object: {"route": ..., "data": {...}}'}}
    return sent["route"], data


def create_app(workspace: Workspace | None = None, store: Store | None = None) -> FastAPI:
    """The app for one workspace and one store: by default the user's own, in MotionSim's
    folder. The same factory serves `motionsim serve`, the container and the tests."""
    if workspace is None or store is None:
        made(home())  # the user's alone before a device file, a document or a key is put in it
        access.code()  # the agent's access code, made at the first start and kept from then on
    service = Service(Workspace(devices()) if workspace is None else workspace, Store() if store is None else store)
    keys.use_saved()
    # The page's policy lets it load nothing but itself, so the pages of documentation FastAPI
    # would add could not draw, and their addresses belong to the page.
    from motionsim.app.agent import AgentGate, Bench, mounted

    bench = service.bench = Bench(service.workspace, service.store, service.session)
    handler, lifespan = mounted(bench)
    app = FastAPI(title="MotionSim", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    # Plain functions of this module, whose one argument FastAPI reads the kind of by name.
    async def page(request: Request) -> Response:
        return await service(request)

    async def stream(socket: WebSocket) -> None:
        await service.socket(socket)

    async def session(socket: WebSocket) -> None:
        await service.hub.serve(socket)

    app.add_api_websocket_route(SOCKET, stream)
    app.add_api_websocket_route(shared.SOCKET, session)
    # The answer is made here, whole: FastAPI is to make no model of it and change nothing in it.
    app.add_api_route("/{address:path}", page, methods=list(METHODS), response_model=None, include_in_schema=False)
    # The agent's /mcp inside the checks of where a request comes from, and outside the rest.
    app.add_middleware(AgentGate, handler=handler, bench=bench)
    app.add_middleware(OnlyLocal)
    return app
