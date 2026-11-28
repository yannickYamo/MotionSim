"""The ASGI app over the service: every address answers through it as the service's one
dispatch answers, and as the standard library's server does, with the same statuses, bodies
and headers; and a request that is wrong is held to the same bounds."""

from __future__ import annotations

import gzip
import http.client
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")
pytest.importorskip("wsproto", reason="the ASGI app needs the app extra")

from motionsim import server
from motionsim.app import home, run
from motionsim.app.server import create_app
from motionsim.app.store import Store
from motionsim.observe import provider
from motionsim.service import routes
from motionsim.service.answers import finite

# The headers that keep a browser strict, and the ones that say how the body is packed.
HELD = ("content-type", "cache-control", "x-content-type-options", "content-security-policy", "server")
PACKING = ("content-encoding", "vary")
# Minutes of engine each, where what is compared here is the adapter and not the engine:
# these are asked without a device, and are refused the same through both.
SLOW = ("/api/capability", "/api/event", "/api/load-proposal", "/api/recommend", "/api/report")


class Served:
    """A server on a port of its own, and one request to it."""

    def __init__(self, port: int) -> None:
        self.port = port

    def ask(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        """The status, the headers by their names in small letters, and the body."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            sent = {k.lower(): v for k, v in (headers or {}).items()}
            # Only what the test says is sent: one Host, its own where it names one.
            connection.putrequest(method, path, skip_host="host" in sent, skip_accept_encoding=True)
            if body is not None and "content-length" not in sent:
                sent["content-length"] = str(len(body))
            for name, value in sent.items():
                connection.putheader(name, value)
            connection.endheaders()
            if body:
                connection.send(body)
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def json(self, method: str, path: str, payload=None, headers: dict | None = None) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload).encode()
        status, _, said = self.ask(method, path, body, headers)
        return status, json.loads(said)


@contextmanager
def served(folder: Path):
    """The ASGI app run by uvicorn as `motionsim serve` runs it, on any free port, with a
    workspace and a store in the folder given."""
    import uvicorn

    listener = run.listening("127.0.0.1", 0)
    app = create_app(server.Workspace(folder / "devices"), Store(folder / "motionsim.db"))
    uvi = uvicorn.Server(run.config(app))
    thread = threading.Thread(target=uvi.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        yield Served(listener.getsockname()[1])
    finally:
        uvi.should_exit = True
        thread.join(timeout=20)
        listener.close()


@contextmanager
def builtin(folder: Path):
    """The standard library's server, to answer the same requests beside it."""
    httpd = server.Server(("127.0.0.1", 0), server.Workspace(folder / "devices"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Served(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    """Nothing of the user's own is read or written: MotionSim's folder is the test's, and
    the reader's lookup of a saved key is put back when the test is over."""
    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    monkeypatch.setattr(provider, "saved_key", provider.saved_key)


@pytest.fixture
def app(tmp_path):
    with served(tmp_path / "asgi") as running:
        yield running


@pytest.fixture
def both(tmp_path):
    with served(tmp_path / "asgi") as asgi, builtin(tmp_path / "builtin") as stdlib:
        yield asgi, stdlib


def requests_of(route: str) -> list[dict]:
    """Requests that stand for what the page sends an address: one with nothing in it, one
    with a motor and its conditions, and one that names the made-up part as well."""
    kinds = server.setup(server.Workspace(Path("unused")))["motors"]
    design = {
        "motor": {"type": "pmsm", **kinds["pmsm"]["values"]},
        "conditions": {**kinds["pmsm"]["start"], "t_sink": 60},
    }
    part = {**design, "devices": ["example"], "device": "example"}
    own = {
        "/api/loads": [{"kind": "pmsm", "rpm": 1000, "torque": 1}, {"kind": ["pmsm"], "rpm": 1000, "torque": 1}],
        "/api/stage": [{**design, "conditions": {**design["conditions"], "v_dc": "a lot"}}],
        "/api/compare": [{"devices": ["example"] * 6, "conditions": {}, "motor": {}}],
        "/api/device": [{"name": "part.yaml", "text": "not: a device"}],
    }
    return [{}, design, *([] if route in SLOW else [part]), *own.get(route, [])]


@pytest.mark.parametrize("route", sorted({**routes.ROUTES, **routes.ADDING}))
def test_every_address_answers_through_the_app_as_dispatch_answers(app, tmp_path, route) -> None:
    """The addresses are read from the service's own tables, so one added there is held to
    this as soon as it is added."""
    apart = server.Workspace(tmp_path / "apart" / "devices")
    seen = set()
    for request in requests_of(route):
        status, body = app.json("POST", route, request)
        own_status, own_body = routes.dispatch(route, request, apart)
        assert (status, body) == (own_status, json.loads(json.dumps(finite(own_body)))), request
        seen.add(status)
    assert seen <= {200, 422}


def test_the_addresses_that_are_read_answer_as_dispatch_answers(app, tmp_path) -> None:
    apart = server.Workspace(tmp_path / "apart" / "devices")
    for path in ("/api/setup", "/api/device/example", "/api/device/no-such-part"):
        status, body = app.json("GET", path)
        own_status, own_body = routes.dispatch(path, {}, apart)
        assert (status, body) == (own_status, json.loads(json.dumps(finite(own_body)))), path
    assert app.json("GET", "/api/device/no-such-part")[0] == 422


def test_a_refusal_is_422_with_its_reason_its_fix_and_its_figure(app) -> None:
    status, body = app.json("POST", "/api/stage", {})
    assert status == 422
    assert body == {
        "refused": "the request has no motor, or it is not a set of names and values",
        "fix": "give the motor",
        "field": "motor",
    }


def test_an_address_nothing_answers_at_is_404(app) -> None:
    assert app.json("POST", "/api/nothing", {}) == (404, {"error": "no such address"})
    assert app.json("GET", "/api/nothing") == (404, {"error": "no such address, or one that is posted to"})
    assert app.json("GET", "/api/stage")[0] == 404  # one that is posted to
    assert app.json("POST", "/api/stage/stream", {})[0] == 404  # not a search


def test_a_fault_is_500_with_no_path_in_it_and_the_app_goes_on(app, monkeypatch, caplog) -> None:
    def broken(data, ws):
        raise RuntimeError("could not open /home/someone/secret/table.npy")

    monkeypatch.setitem(routes.ROUTES, "/api/suggest", broken)
    status, body = app.json("POST", "/api/suggest", {"device": "example"})
    assert status == 500 and body == {"error": "RuntimeError: could not open table.npy"}
    assert any("fault answering /api/suggest" in r.getMessage() and r.exc_info for r in caplog.records)
    assert app.ask("GET", "/api/setup")[0] == 200


def test_an_address_added_to_the_service_later_is_answered_with_no_change_here(app, monkeypatch) -> None:
    """As the control lab's addresses will be: put in the service's tables, and nowhere else."""
    monkeypatch.setitem(routes.ROUTES, "/api/control/step", lambda data, ws: {"echo": data, "nan": float("nan")})
    assert app.json("POST", "/api/control/step", {"kp": 0.4}) == (200, {"echo": {"kp": 0.4}, "nan": None})
    monkeypatch.setitem(routes.ADDING, "/api/control/scheme", lambda data, ws: {"added": True})
    assert app.json("POST", "/api/control/scheme", {}) == (200, {"added": True})


REQUESTS = [
    ("GET", "/", None, {}),
    ("GET", "/", None, {"Accept-Encoding": "gzip, deflate, br"}),
    ("HEAD", "/", None, {}),
    ("GET", "/robots.txt", None, {"Accept-Encoding": "gzip"}),
    ("GET", "/a/step/of/the/page", None, {}),
    ("GET", "/engine/mode.json", None, {}),
    ("GET", "/api/setup", None, {}),
    ("GET", "/api/setup?x=1", None, {"Accept-Encoding": "gzip"}),
    ("GET", "/api/setup", None, {"Accept-Encoding": "gzip;q=0, identity"}),
    ("HEAD", "/api/setup", None, {"Accept-Encoding": "br, *;q=0.1"}),
    ("GET", "/api/device/example", None, {}),
    ("GET", "/api/device/no-such-part", None, {}),
    ("GET", "/api/nothing", None, {}),
    ("GET", "/api/stage", None, {}),
    ("POST", "/api/stage", b"{}", {"Content-Type": "application/json"}),
    ("POST", "/api/stage", b"", {}),
    ("POST", "/api/stage", b"{not json", {}),
    ("POST", "/api/stage", b"[1, 2]", {}),
    ("POST", "/api/stage", b'"text"', {}),
    ("POST", "/api/stage?x=1", b"{}", {}),
    ("POST", "/api/nothing", b"{}", {}),
    ("POST", "/api/nowhere", None, {"Content-Length": str(30 * 1024 * 1024)}),
    ("POST", "/api/stage", None, {"Content-Length": str(server.MAX_JSON + 1)}),
    ("POST", "/api/typed", None, {"Content-Length": str(server.MAX_JSON + 1)}),
    ("POST", "/api/read", None, {"Content-Length": str(server.MAX_BODY + 1)}),
    ("POST", "/api/read?name=sheet.pdf", b"not a pdf", {}),
    ("POST", "/api/loads", b'{"kind": "pmsm", "rpm": 1000, "torque": 1}', {}),
    ("POST", "/api/largest/stream", b"{}", {}),
    ("POST", "/api/stage/stream", b"{}", {}),
    ("GET", "/api/setup", None, {"Host": "elsewhere.example"}),
    ("GET", "/", None, {"Host": "elsewhere.example"}),
    ("GET", "/api/setup", None, {"Origin": "http://elsewhere.example"}),
    ("POST", "/api/stage", b"{}", {"Origin": "http://elsewhere.example"}),
    ("OPTIONS", "/api/stage", None, {"Origin": "http://elsewhere.example"}),
    ("POST", "/api/stage", b"{}", {"Origin": "null"}),
    ("PUT", "/api/stage", b"{}", {}),
    ("DELETE", "/api/setup", None, {}),
    ("PATCH", "/", b"{}", {}),
    ("PUT", "/api/stage", b"{}", {"Host": "elsewhere.example"}),
    ("DELETE", "/", None, {"Origin": "http://elsewhere.example"}),
]


@pytest.mark.parametrize(("method", "path", "body", "headers"), REQUESTS)
def test_the_app_answers_as_the_standard_librarys_server_does(both, monkeypatch, method, path, body, headers) -> None:
    """Status, body, the headers that keep a browser strict and the packing of the body:
    the page cannot tell which of the two serves it. (Where a key is set is the one thing
    each says in its own way: see the test of a read with no reader set up.)"""
    monkeypatch.setattr(server, "NO_KEY_SETTINGS", server.NO_KEY)
    asgi, stdlib = both
    status, said, content = asgi.ask(method, path, body, headers)
    was_status, was_said, was_content = stdlib.ask(method, path, body, headers)
    assert (status, content) == (was_status, was_content)
    assert {name: said.get(name) for name in (*HELD, *PACKING)} == {
        name: was_said.get(name) for name in (*HELD, *PACKING)
    }
    assert said.get("content-length") == was_said.get("content-length")


def test_a_datasheet_read_with_no_reader_set_up_is_refused_the_same_and_asks_no_model(both, monkeypatch) -> None:
    for name in (*provider.SETS_UP, "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    # The reader's own libraries may or may not be installed here: what is asked is the key.
    monkeypatch.setattr("motionsim.observe.run.ready", lambda: None)
    monkeypatch.setattr("motionsim.observe.run.read_datasheet", lambda *a, **k: pytest.fail("no model is asked"))
    asgi, stdlib = both
    answers = [s.json("POST", "/api/read?name=my%20part.pdf", None, {"Content-Length": "0"}) for s in (asgi, stdlib)]
    assert answers[0][0] == answers[1][0] == 422
    assert answers[0][1]["refused"] == answers[1][1]["refused"] and "needs a language model" in answers[0][1]["refused"]
    # The app has Settings, where the key is set with no restart: that is said first. The
    # standard library's server has none, and the shell is the one place.
    assert answers[0][1]["fix"].startswith("set the key under Settings")
    assert "Settings" not in answers[1][1]["fix"] and "shell" in answers[1][1]["fix"]


def test_a_datasheet_goes_to_the_reader_whole_under_its_own_name(app, monkeypatch) -> None:
    """The reader is a stub: what is held to here is that the file and its name reach it."""
    seen = {}

    def read(name, body, workspace, no_key=server.NO_KEY):
        seen.update(name=name, body=body)
        return {"device": {"id": "my-part"}, "read": {"values": 3}}

    monkeypatch.setattr(server, "read_datasheet", read)
    pdf = b"%PDF-1.4 " + bytes(range(256)) * 4096  # a megabyte, of every byte there is
    status, _, said = app.ask("POST", "/api/read?name=my%20part.pdf&x=1", pdf)
    assert status == 200 and json.loads(said) == {"device": {"id": "my-part"}, "read": {"values": 3}}
    assert seen == {"name": "my part.pdf", "body": pdf}


def test_a_body_that_does_not_say_its_length_is_refused_at_the_byte_that_makes_it_too_long(app) -> None:
    """Sent in pieces with no length said, as a browser never does and a script may: it is
    taken up to the size its kind of request has, and no further."""
    connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=60)
    try:
        connection.putrequest("POST", "/api/stage")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.endheaders()
        piece = b"x" * 65536
        try:
            for _ in range(server.MAX_JSON // len(piece) + 2):
                connection.send(b"%x\r\n%s\r\n" % (len(piece), piece))
        except OSError:
            pass  # refused and closed while the rest was still being sent
        response = connection.getresponse()
        assert response.status == 422 and json.loads(response.read()) == server.TOO_LARGE_JSON
    finally:
        connection.close()


def test_a_request_that_is_refused_unread_ends_its_connection(app) -> None:
    """The body was not read, so nothing that follows on the connection could be told from it."""
    for path, headers in (
        ("/api/stage", {"Content-Length": str(server.MAX_JSON + 1)}),
        ("/api/nowhere", {"Content-Length": "100"}),
    ):
        assert app.ask("POST", path, None, headers)[1]["connection"] == "close"


def test_a_request_in_pieces_within_its_size_is_answered(app) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", app.port, timeout=60)
    try:
        connection.request("POST", "/api/loads", iter([b'{"kind": "pmsm", ', b'"rpm": 1000, "torque": 1}']))
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["loads"]
    finally:
        connection.close()


def test_a_request_that_brings_a_file_may_be_as_large_as_the_file(app) -> None:
    text = "x" * (server.MAX_JSON + 1000)
    status, body = app.json("POST", "/api/device", {"name": "part.yaml", "text": text})
    assert status == 422 and "too large" not in body["refused"]


def test_the_page_is_served_with_the_headers_that_keep_a_browser_strict(app) -> None:
    for method, path in (("GET", "/"), ("GET", "/api/setup"), ("GET", "/api/nothing"), ("GET", "/robots.txt")):
        _, headers, _ = app.ask(method, path)
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["content-security-policy"] == server.POLICY
        # The tool's name, and nothing of what runs it.
        assert headers["server"] == "motionsim"
        assert headers["cache-control"] == "no-store"
    status, headers, body = app.ask("GET", "/")
    assert status == 200 and headers["content-type"] == "text/html; charset=utf-8"
    assert body == (server.WEB_ROOT / "index.html").read_bytes()


def test_a_file_of_the_page_goes_gzipped_to_a_browser_that_takes_it(app) -> None:
    script = max(server.WEB_ROOT.glob("assets/*.js"), key=lambda p: p.stat().st_size)
    status, headers, body = app.ask("GET", f"/assets/{script.name}", headers={"Accept-Encoding": "gzip"})
    assert status == 200 and headers["content-type"] == "text/javascript; charset=utf-8"
    assert headers["content-encoding"] == "gzip" and int(headers["content-length"]) == len(body)
    assert gzip.decompress(body) == script.read_bytes()


@pytest.mark.parametrize(
    "path",
    [
        "/../pyproject.toml",
        "/../../../../../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/..%2f..%2fetc/passwd",
        "/assets/../../server.py",
        "//etc/passwd",
        "/assets/..\\..\\server.py",
        "/" + "a" * 5000,
    ],
)
def test_an_address_that_points_out_of_the_pages_folder_gets_the_page_and_nothing_else(app, path) -> None:
    status, headers, body = app.ask("GET", path)
    assert status == 200 and headers["content-type"] == "text/html; charset=utf-8"
    assert body == (server.WEB_ROOT / "index.html").read_bytes()


def test_a_file_beside_the_pages_folder_is_never_served(app, tmp_path, monkeypatch) -> None:
    """A folder whose name begins as the page's does is not the page's: what is served is
    held to the folder itself, and a link out of it is followed to where it really is."""
    root = tmp_path / "webui"
    root.mkdir()
    (root / "index.html").write_text("the page")
    (tmp_path / "webui-private").mkdir()
    (tmp_path / "webui-private" / "secret.txt").write_text("a secret")
    (tmp_path / "secret.txt").write_text("a secret")
    (root / "out.txt").symlink_to(tmp_path / "secret.txt")
    monkeypatch.setattr(server, "WEB_ROOT", root)
    for path in ("/../webui-private/secret.txt", "/../secret.txt", "/out.txt"):
        assert app.ask("GET", path)[2] == b"the page", path


def test_only_this_machines_own_page_is_answered(app) -> None:
    port = app.port
    own = {"Host": f"127.0.0.1:{port}"}
    assert app.ask("GET", "/api/setup", headers={"Host": "elsewhere.example"})[0] == 403
    assert app.ask("GET", "/api/setup", headers={"Host": f"elsewhere.example:{port}"})[0] == 403
    assert app.ask("GET", "/api/setup", headers={"Host": f"127.0.0.1.elsewhere.example:{port}"})[0] == 403
    assert app.ask("GET", "/", headers={"Host": "elsewhere.example"})[0] == 403
    for origin, allowed in (
        (f"http://127.0.0.1:{port}", True),
        (f"http://localhost:{port}", False),  # another origin than the one asked: not this page
        (f"https://127.0.0.1:{port}", False),
        (f"ftp://127.0.0.1:{port}", False),
        ("null", False),
        (f"http://127.0.0.1:{port}.example", False),
        ("http://elsewhere.example", False),
        (f"http://127.0.0.1:{port + 1}", False),
    ):
        for method, path, body in (("GET", "/api/setup", None), ("POST", "/api/stage", b"{}"), ("OPTIONS", "/", None)):
            status, _, said = app.ask(method, path, body, {**own, "Origin": origin})
            assert (status != 403) is allowed, (origin, method)
            if not allowed:
                assert json.loads(said) == server.ONLY_LOCAL
    assert (
        app.ask("GET", "/api/setup", headers={"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"})[0]
        == 200
    )


def test_a_method_the_service_does_not_take_is_said_not_to_be(app) -> None:
    for method, path in (("PUT", "/api/stage"), ("DELETE", "/api/setup"), ("PATCH", "/")):
        status, headers, body = app.ask(method, path, b"{}")
        assert status == 405 and "not answered" in json.loads(body)["error"]
        assert headers["allow"] == "GET, HEAD, POST, PUT, DELETE, OPTIONS"
    status, headers, body = app.ask("OPTIONS", "/api/setup")
    assert status == 204 and body == b"" and headers["allow"] == "GET, HEAD, POST, PUT, DELETE, OPTIONS"


def test_the_pages_of_documentation_fastapi_would_add_are_not_there(app) -> None:
    """Their addresses are the page's own: each gets the page, as any step's address does."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        status, _, body = app.ask("GET", path)
        assert status == 200 and body == (server.WEB_ROOT / "index.html").read_bytes()


BOARDS = Path(__file__).parent / "fixtures" / "boards"


def board_of(size: int) -> str:
    """The made-up half bridge with signal tracks of their own added until the file is this
    many bytes: a board as large as a real one, whose loop is the half bridge's."""
    plain = (BOARDS / "half_bridge.kicad_pcb").read_text(encoding="utf-8").rstrip()[:-1]
    line = '  (segment (start {x} {y}) (end {e} {y}) (width 0.2) (layer "B.Cu") (net 4))\n'
    more, at, n = [], len(plain), 0
    while at < size:
        more.append(line.format(x=n % 200, y=n // 200, e=n % 200 + 0.5))
        at += len(more[-1])
        n += 1
    return plain + "".join(more) + ")"


def test_a_board_file_of_megabytes_is_read_by_either_server(both) -> None:
    """The page sends a board file of up to 30 MB in its request: one of five is a board,
    and is read, not refused for the size of a request of figures."""
    text = board_of(5 * 1024 * 1024)
    for running in both:
        status, body = running.json("POST", "/api/board", {"name": "big.kicad_pcb", "text": text})
        assert status == 200, body
        assert body["figures"]["l_loop_nh"]["value"] > 0


def test_a_board_request_past_its_size_is_refused_in_its_own_words_before_it_is_read(both) -> None:
    """Said to be larger than a board file can be and sent with no body at all: answered at
    once, which a server waiting for the body could not do."""
    for running in both:
        status, headers, said = running.ask(
            "POST", "/api/board", None, {"Content-Length": str(server.MAX_BOARD_JSON + 1)}
        )
        body = json.loads(said)
        assert status == 422 and headers["connection"] == "close"
        assert body["field"] == "board" and "board file" in body["refused"] and "30 MB" in body["refused"]


def test_the_board_requests_size_is_the_board_readers_own() -> None:
    from motionsim.board.model import MOST_BYTES

    assert server.MOST_BOARD == MOST_BYTES
    assert server.MAX_BOARD_JSON >= MOST_BYTES * 4 // 3 + server.MAX_JSON


def test_a_request_that_stops_before_its_end_is_dropped_after_the_idle_time(tmp_path, monkeypatch) -> None:
    """As the standard library's server drops it: the body is waited on for as long as a
    connection may say nothing, a piece at a time, and no longer."""
    import socket
    import time

    monkeypatch.setattr(server, "IDLE", 0.5)
    with served(tmp_path / "asgi") as running:
        with socket.create_connection(("127.0.0.1", running.port), timeout=10) as raw:
            raw.sendall(
                f"POST /api/stage HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\nContent-Length: 100\r\n\r\n{{".encode()
            )
            began, heard = time.monotonic(), b""
            while chunk := raw.recv(65536):
                heard += chunk
            assert time.monotonic() - began < 5
        assert heard.startswith(b"HTTP/1.1 408") and b"stopped" in heard


def test_a_request_that_stops_before_its_end_does_not_hold_the_server_from_stopping(tmp_path) -> None:
    import socket
    import time

    import uvicorn

    listener = run.listening("127.0.0.1", 0)
    uvi = uvicorn.Server(run.config(create_app(server.Workspace(tmp_path / "d"), Store(tmp_path / "s.db"))))
    thread = threading.Thread(target=uvi.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    port = listener.getsockname()[1]
    try:
        while not uvi.started:
            time.sleep(0.05)
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            raw.sendall(f"POST /api/stage HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 100\r\n\r\n{{".encode())
            time.sleep(0.3)  # the request is under way, waiting for the rest of its body
            began = time.monotonic()
            uvi.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive() and time.monotonic() - began < 10
    finally:
        uvi.should_exit = True
        thread.join(timeout=20)
        listener.close()


def test_a_method_or_an_address_no_route_takes_is_answered_with_the_pages_headers(both) -> None:
    """What the frameworks underneath would answer of their own, a method they do not know or
    an address written whole, carries the headers that keep a browser strict all the same."""
    import socket

    for running in both:
        for line in (b"TRACE / HTTP/1.1", b"GET http://127.0.0.1:%d/ HTTP/1.1" % running.port, b"BREW /pot HTTP/1.1"):
            with socket.create_connection(("127.0.0.1", running.port), timeout=20) as raw:
                raw.sendall(line + b"\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % running.port)
                heard = b""
                while chunk := raw.recv(65536):
                    heard += chunk
            head = heard.split(b"\r\n\r\n", 1)[0].decode().lower()
            assert "x-content-type-options: nosniff" in head, (line, head)
            assert f"content-security-policy: {server.POLICY}".lower() in head and "cache-control: no-store" in head


def test_the_built_pages_hashed_files_are_kept_by_the_browser_and_nothing_else_is(both) -> None:
    """A file under assets/ is named by what it holds, so a new build is new names: kept a
    year. The page itself and every answer are never kept, or a new build would not be seen."""
    script = next(server.WEB_ROOT.glob("assets/index-*.js"))
    for running in both:
        status, headers, _ = running.ask("GET", f"/assets/{script.name}")
        assert status == 200 and headers["cache-control"] == "public, max-age=31536000, immutable"
        for path in ("/", "/index.html", "/api/setup", "/assets/no-such-file-AAAAAAAA.js", "/robots.txt"):
            assert running.ask("GET", path)[1]["cache-control"] == "no-store", path
