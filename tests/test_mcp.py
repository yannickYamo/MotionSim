"""The coding agent's MCP server at /mcp, driven end to end by the official MCP client over
streamable HTTP, as Claude Code drives it: refused without the access code or from another
name; its tools read the session the page shows and write it as the page does, refusals by
their field, every write logged with the source "agent" and undone with `undo`."""

from __future__ import annotations

import asyncio
import http.client
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")
pytest.importorskip("mcp", reason="the agent's server needs the app extra")

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from test_app_http import served as running

from motionsim.app import access, keys

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
FAKE_KEY = "sk-ant-test-0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MOTIONSIM_HOME", str(tmp_path / "home"))
    with running(tmp_path) as served:
        yield served


def post(port: int, headers: dict, body: dict = INIT) -> tuple[int, dict, bytes]:
    link = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        sent = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **headers}
        link.request("POST", "/mcp", json.dumps(body), sent)
        r = link.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        link.close()


class Agent:
    """One connection of the MCP client, with the code, and every text it was told."""

    def __init__(self, port: int, code: str | None = None) -> None:
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.code = code or access.code()
        self.told: list[str] = []

    def run(self, work):
        async def go():
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {self.code}"})
            async with Client(streamable_http_client(self.url, http_client=http), mode="legacy") as client:
                return await work(client)

        return asyncio.run(go())

    def call(self, tool: str, args: dict | None = None) -> tuple[bool, dict]:
        async def work(client):
            return await client.call_tool(tool, args or {})

        result = self.run(work)
        text = "".join(getattr(c, "text", "") for c in result.content)
        self.told.append(text)
        body = text[text.index("{") :] if "{" in text else text
        return result.is_error, json.loads(body)


def test_mcp_without_the_access_code_is_401_and_says_nothing_more(app) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {access.code()}"}):
        status, said, body = post(app.port, headers)
        assert status == 401 and said["www-authenticate"].startswith("Bearer")
        assert access.code() not in body.decode()


def test_mcp_from_another_name_or_another_site_is_403_even_with_the_code(app) -> None:
    good = {"Authorization": f"Bearer {access.code()}"}
    assert post(app.port, {**good, "Host": "evil.example:4310"})[0] == 403
    assert post(app.port, {**good, "Origin": "http://evil.example"})[0] == 403
    assert post(app.port, good)[0] == 200


def test_a_new_code_shuts_out_the_old_one(app) -> None:
    old = access.code()
    access.regenerate()
    assert post(app.port, {"Authorization": f"Bearer {old}"})[0] == 401
    assert post(app.port, {"Authorization": f"Bearer {access.code()}"})[0] == 200


def test_the_server_lists_its_tools_guides_and_prompts(app) -> None:
    async def work(client):
        tools = (await client.list_tools()).tools
        resources = (await client.list_resources()).resources
        prompts = (await client.list_prompts()).prompts
        guide = await client.read_resource("motionsim://guide/agent")
        return tools, resources, prompts, guide

    tools, resources, prompts, guide = Agent(app.port).run(work)
    names = {t.name for t in tools}
    expected = {
        "get_session", "get_results", "list_parts", "list_applications", "list_schemes", "get_lab",
        "get_run_series", "list_kept", "list_explorations", "get_exploration", "choose_part", "set_design",
        "set_scheme", "set_param", "revert_to_tuned", "set_test", "run_test", "run_exploration", "keep_run",
        "export_report", "export_scheme", "undo",
    }  # fmt: skip
    assert expected <= names and names - expected <= {"export_c", "export_port"}
    schema = next(t for t in tools if t.name == "get_run_series").input_schema
    assert {"wires", "t0", "t1", "max_points"} <= set(schema["properties"])
    assert {str(r.uri) for r in resources} == {"motionsim://guide/user", "motionsim://guide/agent"}
    assert {p.name for p in prompts} == {"review_drive_design", "tune_for_phase_margin", "lowest_loss_scheme"}
    assert "motionsim" in guide.contents[0].text.lower()


def test_the_agent_sets_up_a_design_the_page_reads_and_undoes_a_change(app) -> None:
    agent = Agent(app.port)
    failed, empty = agent.call("get_session")
    assert not failed and empty["design"]["state"] == "empty"
    failed, refused = agent.call("get_results")
    assert failed and refused["field"] == "part"

    failed, chosen = agent.call("choose_part", {"part": "example"})
    assert not failed and chosen["now"]["part"] == "example" and chosen["change_id"]
    failed, changed = agent.call("set_design", {"fields": {"v_dc": 300, "f_khz": 12}})
    assert not failed and "Supply voltage 325 V → 300 V" in changed["what"]

    # The page reads what the agent set, and the activity says who set it.
    _, now = app.json("GET", "/api/session")
    assert now["doc"]["design"]["conditions"]["v_dc"] == 300 and now["source"] == "agent"
    _, activity = app.json("GET", "/api/session/activity")
    assert [e["source"] for e in activity["items"]] == ["agent", "agent"]

    failed, undone = agent.call("undo", {"change_id": changed["change_id"]})
    assert not failed and undone["what"].startswith("Undid:")
    _, now = app.json("GET", "/api/session")
    assert now["doc"]["design"]["conditions"]["v_dc"] == 325 and now["source"] == "undo"

    failed, results = agent.call("get_results")
    assert not failed and results["parts"][0]["id"] == "example" and results["parts"][0]["loss_W"] > 0
    assert {"level", "topic", "message"} <= set(results["parts"][0]["checks"][0])


def test_the_agent_works_on_a_part_set_mended_where_the_page_left_a_part_unticked(app) -> None:
    agent = Agent(app.port)
    agent.call("choose_part", {"part": "example"})
    _, now = app.json("GET", "/api/session")
    design = {**now["doc"]["design"], "devices": [], "lead": ""}  # the part on the page, not ticked
    app.json("PUT", "/api/session", {"base": now["version"], "doc": {"design": design}, "client": "tab"})
    failed, _ = agent.call("set_design", {"fields": {"v_dc": 300}})
    assert not failed
    _, now = app.json("GET", "/api/session")
    d = now["doc"]["design"]
    assert (d["added"], d["devices"], d["lead"]) == (["example"], ["example"], "example")


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"v_dc": "lots"}, "v_dc"),
        ({"v_dc": 5000}, "v_dc"),
        ({"cooling": "water"}, "cooling"),
        ({"cooling": "heatsink"}, "rth_sink"),
        ({"motor.wings": 2}, "motor.wings"),
        ({"no_such": 1}, "no_such"),
        ({"application": "rocket"}, "application"),
    ],
)
def test_a_write_the_page_would_refuse_is_a_tool_error_with_its_field_and_changes_nothing(app, fields, field) -> None:
    agent = Agent(app.port)
    agent.call("choose_part", {"part": "example"})
    _, before = app.json("GET", "/api/session")
    failed, refused = agent.call("set_design", {"fields": fields})
    assert failed and refused["field"] == field and refused["fix"]
    _, after = app.json("GET", "/api/session")
    assert after["version"] == before["version"]


def test_the_lab_is_tuned_run_read_kept_and_exported_and_nothing_secret_is_said(app, tmp_path) -> None:
    keys.save(FAKE_KEY)
    agent = Agent(app.port)
    agent.call("choose_part", {"part": "example"})
    failed, schemes = agent.call("list_schemes")
    assert not failed and schemes["recommended"] in {s["id"] for s in schemes["schemes"]}
    failed, lab = agent.call("get_lab")
    assert not failed and lab["loops"]["current_q"]["phase_margin_deg"] > 0
    block = next(b for b in lab["blocks"] if b["kind"] == "current_discrete_dq" or b["name"] == "current")
    name, value = next(iter(block["params"].items()))
    failed, refused = agent.call("set_param", {"block": block["name"], "param": "no_such", "value": 1})
    assert failed and refused["field"] == f"scheme.blocks.{block['name']}.no_such"
    # A number written as text, as a model may send it, is read as the number: never refused.
    failed, tuned = agent.call("set_param", {"block": block["name"], "param": name, "value": f"{value * 0.9:.6g}"})
    assert not failed and "current_q" in tuned["loops"], tuned
    failed, tuned = agent.call("set_param", {"block": block["name"], "param": name, "value": value * 0.8})
    assert not failed and "current_q" in tuned["loops"]
    _, lab = agent.call("get_lab")
    assert lab["edits_vs_tuned"][0]["param"] == name

    failed, ran = agent.call("run_test")
    assert not failed and ran["run"]["level"] in ("ok", "caution", "fail", "undecided") and ran["run"]["verdict"]
    _, wires = agent.call("get_run_series")
    some = [w["name"] for w in wires["wires"][:2]]
    _, series = agent.call("get_run_series", {"wires": some, "max_points": 5})
    assert series["points"] <= 5 and all(len(v) == series["points"] for v in series["wires"].values())
    failed, refused = agent.call("get_run_series", {"wires": some, "max_points": 100000})
    assert failed and refused["field"] == "max_points"

    failed, kept = agent.call("keep_run", {"name": "gain lowered"})
    assert not failed
    _, listed = agent.call("list_kept")
    assert [r["name"] for r in listed["runs"]] == ["gain lowered"]
    agent.call("undo", {"change_id": kept["change_id"]})
    assert agent.call("list_kept")[1]["runs"] == []

    _, drawn = agent.call("export_scheme", {"format": "svg"})
    status, _, body = app.ask("GET", drawn["url"].split(f":{app.port}", 1)[1])
    assert status == 200 and body.startswith(b"<svg")
    _, report = agent.call("export_report", {"format": "pdf"})
    assert Path(report["path"]).read_bytes()[:5] == b"%PDF-"

    failed, back = agent.call("revert_to_tuned")
    assert not failed and back["change_id"]
    told = "\n".join(agent.told)
    assert access.code() not in told and FAKE_KEY not in told


def test_the_agent_exports_the_port_to_a_chip_with_what_was_checked(app, monkeypatch) -> None:
    from motionsim.control.codegen import port, replay
    from motionsim.observe import provider

    if replay.compiler() is None:
        pytest.skip("no C compiler: the port is gated by the replay")
    from test_export_port import a_port

    asked = []

    def model(system, text, shape, max_tokens):  # never a real model here
        asked.append(shape)
        return a_port()

    monkeypatch.setattr(port, "ask_model", model)
    monkeypatch.setattr(provider, "chosen", lambda env=None: provider.Reader("anthropic", "fake"))
    monkeypatch.setenv("MOTIONSIM_FIRMWARE_URL", "off")
    agent = Agent(app.port)
    agent.call("choose_part", {"part": "example"})
    failed, made = agent.call("export_port", {"chip": "STM32G474RE"})
    assert not failed, made
    assert made["status"] == "not compiled / not run on hardware" and made["chip"]["name"] == "STM32G4"
    assert Path(made["path"]).read_bytes()[:2] == b"PK" and asked == [port.Port]
    assert any("Not run on hardware" in n for n in made["not_checked"])
