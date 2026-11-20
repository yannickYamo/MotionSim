"""What the local server holds a request to before it works on it: an address it answers,
a size a request of that kind has, an origin that is this page's own, and no more devices
than a comparison takes."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from motionsim import server
from motionsim.observe import provider
from motionsim.service.answers import without_paths


@pytest.fixture
def running(tmp_path):
    httpd = server.Server(("127.0.0.1", 0), server.Workspace(tmp_path))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=10)


def ask(httpd, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
    try:
        connection.putrequest(method, path)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        if body is not None and "Content-Length" not in (headers or {}):
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders()
        if body:
            connection.send(body)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_an_unknown_address_is_answered_before_the_body_is_read(running) -> None:
    """A request to nowhere that says it carries 30 MB and sends none is answered at once:
    the server does not sit waiting for a body it would throw away."""
    status, body = ask(running, "POST", "/api/nowhere", headers={"Content-Length": str(30 * 1024 * 1024)})
    assert status == 404 and b"no such address" in body


@pytest.mark.parametrize("path", ["/api/stage", "/api/proposal", "/api/typed"])
def test_a_request_past_a_megabyte_is_refused_unread(running, path) -> None:
    status, body = ask(running, "POST", path, headers={"Content-Length": str(1024 * 1024 + 1)})
    # A refusal, as the page shows every refusal: the request is the asker's to put right.
    assert status == 422
    said = json.loads(body)
    assert "too large" in said["refused"] and said["fix"]


def test_a_datasheet_may_be_larger(running) -> None:
    """A datasheet of a few megabytes is a datasheet: what it is refused for is not its size."""
    pdf = b"not a pdf" + b"x" * (3 * 1024 * 1024)
    status, body = ask(running, "POST", "/api/read?name=sheet.pdf", pdf)
    assert status == 422 and b"too large" not in body


@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("http://127.0.0.1:{port}", True),
        ("http://localhost:{port}", True),
        ("https://127.0.0.1:{port}", False),
        ("ftp://localhost:{port}", False),
        ("null", False),
        ("http://127.0.0.1:{port}.example", False),
    ],
)
def test_the_origin_is_compared_in_full(running, origin, allowed) -> None:
    port = running.server_address[1]
    status, _ = ask(
        running, "GET", "/api/setup", headers={"Host": f"127.0.0.1:{port}", "Origin": origin.format(port=port)}
    )
    assert (status == 200) is allowed


@pytest.mark.parametrize("route", ["/api/compare", "/api/proposal"])
def test_more_than_five_devices_are_refused_plainly(running, route) -> None:
    payload = json.dumps({"devices": ["example"] * 6, "conditions": {}, "motor": {}}).encode()
    status, body = ask(running, "POST", route, payload, {"Content-Type": "application/json"})
    said = json.loads(body)
    assert status == 422
    assert said["refused"] == "6 devices are named, and 5 is the most compared at once"
    assert said["field"] == "devices"


@pytest.mark.parametrize(
    "text, kept",
    [
        ("no connection to https://api.example.com/v1: refused", "https://api.example.com/v1"),
        ("http://127.0.0.1:8000/v1 did not answer", "http://127.0.0.1:8000/v1"),
        ("cannot open /home/someone/sheets/part.pdf", "part.pdf"),
        ("cannot open C:\\Users\\someone\\part.pdf", "part.pdf"),
    ],
)
def test_paths_are_cut_to_their_last_part_and_addresses_are_kept(text, kept) -> None:
    said = without_paths(text)
    assert kept in said
    assert "someone" not in said


@pytest.mark.parametrize(
    "failure, fix",
    [
        (lambda r: provider.status_failure(r, 401), "key"),
        (lambda r: provider.status_failure(r, 404), "MOTIONSIM_LLM_MODEL"),
        (lambda r: provider.status_failure(r, 429), "wait"),
        (lambda r: provider.status_failure(r, 503), "later"),
        (lambda r: provider.no_connection(r, "refused"), "address"),
        (lambda r: provider.cut_off(), "split"),
    ],
)
def test_a_reading_failure_carries_the_fix_for_its_cause(failure, fix) -> None:
    reader = provider.Reader("chat", "m", "https://models.example/v1", "k")
    assert fix in failure(reader).fix


def test_the_server_passes_the_fix_of_a_reading_failure_on(monkeypatch, tmp_path) -> None:
    from motionsim.observe import run

    monkeypatch.setattr(run, "ready", lambda: None)
    monkeypatch.setattr(provider, "chosen", lambda *a: provider.Reader("chat", "m", "https://models.example/v1", "k"))
    late = provider.status_failure(provider.Reader("chat", "m", "https://models.example/v1", "k"), 429)

    def fails(*args, **kwargs):
        raise late

    monkeypatch.setattr(run, "read_datasheet", fails)
    with pytest.raises(server.Refused) as refused:
        server.read_datasheet("sheet.pdf", b"%PDF-1.4", server.Workspace(tmp_path))
    assert refused.value.fix == late.fix
