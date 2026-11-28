"""A search answered a step at a time through the ASGI app: over HTTP as the standard
library's server sends it, and over a WebSocket; either way the steps, then the answer, and
a search that stops when nobody is waiting for it."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time

import pytest

pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")
pytest.importorskip("wsproto", reason="the ASGI app needs the app extra")

import wsproto
from test_app_http import builtin, served
from wsproto import events

from motionsim import server
from motionsim.app import home
from motionsim.observe import provider
from motionsim.service import routes

SLOW = "/api/slow-search"


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    monkeypatch.setattr(provider, "saved_key", provider.saved_key)


@pytest.fixture
def app(tmp_path):
    with served(tmp_path / "asgi") as running:
        yield running


class Search:
    """A search of the test's own, put in the service's tables as any search is: it says a
    step every few milliseconds, and records how far it got and that it was stopped."""

    def __init__(self, steps: int, pause: float = 0.0) -> None:
        self.steps, self.pause = steps, pause
        self.done = 0
        self.closed = threading.Event()

    def __call__(self, data: dict, workspace):
        try:
            for n in range(self.steps):
                time.sleep(self.pause)
                self.done = n + 1
                yield {"step": n, "asked": data.get("asked")}
            return {"found": self.steps, "nan": float("nan")}
        finally:
            self.closed.set()


@pytest.fixture
def search(monkeypatch):
    def put(steps: int, pause: float = 0.0) -> Search:
        made = Search(steps, pause)
        monkeypatch.setitem(routes.STREAMS, SLOW, made)
        monkeypatch.setitem(routes.ROUTES, SLOW, lambda data, ws: {"found": steps})
        return made

    return put


class Socket:
    """A WebSocket to the app, spoken by hand: what is sent, and each message that comes."""

    def __init__(self, port: int, headers: dict | None = None, target: str = "/ws/stream") -> None:
        self.raw = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.link = wsproto.WSConnection(wsproto.ConnectionType.CLIENT)
        extra = [(name.encode(), value.encode()) for name, value in (headers or {}).items()]
        self.raw.sendall(self.link.send(events.Request(host=f"127.0.0.1:{port}", target=target, extra_headers=extra)))
        self.opened = self._next()

    def _next(self):
        """The next thing the app says, or None once the connection is closed under it."""
        while True:
            for event in self.link.events():
                return event
            try:
                data = self.raw.recv(65536)
            except ConnectionError:
                return None
            if not data:
                return None
            self.link.receive_data(data)

    def send(self, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.raw.sendall(self.link.send(events.TextMessage(data=text)))

    def message(self):
        """The next message as the JSON it is, or the closing event where the app closes."""
        event = self._next()
        return json.loads(event.data) if isinstance(event, events.TextMessage) else event

    def messages(self) -> list:
        """Every message up to the close."""
        said = []
        while not isinstance(item := self.message(), (events.CloseConnection, type(None))):
            said.append(item)
        self.closing = item
        return said

    def close(self) -> None:
        self.raw.close()


def test_a_search_over_http_says_each_step_on_a_line_and_the_answer_last(app, search) -> None:
    search(3)
    status, headers, body = app.ask("POST", SLOW + "/stream", json.dumps({"asked": "x"}).encode())
    assert status == 200 and headers["content-type"] == "application/x-ndjson"
    assert headers["x-content-type-options"] == "nosniff" and headers["content-security-policy"] == server.POLICY
    assert headers["cache-control"] == "no-store" and headers["server"] == "motionsim"
    assert [json.loads(line) for line in body.splitlines()] == [
        {"probe": {"step": 0, "asked": "x"}},
        {"probe": {"step": 1, "asked": "x"}},
        {"probe": {"step": 2, "asked": "x"}},
        {"status": 200, "body": {"found": 3, "nan": None}},
    ]


def test_the_search_of_the_service_is_streamed_as_the_standard_librarys_server_streams_it(tmp_path) -> None:
    """The largest load, asked of both servers with nothing in the request and with a motor
    and a part: line for line the same."""
    kinds = server.setup(server.Workspace(tmp_path / "unused"))["motors"]
    design = {
        "motor": {"type": "pmsm", **kinds["pmsm"]["values"]},
        "conditions": {**kinds["pmsm"]["start"], "t_sink": 60},
        "device": "example",
    }
    with served(tmp_path / "asgi") as asgi, builtin(tmp_path / "builtin") as stdlib:
        for request in ({}, design):
            body = json.dumps(request).encode()
            lines = [s.ask("POST", "/api/largest/stream", body)[2].splitlines() for s in (asgi, stdlib)]
            assert lines[0] == lines[1] and "status" in json.loads(lines[0][-1])


def test_a_search_over_http_stops_when_the_page_stops_waiting(app, search) -> None:
    slow = search(2000, pause=0.01)
    with socket.create_connection(("127.0.0.1", app.port), timeout=30) as raw:
        raw.sendall(
            f"POST {SLOW}/stream HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nContent-Length: 2\r\n\r\n{{}}".encode()
        )
        heard = b""
        while b'{"probe"' not in heard:  # under way
            heard += raw.recv(65536)
    assert slow.closed.wait(timeout=20)  # stopped between two steps, with most of them not done
    assert slow.done < 1000
    assert app.ask("GET", "/api/setup")[0] == 200


def test_a_search_over_the_socket_says_each_step_as_a_message_and_the_answer_last(app, search) -> None:
    search(3)
    link = Socket(app.port)
    assert isinstance(link.opened, events.AcceptConnection)
    link.send({"route": SLOW, "data": {"asked": "x"}})
    assert link.messages() == [
        {"probe": {"step": 0, "asked": "x"}},
        {"probe": {"step": 1, "asked": "x"}},
        {"probe": {"step": 2, "asked": "x"}},
        {"status": 200, "body": {"found": 3, "nan": None}},
    ]
    assert isinstance(link.closing, events.CloseConnection) and link.closing.code == 1000
    link.close()


def test_the_socket_and_the_service_give_one_stream(app, tmp_path) -> None:
    """Every search in the service's table, asked with nothing in the request: the messages
    are the lines `stream` gives, so a search added to the table later is held to this too."""
    apart = server.Workspace(tmp_path / "apart")
    for route in sorted(routes.STREAMS):
        link = Socket(app.port)
        link.send({"route": route, "data": {}})
        assert link.messages() == list(routes.stream(route, {}, apart))
        link.close()


def test_a_search_over_the_socket_stops_when_the_socket_closes(app, search) -> None:
    slow = search(2000, pause=0.01)
    link = Socket(app.port)
    link.send({"route": SLOW})
    assert link.message() == {"probe": {"step": 0, "asked": None}}
    link.close()
    assert slow.closed.wait(timeout=20)
    assert slow.done < 1000
    assert app.ask("GET", "/api/setup")[0] == 200


def test_a_search_over_the_socket_stops_when_the_page_says_anything_more(app, search) -> None:
    slow = search(2000, pause=0.01)
    link = Socket(app.port)
    link.send({"route": SLOW})
    assert link.message() == {"probe": {"step": 0, "asked": None}}
    link.send({"stop": True})
    said = link.messages()
    assert slow.closed.is_set() and slow.done < 1000
    assert all("probe" in line for line in said)  # no answer: the search did not finish
    link.close()


@pytest.mark.parametrize(
    ("sent", "status", "word"),
    [
        ("{not json", 400, "not JSON"),
        ("[1, 2]", 400, "JSON object"),
        ('{"route": 7}', 400, "JSON object"),
        ('{"route": "/api/largest", "data": [1]}', 400, "JSON object"),
        ('{"route": "/api/nothing"}', 404, "no such address"),
        ('{"route": "/api/stage", "data": {}}', 404, "no such address"),  # an address, and not a search
    ],
)
def test_a_first_message_that_asks_nothing_is_answered_as_the_page_reads_every_answer(app, sent, status, word) -> None:
    link = Socket(app.port)
    link.send(sent)
    (said,) = link.messages()
    assert said["status"] == status and word in said["body"]["error"]
    link.close()


def test_a_first_message_too_large_to_be_a_request_is_refused(app) -> None:
    link = Socket(app.port)
    link.send({"route": "/api/largest", "data": {"text": "x" * (server.MAX_JSON + 1)}})
    assert link.messages() == [{"status": 422, "body": server.TOO_LARGE_JSON}]
    link.close()


def test_a_refusal_comes_over_the_socket_as_422_with_its_reason(app) -> None:
    link = Socket(app.port)
    link.send({"route": "/api/largest", "data": {}})
    (said,) = link.messages()
    assert said["status"] == 422 and said["body"]["refused"] and said["body"]["fix"]
    link.close()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://elsewhere.example"},
        {"Origin": "https://127.0.0.1"},
        {"Origin": "null"},
    ],
)
def test_a_socket_opened_by_another_sites_page_is_refused_before_it_is_taken(app, search, headers) -> None:
    """A browser lets any page open a WebSocket to any address, and says where the page is
    from: that is the one thing that keeps another site from running a search here."""
    slow = search(3)
    link = Socket(app.port, headers)
    assert isinstance(link.opened, events.RejectConnection) and link.opened.status_code == 403
    link.close()
    assert slow.done == 0


def test_a_socket_opened_by_this_page_is_taken(app, search) -> None:
    search(1)
    link = Socket(app.port, {"Origin": f"http://127.0.0.1:{app.port}"})
    assert isinstance(link.opened, events.AcceptConnection)
    link.send({"route": SLOW})
    assert len(link.messages()) == 2
    link.close()


def test_a_socket_that_asks_nothing_is_closed_and_not_held_open(app, monkeypatch) -> None:
    monkeypatch.setattr(server, "IDLE", 0.2)
    link = Socket(app.port)
    assert link.messages() == [] and link.closing is not None and link.closing.code == 1008
    link.close()


def test_no_other_address_takes_a_socket(app) -> None:
    link = Socket(app.port, target="/ws/elsewhere")
    assert isinstance(link.opened, events.RejectConnection)
    link.close()


class Spin:
    """A search whose every step keeps a processor busy for a moment and then holds its
    worker a while, and counts the steps begun: what a closed socket leaves running shows as
    steps begun after it closed. Each step lets go of the interpreter for most of its time,
    so that the app hears of the sockets closing as soon as they close."""

    def __init__(self, steps: int, busy: float, held: float) -> None:
        self.steps, self.busy, self.held = steps, busy, held
        self.begun = 0
        self.lock = threading.Lock()

    def __call__(self, data: dict, workspace):
        for n in range(self.steps):
            with self.lock:
                self.begun += 1
            end = time.thread_time() + self.busy
            while time.thread_time() < end:
                pass
            time.sleep(self.held)
            yield {"step": n}
        return {"found": self.steps}


def reset(link: Socket) -> None:
    """Gone without a word: the connection reset, as a tab killed or a cable pulled leaves it."""
    link.raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    link.raw.close()


@pytest.mark.parametrize("how", ["closed", "reset", "said"])
def test_a_socket_that_goes_mid_search_leaves_no_fault_in_the_log(app, search, caplog, how) -> None:
    """A page that stops a search is no fault of the tool's, however it goes."""
    slow = search(2000, pause=0.01)
    link = Socket(app.port)
    link.send({"route": SLOW})
    assert link.message() == {"probe": {"step": 0, "asked": None}}
    if how == "closed":
        link.raw.sendall(link.link.send(events.CloseConnection(code=1000)))
        link.close()
    elif how == "reset":
        reset(link)
    else:
        link.send({"stop": True})
        link.messages()
        link.close()
    assert slow.closed.wait(timeout=20)
    time.sleep(0.3)  # the app's last words, if it had any, are said by now
    assert app.ask("GET", "/api/setup")[0] == 200
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_the_work_of_sockets_that_have_closed_stops_within_two_seconds(app, monkeypatch) -> None:
    """A hundred searches asked at once queue for the workers; once their sockets are gone,
    a step that has not begun never begins, and the processor is idle within two seconds."""
    from motionsim.app import server as app_server

    monkeypatch.setattr(app_server, "MOST_STREAMS", 100)
    spin = Spin(1000, busy=0.005, held=0.1)
    monkeypatch.setitem(routes.STREAMS, SLOW, spin)
    monkeypatch.setitem(routes.ROUTES, SLOW, lambda data, ws: {})
    links = [Socket(app.port) for _ in range(100)]
    for link in links:
        link.send({"route": SLOW})
    time.sleep(0.5)  # under way, and queued for the workers
    for link in links:
        reset(link)
    began = spin.begun
    time.sleep(2.0)
    # The steps under way when the sockets went are finished, and at most those.
    assert spin.begun - began <= 45
    begun, spent = spin.begun, time.process_time()
    time.sleep(1.0)
    assert spin.begun == begun
    assert time.process_time() - spent < 0.2


def test_more_searches_at_once_than_are_taken_are_refused_in_words(app, search, monkeypatch) -> None:
    from motionsim.app import server as app_server

    monkeypatch.setattr(app_server, "MOST_STREAMS", 2)
    slow = search(2000, pause=0.01)
    held = [Socket(app.port) for _ in range(2)]
    for link in held:
        link.send({"route": SLOW})
        assert "probe" in link.message()
    extra = Socket(app.port)
    extra.send({"route": SLOW})
    (said,) = extra.messages()
    assert said["status"] == 429 and "searches" in said["body"]["refused"] and said["body"]["fix"]
    extra.close()
    for link in held:
        link.close()
    assert slow.closed.wait(timeout=20)
    # Once they are done, a search is taken again.
    deadline = time.monotonic() + 10
    while True:
        again = Socket(app.port)
        again.send({"route": SLOW})
        first = again.message()
        again.close()
        if "probe" in first or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    assert "probe" in first


def test_a_message_of_megabytes_is_closed_as_too_large_while_it_arrives(app) -> None:
    """Twenty megabytes asked as one search: closed as too large (1009) before the app sees
    it, and the app answers the next request as ever."""
    link = Socket(app.port)
    frame = link.link.send(
        events.TextMessage(data='{"route": "/api/largest", "data": {"x": "' + "a" * (20 << 20) + '"}}')
    )
    try:
        for at in range(0, len(frame), 1 << 20):
            link.raw.sendall(frame[at : at + (1 << 20)])
        closing = link.message()
    except ConnectionError:
        closing = None  # closed under the sender, as a server that stops reading may
    link.close()
    assert closing is None or (isinstance(closing, events.CloseConnection) and closing.code == 1009)
    assert app.ask("GET", "/api/setup")[0] == 200


def test_more_searches_over_http_at_once_than_are_taken_are_refused_in_words(app, search, monkeypatch) -> None:
    from motionsim.app import server as app_server

    monkeypatch.setattr(app_server, "MOST_STREAMS", 1)
    slow = search(2000, pause=0.01)
    with socket.create_connection(("127.0.0.1", app.port), timeout=30) as raw:
        raw.sendall(
            f"POST {SLOW}/stream HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nContent-Length: 2\r\n\r\n{{}}".encode()
        )
        heard = b""
        while b'{"probe"' not in heard:
            heard += raw.recv(65536)
        status, body = app.json("POST", SLOW + "/stream", {})
        assert status == 429 and "searches" in body["refused"]
    assert slow.closed.wait(timeout=20)
    search(1)  # once it is done, a search is taken again
    deadline = time.monotonic() + 10
    while app.ask("POST", SLOW + "/stream", b"{}")[0] != 200 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert app.ask("POST", SLOW + "/stream", b"{}")[0] == 200
