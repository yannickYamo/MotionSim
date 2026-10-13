"""What the engine, the command line, a design file and the page's addresses must do, each held by
a figure worked out apart from the code."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from motionsim import recommend
from motionsim.device import load_device
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint, Pwm, solve
from motionsim.load import Gravity, Load, Profile, Segment
from motionsim.motor.machines import ADAPTER
from motionsim.motor.stage import Unreachable
from motionsim.transient import follow

SOURCE = Path(__file__).parent.parent / "src" / "motionsim"
EXAMPLE, EXAMPLE_MOSFET = SOURCE / "example_device.yaml", SOURCE / "example_mosfet.yaml"

GATE = dict(v_drive=10, rg_on=5, rg_off=3)


def point(v_dc: float, **more) -> OperatingPoint:
    return OperatingPoint(v_dc=v_dc, i_rms=0, modulation_index=0, power_factor=1, f_sw=20000, t_sink=40, **GATE, **more)


def duty(p) -> float:
    return {k: v for k, v, _ in p.stage.summary}["duty cycle"]


@pytest.mark.parametrize(("rpm", "torque"), [(2500, 0.4), (1000, 0.2), (200, 0.4)])
def test_a_bipolar_h_bridge_swings_the_link_current_both_ways(rpm, torque) -> None:
    # One diagonal for a share s of the period, the other for the rest: the link gives +I,
    # then takes it back, and the winding sees +V then -V.
    fet = load_device(EXAMPLE_MOSFET)
    motor = ADAPTER.validate_python(dict(type="dc", kt=0.05, r=0.4, l=0.0006, drive="bipolar"))
    p = at_speed_and_torque(fet, motor, rpm, torque, point(24, t_dead=100e-9))
    current = torque / 0.05
    volts = 0.05 * rpm * math.pi / 30 + 0.4 * current
    s = (1 + volts / 24) / 2
    assert p.capacitor_rms == pytest.approx(2 * current * math.sqrt(s * (1 - s)), rel=1e-6)
    assert p.ripple_pp == pytest.approx(2 * 24 * s * (1 - s) / (0.0006 * 20000), rel=1e-6)


def test_a_unipolar_h_bridge_keeps_its_figures() -> None:
    fet = load_device(EXAMPLE_MOSFET)
    motor = ADAPTER.validate_python(dict(type="dc", kt=0.05, r=0.4, l=0.0006, drive="unipolar"))
    p = at_speed_and_torque(fet, motor, 2500, 0.4, point(24, t_dead=100e-9))
    d = (0.05 * 2500 * math.pi / 30 + 0.4 * 8) / 24
    assert p.capacitor_rms == pytest.approx(8 * math.sqrt(d * (1 - d)), rel=1e-6)
    assert p.ripple_pp == pytest.approx(24 * d * (1 - d) / (0.0006 * 20000), rel=1e-6)


@pytest.mark.parametrize(("rpm", "torque"), [(2000, 1.0), (3500, 0.5), (-2000, 1.0)])
def test_block_commutation_ripples_through_two_phases_in_series(rpm, torque) -> None:
    # The third phase carries nothing: the chopped voltage is across the phase-to-phase inductance.
    fet = load_device(EXAMPLE_MOSFET)
    motor = ADAPTER.validate_python(dict(type="bldc", pole_pairs=7, kt=0.09, r=0.08, l=0.00012))
    p = at_speed_and_torque(fet, motor, rpm, torque, point(48, t_dead=100e-9))
    current = torque / 0.09
    back_emf = 0.09 * abs(rpm) * math.pi / 30
    d = abs(back_emf + 0.08 * current if rpm > 0 else 0.08 * current - back_emf) / 48
    assert p.ripple_pp == pytest.approx(48 * d * (1 - d) / (0.00012 * 20000), rel=1e-6)
    assert p.capacitor_rms == pytest.approx(current * math.sqrt(d * (1 - d)), rel=1e-6)


@pytest.mark.parametrize(
    ("motor", "v_dc", "rpm", "torque"),
    [
        (dict(type="dc", kt=0.05, r=0.4), 24, 4500, 0.05),  # 23.96 V of 24
        (dict(type="bldc", pole_pairs=7, kt=0.09, r=0.08), 48, 4950, 0.5),  # 47.10 V of 48
    ],
)
def test_every_motor_is_held_to_the_voltage_the_stage_gives(motor, v_dc, rpm, torque) -> None:
    fet = load_device(EXAMPLE_MOSFET)
    machine = ADAPTER.validate_python(motor)
    op = point(v_dc, t_dead=1e-6)  # 2 * 1 us * 20 kHz: 4% of the voltage gone before any drop
    assert at_speed_and_torque(fet, machine, rpm, torque, op, ripple=False).result.p_inverter > 0
    with pytest.raises(Unreachable, match=r"more than the DC link gives through this stage \((\d+\.?\d*) V of"):
        at_speed_and_torque(fet, machine, rpm, torque, op)
    try:
        at_speed_and_torque(fet, machine, rpm, torque, op)
    except Unreachable as exc:
        given = float(re.search(r"\(([\d.]+) V of", str(exc)).group(1))
    assert 0.90 * v_dc < given < 0.96 * v_dc


def test_a_stepper_is_held_to_the_voltage_the_stage_gives() -> None:
    fet = load_device(EXAMPLE_MOSFET)
    motor = ADAPTER.validate_python(
        dict(type="stepper", steps_per_rev=200, holding_torque=1.0, i_phase=2.0, r=1.0, l=0.003)
    )
    op = point(48, t_dead=1e-6)
    # The speed at which the full link is just enough is past what the stage can give.
    low, high = 1.0, 20000.0
    for _ in range(60):
        mid = (low + high) / 2
        try:
            at_speed_and_torque(fet, motor, mid, 0.5, op, ripple=False)
            low = mid
        except Unreachable:
            high = mid
    with pytest.raises(Unreachable, match="gives through this stage"):
        at_speed_and_torque(fet, motor, 0.99 * low, 0.5, op)


@pytest.mark.parametrize("mass", [3.0, 8.0, 14.0])
def test_a_hold_settles_at_the_rotor_position_that_leaves_a_junction_hottest(mass) -> None:
    # At 3 and 8 kg the diode ends hotter than the switch, though the switch loses more.
    igbt = load_device(EXAMPLE)
    motor = ADAPTER.validate_python(dict(type="pmsm", pole_pairs=4, flux_linkage=0.10, ld=0.008, lq=0.008, rs=1.0))
    base = OperatingPoint(
        v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=60, pwm=Pwm.space_vector
    )
    hold = Profile(start_angle_deg=90, segments=[Segment(duration=60.0, speed_start=0, speed_end=0)])
    _, trace = follow(igbt, motor, Load(gravity=Gravity(mass=mass, arm=0.1)), hold, base)
    steady = at_speed_and_torque(igbt, motor, 0.0, mass * 9.80665 * 0.1, base).result
    hottest = max(steady.tj_switch_peak, steady.tj_diode_peak)
    assert trace.tj[-1] == pytest.approx(hottest, abs=0.1)


def test_a_transistor_stage_with_no_current_still_pays_for_its_switching() -> None:
    fet = load_device(EXAMPLE_MOSFET)
    at = lambda i: (
        solve(
            fet, OperatingPoint(v_dc=48, i_rms=i, modulation_index=0.8, power_factor=0.8, f_sw=20000, t_sink=60, **GATE)
        ).p_inverter
    )
    # Six positions, each the one that switches for half the period, each event taking the
    # output charge through the link voltage: 1.5e-7 C at 50 V, going with the root of the voltage.
    expected = 6 * 0.5 * 1.5e-7 * math.sqrt(48 / 50) * 48 * 20000
    assert at(0.0) == pytest.approx(expected, rel=1e-3)
    assert at(0.0) == pytest.approx(at(1e-4), rel=1e-3)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (dict(f_sw=-8000.0), "switching frequency cannot be negative"),
        (dict(i_rms=float("nan")), "current is not a number"),
        (dict(i_rms=-10.0), "current cannot be negative"),
        (dict(power_factor=2.0), "between -1 and 1"),
        (dict(t_sink=float("inf")), "temperature is not a number"),
        (dict(f_out=float("nan")), "output frequency is not a number"),
        (dict(v_dc=-300.0), "DC voltage has to be above zero"),
        (dict(v_dc=0.0), "DC voltage has to be above zero"),
        (dict(modulation_index=-0.5), "modulation index cannot be negative"),
        (dict(parallel=0), "at least one device"),
        (dict(rg_on=-5.0), "turn-on gate resistance cannot be negative"),
        (dict(t_dead=1e-3), "whole switching period"),
    ],
)
def test_figures_that_are_not_an_operating_point_are_refused(change, said) -> None:
    base = dict(v_dc=300.0, i_rms=10.0, modulation_index=0.8, power_factor=0.8, f_sw=8000.0, t_sink=60.0)
    OperatingPoint(**base)
    with pytest.raises(ValueError, match=said):
        OperatingPoint(**{**base, **change})


def test_an_operating_point_may_be_cold_stopped_or_regenerating() -> None:
    OperatingPoint(v_dc=300, i_rms=0, modulation_index=0, power_factor=-1, f_sw=0, t_sink=-40, f_out=0)


@pytest.mark.parametrize("amps", [10.0, 20.0, 80.0])
def test_the_gate_resistor_line_counts_the_recovery_charge_the_current_brings(amps) -> None:
    fet = load_device(EXAMPLE_MOSFET)
    op = OperatingPoint(
        v_dc=48, i_rms=amps / math.sqrt(2), modulation_index=0.8, power_factor=0.8, f_sw=20000, t_sink=60, **GATE
    )
    rec = recommend.gate_resistors(fet, op, amps)
    line = next(text for text in rec.lines if "switching event" in text)
    on, off = (float(x) for x in re.findall(r"([\d.]+) µJ", line))
    moved = 2.0e-8 - 1.304e-8 + 1.4e-8
    recovered = 1.2e-7 * min(amps / 50.0, 1.0)
    e_on = 0.5 * 48 * amps * moved * rec.value["rg_on"] / (10 - 4.6) + (1.5e-7 * math.sqrt(48 / 50) + recovered) * 48
    e_off = 0.5 * 48 * amps * moved * rec.value["rg_off"] / 4.6
    assert on == pytest.approx(e_on * 1e6, rel=6e-3)  # written to three figures
    assert off == pytest.approx(e_off * 1e6, rel=6e-3)
    assert np.isfinite(on)


# The interfaces: the command line, design files and the page's own addresses.

import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

import yaml  # noqa: E402

from motionsim import cli, design, guard, page, server  # noqa: E402


@pytest.fixture()
def workspace(tmp_path):
    return page.Workspace(tmp_path / "ws")


def design_file(tmp_path, **changes) -> Path:
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "--device", "example-mosfet", "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text())
    for key, value in changes.items():
        setup[key] = {**setup.get(key, {}), **value} if isinstance(value, dict) else value
    file.write_text(yaml.safe_dump(setup))
    return file


def run_design(file, capsys) -> tuple[int, dict]:
    capsys.readouterr()
    code = cli.main(["design", "run", str(file), "--json", "--skip", "drive", "--skip", "build"])
    return code, json.loads(capsys.readouterr().out)


def test_a_part_that_cannot_do_the_motion_does_not_pass(tmp_path, capsys) -> None:
    # 400 N·m of friction at the load is far past what the motor's 40 A gives through the gear.
    code, out = run_design(design_file(tmp_path, load={"friction_coulomb": 400}), capsys)
    assert out["verdict"]["candidates"][0]["level"] != "fail"  # the design point alone is fine
    assert any(c["level"] == "fail" for c in out["motion"]["checks"])
    assert out["outcome"] == "does not pass" and code == 3


def test_a_junction_estimated_above_its_rating_fails_whatever_the_range_says() -> None:
    fet = load_device(EXAMPLE_MOSFET)
    op = OperatingPoint(v_dc=48, i_rms=20, modulation_index=0.8, power_factor=0.8, f_sw=20000, t_sink=60, **GATE)
    result = solve(fet, op)
    low, high = result.tj_peak_range
    assert low < high
    # A rating between the low end of the range and the estimate itself: the estimate is over it.
    estimate = max(result.tj_switch_peak, result.tj_diode_peak)
    assert low < estimate
    weak = fet.model_copy(update={"ratings": fet.ratings.model_copy(update={"tj_max": (low + estimate) / 2})})
    found = [c for c in guard.check(weak, op, result, 20 * math.sqrt(2)) if c.topic == "temperature"]
    assert found and found[0].level is guard.Level.fail and "above the" in found[0].message


@pytest.mark.parametrize(("parallel", "said"), [(2.5, "whole number"), (0, "cannot be below 1"), (13, "above 12")])
def test_devices_in_parallel_are_a_whole_number_from_1_to_12(tmp_path, capsys, parallel, said) -> None:
    code, out = run_design(design_file(tmp_path, conditions={"parallel": parallel}), capsys)
    assert code == 2 and said in out["refused"] and out["field"] == "parallel"


@pytest.mark.parametrize(
    "change",
    [
        {"load": {"gear_ratio": float("inf")}},
        {"profile": {"segments": 5}},
        {"profile": {"segments": [{"duration": 1, "speed_start": 0, "speed_end": float("inf")}]}},
        {"conditions": {"v_drive": 3, "rg_on": 5, "rg_off": 5}},
        {"heatsink": {"rth": 1, "c": 500}},
        {"devices": ["x" * 5000]},
    ],
)
def test_a_design_that_cannot_be_worked_with_is_refused_not_a_fault(tmp_path, capsys, change) -> None:
    file = design_file(tmp_path, **change)
    capsys.readouterr()
    code = cli.main(["design", "run", str(file), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and (out.get("refused") or out.get("refusals")), (code, out.get("outcome"))


def test_a_motor_with_no_kind_named_is_a_permanent_magnet_one(tmp_path, capsys) -> None:
    file = design_file(tmp_path)
    setup = yaml.safe_load(file.read_text())
    assert setup["motor"].pop("type") == "pmsm"
    file.write_text(yaml.safe_dump(setup))
    code, out = run_design(file, capsys)
    assert code == 0 and out["outcome"].startswith("passes")


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (
            [
                "simulate",
                "no-such-file.yaml",
                "--vdc",
                "300",
                "--irms",
                "10",
                "--m",
                "0.9",
                "--pf",
                "0.85",
                "--fsw",
                "8000",
                "--tsink",
                "60",
            ],
            "cannot simulate: No such file",
        ),
        (
            [
                "max-current",
                str(EXAMPLE_MOSFET),
                "--vdc",
                "48",
                "--m",
                "0.9",
                "--pf",
                "0.85",
                "--fsw",
                "8000",
                "--tsink",
                "60",
            ],
            "cannot max-current: this device has no measured switching energy",
        ),
        (["design", "run", "no-such-design.yaml"], "no-such-design.yaml"),
    ],
)
def test_the_command_line_says_what_is_wrong_in_a_line(capsys, argv, said) -> None:
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert said in err and "Traceback" not in err


@pytest.mark.parametrize(
    "more",
    [
        ["--irms", "nan"],
        ["--tsink", "inf"],
        ["--m", "5"],
        ["--parallel", "0"],
        ["--fsw", "-8000"],
    ],
)
def test_the_command_line_takes_no_figure_that_is_not_one(capsys, more) -> None:
    base = {"--vdc": "300", "--irms": "10", "--m": "0.9", "--pf": "0.85", "--fsw": "8000", "--tsink": "60"}
    base[more[0]] = more[1]
    argv = ["simulate", str(EXAMPLE)] + [x for pair in base.items() for x in pair]
    try:
        code = cli.main(argv)
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    assert code not in (0, None) and "power-stage loss" not in out.out


def test_the_margin_printed_is_to_the_top_of_the_range(capsys) -> None:
    argv = ["--vdc", "300", "--irms", "10", "--m", "0.9", "--pf", "0.85", "--fsw", "8000", "--tsink", "60"]
    assert cli.main(["simulate", str(EXAMPLE), *argv]) == 0
    out = capsys.readouterr().out
    margin = float(re.search(r"margin to Tj max\s+([\d.]+)", out).group(1))
    top = float(re.search(r"hottest junction\s+[\d.]+ to ([\d.]+)", out).group(1))
    assert margin == pytest.approx(load_device(EXAMPLE).ratings.tj_max - top, abs=0.06)


def test_no_scheme_worked_out_is_not_a_motor_that_decides_its_own() -> None:
    assert "no scheme could be worked out" in recommend.modulation({}, "space-vector").lines[0]
    assert "decides its own" in recommend.modulation({"block": 1.0}, "block").lines[0]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda d: d["switch"]["thermal"].__setitem__("r", [float("nan")]), "thermal"),
        (lambda d: d["ratings"].__setitem__("tj_max", -40), "tj_max"),
        (lambda d: d["ratings"].__setitem__("tj_max", float("inf")), "tj_max"),
    ],
)
def test_a_device_file_with_a_figure_that_is_not_one_is_refused_by_name(workspace, change, said) -> None:
    data = yaml.safe_load(EXAMPLE_MOSFET.read_text())
    change(data)
    with pytest.raises(page.Refused, match=said):
        page.add_device("bad.yaml", yaml.dump(data), workspace)


def test_a_few_lines_that_stand_for_millions_of_figures_are_refused_at_once(workspace) -> None:
    text = "a: &a [1,1,1,1,1,1,1,1,1]\n" + "".join(
        f"{c}: &{c} [*{p},*{p},*{p},*{p},*{p},*{p},*{p},*{p},*{p}]\n"
        for p, c in zip("abcdefgh", "bcdefghi", strict=True)
    )
    began = time.perf_counter()
    with pytest.raises(page.Refused, match="far more figures"):
        page.add_device("bomb.yaml", text, workspace)
    assert time.perf_counter() - began < 5


def test_a_device_name_no_file_could_have_is_cut_to_one_that_can(workspace) -> None:
    out = page.add_device("n" * 5000 + ".yaml", EXAMPLE_MOSFET.read_text(), workspace)
    assert len(out["device"]["id"]) <= 80


def test_a_request_the_engine_cannot_work_with_is_refused_in_words(workspace) -> None:
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"], "i_sat": 1e-320}
    body = {"motor": motor, "conditions": {**page.STARTING["pmsm"], "t_sink": 60}, "devices": ["example-mosfet"]}
    answer = json.loads(page.call("/api/proposal", json.dumps(body), workspace))
    assert answer["status"] == 422 and answer["body"]["refused"]
    for payload in ("[]", '"x"', "1", "null", "[" * 100000):
        assert json.loads(page.call("/api/device", payload, workspace))["status"] == 400


def test_a_supply_of_zero_volts_is_refused_and_not_swapped_for_another(workspace) -> None:
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    with pytest.raises(page.Refused, match="supply voltage cannot be below 1"):
        page.motor_fit({"motor": motor, "device": "example-mosfet", "v_dc": 0}, workspace)


def test_over_http_a_malformed_request_gets_an_answer(workspace) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(workspace))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    address = f"http://127.0.0.1:{httpd.server_address[1]}"

    def status(path: str, body: bytes | None, headers: dict | None = None) -> int:
        try:
            return urllib.request.urlopen(
                urllib.request.Request(address + path, body, headers or {}), timeout=10
            ).status
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        assert status("/api/device", b"[]") == 400
        assert status("/api/typed", b"null") == 400
        assert status("/api/stage", b"[" * 100000) == 400
        assert status("/api/nope", None) == 404
        assert status("/api/stage", None) == 404
        assert status("/", None) == 200
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    ("v_dc", "said"), [(1200, "71% of the rating"), (1500, "88% of the rating"), (2000, "more than")]
)
def test_a_supply_past_the_highest_voltage_class_is_not_said_to_fit(v_dc, said) -> None:
    from motionsim.advise import advise

    motor = ADAPTER.validate_python(dict(type="dc", kt=0.5, r=2.0))
    line = next(text for text in advise(motor, 2000, 5.0, v_dc, 8e3).lines if text.startswith("Voltage"))
    assert "1700 V parts" in line and said in line and "keep" not in line


def test_a_supply_the_highest_class_covers_is_said_to_fit() -> None:
    from motionsim.advise import advise

    motor = ADAPTER.validate_python(dict(type="dc", kt=0.5, r=2.0))
    line = next(text for text in advise(motor, 2000, 5.0, 1000, 8e3).lines if text.startswith("Voltage"))
    assert "1700 V parts keep a 1000 V supply under 60%" in line  # 1000 / 1700 is 59%


def test_two_parts_under_names_that_read_alike_are_two_devices_and_a_file_dropped_again_is_one(workspace) -> None:
    text = EXAMPLE_MOSFET.read_text()
    other = text.replace("part_number: ", "part_number: OTHER-", 1)
    assert "OTHER-" in other
    first = page.add_device("a b.yaml", text, workspace)["device"]["id"]
    second = page.add_device("a_b.yaml", other, workspace)["device"]["id"]
    again = page.add_device("a b.yaml", text, workspace)["device"]["id"]
    second_again = page.add_device("a-b.yaml", other, workspace)["device"]["id"]
    assert (first, second, again, second_again) == ("a-b", "a-b-2", "a-b", "a-b-2")
    assert workspace.device("a-b").part_number != workspace.device("a-b-2").part_number


def test_a_dead_time_given_is_the_dead_time_reported(tmp_path, capsys) -> None:
    code, out = run_design(design_file(tmp_path, conditions={"t_dead": 3e-7}), capsys)
    assert code == 0 and out["verdict"]["candidates"][0]["gate"]["t_dead"] == pytest.approx(3e-7)


def proposal_at(workspace, **conditions) -> dict:
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    body = {
        "motor": motor,
        "conditions": {**page.STARTING["pmsm"], "t_sink": 60, **conditions},
        "devices": ["example-mosfet"],
    }
    return page.proposal(body, workspace)["candidates"][0]


def test_a_stage_may_switch_in_megahertz_and_its_switching_loss_goes_with_the_frequency(workspace) -> None:
    slow = proposal_at(workspace, f_sw=20e3, t_dead=50e-9, v_drive=10, rg_on=5, rg_off=3)["result"]
    fast = proposal_at(workspace, f_sw=1e6, t_dead=50e-9, v_drive=10, rg_on=5, rg_off=3)["result"]
    # Fifty times the events; the energy of each moves only as far as the junction warms.
    assert fast["switching"] / slow["switching"] == pytest.approx(50, rel=0.1)
    assert proposal_at(workspace, f_sw=5e6, t_dead=20e-9, v_drive=10, rg_on=5, rg_off=3)["result"] is not None
    with pytest.raises(page.Refused, match="switching frequency cannot be above 10,000,000"):
        proposal_at(workspace, f_sw=2e7)


def test_each_position_gives_its_junctions_on_average_beside_their_peaks(workspace) -> None:
    result = proposal_at(workspace)["result"]
    for position in result["positions"]:
        assert 60 < position["tj_switch_mean"] <= position["tj_switch"]
        assert position["tj_diode_mean"] <= position["tj_diode"]
    hottest = max(result["positions"], key=lambda p: p["tj"])
    assert hottest["tj"] == pytest.approx(result["tj_peak"])


def test_the_page_s_report_follows_the_device_on_its_drawing_though_another_passes_first(workspace) -> None:
    weak = yaml.safe_load(EXAMPLE.read_text())
    weak["part_number"] = "WEAK-1"
    weak["ratings"]["tj_max"] = 62
    page.add_device("weak.yaml", yaml.dump(weak), workspace)
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    body = {
        "motor": motor,
        "conditions": {"v_dc": 400, "rpm": 2000, "torque": 1.0, "f_sw": 20000, "t_sink": 60},
        "devices": ["weak", "example"],
    }
    usual = design.run(body, workspace, strict=False)
    asked = design.run({**body, "follow": "weak"}, workspace, strict=False)
    assert usual["followed"] == "example" and asked["followed"] == "weak"
    assert design.run({**body, "follow": "no-such-part"}, workspace, strict=False)["followed"] == "example"


def test_a_copy_carrying_measurements_is_named_as_one(workspace) -> None:
    data = json.loads((SOURCE.parent.parent / "examples" / "double_pulse_example.json").read_text())
    added = page.add_measurement("example", "bench.json", json.dumps(data), workspace)["device"]
    plain = next(d for d in page.setup(workspace)["devices"] if d["id"] == "example")
    assert added["id"] == "example-measured" and added["name"] == plain["name"] + ", measured"


def test_each_kind_of_motor_is_offered_only_the_loads_it_is_used_for() -> None:
    offered = {
        kind: [p["id"] for p in page.load_presets(kind, **{k: page.STARTING[kind][k] for k in ("rpm", "torque")})]
        for kind in page.STARTING
    }
    # A reluctance motor is not a washer's or a wheel's motor; nor is a stepper.
    for kind in ("synrm", "stepper"):
        assert not {"drum", "vehicle"} & set(offered[kind]), (kind, offered[kind])
    assert offered["synrm"] == ["fan", "conveyor"]
    # A washer drum: the permanent-magnet motor that drives it directly and the induction motor on its belt.
    assert [k for k, loads in offered.items() if "drum" in loads] == ["pmsm", "induction"]
    # A wheel: motors that can brake it, wound for a battery.
    assert [k for k, loads in offered.items() if "vehicle" in loads] == ["pmsm", "bldc", "dc"]
    # A series motor is offered only loads whose own torque stops them: it cannot brake.
    assert offered["dc_series"] == ["tool", "conveyor"]
    assert set(offered["bldc"]) == {"fan", "vehicle", "tool", "conveyor"} and offered["stepper"] == ["axis", "conveyor"]


def between_estimate_and_top(workspace, name: str = "open") -> tuple[str, float]:
    """A copy of the made-up module rated between its junction estimate and the top of its range."""
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    body = {"motor": motor, "conditions": {"v_dc": 400, "rpm": 2000, "torque": 1.0, "f_sw": 20000, "t_sink": 60}}
    found = page.proposal({**body, "devices": ["example"]}, workspace)["candidates"][0]
    estimate, top = found["result"]["tj_peak"], found["result"]["tj_range"][1]
    assert top - estimate > 1.0
    # Just above the estimate running and held still, and under the top of the range.
    rating = max(estimate, found["stall_tj"]) + 0.3
    assert rating < top
    data = yaml.safe_load(EXAMPLE.read_text())
    data["part_number"] = "OPEN-1"
    data["ratings"]["tj_max"] = rating
    page.add_device(f"{name}.yaml", yaml.dump(data), workspace)
    return name, rating


def test_a_range_that_crosses_the_rating_is_undecided_neither_a_pass_nor_a_fail(workspace) -> None:
    name, rating = between_estimate_and_top(workspace)
    setup = page.setup(workspace)
    motor = {"type": "pmsm", **setup["motors"]["pmsm"]["values"]}
    body = {"motor": motor, "conditions": {"v_dc": 400, "rpm": 2000, "torque": 1.0, "f_sw": 20000, "t_sink": 60}}
    found = page.proposal({**body, "devices": [name, "example"]}, workspace)
    open_ = next(c for c in found["candidates"] if c["id"] == name)
    assert open_["level"] == "undecided"
    said = next(c for c in open_["checks"] if c["topic"] == "temperature")
    assert said["level"] == "undecided" and "crosses" in said["message"] and f"{rating:g}"[:4] in said["message"]
    # The part that is known to pass is ranked before the one the data cannot decide.
    assert [c["id"] for c in found["candidates"]] == ["example", name]
    assert any(
        "not decided by this data" in line for line in page.proposal({**body, "devices": [name]}, workspace)["explain"]
    )


def test_a_design_the_data_cannot_decide_says_so_and_exits_with_its_own_status(tmp_path, capsys, workspace) -> None:
    name, _ = between_estimate_and_top(workspace)
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "--device", "example", "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text())
    setup["devices"] = [str(workspace.paths()[name])]
    setup["conditions"] = {"v_dc": 400, "rpm": 2000, "torque": 1.0, "f_sw": 20000, "t_sink": 60}
    setup["motor"] = {"type": "pmsm", **page.setup(workspace)["motors"]["pmsm"]["values"]}
    file.write_text(yaml.safe_dump(setup))
    capsys.readouterr()
    code = cli.main(["design", "run", str(file), "--json", "--skip", "drive", "--skip", "build", "--skip", "motion"])
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "undecided" and code == 4
    assert cli.main(["design", "run", str(file), "--skip", "drive", "--skip", "build", "--skip", "motion"]) == 4
    report = capsys.readouterr().out
    assert "**Outcome: undecided.**" in report and "**Undecided, temperature.**" in report


def test_switching_faster_than_a_datasheet_model_follows_is_a_caution(workspace) -> None:
    gate = dict(t_dead=120e-9, v_drive=10, rg_on=5, rg_off=3)
    usual = proposal_at(workspace, f_sw=20e3, **gate)
    fast = proposal_at(workspace, f_sw=1e6, **gate)
    assert not [c for c in usual["checks"] if c["topic"] == "switching speed"]
    said = next(c for c in fast["checks"] if c["topic"] == "switching speed")
    # 2 x 120 ns of dead time in a 1 us period is 24%; the edges take less.
    assert said["level"] == "caution" and "1000 kHz" in said["message"] and "24%" in said["message"]
    assert fast["level"] != "ok"


@pytest.mark.parametrize("part", ["example", "example-mosfet"])
def test_every_kind_of_motor_opens_on_a_design_that_runs(workspace, part) -> None:
    # The example of each kind, wound for the part's supply, at the point the page starts it on.
    for kind, m in page.suggest({"device": part}, workspace)["motors"].items():
        body = {"motor": {"type": kind, **m["values"]}, "conditions": {**m["start"], "t_sink": 60}, "devices": [part]}
        found = page.proposal(body, workspace)["candidates"][0]
        assert found["result"] is not None and found["level"] != "fail", (part, kind, found["problem"])


def test_a_trajectory_takes_how_the_package_is_mounted(tmp_path, capsys) -> None:
    """The case stands over the heatsink by the layer's resistance times all the package loses."""
    assert cli.main(["template", "trajectory"]) == 0
    trace = tmp_path / "trace.csv"
    trace.write_text(capsys.readouterr().out)
    base = ["trajectory", "examples/synthetic_igbt_600v_30a.yaml", str(trace), "--vdc", "300", "--fsw", "8000"]

    def case_and_loss(*more: str) -> tuple[float, float]:
        assert cli.main([*base, "--tsink", "60", *more]) == 0
        said = capsys.readouterr().out
        figure = lambda label: float(re.search(rf"{label}\s+([\d.]+)", said).group(1))
        return figure("T case"), figure("power-stage loss")

    case, _ = case_and_loss("--rth-case-sink", "0")
    assert case == pytest.approx(60.0, abs=0.05)
    case, loss = case_and_loss("--rth-case-sink", "0.5")
    assert case == pytest.approx(60.0 + 0.5 * loss, abs=0.1)  # one six-pack: the package is the stage
    on_grease, _ = case_and_loss()
    on_a_pad, _ = case_and_loss("--interface", "pad")
    assert on_a_pad > on_grease + 1.0
    with pytest.raises(SystemExit, match="0 to 50 K/W"):
        cli.main([*base, "--tsink", "60", "--rth-case-sink", "80"])
