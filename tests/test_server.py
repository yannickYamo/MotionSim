"""The local page's interface: the shapes it returns, and how it refuses."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from motionsim import page, server
from motionsim.device import save_device
from test_mosfet import fet

EXAMPLE = Path(__file__).parent.parent / "examples" / "synthetic_igbt_600v_30a.yaml"


@pytest.fixture()
def workspace(tmp_path, monkeypatch) -> server.Workspace:
    save_device(fet(), tmp_path / "transistor.device.yaml")
    return server.Workspace(tmp_path)


def request(workspace: server.Workspace, kind: str = "pmsm", **changes) -> dict:
    kinds = server.setup(workspace)["motors"]
    return {
        "motor": {"type": kind, **kinds[kind]["values"]},
        "conditions": {**kinds[kind]["start"], "t_sink": 60, **changes},
    }


def test_setup_offers_every_motor_with_values_that_run(workspace) -> None:
    info = server.setup(workspace)
    assert set(info["motors"]) == {"pmsm", "bldc", "synrm", "induction", "dc", "dc_series", "stepper"}
    assert [d["id"] for d in info["devices"]] == ["example", "transistor"]
    for kind, motor in info["motors"].items():
        assert {f["key"] for f in motor["fields"]} <= set(motor["values"]) | {"drive"}
        answer = server.stage(request(workspace, kind))  # the first screen is never an error
        assert answer["stage"]["i_peak"] > 0 and answer["advice"]["lines"]


def test_proposal_splits_loss_into_conduction_and_switching(workspace) -> None:
    out = server.proposal({**request(workspace), "devices": ["example"]}, workspace)
    (candidate,) = out["candidates"]
    r = candidate["result"]
    assert r["conduction"] + r["switching"] == pytest.approx(r["loss"])
    assert r["switching"] > 0 and r["tj_range"][0] <= r["tj_peak"] <= r["tj_range"][1]
    assert candidate["needs"] and candidate["checks"] and out["explain"]


def test_a_transistor_without_gate_drive_is_run_with_the_best_resistors_and_says_so(workspace) -> None:
    out = server.proposal({**request(workspace), "devices": ["transistor"]}, workspace)
    (candidate,) = out["candidates"]
    gate = candidate["gate"]
    assert candidate["result"]["loss"] > 0 and gate["kind"] == "chosen"
    assert gate["rg_on"] > 0 and gate["rg_off"] > 0 and gate["v_drive"] > 0
    assert any("lowest loss" in line for line in gate["lines"])
    # A larger resistor of the user's own is kept, and loses more.
    given = request(workspace, v_drive=gate["v_drive"], rg_on=10 * gate["rg_on"], rg_off=10 * gate["rg_off"])
    mine = server.proposal({**given, "devices": ["transistor"]}, workspace)["candidates"][0]
    assert mine["gate"]["kind"] == "given" and mine["result"]["loss"] > candidate["result"]["loss"]


@pytest.mark.parametrize(("changes", "reason", "fix"), [
    ({"rpm": 60000}, "cannot do that from 48 V", "lower the speed"),
    ({"torque": 50}, "more voltage", "or the torque"),
    ({"rpm": 100, "torque": 5}, "limit", "lower the torque"),
    ({"v_dc": -5}, "supply voltage cannot be below", "raise supply voltage"),
    ({"f_sw": "fast"}, "switching frequency is not a number", "enter a value"),
])
def test_impossible_inputs_are_refused_with_what_to_change(workspace, changes, reason, fix) -> None:
    with pytest.raises(server.Refused) as caught:
        server.stage(request(workspace, **changes))
    assert reason in caught.value.reason and fix in caught.value.fix


def test_a_motor_value_that_cannot_be_is_named(workspace) -> None:
    data = request(workspace)
    data["motor"]["pole_pairs"] = -1
    with pytest.raises(server.Refused) as caught:
        server.stage(data)
    assert caught.value.field == "pole_pairs" and "pole pairs" in caught.value.reason


def test_motion_map_and_recommendations(workspace) -> None:
    info = server.setup(workspace)
    base = {**request(workspace), "device": "example"}
    motion = server.cycle({**base, "load": info["load"], "profile": info["profile"]}, workspace)
    assert len(motion["time"]) == len(motion["tj"]) == len(motion["rpm"])
    assert motion["summary"]["peak"] <= motion["summary"]["forever"] + 0.5
    grid = server.speed_torque({**base, "rpm_max": 3000, "torque_max": 1.5, "n": 3}, workspace)
    assert len(grid["loss"]) == 3 and len(grid["loss"][0]) == 3
    topics = [item["topic"] for item in server.recommendations(base, workspace)["items"]]
    assert topics == ["gate resistors", "dead time", "modulation", "heatsink"]


def test_a_motion_nothing_can_follow_is_refused(workspace) -> None:
    info = server.setup(workspace)
    profile = {"segments": [{"duration": 0.001, "speed_start": 0, "speed_end": 5000}]}
    with pytest.raises(server.Refused, match="no instant of this motion"):
        server.cycle({**request(workspace), "device": "example", "load": info["load"],
                      "profile": profile}, workspace)


def test_reading_needs_a_key_and_a_pdf(workspace, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(server.Refused, match="needs a language-model key"):
        server.read_datasheet("part.pdf", b"%PDF-1.7", workspace)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    with pytest.raises(server.Refused, match="not a PDF"):
        server.read_datasheet("part.pdf", b"hello", workspace)


def test_over_http_a_refusal_is_a_422_with_reason_and_fix(workspace) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(workspace))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    address = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path: str, data: dict):
        call = urllib.request.Request(address + path, json.dumps(data).encode(),
                                      {"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(call))

    try:
        assert post("/api/stage", request(workspace))["stage"]["positions"] == 6
        with pytest.raises(urllib.error.HTTPError) as caught:
            post("/api/stage", request(workspace, rpm=60000))
        body = json.load(caught.value)
        assert caught.value.code == 422 and body["refused"] and body["fix"]
        assert json.load(urllib.request.urlopen(address + "/api/setup"))["devices"]
        # Another site in the same browser cannot reach the engine, whatever it posts.
        for headers in ({"Origin": "https://example.com"}, {"Host": "attacker.example"}):
            foreign = urllib.request.Request(address + "/api/read?name=a.pdf", b"%PDF-1.7",
                                             {"Content-Type": "text/plain", **headers})
            with pytest.raises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(foreign)
            assert blocked.value.code == 403
        # Paths outside the page's folder fall back to the page, never to the file system.
        page = urllib.request.urlopen(address + "/../../pyproject.toml").read()
        assert b"[project]" not in page
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_same_interface_as_text_in_text_out(workspace) -> None:
    """The browser's own copy of the engine is called this way, with no server."""
    from motionsim import page

    ok = json.loads(page.call("/api/stage", json.dumps(request(workspace)), workspace))
    assert ok["status"] == 200 and ok["body"]["stage"]["positions"] == 6
    refused = json.loads(page.call("/api/stage", json.dumps(request(workspace, rpm=60000)), workspace))
    assert refused["status"] == 422 and refused["body"]["fix"]
    assert json.loads(page.call("/api/setup", "", workspace))["body"]["devices"]
    assert json.loads(page.call("/api/nowhere", "{}", workspace))["status"] == 404
    assert json.loads(page.call("/api/stage", "not json", workspace))["status"] == 500


def test_a_device_file_can_be_added_and_a_wrong_file_is_refused(workspace) -> None:
    from motionsim import page

    text = EXAMPLE.read_text(encoding="utf-8")
    added = page.add_device("My Part.device.yaml", text, workspace)
    assert added["device"]["id"] == "my-part"
    assert "my-part" in [d["id"] for d in page.setup(workspace)["devices"]]
    with pytest.raises(page.Refused, match="not a device model"):
        page.add_device("notes.yaml", "just: some text", workspace)


def test_the_engine_packed_for_the_browser_is_the_engine_in_this_tree() -> None:
    """The page ships a copy of this package for the browser to run. A change to the
    engine without rebuilding the page would leave the two apart: `cd web && npm run build`."""
    import zipfile

    package = Path(__file__).parent.parent / "src" / "motionsim"
    packed = package / "webui" / "engine" / "motionsim.zip"
    if not packed.exists():
        pytest.skip("the page has not been built")
    with zipfile.ZipFile(packed) as z:
        names = set(z.namelist())
        stale = [n for n in names if z.read(n) != (package.parent / n).read_bytes()]
    source = {
        str(Path("motionsim") / p.relative_to(package)) for p in package.rglob("*")
        if p.suffix in {".py", ".yaml"} and "webui" not in p.parts and "__pycache__" not in p.parts
    }
    assert not stale, f"rebuild the page: {stale[:3]}"
    assert names == source, f"rebuild the page: {sorted(names ^ source)[:3]}"


def test_measured_switching_data_makes_a_second_device_beside_the_first(workspace) -> None:
    from motionsim import page

    data = {"v_dc": 300, "energy_unit": "uJ", "points": [
        {"tj": 25, "current": 10, "e_on": 300, "e_off": 200},
        {"tj": 25, "current": 30, "e_on": 900, "e_off": 600},
    ]}
    added = page.add_measurement("example", "bench.json", json.dumps(data), workspace)
    assert added["device"]["id"] == "example-measured"
    ids = [d["id"] for d in page.setup(workspace)["devices"]]
    assert "example" in ids and "example-measured" in ids
    with pytest.raises(page.Refused, match="not double-pulse data"):
        page.add_measurement("example", "notes.json", '{"hello": 1}', workspace)
    with pytest.raises(page.Refused, match="no device called"):
        page.add_measurement("nothing", "bench.json", json.dumps(data), workspace)


def test_every_load_offered_for_a_motor_can_be_followed_within_its_design_torque(workspace) -> None:
    motors = server.setup(workspace)["motors"]
    for kind, motor in motors.items():
        start = page.STARTING[kind]
        offered = page.load_presets(kind, start["rpm"], start["torque"])
        assert offered and len({p["id"] for p in offered}) == len(offered)
        for preset in offered:
            out = server.cycle({
                "motor": {"type": kind, **motor["values"]}, "conditions": {**start, "t_sink": 60},
                "supply": "battery", "device": "example", "load": preset["load"],
                "profile": {"start_angle_deg": preset["start_angle_deg"], "segments": preset["segments"]},
            }, workspace)
            assert not [c for c in out["checks"] if c["topic"] == "motion"], (kind, preset["id"])
            assert max(abs(t) for t in out["torque"]) <= 1.05 * start["torque"], (kind, preset["id"])
            assert max(abs(n) for n in out["rpm"]) <= 1.001 * start["rpm"], (kind, preset["id"])


def test_one_switching_period_adds_up_to_the_average_loss() -> None:
    """The period drawn on the page is the loss model's own: for a switch that is on for the
    same share of every period at one current, its three energies times the switching
    frequency are the average losses."""
    import numpy as np

    from motionsim.device import load_device
    from motionsim.engine.modulation import Role
    from motionsim.engine.solver import OperatingPoint, _position_losses, switching_period

    device = load_device(server.EXAMPLE)
    op = OperatingPoint(v_dc=300.0, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)
    n = np.ones(8)
    role = Role("held", 1, 12.0 * n, 0.4 * n, 0.0 * n, n, 0.0 * n)
    sw, _, _, _ = _position_losses(device, role, op, 90.0, 90.0)
    one = switching_period(device, role, op, 90.0, 90.0)
    assert one["current"] == 12.0 and one["duty"] == 0.4
    assert one["p_on"] * one["duty"] == pytest.approx(sw.conduction)
    assert one["e_on"] * op.f_sw == pytest.approx(sw.turn_on)
    assert one["e_off"] * op.f_sw == pytest.approx(sw.turn_off)


def test_an_open_loop_start_holds_its_current_until_the_handover_and_heats_the_stage(workspace) -> None:
    motors = server.setup(workspace)["motors"]
    start = page.STARTING["pmsm"]
    fan = next(p for p in page.load_presets("pmsm", start["rpm"], start["torque"]) if p["id"] == "fan")
    request_ = {
        "motor": {"type": "pmsm", **motors["pmsm"]["values"]}, "conditions": {**start, "t_sink": 60},
        "supply": "battery", "device": "example", "load": fan["load"],
        "profile": {"start_angle_deg": 0, "segments": fan["segments"]},
    }
    sensed = server.cycle(request_, workspace)
    blind = server.cycle({**request_, "start": {"method": "open_loop"}}, workspace)
    used = blind["start"]
    assert used["method"] == "open_loop" and used["align_time"] == 0.5
    assert used["handover_rpm"] == pytest.approx(0.1 * start["rpm"])
    # The alignment is one more instant, at standstill, at the start current.
    assert len(blind["rpm"]) == len(sensed["rpm"]) + 1 and blind["rpm"][0] == 0
    peak = used["current"] * 2**0.5
    assert blind["i_peak"][0] == pytest.approx(peak)
    below = [i for n, i in zip(blind["rpm"], blind["i_peak"]) if abs(n) < used["handover_rpm"]]
    above = [(n, i) for n, i in zip(blind["rpm"], blind["i_peak"]) if abs(n) >= used["handover_rpm"]]
    assert below and all(i == pytest.approx(peak) for i in below)
    # Past the handover the two drives ask the same of the stage.
    assert [i for _, i in above] == pytest.approx([i for n, i in zip(sensed["rpm"], sensed["i_peak"]) if abs(n) >= used["handover_rpm"]])
    # A fan asks for almost nothing at low speed, so the held current is what heats the start.
    assert blind["p_stage"][1] > 3 * sensed["p_stage"][0]
    assert blind["summary"]["loss_energy"] > sensed["summary"]["loss_energy"]
    # Signal injection finds the rotor at standstill: no extra current.
    injected = server.cycle({**request_, "start": {"method": "injection"}}, workspace)
    assert injected["i_peak"] == pytest.approx(sensed["i_peak"])


def test_induction_builds_flux_first_and_brushed_motors_need_no_start(workspace) -> None:
    motors = server.setup(workspace)["motors"]
    for kind, applies in (("induction", "flux"), ("dc", "none"), ("stepper", "none")):
        start = page.STARTING[kind]
        preset = page.load_presets(kind, start["rpm"], start["torque"])[0]
        out = server.cycle({
            "motor": {"type": kind, **motors[kind]["values"]}, "conditions": {**start, "t_sink": 60},
            "supply": "battery", "device": "example", "load": preset["load"],
            "profile": {"start_angle_deg": 0, "segments": preset["segments"]},
        }, workspace)
        assert out["start"]["applies"] == applies
        if kind == "induction":
            assert out["rpm"][0] == 0 and out["torque"][0] == 0 and out["i_peak"][0] > 0
            assert out["start"]["flux_time"] > 0


def test_charging_the_link_costs_as_much_as_it_stores() -> None:
    from motionsim.starting import inrush

    found = inrush(400.0, 470e-6, 47.0)
    assert found.energy == pytest.approx(0.5 * 470e-6 * 400**2)
    assert found.peak == pytest.approx(400 / 47) and found.time == pytest.approx(3 * 47 * 470e-6)
    assert inrush(400.0, 470e-6, None).peak is None


def test_what_a_device_can_drive_and_how_much_heavier_the_load_could_be(workspace) -> None:
    motors = server.setup(workspace)["motors"]
    start = page.STARTING["pmsm"]
    request_ = {"motor": {"type": "pmsm", **motors["pmsm"]["values"]}, "conditions": {**start, "t_sink": 60},
                "supply": "battery", "device": "example"}
    can = page.capability(request_, workspace)
    here = can["design"]
    assert here["torque"] > 0 and here["why"]
    assert len(can["edge"]) == len(can["rpm"]) and can["edge"][0]["torque"] > 0  # at standstill too
    by_f = [x["torque"] for x in can["by_f_sw"]]
    assert by_f == sorted(by_f, reverse=True)
    fan = next(p for p in page.load_presets("pmsm", start["rpm"], start["torque"]) if p["id"] == "conveyor")
    found = page.largest({**request_, "load": fan["load"], "profile": {"start_angle_deg": 0, "segments": fan["segments"]}}, workspace)
    assert found["scale"] >= 1.0 and (found["open"] or found["why"])
    # Just past the limit the same request fails; at it, it does not.
    if not found["open"]:
        over = page._scaled({**request_, "load": fan["load"], "profile": {"start_angle_deg": 0, "segments": fan["segments"]}}, 1.05 * found["scale"])
        try:
            failing = [c for c in server.cycle(over, workspace)["checks"] if c["level"] == "fail"]
        except server.Refused:
            failing = ["refused"]
        assert failing
