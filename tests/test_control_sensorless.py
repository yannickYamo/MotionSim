"""A drive with no encoder through its transients: the start from rest is given the time its
own loops take and reaches the speed, a start it cannot make is said not to apply, a step that
is not over says so, and an observer taken under the speed it can read at says it lost the rotor."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import design, posted, started, workspace

from motionsim.control import scenario
from motionsim.control.blocks import Context
from motionsim.control.presets import BUILDERS, foc_servo
from motionsim.control.regulators import SpeedPi
from motionsim.control.sensorless import sensorless, start_ramp, starting_torque
from motionsim.service.routes import dispatch

KEY = "example-mosfet"
RPM = 30.0 / math.pi


@pytest.fixture(scope="module")
def ws():
    return workspace()


def exploration(ws, key: str, name: str = "sensorless_start") -> dict:
    listed = posted("/api/control/explorations", started(key, ws), ws)["explorations"]
    return next(e for e in listed if e["id"] == name)


def test_the_ramp_of_an_open_loop_start_is_a_share_of_what_the_current_spares_beside_the_load() -> None:
    # 30 A along the rotor's q axis makes 1.5·7·0.0105·30 = 3.3075 N·m. Against 1.3075 N·m of
    # load 2 N·m is spare; a quarter of it on 5e-4 kg·m² is 1000 rad/s², 7000 rad/s² electrical:
    # the current makes more than the load's most, and the start has no damping but its margin.
    d = design(i_limit=60.0, load_standstill=1.3075)
    assert starting_torque(d, 30.0) == pytest.approx(3.3075)
    assert start_ramp(d, 30.0) == pytest.approx(7000.0)
    block = next(b for b in sensorless(d).blocks if b.kind == "if_startup")
    assert block.params["current"] == pytest.approx(30.0) and block.params["ramp"] == pytest.approx(7000.0)
    # With nothing loading the shaft: a quarter of 3.3075 N·m, 11576.25 rad/s² electrical.
    assert start_ramp(design(i_limit=60.0), 30.0) == pytest.approx(11576.25)
    # A load whose peak in a turn asks more than the current makes (its mean less) is ridden
    # through on the inertia: half of what is spare over the mean, 1.3075 N·m here.
    peaky = design(i_limit=60.0, load_standstill=4.0, load_rest_mean=2.0)
    assert start_ramp(peaky, 30.0) == pytest.approx(7 * 0.5 * (3.3075 - 2.0) / 5e-4)


def test_a_start_is_given_the_open_loop_ramp_the_run_up_and_the_speed_loop_s_own_time() -> None:
    d = design(i_limit=60.0)
    scheme = sensorless(d)
    start = next(b for b in scheme.blocks if b.kind == "if_startup").params
    speed = next(b for b in scheme.blocks if b.kind == "speed_pi").params
    # A tenth of the design's 1466 rad/s electrical would hand over at 147 rad/s: under ten
    # times the 5 Hz whose back-EMF the phase-locked loop still locks onto, so it is that.
    assert start["handover"] == pytest.approx(10.0 * 2.0 * math.pi * 5.0)
    open_loop = 0.02 + start["handover"] / start["ramp"] + start["blend"]
    assert scenario.open_loop_time(scheme) == pytest.approx(open_loop)
    run_up = 5e-4 * (2000.0 / RPM) / d.torque_limit
    # The loop's own settling: thirty time constants J/Kp, or four of the integral's Kp/Ki
    # where that is slower.
    closing = max(30.0 * 5e-4 / speed["kp"], 4.0 * speed["kp"] / speed["ki"])
    assert scenario.start_time(d, scheme, 2000.0) == pytest.approx(open_loop + 1.5 * run_up + closing + 0.05)
    assert scenario.defaults("start", d, scheme)["duration"] == pytest.approx(scenario.start_time(d, scheme, 2000.0))
    # A scheme with an encoder and a torque command has neither wait.
    torque = BUILDERS["foc_torque"](d)
    assert scenario.start_time(d, torque, 2000.0) == pytest.approx(max(1.5 * run_up + 0.05, 0.1))


def test_a_step_is_given_the_run_up_and_the_settling_of_the_speed_loop_the_scheme_really_has() -> None:
    d = design()
    scheme = foc_servo(d)
    block = next(b for b in scheme.blocks if b.kind == "speed_pi")
    kp, ki = block.params["kp"], block.params["ki"]
    run_up = 5e-4 * 0.1 * d.omega / d.torque_limit
    settle = max(30.0 * 5e-4 / kp, 4.0 * kp / ki)
    by_rule = scenario.defaults("speed_step", d, scheme)["duration"]
    assert by_rule == pytest.approx(0.02 + 1.5 * run_up + settle)
    block.params["kp"] *= 0.25  # a loop tuned four times slower
    slower = max(30.0 * 5e-4 / (0.25 * kp), 4.0 * 0.25 * kp / ki)
    assert scenario.defaults("speed_step", d, scheme)["duration"] == pytest.approx(0.02 + 1.5 * run_up + slower)
    # A hold starts settled, and keeps the rule's time.
    rule = scenario._rule_time(d, scheme)
    assert scenario.defaults("hold", d, scheme)["settle"] == pytest.approx(max(2 / d.f_out, 0.25 * rule))


def test_the_speed_regulator_holds_its_integral_while_the_loop_is_open() -> None:
    ctx = Context(ts=1e-4, f_carrier=1e4, v_dc=48.0, rs=0.03, ld=8e-5, lq=8e-5, psi=0.01, pole_pairs=7)
    block = SpeedPi("speed", {"kp": 0.1, "ki": 2.0, "limit": 5.0}, ctx)
    block.reset()
    for _ in range(500):
        out = block.step(0.0, 100.0, 90.0, 1.0)
    assert out[3] == 0.0 and out[0] == pytest.approx(0.1 * 10.0)  # Kp·e alone
    for _ in range(500):
        out = block.step(0.0, 100.0, 90.0, 0.0)
    assert out[3] == pytest.approx(2.0 * 1e-4 * 10.0 * 500)  # Ki·Ts·e, five hundred times
    # Left unwired the input reads nought: the regulator integrates as it always did.
    assert [p.name for p in SpeedPi.inputs if p.optional] == ["open"]


def test_the_start_reaches_its_speed_with_each_starting_current(ws) -> None:
    found = exploration(ws, KEY)
    assert found["applies"] and found["expects"].startswith("the motor reaches its speed with a starting current")
    answer = posted("/api/control/sweep", {**started(KEY, ws), "exploration": "sensorless_start"}, ws)
    asked = found["scenario"]["to_rpm"] / RPM
    for v in answer["variants"]:
        assert v["step"]["rise_time"] is not None
        assert abs(v["step"]["steady_state_error"]) < 0.02 * asked, v["label"]
        assert not [c for c in v["checks"] if c["topic"] == "tracking"], v["checks"]
    assert not any("did not reach" in line for line in answer["said"])
    assert answer["said"][0].startswith("rise time:")


@pytest.mark.parametrize("key", (KEY, "example-mosfet-40v"))
def test_through_the_open_loop_start_the_speed_regulator_s_integral_stands_still(ws, key: str) -> None:
    # While the angle is the imposed one the regulator's torque is followed by nothing: a
    # regulator that integrated the run-up's error would hand over a torque of several times
    # the load's and carry the shaft past its speed when the loop is closed. Held, the speed
    # comes in within the 2% band it settles in.
    found = exploration(ws, key)
    base = started(key, ws)
    answer = posted(
        "/api/control/run",
        {**base, "scheme": "sensorless_flux", "fidelity": "averaged", "scenario": found["scenario"], "points": 2000},
        ws,
    )
    wires = answer["series"]["wires"]
    held = np.array(wires["speed.int"])[np.array(wires["position.open"]) > 0.5]
    assert held.size > 100 and np.ptp(held) == 0.0
    assert answer["step"]["overshoot"] < 0.02


def test_a_start_cut_short_says_first_that_the_speed_was_not_reached(ws) -> None:
    # An eighth of the time the start is given (its run-up with room to spare, and the loop's
    # settling): the run ends in the open-loop ramp or just past it.
    found = exploration(ws, KEY)
    short = {**found["scenario"], "duration": round(found["scenario"]["duration"] / 8.0, 3)}
    base = started(KEY, ws)
    answer = posted("/api/control/sweep", {**base, "exploration": "sensorless_start", "scenario": short}, ws)
    assert all(v["level"] != "ok" for v in answer["variants"])
    lead = answer["said"][: len(answer["variants"])]
    assert all("the speed did not reach 900 rpm within the run" in line for line in lead), answer["said"]
    one = posted(
        "/api/control/run",
        {**base, "scheme": "sensorless_flux", "scenario": short, "fidelity": "averaged", "points": 500},
        ws,
    )
    (check,) = [c for c in one["checks"] if c["topic"] == "tracking"]
    assert check["level"] == "caution" and check["field"] == "scenario.duration"
    end = one["series"]["wires"]["plant.omega_m"][-1] * RPM
    assert f"it ends at {float(f'{end:.3g}'):g} rpm" in check["message"]


def test_where_the_load_at_rest_is_more_than_the_starting_current_gives_the_start_does_not_apply(ws) -> None:
    # The made-up part whose load asks a constant 2 N·m, 0.05 N·m of friction, a pulsation of
    # 1.5 N·m and 0.9 N·m to break away: 4.45 N·m at the worst angle, of a shaft leaving rest.
    base = started("example-sic", ws)
    load = base["load"]
    worst = (
        load["constant_torque"] + load["friction_coulomb"] + load["pulsation"]["torque"] + load["breakaway"]["torque"]
    )
    assert worst == pytest.approx(4.45)
    told = posted("/api/control/presets", base, ws)["design"]
    assert told["load_standstill"] == pytest.approx(worst, rel=2e-3)
    found = exploration(ws, "example-sic")
    assert found["applies"] is False
    # The most of the currents gone through, 0.7 of the drive's limit of 8.49 A, on 1.5·p·ψ of
    # 0.448 N·m/A: 2.66 N·m, against 2.95 N·m on the mean over a turn at rest (the scheme's own
    # starting current is sized to the load, and starts it: test_control_defaults.py).
    assert found["why_not"].startswith(
        "the load asks 2.95 N·m of a shaft leaving rest on the mean over a turn, and the largest starting current "
        "gone through, 5.94 A peak, gives 2.66 N·m at the most: the rotor cannot follow the open-loop ramp"
    )
    # Four figures at the shaft say it as well.
    easy = {k: v for k, v in started(KEY, ws).items() if k != "load"}
    told = posted("/api/control/presets", {**easy, "shaft": {"inertia": 1e-3, "constant": 1.25}}, ws)["design"]
    assert told["load_standstill"] == pytest.approx(1.25)
    assert exploration(ws, KEY)["applies"] is True


def reversal(ws, scheme: str) -> dict:
    base = started(KEY, ws)
    rpm = 0.5 * base["conditions"]["rpm"]
    test = {"kind": "speed_step", "from_rpm": rpm, "to_rpm": -rpm}
    return posted(
        "/api/control/run", {**base, "scheme": scheme, "scenario": test, "fidelity": "averaged", "points": 1500}, ws
    )


def test_an_observer_of_the_back_emf_taken_through_standstill_says_it_lost_the_rotor(ws) -> None:
    answer = reversal(ws, "sensorless_smo")
    wires = answer["series"]["wires"]
    worst = float(np.degrees(np.abs(wires["observer.error"]).max()))
    assert worst > 90.0  # it did lose it
    pairs = started(KEY, ws)["motor"]["pole_pairs"]
    # Under the back-EMF of 5 Hz the loop has nothing to lock onto: 300/p rpm.
    floor = float(f"{300.0 / pairs:.3g}")
    said = [c["message"] for c in answer["checks"] if c["topic"] == "tracking"]
    assert any(m.startswith(f"the observer loses the rotor below {floor:g} rpm") for m in said), said
    assert answer["level"] != "ok"


def test_a_loop_that_runs_away_after_its_observer_lost_the_rotor_is_refused_for_that(ws) -> None:
    base = started(KEY, ws)
    rpm = 0.5 * base["conditions"]["rpm"]
    test = {"kind": "speed_step", "from_rpm": rpm, "to_rpm": -rpm}
    status, body = dispatch(
        "/api/control/run", {**base, "scheme": "sensorless_emf", "scenario": test, "fidelity": "averaged"}, ws
    )
    pairs = base["motor"]["pole_pairs"]
    if status == 200:  # it came through: then it says what it passed
        said = [c["message"] for c in body["checks"] if c["topic"] == "tracking"]
        assert any("the observer loses the rotor below" in m for m in said), said
        return
    assert status == 422 and body["field"] == "scenario"
    assert f"after the observer loses the rotor below {float(f'{300.0 / pairs:.3g}'):g} rpm" in body["refused"]
    assert "encoder" in body["fix"]


def test_a_reversal_that_ends_short_of_its_speed_says_so(ws) -> None:
    # The run cut off at half the time the speed takes to arrive (read from the full run): it
    # ends short of its speed, and says so.
    full = reversal(ws, "sensorless_smo")
    times, speeds = full["series"]["t"], full["series"]["wires"]["plant.omega_m"]
    arrived = next(t for t, w in zip(times, speeds, strict=True) if w * RPM < -0.98 * 1500.0)
    base = started(KEY, ws)
    rpm = 0.5 * base["conditions"]["rpm"]
    test = {"kind": "speed_step", "from_rpm": rpm, "to_rpm": -rpm, "duration": 0.5 * arrived}
    answer = posted(
        "/api/control/run",
        {**base, "scheme": "sensorless_smo", "scenario": test, "fidelity": "averaged", "points": 1500},
        ws,
    )
    end = answer["series"]["wires"]["plant.omega_m"][-1] * RPM
    assert abs(end + 1500.0) > 30.0
    said = [c["message"] for c in answer["checks"] if c["topic"] == "tracking"]
    assert any(m.startswith("the speed did not reach -1500 rpm within the run") for m in said), said


def test_a_reversal_with_an_encoder_carries_neither_check(ws) -> None:
    answer = reversal(ws, "foc_servo")
    assert not [c for c in answer["checks"] if c["topic"] == "tracking"], answer["checks"]
    assert answer["series"]["wires"]["plant.omega_m"][-1] * RPM == pytest.approx(-1500.0, rel=0.005)
