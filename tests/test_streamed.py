"""A search answered step by step: the lines the local server and the page's own engine send,
and that a reader who goes away stops the search."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time

import pytest

from motionsim import page, server
from motionsim.service import routes
from motionsim.service.motion import heavier

# What the address needs to hold; the search itself is stood in for, so the figures are not read.
DATA = {"motor": {"type": "pmsm"}, "conditions": {}, "device": "example", "load": {}, "profile": {"segments": []}}


def _fake(tried_at: list[float], slow: float = 0.0):
    def tried(data, ws, k, coarse=True):
        tried_at.append(k)
        time.sleep(slow)
        fine = k <= 2.7
        return fine, "" if fine else "junction too hot", {"summary": {"peak": 100.0 + 20 * k, "tj_max": 150.0}}

    return tried


@pytest.fixture
def running(tmp_path):
    httpd = server.Server(("127.0.0.1", 0), server.Workspace(tmp_path))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=10)


def test_the_steps_come_before_the_answer_the_address_gives(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(heavier, "_tried", _fake([]))
    ws = page.Workspace(tmp_path)
    data = DATA
    lines = list(routes.stream("/api/largest", data, ws))
    assert all("probe" in x for x in lines[:-1]) and len(lines) == 11
    assert lines[-1] == {"status": 200, "body": routes.dispatch("/api/largest", data, ws)[1]}
    # The same, as the page's own engine reads it: a line of text at a time.
    said = [json.loads(x) for x in routes.stream_call("/api/largest", json.dumps(data), ws)]
    assert said == lines


def test_a_request_refused_or_faulty_ends_as_dispatch_ends_it(tmp_path, monkeypatch) -> None:
    ws = page.Workspace(tmp_path)
    assert list(routes.stream("/api/largest", {}, ws)) == [
        {"status": 422, "body": routes.dispatch("/api/largest", {}, ws)[1]}
    ]
    assert list(routes.stream("/api/nothing", {}, ws)) == [{"status": 404, "body": {"error": "no such address"}}]
    assert json.loads(next(routes.stream_call("/api/largest", "[1]", ws)))["status"] == 400

    def broken(data, ws, k, coarse=True):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(heavier, "_tried", broken)
    data = DATA
    last = list(routes.stream("/api/largest", data, ws))[-1]
    assert last["status"] == 500 and last["body"] == routes.dispatch("/api/largest", data, ws)[1]


def test_a_stream_put_down_stops_the_search_between_two_steps(tmp_path, monkeypatch) -> None:
    tried_at: list[float] = []
    monkeypatch.setattr(heavier, "_tried", _fake(tried_at))
    lines = routes.stream_call("/api/largest", json.dumps(DATA), page.Workspace(tmp_path))
    next(lines)
    next(lines)
    lines.close()
    assert tried_at == [1.0, 2.0]


def _raw(httpd, payload: dict) -> socket.socket:
    body = json.dumps(payload).encode()
    port = httpd.server_address[1]
    sock = socket.create_connection(("127.0.0.1", port), timeout=20)
    head = (
        f"POST /api/largest/stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    )
    sock.sendall(head.encode() + body)
    return sock


def test_the_server_sends_one_line_a_step_and_the_answer_last(running, monkeypatch) -> None:
    monkeypatch.setattr(heavier, "_tried", _fake([]))
    port = running.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    data = DATA
    connection.request("POST", "/api/largest/stream", json.dumps(data).encode(), {"Content-Type": "application/json"})
    response = connection.getresponse()
    assert response.status == 200 and response.getheader("Content-Type") == "application/x-ndjson"
    assert response.getheader("Content-Security-Policy") == server.POLICY
    lines = [json.loads(x) for x in response.read().decode().splitlines()]
    connection.close()
    assert len(lines) == 11 and lines[-1]["status"] == 200 and lines[-1]["body"]["scale"] == 2.6875


def test_a_page_that_stops_waiting_stops_the_search_on_the_server(running, monkeypatch) -> None:
    tried_at: list[float] = []
    monkeypatch.setattr(heavier, "_tried", _fake(tried_at, slow=0.3))
    sock = _raw(running, DATA)
    seen = b""
    while b'"probe"' not in seen:  # the first step's line
        seen += sock.recv(4096)
    sock.close()
    time.sleep(2.0)  # a search left running would have tried six more scales by now
    # The step on its way when the page went is the last: seen gone before the next one starts.
    assert tried_at == [1.0, 2.0], tried_at


def test_a_stream_that_is_not_json_is_refused_as_any_request_is(running) -> None:
    port = running.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    connection.request("POST", "/api/largest/stream", b"{nope", {"Content-Type": "application/json"})
    response = connection.getresponse()
    assert response.status == 400 and "JSON" in json.loads(response.read())["error"]
    connection.close()
