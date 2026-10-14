"""A local web page over the engine.

`motionsim serve` starts a small HTTP server on this machine. It serves the
built page and a JSON interface to the same functions the command line uses.
Nothing leaves the machine except a datasheet read, which is a call to the
language model made with the user's own key, and only when asked for.

The server holds no model of its own: every number comes from the engine.
What it adds is the shape the page needs, and the reason and the fix when an
input cannot work.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from motionsim.device import save_device
from motionsim.engine import ThermalRunaway
from motionsim.page import (  # noqa: F401  (re-exported: the server is the page's interface over HTTP)
    EXAMPLE,
    ROUTES,
    RUNAWAY,
    UNWORKABLE,
    Refused,
    Workspace,
    add_device,
    add_measurement,
    add_typed,
    asked,
    call,
    curves,
    cycle,
    finite,
    proposal,
    recommendations,
    setup,
    speed_torque,
    stage,
    unworkable,
)

MAX_BODY = 40 * 1024 * 1024  # bytes; the largest request the page can send
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
}


def read_datasheet(name: str, body: bytes, workspace: Workspace) -> dict:
    """Read a datasheet PDF and build its device model. A paid language-model call."""
    from motionsim.observe import provider

    try:
        provider.chosen()
    except provider.NoReader as none:
        raise Refused(str(none), "set it in the shell that runs `motionsim serve`, then start it again") from None
    if not body.startswith(b"%PDF"):
        raise Refused("that file is not a PDF", "drop the datasheet's PDF file")
    from motionsim.fit import MissingData, build_device
    from motionsim.observe import save_observations
    from motionsim.observe.digitise import digitise_curves  # needs the PDF libraries: only when a datasheet is read
    from motionsim.observe.reader import ReaderRefused, read_document, read_tables, reader_name
    from motionsim.observe.verify import check

    key = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-") or "datasheet"
    with tempfile.TemporaryDirectory() as folder:
        pdf = Path(folder) / f"{key}.pdf"
        pdf.write_bytes(body)
        try:
            document, pages = read_document(pdf)
            obs = check(read_tables(pages), document, pages, reader=reader_name())
            obs.curves = digitise_curves(str(pdf), obs)
        except ReaderRefused as exc:
            raise Refused(str(exc), "try another datasheet") from None
        except (
            Exception
        ) as exc:  # the reader, the model call or the PDF: whatever it was, the user is told and it is kept
            log.exception("reading a datasheet failed (%s)", type(exc).__name__)
            raise Refused(
                f"the datasheet could not be read: {exc}", "check the key and the file, then try again"
            ) from None
    save_observations(obs, workspace.folder / f"{key}.observations.yaml")
    flagged = [
        {"what": o.quantity.value, "page": o.page, "why": "; ".join(o.flags)} for o in obs.observations if o.flags
    ] + [
        {"what": f"{c.label} ({c.quantity.value})", "page": c.page, "why": "; ".join(c.flags)}
        for c in obs.curves
        if c.flags
    ]
    read = {
        "from_images": len(obs.document.transcribed),
        "values": len(obs.observations),
        "curves": len([c for c in obs.curves if not c.flags]),
        "flagged": flagged,
    }
    try:
        device = build_device(obs)
    except MissingData as exc:
        raise Refused(
            f"the datasheet was read ({read['values']} values) but a model cannot be built: {exc}",
            "the values read are saved; this datasheet lacks something the model needs",
        ) from None
    save_device(device, workspace.folder / f"{key}.device.yaml")
    return {"device": workspace.summary(key, device), "read": read}


def make_handler(workspace: Workspace):
    class Handler(BaseHTTPRequestHandler):
        server_version = "motionsim"

        def log_message(self, *args) -> None:  # the terminal stays quiet
            pass

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(finite(payload)).encode(), "application/json")

        def _guarded(self, work) -> None:
            try:
                self._json(work())
            except Refused as exc:
                self._json({"refused": exc.reason, "fix": exc.fix, "field": exc.field}, 422)
            except ThermalRunaway:
                self._json(RUNAWAY, 422)
            except OverflowError:
                self._json(
                    {
                        "refused": "a figure is too large or too small to work with",
                        "fix": "check the figures given",
                        "field": "",
                    },
                    422,
                )
            except UNWORKABLE as exc:
                log.info("refused %s: %r", self.path.split("?")[0], exc)
                self._json(unworkable(exc), 422)
            except Exception as exc:  # a fault of ours: say so plainly, keep serving, keep where it happened
                log.exception("fault answering %s", self.path.split("?")[0])
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _local(self) -> bool:
            """Only this machine's own page may talk to the engine.

            Another site open in the same browser could otherwise post to this
            address, and a datasheet read spends the user's own key. The Host
            header must name this machine, and a request that says where it came
            from must have come from this page.
            """
            allowed = {f"127.0.0.1:{self.server.server_address[1]}", f"localhost:{self.server.server_address[1]}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in allowed:
                return False
            return origin is None or origin.split("://", 1)[-1] in allowed

        def do_GET(self) -> None:
            if not self._local():
                return self._json({"error": "this address answers only its own page"}, 403)
            path = self.path.split("?")[0]
            if path == "/engine/mode.json":  # the page asks where its engine is: here
                return self._json({"server": True})
            if path == "/api/setup":
                return self._guarded(lambda: setup(workspace))
            if path.startswith("/api/device/"):
                return self._guarded(lambda: curves(path.rsplit("/", 1)[1], workspace))
            if path.startswith("/api/"):
                return self._json({"error": "no such address, or one that is posted to"}, 404)
            target = (WEB_ROOT / path.lstrip("/")).resolve()
            if path in ("/", "") or not target.is_file() or WEB_ROOT.resolve() not in target.parents:
                target = WEB_ROOT / "index.html"
            if not target.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"the page has not been built", "text/plain")
            self._send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

        def do_POST(self) -> None:
            if not self._local():
                return self._json({"error": "this address answers only its own page"}, 403)
            path, _, query = self.path.partition("?")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                return self._json({"error": "the request does not say how long it is"}, 400)
            if length > MAX_BODY:
                return self._json(
                    {
                        "refused": "that file is too large to be a datasheet",
                        "fix": "datasheets are a few megabytes; check the file",
                        "field": "",
                    },
                    422,
                )
            body = self.rfile.read(length)
            if path == "/api/read":
                name = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("name", "datasheet.pdf")
                from urllib.parse import unquote

                return self._guarded(lambda: read_datasheet(unquote(name), body, workspace))
            if path not in ROUTES and path not in ("/api/device", "/api/measure", "/api/typed"):
                return self._json({"error": "no such address"}, 404)
            try:
                data = json.loads(body or b"{}")
            except (ValueError, RecursionError):
                return self._json({"error": "the request was not JSON"}, 400)
            if not isinstance(data, dict):
                return self._json({"error": "the request has to be a JSON object"}, 400)
            if path == "/api/device":
                return self._guarded(lambda: add_device(data.get("name", ""), data.get("text", ""), workspace))
            if path == "/api/typed":
                return self._guarded(lambda: add_typed(data.get("figures"), workspace))
            if path == "/api/measure":
                return self._guarded(
                    lambda: add_measurement(
                        data.get("device", ""), data.get("name", ""), data.get("text", ""), workspace
                    )
                )

            def answer():
                asked(path, data)  # a request that lacks what its address needs is refused in words
                return ROUTES[path](data, workspace)

            self._guarded(answer)

    return Handler


# Faults and timings only: never a device file, a datasheet's content or a key.
log = logging.getLogger("motionsim")


def serve(port: int = 4310, folder: str | Path | None = None, open_browser: bool = True) -> None:
    workspace = Workspace(Path(folder) if folder else Path.home() / ".motionsim" / "devices")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(workspace))
    address = f"http://127.0.0.1:{port}/"
    print(f"motionsim is at {address}  (devices in {workspace.folder}; Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        webbrowser.open(address)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
