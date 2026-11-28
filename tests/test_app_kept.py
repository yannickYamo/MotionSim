"""What the ASGI app keeps for the page: the datasheet reader's key and the local store,
over HTTP. The key is never sent back, and neither is answered for any page but this one."""

from __future__ import annotations

import io
import json
import logging
import stat
import sys

import pytest
from test_app_http import served

from motionsim import server
from motionsim.app import home, keys
from motionsim.app import server as asgi
from motionsim.app.server import WRITTEN_HERE
from motionsim.app.store import KINDS, MAX_DOC
from motionsim.observe import provider

KEY = "sk-made-up-0123456789"
UNSET = {"reader": {"key": "unset", "source": None, "saved": False}}
SAVED = {"reader": {"key": "set", "source": "saved", "saved": True}}


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    """MotionSim's folder is the test's own, and the environment sets no reader up."""
    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    for name in (*provider.SETS_UP, "ANTHROPIC_BASE_URL", "MOTIONSIM_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(provider, "saved_key", provider.saved_key)
    return tmp_path / "home"


@pytest.fixture
def app(tmp_path):
    with served(tmp_path / "asgi") as running:
        yield running


def state(answer: tuple[int, dict]) -> dict:
    """The settings as answered, less whether the reader's libraries are installed here."""
    status, body = answer
    assert status == 200 and isinstance(body["reader"].pop("available"), bool)
    return body


def test_the_settings_say_no_key_is_set_until_one_is(app) -> None:
    assert state(app.json("GET", "/api/settings")) == UNSET


def test_a_key_set_from_the_page_is_kept_in_a_file_of_its_owners_alone_and_never_sent_back(app, own_folder) -> None:
    status, headers, body = app.ask("PUT", "/api/settings/key", json.dumps({"key": KEY}).encode())
    assert status == 200 and KEY.encode() not in body and KEY not in repr(headers)
    assert state((status, json.loads(body))) == SAVED
    file = own_folder / "reader.key"
    assert file.read_text() == KEY
    if sys.platform != "win32":
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
    # Not in the store either, and not in any later answer.
    assert KEY.encode() not in b"".join(
        p.read_bytes() for p in own_folder.parent.rglob("*") if p.is_file() and p != file
    )
    for path in ("/api/settings", "/api/setup"):
        assert KEY.encode() not in app.ask("GET", path)[2]


def test_a_key_set_from_the_page_is_read_with_at_once(app) -> None:
    """The first screen says whether a datasheet can be read, and says so from the next
    request on: nothing is started again."""
    readable = lambda: app.json("GET", "/api/setup")[1]["can_read"]
    assert readable() is False
    app.json("PUT", "/api/settings/key", {"key": KEY})
    assert readable() is True
    assert provider.chosen().kind == "anthropic"
    assert provider.anthropic_arguments() == {"api_key": KEY}
    app.json("DELETE", "/api/settings/key")
    assert readable() is False


def test_a_key_forgotten_is_gone_from_the_machine(app, own_folder) -> None:
    app.json("PUT", "/api/settings/key", {"key": KEY})
    assert state(app.json("DELETE", "/api/settings/key")) == UNSET
    assert not (own_folder / "reader.key").exists()
    assert state(app.json("DELETE", "/api/settings/key")) == UNSET  # forgetting twice is no fault


def test_a_key_in_the_environment_wins_and_the_settings_say_so(app, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-shell")
    assert state(app.json("GET", "/api/settings")) == {
        "reader": {"key": "set", "source": "environment", "saved": False}
    }
    status, _, body = app.ask("PUT", "/api/settings/key", json.dumps({"key": KEY}).encode())
    assert status == 200 and b"sk-from-the-shell" not in body and KEY.encode() not in body
    assert json.loads(body)["reader"]["source"] == "environment" and json.loads(body)["reader"]["saved"] is True
    assert provider.environment()["ANTHROPIC_API_KEY"] == "sk-from-the-shell"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert state(app.json("GET", "/api/settings")) == SAVED


@pytest.mark.parametrize(
    "sent",
    [{}, {"key": ""}, {"key": None}, {"key": 7}, {"key": "sk with space"}, {"key": "sk-\n" + KEY}, {"key": "k" * 513}],
)
def test_what_has_not_the_shape_of_a_key_is_refused_with_a_reason_and_never_repeated(app, own_folder, sent) -> None:
    status, _, body = app.ask("PUT", "/api/settings/key", json.dumps(sent).encode())
    said = json.loads(body)
    assert status == 422 and said["field"] == "key" and said["refused"] and said["fix"]
    if isinstance(sent.get("key"), str) and sent["key"]:
        assert sent["key"].encode() not in body and KEY.encode() not in body
    assert not (own_folder / "reader.key").exists()


def test_a_request_too_large_to_be_a_key_is_refused_unread(app) -> None:
    status, headers, body = app.ask("PUT", "/api/settings/key", None, {"Content-Length": str(keys.MAX_REQUEST + 1)})
    assert status == 422 and json.loads(body) == asgi.TOO_LARGE_KEY and headers["connection"] == "close"
    assert app.ask("PUT", "/api/settings/key", b"{not json")[0] == 400
    assert app.ask("PUT", "/api/settings/key", b'["' + KEY.encode() + b'"]')[0] == 400


def test_a_key_is_never_written_to_the_log(app, caplog) -> None:
    caplog.set_level("DEBUG")
    app.json("PUT", "/api/settings/key", {"key": KEY})
    app.json("PUT", "/api/settings/key", {"key": KEY + " with space"})
    app.json("DELETE", "/api/settings/key")
    assert KEY not in caplog.text


def test_a_fault_in_keeping_the_key_does_not_say_the_key(app, monkeypatch, caplog) -> None:
    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(keys.os, "replace", full)
    status, _, body = app.ask("PUT", "/api/settings/key", json.dumps({"key": KEY}).encode())
    assert status == 500 and KEY.encode() not in body and KEY not in caplog.text
    assert "No space left" in json.loads(body)["error"]


CROSS = [
    {"Origin": "http://elsewhere.example"},
    {"Origin": "null"},
    {"Host": "elsewhere.example"},
    {"Host": "rebound.example:{port}", "Origin": "http://rebound.example:{port}"},
    {"Origin": "http://localhost:{port}"},  # the same machine, and another origin than the one asked
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "http://127.0.0.1:{port}", "Sec-Fetch-Site": "cross-site"},
]


@pytest.mark.parametrize("headers", CROSS)
def test_a_page_of_another_site_can_neither_set_nor_forget_nor_ask_about_the_key(app, own_folder, headers) -> None:
    """Another site open in the same browser can send a request here, and the browser says
    where it came from. None of them is answered, and none changes anything."""
    sent = {name: value.format(port=app.port) for name, value in headers.items()}
    app.json("PUT", "/api/settings/key", {"key": KEY})
    for method, path, payload in (
        ("PUT", "/api/settings/key", {"key": "sk-set-by-another-site"}),
        ("DELETE", "/api/settings/key", None),
        ("GET", "/api/settings", None),
        ("POST", "/api/settings/key", {"key": "sk-set-by-another-site"}),
    ):
        status, body = app.json(method, path, payload, sent)
        assert (status, body) == (403, server.ONLY_LOCAL), (method, path)
    assert (own_folder / "reader.key").read_text() == KEY


@pytest.mark.parametrize("headers", CROSS)
def test_a_page_of_another_site_can_neither_read_nor_change_the_store(app, headers) -> None:
    sent = {name: value.format(port=app.port) for name, value in headers.items()}
    app.json("PUT", "/api/store/control-run/mine", {"name": "kept"})
    for method, path, payload in (
        ("GET", "/api/store/control-run", None),
        ("GET", "/api/store/control-run/mine", None),
        ("PUT", "/api/store/control-run/mine", {"name": "changed"}),
        ("PUT", "/api/store/control-run/theirs", {}),
        ("DELETE", "/api/store/control-run/mine", None),
    ):
        status, body = app.json(method, path, payload, sent)
        assert (status, body) == (403, server.ONLY_LOCAL), (method, path)
    assert app.json("GET", "/api/store/control-run/mine")[1]["doc"] == {"name": "kept"}
    assert [item["id"] for item in app.json("GET", "/api/store/control-run")[1]["items"]] == ["mine"]


def test_this_page_itself_is_answered_as_a_browser_sends_its_requests(app) -> None:
    own = {"Origin": f"http://127.0.0.1:{app.port}", "Sec-Fetch-Site": "same-origin"}
    assert app.json("PUT", "/api/settings/key", {"key": KEY}, own)[0] == 200
    assert app.json("PUT", "/api/store/exploration/a", {}, own)[0] == 200
    assert app.json("GET", "/api/settings", None, {"Sec-Fetch-Site": "same-origin"})[0] == 200


def test_what_is_kept_is_not_to_be_loaded_by_a_page_of_another_origin(app) -> None:
    for path in ("/api/settings", "/api/store/control-run", "/api/store/control-run/none"):
        _, headers, _ = app.ask("GET", path)
        assert headers["cross-origin-resource-policy"] == "same-origin"
        assert "access-control-allow-origin" not in headers
        assert headers["cache-control"] == "no-store" and headers["content-security-policy"] == server.POLICY


def test_a_document_is_kept_read_listed_and_deleted_over_http(app) -> None:
    doc = {"name": "step to 3000 rpm", "gains": {"kp": 0.4}, "trace": [0, 1.5, None], "unit": "°C"}
    status, kept = app.json("PUT", "/api/store/control-run/run-1", doc)
    assert status == 200 and (kept["kind"], kept["id"], kept["name"]) == ("control-run", "run-1", "step to 3000 rpm")
    status, got = app.json("GET", "/api/store/control-run/run-1")
    assert status == 200 and got["doc"] == doc and got["updated"] == kept["updated"]
    status, listed = app.json("GET", "/api/store/control-run")
    assert status == 200 and listed["kind"] == "control-run"
    assert [(item["id"], item["name"]) for item in listed["items"]] == [("run-1", "step to 3000 rpm")]
    assert app.json("DELETE", "/api/store/control-run/run-1") == (
        200,
        {"deleted": True, "kind": "control-run", "id": "run-1"},
    )
    assert app.json("GET", "/api/store/control-run")[1]["items"] == []


def test_a_document_that_is_not_kept_is_404(app) -> None:
    for method in ("GET", "DELETE"):
        assert app.json(method, "/api/store/control-run/never") == (404, {"error": "nothing is kept under that name"})
    assert app.json("GET", "/api/store/control-run/a/b")[0] == 404


@pytest.mark.parametrize("kind", [k for k in KINDS if k not in WRITTEN_HERE])
def test_each_kind_the_store_keeps_is_kept_apart(app, kind) -> None:
    assert app.json("PUT", f"/api/store/{kind}/same-name", {"kind": kind})[0] == 200
    assert app.json("GET", f"/api/store/{kind}/same-name")[1]["doc"] == {"kind": kind}
    others = [other for other in KINDS if other != kind]
    assert all(app.json("GET", f"/api/store/{other}/same-name")[0] == 404 for other in others)


@pytest.mark.parametrize("kind", sorted(WRITTEN_HERE))
def test_a_kind_the_app_writes_itself_is_not_written_from_outside(app, kind) -> None:
    for method, payload in (("PUT", {"summary": "made up"}), ("DELETE", None)):
        status, body = app.json(method, f"/api/store/{kind}/same-name", payload)
        assert status == 403 and body["error"], method
    assert app.json("GET", f"/api/store/{kind}/same-name")[0] == 404


@pytest.mark.parametrize(
    "kind", ["device", "settings", "control-runs", "CONTROL-RUN", "..", "%2e%2e", "control-run%2Fx"]
)
def test_a_kind_outside_the_list_is_refused_with_the_kinds_kept(app, kind) -> None:
    for method, path, payload in (
        ("GET", f"/api/store/{kind}", None),
        ("GET", f"/api/store/{kind}/a", None),
        ("PUT", f"/api/store/{kind}/a", {}),
        ("DELETE", f"/api/store/{kind}/a", None),
    ):
        status, body = app.json(method, path, payload)
        assert status == 422 and body["field"] == "kind" and all(k in body["fix"] for k in KINDS), (method, path)


@pytest.mark.parametrize("name", [".hidden", "a%20b", "a%2Fb", "-a", "a" * 65, "..", "a;b", "a%00"])
def test_a_name_that_is_not_plain_is_refused(app, name) -> None:
    for method, payload in (("GET", None), ("PUT", {}), ("DELETE", None)):
        status, body = app.json(method, f"/api/store/control-run/{name}", payload)
        assert status == 422 and body["field"] == "id" and body["fix"], method


def test_a_document_past_a_megabyte_is_refused_unread_and_one_within_it_is_kept(app) -> None:
    status, headers, body = app.ask("PUT", "/api/store/exploration/big", None, {"Content-Length": str(MAX_DOC + 1)})
    assert status == 422 and json.loads(body) == asgi.TOO_LARGE_DOC and headers["connection"] == "close"
    text = "x" * (MAX_DOC - 100)
    assert app.json("PUT", "/api/store/exploration/big", {"t": text})[0] == 200
    assert app.json("GET", "/api/store/exploration/big")[1]["doc"] == {"t": text}


@pytest.mark.parametrize("body", [b"[1, 2]", b'"text"', b"{not json", b'{"x": NaN}'])
def test_what_is_not_a_json_object_is_not_kept(app, body) -> None:
    status, _, said = app.ask("PUT", "/api/store/control-run/a", body)
    assert status in (400, 422) and (json.loads(said).get("error") or json.loads(said)["refused"])
    assert app.json("GET", "/api/store/control-run")[1]["items"] == []


def test_the_store_and_the_settings_take_only_their_own_methods(app) -> None:
    for method, path in (
        ("POST", "/api/settings"),
        ("PUT", "/api/settings"),
        ("DELETE", "/api/settings"),
        ("GET", "/api/settings/key"),
        ("POST", "/api/settings/key"),
        ("POST", "/api/store/control-run"),
        ("PUT", "/api/store/control-run"),
        ("DELETE", "/api/store/control-run"),
        ("POST", "/api/store/control-run/a"),
    ):
        status, body = app.json(method, path, {"key": KEY})
        assert status == 405 and "not answered" in body["error"], (method, path)


def test_keys_set_from_many_requests_at_once_are_each_answered_and_one_is_kept(app, own_folder) -> None:
    from concurrent.futures import ThreadPoolExecutor

    sent = [f"{KEY}-{n:02d}" + "x" * n for n in range(50)]
    with ThreadPoolExecutor(50) as pool:
        statuses = list(pool.map(lambda key: app.json("PUT", "/api/settings/key", {"key": key})[0], sent * 2))
    assert statuses == [200] * 100
    assert (own_folder / "reader.key").read_text() in sent


def test_a_fault_that_repeats_a_key_is_answered_and_logged_without_it(tmp_path, monkeypatch, caplog) -> None:
    """Words that leave the process, from whichever server, and words logged, never hold the
    saved key or the environment's."""
    from test_app_http import builtin

    from motionsim.app import run
    from motionsim.service import routes

    monkeypatch.setenv("OPENAI_API_KEY", KEY + "-shell")
    keys.use_saved()
    keys.save(KEY + "-saved")

    def broken(data, ws):
        raise RuntimeError(f"the service said: no to {KEY}-saved and to {KEY}-shell")

    monkeypatch.setitem(routes.ROUTES, "/api/suggest", broken)
    with served(tmp_path / "asgi") as asgi, builtin(tmp_path / "builtin") as stdlib:
        for running in (asgi, stdlib):
            status, _, body = running.ask("POST", "/api/suggest", b'{"device": "example"}')
            assert status == 500 and b"[key]" in body and KEY.encode() not in body
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    root = logging.getLogger()
    root.addHandler(handler)
    level = root.level
    try:
        run.logs("debug")
        logging.getLogger("motionsim").exception("fault with %s", KEY + "-saved", exc_info=RuntimeError(KEY + "-shell"))
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    assert "fault with [key]" in out.getvalue() and KEY not in out.getvalue()


def test_a_put_with_no_document_is_refused_and_keeps_nothing(app) -> None:
    for body in (b"", None):
        status, _, said = app.ask("PUT", "/api/store/control-run/a", body, {"Content-Length": "0"})
        assert status == 400 and "no document" in json.loads(said)["error"]
    assert app.json("GET", "/api/store/control-run")[1]["items"] == []


def test_a_page_that_goes_mid_request_is_no_fault(app, caplog) -> None:
    import socket
    import time

    with socket.create_connection(("127.0.0.1", app.port), timeout=10) as raw:
        raw.sendall(
            f"PUT /api/store/control-run/a HTTP/1.1\r\nHost: 127.0.0.1:{app.port}\r\nContent-Length: 1000\r\n\r\n{{".encode()
        )
        time.sleep(0.3)
    time.sleep(0.5)
    assert app.ask("GET", "/api/setup")[0] == 200
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
