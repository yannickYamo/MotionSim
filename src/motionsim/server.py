"""A local web page over the engine.

`motionsim serve` starts a small HTTP server on this machine. It serves the
built page and a JSON interface to the same functions the command line uses.
Nothing leaves the machine except a datasheet read, which is a call to the
language model made with the user's own key, and only when asked for.

The server holds no model of its own: every number comes from the engine.
Every request goes through the service's one dispatch, which also decides what
is a refusal and what is a fault; what is added here is HTTP.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import select
import socket
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from motionsim.device import save_device
from motionsim.errors import Refusal
from motionsim.files import MOST_BYTES
from motionsim.service.answers import RUNAWAY, answer, finite, without_paths
from motionsim.service.build import recommendations
from motionsim.service.motion import cycle
from motionsim.service.presets import setup
from motionsim.service.routes import ROUTES, STREAMS, call, dispatch, known, stream
from motionsim.service.validate import asked
from motionsim.service.verdict import proposal, speed_torque, stage
from motionsim.service.workspace import (
    EXAMPLE,
    Workspace,
    add_device,
    add_measurement,
    add_typed,
    curves,
    free_key,
)

# By the names this module has always handed on: the server is the service over HTTP.
Refused = Refusal
__all__ = [
    "EXAMPLE",
    "MAX_BODY",
    "MAX_JSON",
    "ROUTES",
    "RUNAWAY",
    "Handler",
    "Refused",
    "Server",
    "Workspace",
    "add_device",
    "add_measurement",
    "add_typed",
    "asked",
    "call",
    "curves",
    "cycle",
    "make_handler",
    "proposal",
    "read_datasheet",
    "recommendations",
    "serve",
    "setup",
    "speed_torque",
    "stage",
]

MAX_BODY = 40 * 1024 * 1024  # bytes; the largest request the page can send: a datasheet
MAX_JSON = 1024 * 1024  # bytes; the largest request of names and values, which is a few kilobytes
# Requests that carry a file's text inside their JSON: held to the size of such a file.
MAX_FILE_JSON = MOST_BYTES + MAX_JSON
CARRY_FILES = ("/api/device", "/api/measure")
# A board's design file, sent as its text or in base64: 30 MB of file (the board reader's own
# limit, motionsim.board.model.MOST_BYTES, which a test holds this to), a third more in
# base64, and the request's names around it.
MOST_BOARD = 30 * 1024 * 1024
MAX_BOARD_JSON = MOST_BOARD * 4 // 3 + MAX_JSON
BOARD = "/api/board"
# A search answered a step at a time is asked for at its own address with this after it.
STREAMED = "/stream"
IDLE = 30.0  # seconds a connection may say nothing before it is dropped
WEB_ROOT = Path(__file__).parent / "webui"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".wasm": "application/wasm",
    ".txt": "text/plain; charset=utf-8",
}
# What the page may load and talk to: itself. The engine in the browser is WebAssembly,
# the charts set styles inline, and small pictures come as data.
# The page's own policy (web/index.html), sent as a header, which a browser holds to before
# the page's first line: the same directives, less the runtime's address, which a page
# served from here never loads, and with no framing, which only a header can forbid.
POLICY = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
)
# A file of the built page named by what it holds (name-hash.ext, under assets/): a new build
# is new names, so the browser may keep one a year. Everything else, the page itself first,
# is never kept, or a new build would not be seen.
HASHED = re.compile(r"[\w.-]+-[\w-]{8}\.[a-z0-9]{1,8}")
KEPT = "public, max-age=31536000, immutable"


def cache_of(target: Path) -> str:
    """How long a browser may keep a file of the built page."""
    try:
        hashed = target.parent.resolve() == (WEB_ROOT / "assets").resolve() and HASHED.fullmatch(target.name)
    except (OSError, ValueError):
        hashed = None
    return KEPT if hashed else "no-store"


# A page on this machine is nobody's to index.
ROBOTS = b"User-agent: *\nDisallow: /\n"
ONLY_LOCAL = {"error": "this address answers only its own page"}
TOO_LARGE = {
    "refused": "that file is too large to be a datasheet",
    "fix": "datasheets are a few megabytes; check the file",
    "field": "",
}
TOO_LARGE_JSON = {
    "refused": "the request is too large to be one the page sends",
    "fix": "a request of figures is a few kilobytes: send the figures, not a file, or bring a file through its own box",
    "field": "",
}
TOO_LARGE_BOARD = {
    "refused": f"the board file is larger than {MOST_BOARD // (1024 * 1024)} MB, which is more than is read",
    "fix": "give the board of the power stage alone",
    "field": "board",
}


def most(path: str) -> tuple[int, dict]:
    """How large a request to an address may be, and what one larger is refused with."""
    if path == BOARD:
        return MAX_BOARD_JSON, TOO_LARGE_BOARD
    return (MAX_FILE_JSON if path in CARRY_FILES else MAX_JSON), TOO_LARGE_JSON


def _what_was_read(obs) -> dict:
    """How much was read from a datasheet, and each value or curve its checks flagged."""
    flagged = [
        {"what": o.quantity.value, "page": o.page, "why": "; ".join(o.flags)} for o in obs.observations if o.flags
    ] + [
        {"what": f"{c.label} ({c.quantity.value})", "page": c.page, "why": "; ".join(c.flags)}
        for c in obs.curves
        if c.flags
    ]
    return {
        "from_images": len(obs.document.transcribed),
        "values": len(obs.observations),
        "curves": len([c for c in obs.curves if not c.flags]),
        "flagged": flagged,
    }


NO_KEY = "set it in the shell that runs `motionsim serve`, then start it again"
# The app's page has Settings, where a key is set and read with at once.
NO_KEY_SETTINGS = "set the key under Settings, at the top of the page; or " + NO_KEY


def read_datasheet(name: str, body: bytes, workspace: Workspace, no_key: str = NO_KEY) -> dict:
    """Read a datasheet PDF and build its device model. A paid language-model call. no_key
    is what a refusal for want of a key says to do, which depends on where the key is set."""
    import warnings

    from motionsim.observe import provider, run

    try:
        run.ready()
        provider.chosen()
    except provider.NoReader as none:
        raise Refusal(str(none), no_key) from None
    if not body.startswith(b"%PDF"):
        raise Refusal("that file is not a PDF", "drop the datasheet's PDF file")
    from motionsim.fit import MissingData, build_device
    from motionsim.observe import save_observations

    # A key about to cross a network unencrypted: said in the terminal that runs the page
    # and handed to the page with the answer.
    said = [warning] if (warning := run.key_warning()) else []
    for line in said:
        log.warning("%s", line)
    # Never under the name of one of the made-up parts: a datasheet called example.pdf is
    # the user's part, and must not stand where the example does.
    key = free_key(re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-"), "datasheet")
    with tempfile.TemporaryDirectory() as folder:
        pdf = Path(folder) / f"{key}.pdf"
        pdf.write_bytes(body)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", provider.KeyInTheClear)  # said above, once
                reading = run.read_datasheet(pdf, say=lambda line: log.info("%s", line))
        except provider.NoReader as none:
            raise Refusal(str(none), no_key) from None
        except provider.ReaderRefused as exc:
            raise Refusal(str(exc), "try another datasheet") from None
        except provider.ReaderFailed as exc:
            # The reader's own one line: the service, the key or the file, with what to do
            # for that cause. Anything else that goes wrong in there is a fault of the tool,
            # and is reported as one.
            raise Refusal(
                f"the datasheet could not be read: {without_paths(str(exc))}",
                exc.fix or "check the key and the file, then try again",
            ) from None
    obs = reading.observations
    save_observations(obs, workspace.folder / f"{key}.observations.yaml")
    read = {**_what_was_read(obs), "summary": reading.summary(), "warnings": said}
    try:
        device = build_device(obs)
    except MissingData as exc:
        raise Refusal(
            f"the datasheet was read ({read['values']} values) but a model cannot be built: {exc}",
            "the values read are saved; this datasheet lacks something the model needs",
        ) from None
    save_device(device, workspace.folder / f"{key}.device.yaml")
    return {"device": workspace.summary(key, device), "read": read}


def written(payload: object) -> bytes:
    """An answer as it leaves: JSON, with every key this process holds taken out of it, as a
    service's error repeated in a refusal or a fault might hold one."""
    from motionsim.observe.provider import scrub

    return scrub(json.dumps(finite(payload))).encode()


def takes_gzip(accepted: str) -> bool:
    """Whether an Accept-Encoding header takes gzip: named (or as x-gzip) with a weight above
    nought, or, where it is not named, any coding taken by a * above nought (RFC 9110, 12.5.3)."""
    weights: dict[str, float] = {}
    for item in accepted.split(","):
        coding, *params = (part.strip() for part in item.split(";"))
        if not coding:
            continue
        q = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        weights[coding.lower()] = q
    for name in ("gzip", "x-gzip"):
        if name in weights:
            return weights[name] > 0
    return weights.get("*", 0.0) > 0


class Handler(BaseHTTPRequestHandler):
    """One request to the local page. The workspace is the server's."""

    server_version = "motionsim"
    sys_version = ""
    timeout = IDLE  # a connection that says nothing does not hold a thread for ever

    def version_string(self) -> str:  # the tool's name, and nothing about what runs it
        return self.server_version

    def log_message(self, *args) -> None:  # the terminal stays quiet
        pass

    @property
    def port(self) -> int:
        """The port this server answers on."""
        _, port = self.request.getsockname()[:2]
        return int(port)

    @property
    def workspace(self) -> Workspace:
        return self.server.workspace  # type: ignore[attr-defined]

    def _packed(self, body: bytes, kind: str) -> tuple[bytes, dict[str, str]]:
        """The body as it goes: text of more than a kilobyte is sent gzipped to a browser that
        takes it, as any host of the built page sends it, so the page opens as quickly here."""
        textual = kind.startswith(("text/", "application/json", "image/svg"))
        headers = getattr(self, "headers", None)  # none where the request's first line is not one
        takes = takes_gzip((headers.get("Accept-Encoding") if headers else "") or "")
        if not (textual and len(body) > 1024):
            return body, {}
        if not takes:
            return body, {"Vary": "Accept-Encoding"}
        return gzip.compress(body, compresslevel=6, mtime=0), {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"}

    def _send(self, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None) -> None:
        body, packing = self._packed(body, kind)
        extra = {**packing, **(extra or {})}
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", extra.pop("Cache-Control", "no-store"))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", POLICY)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200, extra: dict[str, str] | None = None) -> None:
        self._send(status, written(payload), "application/json", extra)

    def _local(self) -> bool:
        """Only this machine's own page may talk to the engine.

        Another site open in the same browser could otherwise post to this
        address, and a datasheet read spends the user's own key. The Host
        header must name this machine, and a request that says where it came
        from must have come from this page.
        """
        port = self.port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in allowed:
            return False
        # The whole origin, its scheme too: this page is served over plain HTTP, and a page of
        # the same name and port served any other way is not it.
        return origin is None or origin in {f"http://{host}" for host in allowed}

    def _file(self, path: str) -> None:
        """A file of the built page; any other address is the page itself, which then
        shows the step the address names."""
        if path == "/robots.txt":
            return self._send(200, ROBOTS, MIME[".txt"])
        try:
            target = (WEB_ROOT / path.lstrip("/")).resolve()
            found = target.is_file()
        except (OSError, ValueError):  # a name the file system does not take is no file here
            found = False
        if path in ("/", "") or not found or WEB_ROOT.resolve() not in target.parents:
            target = WEB_ROOT / "index.html"
        if not target.is_file():
            return self._send(HTTPStatus.NOT_FOUND, b"the page has not been built", MIME[".txt"])
        kind = MIME.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), kind, {"Cache-Control": cache_of(target)})

    def do_GET(self) -> None:
        if not self._local():
            return self._json(ONLY_LOCAL, 403)
        path = self.path.split("?")[0]
        if path == "/engine/mode.json":  # the page asks where its engine is: here
            return self._json({"server": True})
        if path == "/api/setup" or path.startswith("/api/device/"):
            status, body = dispatch(path, {}, self.workspace)
            return self._json(body, status)
        if path.startswith("/api/"):
            return self._json({"error": "no such address, or one that is posted to"}, 404)
        self._file(path)

    do_HEAD = do_GET  # the same headers, and no body: see _send

    def do_OPTIONS(self) -> None:
        if not self._local():
            return self._json(ONLY_LOCAL, 403)
        self._send(204, b"", MIME[".txt"], {"Allow": "GET, HEAD, POST, OPTIONS"})

    def _not_taken(self) -> None:
        """A method no address of this server takes, said as the app says it, with the body
        left unread and so the connection ended."""
        if not self._local():
            return self._json(ONLY_LOCAL, 403)
        self.close_connection = True
        self._json(
            {"error": f"{self.command} is not answered at this address"},
            405,
            {"Allow": "GET, HEAD, POST, OPTIONS", "Connection": "close"},
        )

    do_PUT = do_DELETE = do_PATCH = _not_taken

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """A request the standard library itself turns away (a method it has no handler for,
        a line it cannot read) answered as every answer of the page is: in JSON, with the
        headers that keep a browser strict."""
        self.close_connection = True
        try:
            phrase = HTTPStatus(code).phrase
        except ValueError:
            phrase = "the request cannot be answered"
        self._json({"error": message or phrase}, code, {"Connection": "close"})

    def _body(self, most: int, too_large: dict) -> bytes | None:
        """What was posted, or None once the reason it cannot be taken has been sent. A body
        longer than its kind of request has is refused before a byte of it is read."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._json({"error": "the request does not say how long it is"}, 400)
            return None
        if length > most:
            self.close_connection = True  # the body is not read, so the connection cannot be kept
            self._json(too_large, 422, {"Connection": "close"})
            return None
        return self.rfile.read(length)

    def do_POST(self) -> None:
        if not self._local():
            return self._json(ONLY_LOCAL, 403)
        path, _, query = self.path.partition("?")
        if path == "/api/read":
            body = self._body(MAX_BODY, TOO_LARGE)
            if body is None:
                return None
            pdf: bytes = body
            name = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("name", "datasheet.pdf")
            status, said = answer(lambda: read_datasheet(unquote(name), pdf, self.workspace), path)
            return self._json(said, status)
        streamed = path.endswith(STREAMED) and path.removesuffix(STREAMED) in STREAMS
        if streamed:
            path = path.removesuffix(STREAMED)
        # Where the request is going is known before its body is read: one to nowhere is
        # answered at once, and never waited on.
        if not known(path):
            self.close_connection = True
            return self._json({"error": "no such address"}, 404)
        body = self._body(*most(path))
        if body is None:
            return None
        try:
            data = json.loads(body or b"{}")
        except (ValueError, RecursionError):
            return self._json({"error": "the request was not JSON"}, 400)
        if not isinstance(data, dict):
            return self._json({"error": "the request has to be a JSON object"}, 400)
        if streamed:
            return self._stream(path, data)
        status, said = dispatch(path, data, self.workspace)
        self._json(said, status)

    def _gone(self) -> bool:
        """Whether the page has stopped waiting: its request is read whole, so anything the
        connection has to say now is that it was closed."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _stream(self, path: str, data: dict) -> None:
        """A search answered a line at a time, each line a JSON object: a step as it finishes,
        then the answer. A page that stops waiting stops the search before its next step."""
        self.close_connection = True  # the answer's end is the connection's
        self.send_response(200)
        for name, value in (
            ("Content-Type", "application/x-ndjson"),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", POLICY),
            ("Connection", "close"),
        ):
            self.send_header(name, value)
        self.end_headers()
        lines = stream(path, data, self.workspace)
        try:
            for line in lines:
                if self._gone():
                    break
                self.wfile.write(written(line) + b"\n")
                self.wfile.flush()
        except (ConnectionError, TimeoutError):
            pass  # the page went away mid-line: nothing is left to say to it
        finally:
            lines.close()


class Server(ThreadingHTTPServer):
    """The local server, with the workspace its requests are answered from."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], workspace: Workspace, handler: type = Handler) -> None:
        self.workspace = workspace
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, handler)

    def handle_error(self, request, client_address) -> None:
        """A page closed or reloaded while its answer was on the way is not a fault: nothing
        is printed for it. Anything else is logged with where it happened."""
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        log.exception("fault serving a request")


def make_handler(workspace: Workspace) -> type[Handler]:
    """The handler for one workspace, for a server built by hand."""
    return type("Handler", (Handler,), {"workspace": workspace})


# Faults and timings only: never a device file, a datasheet's content or a key.
log = logging.getLogger("motionsim")


def serve(port: int = 4310, folder: str | Path | None = None, open_browser: bool = True) -> None:
    workspace = Workspace(Path(folder) if folder else Path.home() / ".motionsim" / "devices")
    httpd = Server(("127.0.0.1", port), workspace)
    address = f"http://127.0.0.1:{httpd.server_address[1]}/"
    # Said at once, also where the output is a pipe: whoever started this waits for the line.
    print(f"motionsim is at {address}  (devices in {workspace.folder}; Ctrl+C to stop)", flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(address)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
