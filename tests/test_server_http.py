"""The local server over HTTP: the headers it sends, the methods it answers, what it does
with a request that is wrong, and that it and the page's own engine give one answer."""

from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest

from motionsim import page, server


@pytest.fixture
def running(tmp_path):
    httpd = server.Server(("127.0.0.1", 0), server.Workspace(tmp_path))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=10)


def ask(httpd, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    """One request: the status, the headers and the body."""
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post(httpd, path: str, payload) -> tuple[int, dict]:
    status, _, body = ask(httpd, "POST", path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    return status, json.loads(body)


def test_every_answer_carries_the_headers_that_keep_a_browser_strict(running) -> None:
    for method, path in (("GET", "/"), ("GET", "/api/setup"), ("GET", "/api/nothing"), ("GET", "/robots.txt")):
        _, headers, _ = ask(running, method, path)
        assert headers["X-Content-Type-Options"] == "nosniff"
        policy = dict(d.strip().split(" ", 1) for d in headers["Content-Security-Policy"].split(";"))
        assert policy == {
            "default-src": "'self'",
            "script-src": "'self' 'wasm-unsafe-eval'",
            "worker-src": "'self'",
            "connect-src": "'self'",
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data:",
            "font-src": "'self'",
            "object-src": "'none'",
            "base-uri": "'self'",
            "form-action": "'none'",
            "frame-ancestors": "'none'",
        }
        # The tool's name, and nothing of the Python that runs it.
        assert headers["Server"] == "motionsim"
        assert headers["Cache-Control"] == "no-store"


def test_robots_are_told_to_stay_out(running) -> None:
    status, headers, body = ask(running, "GET", "/robots.txt")
    assert status == 200 and headers["Content-Type"].startswith("text/plain")
    assert body == b"User-agent: *\nDisallow: /\n"


def test_head_gives_the_headers_of_get_and_no_body(running) -> None:
    status, headers, body = ask(running, "GET", "/api/setup")
    head_status, head_headers, head_body = ask(running, "HEAD", "/api/setup")
    assert (status, head_status) == (200, 200) and head_body == b"" and len(body) > 100
    assert head_headers["Content-Length"] == headers["Content-Length"] == str(len(body))
    assert head_headers["Content-Type"] == "application/json"


def test_options_says_which_methods_are_answered(running) -> None:
    status, headers, body = ask(running, "OPTIONS", "/api/setup")
    assert status == 204 and body == b"" and headers["Allow"] == "GET, HEAD, POST, OPTIONS"


def test_only_this_machines_own_page_is_answered(running) -> None:
    port = running.server_address[1]
    assert ask(running, "GET", "/api/setup", headers={"Host": "elsewhere.example"})[0] == 403
    assert ask(running, "GET", "/api/setup", headers={"Origin": "http://elsewhere.example"})[0] == 403
    assert ask(running, "POST", "/api/stage", b"{}", {"Origin": "http://elsewhere.example"})[0] == 403
    assert ask(running, "OPTIONS", "/api/stage", headers={"Origin": "http://elsewhere.example"})[0] == 403
    assert ask(running, "GET", "/api/setup", headers={"Origin": f"http://localhost:{port}"})[0] == 200


def test_the_addresses_of_the_page(running) -> None:
    status, _, body = ask(running, "GET", "/engine/mode.json")
    assert status == 200 and json.loads(body) == {"server": True}
    status, _, body = ask(running, "GET", "/api/device/example")
    assert status == 200 and json.loads(body)
    status, _, body = ask(running, "GET", "/api/device/no-such-part")
    assert status == 422 and json.loads(body)["refused"] == "no device called no-such-part"
    assert ask(running, "GET", "/api/stage")[0] == 404  # one that is posted to
    assert post(running, "/api/nothing", {})[0] == 404


def test_a_body_that_cannot_be_taken_is_said_with_its_status(running) -> None:
    assert ask(running, "POST", "/api/stage", b"{not json")[0] == 400
    assert ask(running, "POST", "/api/stage", b"[1, 2]")[0] == 400
    status, _, body = ask(running, "POST", "/api/stage", headers={"Content-Length": "many"})
    assert status == 400 and "how long" in json.loads(body)["error"]
    status, _, body = ask(running, "POST", "/api/read", headers={"Content-Length": str(server.MAX_BODY + 1)})
    assert status == 422 and "too large" in json.loads(body)["refused"]


def test_a_kind_of_motor_that_is_a_list_is_refused_and_not_a_fault(running) -> None:
    status, body = post(running, "/api/loads", {"kind": ["pmsm"], "rpm": 1000, "torque": 1})
    assert status == 422 and body["field"] == "kind"
    status, body = post(running, "/api/loads", {"kind": "pmsm", "rpm": 1000, "torque": 1})
    assert status == 200 and body["loads"]


def test_a_typed_part_with_a_figure_of_an_unknown_name_is_refused(running) -> None:
    figures = {
        "technology": "Si MOSFET",
        "part_number": "MU100N04",
        "v_rated": 100,
        "i_rated": 100,
        "tj_max": 175,
        "rth_jc": 0.6,
        "rds_on": 4.0,
        "v_th": 3.0,
        "v_plateau": 4.6,
        "q_gs": 20,
        "q_gd": 14,
    }
    status, body = post(running, "/api/typed", {"figures": figures})
    assert status == 200 and body["device"]["v_max"] == 100
    # rds_on_hot mistyped: left out in silence, the part would be built as if it never warmed.
    status, body = post(running, "/api/typed", {"figures": {**figures, "rdson_hot": 7.2}})
    assert status == 422 and body["field"] == "rdson_hot" and "rdson_hot" in body["refused"]


def test_a_datasheet_called_example_does_not_take_the_examples_place(tmp_path, monkeypatch) -> None:
    from motionsim.observe import provider

    seen = {}

    def stop_after_naming(pdf, **kwargs):
        seen["name"] = pdf.name
        raise server.Refused("stopped where the test wanted", "")

    monkeypatch.setattr(provider, "chosen", lambda: provider.Reader("anthropic", "stub"))
    monkeypatch.setattr("motionsim.observe.run.read_datasheet", stop_after_naming)
    ws = server.Workspace(tmp_path)
    for upload, kept in (("example.pdf", "example-file.pdf"), ("Example-MOSFET.pdf", "example-mosfet-file.pdf")):
        with pytest.raises(server.Refused):
            server.read_datasheet(upload, b"%PDF-1.4 nothing", ws)
        assert seen["name"] == kept
    with pytest.raises(server.Refused):
        server.read_datasheet("my part.pdf", b"%PDF-1.4 nothing", ws)
    assert seen["name"] == "my-part.pdf"


def test_a_reader_that_goes_away_mid_answer_is_not_a_fault(running, capfd) -> None:
    port = running.server_address[1]
    for _ in range(5):
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            raw.sendall(f"GET /api/setup HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    assert ask(running, "GET", "/api/setup")[0] == 200  # still serving
    said = capfd.readouterr()
    assert "Traceback" not in said.err and "Exception" not in said.err


def test_a_connection_that_says_nothing_is_dropped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server.Handler, "timeout", 0.3)
    httpd = server.Server(("127.0.0.1", 0), server.Workspace(tmp_path))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(("127.0.0.1", httpd.server_address[1]), timeout=10) as raw:
            raw.sendall(b"GET /api/setup HTTP/1.1\r\n")  # and then nothing
            assert raw.recv(1024) == b""  # closed by the server, not held open
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


def test_the_server_and_the_pages_own_engine_give_one_answer(running, tmp_path) -> None:
    ws = page.Workspace(tmp_path / "other")
    setup = page.setup(ws)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    requests = [
        ("/api/stage", {"motor": motor, "conditions": {**page.STARTING["pmsm"], "t_sink": 60}}),
        ("/api/stage", {"motor": motor}),  # refused: no conditions
        ("/api/stage", {"motor": motor, "conditions": {**page.STARTING["pmsm"], "v_dc": "a lot"}}),
        ("/api/loads", {"kind": 7}),
        ("/api/nothing", {}),
    ]
    for route, body in requests:
        status, over_http = post(running, route, body)
        own = json.loads(page.call(route, json.dumps(body), ws))
        assert (status, over_http) == (own["status"], own["body"]), route


def test_a_fault_is_500_with_no_path_in_it_and_the_server_goes_on(running, monkeypatch, caplog) -> None:
    from motionsim.service import routes

    def broken(data, ws):
        raise RuntimeError("could not open /home/someone/secret/table.npy")

    monkeypatch.setitem(routes.ROUTES, "/api/suggest", broken)
    status, body = post(running, "/api/suggest", {"device": "example"})
    assert status == 500 and body == {"error": "RuntimeError: could not open table.npy"}
    assert any("fault answering /api/suggest" in r.getMessage() and r.exc_info for r in caplog.records)
    assert ask(running, "GET", "/api/setup")[0] == 200


def test_serve_says_where_it_is_at_once_and_stops_when_told(tmp_path) -> None:
    import os
    import signal
    import subprocess
    import sys
    import urllib.request

    process = subprocess.Popen(
        [sys.executable, "-m", "motionsim.cli", "serve", "--port", "0", "--no-browser", "--devices", str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline()  # the line is there though the output is a pipe
        assert line.startswith("motionsim is at http://127.0.0.1:")
        address = line.split()[3]
        with urllib.request.urlopen(address + "api/setup", timeout=20) as answer:
            assert answer.status == 200 and "motors" in json.loads(answer.read())
    finally:
        os.kill(process.pid, signal.SIGINT)
        process.wait(timeout=20)
        process.stdout.close()
        process.stderr.close()
    assert process.returncode == 0


def test_text_goes_gzipped_to_a_browser_that_takes_it_and_plain_to_one_that_does_not(running) -> None:
    import gzip

    _, plain_headers, plain = ask(running, "GET", "/api/setup")
    assert "Content-Encoding" not in plain_headers
    assert plain_headers["Vary"] == "Accept-Encoding"
    status, headers, packed = ask(running, "GET", "/api/setup", headers={"Accept-Encoding": "gzip, deflate, br"})
    assert status == 200
    assert headers["Content-Encoding"] == "gzip" and headers["Vary"] == "Accept-Encoding"
    assert int(headers["Content-Length"]) == len(packed) < len(plain)
    assert gzip.decompress(packed) == plain
    # A small answer and a font go as they are.
    _, small, _ = ask(running, "GET", "/robots.txt", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in small


@pytest.mark.parametrize(
    "header",
    ["gzip;q=0, identity", "gzip; q=0.0", "identity", "deflate, br", "*;q=0", "br, *;q=0", "GZIP;Q=0", "gzipped"],
)
def test_text_goes_plain_to_a_client_that_refuses_gzip(running, header) -> None:
    status, headers, body = ask(running, "GET", "/api/setup", headers={"Accept-Encoding": header})
    assert status == 200 and "Content-Encoding" not in headers
    assert headers["Vary"] == "Accept-Encoding"
    assert body.startswith(b"{")


@pytest.mark.parametrize(
    "header",
    ["gzip", "GZip;q=0.5", "deflate, gzip;q=1.0", "br;q=1, gzip;q=0.001", "*", "br, *;q=0.1", "x-gzip", " gzip ; q=1 "],
)
def test_text_goes_gzipped_to_a_client_that_takes_gzip_by_any_spelling(running, header) -> None:
    _, headers, _ = ask(running, "GET", "/api/setup", headers={"Accept-Encoding": header})
    assert headers.get("Content-Encoding") == "gzip"
