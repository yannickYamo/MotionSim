"""The shared session: versions, a stale write rebased or winning and saying so, the agent's
changes kept with their figures before and after, Undo, and the page's addresses for it."""

from __future__ import annotations

import itertools
import json
import random
import threading

import pytest

from motionsim.app.session import Session, Stale, diff, shown
from motionsim.app.store import Store
from motionsim.errors import Refusal

V = {"design.conditions.v_dc": {"label": "Supply voltage", "unit": "V"}}


@pytest.fixture
def session(tmp_path) -> Session:
    return Session(Store(tmp_path / "s.db"))


def design(v_dc=48, rpm=1000, **more) -> dict:
    return {"design": {"conditions": {"v_dc": v_dc, "rpm": rpm}, **more}}


def test_an_empty_session_is_version_nought_and_each_change_is_one_more(session) -> None:
    assert session.current() == {"version": 0, "doc": {"design": None, "lab": None}, "at": None, "source": None}
    assert session.write(design(), 0, "page")["version"] == 1
    assert session.write(design(v_dc=60), 1, "page")["version"] == 2
    # Writing what is there already changes nothing, and makes no version.
    same = session.write(design(v_dc=60), 2, "page")
    assert same["version"] == 2 and same["changed"] == []


def test_a_stale_write_that_touches_other_figures_is_rebased_and_loses_nothing(session) -> None:
    session.write(design(), 0, "page")
    session.write(design(v_dc=60), None, "agent", labels=V)  # version 2, the agent's
    out = session.write(design(rpm=3000), 1, "page")  # made on version 1, before the agent's change
    assert out["rebased"] and out["overwrote"] == []
    assert session.current()["doc"]["design"]["conditions"] == {"v_dc": 60, "rpm": 3000}


def test_a_stale_write_on_the_same_figure_wins_and_says_whose_it_replaced(session) -> None:
    session.write(design(), 0, "page")
    agent = session.write(design(v_dc=60), None, "agent", labels=V)
    out = session.write(design(v_dc=24), 1, "page")
    assert out["overwrote"] == [{"path": "design.conditions.v_dc", "was": 60, "by": "agent"}]
    assert session.current()["doc"]["design"]["conditions"]["v_dc"] == 24
    # The agent's entry says the user replaced it.
    entry = session.entry(agent["change"]["id"])
    assert entry["overwritten"]["figures"] == ["design.conditions.v_dc"]


def test_an_agent_change_is_kept_with_its_figures_and_said_in_a_line(session) -> None:
    session.write(design(), 0, "page")
    out = session.write(design(v_dc=60), None, "agent", labels=V)
    entry = out["change"]
    assert entry["what"] == "Supply voltage 48 V → 60 V"
    figure = entry["figures"][0]
    assert (figure["path"], figure["label"], figure["unit"], figure["old"], figure["new"]) == (
        "design.conditions.v_dc",
        "Supply voltage",
        "V",
        48,
        60,
    )
    assert [e["id"] for e in session.activity()] == [entry["id"]]
    # The page's own writes are not entries: it has its own undo.
    session.write(design(v_dc=70), None, "page")
    assert len(session.activity()) == 1


def test_undo_puts_back_what_the_change_set_and_is_itself_an_entry(session) -> None:
    session.write(design(), 0, "page")
    change = session.write(design(v_dc=60), None, "agent", labels=V)["change"]
    out = session.undo(change["id"])
    assert session.current()["doc"]["design"]["conditions"]["v_dc"] == 48
    assert out["change"]["kind"] == "undo" and out["change"]["undoes"] == change["id"]
    assert session.entry(change["id"])["undone"]["by"] == out["change"]["id"]
    with pytest.raises(Refusal, match="undone already"):
        session.undo(change["id"])


def test_undo_is_refused_where_the_figure_was_changed_again_since(session) -> None:
    session.write(design(), 0, "page")
    change = session.write(design(v_dc=60), None, "agent", labels=V)["change"]
    session.write(design(v_dc=72), None, "page")
    with pytest.raises(Stale) as refused:
        session.undo(change["id"])
    assert refused.value.field == "design.conditions.v_dc" and "72" in refused.value.reason
    assert session.current()["doc"]["design"]["conditions"]["v_dc"] == 72


def test_a_change_that_began_a_part_is_undone_figure_by_figure_and_then_whole(session) -> None:
    first = session.write({"lab": {"v": 1, "scheme": "a", "figures": {}}}, None, "agent")["change"]
    second = session.write({"lab": {"v": 1, "scheme": "a", "figures": {}, "last_run": {"level": "ok"}}}, None, "agent")
    # The second change set one figure; undoing the first alone is refused only for figures it set.
    assert [f["path"] for f in second["change"]["figures"]] == ["lab.last_run.level"]
    session.undo(second["change"]["id"])
    assert "last_run" not in session.current()["doc"]["lab"]
    session.undo(first["id"])
    assert session.current()["doc"] == {"design": None, "lab": None}


def test_listeners_hear_every_write_and_a_failing_one_stops_nobody(session) -> None:
    heard: list[dict] = []
    session.listeners.append(lambda e: 1 / 0)
    session.listeners.append(heard.append)
    session.write(design(), 0, "page", client="tab-1")
    assert heard[0]["type"] == "session" and heard[0]["client"] == "tab-1" and heard[0]["version"] == 1


def test_what_is_not_a_session_is_refused_by_its_field(session) -> None:
    for doc, field in (([], "doc"), ({"other": {}}, "other"), ({"design": 3}, "design")):
        with pytest.raises(Refusal) as refused:
            session.write(doc, None, "page")  # type: ignore[arg-type]
        assert refused.value.field == field
    with pytest.raises(Refusal, match="never written"):
        session.write(design(), 9, "page")


def test_writes_from_several_threads_each_make_their_own_version(session) -> None:
    session.write({"design": {"n": {}}}, 0, "page")

    def one(k: int) -> None:
        session.write({"design": {"n": {str(k): k}}}, 1, "page")

    threads = [threading.Thread(target=one, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert session.current()["version"] == 9


def test_diff_names_each_figure_and_a_figure_that_became_an_object_whole() -> None:
    assert diff({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3}}) == {("a", "c"): (2, 3)}
    assert diff({"a": 1}, {"a": {"b": 2}}) == {("a",): (1, {"b": 2})}


# -- over HTTP and the WebSocket --------------------------------------------------------------------

pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")


@pytest.fixture
def served(tmp_path, monkeypatch):
    from test_app_http import served as running

    monkeypatch.setenv("MOTIONSIM_HOME", str(tmp_path / "home"))
    with running(tmp_path) as app:
        yield app


def test_the_page_reads_writes_and_undoes_the_session_over_http(served) -> None:
    status, now = served.json("GET", "/api/session")
    assert status == 200 and now["version"] == 0
    status, out = served.json("PUT", "/api/session", {"base": 0, "doc": design(), "client": "tab"})
    assert (
        status == 200 and out["version"] == 1 and out["changed"] == ["design.conditions.rpm", "design.conditions.v_dc"]
    )
    status, out = served.json("PUT", "/api/session", {"base": "one", "doc": design()})
    assert status == 422 and out["field"] == "base"
    status, out = served.json("POST", "/api/session/undo", {"change": "nope"})
    assert status == 422 and out["field"] == "change_id"
    status, listed = served.json("GET", "/api/session/activity")
    assert status == 200 and listed == {"items": []}


def test_another_site_in_the_browser_cannot_read_or_write_the_session(served) -> None:
    cross = {"Sec-Fetch-Site": "cross-site"}
    for method, path in (("GET", "/api/session"), ("PUT", "/api/session"), ("GET", "/api/settings/agent")):
        status, _ = served.json(method, path, {"doc": {}} if method == "PUT" else None, cross)
        assert status == 403
    status, _ = served.json("GET", "/api/session", headers={"Host": "evil.example:4310"})
    assert status == 403


def test_the_agents_settings_show_the_code_and_a_new_one_replaces_it(served) -> None:
    status, first = served.json("GET", "/api/settings/agent")
    assert status == 200 and len(first["code"]) >= 32 and first["write"] is True
    assert first["command"].startswith("claude mcp add --transport http motionsim http://127.0.0.1:")
    assert first["code"] in first["command"]
    status, second = served.json("POST", "/api/settings/agent/code")
    assert status == 200 and second["code"] != first["code"]


def test_the_socket_tells_the_page_of_each_change_as_it_is_made(served) -> None:
    from test_app_stream import Socket

    page = Socket(served.port, target="/ws/session")
    try:
        got = [page.message()]
        served.json("PUT", "/api/session", {"doc": design()})
        got.append(page.message())
    finally:
        page.close()
    assert got[0]["type"] == "hello" and got[0]["version"] == 0 and isinstance(got[0]["build"], str)
    assert got[1]["type"] == "session" and got[1]["version"] == 1 and got[1]["source"] == "page"


def test_an_exported_file_is_served_and_nothing_outside_its_folder(served, tmp_path) -> None:
    folder = tmp_path / "home" / "exports"
    folder.mkdir(parents=True)
    (folder / "report.md").write_text("# hi")
    status, headers, body = served.ask("GET", "/api/exports/report.md")
    assert status == 200 and body == b"# hi" and "attachment" in headers["content-disposition"]
    for name in ("..%2Fmotionsim.db", "nothing.md", "report.exe"):
        assert served.ask("GET", f"/api/exports/{name}")[0] == 404
    assert json.loads(served.ask("PUT", "/api/exports/report.md", b"{}")[2])["error"]


def _page_named(tmp_path, monkeypatch, build: str):
    """A built page of its own, naming a build, served in place of the real one."""
    from motionsim import server as builtin

    root = tmp_path / "webui"
    root.mkdir(exist_ok=True)
    tag = f'<meta name="motionsim-build" content="{build}" />' if build else ""
    (root / "index.html").write_text(f"<!doctype html><html><head><title>MotionSim</title>{tag}</head></html>")
    monkeypatch.setattr(builtin, "WEB_ROOT", root)
    return root


def test_the_build_served_is_read_from_the_page_and_again_when_it_is_built_anew(tmp_path, monkeypatch) -> None:
    import os

    from motionsim.app.build import build_id, older

    root = _page_named(tmp_path, monkeypatch, "aaaa1111")
    assert build_id() == "aaaa1111"
    assert older("bbbb2222") and not older("aaaa1111") and not older(None) and not older("")
    page = root / "index.html"
    page.write_text(page.read_text().replace("aaaa1111", "cccc33334444"))
    os.utime(page, ns=(1, 1))  # another time, so a change within the same tick is seen too
    assert build_id() == "cccc33334444"
    _page_named(tmp_path, monkeypatch, "")
    os.utime(root / "index.html", ns=(2, 2))
    assert build_id() == "" and not older("bbbb2222")


def test_every_answer_names_the_build_and_a_write_of_an_older_one_is_refused(served, tmp_path, monkeypatch) -> None:
    _page_named(tmp_path, monkeypatch, "aaaa1111")
    status, headers, _ = served.ask("GET", "/api/session")
    assert status == 200 and headers["x-motionsim-build"] == "aaaa1111"
    old = {"X-MotionSim-Build": "0000ffff"}
    status, out = served.json("PUT", "/api/session", {"base": 0, "doc": design(), "client": "tab"}, old)
    assert status == 409 and out["field"] == "build" and out["fix"] == "reload the page"
    assert served.json("GET", "/api/session")[1]["version"] == 0
    status, out = served.json("POST", "/api/session/undo", {"change": "x"}, old)
    assert status == 409
    # The page of this build, and an agent or a script that names none, write as before.
    same = {"X-MotionSim-Build": "aaaa1111"}
    assert served.json("PUT", "/api/session", {"base": 0, "doc": design(), "client": "tab"}, same)[0] == 200
    assert served.json("PUT", "/api/session", {"base": 1, "doc": design(rpm=7)})[0] == 200


def test_a_write_sent_as_the_page_closes_is_taken(served) -> None:
    """A keepalive request is an ordinary same-origin PUT: it carries the page's Origin and
    Sec-Fetch-Site, which the checks of where a request comes from take."""
    origin = {"Origin": f"http://127.0.0.1:{served.port}", "Sec-Fetch-Site": "same-origin"}
    status, out = served.json("PUT", "/api/session", {"base": 0, "doc": design(), "client": "tab"}, origin)
    assert status == 200 and out["version"] == 1


def _setup(tmp_path):
    from motionsim.service.presets import setup as setup_of
    from motionsim.service.workspace import Workspace

    return setup_of(Workspace(tmp_path / "devices"))


def test_every_figure_a_write_can_touch_has_a_label_and_the_bookkeeping_is_never_said(tmp_path) -> None:
    from motionsim.app import pagestate
    from motionsim.app.session import _leaves, label_of

    setup = _setup(tmp_path)
    state = pagestate.initial(setup)
    pagestate.set_fields(state, {"v_dc": 60, "rpm": 2500}, setup)
    labels = pagestate.labels_of(state, setup)
    for path in _leaves({"design": pagestate.content(state)}):
        label = label_of(path, labels)
        assert label.get("label") and label["label"] != ".".join(path), ".".join(path)


def test_an_agent_change_says_its_figures_and_not_the_pages_bookkeeping_and_undo_restores_both(tmp_path) -> None:
    from motionsim.app import pagestate

    setup = _setup(tmp_path)
    session = Session(Store(tmp_path / "s.db"))
    state = pagestate.initial(setup)
    pagestate.set_fields(state, {"v_dc": 52}, setup)
    session.write({"design": pagestate.content(state)}, None, "page")
    before = session.current()["doc"]
    pagestate.set_fields(state, {"v_dc": 60}, setup)
    out = session.write({"design": pagestate.content(state)}, None, "agent", labels=pagestate.labels_of(state, setup))
    entry = out["change"]
    assert any(f.get("kept") and "pointOf" in f["path"] for f in entry["figures"])
    sent = shown(entry)
    assert [f["label"] for f in sent["figures"]] == ["Supply voltage"]
    assert "pointOf" not in entry["what"] and entry["what"].startswith("Supply voltage")
    undone = session.undo(entry["id"])
    assert session.current()["doc"] == before
    assert [f["label"] for f in shown(undone["change"])["figures"]] == ["Supply voltage"]


def test_the_access_code_is_made_when_the_app_starts(tmp_path, monkeypatch) -> None:
    from motionsim.app import access
    from motionsim.app.server import create_app

    monkeypatch.setenv("MOTIONSIM_HOME", str(tmp_path / "home"))
    assert not access.path().exists()
    create_app()
    assert access.path().is_file() and len(access.path().read_text().strip()) >= 32


def parts(added, devices, lead, **more) -> dict:
    return {"design": {"added": added, "devices": devices, "lead": lead, "conditions": {"v_dc": 48}, **more}}


def test_a_stale_write_takes_the_parts_on_the_page_and_the_parts_ticked_as_one(session) -> None:
    session.write(parts(["a", "b"], ["a"], "a"), 0, "page")
    # Another tab unticks a and ticks b; this tab, on the version before, takes b off the page.
    session.write(parts(["a", "b"], ["b"], "b"), None, "page")
    out = session.write(parts(["a"], ["a"], "a"), 1, "page")
    assert out["rebased"]
    d = session.current()["doc"]["design"]
    # Figure by figure this would be a on the page and b ticked: the set is the write's, whole.
    assert (d["added"], d["devices"], d["lead"]) == (["a"], ["a"], "a")
    assert {o["path"] for o in out["overwrote"]} == {"design.devices", "design.lead"}


def test_a_stale_write_that_leaves_the_parts_alone_keeps_the_latest_set_whole(session) -> None:
    session.write(parts(["a"], ["a"], "a"), 0, "page")
    session.write(parts(["a", "b"], ["a", "b"], "b"), None, "agent")
    out = session.write(parts(["a"], ["a"], "a", **{"conditions": {"v_dc": 60}}), 1, "page")
    assert out["rebased"] and out["overwrote"] == []
    d = session.current()["doc"]["design"]
    assert (d["added"], d["devices"], d["lead"], d["conditions"]["v_dc"]) == (["a", "b"], ["a", "b"], "b", 60)


def test_the_kind_of_motor_and_its_figures_move_as_one(session) -> None:
    motors = {"pmsm": {"kv": 100}, "bldc": {"kt": 0.09}}
    session.write({"design": {"kind": "pmsm", "motors": motors, "conditions": {"v_dc": 48}}}, 0, "page")
    session.write({"design": {"kind": "bldc", "motors": motors, "conditions": {"v_dc": 48}}}, None, "agent")
    mine = {"pmsm": {"kv": 80}, "bldc": {"kt": 0.09}}
    out = session.write({"design": {"kind": "pmsm", "motors": mine, "conditions": {"v_dc": 48}}}, 1, "page")
    d = session.current()["doc"]["design"]
    assert (d["kind"], d["motors"]["pmsm"]["kv"]) == ("pmsm", 80)
    assert [o["path"] for o in out["overwrote"]] == ["design.kind"]


def test_no_interleaving_of_stale_writes_leaves_a_part_on_the_page_unticked(session) -> None:
    """Two writers, each holding a whole part set of its own, write in every order on versions
    as stale as they come: every version keeps each part ticked on the page, and a page with
    parts has one ticked."""
    rng = random.Random(7)
    ids = ["a", "b", "c"]
    sets = []
    for n in range(4):
        for added in itertools.combinations(ids, n):
            for k in range(1, len(added) + 1):
                for devices in itertools.combinations(added, k):
                    sets.append((list(added), list(devices), devices[0]))
    sets.append(([], [], ""))
    session.write(parts(*sets[0]), 0, "page")
    bases = [1]
    for _ in range(400):
        added, devices, lead = rng.choice(sets)
        extra = {"conditions": {"v_dc": rng.choice([24, 48, 60])}}
        session.write(parts(added, devices, lead, **extra), rng.choice(bases[-6:]), rng.choice(["page", "agent"]))
        bases.append(session.current()["version"])
        d = session.current()["doc"]["design"]
        assert set(d["devices"]) <= set(d["added"]), d
        assert bool(d["added"]) == bool(d["devices"]), d
        assert d["lead"] in d["devices"] or d["lead"] == "" == "".join(d["devices"]), d
